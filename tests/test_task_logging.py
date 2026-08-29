"""P2-06 任务级日志上下文、生命周期序列与脱敏测试。"""

import asyncio
import logging
import re
import sys
import threading
from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest

from pdf_reader import logging_config, task_logging
from pdf_reader.state import StaleDocumentError
from pdf_reader.task_logging import (
    TaskContext,
    pages_label,
    redact_secrets,
    task_context_from_indices,
    task_log,
    task_log_context,
    truncate_document_id,
    truncate_pdf_hash,
)
from pdf_reader.translation_coordinator import TranslationCoordinator


@pytest.fixture(autouse=True)
def _reset_task_context() -> Iterator[None]:
    """任务上下文是全局状态；每个测试前后清空，避免跨文件/跨用例泄漏。"""
    task_logging.set_current_task(None)
    yield
    task_logging.set_current_task(None)


def _statuses(caplog) -> list[str]:
    statuses = []
    for record in caplog.records:
        match = re.search(r"status=([a-z_]+)", record.message)
        if match:
            statuses.append(match.group(1))
    return statuses


def _is_subsequence(needle: list[str], haystack: list[str]) -> bool:
    it = iter(haystack)
    return all(item in it for item in needle)


def test_truncation_lengths():
    assert truncate_document_id("a" * 32) == "a" * 8
    assert truncate_pdf_hash("b" * 64) == "b" * 12
    assert truncate_document_id("") == "-"
    assert truncate_pdf_hash("") == "-"


def test_pages_label_formats():
    assert pages_label(TaskContext("j", "d", "h", page=3)) == "page=3"
    assert pages_label(TaskContext("j", "d", "h", from_page=1, to_page=5)) == "pages=1-5"
    assert pages_label(TaskContext("j", "d", "h", from_page=4, to_page=4)) == "pages=4"
    assert pages_label(TaskContext("j", "d", "h")) == ""


def test_task_context_from_indices():
    single = task_context_from_indices("j", "doc-1", "hash-1", [2])
    assert single.page == 3
    assert single.from_page is None
    assert single.document_id == truncate_document_id("doc-1")
    assert single.pdf_hash == truncate_pdf_hash("hash-1")

    batch = task_context_from_indices("j", "doc-1", "hash-1", [0, 1, 2])
    assert batch.from_page == 1
    assert batch.to_page == 3

    empty = task_context_from_indices("j", "doc-1", "hash-1", [])
    assert empty.page is None
    assert pages_label(empty) == ""


def test_task_log_prefix_format(caplog):
    task = TaskContext(
        job_id="job-123456",
        document_id="doc123456",
        pdf_hash="hash12345678",
        page=3,
        status="started",
    )
    with caplog.at_level(logging.INFO, logger="pdf_reader.translate"):
        task_log(logging.getLogger("pdf_reader.translate"), logging.INFO, "hello %s", "world", task=task)
    msg = caplog.records[0].message
    assert msg.startswith("[job=job-123456 doc=doc12345 hash=hash12345678 page=3 status=started] hello world")


def test_task_context_direct_construction_truncated(caplog):
    """直接构造 TaskContext 也必须受中心截断不变量约束。"""
    task = TaskContext(
        job_id="job-long",
        document_id="d" * 40,
        pdf_hash="h" * 80,
        page=1,
        status="started",
    )
    assert len(task.document_id) == 8
    assert len(task.pdf_hash) == 12

    with caplog.at_level(logging.INFO, logger="pdf_reader.translate"):
        task_log(logging.getLogger("pdf_reader.translate"), logging.INFO, "truncated", task=task)
    msg = caplog.records[0].message
    assert f"doc={'d' * 8}" in msg
    assert f"hash={'h' * 12}" in msg
    assert "d" * 9 not in msg
    assert "h" * 13 not in msg


