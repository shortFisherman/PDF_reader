"""P2-04 依赖声明与验证契约的静态/行为测试。"""

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

LOCK_HEADER_COMMAND = (
    "pip-compile --resolver=backtracking --strip-extras --extra=dev --output-file=requirements.lock pyproject.toml"
)


def _pyproject() -> dict:
    with open(REPO_ROOT / "pyproject.toml", "rb") as f:
        return tomllib.load(f)


def test_pyproject_is_only_direct_declaration_source():
    assert not (REPO_ROOT / "requirements.txt").exists()
    assert not (REPO_ROOT / "requirements-dev.txt").exists()


def test_runtime_dependencies_declared_in_pyproject():
    deps = set(_pyproject()["project"]["dependencies"])
    assert deps == {"flask==3.1.3", "pymupdf==1.25.2", "pdf2zh-next==2.9.0"}


def test_dev_extra_declares_tools():
    dev = _pyproject()["project"]["optional-dependencies"]["dev"]
    assert len(dev) >= 5
    for needle in ("pytest==9.0.3", "ruff==0.15.18", "coverage", "mypy", "pip-tools==7.6.1"):
        assert any(needle in item for item in dev), f"dev extra missing {needle}: {dev}"


def test_lock_header_records_real_command():
    header_lines = REPO_ROOT.joinpath("requirements.lock").read_text(encoding="utf-8").splitlines()[:8]
    assert LOCK_HEADER_COMMAND in "\n".join(header_lines)


def test_lock_contains_dev_tools_and_no_old_inputs():
    text = REPO_ROOT.joinpath("requirements.lock").read_text(encoding="utf-8")
    for name in ("pytest==9.0.3", "ruff==0.15.18", "coverage==", "mypy==", "pip-tools==7.6.1"):
        assert name in text, f"lock missing {name}"
    assert "requirements.txt" not in text
    assert "requirements-dev" not in text


def test_install_contract_consistent_across_ci_readme_start():
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    start = (REPO_ROOT / "start.bat").read_text(encoding="utf-8", errors="replace")
    for label, text in (("CI", ci), ("README", readme), ("start.bat", start)):
        assert "pip install -r requirements.lock" in text, label
        assert "pip install -e . --no-deps" in text, label
        assert "requirements.txt" not in text, label
        assert "requirements-dev" not in text, label
    assert "npm ci" in ci


def test_node_locked_via_package_lock_and_npm_ci():
    assert (REPO_ROOT / "package-lock.json").is_file()
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "npm ci" in ci
    verify = (REPO_ROOT / "scripts" / "verify.ps1").read_text(encoding="utf-8")
    assert "npm test" in verify


def test_verify_script_prints_python_and_warns_on_fallback():
    verify = (REPO_ROOT / "scripts" / "verify.ps1").read_text(encoding="utf-8")
    assert "Resolved Python:" in verify
    assert "Python version:" in verify
    assert "Write-Warning" in verify
