from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
from importlib.metadata import version
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = REPO_ROOT / "packaging" / "windows" / "runtime_policy.py"


def _load_policy() -> ModuleType:
    spec = importlib.util.spec_from_file_location("windows_runtime_policy", POLICY_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runtime_lock_is_constrained_and_excludes_installer_and_dev_only_tools():
    policy = _load_policy()

    assert policy.audit_lock(REPO_ROOT) == []
    runtime = policy.parse_lock(REPO_ROOT / policy.RUNTIME_LOCK)
    aggregate = policy.parse_lock(REPO_ROOT / "requirements.lock")

    assert len(runtime) < len(aggregate)
    assert {name: aggregate[name] for name in runtime} == runtime
    assert {"flask", "pymupdf", "pdf2zh-next", "tomlkit", "babeldoc"} <= runtime.keys()
    assert not (policy.DEV_ONLY_DISTRIBUTIONS | policy.INSTALLER_DISTRIBUTIONS) & runtime.keys()
    assert runtime["ruff"] == aggregate["ruff"]  # Gradio/Xsdata runtime dependency, documented in README.


def test_source_policy_rejects_installer_imports_and_system_python_launches(tmp_path):
    policy = _load_policy()
    package = tmp_path / "src" / "pdf_reader"
    package.mkdir(parents=True)
    (package / "bad.py").write_text(
        "import pip\nimport subprocess\nsubprocess.run(['python.exe', '-m', 'pip', 'install', 'x'])\n",
        encoding="utf-8",
    )

    violations = policy.audit_source_tree(tmp_path)

    assert any("installer import" in item for item in violations)
    assert any("interpreter/installer process" in item for item in violations)


def test_current_production_source_has_no_runtime_install_or_unapproved_process_path():
    policy = _load_policy()

    assert policy.audit_source_tree(REPO_ROOT) == []


def test_installed_runtime_matches_lock_and_native_dependencies_import():
    policy = _load_policy()
    runtime = policy.parse_lock(REPO_ROOT / policy.RUNTIME_LOCK)

    assert {name: version(name) for name in runtime} == runtime
    for module_name in (
        "babeldoc",
        "cv2",
        "hyperscan",
        "onnxruntime",
        "pdf2zh_next",
        "pymupdf",
        "rtree",
        "uharfbuzz",
    ):
        assert importlib.import_module(module_name) is not None


def _write_valid_artifact(policy: ModuleType, artifact: Path) -> None:
    (artifact / "app").mkdir(parents=True)
    (artifact / "PDF Reader.exe").write_bytes(b"launcher")
    service = artifact / "app" / "PDF Reader Service.exe"
    service.write_bytes(b"service")
    lock = REPO_ROOT / policy.RUNTIME_LOCK
    packages = [
        {"name": name, "version": version, "wheel_sha256": "a" * 64}
        for name, version in policy.parse_lock(lock).items()
    ]
    manifest = {
        "schema_version": 1,
        "source_commit": "b" * 40,
        "source_lock": policy.RUNTIME_LOCK.as_posix(),
        "source_lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest(),
        "python": {
            "version": "3.12.8",
            "executable": "app/PDF Reader Service.exe",
            "executable_sha256": hashlib.sha256(service.read_bytes()).hexdigest(),
        },
        "packages": packages,
    }
    (artifact / policy.RUNTIME_MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")


def test_artifact_policy_accepts_private_runtime_manifest_and_rejects_installers(tmp_path):
    policy = _load_policy()
    artifact = tmp_path / "PDF Reader"
    _write_valid_artifact(policy, artifact)

    assert policy.audit_artifact_tree(REPO_ROOT, artifact) == []

    forbidden = artifact / "app" / "_internal" / "pip.exe"
    forbidden.parent.mkdir(parents=True)
    forbidden.write_bytes(b"not allowed")
    (forbidden.parent / "mypy").mkdir()
    violations = policy.audit_artifact_tree(REPO_ROOT, artifact)
    assert any("external runtime executable" in item for item in violations)
    assert any("installer/dev component" in item and "mypy" in item for item in violations)


def test_artifact_manifest_must_match_lock_versions_and_wheel_hashes(tmp_path):
    policy = _load_policy()
    artifact = tmp_path / "PDF Reader"
    _write_valid_artifact(policy, artifact)
    manifest_path = artifact / policy.RUNTIME_MANIFEST
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["packages"][0]["version"] = "0.0.0"
    payload["packages"][1]["wheel_sha256"] = "not-a-hash"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    violations = policy.audit_artifact_tree(REPO_ROOT, artifact)

    assert any("differs from lock" in item for item in violations)
    assert any("invalid wheel hash" in item for item in violations)


def test_artifact_manifest_service_hash_must_match_private_executable(tmp_path):
    policy = _load_policy()
    artifact = tmp_path / "PDF Reader"
    _write_valid_artifact(policy, artifact)
    (artifact / "app" / "PDF Reader Service.exe").write_bytes(b"tampered")

    violations = policy.audit_artifact_tree(REPO_ROOT, artifact)

    assert any("private service hash does not match" in item for item in violations)
