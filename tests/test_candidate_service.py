"""P1-01 候选提取服务：fake local HTTP server + 真实 CandidateStore 边界。"""

from __future__ import annotations

import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Never
from unittest.mock import MagicMock

import pymupdf
import pytest

from pdf_reader.candidate_filter import CANDIDATE_STRATEGY_VERSION
from pdf_reader.candidate_service import (
    CandidateExtractionReport,
    CandidateExtractionService,
    CandidateIdentity,
    CandidateTermService,
)
from pdf_reader.candidate_store import CandidateStore
from pdf_reader.config import CandidateExtractionRuntimeConfig, ModelRuntimeConfig
from pdf_reader.term_diagnostics import candidate_failed_count
from pdf_reader.term_model import TermStoreError


class _FakeHandler(BaseHTTPRequestHandler):
    responses: list[tuple[int, bytes, dict[str, str]]] = []
    requests: list[tuple[str, bytes, dict[str, str]]] = []
    sleep_seconds: float = 0.0

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        type(self).requests.append((self.path, body, dict(self.headers)))
        if self.sleep_seconds:
            time.sleep(self.sleep_seconds)
        status, payload, extra_headers = type(self).responses.pop(0)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        for key, value in extra_headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        try:
            self.wfile.write(payload)
        except OSError:
            return

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return


@pytest.fixture
def fake_server():
    _FakeHandler.responses = []
    _FakeHandler.requests = []
    _FakeHandler.sleep_seconds = 0.0
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeHandler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _doc_dir(tmp_path: Path) -> Path:
    directory = tmp_path / ("c" * 64)
    directory.mkdir()
    return directory


def _hex_doc_dir(tmp_path: Path, hex_name: str) -> Path:
    assert len(hex_name) == 64
    assert all(ch in "0123456789abcdef" for ch in hex_name)
    directory = tmp_path / hex_name
    directory.mkdir()
    return directory


def _pdf(tmp_path: Path, texts: list[str], name: str = "source.pdf") -> Path:
    pdf_path = tmp_path / name
    doc = pymupdf.open()
    for text in texts:
        page = doc.new_page()
        page.insert_text((72, 72), text, fontname="helv")
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def _model(
    provider: str = "openai_compatible",
    *,
    base_url: str | None = None,
    api_key: str = "sk-service-test",
) -> ModelRuntimeConfig:
    return ModelRuntimeConfig(provider=provider, api_key=api_key, model="test-model", base_url=base_url)


def _cfg(**overrides: object) -> CandidateExtractionRuntimeConfig:
    values: dict[str, object] = {
        "enabled": True,
        "timeout": 30.0,
        "qps": 100,
        "max_workers": 1,
        "retry_count": 1,
        "max_input_chars": 80_000,
        "prompt": None,
    }
    values.update(overrides)
    return CandidateExtractionRuntimeConfig(**values)  # type: ignore[arg-type]


def _ok(
    terms: list[dict[str, str]],
    usage: dict[str, int] | None = None,
) -> tuple[int, bytes, dict[str, str]]:
    content = json.dumps({"terms": terms}, ensure_ascii=False)
    data: dict[str, object] = {"choices": [{"message": {"content": content}}]}
    if usage is not None:
        data["usage"] = usage
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    return 200, payload, {}


def _service(fake_server: str, **overrides: object) -> CandidateExtractionService:
    return CandidateExtractionService(_cfg(**overrides), _model(base_url=fake_server))


def _run(
    service: CandidateExtractionService,
    pdf: Path,
    page_indices: list[int] | tuple[int, ...],
    document_dir: Path,
    *,
    identity: CandidateIdentity | None = None,
    active_job_provider=None,
) -> CandidateExtractionReport:
    """测试便捷入口：显式执行 prepare 阶段后执行 commit 阶段。"""
    prepared = service.prepare(
        pdf,
        page_indices,
        document_dir,
        identity=identity,
        active_job_provider=active_job_provider,
    )
    return service.commit(
        prepared,
        document_dir,
        identity=identity,
        active_job_provider=active_job_provider,
    )


def test_success_writes_candidates_with_pages_and_strategy(tmp_path, fake_server):
    pdf = _pdf(tmp_path, ["AD is a common term.", "TCS is another term."])
    _FakeHandler.responses.append(
        _ok([{"source": "AD", "target": "阿尔茨海默病"}, {"source": "TCS", "target": "外用糖皮质激素"}])
    )
    document_dir = _doc_dir(tmp_path)
    service = _service(fake_server)

    report = _run(service, pdf, [0, 1], document_dir)

    assert report.status == "ok"
    assert report.candidates == 2
    assert report.pages == (1, 2)
    assert report.filtered == 0
    entries, revision, _ = CandidateStore(document_dir).load()
    assert revision == 1
    by_source = {entry.source_key: entry for entry in entries}
    assert by_source["ad"].targets[0].pages == (1,)
    assert by_source["ad"].targets[0].evidence == ("AD is a common term.",)
    assert by_source["ad"].strategy_version == CANDIDATE_STRATEGY_VERSION
    assert by_source["tcs"].targets[0].target == "外用糖皮质激素"
    assert by_source["tcs"].targets[0].pages == (2,)
    assert by_source["tcs"].targets[0].evidence == ("TCS is another term.",)


