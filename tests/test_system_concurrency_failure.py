"""P1-04 system-level concurrency and failure regression tests.

These tests cross real Flask routes, the real Response/SSE generators, the
real TranslationCoordinator, a real TranslationStream worker thread, the real
AppState document/identity boundaries and the real disk cache.  Only the
external translation engine boundary (``do_translate_async_stream``) is
replaced by a deterministic fake; failure injection is limited to
``tempfile.mkdtemp``, ``cache_ops.write_temp_marker``, ``pymupdf.Document.save``
and ``os.replace`` so the surrounding real lifecycle still runs.

Test matrix (each row maps to one or more tests below):

1. (a) A translating, open B -> HTTP 409 translation_busy; B never gets a
   cache dir; A's completed result is committed into A's right.pdf only.
2. (b) Two Flask clients: only one translation request is accepted; the loser
   gets 409 with the winner's job id, starts no worker and creates no dirs.
3. (c) SSE disconnected while the worker is alive; the worker continues and
   produces a late finish, the late result never reaches replace_page,
   dirs are removed only after the worker exits, job released as cancelled.
4. (d) SSE disconnected and the worker eventually fails; the failure is
   contained, dirs removed after exit, job released, document untouched.
5. (e) Worker ignores cancellation past the join timeout: dirs are kept for
   recovery, job slot is still released as cancelled, and the test releases
   the worker afterwards and joins it so no daemon thread leaks past the case.
6. (f) workspace-root creation, marker-write and PDF save failures each produce
   an SSE error, clean up, release the job and allow a retry.
7. (g) Single-page and batch commit failures leave right.pdf/translated_pages
   at their last committed state, stay renderable and recover on retry.
8. (h) Partial-commit semantics pinned: PDF replace runs first, glossary merge
   second.  A failed PDF commit aborts before glossary merge; a failed
   glossary commit keeps the PDF commit, keeps the old glossary and still
   finishes the job (the real merge callback contains the failure).
9. (i) One Flask-client round trip: open -> translate (fake upstream, real
   SSE consumption) -> render, checking final PDF bytes/page text,
   document_id, coordinator state, worker state and temp-dir cleanup.
"""

import csv
import os
import tempfile
import threading
from collections.abc import AsyncIterator
from pathlib import Path

import pymupdf
import pytest
from flask import Flask

from pdf_reader import cache_ops, config, sse_stream, translation_orchestrator
from pdf_reader.file_hash import sha256
from pdf_reader.routes import register_routes
from pdf_reader.state import AppState
from pdf_reader.strict_glossary import StrictTranslationContext
from pdf_reader.translation_coordinator import TranslationCoordinator

pytestmark = pytest.mark.system


class FakeTranslateResult:
    """Protocol-shaped result produced by the fake upstream engine."""

    def __init__(
        self,
        mono_pdf_path: str | Path | None = None,
        dual_pdf_path: str | Path | None = None,
        auto_extracted_glossary_path: str | Path | None = None,
    ) -> None:
        self.mono_pdf_path = mono_pdf_path
        self.dual_pdf_path = dual_pdf_path
        self.auto_extracted_glossary_path = auto_extracted_glossary_path


class ControlledUpstream:
    """Deterministic async upstream for a real TranslationStream worker.

    The worker yields one progress event, then blocks until ``release`` is
    set (or the optional ``stuck`` branch sleeps instead).  Afterwards it
    either yields a finish event with a result, or raises a recorded error.
    The events record that the worker really continued after the consumer
    disconnected and which late outcome it produced.
    """

    def __init__(
        self,
        result: FakeTranslateResult | None = None,
        fail_error: str | None = None,
        stuck: bool = False,
    ) -> None:
        self.release = threading.Event()
        self.started = threading.Event()
        self.progress_yielded = threading.Event()
        self.stuck_blocked = threading.Event()
        self.finish_yielded = threading.Event()
        self.raised = threading.Event()
        self.result = result
        self._fail_error = fail_error
        self._stuck = stuck

    async def __call__(self, settings, pdf_path: str) -> AsyncIterator[dict]:
        self.started.set()
        yield {
            "type": "progress_start",
            "stage": "layout_analysis",
            "overall_progress": 0,
            "stage_current": 0,
            "stage_total": 0,
        }
        self.progress_yielded.set()
        if self._stuck:
            self.stuck_blocked.set()
            # Block until the test releases us.  A threading-Event wait cannot
            # observe TranslationStream.cancel(), so the worker stays alive
            # through the join-timeout assertion without a long sleep.
            self.release.wait(timeout=30)
            return
        self.release.wait(timeout=60)
        if self._fail_error is not None:
            self.raised.set()
            raise RuntimeError(self._fail_error)
        self.finish_yielded.set()
        yield {
            "type": "finish",
            "stage": "generating_pdf",
            "translate_result": self.result,
            "token_usage": {},
        }


