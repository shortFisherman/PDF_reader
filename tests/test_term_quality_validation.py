"""P2-01 fixture schema 校验分支测试：每个结构错误都 fail-closed。"""

from __future__ import annotations

import copy
from collections.abc import Callable

import pytest

from pdf_reader import term_quality

FixtureMutator = Callable[[dict], None]


def _base() -> dict:
    return copy.deepcopy(term_quality.load_fixture(term_quality.FIXTURE_PATH))


def _expect_invalid(mutator: FixtureMutator) -> None:
    fixture = _base()
    mutator(fixture)
    with pytest.raises(term_quality.TermQualityError):
        term_quality.validate_fixture(fixture)


def test_document_validation_fail_closed():
    cases: dict[str, FixtureMutator] = {
        "empty_id": lambda f: f["documents"][0].__setitem__("id", ""),
        "duplicate_id": lambda f: f["documents"][1].__setitem__("id", f["documents"][0]["id"]),
        "invalid_category": lambda f: f["documents"][0].__setitem__("category", "unknown"),
        "empty_pages": lambda f: f["documents"][0].__setitem__("pages", []),
        "invalid_page_number": lambda f: f["documents"][0]["pages"][0].__setitem__("page", 0),
        "duplicate_page": lambda f: f["documents"][0]["pages"].append(copy.deepcopy(f["documents"][0]["pages"][0])),
        "empty_page_text": lambda f: f["documents"][0]["pages"][0].__setitem__("text", " "),
        "missing_golden": lambda f: f["documents"][0].pop("golden"),
        "empty_core_terms": lambda f: f["documents"][0]["golden"].__setitem__("core_terms", []),
        "empty_core_source": lambda f: f["documents"][0]["golden"]["core_terms"][0].__setitem__("source", ""),
        "empty_forms": lambda f: f["documents"][0]["golden"]["core_terms"][0].__setitem__("forms", []),
        "source_not_in_forms": lambda f: f["documents"][0]["golden"]["core_terms"][0].__setitem__("forms", ["other"]),
        "empty_target": lambda f: f["documents"][0]["golden"]["core_terms"][0].__setitem__("expected_target", ""),
        "term_page_out_of_doc": lambda f: f["documents"][0]["golden"]["core_terms"][0].__setitem__("pages", [99]),
        "common_words_not_list": lambda f: f["documents"][0]["golden"].__setitem__("common_words", "benefits"),
        "empty_common_words": lambda f: f["documents"][0]["golden"].__setitem__("common_words", []),
        "common_word_not_in_text": lambda f: f["documents"][0]["golden"]["common_words"].append("nevermentionedword"),
        "duplicate_core_form": lambda f: next(
            term for term in f["documents"][2]["golden"]["core_terms"] if term["source"] == "TCP handshake"
        )["forms"].append("TCP"),
    }
    for label, mutator in cases.items():
        _expect_invalid(mutator)


def test_response_validation_fail_closed():
    def duplicate_scope(fixture: dict) -> None:
        twin = copy.deepcopy(fixture["model_responses"][0])
        twin["id"] = "twin"
        fixture["model_responses"].append(twin)

    cases: dict[str, FixtureMutator] = {
        "empty_responses": lambda f: f.__setitem__("model_responses", []),
        "duplicate_response_id": lambda f: f["model_responses"][1].__setitem__("id", f["model_responses"][0]["id"]),
        "unknown_document": lambda f: f["model_responses"][0].__setitem__("document_id", "missing"),
        "invalid_scope": lambda f: f["model_responses"][0].__setitem__("scope", "all"),
        "duplicate_scope": duplicate_scope,
        "invalid_response_page": lambda f: f["model_responses"][0].__setitem__("pages", [99]),
        "raw_without_choices": lambda f: f["model_responses"][0].__setitem__("raw", {"message": {}}),
        "empty_parsed_terms": lambda f: f["model_responses"][0].__setitem__("expected_parsed_terms", []),
        "empty_expected_filter": lambda f: f["model_responses"][0].__setitem__("expected_filter", {}),
        "invalid_parsed_pair": lambda f: f["model_responses"][0]["expected_parsed_terms"].append(["only"]),
        "filter_source_not_parsed": lambda f: f["model_responses"][0]["expected_filter"].__setitem__(
            "missing", {"kept": True, "reason": None}
        ),
        "filter_kept_not_bool": lambda f: f["model_responses"][0]["expected_filter"]["AD"].__setitem__("kept", "yes"),
        "kept_with_reason": lambda f: f["model_responses"][0]["expected_filter"]["AD"].__setitem__("reason", "why"),
        "rejected_without_reason": lambda f: f["model_responses"][0]["expected_filter"]["benefits"].__setitem__(
            "reason", None
        ),
    }
    for label, mutator in cases.items():
        _expect_invalid(mutator)


