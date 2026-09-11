"""P1-03 发行包便携数据策略门（构建契约）测试。

真实 onedir ZIP 在 P2-01 才产生；本文件先用合成 staging 目录把契约锁死：发行包不得
携带真实 ``data/``、用户 ``config.toml``、模型权重或文档缓存，发行说明必须明确告知
删除整个便携目录会删除配置与缓存，并给出旧 data 的受控导入方式。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = REPO_ROOT / "packaging" / "windows" / "data_policy.py"


def _load_policy() -> ModuleType:
    spec = importlib.util.spec_from_file_location("windows_data_policy", POLICY_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _staging_tree(policy: ModuleType, root: Path) -> Path:
    """构造一个合法发行 staging 树：顶层启动器 + app/ 运行时目录。"""

    (root / policy.APP_DIRECTORY).mkdir(parents=True, exist_ok=True)
    (root / policy.LAUNCHER_EXECUTABLE).write_bytes(b"launcher")
    (root / policy.APP_DIRECTORY / "PDF Reader Service.exe").write_bytes(b"service")
    return root


def test_staging_tree_without_data_directory_passes(tmp_path: Path) -> None:
    policy = _load_policy()

    assert policy.audit_artifact_tree(_staging_tree(policy, tmp_path / "artifact")) == []


def test_empty_data_scaffold_is_allowed(tmp_path: Path) -> None:
    policy = _load_policy()
    artifact = _staging_tree(policy, tmp_path / "artifact")
    (artifact / policy.DATA_DIRECTORY).mkdir()

    assert policy.audit_artifact_tree(artifact) == []


def test_real_portable_data_is_rejected_category_by_category(tmp_path: Path) -> None:
    policy = _load_policy()
    artifact = _staging_tree(policy, tmp_path / "artifact")
    leaked = (
        "config/config.toml",
        "models/model.safetensors",
        "documents/abc123/right.pdf",
        "fonts/NotoSans.ttf",
        "upstream-cache/truststore.pem",
        "logs/launcher.log",
        "temp/translate.tmp",
    )
    for relative in leaked:
        path = artifact / policy.DATA_DIRECTORY / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")

    violations = policy.audit_artifact_tree(artifact)

    assert len(violations) == len(leaked)
    for relative in leaked:
        assert any(relative in violation for violation in violations)


def test_config_models_and_caches_outside_data_are_rejected(tmp_path: Path) -> None:
    policy = _load_policy()
    artifact = _staging_tree(policy, tmp_path / "artifact")
    (artifact / "config.toml").write_text("[api]\n", encoding="utf-8")
    (artifact / "models").mkdir()
    (artifact / "models" / "doclayout.pt").write_bytes(b"weights")
    (artifact / "documents").mkdir()
    (artifact / "app" / "portable-data.json").write_text("{}", encoding="utf-8")
    (artifact / "app" / "layout.onnx").write_bytes(b"graph")

    violations = policy.audit_artifact_tree(artifact)
    joined = "\n".join(violations)

    assert "config.toml" in joined
    assert "models" in joined
    assert "documents" in joined
    assert "portable-data.json" in joined
    assert "layout.onnx" in joined


def test_release_notes_must_warn_that_deleting_the_portable_directory_erases_config_and_cache() -> None:
    policy = _load_policy()
    notes = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert policy.audit_release_notes(notes) == []
    assert policy.audit_release_notes("便携版解压即用，欢迎反馈问题。") != []


def test_policy_cli_passes_a_clean_tree_and_blocks_a_leaking_one(tmp_path: Path) -> None:
    policy = _load_policy()
    notes = str(REPO_ROOT / "README.md")
    clean = _staging_tree(policy, tmp_path / "clean")
    leaky = _staging_tree(policy, tmp_path / "leaky")
    leaked_config = leaky / policy.DATA_DIRECTORY / "config" / "config.toml"
    leaked_config.parent.mkdir(parents=True)
    leaked_config.write_text("[api]\n", encoding="utf-8")

    assert policy.main(["--artifact", str(clean), "--release-notes", notes]) == 0
    assert policy.main(["--artifact", str(leaky), "--release-notes", notes]) == 1
