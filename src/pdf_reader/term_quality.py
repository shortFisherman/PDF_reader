"""P2-01 术语黄金样本与质量门槛（离线确定性评测）。

本模块把 P2-01 的验收边界实现为可重复运行的纯 Python 评测：

- 黄金样本是仓库内版本控制的 JSON fixture（``tests/fixtures/term_quality/``），
  覆盖医学指南、技术论文、教材/一般技术文档三类最小文本；
- 模型响应 fixture 保存为受控 chat completions 响应体，解析与后置过滤可分别评测，
  分别复用 ``term_extraction.parse_model_response`` 与 ``candidate_filter.filter_candidates``；
- 用户合规率复用 ``terminology_compliance.verify_translated_text``；
- 错误首译锁死与被拒绝候选重复提示复用 ``CandidateStore`` 的真实观察/拒绝/摘要语义；
- 评测不联网、不需要 API Key、不写真实 ``cache/``/``docs/`` 用户数据；
  临时状态只写在调用方提供的 ``work_dir``（或系统临时目录）内。

报告 JSON 不含时间戳、临时路径或正文之外的敏感内容，重复执行字节一致；
``repeat_run_determinism`` 指标由两次独立运行比较得出。
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pdf_reader.candidate_filter import filter_candidates
from pdf_reader.candidate_store import CandidateObservation, CandidateStore
from pdf_reader.term_extraction import TermCandidate, parse_model_response
from pdf_reader.term_model import normalize_source_key
from pdf_reader.terminology_compliance import ComplianceStatus, verify_translated_text

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "term_quality" / "fixture.json"
BASELINE_PATH = REPO_ROOT / "docs" / "reports" / "term-quality-baseline.json"

QUALITY_SCHEMA_VERSION = 1
METRIC_DEFINITIONS_VERSION = 1
DRIFT_TOLERANCE = 0.05
DOCUMENT_CATEGORIES = frozenset({"medical_guideline", "technical_paper", "textbook_general_technical"})
SCOPES = frozenset({"single_page", "batch"})

# 门槛以防退化为主：除硬不变量外不追求虚假 100%。方向由
# ``LOWER_IS_BETTER_METRICS`` 区分；数值都保留到 6 位小数。
QUALITY_THRESHOLDS: dict[str, float | bool] = {
    "candidate_precision": 0.75,
    "candidate_target_accuracy": 0.9,
    "core_term_recall": 0.8,
    "single_page_recall": 0.5,
    "batch_recall": 0.8,
    "batch_minus_single_core_recall_delta": -0.25,
    "common_word_contamination_rate": 0.0,
    "authoritative_compliance_rate": 0.5,
    "repeat_run_determinism": True,
    "rejected_candidate_reprompt_rate": 0.0,
    "wrong_first_translation_lock_rate": 0.0,
    "filter_check_pass_rate": 1.0,
    "parse_check_pass_rate": 1.0,
    "boundary_check_pass_rate": 1.0,
    "compliance_fail_detected_rate": 1.0,
}

LOWER_IS_BETTER_METRICS = frozenset(
    {
        "common_word_contamination_rate",
        "rejected_candidate_reprompt_rate",
        "wrong_first_translation_lock_rate",
    }
)

METRIC_DEFINITIONS: dict[str, dict[str, str]] = {
    "candidate_precision": {
        "numerator": "kept candidates whose cleaned source matches a golden core-term form",
        "denominator": "all kept candidates (after production candidate_filter)",
        "direction": "higher_is_better",
        "empty_semantics": (
            "1.0 when there are no kept candidates (no false positives; core_term_recall guards missing candidates)"
        ),
        "description": "术语识别精确率：只判断识别出的 source 是否属于黄金核心术语，不判断中文译法。",
    },
    "candidate_target_accuracy": {
        "numerator": "term-identified (TP) kept candidates whose target equals the matched golden expected_target",
        "denominator": "TP kept candidates (kept candidates whose source matches a golden core-term form)",
        "direction": "higher_is_better",
        "empty_semantics": "1.0 when there are no TP candidates (vacuous; core_term_recall guards coverage)",
        "description": "黄金中文目标准确率：只在已识别为核心术语的候选上考核 target 是否等于人工 golden 期望译法。",
    },
    "core_term_recall": {
        "numerator": "golden core terms covered by at least one kept candidate matching one of its forms",
        "denominator": "golden core terms expected for the response scope (term pages intersect response pages)",
        "direction": "higher_is_better",
        "empty_semantics": "1.0 when a scope has no expected terms (fixture validation requires non-empty core_terms)",
        "description": (
            "核心术语召回率：按 source/forms 覆盖判断，不要求 target 正确"
            "（target 由 candidate_target_accuracy 单独考核）。"
        ),
    },
    "single_page_recall": {
        "numerator": "covered core terms in single_page response groups",
        "denominator": "expected core terms in single_page response groups",
        "direction": "higher_is_better",
        "empty_semantics": "1.0 when there are no single_page groups (fixture validation requires both scopes)",
        "description": "单页范围的 core_term_recall。",
    },
    "batch_recall": {
        "numerator": "covered core terms in batch response groups",
        "denominator": "expected core terms in batch response groups",
        "direction": "higher_is_better",
        "empty_semantics": "1.0 when there are no batch groups (fixture validation requires both scopes)",
        "description": "批量范围的 core_term_recall。",
    },
    "batch_minus_single_core_recall_delta": {
        "numerator": "weighted batch_recall minus weighted single_page_recall (aggregate over all response groups)",
        "denominator": "1 (directional difference, not an absolute consistency metric)",
        "direction": "higher_is_better",
        "empty_semantics": "0.0 when no paired scopes exist (fixture validation requires both per document)",
        "description": (
            "有方向指标：batch_recall - single_page_recall；阈值只防批量相对单页"
            "召回退化（低于 -0.25 失败），正值表示批量覆盖更完整，不代表单页/批量一致性。"
        ),
    },
    "common_word_contamination_rate": {
        "numerator": "kept candidates whose normalized source is a golden common word",
        "denominator": "parsed candidates whose normalized source is a golden common word",
        "direction": "lower_is_better",
        "empty_semantics": "0.0 when no common words were proposed by the model responses",
        "description": "普通词污染率：模型提出且过滤后仍保留的黄金普通词占比。",
    },
    "authoritative_compliance_rate": {
        "numerator": "PASS term checks across all compliance cases",
        "denominator": "PASS + FAIL term checks (UNKNOWN verdicts excluded from denominator)",
        "direction": "higher_is_better",
        "empty_semantics": "1.0 when there are no verifiable term checks (fixture requires pass/fail/unknown cases)",
        "description": (
            "用户权威术语合规率：翻译文本中权威 target 实际出现的检查通过占比；"
            "fixture 内故意包含 fail 案例，因此不是天然 100%。"
        ),
    },
    "compliance_fail_detected_rate": {
        "numerator": "expected-fail compliance cases whose verdict is FAIL",
        "denominator": "expected-fail compliance cases",
        "direction": "higher_is_better",
        "empty_semantics": "1.0 when there are no expected-fail cases (fixture validation requires a fail case)",
        "description": "失败路径检测率：确认合规门确实能发现故意不合规的译文。",
    },
    "repeat_run_determinism": {
        "numerator": "two independent evaluation runs produce identical metrics and detail",
        "denominator": "1 (boolean)",
        "direction": "exact_true",
        "empty_semantics": "n/a; always computed from two runs",
        "description": "重复运行确定性：同一 fixture 两次独立执行（不同临时目录）报告完全一致。",
    },
    "rejected_candidate_reprompt_rate": {
        "numerator": "rejected targets still non-suppressed after later observations",
        "denominator": "rejected targets in rejected scenarios",
        "direction": "lower_is_better",
        "empty_semantics": "0.0 when there are no rejected scenarios (fixture validation requires one)",
        "description": "被拒绝候选重复提示率：用户 reject 后再记录观察，rejected target 仍不得以可提示状态出现。",
    },
    "wrong_first_translation_lock_rate": {
        "numerator": "wrong-first scenarios where accept() no-arg did not return the expected target",
        "denominator": (
            "wrong-first scenarios (observations with a wrong first target followed by more frequent correct target)"
        ),
        "direction": "lower_is_better",
        "empty_semantics": "0.0 when there are no wrong-first scenarios (fixture validation requires one)",
        "description": "错误首译锁死率：首次错误译法不得压制后续高频正确建议。",
    },
    "parse_check_pass_rate": {
        "numerator": "model responses whose parsed terms equal expected_parsed_terms",
        "denominator": "all model responses",
        "direction": "higher_is_better",
        "empty_semantics": "1.0 when there are no responses (fixture validation requires non-empty responses)",
        "description": "模型响应解析检查通过率。",
    },
    "filter_check_pass_rate": {
        "numerator": "expected_filter checks whose kept/reason match",
        "denominator": "all expected_filter checks",
        "direction": "higher_is_better",
        "empty_semantics": (
            "1.0 when there are no filter checks (fixture validation requires non-empty filter checks per response)"
        ),
        "description": "后置过滤期望检查通过率：逐条固定 kept/reason，包括 AD/TCS 边界与普通词拒绝。",
    },
    "boundary_check_pass_rate": {
        "numerator": "boundary cases whose expected kept/reason match",
        "denominator": "all boundary cases",
        "direction": "higher_is_better",
        "empty_semantics": "1.0 when there are no boundary cases (fixture validation requires kept and rejected cases)",
        "description": "缩写/全称边界检查通过率：独立 AD/TCS 可命中，单词内部子串不误命中。",
    },
}


class TermQualityError(RuntimeError):
    """黄金样本/评测配置错误；消息只含稳定原因，不含正文或 Prompt。"""


@dataclass(frozen=True)
class QualityReport:
    """一次质量评测的确定性报告。"""

    fixture: str
    fixture_sha256: str
    schema_version: int
    metrics: dict[str, float | bool]
    detail: dict[str, Any]
    thresholds: dict[str, float | bool]
    passed: bool
    failures: tuple[str, ...]

    def to_json(self) -> str:
        payload = {
            "tool": "term-quality",
            "schema_version": self.schema_version,
            "metric_definitions_version": METRIC_DEFINITIONS_VERSION,
            "metric_definitions": METRIC_DEFINITIONS,
            "fixture": self.fixture,
            "fixture_sha256": self.fixture_sha256,
            "metrics": self.metrics,
            "thresholds": self.thresholds,
            "passed": self.passed,
            "failures": list(self.failures),
            "detail": self.detail,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


@dataclass(frozen=True)
class _RunResult:
    metrics: dict[str, float | bool]
    detail: dict[str, Any]


def ratio(part: int, total: int, *, empty_value: float) -> float:
    """显式空集合语义：分母为 0 时返回调用方指定的空集合默认值。"""
    if total <= 0:
        return empty_value
    return part / total


def load_fixture(path: str | Path) -> dict[str, Any]:
    """加载并校验黄金样本 fixture；任何结构问题都抛 ``TermQualityError``。"""
    fixture_path = Path(path)
    try:
        data = json.loads(fixture_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise TermQualityError(f"failed to load fixture {fixture_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise TermQualityError(f"invalid fixture payload in {fixture_path}")
    validate_fixture(data)
    return data


def validate_fixture(fixture: dict[str, Any]) -> None:
    """校验 fixture schema；不修改输入，不读真实数据。"""
    _validate_metadata(fixture)
    if fixture.get("schema_version") != QUALITY_SCHEMA_VERSION:
        raise TermQualityError(f"unsupported fixture schema_version: {fixture.get('schema_version')!r}")
    documents = fixture.get("documents")
    if not isinstance(documents, list) or not documents:
        raise TermQualityError("fixture requires non-empty documents")
    categories = {doc.get("category") for doc in documents if isinstance(doc, dict)}
    if not DOCUMENT_CATEGORIES.issubset(categories):
        raise TermQualityError("fixture requires all three document categories")

    all_docs: dict[str, dict[str, Any]] = {}
    doc_ids: set[str] = set()
    for doc in documents:
        _validate_document(doc, doc_ids, all_docs)

    responses = fixture.get("model_responses")
    if not isinstance(responses, list) or not responses:
        raise TermQualityError("fixture requires non-empty model_responses")
    response_ids: set[str] = set()
    seen_scope_pairs: set[tuple[str, str]] = set()
    for response in responses:
        _validate_response(response, all_docs, response_ids, seen_scope_pairs)
    for doc in documents:
        doc_id = str(doc["id"])
        if (doc_id, "single_page") not in seen_scope_pairs or (
            doc_id,
            "batch",
        ) not in seen_scope_pairs:
            raise TermQualityError(f"document {doc_id} requires both single_page and batch responses")
    for doc in documents:
        _validate_core_term_coverage(doc, responses)

    compliance_cases = fixture.get("compliance_cases")
    if not isinstance(compliance_cases, list) or not compliance_cases:
        raise TermQualityError("fixture requires non-empty compliance_cases")
    compliance_ids: set[str] = set()
    for case in compliance_cases:
        _validate_compliance_case(case, compliance_ids)
    if not {"pass", "fail", "unknown"} <= {case["expected"] for case in compliance_cases}:
        raise TermQualityError("compliance_cases must cover pass, fail and unknown verdicts")

    boundary_cases = fixture.get("boundary_cases")
    if not isinstance(boundary_cases, list) or not boundary_cases:
        raise TermQualityError("fixture requires non-empty boundary_cases")
    boundary_ids: set[str] = set()
    for case in boundary_cases:
        _validate_boundary_case(case, boundary_ids)
    _validate_boundary_coverage(boundary_cases)

    store_scenarios = fixture.get("store_scenarios")
    if not isinstance(store_scenarios, list) or not store_scenarios:
        raise TermQualityError("fixture requires non-empty store_scenarios")
    scenario_ids: set[str] = set()
    for scenario in store_scenarios:
        _validate_store_scenario(scenario, scenario_ids)
    _validate_store_coverage(store_scenarios)


def _validate_metadata(fixture: dict[str, Any]) -> None:
    """校验 fixture 的 provenance/license 元数据（测试原创/合成文本，AGPL-3.0-only）。"""
    metadata = fixture.get("metadata")
    if not isinstance(metadata, dict):
        raise TermQualityError("fixture requires metadata provenance/license block")
    if metadata.get("provenance") != "synthetic-original":
        raise TermQualityError("fixture metadata.provenance must be 'synthetic-original'")
    if metadata.get("license") != "AGPL-3.0-only":
        raise TermQualityError("fixture metadata.license must be 'AGPL-3.0-only'")
    statement = metadata.get("statement")
    if (
        not isinstance(statement, str)
        or not statement.strip()
        or "原创" not in statement
        or "AGPL-3.0-only" not in statement
    ):
        raise TermQualityError("fixture metadata.statement must declare original/synthetic text under AGPL-3.0-only")


def _validate_document(
    doc: Any,
    doc_ids: set[str],
    all_docs: dict[str, dict[str, Any]],
) -> None:
    if not isinstance(doc, dict):
        raise TermQualityError("document must be a JSON object")
    doc_id = doc.get("id")
    if not isinstance(doc_id, str) or not doc_id.strip():
        raise TermQualityError("document requires non-empty id")
    if doc_id in doc_ids:
        raise TermQualityError(f"duplicate document id: {doc_id!r}")
    doc_ids.add(doc_id)
    if doc.get("category") not in DOCUMENT_CATEGORIES:
        raise TermQualityError(f"invalid document category in {doc_id!r}")
    pages = doc.get("pages")
    if not isinstance(pages, list) or not pages:
        raise TermQualityError(f"document {doc_id!r} requires non-empty pages")
    page_numbers: list[int] = []
    for page in pages:
        if not isinstance(page, dict):
            raise TermQualityError(f"invalid page in {doc_id!r}")
        page_number = page.get("page")
        text = page.get("text")
        if isinstance(page_number, bool) or not isinstance(page_number, int) or page_number < 1:
            raise TermQualityError(f"invalid page number in {doc_id!r}")
        if page_number in page_numbers:
            raise TermQualityError(f"duplicate page number in {doc_id!r}")
        page_numbers.append(page_number)
        if not isinstance(text, str) or not text.strip():
            raise TermQualityError(f"invalid page text in {doc_id!r}")
    golden = doc.get("golden")
    if not isinstance(golden, dict):
        raise TermQualityError(f"document {doc_id!r} requires golden")
    core_terms = golden.get("core_terms")
    if not isinstance(core_terms, list) or not core_terms:
        raise TermQualityError(f"document {doc_id!r} requires golden core_terms")
    form_owners: dict[str, str] = {}
    for term in core_terms:
        _validate_core_term(term, doc_id, page_numbers)
        for form in term["forms"]:
            form_key = normalize_source_key(form)
            owner = form_owners.get(form_key)
            if owner is not None and owner != normalize_source_key(term["source"]):
                raise TermQualityError(
                    f"duplicate core term form {form!r} in {doc_id!r} (owned by {owner!r} and {term['source']!r})"
                )
            form_owners[form_key] = normalize_source_key(term["source"])
    common_words = golden.get("common_words", [])
    if not isinstance(common_words, list) or not common_words:
        raise TermQualityError(f"document {doc_id!r} requires non-empty common_words list")
    page_text = " ".join(str(page.get("text")) for page in pages)
    for word in common_words:
        if not isinstance(word, str) or not word.strip():
            raise TermQualityError(f"invalid common word in {doc_id!r}")
        if word.lower() not in page_text.lower():
            raise TermQualityError(f"common word {word!r} not present in {doc_id!r} text")
    all_docs[doc_id] = doc


def _validate_core_term(
    term: Any,
    doc_id: str,
    page_numbers: list[int],
) -> None:
    if not isinstance(term, dict):
        raise TermQualityError(f"invalid core term in {doc_id!r}")
    source = term.get("source")
    forms = term.get("forms")
    expected_target = term.get("expected_target")
    term_pages = term.get("pages")
    if not isinstance(source, str) or not source.strip():
        raise TermQualityError(f"invalid core term source in {doc_id!r}")
    if not isinstance(forms, list) or not forms:
        raise TermQualityError(f"core term {source!r} requires forms")
    if not all(isinstance(form, str) and form.strip() for form in forms):
        raise TermQualityError(f"invalid core term forms for {source!r}")
    if normalize_source_key(source) not in {normalize_source_key(form) for form in forms}:
        raise TermQualityError(f"core term {source!r} must be present in its forms")
    if not isinstance(expected_target, str) or not expected_target.strip():
        raise TermQualityError(f"core term {source!r} requires expected_target")
    if not isinstance(term_pages, list) or not term_pages:
        raise TermQualityError(f"core term {source!r} requires pages")
    for page in term_pages:
        if isinstance(page, bool) or not isinstance(page, int) or page < 1 or page not in page_numbers:
            raise TermQualityError(f"core term {source!r} page {page!r} not in document {doc_id!r}")


def _validate_response(
    response: Any,
    all_docs: dict[str, dict[str, Any]],
    response_ids: set[str],
    seen_scope_pairs: set[tuple[str, str]],
) -> None:
    if not isinstance(response, dict):
        raise TermQualityError("model response must be a JSON object")
    response_id = response.get("id")
    if not isinstance(response_id, str) or not response_id.strip():
        raise TermQualityError("model response requires non-empty id")
    if response_id in response_ids:
        raise TermQualityError(f"duplicate model response id: {response_id!r}")
    response_ids.add(response_id)
    document_id = response.get("document_id")
    if not isinstance(document_id, str) or document_id not in all_docs:
        raise TermQualityError(f"unknown document_id in response {response_id!r}")
    scope = response.get("scope")
    if scope not in SCOPES:
        raise TermQualityError(f"invalid scope in response {response_id!r}")
    pair = (document_id, scope)
    if pair in seen_scope_pairs:
        raise TermQualityError(f"duplicate scope {scope!r} for document {document_id!r}")
    seen_scope_pairs.add(pair)
    doc_pages = {page["page"] for page in all_docs[document_id]["pages"]}
    pages = response.get("pages")
    if not isinstance(pages, list) or not pages:
        raise TermQualityError(f"response {response_id!r} requires pages")
    for page in pages:
        if isinstance(page, bool) or not isinstance(page, int) or page < 1 or page not in doc_pages:
            raise TermQualityError(f"invalid page in response {response_id!r}")
    raw = response.get("raw")
    if not isinstance(raw, dict) or not isinstance(raw.get("choices"), list) or not raw["choices"]:
        raise TermQualityError(f"response {response_id!r} requires raw chat response")
    parsed_terms = response.get("expected_parsed_terms")
    if not isinstance(parsed_terms, list) or not parsed_terms:
        raise TermQualityError(f"response {response_id!r} requires expected_parsed_terms")
    parsed_sources: set[str] = set()
    for pair_item in parsed_terms:
        if (
            not isinstance(pair_item, list)
            or len(pair_item) != 2
            or not all(isinstance(value, str) and value.strip() for value in pair_item)
        ):
            raise TermQualityError(f"invalid expected_parsed_terms in {response_id!r}")
        parsed_sources.add(normalize_source_key(str(pair_item[0])))
    expected_filter = response.get("expected_filter", {})
    if not isinstance(expected_filter, dict) or not expected_filter:
        raise TermQualityError(f"response {response_id!r} requires non-empty expected_filter dict")
    for source, expected in expected_filter.items():
        if not isinstance(source, str) or not source.strip():
            raise TermQualityError(f"invalid expected_filter source in {response_id!r}")
        if normalize_source_key(source) not in parsed_sources:
            raise TermQualityError(f"expected_filter source {source!r} missing from parsed terms in {response_id!r}")
        if not isinstance(expected, dict):
            raise TermQualityError(f"invalid expected_filter value in {response_id!r}")
        kept = expected.get("kept")
        reason = expected.get("reason")
        if not isinstance(kept, bool):
            raise TermQualityError(f"invalid expected_filter.kept in {response_id!r}")
        if kept and reason is not None:
            raise TermQualityError(f"kept candidate must have null reason in {response_id!r}")
        if not kept and not isinstance(reason, str):
            raise TermQualityError(f"rejected candidate requires reason in {response_id!r}")


def _validate_core_term_coverage(
    doc: dict[str, Any],
    responses: list[Any],
) -> None:
    doc_responses = [response for response in responses if response["document_id"] == doc["id"]]
    for term in doc["golden"]["core_terms"]:
        if not any(set(term["pages"]) & set(response["pages"]) for response in doc_responses):
            raise TermQualityError(f"core term {term['source']!r} not covered by any response in {doc['id']!r}")


def _validate_compliance_case(case: Any, ids: set[str]) -> None:
    if not isinstance(case, dict):
        raise TermQualityError("compliance case must be a JSON object")
    case_id = case.get("id")
    if not isinstance(case_id, str) or not case_id.strip():
        raise TermQualityError("compliance case requires non-empty id")
    if case_id in ids:
        raise TermQualityError(f"duplicate compliance case id: {case_id!r}")
    ids.add(case_id)
    active_terms = case.get("active_terms")
    if not isinstance(active_terms, list) or not active_terms:
        raise TermQualityError(f"compliance case {case_id!r} requires active_terms")
    for pair_item in active_terms:
        if (
            not isinstance(pair_item, list)
            or len(pair_item) != 2
            or not all(isinstance(value, str) and value.strip() for value in pair_item)
        ):
            raise TermQualityError(f"invalid active_terms in {case_id!r}")
    if not isinstance(case.get("translated_text"), str):
        raise TermQualityError(f"compliance case {case_id!r} requires translated_text")
    if case.get("expected") not in {"pass", "fail", "unknown"}:
        raise TermQualityError(f"invalid expected verdict in {case_id!r}")


def _validate_boundary_case(case: Any, ids: set[str]) -> None:
    if not isinstance(case, dict):
        raise TermQualityError("boundary case must be a JSON object")
    case_id = case.get("id")
    if not isinstance(case_id, str) or not case_id.strip():
        raise TermQualityError("boundary case requires non-empty id")
    if case_id in ids:
        raise TermQualityError(f"duplicate boundary case id: {case_id!r}")
    ids.add(case_id)
    if not isinstance(case.get("source"), str) or not case["source"].strip():
        raise TermQualityError(f"boundary case {case_id!r} requires source")
    if not isinstance(case.get("text"), str) or not case["text"].strip():
        raise TermQualityError(f"boundary case {case_id!r} requires text")
    if not isinstance(case.get("expected_kept"), bool):
        raise TermQualityError(f"boundary case {case_id!r} requires expected_kept")
    expected_reason = case.get("expected_reason")
    if case["expected_kept"] and expected_reason is not None:
        raise TermQualityError(f"kept boundary case {case_id!r} must have null reason")
    if not case["expected_kept"] and not isinstance(expected_reason, str):
        raise TermQualityError(f"rejected boundary case {case_id!r} requires expected_reason")


def _validate_store_scenario(scenario: Any, ids: set[str]) -> None:
    if not isinstance(scenario, dict):
        raise TermQualityError("store scenario must be a JSON object")
    scenario_id = scenario.get("id")
    if not isinstance(scenario_id, str) or not scenario_id.strip():
        raise TermQualityError("store scenario requires non-empty id")
    if scenario_id in ids:
        raise TermQualityError(f"duplicate store scenario id: {scenario_id!r}")
    ids.add(scenario_id)
    if not isinstance(scenario.get("source"), str) or not scenario["source"].strip():
        raise TermQualityError(f"store scenario {scenario_id!r} requires source")
    observations = scenario.get("observations")
    if not isinstance(observations, list) or not observations:
        raise TermQualityError(f"store scenario {scenario_id!r} requires observations")
    for item in observations:
        _validate_observation(item, scenario_id)
    reject_target = scenario.get("reject_target")
    later_observations = scenario.get("later_observations", [])
    if reject_target is not None:
        if "expected_recommended_target" in scenario:
            raise TermQualityError(
                f"rejected store scenario {scenario_id!r} must not carry expected_recommended_target"
            )
        if not isinstance(reject_target, str) or not reject_target.strip():
            raise TermQualityError(f"invalid reject_target in {scenario_id!r}")
        if not isinstance(later_observations, list):
            raise TermQualityError(f"invalid later_observations in {scenario_id!r}")
        for item in later_observations:
            _validate_observation(item, scenario_id)
        if not isinstance(scenario.get("expected_suppressed_after_reject"), bool):
            raise TermQualityError(f"store scenario {scenario_id!r} requires expected_suppressed_after_reject")
        expected_entries = scenario.get("expected_entries_after")
        if isinstance(expected_entries, bool) or not isinstance(expected_entries, int) or expected_entries < 1:
            raise TermQualityError(f"store scenario {scenario_id!r} requires expected_entries_after")
    elif later_observations:
        raise TermQualityError(f"store scenario {scenario_id!r} requires reject_target for later_observations")
    else:
        expected_recommended = scenario.get("expected_recommended_target")
        if not isinstance(expected_recommended, str) or not expected_recommended.strip():
            raise TermQualityError(f"wrong-first store scenario {scenario_id!r} requires expected_recommended_target")
        for forbidden in (
            "expected_suppressed_after_reject",
            "expected_entries_after",
        ):
            if forbidden in scenario:
                raise TermQualityError(f"wrong-first store scenario {scenario_id!r} must not carry {forbidden}")


def _validate_boundary_coverage(cases: list[Any]) -> None:
    """边界维度 fail-closed：必须同时固定 AD/TCS 的独立命中与子串误命中、TCS 全称命中。"""
    kept_ad = any(normalize_source_key(case["source"]) == "ad" and case["expected_kept"] for case in cases)
    rejected_ad_substring = any(
        normalize_source_key(case["source"]) == "ad"
        and not case["expected_kept"]
        and case.get("expected_reason") == "no_source_match"
        for case in cases
    )
    kept_tcs_abbr = any(normalize_source_key(case["source"]) == "tcs" and case["expected_kept"] for case in cases)
    rejected_tcs_substring = any(
        normalize_source_key(case["source"]) == "tcs"
        and not case["expected_kept"]
        and case.get("expected_reason") == "no_source_match"
        for case in cases
    )
    kept_tcs_full = any(
        normalize_source_key(case["source"]) == "topical corticosteroids" and case["expected_kept"] for case in cases
    )
    if not (kept_ad and rejected_ad_substring):
        raise TermQualityError("boundary_cases must cover AD standalone kept and AD substring false-positive")
    if not (kept_tcs_abbr and rejected_tcs_substring and kept_tcs_full):
        raise TermQualityError(
            "boundary_cases must cover TCS abbreviation kept, TCS substring false-positive and full-form kept"
        )


def _validate_store_coverage(scenarios: list[Any]) -> None:
    """候选存储维度 fail-closed：必须包含 wrong-first 与 rejected 两条主路径。"""
    wrong_first = [scenario for scenario in scenarios if scenario.get("reject_target") is None]
    rejected = [scenario for scenario in scenarios if scenario.get("reject_target") is not None]
    if not wrong_first:
        raise TermQualityError("store_scenarios must include a wrong-first scenario")
    if not rejected:
        raise TermQualityError("store_scenarios must include a rejected scenario")
    if not any(
        len({str(item["target"]) for item in scenario["observations"]}) >= 2
        and scenario["expected_recommended_target"] != scenario["observations"][0]["target"]
        for scenario in wrong_first
    ):
        raise TermQualityError(
            "wrong-first scenario must have a wrong first target and a different expected winning target"
        )
    if not any(
        scenario.get("later_observations")
        and any(str(item["target"]) == scenario["reject_target"] for item in scenario["later_observations"])
        and scenario["expected_suppressed_after_reject"] is True
        and scenario["expected_entries_after"] == 1
        for scenario in rejected
    ):
        raise TermQualityError(
            "rejected scenario must re-observe the rejected target and stay suppressed with a single entry"
        )


def _validate_observation(item: Any, scenario_id: str) -> None:
    if not isinstance(item, dict):
        raise TermQualityError(f"invalid observation in {scenario_id!r}")
    target = item.get("target")
    pages = item.get("pages")
    count = item.get("count")
    if not isinstance(target, str) or not target.strip():
        raise TermQualityError(f"invalid observation target in {scenario_id!r}")
    if not isinstance(pages, list) or not pages:
        raise TermQualityError(f"invalid observation pages in {scenario_id!r}")
    for page in pages:
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            raise TermQualityError(f"invalid observation page in {scenario_id!r}")
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise TermQualityError(f"invalid observation count in {scenario_id!r}")


def evaluate_quality(
    fixture_path: str | Path,
    *,
    work_dir: str | Path | None = None,
) -> QualityReport:
    """运行完整质量评测并比较两次独立执行以计算 repeat-run determinism。"""
    fixture = load_fixture(fixture_path)
    own_temp = work_dir is None
    work = Path(tempfile.mkdtemp(prefix="pdf-reader-term-quality-")) if work_dir is None else Path(work_dir)
    try:
        first = _evaluate_once(fixture, work / "run-1")
        second = _evaluate_once(fixture, work / "run-2")
    finally:
        if own_temp:
            shutil.rmtree(work, ignore_errors=True)
    deterministic = first.metrics == second.metrics and first.detail == second.detail
    metrics = dict(first.metrics)
    metrics["repeat_run_determinism"] = deterministic
    passed, failures = check_thresholds(metrics, QUALITY_THRESHOLDS)
    return QualityReport(
        fixture=_display_fixture(Path(fixture_path)),
        fixture_sha256=hashlib.sha256(Path(fixture_path).read_bytes()).hexdigest(),
        schema_version=QUALITY_SCHEMA_VERSION,
        metrics=metrics,
        detail=first.detail,
        thresholds=dict(QUALITY_THRESHOLDS),
        passed=passed,
        failures=failures,
    )


def _display_fixture(path: Path) -> str:
    """把仓库内 fixture 显示为可移植的仓库相对路径（POSIX 分隔符），仓库外保持绝对路径。"""
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def _evaluate_once(fixture: dict[str, Any], work_dir: Path) -> _RunResult:
    work_dir.mkdir(parents=True, exist_ok=True)
    documents = {doc["id"]: doc for doc in fixture["documents"]}
    doc_pages = {doc["id"]: {page["page"]: page["text"] for page in doc["pages"]} for doc in fixture["documents"]}

    tp_total = 0
    target_correct_total = 0
    fp_total = 0
    proposed_common_total = 0
    kept_common_total = 0
    single_expected = 0
    single_covered = 0
    batch_expected = 0
    batch_covered = 0
    overall_expected = 0
    overall_covered = 0
    parse_passed = 0
    parse_total = 0
    filter_passed = 0
    filter_total = 0
    pass_checks = 0
    fail_checks = 0
    unknown_checks = 0
    fail_cases = 0
    fail_cases_detected = 0
    boundary_passed = 0
    boundary_total = 0
    reprompt_failures = 0
    reprompt_total = 0
    lock_failures = 0
    lock_total = 0
    entries_failures = 0
    entries_total = 0

    response_details: list[dict[str, Any]] = []
    for response in fixture["model_responses"]:
        doc = documents[response["document_id"]]
        response_detail = _evaluate_response(response, doc, doc_pages[response["document_id"]])
        response_details.append(response_detail)
        tp_total += response_detail["candidate_tp"]
        target_correct_total += response_detail["target_correct"]
        fp_total += response_detail["candidate_fp"]
        proposed_common_total += response_detail["proposed_common"]
        kept_common_total += response_detail["kept_common"]
        if response_detail["scope"] == "single_page":
            single_expected += len(response_detail["expected_terms"])
            single_covered += len(response_detail["covered_terms"])
        else:
            batch_expected += len(response_detail["expected_terms"])
            batch_covered += len(response_detail["covered_terms"])
        overall_expected += len(response_detail["expected_terms"])
        overall_covered += len(response_detail["covered_terms"])
        parse_total += 1
        if response_detail["parse_matched"]:
            parse_passed += 1
        filter_total += response_detail["filter_checks_total"]
        filter_passed += response_detail["filter_checks_passed"]

    boundary_details: list[dict[str, Any]] = []
    for case in fixture.get("boundary_cases", []):
        result = filter_candidates(
            [TermCandidate(case["source"], "中文目标")],
            case["text"],
            [(1, case["text"])],
        )
        item = result[0]
        actual_kept = item.reason is None
        expected_reason = case.get("expected_reason")
        ok = actual_kept == case["expected_kept"] and (expected_reason is None or item.reason == expected_reason)
        boundary_total += 1
        if ok:
            boundary_passed += 1
        boundary_details.append(
            {
                "id": case["id"],
                "source": case["source"],
                "expected_kept": case["expected_kept"],
                "actual_kept": actual_kept,
                "expected_reason": expected_reason,
                "actual_reason": item.reason,
                "passed": ok,
            }
        )

    compliance_details: list[dict[str, Any]] = []
    for case in fixture.get("compliance_cases", []):
        active_terms = [(str(s), str(t)) for s, t in case["active_terms"]]
        verdict = verify_translated_text(case["translated_text"], active_terms)
        checks = [
            {
                "source": check.source,
                "target": check.target,
                "status": check.status.value,
            }
            for check in verdict.checks
        ]
        for check in checks:
            if check["status"] == ComplianceStatus.PASS.value:
                pass_checks += 1
            elif check["status"] == ComplianceStatus.FAIL.value:
                fail_checks += 1
            else:
                unknown_checks += 1
        detected = verdict.status.value == case["expected"]
        if case["expected"] == "fail":
            fail_cases += 1
            if detected:
                fail_cases_detected += 1
        compliance_details.append(
            {
                "id": case["id"],
                "expected": case["expected"],
                "actual": verdict.status.value,
                "detected": detected,
                "checks": checks,
                "reason": verdict.reason,
            }
        )

    store_details: list[dict[str, Any]] = []
    for scenario in fixture.get("store_scenarios", []):
        scenario_dir = work_dir / hashlib.sha256(scenario["id"].encode("utf-8")).hexdigest()
        scenario_dir.mkdir(parents=True, exist_ok=True)
        store = CandidateStore(scenario_dir)
        _record_observations(store, scenario["source"], scenario["observations"])
        scenario_detail: dict[str, Any] = {
            "id": scenario["id"],
            "source": scenario["source"],
        }
        reject_target = scenario.get("reject_target")
        if reject_target is None:
            # wrong-first 主路径：直接对 candidate 状态执行 accept() 无参，验证推荐结果。
            lock_total += 1
            entry, _ = store.accept(scenario["source"])
            scenario_detail["accepted_target"] = entry.accepted_target
            if entry.accepted_target != scenario["expected_recommended_target"]:
                lock_failures += 1
        else:
            # rejected 主路径：不先 accept，直接在 candidate 状态 reject，
            # 再记录 later observations 并检查 suppressed。
            store.reject(scenario["source"], target=reject_target)
            if scenario.get("later_observations"):
                _record_observations(
                    store,
                    scenario["source"],
                    scenario["later_observations"],
                )
            summaries = {summary.source_key: summary for summary in store.candidate_summaries()}
            source_key = normalize_source_key(scenario["source"])
            entry_count = sum(1 for key in summaries if key == source_key)
            entries_total += 1
            if entry_count != scenario["expected_entries_after"]:
                entries_failures += 1
            summary = summaries.get(source_key)
            targets = summary.targets if summary is not None else ()
            rejected_targets = [target for target in targets if target.target == reject_target]
            reprompt_total += 1
            reprompted = not rejected_targets or any(not target.suppressed for target in rejected_targets)
            if reprompted:
                reprompt_failures += 1
            scenario_detail["entries_after_reject"] = entry_count
            scenario_detail["rejected_suppressed"] = not reprompted
        store_details.append(scenario_detail)

    precision = ratio(tp_total, tp_total + fp_total, empty_value=1.0)
    recall = ratio(overall_covered, overall_expected, empty_value=1.0)
    single_recall = ratio(single_covered, single_expected, empty_value=1.0)
    batch_recall = ratio(batch_covered, batch_expected, empty_value=1.0)
    metrics: dict[str, float | bool] = {
        "candidate_precision": round(precision, 6),
        "candidate_target_accuracy": round(
            ratio(target_correct_total, tp_total, empty_value=1.0),
            6,
        ),
        "core_term_recall": round(recall, 6),
        "single_page_recall": round(single_recall, 6),
        "batch_recall": round(batch_recall, 6),
        "batch_minus_single_core_recall_delta": round(batch_recall - single_recall, 6),
        "common_word_contamination_rate": round(
            ratio(kept_common_total, proposed_common_total, empty_value=0.0),
            6,
        ),
        "authoritative_compliance_rate": round(
            ratio(pass_checks, pass_checks + fail_checks, empty_value=1.0),
            6,
        ),
        "compliance_fail_detected_rate": round(
            ratio(fail_cases_detected, fail_cases, empty_value=1.0),
            6,
        ),
        "rejected_candidate_reprompt_rate": round(
            ratio(reprompt_failures, reprompt_total, empty_value=0.0),
            6,
        ),
        "wrong_first_translation_lock_rate": round(
            ratio(lock_failures, lock_total, empty_value=0.0),
            6,
        ),
        "parse_check_pass_rate": round(
            ratio(parse_passed, parse_total, empty_value=1.0),
            6,
        ),
        "filter_check_pass_rate": round(
            ratio(filter_passed, filter_total, empty_value=1.0),
            6,
        ),
        "boundary_check_pass_rate": round(
            ratio(boundary_passed, boundary_total, empty_value=1.0),
            6,
        ),
    }
    detail: dict[str, Any] = {
        "documents": [
            {
                "id": doc["id"],
                "category": doc["category"],
                "pages": [page["page"] for page in doc["pages"]],
                "core_terms": len(doc["golden"]["core_terms"]),
            }
            for doc in fixture["documents"]
        ],
        "responses": response_details,
        "compliance_cases": compliance_details,
        "boundary_cases": boundary_details,
        "store_scenarios": store_details,
        "counts": {
            "true_positives": tp_total,
            "target_correct_tp": target_correct_total,
            "false_positives": fp_total,
            "proposed_common_words": proposed_common_total,
            "kept_common_words": kept_common_total,
            "single_page_expected_terms": single_expected,
            "single_page_covered_terms": single_covered,
            "batch_expected_terms": batch_expected,
            "batch_covered_terms": batch_covered,
            "overall_expected_terms": overall_expected,
            "overall_covered_terms": overall_covered,
            "pass_checks": pass_checks,
            "fail_checks": fail_checks,
            "unknown_checks": unknown_checks,
            "compliance_fail_cases": fail_cases,
            "compliance_fail_cases_detected": fail_cases_detected,
            "rejected_scenarios": reprompt_total,
            "reprompt_failures": reprompt_failures,
            "wrong_first_scenarios": lock_total,
            "wrong_first_failures": lock_failures,
            "entries_total": entries_total,
            "entries_failures": entries_failures,
        },
    }
    return _RunResult(metrics=metrics, detail=detail)


def _evaluate_response(
    response: dict[str, Any],
    doc: dict[str, Any],
    page_texts: dict[int, str],
) -> dict[str, Any]:
    raw = json.dumps(response["raw"], ensure_ascii=False).encode("utf-8")
    try:
        parsed = parse_model_response(raw)
        parse_ok = True
        parse_error: str | None = None
    except Exception as exc:
        parsed = []
        parse_ok = False
        parse_error = type(exc).__name__
    expected = [tuple(pair) for pair in response.get("expected_parsed_terms", [])]
    parse_matched = parse_ok and [(item.source, item.target) for item in parsed] == expected

    pages = sorted(int(page) for page in response["pages"])
    sent_text = "\n".join(page_texts[page] for page in pages)
    chunks = [(page, page_texts[page]) for page in pages]
    filtered = filter_candidates(parsed, sent_text, chunks)
    kept = [item for item in filtered if item.reason is None]
    rejected = [item for item in filtered if item.reason is not None]

    core_terms = doc["golden"]["core_terms"]
    all_golden_forms = {normalize_source_key(form) for term in core_terms for form in term["forms"]}
    term_by_form: dict[str, dict[str, Any]] = {}
    for term in core_terms:
        for form in term["forms"]:
            term_by_form.setdefault(normalize_source_key(form), term)
    common_words = {normalize_source_key(word) for word in doc["golden"].get("common_words", [])}
    candidate_tp = 0
    target_correct = 0
    for item in kept:
        form_key = normalize_source_key(item.source)
        if form_key not in all_golden_forms:
            continue
        candidate_tp += 1
        if item.target == term_by_form[form_key]["expected_target"]:
            target_correct += 1
    candidate_fp = len(kept) - candidate_tp
    proposed_common = sum(1 for item in parsed if normalize_source_key(item.source) in common_words)
    kept_common = sum(1 for item in kept if normalize_source_key(item.source) in common_words)

    expected_terms: list[str] = []
    covered_terms: list[str] = []
    for index, term in enumerate(core_terms):
        if not set(term["pages"]) & set(pages):
            continue
        expected_terms.append(str(index))
        term_forms = {normalize_source_key(form) for form in term["forms"]}
        if any(normalize_source_key(candidate.source) in term_forms for candidate in kept):
            covered_terms.append(str(index))

    filter_checks_total = len(response.get("expected_filter", {}))
    filter_checks_passed = 0
    for source, expected_filter in response.get("expected_filter", {}).items():
        wanted = normalize_source_key(source)
        matched_item = next(
            (candidate for candidate in filtered if normalize_source_key(candidate.source) == wanted),
            None,
        )
        actual_kept = matched_item is not None and matched_item.reason is None
        actual_reason = matched_item.reason if matched_item is not None else "no_candidate"
        expected_reason = expected_filter.get("reason")
        ok = actual_kept == expected_filter["kept"] and (expected_reason is None or actual_reason == expected_reason)
        if ok:
            filter_checks_passed += 1

    return {
        "id": response["id"],
        "document_id": response["document_id"],
        "scope": response["scope"],
        "pages": pages,
        "parse_ok": parse_ok,
        "parse_error": parse_error,
        "parse_matched": parse_matched,
        "parsed_terms": [[item.source, item.target] for item in parsed],
        "kept": [[item.source, item.target] for item in kept],
        "rejected": [
            {
                "source": item.source,
                "target": item.target,
                "reason": item.reason,
            }
            for item in rejected
        ],
        "candidate_tp": candidate_tp,
        "target_correct": target_correct,
        "candidate_fp": candidate_fp,
        "proposed_common": proposed_common,
        "kept_common": kept_common,
        "expected_terms": expected_terms,
        "covered_terms": covered_terms,
        "filter_checks_passed": filter_checks_passed,
        "filter_checks_total": filter_checks_total,
    }


def _record_observations(
    store: CandidateStore,
    source: str,
    observations: list[dict[str, Any]],
) -> None:
    prepared: list[CandidateObservation] = []
    for item in observations:
        pages = tuple(int(page) for page in item["pages"])
        for _ in range(int(item["count"])):
            prepared.append(
                CandidateObservation(
                    source=source,
                    target=str(item["target"]),
                    pages=pages,
                )
            )
    store.record_observations(prepared, strategy_version="quality-eval/1")


def check_thresholds(
    metrics: dict[str, float | bool],
    thresholds: dict[str, float | bool] | None = None,
) -> tuple[bool, tuple[str, ...]]:
    """按明确方向和阈值检查指标；失败门槛返回非零信息供调用方退出。"""
    effective = dict(QUALITY_THRESHOLDS if thresholds is None else thresholds)
    failures: list[str] = []
    for key, threshold in effective.items():
        if key not in metrics:
            failures.append(f"missing metric {key}")
            continue
        value = metrics[key]
        if isinstance(threshold, bool):
            if not isinstance(value, bool):
                failures.append(f"{key}: type mismatch, expected bool got {value!r}")
            elif value is not threshold:
                failures.append(f"{key}: expected {threshold}, got {value!r}")
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            failures.append(f"{key}: non-numeric value {value!r}")
            continue
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
            failures.append(f"{key}: non-numeric threshold {threshold!r}")
            continue
        numeric = float(value)
        limit = float(threshold)
        if not math.isfinite(numeric):
            failures.append(f"{key}: non-finite value {value!r}")
            continue
        if not math.isfinite(limit):
            failures.append(f"{key}: non-finite threshold {threshold!r}")
            continue
        if key in LOWER_IS_BETTER_METRICS:
            if numeric > limit + 1e-9:
                failures.append(f"{key}: {numeric:.6f} > {limit:.6f}")
        elif numeric < limit - 1e-9:
            failures.append(f"{key}: {numeric:.6f} < {limit:.6f}")
    return (not failures), tuple(failures)


def compare_baseline(
    current: dict[str, float | bool],
    baseline: dict[str, float | bool],
    *,
    tolerance: float = DRIFT_TOLERANCE,
) -> tuple[dict[str, float | bool], tuple[str, ...]]:
    """当前报告与版本化基线对比；返回 delta 与漂移失败列表。"""
    if (
        isinstance(tolerance, bool)
        or not isinstance(tolerance, (int, float))
        or not math.isfinite(float(tolerance))
        or tolerance < 0
    ):
        raise TermQualityError("tolerance must be finite and >= 0")
    deltas: dict[str, float | bool] = {}
    failures: list[str] = []
    for key, base in baseline.items():
        if key not in current:
            failures.append(f"baseline metric missing in current: {key}")
            continue
        value = current[key]
        base_bool = isinstance(base, bool)
        value_bool = isinstance(value, bool)
        if base_bool or value_bool:
            if base_bool and value_bool:
                if value != base:
                    failures.append(f"{key}: baseline {base!r} != current {value!r}")
                deltas[key] = value
            else:
                failures.append(f"{key}: type mismatch (bool vs numeric)")
            continue
        if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            failures.append(f"{key}: non-finite current value {value!r}")
            continue
        if not isinstance(base, (int, float)) or not math.isfinite(float(base)):
            failures.append(f"{key}: non-finite baseline value {base!r}")
            continue
        delta = float(value) - float(base)
        deltas[key] = delta
        if key in LOWER_IS_BETTER_METRICS:
            if delta > tolerance + 1e-9:
                failures.append(f"{key}: drift +{delta:.6f} > tolerance {tolerance:.6f}")
        elif delta < -tolerance - 1e-9:
            failures.append(f"{key}: drift {delta:.6f} < -tolerance {tolerance:.6f}")
    for key in current:
        if key not in baseline:
            failures.append(f"new metric not in baseline: {key}")
    return deltas, tuple(failures)


def _validate_baseline_metrics(metrics: Any, *, label: str) -> None:
    """基线 metrics/thresholds fail-closed：键集合、值类型与有限性必须匹配当前门槛。"""
    if not isinstance(metrics, dict):
        raise TermQualityError(f"invalid baseline {label}: not an object")
    expected = set(QUALITY_THRESHOLDS)
    actual = set(metrics)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing or extra:
        raise TermQualityError(f"invalid baseline {label} key set: missing={missing} extra={extra}")
    for key in expected:
        value = metrics[key]
        threshold = QUALITY_THRESHOLDS[key]
        if isinstance(threshold, bool):
            if not isinstance(value, bool):
                raise TermQualityError(f"invalid baseline {label} {key}: expected bool, got {value!r}")
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise TermQualityError(f"invalid baseline {label} {key}: expected finite number, got {value!r}")


def load_baseline(path: str | Path) -> dict[str, Any]:
    """加载版本化基线报告；schema、键集合、类型、有限性与元数据不匹配时 fail-closed。"""
    baseline_path = Path(path)
    try:
        data = json.loads(baseline_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise TermQualityError(f"failed to load baseline {baseline_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise TermQualityError(f"invalid baseline payload in {baseline_path}")
    if data.get("schema_version") != QUALITY_SCHEMA_VERSION:
        raise TermQualityError(f"unsupported baseline schema version in {baseline_path}")
    if data.get("metric_definitions_version") != METRIC_DEFINITIONS_VERSION:
        raise TermQualityError(f"unsupported metric_definitions_version in baseline {baseline_path}")
    _validate_baseline_metrics(data.get("metrics"), label="metrics")
    thresholds = data.get("thresholds")
    _validate_baseline_metrics(thresholds, label="thresholds")
    assert isinstance(thresholds, dict)
    for key, threshold in QUALITY_THRESHOLDS.items():
        if thresholds[key] != threshold:
            raise TermQualityError(f"baseline threshold mismatch for {key}: {thresholds[key]!r} != {threshold!r}")
    fixture = data.get("fixture")
    if not isinstance(fixture, str) or not fixture.strip():
        raise TermQualityError(f"invalid baseline fixture in {baseline_path}")
    source = data.get("source")
    if not isinstance(source, str) or not source.strip():
        raise TermQualityError(f"invalid baseline source in {baseline_path}")
    fixture_sha256 = data.get("fixture_sha256")
    if not isinstance(fixture_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", fixture_sha256) is None:
        raise TermQualityError(f"invalid baseline fixture_sha256 in {baseline_path}")
    return data


def write_baseline(report: QualityReport, path: str | Path) -> None:
    """原子写入版本化基线报告（同目录临时文件 + ``os.replace``）。"""
    target = Path(path)
    payload = {
        "schema_version": QUALITY_SCHEMA_VERSION,
        "metric_definitions_version": METRIC_DEFINITIONS_VERSION,
        "fixture": report.fixture,
        "fixture_sha256": report.fixture_sha256,
        "metrics": dict(report.metrics),
        "thresholds": dict(report.thresholds),
        "source": "scripts/term_quality_gate.py --update-baseline",
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