def test_success_report_includes_proposed_elapsed_and_usage(tmp_path, fake_server):
    pdf = _pdf(tmp_path, ["AD is a common term.", "TCS is another term."])
    _FakeHandler.responses.append(
        _ok(
            [{"source": "AD", "target": "阿尔茨海默病"}, {"source": "TCS", "target": "外用糖皮质激素"}],
            usage={"prompt_tokens": 20, "completion_tokens": 8, "total_tokens": 28},
        )
    )
    document_dir = _doc_dir(tmp_path)
    service = _service(fake_server)

    report = _run(service, pdf, [0, 1], document_dir)

    assert report.status == "ok"
    assert report.proposed == 2
    assert report.candidates == 2
    assert report.filtered == 0
    assert report.elapsed_ms >= 0
    assert report.usage is not None
    assert report.usage.prompt_tokens == 20
    assert report.usage.completion_tokens == 8
    assert report.usage.total_tokens == 28
    assert candidate_failed_count(report) == 0


def test_missing_usage_reports_unavailable_in_log(tmp_path, fake_server, managed_caplog):
    pdf = _pdf(tmp_path, ["AD is a common term."])
    _FakeHandler.responses.append(_ok([{"source": "AD", "target": "阿尔茨海默病"}]))
    document_dir = _doc_dir(tmp_path)
    service = _service(fake_server)

    with managed_caplog.at_level(logging.INFO, logger="pdf_reader.candidate"):
        report = _run(service, pdf, [0], document_dir)

    assert report.status == "ok"
    assert report.usage is None
    assert "usage=unavailable" in managed_caplog.text
    assert "candidate summary" in managed_caplog.text


def test_proposed_counts_model_output_before_filter(tmp_path, fake_server):
    pdf = _pdf(tmp_path, ["AD appears in the guideline."])
    _FakeHandler.responses.append(
        _ok(
            [
                {"source": "AD", "target": "阿尔茨海默病"},
                {"source": "benefits", "target": "获益"},
                {"source": "nonexistentterm", "target": "不存在的术语"},
            ]
        )
    )
    document_dir = _doc_dir(tmp_path)
    service = _service(fake_server)

    report = _run(service, pdf, [0], document_dir)

    assert report.status == "ok"
    assert report.proposed == 3
    assert report.candidates == 1
    assert report.filtered == 2
    assert candidate_failed_count(report) == 0


def test_failed_report_carries_elapsed_and_failed_count(tmp_path, fake_server):
    pdf = _pdf(tmp_path, ["AD text"])
    document_dir = _doc_dir(tmp_path)
    _FakeHandler.responses.append((503, b"", {}))
    _FakeHandler.responses.append((503, b"", {}))
    service = _service(fake_server)

    report = _run(service, pdf, [0], document_dir)

    assert report.status == "failed"
    assert candidate_failed_count(report) == 1
    assert report.elapsed_ms >= 0
    assert report.proposed == 0
    assert report.candidates == 0
    assert report.usage is None


def test_nonzero_single_page_maps_local_pdf_to_original_page(tmp_path, fake_server):
    # 原文第 10 页（0-based 9）抽取成 1 页局部 PDF：必须按 local_idx=0 读取，
    # 证据页记录为 10，不能 doc[9] 越界。
    pdf = _pdf(tmp_path, ["AD appears on original page ten."])
    _FakeHandler.responses.append(_ok([{"source": "AD", "target": "阿尔茨海默病"}]))
    document_dir = _doc_dir(tmp_path)
    service = _service(fake_server)

    report = _run(service, pdf, [9], document_dir)

    assert report.status == "ok"
    assert report.pages == (10,)
    entries, _, _ = CandidateStore(document_dir).load()
    assert entries[0].targets[0].pages == (10,)


