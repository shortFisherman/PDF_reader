"""P2-01 黄金样本 fixture 完整性、指标值与版本化基线一致性测试。"""

from __future__ import annotations

import json

import pytest

from pdf_reader import term_quality
from pdf_reader.candidate_filter import filter_candidates
from pdf_reader.candidate_store import CandidateObservation, CandidateStore
from pdf_reader.term_extraction import parse_model_response


def test_fixture_covers_three_document_categories_and_real_issues():
    fixture = term_quality.load_fixture(term_quality.FIXTURE_PATH)
    assert fixture["metadata"]["provenance"] == "synthetic-original"
    assert fixture["metadata"]["license"] == "AGPL-3.0-only"
    assert "原创" in fixture["metadata"]["statement"]
    assert "AGPL-3.0-only" in fixture["metadata"]["statement"]
    categories = {doc["category"] for doc in fixture["documents"]}
    assert categories == {
        "medical_guideline",
        "technical_paper",
        "textbook_general_technical",
    }

    all_sources = {(response["document_id"], response["scope"]) for response in fixture["model_responses"]}
    for doc in fixture["documents"]:
        assert (doc["id"], "single_page") in all_sources
        assert (doc["id"], "batch") in all_sources

    common_words = {word for doc in fixture["documents"] for word in doc["golden"]["common_words"]}
    assert {"benefits", "cost", "confusion", "education", "burden"} <= common_words

    tcs_terms = [
        term
        for doc in fixture["documents"]
        if doc["id"] == "medical-guideline-ad-tcs"
        for term in doc["golden"]["core_terms"]
        if term["source"] == "TCS"
    ]
    assert tcs_terms
    assert "topical corticosteroids" in tcs_terms[0]["forms"]
    assert "topical corticosteroid" in tcs_terms[0]["forms"]

    boundary_sources = {case["source"] for case in fixture["boundary_cases"]}
    assert "AD" in boundary_sources
    assert "TCS" in boundary_sources

    scenario_sources = {scenario["source"] for scenario in fixture["store_scenarios"]}
    assert scenario_sources == {"TCS", "AD"}
    assert any(
        scenario["observations"][0]["target"] == "外用皮质类固醇" and scenario["observations"][1]["count"] == 10
        for scenario in fixture["store_scenarios"]
        if scenario["id"] == "tcs-wrong-first-then-correct"
    )
    assert any(
        scenario.get("reject_target") is not None and scenario.get("later_observations")
        for scenario in fixture["store_scenarios"]
        if scenario["id"] == "ad-rejected-not-reprompted"
    )


def test_each_model_response_parses_to_expected_terms():
    fixture = term_quality.load_fixture(term_quality.FIXTURE_PATH)
    docs = {doc["id"]: doc for doc in fixture["documents"]}
    for response in fixture["model_responses"]:
        raw = json.dumps(response["raw"], ensure_ascii=False).encode("utf-8")
        parsed = parse_model_response(raw)
        assert [[item.source, item.target] for item in parsed] == response["expected_parsed_terms"]

        doc = docs[response["document_id"]]
        pages = {page["page"]: page["text"] for page in doc["pages"]}
        selected = sorted(response["pages"])
        sent_text = "\n".join(pages[page] for page in selected)
        chunks = [(page, pages[page]) for page in selected]
        filtered = filter_candidates(parsed, sent_text, chunks)
        by_source = {term_quality.normalize_source_key(item.source): item for item in filtered}
        for source, expected in response["expected_filter"].items():
            item = by_source[term_quality.normalize_source_key(source)]
            actual_kept = item.reason is None
            assert actual_kept is expected["kept"], (response["id"], source)
            assert item.reason == expected["reason"], (response["id"], source)