def test_task_log_without_context_is_plain(caplog):
    with caplog.at_level(logging.INFO, logger="pdf_reader.translate"):
        task_log(logging.getLogger("pdf_reader.translate"), logging.INFO, "plain %s", "message")
    assert caplog.records[0].message == "plain message"


def test_task_log_context_manager_sets_and_restores(caplog):
    logger = logging.getLogger("pdf_reader.translate")
    task = TaskContext("job-x", "doc-x", "hash-x", page=1, status="started")
    with task_log_context(task):
        assert task_logging.get_current_task() is task
        with caplog.at_level(logging.INFO, logger="pdf_reader.translate"):
            task_log(logger, logging.INFO, "inside")
    assert task_logging.get_current_task() is None
    assert "job=job-x" in caplog.records[0].message


def test_task_context_propagates_to_worker_thread(caplog):
    task = TaskContext("job-thread", "doc-thread", "hash-thread", page=2, status="started")

    def worker() -> None:
        task_logging.set_current_task(task)
        task_log(logging.getLogger("pdf_reader.translate"), logging.INFO, "worker message")

    with caplog.at_level(logging.INFO, logger="pdf_reader.translate"):
        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()

    assert any("job=job-thread" in r.message and "worker message" in r.message for r in caplog.records)


def test_translation_stream_worker_uses_task_context(caplog):
    from pdf_reader.translation_orchestrator import run_translation

    task = TaskContext("job-w", "doc-w", "hash-w", page=1, status="started")

    async def fake_stream(settings, file) -> None:
        yield {"type": "progress_start"}
        yield {"type": "finish", "translate_result": MagicMock()}

    with patch("pdf_reader.translation_orchestrator.do_translate_async_stream", fake_stream):
        with caplog.at_level(logging.INFO, logger="pdf_reader.translate"):
            list(run_translation(MagicMock(), "fake.pdf", flow_label="x", task_ctx=task))

    messages = [r.message for r in caplog.records]
    assert any("job=job-w" in m and "thread start" in m for m in messages)
    assert any("job=job-w" in m and "thread end" in m for m in messages)


def test_redact_secrets_common_tokens(monkeypatch):
    monkeypatch.setattr("pdf_reader.config.MODEL_API_KEY", "sk-configured-secret")
    text = (
        "api_key=sk-raw-value Authorization: Bearer abcdef123 "
        '"api_key": "json-secret" "Authorization": "Bearer json-bearer" '
        "Bearer test-standalone-token-123 "
        "sk-secret-123 C:\\Users\\priv /home/user <img src=x onerror=alert(1)> "
        "Bearer of good news and api_key field without colon"
    )
    redacted = redact_secrets(text)
    for secret in (
        "sk-configured-secret",
        "sk-raw-value",
        "sk-secret-123",
        "abcdef123",
        "json-secret",
        "json-bearer",
        "standalone-token-123",
    ):
        assert secret not in redacted
    assert '"api_key": "<redacted>"' in redacted
    assert '"Authorization": "Bearer <redacted>"' in redacted
    assert "Authorization: Bearer <redacted>" in redacted
    assert "Bearer <redacted>" in redacted
    assert "***REDACTED***" in redacted
    assert "C:\\Users\\priv" in redacted
    assert "/home/user" in redacted
    assert "onerror" in redacted
    assert "Bearer of good news" in redacted
    assert "api_key field without colon" in redacted


def test_safe_formatter_redacts_message_and_traceback():
    formatter = task_logging.SafeFormatter("%(message)s")
    try:
        raise RuntimeError("sk-secret-999")
    except RuntimeError:
        record = logging.LogRecord(
            "pdf_reader.app",
            logging.ERROR,
            __file__,
            1,
            "boom %s",
            ("sk-secret-999",),
            sys.exc_info(),
        )
    output = formatter.format(record)
    assert "sk-secret-999" not in output
    assert "Traceback" in output
    assert "RuntimeError" in output
    assert "***REDACTED***" in output