def test_nonzero_batch_maps_local_indices_to_original_pages(tmp_path, fake_server):
    # 原文页 3、6（0-based 2、5）抽取成 2 页局部 PDF：按 local_idx 0/1 读取，
    # 证据页记录为 3、6。
    pdf = _pdf(tmp_path, ["AD on original page three.", "TCS on original page six."])
    _FakeHandler.responses.append(
        _ok([{"source": "AD", "target": "阿尔茨海默病"}, {"source": "TCS", "target": "外用糖皮质激素"}])
    )
    document_dir = _doc_dir(tmp_path)
    service = _service(fake_server)

    report = _run(service, pdf, [2, 5], document_dir)

    assert report.status == "ok"
    assert report.pages == (3, 6)
    entries, _, _ = CandidateStore(document_dir).load()
    by_source = {entry.source_key: entry for entry in entries}
    assert by_source["ad"].targets[0].pages == (3,)
    assert by_source["ad"].targets[0].evidence == ("AD on original page three.",)
    assert by_source["tcs"].targets[0].pages == (6,)
    assert by_source["tcs"].targets[0].evidence == ("TCS on original page six.",)


def test_hallucinated_candidate_filtered_and_not_written(tmp_path, fake_server):
    pdf = _pdf(tmp_path, ["AD appears in the guideline."])
    _FakeHandler.responses.append(
        _ok(
            [
                {"source": "AD", "target": "阿尔茨海默病"},
                {"source": "nonexistentterm", "target": "不存在的术语"},
            ]
        )
    )
    document_dir = _doc_dir(tmp_path)
    service = _service(fake_server)

    report = _run(service, pdf, [0], document_dir)

    assert report.status == "ok"
    assert report.candidates == 1
    assert report.filtered == 1
    assert ("no_source_match", 1) in report.filtered_by_reason
    entries, revision, _ = CandidateStore(document_dir).load()
    assert revision == 1
    assert len(entries) == 1
    assert entries[0].source == "AD"


def test_common_word_all_filtered_writes_no_empty_revision(tmp_path, fake_server):
    pdf = _pdf(tmp_path, ["Benefits are important for patients."])
    document_dir = _doc_dir(tmp_path)
    store = CandidateStore(document_dir)
    store.record_observation("TCS", "外用糖皮质激素")
    old_bytes = store.path.read_bytes()
    _FakeHandler.responses.append(_ok([{"source": "benefits", "target": "获益"}]))
    service = _service(fake_server)

    report = _run(service, pdf, [0], document_dir)

    assert report.status == "all_filtered"
    assert report.candidates == 0
    assert report.filtered == 1
    assert ("common_word", 1) in report.filtered_by_reason
    entries, revision, _ = store.load()
    assert revision == 1
    assert len(entries) == 1
    assert store.path.read_bytes() == old_bytes


def test_rejected_source_target_auto_observation_keeps_user_state(tmp_path, fake_server):
    pdf = _pdf(tmp_path, ["AD appears in the guideline."])
    document_dir = _doc_dir(tmp_path)
    store = CandidateStore(document_dir)
    store.record_observation("AD", "自动建议")
    store.reject("AD", target="自动建议")
    _FakeHandler.responses.append(_ok([{"source": "AD", "target": "自动建议"}]))
    service = _service(fake_server)

    report = _run(service, pdf, [0], document_dir)

    assert report.status == "ok"
    assert report.candidates == 1
    entries, revision, _ = store.load()
    assert revision == 3
    assert len(entries) == 1
    entry = entries[0]
    assert entry.status == "rejected"
    assert entry.rejected_targets == ["自动建议"]
    suggestion = entry.targets[0]
    assert suggestion.observations == 2
    assert suggestion.pages == (1,)
    assert suggestion.evidence


def test_local_pdf_page_count_mismatch_degrades_without_store(tmp_path, fake_server):
    pdf = _pdf(tmp_path, ["only one local page"])
    _FakeHandler.responses.append(_ok([{"source": "AD", "target": "阿尔茨海默病"}]))
    document_dir = _doc_dir(tmp_path)
    service = _service(fake_server)

    report = _run(service, pdf, [0, 1], document_dir)

    assert report.status == "source_failed"
    assert _FakeHandler.requests == []
    assert not (document_dir / "term_candidates.json").exists()


def test_accepted_and_rejected_statuses_never_overwritten(tmp_path, fake_server):
    pdf = _pdf(tmp_path, ["AD accepted term.", "TCS rejected term."])
    document_dir = _doc_dir(tmp_path)
    store = CandidateStore(document_dir)
    store.record_observation("AD", "自动建议")
    store.accept("AD", target="用户确认")
    store.record_observation("TCS", "旧译法")
    store.reject("TCS", target="旧译法")

    _FakeHandler.responses.append(_ok([{"source": "AD", "target": "新建议"}, {"source": "TCS", "target": "新建议"}]))
    service = _service(fake_server)
    report = _run(service, pdf, [0, 1], document_dir)

    assert report.status == "ok"
    entries, _, _ = store.load()
    by_source = {entry.source_key: entry for entry in entries}
    assert by_source["ad"].status == "accepted"
    assert by_source["ad"].accepted_target == "用户确认"
    assert {s.target for s in by_source["ad"].targets} == {"用户确认", "自动建议", "新建议"}
    assert by_source["tcs"].status == "rejected"
    assert by_source["tcs"].rejected_targets == ["旧译法"]
    assert {s.target for s in by_source["tcs"].targets} == {"旧译法", "新建议"}


