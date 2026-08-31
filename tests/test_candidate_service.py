"""P1-01 候选提取服务：fake local HTTP server + 真实 CandidateStore 边界。"""

from __future__ import annotations

import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Never

import pymupdf
import pytest

from pdf_reader.candidate_filter import CANDIDATE_STRATEGY_VERSION
from pdf_reader.candidate_service import CandidateExtractionService
from pdf_reader.candidate_store import CandidateStore
from pdf_reader.config import CandidateExtractionRuntimeConfig, ModelRuntimeConfig
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


def _ok(terms: list[dict[str, str]]) -> tuple[int, bytes, dict[str, str]]:
    content = json.dumps({"terms": terms}, ensure_ascii=False)
    payload = json.dumps({"choices": [{"message": {"content": content}}]}, ensure_ascii=False).encode("utf-8")
    return 200, payload, {}


def _service(fake_server: str, **overrides: object) -> CandidateExtractionService:
    return CandidateExtractionService(_cfg(**overrides), _model(base_url=fake_server))


def test_success_writes_candidates_with_pages_and_strategy(tmp_path, fake_server):
    pdf = _pdf(tmp_path, ["AD is a common term.", "TCS is another term."])
    _FakeHandler.responses.append(
        _ok([{"source": "AD", "target": "阿尔茨海默病"}, {"source": "TCS", "target": "外用糖皮质激素"}])
    )
    document_dir = _doc_dir(tmp_path)
    service = _service(fake_server)

    report = service.run_for_pdf(pdf, [0, 1], document_dir)

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


def test_nonzero_single_page_maps_local_pdf_to_original_page(tmp_path, fake_server):
    # 原文第 10 页（0-based 9）抽取成 1 页局部 PDF：必须按 local_idx=0 读取，
    # 证据页记录为 10，不能 doc[9] 越界。
    pdf = _pdf(tmp_path, ["AD appears on original page ten."])
    _FakeHandler.responses.append(_ok([{"source": "AD", "target": "阿尔茨海默病"}]))
    document_dir = _doc_dir(tmp_path)
    service = _service(fake_server)

    report = service.run_for_pdf(pdf, [9], document_dir)

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

    report = service.run_for_pdf(pdf, [2, 5], document_dir)

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

    report = service.run_for_pdf(pdf, [0], document_dir)

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

    report = service.run_for_pdf(pdf, [0], document_dir)

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

    report = service.run_for_pdf(pdf, [0], document_dir)

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

    report = service.run_for_pdf(pdf, [0, 1], document_dir)

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
    report = service.run_for_pdf(pdf, [0, 1], document_dir)

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
    report = service.run_for_pdf(pdf, [0], document_dir)
    assert report.status == "unsupported"
    assert not (document_dir / "term_candidates.json").exists()
    assert _FakeHandler.requests == []


def test_disabled_no_network_and_no_store(tmp_path, fake_server):
    pdf = _pdf(tmp_path, ["text"])
    document_dir = _doc_dir(tmp_path)
    service = _service(fake_server, enabled=False)
    report = service.run_for_pdf(pdf, [0], document_dir)
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
    report = service.run_for_pdf(pdf, [0], document_dir)
    assert report.status == "empty"
    assert _FakeHandler.requests == []


def test_oversize_input_truncated_deterministically(tmp_path, fake_server):
    long_text = ("AD " * 3000).strip()
    pdf = _pdf(tmp_path, [long_text])
    _FakeHandler.responses.append(_ok([{"source": "AD", "target": "阿尔茨海默病"}]))
    document_dir = _doc_dir(tmp_path)
    service = _service(fake_server, max_input_chars=1000)
    report = service.run_for_pdf(pdf, [0], document_dir)
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
    report = service.run_for_pdf(pdf, [0], document_dir)
    assert report.status == "ok"
    assert len(_FakeHandler.requests) == 2

    _FakeHandler.responses.append((503, b"", {}))
    _FakeHandler.responses.append((503, b"", {}))
    report = service.run_for_pdf(pdf, [0], document_dir)
    assert report.status == "failed"


def test_4xx_timeout_and_malformed_all_degrades(tmp_path, fake_server):
    pdf = _pdf(tmp_path, ["AD text"])
    document_dir = _doc_dir(tmp_path)
    service = _service(fake_server)

    _FakeHandler.responses.append((400, b"", {}))
    assert service.run_for_pdf(pdf, [0], document_dir).status == "failed"
    _FakeHandler.responses.append((200, b"not json", {}))
    assert service.run_for_pdf(pdf, [0], document_dir).status == "failed"

    _FakeHandler.sleep_seconds = 0.25
    _FakeHandler.responses.append(_ok([{"source": "AD", "target": "阿尔茨海默病"}]))
    timeout_service = _service(fake_server, timeout=0.05)
    assert timeout_service.run_for_pdf(pdf, [0], document_dir).status == "failed"
    assert not (document_dir / "term_candidates.json").exists()


def test_store_failure_degrades_and_body_semantics_unaffected(tmp_path, fake_server, monkeypatch):
    pdf = _pdf(tmp_path, ["AD text"])
    document_dir = _doc_dir(tmp_path)
    _FakeHandler.responses.append(_ok([{"source": "AD", "target": "阿尔茨海默病"}]))
    service = _service(fake_server)

    def boom(self, observations: object, **kwargs: object) -> Never:
        raise TermStoreError("disk failure")

    monkeypatch.setattr(CandidateStore, "record_observations", boom)
    report = service.run_for_pdf(pdf, [0], document_dir)
    assert report.status == "store_failed"
    assert not (document_dir / "term_candidates.json").exists()


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
        report = service.run_for_pdf(pdf, [0], document_dir)
    assert report.status == "ok"
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
    assert "candidates=1" in text
    assert "pages=(1,)" in text