def test_rotating_file_handler_redacts_on_disk(monkeypatch, tmp_path, capsys):
    logging_config.reset_logging()
    log_dir = tmp_path / "logs"
    monkeypatch.setattr(logging_config, "LOG_DIR", log_dir)
    logging_config.setup_logging(False)

    logger = logging.getLogger("pdf_reader.app")
    sentinel = (
        "sk-secret-123 Authorization: Bearer abcdef123 api_key=mykey "
        '"api_key": "json-secret" "Authorization": "Bearer json-bearer" '
        "Bearer test-standalone-token-123 "
        "<img src=x onerror=alert(1)> C:\\Users\\priv /home/user"
    )
    try:
        raise RuntimeError(sentinel)
    except RuntimeError:
        logger.error("task failed with %s", sentinel, exc_info=True)

    content = (log_dir / "pdf_reader.log").read_text(encoding="utf-8")
    assert "sk-secret-123" not in content
    assert "abcdef123" not in content
    assert "mykey" not in content
    assert "json-secret" not in content
    assert "json-bearer" not in content
    assert "standalone-token-123" not in content
    assert "***REDACTED***" in content
    assert '"api_key": "<redacted>"' in content
    assert '"Authorization": "Bearer <redacted>"' in content
    assert "Bearer <redacted>" in content
    assert "Traceback" in content
    assert "RuntimeError" in content
    assert "C:\\Users\\priv" in content
    assert "/home/user" in content

    console = capsys.readouterr().out
    assert "sk-secret-123" not in console
    assert "***REDACTED***" in console
    logging_config.reset_logging()


def test_safe_rmtree_returns_verifiable_result(tmp_path):
    from pdf_reader.sse_stream import _safe_rmtree

    missing = tmp_path / "missing"
    assert _safe_rmtree(missing) is True

    existing = tmp_path / "existing"
    existing.mkdir()
    assert _safe_rmtree(existing) is True
    assert not existing.exists()

    stubborn = tmp_path / "stubborn"
    stubborn.mkdir()
    with patch("pdf_reader.sse_stream.shutil.rmtree", side_effect=OSError("boom")):
        assert _safe_rmtree(stubborn) is False
    assert stubborn.exists()


def test_single_cleanup_failure_records_cleanup_deferred(caplog, tmp_path):
    from pdf_reader.sse_stream import GenerateContext, generate

    coordinator = TranslationCoordinator()
    job = coordinator.start("doc-1234567890", [0], pdf_hash="hash-abcdef")
    task_ctx = task_context_from_indices(job.job_id, job.document_id, job.pdf_hash or "", [0])
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = MagicMock()
    result.mono_pdf_path = str(tmp_path / "t.pdf")
    result.dual_pdf_path = None
    result.auto_extracted_glossary_path = None
    ctx = GenerateContext(
        settings=MagicMock(),
        job_id=job.job_id,
        finish_job=coordinator.finish,
        fail_job=coordinator.fail,
        cancel_job=coordinator.cancel,
        replace_page=MagicMock(),
        merge_glossary=MagicMock(),
        glossary_cache_path=None,
        page=0,
        glossary_paths=None,
        cache_dir=cache_dir,
        extract_page=MagicMock(return_value=tmp_path / "page.pdf"),
        task_ctx=task_ctx,
    )

    with patch("pdf_reader.cache_ops.tempfile.mkdtemp", return_value=str(workspace)):
        with patch(
            "pdf_reader.sse_stream.run_translation",
            return_value=iter([{"type": "finish", "translate_result": result}]),
        ):
            with patch("pdf_reader.sse_stream.debug_trace"):
                with patch("pdf_reader.sse_stream.shutil.rmtree", side_effect=OSError("boom")):
                    with caplog.at_level(logging.INFO, logger="pdf_reader"):
                        list(generate(ctx))

    statuses = _statuses(caplog)
    assert "cleanup_deferred" in statuses
    assert "cleaned" not in statuses
    warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("cleanup deferred" in w and "status=cleanup_deferred" in w for w in warnings)


