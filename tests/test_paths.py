"""P2-07 统一项目根路径与测试文件隔离。

路径策略由 ``paths.py`` 集中提供：

- ``PROJECT_ROOT``（项目资源根）＝仓库根，由 ``config.example.toml`` 标记自模块
  位置向上解析；``PDF_READER_ROOT`` 可显式覆盖；
- ``DATA_ROOT``（运行数据根）默认等于 ``PROJECT_ROOT``，可用
  ``PDF_READER_DATA_ROOT`` 覆盖（测试隔离/未来多数据目录）；
- ``config.toml`` / ``docs/glossary.csv`` / ``templates`` / ``static`` 锚定资源根；
- ``logs`` 与相对 ``cache_dir`` 锚定数据根；绝对 ``cache_dir`` 原样保留。

这些用例必须从任意 CWD 通过，且不得写入仓库 ``logs/`` 或 ``cache/``。
"""

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Never

import pytest

from pdf_reader import config, logging_config, paths
from pdf_reader.app import create_app

REPO_ROOT = Path(__file__).resolve().parents[1]

_PROBE = """
import json
import logging

logging.disable(logging.CRITICAL)

from pdf_reader import paths
from pdf_reader import config
from pdf_reader.app import create_app

app = create_app(config.build_app_settings())
print(json.dumps({
    "project_root": str(paths.get_project_root()),
    "config_path": str(paths.get_config_path()),
    "glossary_path": str(paths.get_glossary_path()),
    "log_dir": str(paths.get_log_dir()),
    "cache_dir": str(config.CACHE_DIR),
    "templates": str(app.template_folder),
    "static": str(app.static_folder),
}))
"""


_ENV_OVERRIDE_PROBE = """
import sys

from pdf_reader import paths

which = sys.argv[1] if len(sys.argv) > 1 else "root"
try:
    value = paths.get_project_root() if which == "root" else paths.get_data_root()
except Exception as exc:
    print(type(exc).__name__ + ":" + str(exc))
else:
    print("OK:" + str(value))
"""


_PORTABLE_PROBE = """
import json
import logging
import sys

from pdf_reader import paths

layout = paths.RuntimeLayout.portable_from_executable(sys.argv[1])
paths.install_runtime_layout(layout)
paths.prepare_runtime_layout()

# 这些模块故意放在显式布局安装之后导入，镜像未来便携服务入口的顺序。
from pdf_reader import config, logging_config
from pdf_reader.app import create_app

logging.disable(logging.CRITICAL)
app = create_app(config.build_app_settings())
print(json.dumps({
    "mode": layout.mode,
    "portable_root": str(paths.get_portable_root()),
    "resource_root": str(paths.get_resource_root()),
    "data_root": str(paths.get_data_root()),
    "config_path": str(config.CONFIG_PATH),
    "glossary_path": str(config.GLOSSARY_PATH),
    "log_dir": str(paths.get_log_dir()),
    "cache_dir": str(config.CACHE_DIR),
    "settings_cache_dir": str(app.config["app_settings"].cache_dir),
    "templates": str(app.template_folder),
    "static": str(app.static_folder),
}))
logging_config.reset_logging()
"""


def _probe_env(data_root: Path) -> dict:
    # 说明：P2-01 包化后子进程直接导入已安装的 pdf_reader 包，不再设置
    # PYTHONPATH；PROJECT_ROOT/DATA_ROOT 由 paths.py 的 marker/环境变量契约决定。
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["PDF_READER_DATA_ROOT"] = str(data_root)
    env.pop("PDF_READER_ROOT", None)
    return env


def _run_probe(cwd: Path, data_root: Path) -> dict:
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=cwd,
        env=_probe_env(data_root),
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, f"probe failed from {cwd}:\n{result.stderr}"
    return json.loads(result.stdout.strip())