@pytest.fixture
def system_app(tmp_path, monkeypatch, mock_config):
    """A real Flask app with a tmp cache, real AppState and coordinator."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    monkeypatch.setattr(config, "CACHE_DIR", cache_dir)
    monkeypatch.setattr(config, "DEBUG", False)
    app = Flask(__name__)
    app.config.update(TESTING=True)
    app.config["app_state"] = AppState(cache_dir)
    app.config["translation_coordinator"] = TranslationCoordinator()
    register_routes(app)

    def fake_prepare(snapshot):  # noqa: ANN202
        return StrictTranslationContext(
            document_dir=snapshot.glossary_cache_path,
            document_id=snapshot.document_id,
            pdf_hash=snapshot.pdf_hash,
            effective_glossary_path=None,
            effective_rows=(),
        )

    monkeypatch.setattr("pdf_reader.routes.strict_glossary.prepare_strict_translation_context", fake_prepare)
    yield app
    app.config["app_state"]._close_docs()


@pytest.fixture
def system_client(system_app):
    with system_app.test_client() as client:
        yield client


def _make_pdf(path: Path, pages: int, labels: list[str]) -> Path:
    doc = pymupdf.open()
    try:
        for i in range(pages):
            page = doc.new_page(width=612, height=792)
            page.insert_text((50, 100), labels[i], fontsize=24)
        doc.save(str(path))
    finally:
        doc.close()
    return path


def _make_translated_pdf(path: Path, labels: list[str]) -> Path:
    return _make_pdf(path, len(labels), labels)


def _write_glossary(path: Path, rows: list[tuple[str, str]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["source", "target"])
        writer.writerows(rows)


def _read_glossary(path: Path) -> list[tuple[str, str]]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [(row["source"], row["target"]) for row in csv.DictReader(f)]


def _pdf_texts(path: str | Path) -> list[str]:
    with pymupdf.open(str(path)) as doc:
        return [page.get_text() for page in doc]


def _open_document(client, pdf_path: Path) -> dict:
    resp = client.post("/api/open", json={"path": str(pdf_path)})
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data["document_id"], str) and data["document_id"]
    return data


def _consume(response) -> str:
    body = "".join(chunk.decode("utf-8") for chunk in response.response)
    response.close()
    return body


def _document_marker(app_state) -> tuple[str, int, frozenset[int]]:
    return sha256(app_state._right_pdf_path), app_state.page_count, app_state.translated_pages


def _assert_marker(app_state, marker: tuple[str, int, frozenset[int]]) -> None:
    assert sha256(app_state._right_pdf_path) == marker[0]
    assert app_state.page_count == marker[1]
    assert app_state.translated_pages == marker[2]


def _assert_renderable(client, page_count: int) -> None:
    for page in range(page_count):
        resp = client.get(f"/api/page/right/{page}")
        assert resp.status_code == 200
        assert resp.data[:4] == b"\x89PNG"


def _install_upstream(monkeypatch, source: ControlledUpstream) -> None:
    monkeypatch.setattr(translation_orchestrator, "do_translate_async_stream", source)


def _install_stream_spy(monkeypatch) -> list:
    """Wrap the real run_translation factory and record the real streams."""
    streams: list = []
    real_factory = translation_orchestrator.run_translation

    def spy(
        settings,
        pdf_path: str,
        flow_label: str = "",
        task_ctx=None,
    ) -> translation_orchestrator.TranslationStream:
        stream = real_factory(settings, pdf_path, flow_label, task_ctx)
        streams.append(stream)
        return stream

    monkeypatch.setattr(sse_stream, "run_translation", spy)
    return streams


def _install_mkdtemp_control(monkeypatch, fail_at: int | None = None) -> list:
    """Record real temp dirs; optionally raise on the fail_at-th call."""
    created: list = []
    real_mkdtemp = tempfile.mkdtemp
    counter = {"n": 0}

    def controlled(*args: object, **kwargs: object) -> str:
        counter["n"] += 1
        if fail_at is not None and counter["n"] == fail_at:
            raise OSError(f"injected mkdtemp failure at call {fail_at}")
        path = real_mkdtemp(*args, **kwargs)
        created.append(Path(path))
        return path

    monkeypatch.setattr(tempfile, "mkdtemp", controlled)
    return created


def _fail_document_save_at(monkeypatch, call_number: int) -> None:
    real_save = pymupdf.Document.save
    counter = {"n": 0}

    def failing_save(self, *args: object, **kwargs: object) -> None:
        counter["n"] += 1
        if counter["n"] == call_number:
            raise RuntimeError(f"injected Document.save failure at call {call_number}")
        real_save(self, *args, **kwargs)

    monkeypatch.setattr(pymupdf.Document, "save", failing_save)


def _fail_os_replace_at(monkeypatch, call_number: int) -> None:
    real_replace = os.replace
    counter = {"n": 0}

    def failing_replace(src, dst) -> None:
        counter["n"] += 1
        if counter["n"] == call_number:
            raise OSError(f"injected os.replace failure at call {call_number}")
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", failing_replace)


# --- (a) open B while A is translating --------------------------------


def test_open_b_rejected_while_translation_active_and_result_stays_in_a(
    system_app, system_client, tmp_path, monkeypatch
):
    state = system_app.config["app_state"]
    coordinator = system_app.config["translation_coordinator"]
    pdf_a = _make_pdf(tmp_path / "a.pdf", 2, ["A_0", "A_1"])
    pdf_b = _make_pdf(tmp_path / "b.pdf", 2, ["B_0", "B_1"])
    doc_a = _open_document(system_client, pdf_a)
    translated_a = _make_translated_pdf(tmp_path / "translated_a.pdf", ["TA_0"])

    source = ControlledUpstream(result=FakeTranslateResult(mono_pdf_path=str(translated_a)))
    _install_upstream(monkeypatch, source)
    created = _install_mkdtemp_control(monkeypatch)
    streams = _install_stream_spy(monkeypatch)

    first = system_client.post("/api/translate/0", json={}, buffered=False)
    assert first.status_code == 200
    assert source.progress_yielded.wait(timeout=5)
    assert coordinator.active_job is not None
    assert len(streams) == 1

    hash_b = sha256(str(pdf_b))
    rejected = system_app.test_client().post("/api/open", json={"path": str(pdf_b)})
    assert rejected.status_code == 409
    payload = rejected.get_json()
    assert payload["code"] == "translation_busy"
    assert payload["active_job_id"] == coordinator.active_job.job_id
    assert state.translation_snapshot().document_id == doc_a["document_id"]
    assert not (config.CACHE_DIR / hash_b).exists()

    source.release.set()
    body = _consume(first)
    assert '"type": "finish"' in body
    assert coordinator.active_job is None
    assert streams[0].is_alive is False

    texts = _pdf_texts(state._right_pdf_path)
    assert "TA_0" in texts[0]
    assert "A_1" in texts[1]
    assert state.translated_pages == frozenset({0})
    assert state.translation_snapshot().document_id == doc_a["document_id"]
    assert not (config.CACHE_DIR / hash_b).exists()
    assert all(not p.exists() for p in created)


# --- (b) two clients, one accepted ------------------------------------


def test_two_clients_only_one_translation_accepted(system_app, system_client, tmp_path, monkeypatch):
    state = system_app.config["app_state"]
    coordinator = system_app.config["translation_coordinator"]
    pdf = _make_pdf(tmp_path / "two.pdf", 2, ["S_0", "S_1"])
    doc = _open_document(system_client, pdf)
    translated = _make_translated_pdf(tmp_path / "translated.pdf", ["X_0"])

    source = ControlledUpstream(result=FakeTranslateResult(mono_pdf_path=str(translated)))
    _install_upstream(monkeypatch, source)
    created = _install_mkdtemp_control(monkeypatch)
    streams = _install_stream_spy(monkeypatch)

    first = system_client.post("/api/translate/0", json={}, buffered=False)
    assert first.status_code == 200
    assert source.progress_yielded.wait(timeout=5)
    assert coordinator.active_job is not None

    second_client = system_app.test_client()
    rejected = second_client.post("/api/translate-batch", json={"from": 1, "to": 2})
    assert rejected.status_code == 409
    payload = rejected.get_json()
    assert payload["code"] == "translation_busy"
    assert payload["active_job_id"] == coordinator.active_job.job_id
    assert len(streams) == 1, "rejected request must not start a worker"
    assert len(created) == 1, "rejected request must not create a temp workspace"
    assert state.translation_snapshot().document_id == doc["document_id"]

    source.release.set()
    first.close()

    assert coordinator.active_job is None
    assert streams[0].is_alive is False
    assert all(not p.exists() for p in created)
    assert state.translated_pages == frozenset()
    assert "X_0" not in "".join(_pdf_texts(state._right_pdf_path))


# --- (c)/(d)/(e) SSE disconnect and worker ownership -------------------


def test_sse_disconnect_worker_continues_late_result_discarded(system_app, system_client, tmp_path, monkeypatch):
    state = system_app.config["app_state"]
    coordinator = system_app.config["translation_coordinator"]
    pdf = _make_pdf(tmp_path / "disc.pdf", 2, ["D_0", "D_1"])
    _open_document(system_client, pdf)
    translated = _make_translated_pdf(tmp_path / "late.pdf", ["LATE_0"])

    source = ControlledUpstream(result=FakeTranslateResult(mono_pdf_path=str(translated)))
    _install_upstream(monkeypatch, source)
    created = _install_mkdtemp_control(monkeypatch)
    streams = _install_stream_spy(monkeypatch)
    marker = _document_marker(state)

    resp = system_client.post("/api/translate/0", json={}, buffered=False)
    assert resp.status_code == 200
    assert source.progress_yielded.wait(timeout=5)
    assert streams[0].is_alive is True, "worker must still be running at disconnect"

    timer = threading.Timer(0.3, source.release.set)
    timer.start()
    resp.close()
    timer.join()

    assert source.finish_yielded.is_set(), "worker continued and produced the late result"
    assert streams[0].is_alive is False, "worker exited before dir cleanup"
    assert coordinator.active_job is None
    assert all(not p.exists() for p in created)
    _assert_marker(state, marker)
    assert state.translated_pages == frozenset()


def test_sse_disconnect_worker_fails_late_task_released(system_app, system_client, tmp_path, monkeypatch):
    state = system_app.config["app_state"]
    coordinator = system_app.config["translation_coordinator"]
    pdf = _make_pdf(tmp_path / "fail.pdf", 2, ["F_0", "F_1"])
    _open_document(system_client, pdf)

    source = ControlledUpstream(fail_error="late worker failure")
    _install_upstream(monkeypatch, source)
    created = _install_mkdtemp_control(monkeypatch)
    streams = _install_stream_spy(monkeypatch)
    marker = _document_marker(state)

    resp = system_client.post("/api/translate/0", json={}, buffered=False)
    assert resp.status_code == 200
    assert source.progress_yielded.wait(timeout=5)
    assert streams[0].is_alive is True

    timer = threading.Timer(0.3, source.release.set)
    timer.start()
    resp.close()
    timer.join()

    assert source.raised.is_set(), "worker continued and eventually failed"
    assert streams[0].is_alive is False
    assert coordinator.active_job is None
    assert all(not p.exists() for p in created)
    _assert_marker(state, marker)
    assert state.translated_pages == frozenset()


def test_sse_disconnect_join_timeout_keeps_dirs_and_releases_task(system_app, system_client, tmp_path, monkeypatch):
    state = system_app.config["app_state"]
    coordinator = system_app.config["translation_coordinator"]
    pdf = _make_pdf(tmp_path / "stuck.pdf", 2, ["K_0", "K_1"])
    _open_document(system_client, pdf)

    source = ControlledUpstream(stuck=True)
    _install_upstream(monkeypatch, source)
    created = _install_mkdtemp_control(monkeypatch)
    streams = _install_stream_spy(monkeypatch)
    monkeypatch.setattr(sse_stream, "WORKER_JOIN_TIMEOUT", 0.2)
    marker = _document_marker(state)

    resp = system_client.post("/api/translate/0", json={}, buffered=False)
    assert resp.status_code == 200
    assert source.progress_yielded.wait(timeout=5)
    assert source.stuck_blocked.wait(timeout=5), "worker must be blocked before disconnect"
    assert streams[0].is_alive is True

    resp.close()

    assert streams[0].is_alive is True, "non-cooperative worker survives join timeout"
    assert coordinator.active_job is None, "job slot still released as cancelled"
    assert len(created) == 1
    workspace = created[0]
    assert workspace.exists(), "workspace must be kept for recovery"
    assert (workspace / "input").is_dir(), "input dir must be kept for recovery"
    assert (workspace / "output").is_dir(), "output dir must be kept for recovery"
    assert (workspace / cache_ops.TEMP_MARKER_NAME).is_file(), "marker must be kept for recovery"
    _assert_marker(state, marker)

    # Test-controlled teardown: release the fake upstream, then explicitly
    # join the real worker so no daemon thread outlives this test case.
    source.release.set()
    streams[0].join(timeout=5)
    assert streams[0].is_alive is False, "worker must be joined before the case ends"
    assert workspace.exists(), "retained workspace must not be deleted by production logic"
    assert (workspace / "input").is_dir()
    assert (workspace / "output").is_dir()
    assert (workspace / cache_ops.TEMP_MARKER_NAME).is_file()


# --- (f) temp/output dir and PDF save failures -------------------------


def test_temp_dir_creation_failure_yields_error_and_recovers(system_app, system_client, tmp_path, monkeypatch):
    state = system_app.config["app_state"]
    coordinator = system_app.config["translation_coordinator"]
    pdf = _make_pdf(tmp_path / "tmpfail.pdf", 2, ["M_0", "M_1"])
    _open_document(system_client, pdf)
    translated = _make_translated_pdf(tmp_path / "ok.pdf", ["OK_0"])
    source = ControlledUpstream(result=FakeTranslateResult(mono_pdf_path=str(translated)))
    _install_upstream(monkeypatch, source)
    streams = _install_stream_spy(monkeypatch)
    created = _install_mkdtemp_control(monkeypatch, fail_at=1)
    marker = _document_marker(state)

    body = _consume(system_client.post("/api/translate/0", json={}, buffered=False))
    assert '"type": "error"' in body
    assert streams == [], "no worker may start when temp dir creation fails"
    assert coordinator.active_job is None
    assert created == []
    _assert_marker(state, marker)

    source.release.set()
    body = _consume(system_client.post("/api/translate/0", json={}, buffered=False))
    assert '"type": "finish"' in body
    assert 0 in state.translated_pages
    assert "OK_0" in _pdf_texts(state._right_pdf_path)[0]
    assert all(not p.exists() for p in created)


def test_marker_write_failure_cleans_workspace_and_recovers(system_app, system_client, tmp_path, monkeypatch):
    state = system_app.config["app_state"]
    coordinator = system_app.config["translation_coordinator"]
    pdf = _make_pdf(tmp_path / "outfail.pdf", 2, ["N_0", "N_1"])
    _open_document(system_client, pdf)
    translated = _make_translated_pdf(tmp_path / "ok2.pdf", ["OK2_0"])
    source = ControlledUpstream(result=FakeTranslateResult(mono_pdf_path=str(translated)))
    _install_upstream(monkeypatch, source)
    streams = _install_stream_spy(monkeypatch)
    created = _install_mkdtemp_control(monkeypatch)
    real_write_marker = cache_ops.write_temp_marker
    counter = {"n": 0}

    def failing_marker(dir_path, *, job_id, pid=None) -> None:
        counter["n"] += 1
        if counter["n"] == 1:
            raise OSError("injected marker write failure")
        real_write_marker(dir_path, job_id=job_id, pid=pid)

    monkeypatch.setattr(cache_ops, "write_temp_marker", failing_marker)
    marker = _document_marker(state)

    body = _consume(system_client.post("/api/translate/0", json={}, buffered=False))
    assert '"type": "error"' in body
    assert streams == [], "no worker may start when workspace marker write fails"
    assert coordinator.active_job is None
    assert len(created) == 1
    assert not created[0].exists(), "workspace root must be cleaned even on setup failure"
    _assert_marker(state, marker)

    source.release.set()
    body = _consume(system_client.post("/api/translate/0", json={}, buffered=False))
    assert '"type": "finish"' in body
    assert 0 in state.translated_pages
    assert all(not p.exists() for p in created)


def test_extraction_pdf_save_failure_cleans_up_and_recovers(system_app, system_client, tmp_path, monkeypatch):
    state = system_app.config["app_state"]
    coordinator = system_app.config["translation_coordinator"]
    pdf = _make_pdf(tmp_path / "savefail.pdf", 2, ["P_0", "P_1"])
    _open_document(system_client, pdf)
    translated = _make_translated_pdf(tmp_path / "ok3.pdf", ["OK3_0"])
    source = ControlledUpstream(result=FakeTranslateResult(mono_pdf_path=str(translated)))
    _install_upstream(monkeypatch, source)
    streams = _install_stream_spy(monkeypatch)
    created = _install_mkdtemp_control(monkeypatch)
    _fail_document_save_at(monkeypatch, 1)
    marker = _document_marker(state)

    body = _consume(system_client.post("/api/translate/0", json={}, buffered=False))
    assert '"type": "error"' in body
    assert streams == [], "extraction save failure must happen before the worker starts"
    assert coordinator.active_job is None
    assert all(not p.exists() for p in created)
    _assert_marker(state, marker)

    source.release.set()
    body = _consume(system_client.post("/api/translate/0", json={}, buffered=False))
    assert '"type": "finish"' in body
    assert 0 in state.translated_pages


def test_replace_pdf_save_failure_keeps_document_and_recovers(system_app, system_client, tmp_path, monkeypatch):
    state = system_app.config["app_state"]
    coordinator = system_app.config["translation_coordinator"]
    pdf = _make_pdf(tmp_path / "repsave.pdf", 2, ["Q_0", "Q_1"])
    _open_document(system_client, pdf)
    translated = _make_translated_pdf(tmp_path / "ok4.pdf", ["OK4_0"])
    source = ControlledUpstream(result=FakeTranslateResult(mono_pdf_path=str(translated)))
    _install_upstream(monkeypatch, source)
    streams = _install_stream_spy(monkeypatch)
    created = _install_mkdtemp_control(monkeypatch)
    _fail_document_save_at(monkeypatch, 2)  # extraction save succeeds, work-copy save fails
    marker = _document_marker(state)

    source.release.set()
    body = _consume(system_client.post("/api/translate/0", json={}, buffered=False))
    assert '"type": "error"' in body
    assert len(streams) == 1
    assert streams[0].is_alive is False
    assert coordinator.active_job is None
    assert all(not p.exists() for p in created)
    _assert_marker(state, marker)

    source.release.set()
    body = _consume(system_client.post("/api/translate/0", json={}, buffered=False))
    assert '"type": "finish"' in body
    assert 0 in state.translated_pages
    assert "OK4_0" in _pdf_texts(state._right_pdf_path)[0]


# --- (g) single/batch commit failure and recovery ----------------------


def test_single_page_commit_failure_keeps_state_and_recovers(system_app, system_client, tmp_path, monkeypatch):
    state = system_app.config["app_state"]
    coordinator = system_app.config["translation_coordinator"]
    pdf = _make_pdf(tmp_path / "single.pdf", 2, ["S_0", "S_1"])
    _open_document(system_client, pdf)
    translated_0 = _make_translated_pdf(tmp_path / "t0.pdf", ["T0_0"])
    translated_1 = _make_translated_pdf(tmp_path / "t1.pdf", ["T1_0"])

    source = ControlledUpstream(result=FakeTranslateResult(mono_pdf_path=str(translated_0)))
    _install_upstream(monkeypatch, source)
    created = _install_mkdtemp_control(monkeypatch)
    _install_stream_spy(monkeypatch)
    source.release.set()

    body = _consume(system_client.post("/api/translate/0", json={}, buffered=False))
    assert '"type": "finish"' in body
    assert state.translated_pages == frozenset({0})

    source.result = FakeTranslateResult(mono_pdf_path=str(translated_1))
    _fail_os_replace_at(monkeypatch, 1)
    body = _consume(system_client.post("/api/translate/1", json={}, buffered=False))
    assert '"type": "error"' in body
    assert coordinator.active_job is None
    assert state.translated_pages == frozenset({0})
    texts = _pdf_texts(state._right_pdf_path)
    assert "T0_0" in texts[0]
    assert "S_1" in texts[1]
    assert not Path(state._right_pdf_path + ".tmp").exists()
    _assert_renderable(system_client, 2)

    source.release.set()
    body = _consume(system_client.post("/api/translate/1", json={}, buffered=False))
    assert '"type": "finish"' in body
    assert state.translated_pages == frozenset({0, 1})
    texts = _pdf_texts(state._right_pdf_path)
    assert "T1_0" in texts[1]
    _assert_renderable(system_client, 2)
    assert all(not p.exists() for p in created)


def test_batch_commit_failure_keeps_state_and_recovers(system_app, system_client, tmp_path, monkeypatch):
    state = system_app.config["app_state"]
    coordinator = system_app.config["translation_coordinator"]
    pdf = _make_pdf(tmp_path / "batch.pdf", 4, ["B_0", "B_1", "B_2", "B_3"])
    _open_document(system_client, pdf)
    translated_01 = _make_translated_pdf(tmp_path / "b01.pdf", ["TB0_0", "TB1_1"])
    translated_23 = _make_translated_pdf(tmp_path / "b23.pdf", ["TB2_2", "TB3_3"])

    source = ControlledUpstream(result=FakeTranslateResult(mono_pdf_path=str(translated_01)))
    _install_upstream(monkeypatch, source)
    created = _install_mkdtemp_control(monkeypatch)
    _install_stream_spy(monkeypatch)
    source.release.set()

    body = _consume(system_client.post("/api/translate-batch", json={"from": 1, "to": 2}, buffered=False))
    assert '"type": "finish"' in body
    assert state.translated_pages == frozenset({0, 1})

    source.result = FakeTranslateResult(mono_pdf_path=str(translated_23))
    _fail_os_replace_at(monkeypatch, 1)
    body = _consume(system_client.post("/api/translate-batch", json={"from": 3, "to": 4}, buffered=False))
    assert '"type": "error"' in body
    assert coordinator.active_job is None
    assert state.translated_pages == frozenset({0, 1})
    texts = _pdf_texts(state._right_pdf_path)
    assert "TB0_0" in texts[0]
    assert "TB1_1" in texts[1]
    assert "B_2" in texts[2]
    assert "B_3" in texts[3]
    assert not Path(state._right_pdf_path + ".tmp").exists()
    _assert_renderable(system_client, 4)

    source.release.set()
    body = _consume(system_client.post("/api/translate-batch", json={"from": 3, "to": 4}, buffered=False))
    assert '"type": "finish"' in body
    assert state.translated_pages == frozenset({0, 1, 2, 3})
    texts = _pdf_texts(state._right_pdf_path)
    assert "TB2_2" in texts[2]
    assert "TB3_3" in texts[3]
    _assert_renderable(system_client, 4)
    assert all(not p.exists() for p in created)


# --- (h) pinned partial-commit semantics -------------------------------


def test_single_page_pdf_commit_failure_skips_glossary_merge(system_app, system_client, tmp_path, monkeypatch):
    state = system_app.config["app_state"]
    coordinator = system_app.config["translation_coordinator"]
    pdf = _make_pdf(tmp_path / "g.pdf", 2, ["G_0", "G_1"])
    _open_document(system_client, pdf)
    auto = tmp_path / "auto.csv"
    _write_glossary(auto, [("beta", "贝塔")])
    cumulative = state.glossary_cache_path / "cumulative_glossary.csv"
    _write_glossary(cumulative, [("alpha", "阿尔法")])
    cumulative_before = cumulative.read_bytes()
    translated = _make_translated_pdf(tmp_path / "gt.pdf", ["GT_0"])
    source = ControlledUpstream(
        result=FakeTranslateResult(
            mono_pdf_path=str(translated),
            auto_extracted_glossary_path=str(auto),
        )
    )
    _install_upstream(monkeypatch, source)
    created = _install_mkdtemp_control(monkeypatch)
    _fail_os_replace_at(monkeypatch, 1)  # PDF commit is the first os.replace
    marker = _document_marker(state)

    source.release.set()
    body = _consume(system_client.post("/api/translate/0", json={}, buffered=False))
    assert '"type": "error"' in body
    assert coordinator.active_job is None
    assert cumulative.read_bytes() == cumulative_before
    assert _read_glossary(cumulative) == [("alpha", "阿尔法")]
    _assert_marker(state, marker)
    assert not list(state.glossary_cache_path.glob("*.tmp"))
    assert all(not p.exists() for p in created)


def test_single_page_glossary_commit_failure_keeps_pdf_commit_and_finishes(
    system_app, system_client, tmp_path, monkeypatch
):
    state = system_app.config["app_state"]
    coordinator = system_app.config["translation_coordinator"]
    pdf = _make_pdf(tmp_path / "g2.pdf", 2, ["H_0", "H_1"])
    _open_document(system_client, pdf)
    auto = tmp_path / "auto2.csv"
    _write_glossary(auto, [("beta", "贝塔")])
    cumulative = state.glossary_cache_path / "cumulative_glossary.csv"
    _write_glossary(cumulative, [("alpha", "阿尔法")])
    cumulative_before = cumulative.read_bytes()
    translated = _make_translated_pdf(tmp_path / "gt2.pdf", ["HT_0"])
    source = ControlledUpstream(
        result=FakeTranslateResult(
            mono_pdf_path=str(translated),
            auto_extracted_glossary_path=str(auto),
        )
    )
    _install_upstream(monkeypatch, source)
    created = _install_mkdtemp_control(monkeypatch)
    _fail_os_replace_at(monkeypatch, 2)  # PDF commit ok, glossary commit fails

    source.release.set()
    body = _consume(system_client.post("/api/translate/0", json={}, buffered=False))
    assert '"type": "finish"' in body
    assert '"type": "error"' not in body
    assert coordinator.active_job is None
    assert state.translated_pages == frozenset({0})
    assert "HT_0" in _pdf_texts(state._right_pdf_path)[0]
    assert cumulative.read_bytes() == cumulative_before
    assert _read_glossary(cumulative) == [("alpha", "阿尔法")]
    assert not list(state.glossary_cache_path.glob("*.tmp"))
    assert all(not p.exists() for p in created)


def test_batch_pdf_commit_failure_skips_glossary_merge(system_app, system_client, tmp_path, monkeypatch):
    state = system_app.config["app_state"]
    coordinator = system_app.config["translation_coordinator"]
    pdf = _make_pdf(tmp_path / "g3.pdf", 4, ["I_0", "I_1", "I_2", "I_3"])
    _open_document(system_client, pdf)
    auto = tmp_path / "auto3.csv"
    _write_glossary(auto, [("beta", "贝塔")])
    cumulative = state.glossary_cache_path / "cumulative_glossary.csv"
    _write_glossary(cumulative, [("alpha", "阿尔法")])
    cumulative_before = cumulative.read_bytes()
    translated = _make_translated_pdf(tmp_path / "gt3.pdf", ["IT_0", "IT_1"])
    source = ControlledUpstream(
        result=FakeTranslateResult(
            mono_pdf_path=str(translated),
            auto_extracted_glossary_path=str(auto),
        )
    )
    _install_upstream(monkeypatch, source)
    created = _install_mkdtemp_control(monkeypatch)
    _fail_os_replace_at(monkeypatch, 1)
    marker = _document_marker(state)

    source.release.set()
    body = _consume(system_client.post("/api/translate-batch", json={"from": 1, "to": 2}, buffered=False))
    assert '"type": "error"' in body
    assert coordinator.active_job is None
    assert cumulative.read_bytes() == cumulative_before
    assert _read_glossary(cumulative) == [("alpha", "阿尔法")]
    _assert_marker(state, marker)
    assert not list(state.glossary_cache_path.glob("*.tmp"))
    assert all(not p.exists() for p in created)


def test_batch_glossary_commit_failure_keeps_pdf_commit_and_finishes(system_app, system_client, tmp_path, monkeypatch):
    state = system_app.config["app_state"]
    coordinator = system_app.config["translation_coordinator"]
    pdf = _make_pdf(tmp_path / "g4.pdf", 4, ["J_0", "J_1", "J_2", "J_3"])
    _open_document(system_client, pdf)
    auto = tmp_path / "auto4.csv"
    _write_glossary(auto, [("beta", "贝塔")])
    cumulative = state.glossary_cache_path / "cumulative_glossary.csv"
    _write_glossary(cumulative, [("alpha", "阿尔法")])
    cumulative_before = cumulative.read_bytes()
    translated = _make_translated_pdf(tmp_path / "gt4.pdf", ["JT_0", "JT_1"])
    source = ControlledUpstream(
        result=FakeTranslateResult(
            mono_pdf_path=str(translated),
            auto_extracted_glossary_path=str(auto),
        )
    )
    _install_upstream(monkeypatch, source)
    created = _install_mkdtemp_control(monkeypatch)
    _fail_os_replace_at(monkeypatch, 2)

    source.release.set()
    body = _consume(system_client.post("/api/translate-batch", json={"from": 1, "to": 2}, buffered=False))
    assert '"type": "finish"' in body
    assert '"type": "error"' not in body
    assert coordinator.active_job is None
    assert state.translated_pages == frozenset({0, 1})
    texts = _pdf_texts(state._right_pdf_path)
    assert "JT_0" in texts[0]
    assert "JT_1" in texts[1]
    assert cumulative.read_bytes() == cumulative_before
    assert _read_glossary(cumulative) == [("alpha", "阿尔法")]
    assert not list(state.glossary_cache_path.glob("*.tmp"))
    assert all(not p.exists() for p in created)


# --- (i) full open -> translate -> render round trip -------------------


def test_open_translate_render_round_trip(system_app, system_client, tmp_path, monkeypatch):
    state = system_app.config["app_state"]
    coordinator = system_app.config["translation_coordinator"]
    pdf = _make_pdf(tmp_path / "round.pdf", 2, ["SRC_0", "SRC_1"])
    doc = _open_document(system_client, pdf)
    translated = _make_translated_pdf(tmp_path / "round_translated.pdf", ["TRANS_0"])
    auto = tmp_path / "round_auto.csv"
    _write_glossary(auto, [("beta", "贝塔")])
    cumulative = state.glossary_cache_path / "cumulative_glossary.csv"
    _write_glossary(cumulative, [("alpha", "阿尔法")])
    source = ControlledUpstream(
        result=FakeTranslateResult(
            mono_pdf_path=str(translated),
            auto_extracted_glossary_path=str(auto),
        )
    )
    _install_upstream(monkeypatch, source)
    created = _install_mkdtemp_control(monkeypatch)
    streams = _install_stream_spy(monkeypatch)
    source.release.set()

    body = _consume(system_client.post("/api/translate/0", json={"prompt": "round-trip prompt"}, buffered=False))
    assert '"type": "finish"' in body
    assert '"progress": 100' in body
    assert coordinator.active_job is None
    assert len(streams) == 1
    assert streams[0].is_alive is False
    assert state.translation_snapshot().document_id == doc["document_id"]

    texts = _pdf_texts(state._right_pdf_path)
    assert "TRANS_0" in texts[0]
    assert "SRC_1" in texts[1]
    assert state.translated_pages == frozenset({0})

    pages_resp = system_client.get("/api/translated-pages")
    assert pages_resp.get_json() == {"pages": [0]}
    _assert_renderable(system_client, 2)

    rows = _read_glossary(cumulative)
    assert ("alpha", "阿尔法") in rows
    assert ("beta", "贝塔") in rows
    assert not list(state.glossary_cache_path.glob("*.tmp"))
    assert all(not p.exists() for p in created)