def test_batch_cleanup_failure_records_cleanup_deferred(caplog, tmp_path):
    from pdf_reader.sse_stream import GenerateBatchContext, generate_batch

    coordinator = TranslationCoordinator()
    job = coordinator.start("doc-1234567890", [1, 2], pdf_hash="hash-abcdef")
    task_ctx = task_context_from_indices(job.job_id, job.document_id, job.pdf_hash or "", [1, 2])
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    ctx = GenerateBatchContext(
        settings=MagicMock(),
        job_id=job.job_id,
        finish_job=coordinator.finish,
        fail_job=coordinator.fail,
        cancel_job=coordinator.cancel,
        from_page=2,
        to_page=3,
        page_indices=[1, 2],
        replace_pages=MagicMock(),
        merge_glossary=MagicMock(),
        glossary_cache_path=None,
        glossary_paths=None,
        cache_dir=cache_dir,
        extract_pages=MagicMock(return_value=tmp_path / "pages.pdf"),
        task_ctx=task_ctx,
    )

    with patch("pdf_reader.cache_ops.tempfile.mkdtemp", return_value=str(workspace)):
        with patch(
            "pdf_reader.sse_stream.run_translation",
            return_value=iter(
                [{"type": "finish", "translate_result": MagicMock(mono_pdf_path=str(tmp_path / "t.pdf"))}]
            ),
        ):
            with patch("pdf_reader.sse_stream.debug_trace"):
                with patch("pdf_reader.sse_stream.shutil.rmtree", side_effect=OSError("boom")):
                    with caplog.at_level(logging.INFO, logger="pdf_reader"):
                        list(generate_batch(ctx))

    statuses = _statuses(caplog)
    assert "cleanup_deferred" in statuses
    assert "cleaned" not in statuses
    warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("cleanup deferred" in w and "status=cleanup_deferred" in w for w in warnings)


def test_success_lifecycle_status_sequence(caplog, tmp_path):
    from pdf_reader.sse_stream import GenerateContext, generate

    coordinator = TranslationCoordinator()
    job = coordinator.start("doc-1234567890", [0], pdf_hash="hash-abcdef")
    task_ctx = task_context_from_indices(job.job_id, job.document_id, job.pdf_hash or "", [0])

    result = MagicMock()
    result.mono_pdf_path = str(tmp_path / "t.pdf")
    result.dual_pdf_path = None
    result.auto_extracted_glossary_path = None
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    ctx = GenerateContext(
        settings=MagicMock(),
        job_id=job.job_id,
        finish_job=coordinator.finish,
        fail_job=coordinator.fail,
        cancel_job=coordinator.cancel,
        replace_page=MagicMock(),
        merge_glossary=MagicMock(),
        glossary_cache_path=None,
        page=0,
        glossary_paths=None,
        cache_dir=cache_dir,
        extract_page=MagicMock(return_value=tmp_path / "page.pdf"),
        task_ctx=task_ctx,
    )

    with patch(
        "pdf_reader.sse_stream.run_translation",
        return_value=iter([{"type": "finish", "translate_result": result}]),
    ):
        with patch("pdf_reader.sse_stream.debug_trace"):
            with caplog.at_level(logging.INFO, logger="pdf_reader"):
                list(generate(ctx))

    statuses = _statuses(caplog)
    assert _is_subsequence(["created", "started", "finished", "cleaned"], statuses)