def test_scope_and_core_coverage_validation_fail_closed():
    def remove_single(fixture: dict) -> None:
        fixture["model_responses"] = [
            response
            for response in fixture["model_responses"]
            if not (response["document_id"] == fixture["documents"][0]["id"] and response["scope"] == "single_page")
        ]

    def core_not_covered(fixture: dict) -> None:
        fixture["documents"][0]["golden"]["core_terms"][0]["pages"] = [7]

    cases: dict[str, FixtureMutator] = {
        "missing_single_scope": remove_single,
        "core_term_uncovered": core_not_covered,
    }
    for label, mutator in cases.items():
        _expect_invalid(mutator)


def test_required_sections_cannot_be_empty_or_missing():
    cases: dict[str, FixtureMutator] = {
        "missing_compliance": lambda f: f.pop("compliance_cases"),
        "empty_compliance": lambda f: f.__setitem__("compliance_cases", []),
        "missing_boundary": lambda f: f.pop("boundary_cases"),
        "empty_boundary": lambda f: f.__setitem__("boundary_cases", []),
        "missing_store": lambda f: f.pop("store_scenarios"),
        "empty_store": lambda f: f.__setitem__("store_scenarios", []),
        "missing_metadata": lambda f: f.pop("metadata"),
        "wrong_provenance": lambda f: f["metadata"].__setitem__("provenance", "scraped-from-web"),
        "wrong_license": lambda f: f["metadata"].__setitem__("license", "MIT"),
        "statement_without_original": lambda f: f["metadata"].__setitem__("statement", "AGPL-3.0-only"),
        "statement_without_license": lambda f: f["metadata"].__setitem__("statement", "本文本为原创合成"),
    }
    for label, mutator in cases.items():
        _expect_invalid(mutator)


def test_compliance_coverage_requires_pass_fail_unknown():
    def drop_fail(fixture: dict) -> None:
        fixture["compliance_cases"] = [case for case in fixture["compliance_cases"] if case["expected"] != "fail"]

    def all_pass(fixture: dict) -> None:
        for case in fixture["compliance_cases"]:
            case["expected"] = "pass"

    cases: dict[str, FixtureMutator] = {
        "drop_fail": drop_fail,
        "all_pass": all_pass,
    }
    for label, mutator in cases.items():
        _expect_invalid(mutator)


def test_boundary_coverage_requires_ad_and_tcs_cases():
    def drop_ad_rejected(fixture: dict) -> None:
        fixture["boundary_cases"] = [
            case for case in fixture["boundary_cases"] if not (case["source"] == "AD" and not case["expected_kept"])
        ]

    def drop_tcs_kept(fixture: dict) -> None:
        fixture["boundary_cases"] = [
            case for case in fixture["boundary_cases"] if not (case["source"] == "TCS" and case["expected_kept"])
        ]

    def drop_tcs_full_form(fixture: dict) -> None:
        fixture["boundary_cases"] = [
            case for case in fixture["boundary_cases"] if not (case["source"] == "topical corticosteroids")
        ]

    cases: dict[str, FixtureMutator] = {
        "drop_ad_rejected": drop_ad_rejected,
        "drop_tcs_kept": drop_tcs_kept,
        "drop_tcs_full_form": drop_tcs_full_form,
    }
    for label, mutator in cases.items():
        _expect_invalid(mutator)


