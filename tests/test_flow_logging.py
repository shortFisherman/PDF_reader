"""TDD tests for INFO/ERROR logging in state.py: open_pdf, replace_page, replace_pages, and in translate flow."""

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pdf_reader import debug_trace
from pdf_reader.logging_config import setup_logging
from pdf_reader.pdf_renderer import render_page
from pdf_reader.sse_stream import (
    GenerateBatchContext,
    GenerateContext,
    generate,
    generate_batch,
)
from pdf_reader.state import AppState
from pdf_reader.task_logging import TaskContext
from pdf_reader.translation_orchestrator import TranslationError, run_translation


def test_open_pdf_logs_info_with_hash_and_pages(sample_pdf, tmp_path, caplog):
    """open_pdf 成功后产生 INFO 记录，包含 hash+pages+dim+cache 标记."""
    setup_logging(False)
    caplog.set_level(logging.INFO, logger="pdf_reader.state")

    from pdf_reader.file_hash import sha256

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    state = AppState(cache_dir)
    result = state.open_pdf(str(sample_pdf), sha256)

    records = [r for r in caplog.records if r.name == "pdf_reader.state"]
    assert len(records) >= 1, "expected at least one INFO from open_pdf"
    msg = records[0].message
    assert "hash=" in msg
    assert "pages=" in msg
    assert "dim=" in msg
    assert "cache=" in msg
    assert result["page_count"] == 2


def test_replace_page_logs_info_on_success(app_state, sample_pdf, caplog):
    """replace_page 成功后产生 INFO，含 page 索引与 right.pdf 路径."""
    setup_logging(False)
    caplog.set_level(logging.INFO, logger="pdf_reader.state")

    from pdf_reader.file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    document_id = app_state.translation_snapshot().document_id

    # 构建单页译文 PDF
    import pymupdf

    translated_pdf = Path(sample_pdf).parent / "translated.pdf"
    doc = pymupdf.open()
    doc.new_page(width=612, height=792)
    doc.save(str(translated_pdf))
    doc.close()

    app_state.replace_page(str(translated_pdf), 0, document_id)

    records = [r for r in caplog.records if r.name == "pdf_reader.state" and r.levelno == logging.INFO]
    replace_msgs = [r.message for r in records if "replace" in r.message]
    assert len(replace_msgs) >= 1, f"expected replace INFO, got: {replace_msgs}"
    msg = replace_msgs[0]
    assert "page=" in msg
    assert "0" in msg
    assert "right.pdf" in msg


def test_replace_page_logs_error_and_reraises_on_failure(app_state, sample_pdf, caplog):
    """replace_page 失败时记录 ERROR+exc_info，然后重新抛出异常."""
    setup_logging(False)
    caplog.set_level(logging.INFO, logger="pdf_reader.state")

    from pdf_reader.file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    document_id = app_state.translation_snapshot().document_id

    with pytest.raises(Exception):
        app_state.replace_page("/nonexistent/path/translated.pdf", 0, document_id)

    records = [r for r in caplog.records if r.name == "pdf_reader.state" and r.levelno == logging.ERROR]
    assert len(records) >= 1, f"expected ERROR log, got: {[r.message for r in caplog.records]}"
    assert "page=" in records[0].message
    assert "replace failed" in records[0].message
    assert records[0].exc_info is not None


def test_replace_pages_logs_info_on_success(app_state, sample_pdf, caplog):
    """replace_pages 成功后产生 INFO，含 batch 标记、page_indices 与路径."""
    setup_logging(False)
    caplog.set_level(logging.INFO, logger="pdf_reader.state")

    from pdf_reader.file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    document_id = app_state.translation_snapshot().document_id

    import pymupdf

    translated_pdf = Path(sample_pdf).parent / "translated.pdf"
    doc = pymupdf.open()
    for _ in range(2):
        doc.new_page(width=612, height=792)
    doc.save(str(translated_pdf))
    doc.close()

    app_state.replace_pages(str(translated_pdf), [0, 1], document_id)

    records = [r for r in caplog.records if r.name == "pdf_reader.state" and r.levelno == logging.INFO]
    batch_msgs = [r.message for r in records if "pages=1-2" in r.message and "replace into" in r.message]
    assert len(batch_msgs) >= 1, f"expected batch INFO, got: {batch_msgs}"
    msg = batch_msgs[0]
    assert "pages=1-2" in msg
    assert "right.pdf" in msg


def test_render_page_debug_off_no_output(app_state, sample_pdf, caplog):
    """debug off 时 render_page 不产生 INFO 级别记录."""
    from pdf_reader.file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    caplog.set_level(logging.INFO, logger="pdf_reader.render")

    app_state.render_page("left", 0, render_page, 200)

    records = [r for r in caplog.records if r.name == "pdf_reader.render"]
    assert len(records) == 0, f"expected no INFO from render_page, got: {[r.message for r in records]}"


