"""P2-01 独立质量门 CLI 测试：退出码、JSON 输出、基线更新与漂移检测。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from pdf_reader import term_quality

REPO_ROOT = Path(__file__).resolve().parents[1]
GATE = REPO_ROOT / "scripts" / "term_quality_gate.py"


def _run_gate(*args: str, cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GATE), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_gate_passes_with_real_fixture_and_committed_baseline():
    result = _run_gate("--json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["passed"] is True
    assert payload["failures"] == []
    assert payload["report"]["metrics"]["repeat_run_determinism"] is True


def test_gate_human_output_is_clear_on_success():
    result = _run_gate()
    assert result.returncode == 0, result.stderr
    assert "Term quality report" in result.stdout
    assert "candidate_precision" in result.stdout
    assert "Term quality gate PASSED" in result.stdout


def test_gate_json_output_is_deterministic():
    first = _run_gate("--json")
    second = _run_gate("--json")
    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert first.stdout == second.stdout


def test_gate_fails_nonzero_when_thresholds_regress(tmp_path):
    fixture = term_quality.load_fixture(term_quality.FIXTURE_PATH)
    for response in fixture["model_responses"]:
        content = {"terms": [{"source": "hallucinatedterm", "target": "幻觉术语"}]}
        response["raw"] = {"choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}]}
        response["expected_parsed_terms"] = [["hallucinatedterm", "幻觉术语"]]
        response["expected_filter"] = {"hallucinatedterm": {"kept": False, "reason": "no_source_match"}}
    bad_fixture = tmp_path / "bad-fixture.json"
    bad_fixture.write_text(
        json.dumps(fixture, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    result = _run_gate("--fixture", str(bad_fixture), "--no-baseline", "--json")
    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["passed"] is False
    assert payload["failures"]


def test_gate_update_baseline_writes_atomically_and_passes_after(tmp_path):
    baseline = tmp_path / "baseline.json"
    result = _run_gate(
        "--update-baseline",
        "--baseline",
        str(baseline),
        "--json",
    )
    assert result.returncode == 0, result.stderr
    assert baseline.is_file()
    payload = json.loads(result.stdout)
    assert payload["passed"] is True

    second = _run_gate("--baseline", str(baseline), "--json")
    assert second.returncode == 0, second.stderr
    assert json.loads(second.stdout)["baseline"]["deltas"] is not None


def test_gate_refuses_baseline_update_when_thresholds_fail(tmp_path):
    fixture = term_quality.load_fixture(term_quality.FIXTURE_PATH)
    for response in fixture["model_responses"]:
        response["raw"] = {"choices": [{"message": {"content": "not json"}}]}
    bad_fixture = tmp_path / "bad-fixture.json"
    bad_fixture.write_text(
        json.dumps(fixture, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    baseline = tmp_path / "baseline.json"
    result = _run_gate(
        "--fixture",
        str(bad_fixture),
        "--update-baseline",
        "--baseline",
        str(baseline),
    )
    assert result.returncode != 0
    assert not baseline.exists()


def test_gate_detects_baseline_drift_with_nonzero_exit(tmp_path):
    baseline = term_quality.load_baseline(term_quality.BASELINE_PATH)
    baseline["metrics"] = dict(baseline["metrics"])
    baseline["metrics"]["candidate_precision"] = 0.99
    drifted = tmp_path / "drifted-baseline.json"
    drifted.write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    result = _run_gate("--baseline", str(drifted), "--json")
    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["passed"] is False
    assert any("candidate_precision" in failure for failure in payload["failures"])


def test_gate_missing_fixture_exits_usage_error(tmp_path):
    result = _run_gate("--fixture", str(tmp_path / "missing.json"), "--no-baseline")
    assert result.returncode == 2
    assert "term quality error" in result.stderr.lower()


@pytest.mark.parametrize("tolerance", ["-0.1", "nan", "inf", "abc"])
def test_gate_rejects_invalid_tolerance(tolerance):
    result = _run_gate("--tolerance", tolerance, "--no-baseline", "--json")
    assert result.returncode == 2
    assert "tolerance" in result.stderr.lower()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda f: f.pop("compliance_cases"),
        lambda f: f.pop("boundary_cases"),
        lambda f: f.pop("store_scenarios"),
        lambda f: f["model_responses"][0].__setitem__("expected_filter", {}),
        lambda f: f["documents"][0]["golden"].__setitem__("common_words", []),
        lambda f: f.pop("metadata"),
    ],
)
def test_gate_rejects_fixture_without_required_dimensions(tmp_path, mutate):
    fixture = term_quality.load_fixture(term_quality.FIXTURE_PATH)
    mutate(fixture)
    bad = tmp_path / "incomplete-fixture.json"
    bad.write_text(
        json.dumps(fixture, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    result = _run_gate("--fixture", str(bad), "--no-baseline", "--json")
    assert result.returncode == 2
    assert "term quality error" in result.stderr.lower()


def test_gate_fails_when_all_core_targets_are_wrong(tmp_path):
    fixture = term_quality.load_fixture(term_quality.FIXTURE_PATH)
    for response in fixture["model_responses"]:
        terms = json.loads(response["raw"]["choices"][0]["message"]["content"])["terms"]
        for term in terms:
            term["target"] = "错误译法"
        response["raw"]["choices"][0]["message"]["content"] = json.dumps({"terms": terms}, ensure_ascii=False)
        response["expected_parsed_terms"] = [[term["source"], term["target"]] for term in terms]
    bad = tmp_path / "wrong-targets.json"
    bad.write_text(
        json.dumps(fixture, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    result = _run_gate("--fixture", str(bad), "--no-baseline", "--json")
    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["report"]["metrics"]["candidate_target_accuracy"] == 0.0
    assert any("candidate_target_accuracy" in failure for failure in payload["failures"])


def test_gate_does_not_need_api_key_or_config(tmp_path):
    env = os.environ.copy()
    env.pop("PDF_READER_DATA_ROOT", None)
    env.pop("DEEPSEEK_API_KEY", None)
    env.pop("OPENAI_API_KEY", None)
    result = subprocess.run(
        [sys.executable, str(GATE), "--json", "--no-baseline"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["passed"] is True


@pytest.mark.skipif(os.name != "nt", reason="verify.ps1 is Windows/PowerShell-only")
def test_verify_script_invokes_term_quality_gate():
    verify = (REPO_ROOT / "scripts" / "verify.ps1").read_text(encoding="utf-8")
    assert "term_quality_gate.py" in verify
    assert "Term quality gate" in verify