def test_unsupported_provider_degrades_without_store(tmp_path, fake_server):
    pdf = _pdf(tmp_path, ["text"])
    document_dir = _doc_dir(tmp_path)
    service = CandidateExtractionService(_cfg(), _model(provider="zhipu", base_url=None))
    report = _run(service, pdf, [0], document_dir)
    assert report.status == "unsupported"
    assert not (document_dir / "term_candidates.json").exists()
    assert _FakeHandler.requests == []


def test_disabled_no_network_and_no_store(tmp_path, fake_server):
    pdf = _pdf(tmp_path, ["text"])
    document_dir = _doc_dir(tmp_path)
    service = _service(fake_server, enabled=False)
    report = _run(service, pdf, [0], document_dir)
    assert report.status == "disabled"
    assert _FakeHandler.requests == []
    assert not (document_dir / "term_candidates.json").exists()


def test_empty_source_skips_network(tmp_path, fake_server):
    pdf = tmp_path / "blank.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(str(pdf))
    doc.close()
    document_dir = _doc_dir(tmp_path)
    service = _service(fake_server)
    report = _run(service, pdf, [0], document_dir)
    assert report.status == "empty"
    assert _FakeHandler.requests == []


def test_oversize_input_truncated_deterministically(tmp_path, fake_server):
    long_text = ("AD " * 3000).strip()
    pdf = _pdf(tmp_path, [long_text])
    _FakeHandler.responses.append(_ok([{"source": "AD", "target": "阿尔茨海默病"}]))
    document_dir = _doc_dir(tmp_path)
    service = _service(fake_server, max_input_chars=1000)
    report = _run(service, pdf, [0], document_dir)
    assert report.status == "ok"
    _, body, _ = _FakeHandler.requests[0]
    user_content = json.loads(body)["messages"][1]["content"]
    assert len(user_content) <= 1000
    assert user_content.startswith("AD")


def test_429_retry_then_ok_and_5xx_failure_degrades(tmp_path, fake_server):
    pdf = _pdf(tmp_path, ["AD text"])
    document_dir = _doc_dir(tmp_path)
    _FakeHandler.responses.append((429, b"", {}))
    _FakeHandler.responses.append(_ok([{"source": "AD", "target": "阿尔茨海默病"}]))
    service = _service(fake_server)
    report = _run(service, pdf, [0], document_dir)
    assert report.status == "ok"
    assert len(_FakeHandler.requests) == 2

    _FakeHandler.responses.append((503, b"", {}))
    _FakeHandler.responses.append((503, b"", {}))
    report = _run(service, pdf, [0], document_dir)
    assert report.status == "failed"


def test_4xx_timeout_and_malformed_all_degrades(tmp_path, fake_server):
    pdf = _pdf(tmp_path, ["AD text"])
    document_dir = _doc_dir(tmp_path)
    service = _service(fake_server)

    _FakeHandler.responses.append((400, b"", {}))
    assert _run(service, pdf, [0], document_dir).status == "failed"
    _FakeHandler.responses.append((200, b"not json", {}))
    assert _run(service, pdf, [0], document_dir).status == "failed"

    _FakeHandler.sleep_seconds = 0.25
    _FakeHandler.responses.append(_ok([{"source": "AD", "target": "阿尔茨海默病"}]))
    timeout_service = _service(fake_server, timeout=0.05)
    assert _run(timeout_service, pdf, [0], document_dir).status == "failed"
    assert not (document_dir / "term_candidates.json").exists()


def test_store_failure_degrades_and_body_semantics_unaffected(tmp_path, fake_server, monkeypatch):
    pdf = _pdf(tmp_path, ["AD text"])
    document_dir = _doc_dir(tmp_path)
    _FakeHandler.responses.append(_ok([{"source": "AD", "target": "阿尔茨海默病"}]))
    service = _service(fake_server)

    def boom(self, observations: object, **kwargs: object) -> Never:
        raise TermStoreError("disk failure")

    monkeypatch.setattr(CandidateStore, "record_observations", boom)
    report = _run(service, pdf, [0], document_dir)
    assert report.status == "store_failed"
    assert not (document_dir / "term_candidates.json").exists()