def test_render_page_debug_on_logs_debug(app_state, sample_pdf, caplog):
    """debug on 时 render_page 产生 DEBUG 记录含 [render] page=N."""
    from pdf_reader.file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    caplog.set_level(logging.DEBUG, logger="pdf_reader.render")

    app_state.render_page("left", 0, render_page, 200)

    records = [r for r in caplog.records if r.name == "pdf_reader.render" and r.levelno == logging.DEBUG]
    assert len(records) >= 1, f"expected DEBUG from render_page, got: {[r.message for r in caplog.records]}"
    msg = records[0].message
    assert "[render]" in msg
    assert "page=0" in msg


def test_replace_pages_logs_error_and_reraises_on_failure(app_state, sample_pdf, caplog):
    """replace_pages 失败时记录 ERROR+exc_info，然后重新抛出异常."""
    setup_logging(False)
    caplog.set_level(logging.INFO, logger="pdf_reader.state")

    from pdf_reader.file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    document_id = app_state.translation_snapshot().document_id

    with pytest.raises(Exception):
        app_state.replace_pages("/nonexistent/path/translated.pdf", [0], document_id)

    records = [r for r in caplog.records if r.name == "pdf_reader.state" and r.levelno == logging.ERROR]
    assert len(records) >= 1, f"expected ERROR log, got: {[r.message for r in caplog.records]}"
    assert "pages=" in records[0].message
    assert "replace pages failed" in records[0].message
    assert records[0].exc_info is not None


# --- translate flow logging ---


def test_translate_thread_lifecycle_logging_debug_off(caplog):
    """debug off: run_translation logs [page=N] thread start, thread end at INFO."""
    setup_logging(False)
    caplog.set_level(logging.INFO, logger="pdf_reader.translate")

    events = [
        {"type": "progress_start", "stage": "layout_analysis"},
        {"type": "finish", "translate_result": MagicMock()},
    ]

    async def fake_stream(settings, file) -> None:
        for evt in events:
            yield evt

    with patch("pdf_reader.translation_orchestrator.do_translate_async_stream", fake_stream):
        list(run_translation(MagicMock(), "fake.pdf", flow_label="page=1"))

    records = [r for r in caplog.records if r.name == "pdf_reader.translate" and r.levelno == logging.INFO]
    messages = [r.message for r in records]
    assert all("[job=test-job]" in msg for msg in messages if "submit translate" in msg or "translate done" in msg)
    assert any("thread start" in msg for msg in messages), f"Got: {messages}"
    assert any("thread end" in msg for msg in messages), f"Got: {messages}"


def test_translate_thread_exception_logging(caplog):
    """run_translation logs ERROR with exc_info on thread exception."""
    setup_logging(False)
    caplog.set_level(logging.INFO, logger="pdf_reader.translate")

    async def failing_stream(settings, file) -> None:
        yield {"type": "progress_start"}
        raise RuntimeError("translation crash")

    with patch("pdf_reader.translation_orchestrator.do_translate_async_stream", failing_stream):
        with pytest.raises(TranslationError, match="translation crash"):
            list(run_translation(MagicMock(), "fake.pdf", flow_label="page=1"))

    records = [r for r in caplog.records if r.name == "pdf_reader.translate" and r.levelno == logging.ERROR]
    assert len(records) >= 1, f"Got: {[r.message for r in caplog.records]}"
    assert "thread exception" in records[0].message
    assert records[0].exc_info is not None


def test_translate_token_usage_not_visible_debug_off(caplog):
    """debug off: debug_trace.log_token_usage logs at DEBUG — not visible at INFO."""
    setup_logging(False)
    caplog.set_level(logging.INFO, logger="pdf_reader.debug_trace")

    debug_trace.log_token_usage({"main": {"total": 100}, "term": {"total": 50}})

    records = [r for r in caplog.records if r.name == "pdf_reader.debug_trace"]
    assert len(records) == 0, f"expected no token_usage log at INFO, got: {[r.message for r in records]}"


def test_translate_token_usage_visible_debug_on(caplog):
    """debug on: debug_trace.log_token_usage logs at DEBUG with token counts."""
    caplog.set_level(logging.DEBUG, logger="pdf_reader.debug_trace")

    debug_trace.log_token_usage({"main": {"total": 100}, "term": {"total": 50}})

    records = [r for r in caplog.records if r.name == "pdf_reader.debug_trace" and r.levelno == logging.DEBUG]
    assert len(records) >= 1, f"expected token_usage log, got: {[r.message for r in records]}"
    msg = records[0].message
    assert "main=100" in msg
    assert "term=50" in msg