def _run_env_probe(cwd: Path, env: dict, which: str) -> str:
    result = subprocess.run(
        [sys.executable, "-c", _ENV_OVERRIDE_PROBE, which],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"env probe failed from {cwd}:\n{result.stderr}"
    return result.stdout.strip()


def _run_portable_probe(cwd: Path, executable: Path, hostile_data_root: Path) -> dict:
    env = _probe_env(hostile_data_root)
    env["PDF_READER_ROOT"] = str(hostile_data_root / "resource-override")
    result = subprocess.run(
        [sys.executable, "-c", _PORTABLE_PROBE, str(executable)],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, f"portable probe failed from {cwd}:\n{result.stderr}"
    return json.loads(result.stdout.strip())


def _app_location(app) -> dict:
    return {
        "project_root": str(paths.get_project_root()),
        "config_path": str(paths.get_config_path()),
        "glossary_path": str(paths.get_glossary_path()),
        "log_dir": str(paths.get_log_dir()),
        "cache_dir": str(config.CACHE_DIR),
        "templates": str(app.template_folder),
        "static": str(app.static_folder),
    }


def test_config_and_glossary_use_unified_strategy():
    """config 模块的路径常量必须来自 paths 策略。"""
    assert config.CONFIG_PATH == paths.get_config_path()
    assert config.GLOSSARY_PATH == paths.get_glossary_path()
    assert config.CONFIG_PATH.parent == paths.get_project_root()


def test_default_data_root_equals_project_root(monkeypatch):
    """未覆盖 DATA_ROOT 时，运行数据根等于项目资源根（保持本地运行语义）。"""
    monkeypatch.delenv("PDF_READER_DATA_ROOT", raising=False)
    monkeypatch.delenv("PDF_READER_ROOT", raising=False)
    assert paths.get_data_root() == paths.get_project_root()
    assert paths.get_log_dir() == paths.get_project_root() / "logs"


def test_project_root_env_override(monkeypatch, tmp_path):
    """PDF_READER_ROOT 可显式覆盖资源根（安装/隔离场景）。"""
    fake_root = tmp_path / "fake-repo"
    fake_root.mkdir()
    (fake_root / "config.example.toml").write_text("", encoding="utf-8")
    monkeypatch.setenv("PDF_READER_ROOT", str(fake_root))
    assert paths.get_project_root() == fake_root.resolve()
    assert paths.get_config_path() == fake_root.resolve() / "config.toml"
    assert paths.get_glossary_path() == fake_root.resolve() / "docs" / "glossary.csv"


def test_relative_cache_dir_resolves_under_data_root(monkeypatch, tmp_path):
    """相对 cache_dir 锚定 DATA_ROOT，而不是当前工作目录。"""
    data_root = tmp_path / "data"
    monkeypatch.setenv("PDF_READER_DATA_ROOT", str(data_root))
    assert paths.resolve_cache_dir("cache") == (data_root / "cache").resolve()
    assert paths.resolve_cache_dir("./sub/cache") == (data_root / "sub" / "cache").resolve()


def test_absolute_cache_dir_not_rewritten(tmp_path):
    """绝对 cache_dir 保持绝对，不被 DATA_ROOT 重写。"""
    abs_cache = tmp_path / "abs-cache"
    assert paths.resolve_cache_dir(str(abs_cache)) == abs_cache.resolve()


@pytest.mark.parametrize(
    ("env_name", "which", "relative_value"),
    [
        ("PDF_READER_ROOT", "root", "relative-root"),
        ("PDF_READER_ROOT", "root", "..\\up-root"),
        ("PDF_READER_DATA_ROOT", "data", "relative-data"),
        ("PDF_READER_DATA_ROOT", "data", "sub\\dir"),
    ],
)
def test_relative_env_override_rejected_identically_from_any_cwd(tmp_path, env_name, which, relative_value):
    """相对 override 从两个不同 CWD 都被同样拒绝，且消息含变量名与绝对路径语义。"""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    outputs = []
    for cwd in (REPO_ROOT, elsewhere):
        env = _probe_env(tmp_path)
        env[env_name] = relative_value
        outputs.append(_run_env_probe(cwd, env, which))
    assert outputs[0] == outputs[1]
    assert "PathStrategyError" in outputs[0]
    assert env_name in outputs[0]
    assert "绝对路径" in outputs[0]
    assert "absolute" in outputs[0]


@pytest.mark.parametrize(
    ("env_name", "which"),
    [("PDF_READER_ROOT", "root"), ("PDF_READER_DATA_ROOT", "data")],
)
def test_absolute_env_override_identical_from_any_cwd(tmp_path, env_name, which):
    """绝对 override 从两个不同 CWD 解析出同一结果。"""
    override = tmp_path / ("abs-root" if env_name == "PDF_READER_ROOT" else "abs-data")
    override.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    outputs = []
    for cwd in (REPO_ROOT, elsewhere):
        env = _probe_env(tmp_path)
        env[env_name] = str(override)
        outputs.append(_run_env_probe(cwd, env, which))
    assert outputs[0] == outputs[1]
    assert outputs[0] == f"OK:{override.resolve()}"


def test_missing_marker_raises_instead_of_silent_fallback(monkeypatch, tmp_path):
    """找不到 config.example.toml 时快速失败，绝不静默回退到模块目录。"""
    monkeypatch.delenv("PDF_READER_ROOT", raising=False)
    bare = tmp_path / "no-marker"
    bare.mkdir()
    with pytest.raises(paths.PathStrategyError, match="config.example.toml"):
        paths._find_project_root(start=bare)


def test_missing_marker_allowed_when_root_explicit(monkeypatch, tmp_path):
    """显式 PDF_READER_ROOT 时不需要 marker。"""
    fake_root = tmp_path / "explicit-root"
    fake_root.mkdir()
    monkeypatch.setenv("PDF_READER_ROOT", str(fake_root))
    assert paths._find_project_root(start=tmp_path) == fake_root.resolve()


def test_src_layout_anchor_still_finds_repo_root(monkeypatch):
    """P2-01 前瞻：start 模拟 src/pdf_reader 仍向上找到仓库根，数据位置不变。"""
    monkeypatch.delenv("PDF_READER_ROOT", raising=False)
    src_anchor = REPO_ROOT / "src" / "pdf_reader"
    found = paths._find_project_root(start=src_anchor)
    assert found == REPO_ROOT.resolve()
    assert found == paths.get_project_root()
    assert found / "config.toml" == paths.get_config_path()
    assert found / "docs" / "glossary.csv" == paths.get_glossary_path()


def test_two_cwds_build_app_with_identical_paths(tmp_path):
    """两个不同 CWD 的真实 create_app 解析出完全一致的路径。"""
    data_root = tmp_path / "data-root"
    data_root.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    first = _run_probe(REPO_ROOT, data_root)
    second = _run_probe(elsewhere, data_root)

    assert first == second
    assert first == {
        "project_root": str(REPO_ROOT.resolve()),
        "config_path": str((REPO_ROOT / "config.toml").resolve()),
        "glossary_path": str((REPO_ROOT / "docs" / "glossary.csv").resolve()),
        "log_dir": str((data_root / "logs").resolve()),
        "cache_dir": str((data_root / "cache").resolve()),
        "templates": str((REPO_ROOT / "templates").resolve()),
        "static": str((REPO_ROOT / "static").resolve()),
    }
    # 真实应用构造把日志写进 DATA_ROOT，而不是仓库 logs/
    assert (data_root / "logs" / "pdf_reader.log").is_file()


def test_two_cwds_in_process_without_syspath_changes(monkeypatch, tmp_path):
    """当前 pytest 进程内用 monkeypatch.chdir 切换两个 CWD 后两次真实 create_app；
    测试本身不修改 sys.path/PYTHONPATH，路径结果仍一致。"""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    monkeypatch.chdir(REPO_ROOT)
    app_first = create_app(config.build_app_settings())
    logging_config.reset_logging()

    monkeypatch.chdir(elsewhere)
    app_second = create_app(config.build_app_settings())
    logging_config.reset_logging()

    expected = _app_location(app_first)
    assert _app_location(app_second) == expected
    assert expected == {
        "project_root": str(paths.get_project_root()),
        "config_path": str(paths.get_config_path()),
        "glossary_path": str(paths.get_glossary_path()),
        "log_dir": str(paths.get_log_dir()),
        "cache_dir": str(config.CACHE_DIR),
        "templates": str(app_first.template_folder),
        "static": str(app_first.static_folder),
    }


def test_create_app_uses_unified_resource_folders():
    """Flask templates/static 显式锚定资源根。"""
    app = create_app(config.build_app_settings())
    assert app.template_folder == str(paths.get_resource_root() / "templates")
    assert app.static_folder == str(paths.get_resource_root() / "static")


def test_logging_dir_uses_unified_strategy_and_reset(monkeypatch, tmp_path):
    """日志目录来自统一策略；reset 后可换新目录重建 handler。"""
    assert Path(logging_config.LOG_DIR) == paths.get_log_dir()

    log_dir = tmp_path / "data" / "logs"
    monkeypatch.setattr(logging_config, "LOG_DIR", log_dir)

    logging_config.setup_logging(False)
    root = logging.getLogger("pdf_reader")
    assert root.handlers
    assert (log_dir / "pdf_reader.log").is_file()

    logging_config.reset_logging()
    assert root.handlers == []

    log_dir_b = tmp_path / "data-b" / "logs"
    monkeypatch.setattr(logging_config, "LOG_DIR", log_dir_b)
    logging_config.setup_logging(False)
    assert (log_dir_b / "pdf_reader.log").is_file()


def _make_portable_layout(tmp_path: Path) -> paths.RuntimeLayout:
    portable_root = tmp_path / "PDF 阅读器 portable path with spaces"
    (portable_root / "app").mkdir(parents=True)
    executable = portable_root / "PDF Reader.exe"
    executable.write_bytes(b"")
    return paths.RuntimeLayout.portable_from_executable(executable)


def test_portable_layout_is_derived_from_executable_and_ignores_cwd_and_dev_env(monkeypatch, tmp_path):
    """便携根只来自顶层 EXE；CWD 与开发态覆盖均不能改变发行边界。"""
    layout = _make_portable_layout(tmp_path)
    expected_root = layout.portable_root
    assert expected_root is not None

    monkeypatch.setenv("PDF_READER_ROOT", str(tmp_path / "host-resource-override"))
    monkeypatch.setenv("PDF_READER_DATA_ROOT", str(tmp_path / "host-data-override"))
    elsewhere = tmp_path / "另一个 current directory"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    assert layout.mode is paths.RuntimeMode.PORTABLE
    assert layout.portable_root == expected_root
    assert layout.resource_root == expected_root / "app"
    assert layout.data_root == expected_root / "data"
    assert layout.config_path == expected_root / "data" / "config" / "config.toml"
    assert layout.glossary_path == expected_root / "data" / "glossary" / "glossary.csv"
    assert layout.log_dir == expected_root / "data" / "logs"
    assert layout.temp_dir == expected_root / "data" / "temp"
    assert layout.resolve_cache_dir("documents") == expected_root / "data" / "documents"


def test_prepare_portable_layout_supports_long_unicode_path(tmp_path):
    portable_root = tmp_path / "中文 path with spaces" / ("long-segment-" + "a" * 70) / ("nested-segment-" + "b" * 70)
    (portable_root / "app").mkdir(parents=True)
    executable = portable_root / "PDF Reader.exe"
    executable.write_bytes(b"")

    layout = paths.RuntimeLayout.portable_from_executable(executable)
    paths.prepare_runtime_layout(layout)

    assert layout.portable_root == portable_root.resolve()
    assert layout.data_root == portable_root.resolve() / "data"
    assert all(directory.is_dir() for directory in layout.managed_directories)


def test_two_cwds_import_real_app_with_identical_portable_paths(tmp_path):
    """显式安装布局后再导入真实配置/应用，所有可变路径仍只落在 data。"""
    layout = _make_portable_layout(tmp_path)
    assert layout.portable_root is not None
    executable = layout.portable_root / "PDF Reader.exe"
    elsewhere = tmp_path / "portable-probe-cwd"
    elsewhere.mkdir()
    hostile_data_root = tmp_path / "must-not-be-used"

    first = _run_portable_probe(REPO_ROOT, executable, hostile_data_root)
    second = _run_portable_probe(elsewhere, executable, hostile_data_root)

    expected_root = layout.portable_root
    expected_data = expected_root / "data"
    assert first == second
    assert first == {
        "mode": "portable",
        "portable_root": str(expected_root),
        "resource_root": str(expected_root / "app"),
        "data_root": str(expected_data),
        "config_path": str(expected_data / "config" / "config.toml"),
        "glossary_path": str(expected_data / "glossary" / "glossary.csv"),
        "log_dir": str(expected_data / "logs"),
        "cache_dir": str(expected_data / "documents"),
        "settings_cache_dir": str(expected_data / "documents"),
        "templates": str(expected_root / "app" / "templates"),
        "static": str(expected_root / "app" / "static"),
    }
    assert (expected_data / "logs" / "pdf_reader.log").is_file()
    assert not hostile_data_root.exists()


def test_portable_layout_install_is_explicit_and_cannot_switch(monkeypatch, tmp_path):
    """便携模式由入口显式注入，同一进程不能悄悄换到另一个数据根。"""
    monkeypatch.setattr(paths, "_configured_layout", None)
    layout = _make_portable_layout(tmp_path)
    paths.install_runtime_layout(layout)

    assert paths.get_runtime_layout() is layout
    assert paths.get_portable_root() == layout.portable_root
    assert paths.get_data_root() == layout.data_root
    assert paths.get_config_path() == layout.config_path
    assert paths.get_glossary_path() == layout.glossary_path
    assert paths.get_log_dir() == layout.log_dir
    assert paths.get_temp_dir() == layout.temp_dir
    assert paths.get_default_cache_dirname() == "documents"

    other = paths.RuntimeLayout.portable_from_executable(tmp_path / "other" / "PDF Reader.exe")
    with pytest.raises(paths.PathStrategyError) as exc_info:
        paths.install_runtime_layout(other)
    assert exc_info.value.code == "runtime_layout_already_installed"


@pytest.mark.parametrize(
    "unsafe_value",
    [
        "../outside",
        "documents/../../outside",
    ],
)
def test_portable_cache_rejects_relative_path_traversal(tmp_path, unsafe_value):
    layout = _make_portable_layout(tmp_path)
    with pytest.raises(paths.PathStrategyError) as exc_info:
        layout.resolve_cache_dir(unsafe_value)
    assert exc_info.value.code == "path_outside_data_root"


def test_portable_cache_rejects_absolute_outside_path_but_development_keeps_compatibility(tmp_path):
    outside = (tmp_path / "outside-cache").resolve()
    portable = _make_portable_layout(tmp_path)
    development = paths.RuntimeLayout.development(
        resource_root=REPO_ROOT,
        data_root=tmp_path / "development-data",
    )

    with pytest.raises(paths.PathStrategyError) as exc_info:
        portable.resolve_cache_dir(str(outside))
    assert exc_info.value.code == "path_outside_data_root"
    assert development.resolve_cache_dir(str(outside)) == outside


def test_portable_data_path_rejects_existing_symlink_with_nonexistent_tail(tmp_path):
    """即使目标尾部尚不存在，已有链接也不能把随后写入导向 data 外。"""
    layout = _make_portable_layout(tmp_path)
    layout.data_root.mkdir()
    outside = tmp_path / "outside-symlink-target"
    outside.mkdir()
    link = layout.data_root / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"当前环境不允许创建目录符号链接：{exc}")

    with pytest.raises(paths.PathStrategyError) as exc_info:
        layout.require_data_path(link / "not-created-yet" / "output.pdf")
    assert exc_info.value.code == "path_outside_data_root"


@pytest.mark.skipif(os.name != "nt", reason="Windows junction contract")
def test_portable_layout_rejects_data_root_junction(tmp_path):
    """Windows junction 不能把整个 data 根重定向到便携目录之外。"""
    portable_root = tmp_path / "portable-junction-check"
    (portable_root / "app").mkdir(parents=True)
    executable = portable_root / "PDF Reader.exe"
    executable.write_bytes(b"")
    outside = tmp_path / "junction-target"
    outside.mkdir()
    junction = portable_root / "data"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        pytest.skip(f"当前环境不允许创建 junction：{result.stderr or result.stdout}")
    try:
        with pytest.raises(paths.PathStrategyError) as exc_info:
            paths.RuntimeLayout.portable_from_executable(executable)
        assert exc_info.value.code == "portable_data_outside_root"
    finally:
        os.rmdir(junction)


def test_prepare_portable_layout_creates_only_contract_directories_and_removes_probe(tmp_path):
    layout = _make_portable_layout(tmp_path)
    result = paths.prepare_runtime_layout(layout)

    assert result is layout
    assert all(directory.is_dir() for directory in layout.managed_directories)
    assert list(layout.data_root.glob(".pdf-reader-write-test-*.tmp")) == []
    assert not layout.config_path.exists()
    assert not layout.glossary_path.exists()


def test_prepare_portable_layout_fails_with_stable_code_instead_of_fallback(monkeypatch, tmp_path):
    layout = _make_portable_layout(tmp_path)

    def deny_write(_path: object, _flags: int, _mode: int = 0o777) -> Never:
        raise PermissionError("simulated read-only portable directory")

    monkeypatch.setattr(paths.os, "open", deny_write)
    with pytest.raises(paths.PathStrategyError) as exc_info:
        paths.prepare_runtime_layout(layout)
    assert exc_info.value.code == "portable_data_not_writable"
    assert str(layout.portable_root) in str(exc_info.value)
    assert not (tmp_path / "host-fallback").exists()