def test_identity_gate_same_active_job_writes_and_report_carries_identity(tmp_path, fake_server):
    pdf = _pdf(tmp_path, ["AD is a common term."])
    document_dir = _doc_dir(tmp_path)
    _FakeHandler.responses.append(_ok([{"source": "AD", "target": "阿尔茨海默病"}]))
    service = _service(fake_server)
    identity = CandidateIdentity(
        job_id="job-same",
        document_id="doc-same",
        pdf_hash=document_dir.name,
        document_dir=document_dir,
    )
    active = MagicMock(job_id="job-same", document_id="doc-same", pdf_hash=document_dir.name)

    report = _run(
        service,
        pdf,
        [0],
        document_dir,
        identity=identity,
        active_job_provider=lambda: active,
    )

    assert report.status == "ok"
    assert report.job_id == "job-same"
    assert report.document_id == "doc-same"
    assert report.pdf_hash == document_dir.name
    entries, _, _ = CandidateStore(document_dir).load()
    assert len(entries) == 1


@pytest.mark.parametrize(
    ("active", "expected_status"),
    [
        (None, "identity_rejected"),
        (MagicMock(job_id="other-job", document_id="doc-same", pdf_hash="h" * 64), "identity_rejected"),
        (MagicMock(job_id="job-same", document_id="other-doc", pdf_hash="h" * 64), "identity_rejected"),
        (MagicMock(job_id="job-same", document_id="doc-same", pdf_hash="h" * 64), "identity_rejected"),
    ],
)
def test_identity_gate_rejects_stale_or_other_job_without_store(tmp_path, fake_server, active, expected_status):
    pdf = _pdf(tmp_path, ["AD is a common term."])
    document_dir = _doc_dir(tmp_path)
    _FakeHandler.responses.append(_ok([{"source": "AD", "target": "阿尔茨海默病"}]))
    service = _service(fake_server)
    identity = CandidateIdentity(
        job_id="job-same",
        document_id="doc-same",
        pdf_hash=document_dir.name,
        document_dir=document_dir,
    )

    report = _run(
        service,
        pdf,
        [0],
        document_dir,
        identity=identity,
        active_job_provider=lambda: active,
    )

    assert report.status == expected_status
    assert report.job_id == "job-same"
    assert not (document_dir / "term_candidates.json").exists()


def test_identity_gate_rechecks_before_store_after_network(tmp_path, fake_server):
    pdf = _pdf(tmp_path, ["AD is a common term."])
    document_dir = _doc_dir(tmp_path)
    _FakeHandler.responses.append(_ok([{"source": "AD", "target": "阿尔茨海默病"}]))
    service = _service(fake_server)
    identity = CandidateIdentity(
        job_id="job-same",
        document_id="doc-same",
        pdf_hash=document_dir.name,
        document_dir=document_dir,
    )
    active = MagicMock(job_id="job-same", document_id="doc-same", pdf_hash=document_dir.name)
    calls = {"n": 0}

    def provider() -> object | None:
        calls["n"] += 1
        return active if calls["n"] == 1 else None

    report = _run(
        service,
        pdf,
        [0],
        document_dir,
        identity=identity,
        active_job_provider=provider,
    )

    assert calls["n"] == 2
    assert len(_FakeHandler.requests) == 1
    assert report.status == "identity_rejected"
    assert not (document_dir / "term_candidates.json").exists()


def test_prepare_never_writes_store_and_commit_writes(tmp_path, fake_server):
    pdf = _pdf(tmp_path, ["AD is a common term."])
    _FakeHandler.responses.append(_ok([{"source": "AD", "target": "阿尔茨海默病"}]))
    document_dir = _doc_dir(tmp_path)
    service = _service(fake_server)

    prepared = service.prepare(pdf, [0], document_dir)

    assert prepared.report.status == "ok"
    assert len(prepared.observations) == 1
    assert not (document_dir / "term_candidates.json").exists()

    report = service.commit(prepared, document_dir)
    assert report.status == "ok"
    entries, revision, _ = CandidateStore(document_dir).load()
    assert revision == 1
    assert len(entries) == 1


def test_identity_change_between_prepare_and_commit_rejected(tmp_path, fake_server):
    pdf = _pdf(tmp_path, ["AD is a common term."])
    _FakeHandler.responses.append(_ok([{"source": "AD", "target": "阿尔茨海默病"}]))
    document_dir = _doc_dir(tmp_path)
    service = _service(fake_server)
    identity = CandidateIdentity(
        job_id="job-a",
        document_id="doc-a",
        pdf_hash=document_dir.name,
        document_dir=document_dir,
    )
    active = MagicMock(job_id="job-a", document_id="doc-a", pdf_hash=document_dir.name)
    other = MagicMock(job_id="job-b", document_id="doc-a", pdf_hash=document_dir.name)

    prepared = service.prepare(pdf, [0], document_dir, identity=identity, active_job_provider=lambda: active)
    assert prepared.report.status == "ok"
    assert len(prepared.observations) == 1

    report = service.commit(prepared, document_dir, identity=identity, active_job_provider=lambda: other)

    assert report.status == "identity_rejected"
    assert not (document_dir / "term_candidates.json").exists()


