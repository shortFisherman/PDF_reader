"""P2-03 覆盖率/mypy/ESLint/标记契约的静态与行为测试。"""

import importlib.util
import json
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _pyproject() -> dict:
    with open(REPO_ROOT / "pyproject.toml", "rb") as f:
        return tomllib.load(f)


def test_coverage_config_covers_package_only_with_branches():
    coverage = _pyproject()["tool"]["coverage"]["run"]
    assert coverage["branch"] is True
    assert coverage["source"] == ["pdf_reader"]


def test_pytest_markers_declared():
    markers = "\n".join(_pyproject()["tool"]["pytest"]["ini_options"]["markers"])
    for name in ("unit", "integration", "system"):
        assert f'"{name}:' in markers or f"{name}:" in markers


def test_mypy_config_active_without_blanket_core_ignore():
    mypy = _pyproject()["tool"]["mypy"]
    for option in (
        "check_untyped_defs",
        "no_implicit_optional",
        "warn_unused_ignores",
        "warn_redundant_casts",
        "warn_return_any",
        "strict_equality",
    ):
        assert mypy.get(option) is True, f"mypy option {option} must be enabled"
    overrides = mypy.get("overrides", [])
    for override in overrides:
        modules = override.get("module", [])
        if any("pdf_reader" in module for module in modules):
            assert override.get("ignore_errors") is not True, "blanket ignore_errors on pdf_reader is forbidden"


def test_verify_pipeline_contract():
    verify = (REPO_ROOT / "scripts" / "verify.ps1").read_text(encoding="utf-8")
    for needle in (
        "coverage run --branch -m pytest",
        "coverage report",
        "coverage json",
        "check_coverage_policy",
        "-m mypy",
        "npm run lint:js",
        "npm test",
    ):
        assert needle in verify, f"verify.ps1 missing {needle}"
    assert "pytest -m " not in verify, "verify must not filter pytest markers"
    assert "pytest --ignore" not in verify
    assert "-k " not in verify


def test_coverage_policy_thresholds_are_meaningful():
    spec = importlib.util.spec_from_file_location(
        "check_coverage_policy",
        REPO_ROOT / "scripts" / "check_coverage_policy.py",
    )
    assert spec is not None and spec.loader is not None
    check_coverage_policy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check_coverage_policy)

    assert 0 < check_coverage_policy.GLOBAL_LINE_FLOOR < 100
    assert 0 < check_coverage_policy.GLOBAL_BRANCH_FLOOR < 100
    for module, (line_floor, branch_floor) in check_coverage_policy.MODULE_FLOORS.items():
        assert 0 < line_floor < 100, module
        assert 0 < branch_floor < 100, module


def _coverage_json(line_pct: float, branch_pct: float) -> dict:
    totals = {
        "num_statements": 100,
        "covered_lines": int(100 * line_pct / 100),
        "num_branches": 100,
        "covered_branches": int(100 * branch_pct / 100),
    }
    module_summary = {
        "num_statements": 100,
        "covered_lines": 100,
        "num_branches": 100,
        "covered_branches": 100,
    }
    return {
        "totals": totals,
        "files": {
            "src/pdf_reader/state.py": {"summary": module_summary},
            "src/pdf_reader/translation_coordinator.py": {"summary": module_summary},
            "src/pdf_reader/translation_lifecycle.py": {"summary": module_summary},
            "src/pdf_reader/sse_stream.py": {"summary": module_summary},
            "src/pdf_reader/routes.py": {"summary": module_summary},
        },
    }


def test_coverage_policy_script_pass_and_fail(tmp_path):
    script = REPO_ROOT / "scripts" / "check_coverage_policy.py"

    ok = tmp_path / "ok.json"
    ok.write_text(json.dumps(_coverage_json(100, 100)), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(script), str(ok)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "Coverage policy OK" in result.stdout

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(_coverage_json(50, 50)), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(script), str(bad)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode != 0
    assert "COVERAGE POLICY FAILED" in result.stderr


def test_coverage_policy_missing_module_fails(tmp_path):
    script = REPO_ROOT / "scripts" / "check_coverage_policy.py"
    data = _coverage_json(100, 100)
    del data["files"]["src/pdf_reader/state.py"]
    missing = tmp_path / "missing-module.json"
    missing.write_text(json.dumps(data), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(script), str(missing)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode != 0
    assert "state.py: not measured" in result.stderr


def test_eslint_contract():
    config = (REPO_ROOT / "eslint.config.mjs").read_text(encoding="utf-8")
    assert "js.configs.recommended" in config
    assert "'no-unused-vars': ['error'" in config or '"no-unused-vars": ["error"' in config
    assert "'no-undef': 'off'" not in config
    assert "'no-unused-vars': 'off'" not in config
    package = json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))
    assert "lint:js" in package["scripts"]
    assert "eslint" in package["devDependencies"]
    lock = (REPO_ROOT / "package-lock.json").read_text(encoding="utf-8")
    assert '"eslint"' in lock


def test_ci_coverage_artifact_contract():
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "PDF_READER_COVERAGE_ARTIFACT_DIR" in ci
    assert "upload-artifact@v4" in ci
    assert "coverage-artifacts" in ci
    assert "if-no-files-found: error" in ci
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "coverage-artifacts/" in gitignore
    assert ".coverage" in gitignore
    assert not (REPO_ROOT / ".coverage").exists()


def test_system_tests_collected_by_default():
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "tests/test_system_concurrency_failure.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "16 tests collected" in result.stdout


def test_integration_tests_collected():
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "tests/test_translation_routes.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "tests collected" in result.stdout
