"""P2-02 术语诊断、统计与可解释性：不变量与故障隔离测试。"""

from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock, patch

import pytest

from pdf_reader.candidate_service import CandidateExtractionReport
from pdf_reader.task_logging import (
    TaskContext,
    task_context_from_indices,
    task_log,
    truncate_glossary_revision,
)
from pdf_reader.term_diagnostics import (
    CandidateStoreCounts,
    candidate_failed_count,
    format_candidate_summary,
    format_usage,
    log_candidate_summary,
    log_compliance,
)
from pdf_reader.term_extraction import (
    TermCandidate,
    TermExtractionClient,
    TokenUsage,
    parse_model_response_with_usage,
)


class _SpyResponse:
    """可注入 urlopen 的受控响应。"""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self._offset = 0
        self.closed = False
        self.headers = {"Content-Length": str(len(payload))}

    def read(self, size: int = -1) -> bytes:
        if self.closed:
            raise ValueError("read after close")
        if size is None or size < 0:
            size = len(self._payload) - self._offset
        chunk = self._payload[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk

    def close(self) -> None:
        self.closed = True


def _model() -> object:
    from pdf_reader.config import ModelRuntimeConfig

    return ModelRuntimeConfig(
        provider="openai_compatible",
        api_key="sk-diagnostics-test",
        model="test-model",
        base_url="http://127.0.0.1:1/v1",
    )


def _cfg() -> object:
    from pdf_reader.config import CandidateExtractionRuntimeConfig

    return CandidateExtractionRuntimeConfig(
        enabled=True,
        timeout=30.0,
        qps=100,
        max_workers=1,
        retry_count=0,
        max_input_chars=80_000,
        prompt=None,
    )


def _client(payload: bytes) -> TermExtractionClient:
    return TermExtractionClient(
        _model(),  # type: ignore[arg-type]
        _cfg(),  # type: ignore[arg-type]
        urlopen=lambda request, timeout: _SpyResponse(payload),
        sleep=lambda _seconds: None,
    )


def _payload(terms: list[dict[str, str]], usage: dict[str, int] | None = None) -> bytes:
    content = json.dumps({"terms": terms}, ensure_ascii=False)
    data: dict[str, object] = {"choices": [{"message": {"content": content}}]}
    if usage is not None:
        data["usage"] = usage
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


def test_parse_model_response_with_usage_full():
    raw = _payload(
        [{"source": "AD", "target": "阿尔茨海默病"}],
        {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    )
    result = parse_model_response_with_usage(raw)

    assert result.terms == [TermCandidate(source="AD", target="阿尔茨海默病")]
    assert result.usage == TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    assert result.usage is not None
    assert result.usage.available is True


@pytest.mark.parametrize(
    "usage",
    [
        None,
        {},
        {"prompt_tokens": -1, "completion_tokens": 5, "total_tokens": 15},
        {"prompt_tokens": "10", "completion_tokens": 5, "total_tokens": 15},
        {"prompt_tokens": True, "completion_tokens": 5, "total_tokens": 15},
        {"prompt_tokens": 1.5, "completion_tokens": 5, "total_tokens": 15},
        {"unexpected": 1},
    ],
)
def test_parse_model_response_usage_missing_or_invalid_is_unavailable(usage):
    raw = _payload([{"source": "AD", "target": "阿尔茨海默病"}], usage=usage)  # type: ignore[arg-type]
    result = parse_model_response_with_usage(raw)

    assert result.terms == [TermCandidate(source="AD", target="阿尔茨海默病")]
    assert result.usage is None


def test_extract_terms_with_usage_returns_result_and_extract_terms_stays_compatible():
    raw = _payload(
        [{"source": "AD", "target": "阿尔茨海默病"}],
        {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
    )
    client = _client(raw)

    result = client.extract_terms_with_usage("AD text")
    assert result.terms == [TermCandidate(source="AD", target="阿尔茨海默病")]
    assert result.usage == TokenUsage(prompt_tokens=7, completion_tokens=3, total_tokens=10)

    assert client.extract_terms("AD text") == [TermCandidate(source="AD", target="阿尔茨海默病")]


def test_truncate_glossary_revision_lengths():
    assert truncate_glossary_revision("a" * 64) == "a" * 12
    assert truncate_glossary_revision("") == "-"


def test_task_context_revision_truncated_and_in_prefix(caplog):
    task = TaskContext(
        job_id="job-rev",
        document_id="doc",
        pdf_hash="hash",
        page=2,
        glossary_revision="f" * 64,
        status="started",
    )
    assert task.glossary_revision == "f" * 12

    with caplog.at_level(logging.INFO, logger="pdf_reader.translate"):
        task_log(logging.getLogger("pdf_reader.translate"), logging.INFO, "rev check", task=task)
    msg = caplog.records[0].message
    assert f"rev={'f' * 12}" in msg
    assert "f" * 13 not in msg


def test_task_context_from_indices_passes_revision():
    task = task_context_from_indices(
        "j",
        "doc",
        "hash",
        [3, 4],
        glossary_revision="b" * 64,
    )
    assert task.from_page == 4
    assert task.to_page == 5
    assert task.glossary_revision == "b" * 12


def test_task_log_prefix_omits_empty_revision(caplog):
    task = TaskContext(job_id="j", document_id="d", pdf_hash="h", page=1)
    assert task.glossary_revision == "-"
    with caplog.at_level(logging.INFO, logger="pdf_reader.translate"):
        task_log(logging.getLogger("pdf_reader.translate"), logging.INFO, "no rev", task=task)
    assert "rev=" not in caplog.records[0].message


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("ok", 0),
        ("no_candidates", 0),
        ("all_filtered", 0),
        ("empty", 0),
        ("disabled", 0),
        ("unsupported", 0),
        ("identity_rejected", 0),
        ("failed", 1),
        ("source_failed", 1),
        ("store_failed", 1),
    ],
)
def test_candidate_failed_count_definitions(status, expected):
    assert candidate_failed_count(CandidateExtractionReport(status=status)) == expected


def test_format_candidate_summary_safe_and_deterministic():
    report = CandidateExtractionReport(
        status="ok",
        candidates=2,
        proposed=4,
        pages=(1, 3),
        filtered=2,
        filtered_by_reason=(("common_word", 1), ("no_source_match", 1)),
        job_id="job",
        document_id="doc",
        pdf_hash="hash",
        elapsed_ms=42,
        usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )
    summary = format_candidate_summary(report)

    assert "status=ok" in summary
    assert "proposed=4" in summary
    assert "kept=2" in summary
    assert "filtered=2" in summary
    assert "failed=0" in summary
    assert "pages=(1, 3)" in summary
    assert "reasons=common_word:1;no_source_match:1" in summary
    assert "elapsed_ms=42" in summary
    assert "usage=prompt=10 completion=5 total=15" in summary
    assert summary == format_candidate_summary(report)

    # 稳定摘要绝不携带 source/target/evidence/job 原文
    for secret in ("job", "doc", "hash", "阿尔茨海默病", "AD"):
        assert secret not in summary


def test_prepare_summary_uses_batch_semantics_not_user_states():
    report = CandidateExtractionReport(
        status="ok",
        candidates=2,
        proposed=4,
        pages=(1,),
        filtered=2,
        filtered_by_reason=(("common_word", 1), ("no_source_match", 1)),
    )
    summary = format_candidate_summary(report)

    assert "proposed=4" in summary
    assert "kept=2" in summary
    assert "filtered=2" in summary
    # prepare 批次不得把 kept 称为 accepted，也不得把 filtered 称为 rejected
    assert "accepted=" not in summary
    assert "rejected=" not in summary
    assert "pending=" not in summary


def test_commit_summary_uses_real_store_state_counts():
    report = CandidateExtractionReport(status="ok", candidates=1, proposed=1, pages=(1,))
    store_counts = CandidateStoreCounts(pending=2, accepted=1, rejected=3)

    summary = format_candidate_summary(report, event="candidate_commit", store_counts=store_counts)

    assert "event=candidate_commit" in summary
    assert "kept=1" in summary
    assert "pending=2" in summary
    assert "accepted=1" in summary
    assert "rejected=3" in summary
    for secret in ("AD", "TCS", "阿尔茨海默病", "外用糖皮质激素"):
        assert secret not in summary


def test_commit_summary_store_stats_failure_is_explicit_unavailable():
    report = CandidateExtractionReport(status="ok", candidates=1, proposed=1, pages=(1,))
    summary = format_candidate_summary(report, event="candidate_commit", store_counts=None)
    assert "pending=unavailable" in summary
    assert "accepted=unavailable" in summary
    assert "rejected=unavailable" in summary


def test_format_candidate_summary_handles_magicmock_defaults():
    report = MagicMock(status="failed")
    summary = format_candidate_summary(report)
    assert "status=failed" in summary
    assert "proposed=0" in summary
    assert "kept=0" in summary
    assert "usage=unavailable" in summary
    assert "pending=" not in summary
    assert "accepted=" not in summary

    commit_summary = format_candidate_summary(report, event="candidate_commit")
    assert "pending=unavailable" in commit_summary
    assert "accepted=unavailable" in commit_summary
    assert "rejected=unavailable" in commit_summary


def test_format_candidate_summary_sanitizes_unknown_tokens():
    report = CandidateExtractionReport(
        status="SECRET\nsource",
        candidates=1,
        proposed=1,
        filtered_by_reason=(("common_word", 1), ("SECRET target sk-key", 5)),
        pages=(1,),
    )
    summary = format_candidate_summary(report)

    assert "status=unknown" in summary
    assert "reasons=common_word:1;unknown:5" in summary
    for secret in ("SECRET", "target", "sk-key", "\n"):
        assert secret not in summary


def test_log_compliance_sanitizes_unknown_status_event_and_reason(caplog):
    logger = logging.getLogger("pdf_reader.translate")
    with caplog.at_level(logging.WARNING, logger="pdf_reader.translate"):
        log_compliance(
            logger,
            logging.WARNING,
            event="compliance_SECRET\nsk-key",
            attempt=1,
            status="SECRET\nsk-key",
            sources=1,
            failed=1,
            reason="prompt: sk-key-abc\n",
        )

    text = caplog.text
    assert "event=unknown" in text
    assert "status=unknown" in text
    assert "reason=unknown" in text
    records = [record for record in caplog.records if record.name == "pdf_reader.translate"]
    assert len(records) == 1
    assert "\n" not in records[0].message
    for secret in ("SECRET", "sk-key", "prompt"):
        assert secret not in text


def test_log_compliance_event_none_never_formats_unknown_status(caplog):
    class EvilStatus:
        calls: list[str] = []

        def __str__(self) -> str:
            type(self).calls.append("str")
            return "SECRET-STR"

        def __format__(self, spec: str) -> str:
            type(self).calls.append("format")
            return "SECRET-FORMAT"

    EvilStatus.calls = []
    evil = EvilStatus()
    logger = logging.getLogger("pdf_reader.translate")
    with caplog.at_level(logging.WARNING, logger="pdf_reader.translate"):
        log_compliance(
            logger,
            logging.WARNING,
            event=None,
            attempt=1,
            status=evil,
            sources=1,
            failed=1,
            reason="",
        )

    assert EvilStatus.calls == []
    text = caplog.text
    assert "event=unknown" in text
    assert "status=unknown" in text
    assert "SECRET" not in text


def test_log_compliance_never_calls_bool_or_str_on_unknown_reason(caplog):
    class EvilReason:
        calls: list[str] = []

        def __bool__(self) -> bool:
            type(self).calls.append("bool")
            return True

        def __str__(self) -> str:
            type(self).calls.append("str")
            return "SECRET-REASON"

        def __format__(self, spec: str) -> str:
            type(self).calls.append("format")
            return "SECRET-REASON-FORMAT"

    EvilReason.calls = []
    evil = EvilReason()
    logger = logging.getLogger("pdf_reader.translate")
    with caplog.at_level(logging.WARNING, logger="pdf_reader.translate"):
        log_compliance(
            logger,
            logging.WARNING,
            event="compliance_fail",
            attempt=1,
            status="fail",
            sources=1,
            failed=1,
            reason=evil,
        )

    assert EvilReason.calls == []
    text = caplog.text
    assert "reason=unknown" in text
    assert "SECRET" not in text


def test_format_usage_available_and_unavailable():
    assert format_usage(TokenUsage(prompt_tokens=1, completion_tokens=2, total_tokens=3)) == (
        "prompt=1 completion=2 total=3"
    )
    assert format_usage(None) == "unavailable"


@pytest.mark.parametrize(
    "usage",
    [
        TokenUsage(prompt_tokens=1, completion_tokens=None, total_tokens=5),
        TokenUsage(prompt_tokens=True, completion_tokens=2, total_tokens=3),
        TokenUsage(prompt_tokens=-1, completion_tokens=2, total_tokens=3),
    ],
)
def test_format_usage_partial_or_invalid_is_unavailable(usage):
    assert format_usage(usage) == "unavailable"


def test_log_candidate_summary_format_failure_is_contained(caplog):
    report = CandidateExtractionReport(status="ok", candidates=1)
    with patch("pdf_reader.term_diagnostics.format_candidate_summary", side_effect=RuntimeError("fmt boom")):
        with caplog.at_level(logging.WARNING, logger="pdf_reader.candidate"):
            log_candidate_summary(logging.getLogger("pdf_reader.candidate"), logging.INFO, report)

    assert "candidate diagnostics unavailable" in caplog.text
    assert "fmt boom" not in caplog.text


def test_log_candidate_summary_emission_failure_is_contained(caplog):
    report = CandidateExtractionReport(status="ok", candidates=1)
    with patch("pdf_reader.term_diagnostics.safe_task_log", side_effect=RuntimeError("emit boom")):
        with caplog.at_level(logging.WARNING, logger="pdf_reader.candidate"):
            log_candidate_summary(logging.getLogger("pdf_reader.candidate"), logging.INFO, report)

    assert "candidate diagnostics unavailable" in caplog.text
    assert "emit boom" not in caplog.text