def test_failed_lifecycle_status_sequence(caplog, tmp_path):
    from pdf_reader.sse_stream import GenerateContext, generate

    coordinator = TranslationCoordinator()
    job = coordinator.start("doc-1234567890", [0], pdf_hash="hash-abcdef")
    task_ctx = task_context_from_indices(job.job_id, job.document_id, job.pdf_hash or "", [0])
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    ctx = GenerateContext(
        settings=MagicMock(),
        job_id=job.job_id,
        finish_job=coordinator.finish,
        fail_job=coordinator.fail,
        cancel_job=coordinator.cancel,
        replace_page=MagicMock(),
        merge_glossary=MagicMock(),
        glossary_cache_path=None,
        page=0,
        glossary_paths=None,
        cache_dir=cache_dir,
        extract_page=MagicMock(side_effect=RuntimeError("boom")),
        task_ctx=task_ctx,
    )

    with patch("pdf_reader.sse_stream.run_translation"):
        with patch("pdf_reader.sse_stream.debug_trace"):
            with caplog.at_level(logging.INFO, logger="pdf_reader"):
                list(generate(ctx))

    statuses = _statuses(caplog)
    assert _is_subsequence(["created", "started", "failed", "cleaned"], statuses)


def test_batch_failed_lifecycle_status_sequence(caplog, tmp_path):
    from pdf_reader.sse_stream import GenerateBatchContext, generate_batch

    coordinator = TranslationCoordinator()
    job = coordinator.start("doc-1234567890", [1, 2, 3, 4], pdf_hash="hash-abcdef")
    task_ctx = task_context_from_indices(job.job_id, job.document_id, job.pdf_hash or "", [1, 2, 3, 4])
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    ctx = GenerateBatchContext(
        settings=MagicMock(),
        job_id=job.job_id,
        finish_job=coordinator.finish,
        fail_job=coordinator.fail,
        cancel_job=coordinator.cancel,
        from_page=2,
        to_page=5,
        page_indices=[1, 2, 3, 4],
        replace_pages=MagicMock(),
        merge_glossary=MagicMock(),
        glossary_cache_path=None,
        glossary_paths=None,
        cache_dir=cache_dir,
        extract_pages=MagicMock(side_effect=RuntimeError("batch boom")),
        task_ctx=task_ctx,
    )

    with patch("pdf_reader.sse_stream.run_translation"):
        with patch("pdf_reader.sse_stream.debug_trace"):
            with caplog.at_level(logging.INFO, logger="pdf_reader"):
                list(generate_batch(ctx))

    statuses = _statuses(caplog)
    assert _is_subsequence(["created", "started", "failed", "cleaned"], statuses)
    messages = [r.message for r in caplog.records]
    assert any("pages=2-5" in m and "status=failed" in m for m in messages)


def test_disconnect_late_discard_lifecycle_sequence(caplog, tmp_path):
    from pdf_reader.sse_stream import GenerateContext, generate

    coordinator = TranslationCoordinator()
    job = coordinator.start("doc-1234567890", [0], pdf_hash="hash-abcdef")
    task_ctx = task_context_from_indices(job.job_id, job.document_id, job.pdf_hash or "", [0])
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    ctx = GenerateContext(
        settings=MagicMock(),
        job_id=job.job_id,
        finish_job=coordinator.finish,
        fail_job=coordinator.fail,
        cancel_job=coordinator.cancel,
        replace_page=MagicMock(),
        merge_glossary=MagicMock(),
        glossary_cache_path=None,
        page=0,
        glossary_paths=None,
        cache_dir=cache_dir,
        extract_page=MagicMock(return_value=tmp_path / "page.pdf"),
        task_ctx=task_ctx,
    )

    async def slow_source(settings, file) -> None:
        yield {"type": "progress_start", "stage": "layout_analysis"}
        await asyncio.sleep(0.3)
        yield {"type": "finish", "translate_result": MagicMock()}

    with patch("pdf_reader.translation_orchestrator.do_translate_async_stream", slow_source):
        with patch("pdf_reader.sse_stream.debug_trace"):
            with caplog.at_level(logging.INFO, logger="pdf_reader"):
                gen = generate(ctx)
                next(gen)
                gen.close()

    statuses = _statuses(caplog)
    assert _is_subsequence(
        ["client_disconnected", "cancelling", "discarded", "cleaned"],
        statuses,
    )