def test_prepare_rejects_document_dir_identity_mismatch(tmp_path, fake_server):
    pdf = _pdf(tmp_path, ["AD is a common term."])
    _FakeHandler.responses.append(_ok([{"source": "AD", "target": "阿尔茨海默病"}]))
    dir_a = _hex_doc_dir(tmp_path, "a" * 64)
    dir_b = _hex_doc_dir(tmp_path, "b" * 64)
    service = _service(fake_server)
    identity_a = CandidateIdentity(
        job_id="job-a",
        document_id="doc-a",
        pdf_hash="a" * 64,
        document_dir=dir_a,
    )
    active_a = MagicMock(job_id="job-a", document_id="doc-a", pdf_hash="a" * 64)

    prepared = service.prepare(
        pdf,
        [0],
        dir_b,
        identity=identity_a,
        active_job_provider=lambda: active_a,
    )

    assert prepared.report.status == "identity_rejected"
    assert prepared.observations == ()
    assert prepared.identity == identity_a
    assert _FakeHandler.requests == []
    assert not (dir_a / "term_candidates.json").exists()
    assert not (dir_b / "term_candidates.json").exists()


def test_commit_identity_mismatch_cannot_cross_write(tmp_path, fake_server):
    pdf = _pdf(tmp_path, ["AD is a common term."])
    _FakeHandler.responses.append(_ok([{"source": "AD", "target": "阿尔茨海默病"}]))
    dir_a = _hex_doc_dir(tmp_path, "a" * 64)
    dir_b = _hex_doc_dir(tmp_path, "b" * 64)
    service = _service(fake_server)
    identity_a = CandidateIdentity(
        job_id="job-a",
        document_id="doc-a",
        pdf_hash="a" * 64,
        document_dir=dir_a,
    )
    identity_b = CandidateIdentity(
        job_id="job-b",
        document_id="doc-b",
        pdf_hash="b" * 64,
        document_dir=dir_b,
    )
    active_a = MagicMock(job_id="job-a", document_id="doc-a", pdf_hash="a" * 64)
    active_b = MagicMock(job_id="job-b", document_id="doc-b", pdf_hash="b" * 64)

    prepared = service.prepare(
        pdf,
        [0],
        dir_a,
        identity=identity_a,
        active_job_provider=lambda: active_a,
    )
    assert prepared.report.status == "ok"
    assert len(prepared.observations) == 1
    assert prepared.identity == identity_a

    report = service.commit(
        prepared,
        dir_b,
        identity=identity_b,
        active_job_provider=lambda: active_b,
    )

    assert report.status == "identity_rejected"
    assert not (dir_a / "term_candidates.json").exists()
    assert not (dir_b / "term_candidates.json").exists()


def test_commit_document_dir_mismatch_cannot_cross_write(tmp_path, fake_server):
    pdf = _pdf(tmp_path, ["AD is a common term."])
    _FakeHandler.responses.append(_ok([{"source": "AD", "target": "阿尔茨海默病"}]))
    dir_a = _hex_doc_dir(tmp_path, "a" * 64)
    dir_b = _hex_doc_dir(tmp_path, "b" * 64)
    service = _service(fake_server)
    identity_a = CandidateIdentity(
        job_id="job-a",
        document_id="doc-a",
        pdf_hash="a" * 64,
        document_dir=dir_a,
    )
    active_a = MagicMock(job_id="job-a", document_id="doc-a", pdf_hash="a" * 64)

    prepared = service.prepare(
        pdf,
        [0],
        dir_a,
        identity=identity_a,
        active_job_provider=lambda: active_a,
    )
    assert prepared.report.status == "ok"
    assert prepared.identity == identity_a

    report = service.commit(
        prepared,
        dir_b,
        identity=identity_a,
        active_job_provider=lambda: active_a,
    )

    assert report.status == "identity_rejected"
    assert not (dir_a / "term_candidates.json").exists()
    assert not (dir_b / "term_candidates.json").exists()


def test_commit_cannot_upgrade_identityless_prepared(tmp_path, fake_server):
    pdf = _pdf(tmp_path, ["AD is a common term."])
    _FakeHandler.responses.append(_ok([{"source": "AD", "target": "阿尔茨海默病"}]))
    dir_a = _hex_doc_dir(tmp_path, "a" * 64)
    service = _service(fake_server)
    identity_a = CandidateIdentity(
        job_id="job-a",
        document_id="doc-a",
        pdf_hash="a" * 64,
        document_dir=dir_a,
    )
    active_a = MagicMock(job_id="job-a", document_id="doc-a", pdf_hash="a" * 64)

    prepared = service.prepare(pdf, [0], dir_a)
    assert prepared.report.status == "ok"
    assert prepared.identity is None

    report = service.commit(
        prepared,
        dir_a,
        identity=identity_a,
        active_job_provider=lambda: active_a,
    )

    assert report.status == "identity_rejected"
    assert not (dir_a / "term_candidates.json").exists()


