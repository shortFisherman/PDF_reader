"""P2-01 术语质量评测引擎单元测试：空集合语义、阈值、基线漂移与生产边界复用。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

import pytest

from pdf_reader import term_quality
from pdf_reader.candidate_filter import FilteredCandidate
from pdf_reader.term_extraction import TermCandidate, parse_model_response
from pdf_reader.terminology_compliance import ComplianceVerdict


def test_ratio_empty_semantics_are_explicit():
    assert term_quality.ratio(0, 0, empty_value=1.0) == 1.0
    assert term_quality.ratio(0, 0, empty_value=0.0) == 0.0
    assert term_quality.ratio(3, 4, empty_value=1.0) == pytest.approx(0.75)
    assert term_quality.ratio(0, 4, empty_value=1.0) == pytest.approx(0.0)


def test_quality_thresholds_are_conservative_not_all_100():
    thresholds = term_quality.QUALITY_THRESHOLDS
    assert thresholds["candidate_precision"] < 1.0
    assert thresholds["candidate_target_accuracy"] < 1.0
    assert thresholds["core_term_recall"] < 1.0
    assert thresholds["single_page_recall"] < 1.0
    assert thresholds["batch_recall"] < 1.0
    assert thresholds["authoritative_compliance_rate"] < 1.0
    assert thresholds["batch_minus_single_core_recall_delta"] <= 0.0
    assert thresholds["common_word_contamination_rate"] == 0.0
    assert thresholds["rejected_candidate_reprompt_rate"] == 0.0
    assert thresholds["wrong_first_translation_lock_rate"] == 0.0


def test_check_thresholds_passes_good_metrics():
    metrics = {
        "candidate_precision": 0.9,
        "candidate_target_accuracy": 0.95,
        "core_term_recall": 0.9,
        "single_page_recall": 0.8,
        "batch_recall": 1.0,
        "batch_minus_single_core_recall_delta": 0.1,
        "common_word_contamination_rate": 0.0,
        "authoritative_compliance_rate": 0.7,
        "repeat_run_determinism": True,
        "rejected_candidate_reprompt_rate": 0.0,
        "wrong_first_translation_lock_rate": 0.0,
        "filter_check_pass_rate": 1.0,
        "parse_check_pass_rate": 1.0,
        "boundary_check_pass_rate": 1.0,
        "compliance_fail_detected_rate": 1.0,
    }
    passed, failures = term_quality.check_thresholds(metrics)
    assert passed
    assert failures == ()


def test_check_thresholds_fails_on_each_regression_direction():
    good = {
        "candidate_precision": 0.9,
        "candidate_target_accuracy": 0.95,
        "core_term_recall": 0.9,
        "single_page_recall": 0.8,
        "batch_recall": 1.0,
        "batch_minus_single_core_recall_delta": 0.1,
        "common_word_contamination_rate": 0.0,
        "authoritative_compliance_rate": 0.7,
        "repeat_run_determinism": True,
        "rejected_candidate_reprompt_rate": 0.0,
        "wrong_first_translation_lock_rate": 0.0,
        "filter_check_pass_rate": 1.0,
        "parse_check_pass_rate": 1.0,
        "boundary_check_pass_rate": 1.0,
        "compliance_fail_detected_rate": 1.0,
    }
    cases = {
        "low_precision": {**good, "candidate_precision": 0.7},
        "low_target_accuracy": {**good, "candidate_target_accuracy": 0.85},
        "low_recall": {**good, "core_term_recall": 0.7},
        "low_single_recall": {**good, "single_page_recall": 0.4},
        "low_batch_recall": {**good, "batch_recall": 0.7},
        "contamination": {**good, "common_word_contamination_rate": 0.1},
        "low_compliance": {**good, "authoritative_compliance_rate": 0.4},
        "nondeterministic": {**good, "repeat_run_determinism": False},
        "batch_worse_than_single": {**good, "batch_minus_single_core_recall_delta": -0.3},
        "reprompt": {**good, "rejected_candidate_reprompt_rate": 0.5},
        "wrong_first_lock": {**good, "wrong_first_translation_lock_rate": 0.5},
        "filter_check_fail": {**good, "filter_check_pass_rate": 0.9},
        "parse_check_fail": {**good, "parse_check_pass_rate": 0.9},
        "boundary_check_fail": {**good, "boundary_check_pass_rate": 0.9},
        "fail_detection_fail": {**good, "compliance_fail_detected_rate": 0.0},
    }
    for label, metrics in cases.items():
        passed, failures = term_quality.check_thresholds(metrics)
        assert not passed, label
        assert failures, label


def test_check_thresholds_rejects_missing_and_non_numeric():
    passed, failures = term_quality.check_thresholds({})
    assert not passed
    assert any("missing metric" in failure for failure in failures)

    bad = dict(term_quality.QUALITY_THRESHOLDS)
    bad["candidate_precision"] = "0.9"
    passed, failures = term_quality.check_thresholds(bad)
    assert not passed
    assert any("non-numeric" in failure for failure in failures)

    for value in (float("nan"), float("inf"), float("-inf")):
        bad = dict(term_quality.QUALITY_THRESHOLDS)
        bad["candidate_precision"] = value
        passed, failures = term_quality.check_thresholds(bad)
        assert not passed
        assert any("non-finite" in failure for failure in failures)

    bad_threshold = dict(term_quality.QUALITY_THRESHOLDS)
    passed, failures = term_quality.check_thresholds(
        bad_threshold,
        thresholds={**term_quality.QUALITY_THRESHOLDS, "candidate_precision": "0.9"},
    )
    assert not passed
    assert any("non-numeric threshold" in failure for failure in failures)


def test_baseline_compare_detects_drift_in_both_directions():
    baseline = {
        "candidate_precision": 0.9,
        "common_word_contamination_rate": 0.0,
        "repeat_run_determinism": True,
    }
    _, failures = term_quality.compare_baseline(
        {**baseline, "candidate_precision": 0.84},
        baseline,
        tolerance=0.05,
    )
    assert any("candidate_precision" in failure for failure in failures)

    _, failures = term_quality.compare_baseline(
        {**baseline, "common_word_contamination_rate": 0.1},
        baseline,
        tolerance=0.05,
    )
    assert any("common_word_contamination_rate" in failure for failure in failures)

    _, failures = term_quality.compare_baseline(
        {**baseline, "repeat_run_determinism": False},
        baseline,
        tolerance=0.05,
    )
    assert any("repeat_run_determinism" in failure for failure in failures)


def test_baseline_compare_rejects_nan_infinity_strings_and_type_mismatch():
    baseline = {
        "candidate_precision": 0.9,
        "repeat_run_determinism": True,
    }
    for bad_value in (float("nan"), float("inf"), float("-inf"), "0.9"):
        _, failures = term_quality.compare_baseline(
            {**baseline, "candidate_precision": bad_value},
            baseline,
            tolerance=0.05,
        )
        assert any("candidate_precision" in failure for failure in failures), bad_value

    _, failures = term_quality.compare_baseline(
        {**baseline, "repeat_run_determinism": 1},
        baseline,
        tolerance=0.05,
    )
    assert any("type mismatch" in failure for failure in failures)

    _, failures = term_quality.compare_baseline(
        {**baseline, "candidate_precision": 0.9},
        {**baseline, "candidate_precision": float("nan")},
        tolerance=0.05,
    )
    assert any("non-finite baseline" in failure for failure in failures)


def test_baseline_compare_rejects_invalid_tolerance():
    metrics = {"candidate_precision": 0.9}
    for tolerance in (-0.1, float("nan"), float("inf"), "0.1"):
        with pytest.raises(term_quality.TermQualityError):
            term_quality.compare_baseline(metrics, metrics, tolerance=tolerance)


def test_baseline_compare_accepts_within_tolerance_and_missing_metric_fails():
    baseline = {"candidate_precision": 0.9, "repeat_run_determinism": True}
    deltas, failures = term_quality.compare_baseline(
        {"candidate_precision": 0.87, "repeat_run_determinism": True},
        baseline,
        tolerance=0.05,
    )
    assert failures == ()
    assert deltas["candidate_precision"] == pytest.approx(-0.03)

    _, failures = term_quality.compare_baseline(
        {"candidate_precision": 0.9},
        baseline,
        tolerance=0.05,
    )
    assert any("repeat_run_determinism" in failure for failure in failures)


def test_fixture_validation_rejects_bad_schema(tmp_path):
    fixture = {
        "schema_version": 999,
        "documents": [],
        "model_responses": [],
        "compliance_cases": [],
        "boundary_cases": [],
        "store_scenarios": [],
    }
    with pytest.raises(term_quality.TermQualityError):
        term_quality.validate_fixture(fixture)

    bad = {
        "schema_version": 1,
        "documents": [
            {
                "id": "doc",
                "category": "unknown_category",
                "pages": [{"page": 1, "text": "text"}],
                "golden": {"core_terms": [], "common_words": []},
            }
        ],
        "model_responses": [],
        "compliance_cases": [],
        "boundary_cases": [],
        "store_scenarios": [],
    }
    with pytest.raises(term_quality.TermQualityError):
        term_quality.validate_fixture(bad)


def test_load_fixture_missing_file_raises(tmp_path):
    with pytest.raises(term_quality.TermQualityError):
        term_quality.load_fixture(tmp_path / "missing.json")


def test_load_baseline_rejects_invalid_payloads(tmp_path):
    with pytest.raises(term_quality.TermQualityError):
        term_quality.load_baseline(tmp_path / "missing.json")

    invalid_json = tmp_path / "invalid.json"
    invalid_json.write_text("not json", encoding="utf-8")
    with pytest.raises(term_quality.TermQualityError):
        term_quality.load_baseline(invalid_json)

    not_object = tmp_path / "not-object.json"
    not_object.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(term_quality.TermQualityError):
        term_quality.load_baseline(not_object)

    bad_schema = tmp_path / "bad-schema.json"
    bad_schema.write_text(
        json.dumps({"schema_version": 999, "metrics": {}}),
        encoding="utf-8",
    )
    with pytest.raises(term_quality.TermQualityError):
        term_quality.load_baseline(bad_schema)

    bad_metrics = tmp_path / "bad-metrics.json"
    bad_metrics.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "metric_definitions_version": 1,
                "metrics": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(term_quality.TermQualityError):
        term_quality.load_baseline(bad_metrics)

    missing_key = tmp_path / "missing-key.json"
    metrics = dict(term_quality.QUALITY_THRESHOLDS)
    metrics.pop("candidate_precision")
    missing_key.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "metric_definitions_version": 1,
                "fixture": "tests/fixtures/term_quality/fixture.json",
                "fixture_sha256": "0" * 64,
                "metrics": metrics,
                "thresholds": dict(term_quality.QUALITY_THRESHOLDS),
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(term_quality.TermQualityError):
        term_quality.load_baseline(missing_key)

    bad_type = tmp_path / "bad-type.json"
    bad_type_metrics = dict(term_quality.QUALITY_THRESHOLDS)
    bad_type_metrics["repeat_run_determinism"] = "true"
    bad_type.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "metric_definitions_version": 1,
                "fixture": "tests/fixtures/term_quality/fixture.json",
                "fixture_sha256": "0" * 64,
                "metrics": bad_type_metrics,
                "thresholds": dict(term_quality.QUALITY_THRESHOLDS),
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(term_quality.TermQualityError):
        term_quality.load_baseline(bad_type)

    nan_value = tmp_path / "nan-value.json"
    nan_metrics = dict(term_quality.QUALITY_THRESHOLDS)
    nan_metrics["candidate_precision"] = float("nan")
    nan_value.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "metric_definitions_version": 1,
                "fixture": "tests/fixtures/term_quality/fixture.json",
                "fixture_sha256": "0" * 64,
                "metrics": nan_metrics,
                "thresholds": dict(term_quality.QUALITY_THRESHOLDS),
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(term_quality.TermQualityError):
        term_quality.load_baseline(nan_value)

    missing_defs_version = tmp_path / "missing-defs-version.json"
    missing_defs_version.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "fixture": "tests/fixtures/term_quality/fixture.json",
                "fixture_sha256": "0" * 64,
                "metrics": dict(term_quality.QUALITY_THRESHOLDS),
                "thresholds": dict(term_quality.QUALITY_THRESHOLDS),
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(term_quality.TermQualityError):
        term_quality.load_baseline(missing_defs_version)

    bad_sha = tmp_path / "bad-sha.json"
    bad_sha.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "metric_definitions_version": 1,
                "fixture": "tests/fixtures/term_quality/fixture.json",
                "fixture_sha256": "xyz",
                "metrics": dict(term_quality.QUALITY_THRESHOLDS),
                "thresholds": dict(term_quality.QUALITY_THRESHOLDS),
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(term_quality.TermQualityError):
        term_quality.load_baseline(bad_sha)


def test_write_baseline_cleans_tmp_on_failure(tmp_path, monkeypatch):
    report = term_quality.evaluate_quality(term_quality.FIXTURE_PATH, work_dir=tmp_path / "work")
    target = tmp_path / "baseline.json"

    def fail_replace(src, dst) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(term_quality.os, "replace", fail_replace)
    with pytest.raises(OSError):
        term_quality.write_baseline(report, target)
    assert not target.exists()
    assert not (tmp_path / "baseline.json.tmp").exists()


def test_malformed_model_response_is_reported_not_crashed(tmp_path):
    fixture = term_quality.load_fixture(term_quality.FIXTURE_PATH)
    response = fixture["model_responses"][0]
    response["raw"] = {"choices": [{"message": {"content": "not json"}}]}
    response["expected_parsed_terms"] = [["AD", "特应性皮炎"]]
    response["expected_filter"] = {"AD": {"kept": True, "reason": None}}
    bad = tmp_path / "bad-response.json"
    bad.write_text(
        json.dumps(fixture, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    report = term_quality.evaluate_quality(bad, work_dir=tmp_path / "work")
    response_detail = report.detail["responses"][0]
    assert response_detail["parse_ok"] is False
    assert response_detail["parse_error"] == "TermExtractionParseError"
    assert response_detail["filter_checks_passed"] == 0
    assert report.passed is False
    assert any("parse_check_pass_rate" in failure for failure in report.failures)


def test_parse_model_response_is_reused_and_validates_expected_terms():
    fixture = term_quality.load_fixture(term_quality.FIXTURE_PATH)
    for response in fixture["model_responses"]:
        raw = json.dumps(response["raw"], ensure_ascii=False).encode("utf-8")
        parsed = parse_model_response(raw)
        expected = [tuple(pair) for pair in response["expected_parsed_terms"]]
        assert [(item.source, item.target) for item in parsed] == expected, response["id"]


def test_evaluation_reuses_production_boundaries(monkeypatch, tmp_path):
    fixture = term_quality.load_fixture(term_quality.FIXTURE_PATH)
    calls = {"parse": 0, "filter": 0, "compliance": 0, "store_record": 0, "accept": 0, "reject": 0}

    real_parse = term_quality.parse_model_response

    def fake_parse(raw: bytes) -> list[TermCandidate]:
        calls["parse"] += 1
        return real_parse(raw)

    real_filter = term_quality.filter_candidates

    def fake_filter(
        candidates: Sequence[TermCandidate],
        sent_text: str,
        page_chunks: Sequence[tuple[int, str]],
    ) -> tuple[FilteredCandidate, ...]:
        calls["filter"] += 1
        return real_filter(candidates, sent_text, page_chunks)

    real_verify = term_quality.verify_translated_text

    def fake_verify(
        translated_text: str,
        active_terms: Sequence[tuple[str, str]],
    ) -> ComplianceVerdict:
        calls["compliance"] += 1
        return real_verify(translated_text, active_terms)

    real_record = term_quality.CandidateStore.record_observations
    real_accept = term_quality.CandidateStore.accept
    real_reject = term_quality.CandidateStore.reject

    def fake_record(
        self,
        observations,
        *,
        strategy_version: str = "auto/1",
        expected_revision: int | None = None,
    ) -> int:
        calls["store_record"] += 1
        return real_record(
            self,
            observations,
            strategy_version=strategy_version,
            expected_revision=expected_revision,
        )

    def fake_accept(
        self,
        source: str,
        *,
        target: str | None = None,
        expected_revision: int | None = None,
    ) -> tuple[object, int]:
        calls["accept"] += 1
        return real_accept(self, source, target=target, expected_revision=expected_revision)

    def fake_reject(
        self,
        source: str,
        *,
        target: str | None = None,
        expected_revision: int | None = None,
    ) -> tuple[object, int]:
        calls["reject"] += 1
        return real_reject(self, source, target=target, expected_revision=expected_revision)

    monkeypatch.setattr(term_quality, "parse_model_response", fake_parse)
    monkeypatch.setattr(term_quality, "filter_candidates", fake_filter)
    monkeypatch.setattr(term_quality, "verify_translated_text", fake_verify)
    monkeypatch.setattr(term_quality.CandidateStore, "record_observations", fake_record)
    monkeypatch.setattr(term_quality.CandidateStore, "accept", fake_accept)
    monkeypatch.setattr(term_quality.CandidateStore, "reject", fake_reject)

    report = term_quality.evaluate_quality(term_quality.FIXTURE_PATH, work_dir=tmp_path)
    assert report.passed
    assert calls["parse"] == len(fixture["model_responses"]) * 2  # 确定性检查执行两遍
    assert calls["filter"] == (len(fixture["model_responses"]) + len(fixture["boundary_cases"])) * 2
    assert calls["compliance"] == len(fixture["compliance_cases"]) * 2
    assert calls["store_record"] == 3 * 2
    assert calls["accept"] == 1 * 2
    assert calls["reject"] == 1 * 2


def test_evaluation_writes_only_inside_work_dir(tmp_path):
    work = tmp_path / "work"
    report = term_quality.evaluate_quality(term_quality.FIXTURE_PATH, work_dir=work)
    assert report.passed
    assert work.is_dir()
    # 评测临时状态只落在 work_dir（含两次执行的 run-1/run-2 子目录）。
    run_dirs = sorted(path.name for path in work.iterdir() if path.is_dir())
    assert run_dirs == ["run-1", "run-2"]


def test_report_json_is_deterministic_across_runs(tmp_path):
    first = term_quality.evaluate_quality(term_quality.FIXTURE_PATH, work_dir=tmp_path / "a")
    second = term_quality.evaluate_quality(term_quality.FIXTURE_PATH, work_dir=tmp_path / "b")
    assert first.to_json() == second.to_json()
    assert first.metrics["repeat_run_determinism"] is True


def test_filter_check_semantics_use_cleaned_source_matching(tmp_path):
    report = term_quality.evaluate_quality(term_quality.FIXTURE_PATH, work_dir=tmp_path)
    detail = report.detail
    assert detail["responses"]
    for response_detail in detail["responses"]:
        assert response_detail["parse_ok"] is True
        assert response_detail["filter_checks_passed"] == response_detail["filter_checks_total"]


def test_quality_report_shape_is_machine_readable(tmp_path):
    report = term_quality.evaluate_quality(term_quality.FIXTURE_PATH, work_dir=tmp_path)
    payload = json.loads(report.to_json())
    assert payload["tool"] == "term-quality"
    assert payload["schema_version"] == 1
    assert payload["metric_definitions_version"] == term_quality.METRIC_DEFINITIONS_VERSION
    assert set(payload["metric_definitions"]) == set(term_quality.QUALITY_THRESHOLDS)
    for key, definition in payload["metric_definitions"].items():
        assert definition["numerator"]
        assert definition["denominator"]
        assert definition["direction"] in {"higher_is_better", "lower_is_better", "exact_true"}
        assert "empty_semantics" in definition
        assert definition["description"]
    assert set(payload["metrics"]) == set(term_quality.QUALITY_THRESHOLDS)
    assert payload["passed"] is True
    assert payload["failures"] == []
    assert "detail" in payload
    assert payload["fixture_sha256"] == hashlib.sha256(term_quality.FIXTURE_PATH.read_bytes()).hexdigest()


def test_single_wrong_core_target_drops_target_accuracy(tmp_path):
    fixture = term_quality.load_fixture(term_quality.FIXTURE_PATH)
    response = fixture["model_responses"][0]
    raw_terms = json.loads(response["raw"]["choices"][0]["message"]["content"])["terms"]
    for term in raw_terms:
        if term["source"] == "AD":
            term["target"] = "特应性皮炎（错误译法）"
    response["raw"]["choices"][0]["message"]["content"] = json.dumps({"terms": raw_terms}, ensure_ascii=False)
    response["expected_parsed_terms"] = [[term["source"], term["target"]] for term in raw_terms]
    mutated = tmp_path / "mutated-target.json"
    mutated.write_text(
        json.dumps(fixture, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    baseline_report = term_quality.evaluate_quality(term_quality.FIXTURE_PATH, work_dir=tmp_path / "base-work")
    mutated_report = term_quality.evaluate_quality(mutated, work_dir=tmp_path / "mut-work")
    assert baseline_report.metrics["candidate_target_accuracy"] == 1.0
    assert mutated_report.metrics["candidate_target_accuracy"] < 1.0
    assert mutated_report.metrics["candidate_precision"] == baseline_report.metrics["candidate_precision"]
    assert mutated_report.metrics["core_term_recall"] == baseline_report.metrics["core_term_recall"]