def test_join_timeout_cleanup_deferred(caplog, tmp_path):
    from pdf_reader.sse_stream import GenerateContext, generate

    coordinator = TranslationCoordinator()
    job = coordinator.start("doc-1234567890", [0], pdf_hash="hash-abcdef")
    task_ctx = task_context_from_indices(job.job_id, job.document_id, job.pdf_hash or "", [0])
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    ctx = GenerateContext(
        settings=MagicMock(),
        job_id=job.job_id,
        finish_job=coordinator.finish,
        fail_job=coordinator.fail,
        cancel_job=coordinator.cancel,
        replace_page=MagicMock(),
        merge_glossary=MagicMock(),
        glossary_cache_path=None,
        page=0,
        glossary_paths=None,
        cache_dir=cache_dir,
        extract_page=MagicMock(return_value=tmp_path / "page.pdf"),
        task_ctx=task_ctx,
    )

    async def stuck_source(settings, file) -> None:
        yield {"type": "progress_start", "stage": "layout_analysis"}
        await asyncio.sleep(3600)

    with patch("pdf_reader.translation_orchestrator.do_translate_async_stream", stuck_source):
        with patch("pdf_reader.sse_stream.WORKER_JOIN_TIMEOUT", 0.2):
            with patch("pdf_reader.sse_stream.debug_trace"):
                with caplog.at_level(logging.INFO, logger="pdf_reader"):
                    gen = generate(ctx)
                    next(gen)
                    gen.close()

    statuses = _statuses(caplog)
    assert _is_subsequence(["client_disconnected", "cancelling", "cleanup_deferred"], statuses)
    assert "cleaned" not in statuses
    warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("cleanup_deferred" in w and "job=" in w for w in warnings)


def test_stale_release_does_not_emit_half_baked_task_log(caplog):
    coordinator = TranslationCoordinator()
    job = coordinator.start("doc-1234567890", [0], pdf_hash="hash-abcdef")
    coordinator.finish(job.job_id)

    with caplog.at_level(logging.DEBUG, logger="pdf_reader.translate"):
        before = len(caplog.records)
        assert coordinator.finish(job.job_id) is False
        assert len(caplog.records) == before


def test_stale_result_rejection_carries_task_context(app_state, sample_pdf, caplog):
    from pdf_reader.file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    snapshot = app_state.translation_snapshot()
    task_ctx = TaskContext(
        job_id="job-stale",
        document_id=truncate_document_id(snapshot.document_id),
        pdf_hash=truncate_pdf_hash(snapshot.pdf_hash),
        page=1,
        status="started",
    )
    with task_log_context(task_ctx):
        with caplog.at_level(logging.WARNING, logger="pdf_reader.state"):
            with pytest.raises(StaleDocumentError):
                app_state.replace_page(str(sample_pdf), 0, "wrong-document-id")

    messages = [r.message for r in caplog.records]
    assert any("job=job-stale" in m and "status=discarded" in m and "[stale-result]" in m for m in messages)


def test_replace_failure_carries_task_context(app_state, sample_pdf, caplog):
    from pdf_reader.file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    snapshot = app_state.translation_snapshot()
    task_ctx = TaskContext(
        job_id="job-replace",
        document_id=truncate_document_id(snapshot.document_id),
        pdf_hash=truncate_pdf_hash(snapshot.pdf_hash),
        page=1,
        status="started",
    )
    with task_log_context(task_ctx):
        with caplog.at_level(logging.ERROR, logger="pdf_reader.state"):
            with pytest.raises(Exception):
                app_state.replace_page("/nonexistent/path/translated.pdf", 0, snapshot.document_id)

    messages = [r.message for r in caplog.records]
    assert any("job=job-replace" in m and "status=started" in m and "replace failed" in m for m in messages)