def test_commit_without_observations_is_noop(tmp_path, fake_server, managed_caplog):
    pdf = _pdf(tmp_path, ["Benefits are important for patients."])
    document_dir = _doc_dir(tmp_path)
    store = CandidateStore(document_dir)
    store.record_observation("TCS", "外用糖皮质激素")
    old_bytes = store.path.read_bytes()
    _FakeHandler.responses.append(_ok([{"source": "benefits", "target": "获益"}]))
    service = _service(fake_server)

    prepared = service.prepare(pdf, [0], document_dir)

    assert prepared.report.status == "all_filtered"
    assert prepared.observations == ()
    with managed_caplog.at_level(logging.INFO, logger="pdf_reader.candidate"):
        report = service.commit(prepared, document_dir)
    assert report.status == "all_filtered"
    assert store.path.read_bytes() == old_bytes
    assert "event=candidate_commit" in managed_caplog.text


def test_logs_never_contain_text_prompt_targets_or_keys(tmp_path, fake_server, managed_caplog):
    pdf = _pdf(tmp_path, ["SECRET-SOURCE-TERM appears in the guideline. Confusion is common."])
    document_dir = _doc_dir(tmp_path)
    _FakeHandler.responses.append(
        _ok(
            [
                {"source": "SECRET-SOURCE-TERM", "target": "秘密目标译法"},
                {"source": "confusion", "target": "混淆"},
            ]
        )
    )
    service = _service(fake_server)
    with managed_caplog.at_level(logging.INFO, logger="pdf_reader.candidate"):
        report = _run(service, pdf, [0], document_dir)
    assert report.status == "ok"
    assert report.proposed == 2
    assert report.candidates == 1
    assert report.filtered == 1
    text = managed_caplog.text
    assert "SECRET-SOURCE-TERM" not in text
    assert "秘密目标译法" not in text
    assert "confusion" not in text
    assert "混淆" not in text
    assert "sk-service-test" not in text
    assert str(pdf) not in text
    assert "Traceback" not in text
    assert "common_word" in text
    assert "candidate summary" in text
    assert "proposed=2" in text
    assert "kept=1" in text
    assert "filtered=1" in text
    assert "failed=0" in text
    assert "usage=" in text
    assert "pages=(1,)" in text


def test_commit_summary_logs_store_state_counts(tmp_path, fake_server, managed_caplog):
    pdf = _pdf(tmp_path, ["AD is a common term."])
    _FakeHandler.responses.append(_ok([{"source": "AD", "target": "阿尔茨海默病"}]))
    document_dir = _doc_dir(tmp_path)
    service = _service(fake_server)

    with managed_caplog.at_level(logging.INFO, logger="pdf_reader.candidate"):
        _run(service, pdf, [0], document_dir)

    assert "event=candidate_commit" in managed_caplog.text
    assert "pending=1" in managed_caplog.text
    assert "accepted=0" in managed_caplog.text
    assert "rejected=0" in managed_caplog.text


def test_commit_pending_stat_failure_degrades_without_store_damage(tmp_path, fake_server, monkeypatch, managed_caplog):
    pdf = _pdf(tmp_path, ["AD is a common term."])
    _FakeHandler.responses.append(_ok([{"source": "AD", "target": "阿尔茨海默病"}]))
    document_dir = _doc_dir(tmp_path)
    service = _service(fake_server)

    def boom(self) -> None:
        raise TermStoreError("summary stat unavailable")

    monkeypatch.setattr(CandidateStore, "candidate_summaries", boom)
    with managed_caplog.at_level(logging.INFO, logger="pdf_reader.candidate"):
        report = _run(service, pdf, [0], document_dir)

    assert report.status == "ok"
    assert "event=candidate_commit" in managed_caplog.text
    assert "pending=unavailable" in managed_caplog.text
    assert "accepted=unavailable" in managed_caplog.text
    assert "rejected=unavailable" in managed_caplog.text
    entries, _, _ = CandidateStore(document_dir).load()
    assert len(entries) == 1