def test_full_evaluation_metrics_match_golden_values(tmp_path):
    report = term_quality.evaluate_quality(term_quality.FIXTURE_PATH, work_dir=tmp_path)
    metrics = report.metrics
    assert metrics["candidate_precision"] == pytest.approx(23 / 27)
    assert metrics["candidate_target_accuracy"] == pytest.approx(1.0)
    assert metrics["core_term_recall"] == pytest.approx(21 / 24)
    assert metrics["single_page_recall"] == pytest.approx(8 / 11)
    assert metrics["batch_recall"] == pytest.approx(1.0)
    assert metrics["batch_minus_single_core_recall_delta"] == pytest.approx(3 / 11)
    assert metrics["common_word_contamination_rate"] == pytest.approx(0.0)
    assert metrics["authoritative_compliance_rate"] == pytest.approx(3 / 4)
    assert metrics["compliance_fail_detected_rate"] == pytest.approx(1.0)
    assert metrics["rejected_candidate_reprompt_rate"] == pytest.approx(0.0)
    assert metrics["wrong_first_translation_lock_rate"] == pytest.approx(0.0)
    assert metrics["parse_check_pass_rate"] == pytest.approx(1.0)
    assert metrics["filter_check_pass_rate"] == pytest.approx(1.0)
    assert metrics["boundary_check_pass_rate"] == pytest.approx(1.0)
    assert metrics["repeat_run_determinism"] is True
    assert report.passed
    assert report.failures == ()


def test_versioned_baseline_matches_current_report(tmp_path):
    report = term_quality.evaluate_quality(term_quality.FIXTURE_PATH, work_dir=tmp_path)
    baseline = term_quality.load_baseline(term_quality.BASELINE_PATH)
    assert baseline["schema_version"] == term_quality.QUALITY_SCHEMA_VERSION
    assert baseline["metric_definitions_version"] == term_quality.METRIC_DEFINITIONS_VERSION
    assert baseline["fixture"] == str(term_quality.FIXTURE_PATH.relative_to(term_quality.REPO_ROOT))
    assert baseline["fixture_sha256"] == report.fixture_sha256
    assert baseline["metrics"] == report.metrics
    _, drift = term_quality.compare_baseline(
        report.metrics,
        baseline["metrics"],
        tolerance=term_quality.DRIFT_TOLERANCE,
    )
    assert drift == ()


def test_store_scenario_wrong_first_translation_does_not_lock(tmp_path):
    scenario_dir = tmp_path / ("0" * 64)
    scenario_dir.mkdir()
    store = CandidateStore(scenario_dir)
    store.record_observations(
        [
            CandidateObservation(source="TCS", target="外用皮质类固醇", pages=(1,)),
            *[CandidateObservation(source="TCS", target="外用糖皮质激素", pages=(1, 2, 3)) for _ in range(10)],
        ],
        strategy_version="quality-eval/1",
    )
    entry, _ = store.accept("TCS")
    assert entry.accepted_target == "外用糖皮质激素"


def test_store_scenario_rejected_target_is_not_reprompted(tmp_path):
    scenario_dir = tmp_path / ("1" * 64)
    scenario_dir.mkdir()
    store = CandidateStore(scenario_dir)
    store.record_observations(
        [CandidateObservation(source="AD", target="阿尔茨海默氏病", pages=(1,))],
        strategy_version="quality-eval/1",
    )
    store.reject("AD", target="阿尔茨海默氏病")
    store.record_observations(
        [CandidateObservation(source="AD", target="阿尔茨海默氏病", pages=(2,)) for _ in range(5)],
        strategy_version="quality-eval/1",
    )
    summaries = {summary.source_key: summary for summary in store.candidate_summaries()}
    summary = summaries[term_quality.normalize_source_key("AD")]
    rejected = [target for target in summary.targets if target.target == "阿尔茨海默氏病"]
    assert len(rejected) == 1
    assert rejected[0].suppressed is True
    assert len(summaries) == 1


def test_evaluation_does_not_write_repo_cache_or_docs(tmp_path):
    cache_before = (
        {
            str(path.relative_to(term_quality.REPO_ROOT / "cache"))
            for path in (term_quality.REPO_ROOT / "cache").rglob("*")
        }
        if (term_quality.REPO_ROOT / "cache").exists()
        else set()
    )
    docs_before = {
        str(path.relative_to(term_quality.REPO_ROOT / "docs")) for path in (term_quality.REPO_ROOT / "docs").rglob("*")
    }
    term_quality.evaluate_quality(term_quality.FIXTURE_PATH, work_dir=tmp_path)
    cache_after = (
        {
            str(path.relative_to(term_quality.REPO_ROOT / "cache"))
            for path in (term_quality.REPO_ROOT / "cache").rglob("*")
        }
        if (term_quality.REPO_ROOT / "cache").exists()
        else set()
    )
    docs_after = {
        str(path.relative_to(term_quality.REPO_ROOT / "docs")) for path in (term_quality.REPO_ROOT / "docs").rglob("*")
    }
    assert cache_after == cache_before
    assert docs_after == docs_before