# --- sse_stream generate / generate_batch logging ---


def test_generate_logging_info_messages(caplog, tmp_path):
    """generate() produces [page=N] submit, thread start/end, translate done at INFO. Token usage not visible."""
    setup_logging(False)
    caplog.set_level(logging.INFO, logger="pdf_reader.translate")

    mock_result = MagicMock()
    events = [
        {"type": "progress_start", "stage": "layout_analysis"},
        {"type": "finish", "translate_result": mock_result, "token_usage": {"main": {"total": 100}}},
    ]

    async def fake_stream(settings, file) -> None:
        for evt in events:
            yield evt

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    task_ctx = TaskContext(
        job_id="test-job",
        document_id="doc12345678",
        pdf_hash="hash12345678",
        page=1,
        status="started",
    )
    ctx = GenerateContext(
        settings=MagicMock(),
        job_id="test-job",
        finish_job=MagicMock(return_value=True),
        fail_job=MagicMock(return_value=True),
        cancel_job=MagicMock(return_value=True),
        replace_page=MagicMock(),
        merge_glossary=MagicMock(),
        glossary_cache_path=None,
        page=0,
        glossary_paths=None,
        cache_dir=cache_dir,
        extract_page=MagicMock(return_value=Path(tmp_path / "fake_page.pdf")),
        task_ctx=task_ctx,
    )

    with patch("pdf_reader.translation_orchestrator.do_translate_async_stream", fake_stream):
        list(generate(ctx))

    records = [r for r in caplog.records if r.name == "pdf_reader.translate" and r.levelno == logging.INFO]
    messages = [r.message for r in records]
    assert all("job=test-job" in msg for msg in messages if "submit translate" in msg or "translate done" in msg)
    assert any("page=1" in msg and "submit translate" in msg for msg in messages), f"Messages: {messages}"
    assert any("page=1" in msg and "thread start" in msg for msg in messages), f"Messages: {messages}"
    assert any("page=1" in msg and "thread end" in msg for msg in messages), f"Messages: {messages}"
    assert any("translate done" in msg for msg in messages), f"Messages: {messages}"

    token_records = [r for r in caplog.records if r.name == "pdf_reader.debug_trace" and "Token usage" in r.message]
    assert len(token_records) == 0, (
        f"token_usage should not be visible at INFO, got: {[r.message for r in token_records]}"
    )


def test_generate_batch_logging_info_messages(caplog, tmp_path):
    """generate_batch() produces [batch=N-M] submit, thread start/end, translate done at INFO.
    Token usage not visible."""
    setup_logging(False)
    caplog.set_level(logging.INFO, logger="pdf_reader.translate")

    mock_result = MagicMock()
    events = [
        {"type": "progress_start", "stage": "layout_analysis"},
        {"type": "finish", "translate_result": mock_result, "token_usage": {"main": {"total": 200}}},
    ]

    async def fake_stream(settings, file) -> None:
        for evt in events:
            yield evt

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    task_ctx = TaskContext(
        job_id="test-job",
        document_id="doc12345678",
        pdf_hash="hash12345678",
        from_page=2,
        to_page=5,
        status="started",
    )
    ctx = GenerateBatchContext(
        settings=MagicMock(),
        job_id="test-job",
        finish_job=MagicMock(return_value=True),
        fail_job=MagicMock(return_value=True),
        cancel_job=MagicMock(return_value=True),
        from_page=2,
        to_page=5,
        page_indices=[1, 2, 3, 4],
        replace_pages=MagicMock(),
        merge_glossary=MagicMock(),
        glossary_cache_path=None,
        glossary_paths=None,
        cache_dir=cache_dir,
        extract_pages=MagicMock(return_value=Path(tmp_path / "fake_pages.pdf")),
        task_ctx=task_ctx,
    )

    with patch("pdf_reader.translation_orchestrator.do_translate_async_stream", fake_stream):
        list(generate_batch(ctx))

    records = [r for r in caplog.records if r.name == "pdf_reader.translate" and r.levelno == logging.INFO]
    messages = [r.message for r in records]
    assert any("pages=2-5" in msg and "submit translate" in msg for msg in messages), f"Messages: {messages}"
    assert any("pages=2-5" in msg and "thread start" in msg for msg in messages), f"Messages: {messages}"
    assert any("pages=2-5" in msg and "thread end" in msg for msg in messages), f"Messages: {messages}"
    assert any("pages=2-5" in msg and "translate done" in msg for msg in messages), f"Messages: {messages}"

    token_records = [r for r in caplog.records if r.name == "pdf_reader.debug_trace" and "Token usage" in r.message]
    assert len(token_records) == 0, (
        f"token_usage should not be visible at INFO, got: {[r.message for r in token_records]}"
    )