def test_commit_summary_counts_real_store_states(tmp_path, fake_server, managed_caplog):
    pdf = _pdf(tmp_path, ["AD is a common term."])
    _FakeHandler.responses.append(_ok([{"source": "AD", "target": "阿尔茨海默病"}]))
    document_dir = _doc_dir(tmp_path)
    store = CandidateStore(document_dir)
    store.record_observation("TCS", "外用糖皮质激素")
    store.accept("TCS")
    store.record_observation("benefits", "福利")
    store.reject("benefits")
    service = _service(fake_server)

    with managed_caplog.at_level(logging.INFO, logger="pdf_reader.candidate"):
        report = _run(service, pdf, [0], document_dir)

    assert report.status == "ok"
    text = managed_caplog.text
    assert "event=candidate_commit" in text
    assert "pending=1" in text
    assert "accepted=1" in text
    assert "rejected=1" in text
    for secret in ("AD", "TCS", "benefits", "阿尔茨海默病", "外用糖皮质激素", "福利"):
        assert secret not in text


def test_commit_identity_rejected_emits_summary(tmp_path, fake_server, managed_caplog):
    pdf = _pdf(tmp_path, ["AD is a common term."])
    _FakeHandler.responses.append(_ok([{"source": "AD", "target": "阿尔茨海默病"}]))
    document_dir = _doc_dir(tmp_path)
    service = _service(fake_server)
    identity = CandidateIdentity(
        job_id="job-a",
        document_id="doc-a",
        pdf_hash=document_dir.name,
        document_dir=document_dir,
    )
    active = MagicMock(job_id="job-a", document_id="doc-a", pdf_hash=document_dir.name)
    other = MagicMock(job_id="job-b", document_id="doc-a", pdf_hash=document_dir.name)
    prepared = service.prepare(pdf, [0], document_dir, identity=identity, active_job_provider=lambda: active)
    assert prepared.report.status == "ok"

    with managed_caplog.at_level(logging.INFO, logger="pdf_reader.candidate"):
        report = service.commit(prepared, document_dir, identity=identity, active_job_provider=lambda: other)

    assert report.status == "identity_rejected"
    assert "event=candidate_commit" in managed_caplog.text
    assert "status=identity_rejected" in managed_caplog.text
    assert "failed=0" in managed_caplog.text
    assert not (document_dir / "term_candidates.json").exists()


def test_commit_store_failed_emits_summary_with_failed(tmp_path, fake_server, monkeypatch, managed_caplog):
    pdf = _pdf(tmp_path, ["AD text"])
    _FakeHandler.responses.append(_ok([{"source": "AD", "target": "阿尔茨海默病"}]))
    document_dir = _doc_dir(tmp_path)
    service = _service(fake_server)

    def boom(self, observations: object, **kwargs: object) -> None:
        raise TermStoreError("disk failure")

    monkeypatch.setattr(CandidateStore, "record_observations", boom)
    with managed_caplog.at_level(logging.INFO, logger="pdf_reader.candidate"):
        report = _run(service, pdf, [0], document_dir)

    assert report.status == "store_failed"
    assert "event=candidate_commit" in managed_caplog.text
    assert "status=store_failed" in managed_caplog.text
    assert "failed=1" in managed_caplog.text
    assert not (document_dir / "term_candidates.json").exists()


def test_candidate_term_service_exposes_deterministic_summaries(tmp_path):
    document_dir = _doc_dir(tmp_path)
    store = CandidateStore(document_dir)
    store.record_observation("AD", "自动建议")
    store.accept("AD", target="用户确认")
    store.record_observation("AD", "高票建议", pages=[1, 2, 3])
    store.record_observation("benefits", "福利", pages=[1])
    store.reject("benefits", target="福利")

    service = CandidateTermService(document_dir)
    summaries = service.list_summaries()
    assert [summary.source_key for summary in summaries] == ["ad", "benefits"]

    ad = summaries[0]
    assert ad.status == "accepted"
    assert ad.accepted_target == "用户确认"
    assert [item.target for item in ad.targets] == ["用户确认", "高票建议", "自动建议"]
    assert ad.targets[0].accepted is True
    assert ad.targets[0].suppressed is False
    assert ad.targets[0].rank == 1
    assert ad.targets[1].target == "高票建议"
    assert ad.targets[1].observations == 1
    assert ad.targets[1].distinct_page_count == 3
    assert ad.targets[1].pages == (1, 2, 3)

    benefits = summaries[1]
    assert benefits.status == "rejected"
    assert all(item.suppressed for item in benefits.targets)
    assert [item.target for item in benefits.targets] == ["福利"]
    assert benefits.targets[0].rejected is True
    assert benefits.targets[0].rank == 1

    targets = service.target_summaries("benefits")
    assert [item.target for item in targets] == ["福利"]
    assert targets[0].rejected is True
    assert targets[0].suppressed is True


def test_candidate_term_service_raises_for_missing_source(tmp_path):
    service = CandidateTermService(_doc_dir(tmp_path))
    with pytest.raises(TermStoreError, match="not found"):
        service.target_summaries("missing")