def test_store_coverage_requires_wrong_first_and_rejected_paths():
    def drop_rejected(fixture: dict) -> None:
        fixture["store_scenarios"] = [
            scenario for scenario in fixture["store_scenarios"] if scenario.get("reject_target") is None
        ]

    def single_target_wrong_first(fixture: dict) -> None:
        wrong_first = next(scenario for scenario in fixture["store_scenarios"] if scenario.get("reject_target") is None)
        wrong_first["observations"] = [wrong_first["observations"][1]]

    cases: dict[str, FixtureMutator] = {
        "drop_rejected": drop_rejected,
        "single_target_wrong_first": single_target_wrong_first,
    }
    for label, mutator in cases.items():
        _expect_invalid(mutator)


def test_case_validation_fail_closed():
    cases: dict[str, FixtureMutator] = {
        "duplicate_compliance_id": lambda f: f["compliance_cases"][1].__setitem__("id", f["compliance_cases"][0]["id"]),
        "empty_active_terms": lambda f: f["compliance_cases"][0].__setitem__("active_terms", []),
        "invalid_active_pair": lambda f: f["compliance_cases"][0]["active_terms"].append(["solo"]),
        "missing_translated_text": lambda f: f["compliance_cases"][0].pop("translated_text"),
        "invalid_expected_verdict": lambda f: f["compliance_cases"][0].__setitem__("expected", "maybe"),
        "duplicate_boundary_id": lambda f: f["boundary_cases"][1].__setitem__("id", f["boundary_cases"][0]["id"]),
        "missing_boundary_source": lambda f: f["boundary_cases"][0].pop("source"),
        "missing_boundary_text": lambda f: f["boundary_cases"][0].pop("text"),
        "boundary_kept_not_bool": lambda f: f["boundary_cases"][0].__setitem__("expected_kept", "yes"),
        "boundary_kept_with_reason": lambda f: f["boundary_cases"][0].__setitem__("expected_reason", "why"),
        "boundary_rejected_without_reason": lambda f: f["boundary_cases"][1].__setitem__("expected_reason", None),
        "duplicate_scenario_id": lambda f: f["store_scenarios"][1].__setitem__("id", f["store_scenarios"][0]["id"]),
        "missing_scenario_source": lambda f: f["store_scenarios"][0].pop("source"),
        "empty_scenario_observations": lambda f: f["store_scenarios"][0].__setitem__("observations", []),
        "bad_observation_target": lambda f: f["store_scenarios"][0]["observations"][0].__setitem__("target", ""),
        "bad_observation_pages": lambda f: f["store_scenarios"][0]["observations"][0].__setitem__("pages", []),
        "bad_observation_count": lambda f: f["store_scenarios"][0]["observations"][0].__setitem__("count", 0),
        "missing_recommended_target": lambda f: f["store_scenarios"][0].pop("expected_recommended_target"),
        "bad_reject_target": lambda f: f["store_scenarios"][1].__setitem__("reject_target", ""),
        "later_without_reject": lambda f: f["store_scenarios"][0].__setitem__(
            "later_observations", f["store_scenarios"][0]["observations"]
        ),
        "missing_suppressed_flag": lambda f: f["store_scenarios"][1].pop("expected_suppressed_after_reject"),
        "missing_entries_count": lambda f: f["store_scenarios"][1].pop("expected_entries_after"),
        "rejected_with_recommended_target": lambda f: f["store_scenarios"][1].__setitem__(
            "expected_recommended_target", "阿尔茨海默氏病"
        ),
        "wrong_first_with_reject_fields": lambda f: f["store_scenarios"][0].__setitem__(
            "expected_suppressed_after_reject", True
        ),
    }
    for label, mutator in cases.items():
        _expect_invalid(mutator)