# --- sse_stream error logging ---


def test_generate_error_logging_context(caplog, tmp_path, mock_config):
    """generate() generic error logs ERROR with [page=N], provider, model, lang, tmpdir, exc_info."""
    setup_logging(False)
    caplog.set_level(logging.INFO, logger="pdf_reader.translate")

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    task_ctx = TaskContext(
        job_id="test-job",
        document_id="doc12345678",
        pdf_hash="hash12345678",
        page=8,
        status="started",
    )
    ctx = GenerateContext(
        settings=MagicMock(),
        job_id="test-job",
        finish_job=MagicMock(return_value=True),
        fail_job=MagicMock(return_value=True),
        cancel_job=MagicMock(return_value=True),
        replace_page=MagicMock(),
        merge_glossary=MagicMock(),
        glossary_cache_path=None,
        page=7,
        glossary_paths=None,
        cache_dir=cache_dir,
        extract_page=MagicMock(side_effect=RuntimeError("extract crashed")),
        task_ctx=task_ctx,
    )

    list(generate(ctx))

    records = [r for r in caplog.records if r.name == "pdf_reader.translate" and r.levelno == logging.ERROR]
    assert len(records) == 1, f"expected 1 ERROR, got: {[r.message for r in caplog.records]}"
    msg = records[0].message
    assert "job=test-job" in msg
    assert "page=8" in msg
    assert "status=failed" in msg
    assert "translate failed" in msg
    assert "provider=deepseek" in msg
    assert "model=deepseek-v4-flash" in msg
    assert "lang=en->zh" in msg
    assert "tmpdir=" in msg
    assert records[0].exc_info is not None
    assert "sk-test-key" not in msg


def test_generate_batch_error_logging_context(caplog, tmp_path, mock_config):
    """generate_batch() generic error logs ERROR with [batch=N-M], provider, model, lang, tmpdir, exc_info."""
    setup_logging(False)
    caplog.set_level(logging.INFO, logger="pdf_reader.translate")

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    task_ctx = TaskContext(
        job_id="test-job",
        document_id="doc12345678",
        pdf_hash="hash12345678",
        from_page=4,
        to_page=9,
        status="started",
    )
    ctx = GenerateBatchContext(
        settings=MagicMock(),
        job_id="test-job",
        finish_job=MagicMock(return_value=True),
        fail_job=MagicMock(return_value=True),
        cancel_job=MagicMock(return_value=True),
        from_page=4,
        to_page=9,
        page_indices=[3, 4, 5, 6, 7, 8],
        replace_pages=MagicMock(),
        merge_glossary=MagicMock(),
        glossary_cache_path=None,
        glossary_paths=None,
        cache_dir=cache_dir,
        extract_pages=MagicMock(side_effect=RuntimeError("batch extract crashed")),
        task_ctx=task_ctx,
    )

    list(generate_batch(ctx))

    records = [r for r in caplog.records if r.name == "pdf_reader.translate" and r.levelno == logging.ERROR]
    assert len(records) == 1, f"expected 1 ERROR, got: {[r.message for r in caplog.records]}"
    msg = records[0].message
    assert "job=test-job" in msg
    assert "pages=4-9" in msg
    assert "status=failed" in msg
    assert "translate failed" in msg
    assert "provider=deepseek" in msg
    assert "model=deepseek-v4-flash" in msg
    assert "lang=en->zh" in msg
    assert "tmpdir=" in msg
    assert records[0].exc_info is not None
    assert "sk-test-key" not in msg


def test_generate_error_logging_produces_sse_error_event(caplog, tmp_path, mock_config):
    """generate() generic error still yields an SSE error event after logging."""
    setup_logging(False)
    caplog.set_level(logging.INFO, logger="pdf_reader.translate")

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    ctx = GenerateContext(
        settings=MagicMock(),
        job_id="test-job",
        finish_job=MagicMock(return_value=True),
        fail_job=MagicMock(return_value=True),
        cancel_job=MagicMock(return_value=True),
        replace_page=MagicMock(),
        merge_glossary=MagicMock(),
        glossary_cache_path=None,
        page=1,
        glossary_paths=None,
        cache_dir=cache_dir,
        extract_page=MagicMock(side_effect=RuntimeError("boom")),
    )

    output = list(generate(ctx))

    error_events = [line for line in output if '"type": "error"' in line]
    assert len(error_events) >= 1, f"expected SSE error event, got: {output}"
