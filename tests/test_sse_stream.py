import asyncio
import csv
import json
import logging
import tempfile
import threading
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pdf_reader import cache_ops
from pdf_reader.glossary_service import merge_after_translate
from pdf_reader.sse_stream import (
    MAXIMUM_UPSTREAM_ERROR_ITEMS,
    MODEL_DOWNLOAD_FAILED_CODE,
    MODEL_DOWNLOAD_FAILED_MESSAGE,
    GenerateBatchContext,
    GenerateContext,
    classify_upstream_error,
    format_batch_info,
    format_sse_event,
    generate,
    generate_batch,
)

# --- Gold-standard SSE constants (preserved from original) ---
EXPECTED_PROGRESS_START_SSE = (
    "data: "
    + json.dumps(
        {
            "type": "progress",
            "progress": 0,
            "stage": "layout_analysis",
            "stage_current": 0,
            "stage_total": 0,
        }
    )
    + "\n\n"
)

EXPECTED_PROGRESS_UPDATE_SSE = (
    "data: "
    + json.dumps(
        {
            "type": "progress",
            "progress": 50,
            "stage": "translating",
            "stage_current": 2,
            "stage_total": 5,
        }
    )
    + "\n\n"
)

EXPECTED_FINISH_PROGRESS_SSE = (
    "data: "
    + json.dumps(
        {
            "type": "progress",
            "progress": 95,
            "stage": "generating_pdf",
            "stage_current": 0,
            "stage_total": 0,
        }
    )
    + "\n\n"
)

EXPECTED_ERROR_SSE = (
    "data: " + json.dumps({"type": "error", "code": "translation_error", "error": "上游翻译失败"}) + "\n\n"
)

EXPECTED_FINAL_PROGRESS_SSE = (
    "data: "
    + json.dumps(
        {
            "type": "progress",
            "progress": 100,
            "stage": "finish",
            "stage_current": 0,
            "stage_total": 0,
        }
    )
    + "\n\n"
)

EXPECTED_FINAL_FINISH_SSE = "data: " + json.dumps({"type": "finish", "progress": 100}) + "\n\n"


def _make_ctx(
    settings=None,
    job_id="test-job",
    finish_job=None,
    fail_job=None,
    cancel_job=None,
    replace_page=None,
    merge_glossary=None,
    glossary_cache_path=None,
    page=0,
    glossary_paths=None,
    cache_dir=None,
    extract_page=None,
) -> GenerateContext:
    if settings is None:
        settings = MagicMock()
    if finish_job is None:
        finish_job = MagicMock(return_value=True)
    if fail_job is None:
        fail_job = MagicMock(return_value=True)
    if cancel_job is None:
        cancel_job = MagicMock(return_value=True)
    if replace_page is None:
        replace_page = MagicMock()
    if merge_glossary is None:
        merge_glossary = MagicMock()
    if cache_dir is None:
        cache_dir = Path(tempfile.mkdtemp())
    if extract_page is None:
        extract_page = MagicMock(return_value=Path("/fake/page.pdf"))
    return GenerateContext(
        settings=settings,
        job_id=job_id,
        finish_job=finish_job,
        fail_job=fail_job,
        cancel_job=cancel_job,
        replace_page=replace_page,
        merge_glossary=merge_glossary,
        glossary_cache_path=glossary_cache_path,
        page=page,
        glossary_paths=glossary_paths,
        cache_dir=cache_dir,
        extract_page=extract_page,
    )


# --- Golden sample tests ---


def test_golden_sample_progress_start():
    assert EXPECTED_PROGRESS_START_SSE == (
        'data: {"type": "progress", "progress": 0, "stage": "layout_analysis", '
        '"stage_current": 0, "stage_total": 0}\n\n'
    )


def test_golden_sample_progress_update():
    assert EXPECTED_PROGRESS_UPDATE_SSE == (
        'data: {"type": "progress", "progress": 50, "stage": "translating", "stage_current": 2, "stage_total": 5}\n\n'
    )


def test_golden_sample_error():
    assert EXPECTED_ERROR_SSE == (
        "data: " + json.dumps({"type": "error", "code": "translation_error", "error": "上游翻译失败"}) + "\n\n"
    )


# --- format_sse_event tests ---


def test_format_sse_event_progress_start():
    evt = {
        "type": "progress_start",
        "stage": "layout_analysis",
        "overall_progress": 0,
        "stage_current": 0,
        "stage_total": 0,
    }
    assert format_sse_event(evt) == EXPECTED_PROGRESS_START_SSE


def test_format_sse_event_progress_update():
    evt = {
        "type": "progress_update",
        "stage": "translating",
        "overall_progress": 50,
        "stage_current": 2,
        "stage_total": 5,
    }
    assert format_sse_event(evt) == EXPECTED_PROGRESS_UPDATE_SSE


def test_format_sse_event_finish():
    evt = {
        "type": "finish",
        "stage": "generating_pdf",
        "translate_result": None,
        "token_usage": {},
    }
    assert format_sse_event(evt) == EXPECTED_FINISH_PROGRESS_SSE


def test_format_sse_event_finish_without_min_progress_keeps_old_95_bytes():
    evt = {"type": "finish", "stage": "generating_pdf", "translate_result": None, "token_usage": {}}
    assert format_sse_event(evt) == EXPECTED_FINISH_PROGRESS_SSE
    assert '"progress": 95' in format_sse_event(evt)


def test_format_sse_event_attempt1_window_clamps_to_0_95():
    start = format_sse_event(
        {
            "type": "progress_start",
            "stage": "layout_analysis",
            "overall_progress": 0,
            "stage_current": 0,
            "stage_total": 0,
        },
        min_progress=0,
        max_progress=95,
    )
    update = format_sse_event(
        {
            "type": "progress_update",
            "stage": "translating",
            "overall_progress": 100,
            "stage_current": 1,
            "stage_total": 2,
        },
        min_progress=0,
        max_progress=95,
    )
    finish = format_sse_event(
        {"type": "finish", "stage": "generating_pdf", "translate_result": None, "token_usage": {}},
        min_progress=0,
        max_progress=95,
    )
    assert '"progress": 0' in start
    assert '"progress": 95' in update
    assert '"progress": 95' in finish
    assert '"stage": "generating_pdf"' in finish


def test_format_sse_event_attempt2_window_clamps_to_95_99():
    start = format_sse_event(
        {
            "type": "progress_start",
            "stage": "layout_analysis",
            "overall_progress": 0,
            "stage_current": 0,
            "stage_total": 0,
        },
        min_progress=95,
        max_progress=99,
    )
    update = format_sse_event(
        {
            "type": "progress_update",
            "stage": "translating",
            "overall_progress": 100,
            "stage_current": 1,
            "stage_total": 2,
        },
        min_progress=95,
        max_progress=99,
    )
    finish = format_sse_event(
        {"type": "finish", "stage": "generating_pdf", "translate_result": None, "token_usage": {}},
        min_progress=95,
        max_progress=99,
    )
    assert '"progress": 95' in start
    assert '"progress": 99' in update
    assert '"progress": 99' in finish
    assert '"stage": "generating_pdf"' in finish


def test_format_sse_event_without_min_progress_preserves_raw_update():
    evt = {
        "type": "progress_update",
        "stage": "translating",
        "overall_progress": 100,
        "stage_current": 1,
        "stage_total": 2,
    }
    assert '"progress": 100' in format_sse_event(evt)


def test_format_sse_event_error():
    evt = {"type": "error", "error": "test error"}
    assert format_sse_event(evt) == EXPECTED_ERROR_SSE


def test_format_sse_event_internal_done_returns_none():
    evt = {"type": "_done"}
    assert format_sse_event(evt) is None


def test_format_sse_event_unknown_type_returns_none():
    evt = {"type": "unknown_type"}
    assert format_sse_event(evt) is None


# --- generate() full-flow and error tests ---


def test_generate_full_flow_byte_level_compatible(tmp_path):
    mock_result = MagicMock()
    mock_result.mono_pdf_path = str(tmp_path / "translated.pdf")
    mock_result.dual_pdf_path = None
    mock_result.auto_extracted_glossary_path = None

    events = [
        {
            "type": "progress_start",
            "stage": "layout_analysis",
            "overall_progress": 0,
            "stage_current": 0,
            "stage_total": 0,
        },
        {
            "type": "progress_update",
            "stage": "translating",
            "overall_progress": 50,
            "stage_current": 2,
            "stage_total": 5,
        },
        {"type": "finish", "stage": "generating_pdf", "translate_result": mock_result, "token_usage": {}},
    ]

    replace_page = MagicMock()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    ctx = _make_ctx(
        settings=MagicMock(),
        replace_page=replace_page,
        cache_dir=cache_dir,
    )

    with patch("pdf_reader.sse_stream.run_translation", return_value=iter(events)):
        with patch("pdf_reader.sse_stream.debug_trace"):
            result = list(generate(ctx))

    expected = [
        EXPECTED_PROGRESS_START_SSE,
        EXPECTED_PROGRESS_UPDATE_SSE,
        EXPECTED_FINISH_PROGRESS_SSE,
        EXPECTED_FINAL_PROGRESS_SSE,
        EXPECTED_FINAL_FINISH_SSE,
    ]
    assert result == expected
    replace_page.assert_called_once_with(str(tmp_path / "translated.pdf"))


def test_generate_error_event_stops_stream(tmp_path):
    events = [
        {"type": "progress_start", "stage": "layout_analysis"},
        {"type": "error", "error": "test error"},
    ]

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    ctx = _make_ctx(
        settings=MagicMock(),
        cache_dir=cache_dir,
    )

    with patch("pdf_reader.sse_stream.run_translation", return_value=iter(events)):
        with patch("pdf_reader.sse_stream.debug_trace"):
            result = list(generate(ctx))

    assert len(result) == 2
    assert result[0] == EXPECTED_PROGRESS_START_SSE
    assert result[1] == EXPECTED_ERROR_SSE


def test_generate_translation_error_yields_error_event(tmp_path, caplog):
    from pdf_reader.translation_orchestrator import TranslationError

    events = [{"type": "progress_start", "stage": "layout_analysis"}]

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    ctx = _make_ctx(
        settings=MagicMock(),
        cache_dir=cache_dir,
    )

    def error_iter() -> Iterator[dict]:
        yield from events
        raise TranslationError("thread crashed")

    with patch("pdf_reader.sse_stream.run_translation", return_value=error_iter()):
        with patch("pdf_reader.sse_stream.debug_trace"):
            with caplog.at_level("WARNING", logger="pdf_reader.translate"):
                result = list(generate(ctx))

    assert len(result) == 2
    assert result[0] == EXPECTED_PROGRESS_START_SSE
    assert result[1] == EXPECTED_ERROR_SSE
    assert "thread crashed" not in result[1]
    assert "thread crashed" in caplog.text


def test_generate_merges_glossary_with_str_auto_path(tmp_path):
    glossary_cache = tmp_path / "cache"
    glossary_cache.mkdir()
    cumulative_file = glossary_cache / "cumulative_glossary.csv"
    with open(cumulative_file, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["source", "target"])
        w.writerow(["alpha", "\u963f\u5c14\u6cd5"])

    auto_file = glossary_cache / "auto_extracted.csv"
    with open(auto_file, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["source", "target"])
        w.writerow(["beta", "\u8d1d\u5854"])

    mock_result = MagicMock()
    mock_result.mono_pdf_path = str(tmp_path / "translated.pdf")
    mock_result.dual_pdf_path = None
    mock_result.auto_extracted_glossary_path = str(auto_file)

    events = [
        {
            "type": "progress_start",
            "stage": "layout_analysis",
            "overall_progress": 0,
            "stage_current": 0,
            "stage_total": 0,
        },
        {"type": "finish", "stage": "generating_pdf", "translate_result": mock_result, "token_usage": {}},
    ]

    replace_page = MagicMock()
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    ctx = _make_ctx(
        settings=MagicMock(),
        replace_page=replace_page,
        merge_glossary=lambda auto_path: merge_after_translate(cumulative_file, auto_path),
        glossary_cache_path=glossary_cache,
        cache_dir=work_dir,
    )

    with patch("pdf_reader.sse_stream.run_translation", return_value=iter(events)):
        with patch("pdf_reader.sse_stream.debug_trace"):
            list(generate(ctx))

    with open(cumulative_file, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = {row["source"]: row["target"] for row in reader}

    assert rows.get("alpha") == "\u963f\u5c14\u6cd5"
    assert rows.get("beta") == "\u8d1d\u5854"


def test_generate_passes_through_keepalive_empty_string(tmp_path):
    mock_result = MagicMock()
    mock_result.mono_pdf_path = str(tmp_path / "translated.pdf")
    mock_result.dual_pdf_path = None
    mock_result.auto_extracted_glossary_path = None

    events = [
        "",
        {"type": "finish", "stage": "generating_pdf", "translate_result": mock_result, "token_usage": {}},
    ]

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    ctx = _make_ctx(
        settings=MagicMock(),
        cache_dir=cache_dir,
    )

    with patch("pdf_reader.sse_stream.run_translation", return_value=iter(events)):
        with patch("pdf_reader.sse_stream.debug_trace"):
            result = list(generate(ctx))

    assert result[0] == ""


# --- Cleanup tests ---


def test_generate_cleans_up_on_error_event(tmp_path):
    """3.1: error event early exit -> owned workspace (input/output/marker) removed"""
    events = [{"type": "error", "error": "test error"}]

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    ctx = _make_ctx(cache_dir=cache_dir)

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with patch("pdf_reader.cache_ops.tempfile.mkdtemp", return_value=str(workspace)):
        with patch("pdf_reader.sse_stream.run_translation", return_value=iter(events)):
            with patch("pdf_reader.sse_stream.debug_trace"):
                list(generate(ctx))

    assert not workspace.exists()


def test_generate_cleans_up_on_no_translate_result(tmp_path):
    """3.2: no translate_result early exit -> owned workspace removed"""
    events = [{"type": "progress_start", "stage": "layout_analysis"}]

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    ctx = _make_ctx(cache_dir=cache_dir)

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with patch("pdf_reader.cache_ops.tempfile.mkdtemp", return_value=str(workspace)):
        with patch("pdf_reader.sse_stream.run_translation", return_value=iter(events)):
            with patch("pdf_reader.sse_stream.debug_trace"):
                list(generate(ctx))

    assert not workspace.exists()


def test_generate_cleans_up_on_generator_close(tmp_path):
    """3.3: gen.close() -> GeneratorExit -> workspace removed, job released as cancelled"""
    events = [
        {
            "type": "progress_start",
            "stage": "layout_analysis",
            "overall_progress": 0,
            "stage_current": 0,
            "stage_total": 0,
        },
    ]

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    fail_job = MagicMock(return_value=True)
    cancel_job = MagicMock(return_value=True)
    ctx = _make_ctx(
        job_id="job-disconnect",
        fail_job=fail_job,
        cancel_job=cancel_job,
        cache_dir=cache_dir,
    )

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with patch("pdf_reader.cache_ops.tempfile.mkdtemp", return_value=str(workspace)):
        with patch("pdf_reader.sse_stream.run_translation", return_value=iter(events)):
            with patch("pdf_reader.sse_stream.debug_trace"):
                gen = generate(ctx)
                next(gen)
                gen.close()

    assert not workspace.exists()
    cancel_job.assert_called_once_with("job-disconnect")
    fail_job.assert_not_called()


def test_generate_cleans_up_on_success(tmp_path):
    """3.4: success path -> workspace removed exactly once"""
    mock_result = MagicMock()
    mock_result.mono_pdf_path = str(tmp_path / "translated.pdf")
    mock_result.dual_pdf_path = None
    mock_result.auto_extracted_glossary_path = None

    events = [{"type": "finish", "stage": "generating_pdf", "translate_result": mock_result}]

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    ctx = _make_ctx(cache_dir=cache_dir)

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with patch("pdf_reader.cache_ops.tempfile.mkdtemp", return_value=str(workspace)):
        with patch("pdf_reader.sse_stream.run_translation", return_value=iter(events)):
            with patch("pdf_reader.sse_stream.debug_trace"):
                list(generate(ctx))

    assert not workspace.exists()


def test_generate_cleans_up_on_exception(tmp_path):
    """Exception during translation -> workspace removed"""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    ctx = _make_ctx(cache_dir=cache_dir)

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with patch("pdf_reader.cache_ops.tempfile.mkdtemp", return_value=str(workspace)):
        with patch("pdf_reader.sse_stream.run_translation", side_effect=RuntimeError("boom")):
            with patch("pdf_reader.sse_stream.debug_trace"):
                list(generate(ctx))

    assert not workspace.exists()


def test_format_batch_info_event():
    sse = format_batch_info(2, 5, 4)
    assert sse == ('data: {"type": "batch_info", "from": 2, "to": 5, "total": 4}\n\n')


def _make_batch_ctx(
    settings=None,
    job_id="test-job",
    finish_job=None,
    fail_job=None,
    cancel_job=None,
    from_page=2,
    to_page=5,
    page_indices=None,
    replace_pages=None,
    merge_glossary=None,
    glossary_cache_path=None,
    glossary_paths=None,
    cache_dir=None,
    extract_pages=None,
) -> GenerateBatchContext:
    if settings is None:
        settings = MagicMock()
    if finish_job is None:
        finish_job = MagicMock(return_value=True)
    if fail_job is None:
        fail_job = MagicMock(return_value=True)
    if cancel_job is None:
        cancel_job = MagicMock(return_value=True)
    if replace_pages is None:
        replace_pages = MagicMock()
    if merge_glossary is None:
        merge_glossary = MagicMock()
    if cache_dir is None:
        cache_dir = Path(tempfile.mkdtemp())
    if extract_pages is None:
        extract_pages = MagicMock(return_value=Path("/fake/pages.pdf"))
    if page_indices is None:
        page_indices = list(range(from_page - 1, to_page))
    return GenerateBatchContext(
        settings=settings,
        job_id=job_id,
        finish_job=finish_job,
        fail_job=fail_job,
        cancel_job=cancel_job,
        from_page=from_page,
        to_page=to_page,
        page_indices=page_indices,
        replace_pages=replace_pages,
        merge_glossary=merge_glossary,
        glossary_cache_path=glossary_cache_path,
        glossary_paths=glossary_paths,
        cache_dir=cache_dir,
        extract_pages=extract_pages,
    )


def test_generate_batch_emits_batch_info_then_progress_then_finish(tmp_path):
    mock_result = MagicMock()
    mock_result.mono_pdf_path = str(tmp_path / "translated.pdf")
    mock_result.dual_pdf_path = None
    mock_result.auto_extracted_glossary_path = None

    events = [
        {
            "type": "progress_start",
            "stage": "layout_analysis",
            "overall_progress": 0,
            "stage_current": 0,
            "stage_total": 0,
        },
        {
            "type": "progress_update",
            "stage": "translating",
            "overall_progress": 40,
            "stage_current": 1,
            "stage_total": 2,
        },
        {"type": "finish", "stage": "generating_pdf", "translate_result": mock_result, "token_usage": {}},
    ]

    replace_pages = MagicMock()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    ctx = _make_batch_ctx(replace_pages=replace_pages, cache_dir=cache_dir)

    with patch("pdf_reader.sse_stream.run_translation", return_value=iter(events)):
        with patch("pdf_reader.sse_stream.debug_trace"):
            with patch("pdf_reader.sse_stream.merge_glossary_only") as mg:
                result = list(generate_batch(ctx))

    # batch_info present at head
    assert '"type": "batch_info", "from": 2, "to": 5, "total": 4' in result[0]
    # progress events forwarded
    assert any('"type": "progress", "progress": 40' in r for r in result)
    # finish tail present
    assert any('"type": "finish"' in r for r in result)
    # replace_pages called once with translated pdf path
    replace_pages.assert_called_once_with(str(tmp_path / "translated.pdf"))
    # merge_glossary_only called (no replace internally)
    mg.assert_called_once()


def test_generate_batch_includes_already_translated_pages(tmp_path):
    """范围内已翻译页也纳入（不跳过）：page_indices 应等于 range(from-1,to)，无过滤。"""
    mock_result = MagicMock()
    mock_result.mono_pdf_path = str(tmp_path / "t.pdf")
    mock_result.auto_extracted_glossary_path = None
    mock_result.dual_pdf_path = None

    captured_indices = []

    def extract_spy(indices, tmpdir, func) -> Path:
        captured_indices.append(list(indices))
        return Path("/fake/pages.pdf")

    cache_dir = tmp_path / "c"
    cache_dir.mkdir()
    ctx = _make_batch_ctx(
        from_page=1,
        to_page=3,
        extract_pages=extract_spy,
        cache_dir=cache_dir,
    )

    with patch(
        "pdf_reader.sse_stream.run_translation",
        return_value=iter(
            [{"type": "finish", "stage": "generating_pdf", "translate_result": mock_result, "token_usage": {}}]
        ),
    ):
        with patch("pdf_reader.sse_stream.debug_trace"):
            with patch("pdf_reader.sse_stream.merge_glossary_only"):
                list(generate_batch(ctx))

    assert captured_indices == [[0, 1, 2]]


def test_generate_batch_error_event_stops_stream(tmp_path):
    events = [{"type": "error", "error": "boom"}]
    cache_dir = tmp_path / "c"
    cache_dir.mkdir()
    ctx = _make_batch_ctx(cache_dir=cache_dir)
    with patch("pdf_reader.sse_stream.run_translation", return_value=iter(events)):
        with patch("pdf_reader.sse_stream.debug_trace"):
            result = list(generate_batch(ctx))
    assert any('"type": "error"' in r for r in result)
    # no finish tail when error
    assert not any('"type": "finish"' in r for r in result)


def test_generate_success_finishes_active_job(tmp_path):
    mock_result = MagicMock()
    mock_result.mono_pdf_path = str(tmp_path / "translated.pdf")
    mock_result.dual_pdf_path = None
    mock_result.auto_extracted_glossary_path = None
    finish_job = MagicMock(return_value=True)
    fail_job = MagicMock(return_value=True)
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    ctx = _make_ctx(
        job_id="job-success",
        finish_job=finish_job,
        fail_job=fail_job,
        cache_dir=cache_dir,
    )

    with patch(
        "pdf_reader.sse_stream.run_translation",
        return_value=iter([{"type": "finish", "translate_result": mock_result}]),
    ):
        list(generate(ctx))

    finish_job.assert_called_once_with("job-success")
    fail_job.assert_not_called()


def test_generate_error_event_fails_active_job(tmp_path):
    finish_job = MagicMock(return_value=True)
    fail_job = MagicMock(return_value=True)
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    ctx = _make_ctx(
        job_id="job-error",
        finish_job=finish_job,
        fail_job=fail_job,
        cache_dir=cache_dir,
    )

    with patch("pdf_reader.sse_stream.run_translation", return_value=iter([{"type": "error", "error": "boom"}])):
        list(generate(ctx))

    fail_job.assert_called_once_with("job-error")
    finish_job.assert_not_called()


def test_generate_setup_exception_fails_active_job(tmp_path):
    finish_job = MagicMock(return_value=True)
    fail_job = MagicMock(return_value=True)
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    ctx = _make_ctx(
        job_id="job-setup-error",
        finish_job=finish_job,
        fail_job=fail_job,
        cache_dir=cache_dir,
    )

    with patch("pdf_reader.cache_ops.create_temp_workspace", side_effect=OSError("no temp space")):
        result = list(generate(ctx))

    assert any('"type": "error"' in item for item in result)
    fail_job.assert_called_once_with("job-setup-error")
    finish_job.assert_not_called()


# --- P1-01: SSE disconnect and background worker ownership ---


def test_generate_disconnect_cancels_worker_and_discards_late_result(tmp_path):
    """Client closes SSE mid-stream: the worker is cancelled cooperatively, a
    late translate_result never reaches replace_page, temp dirs are removed
    only after the worker actually exits, and the job slot is released as
    cancelled."""
    mock_result = MagicMock()
    mock_result.mono_pdf_path = str(tmp_path / "translated.pdf")
    mock_result.dual_pdf_path = None
    mock_result.auto_extracted_glossary_path = None

    async def slow_completing_source(settings, file) -> AsyncIterator[dict]:
        yield {"type": "progress_start", "stage": "layout_analysis"}
        await asyncio.sleep(0.3)
        yield {"type": "finish", "stage": "generating_pdf", "translate_result": mock_result}

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    replace_page = MagicMock()
    finish_job = MagicMock(return_value=True)
    fail_job = MagicMock(return_value=True)
    cancel_job = MagicMock(return_value=True)
    ctx = _make_ctx(
        job_id="job-disconnect-late",
        finish_job=finish_job,
        fail_job=fail_job,
        cancel_job=cancel_job,
        replace_page=replace_page,
        cache_dir=cache_dir,
    )

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with patch("pdf_reader.cache_ops.tempfile.mkdtemp", return_value=str(workspace)):
        with patch("pdf_reader.translation_orchestrator.do_translate_async_stream", slow_completing_source):
            with patch("pdf_reader.sse_stream.debug_trace"):
                gen = generate(ctx)
                next(gen)
                gen.close()

    assert not workspace.exists()
    replace_page.assert_not_called()
    finish_job.assert_not_called()
    fail_job.assert_not_called()
    cancel_job.assert_called_once_with("job-disconnect-late")


def test_generate_keeps_dirs_when_worker_survives_join_timeout(tmp_path):
    """A non-cooperative worker still running when SSE closes must not lose its
    workspace: after the join timeout the whole owned workspace (input/output/
    marker) is kept for recovery, the job is released as cancelled, and nothing
    is written to the document.  The fake upstream blocks on a test-owned
    release gate, and the test always releases and joins the real worker so no
    daemon thread outlives the case."""

    release = threading.Event()
    streams: list = []

    async def stuck_source(settings, file) -> AsyncIterator[dict]:
        yield {"type": "progress_start", "stage": "layout_analysis"}
        release.wait(timeout=30)

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    replace_page = MagicMock()
    cancel_job = MagicMock(return_value=True)
    ctx = _make_ctx(
        job_id="job-stuck",
        cancel_job=cancel_job,
        replace_page=replace_page,
        cache_dir=cache_dir,
    )
    ctx.register_stream = lambda job_id, stream: streams.append(stream)

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    stream = None
    try:
        with patch("pdf_reader.cache_ops.tempfile.mkdtemp", return_value=str(workspace)):
            with patch("pdf_reader.translation_orchestrator.do_translate_async_stream", stuck_source):
                with patch("pdf_reader.sse_stream.WORKER_JOIN_TIMEOUT", 0.2):
                    with patch("pdf_reader.sse_stream.debug_trace"):
                        gen = generate(ctx)
                        next(gen)
                        gen.close()

        stream = streams[0]
        assert stream.is_alive, "non-cooperative worker survives join timeout"
        assert workspace.exists()
        assert (workspace / "input").is_dir()
        assert (workspace / "output").is_dir()
        assert (workspace / cache_ops.TEMP_MARKER_NAME).is_file()
        replace_page.assert_not_called()
        cancel_job.assert_called_once_with("job-stuck")
    finally:
        release.set()
        if stream is not None:
            stream.join(timeout=5.0)
            assert not stream.is_alive
            assert workspace.exists()
            assert (workspace / "input").is_dir()
            assert (workspace / "output").is_dir()
            assert (workspace / cache_ops.TEMP_MARKER_NAME).is_file()


def test_generate_batch_disconnect_cancels_worker(tmp_path):
    """generate_batch shares the same worker ownership: disconnect cancels the
    worker, discards the late result and cleans the owned workspace only after
    worker exit."""
    mock_result = MagicMock()
    mock_result.mono_pdf_path = str(tmp_path / "translated.pdf")
    mock_result.dual_pdf_path = None
    mock_result.auto_extracted_glossary_path = None

    async def slow_completing_source(settings, file) -> AsyncIterator[dict]:
        yield {"type": "progress_start", "stage": "layout_analysis"}
        await asyncio.sleep(0.3)
        yield {"type": "finish", "stage": "generating_pdf", "translate_result": mock_result}

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    replace_pages = MagicMock()
    cancel_job = MagicMock(return_value=True)
    ctx = _make_batch_ctx(
        job_id="job-batch-disconnect",
        cancel_job=cancel_job,
        replace_pages=replace_pages,
        cache_dir=cache_dir,
    )

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with patch("pdf_reader.cache_ops.tempfile.mkdtemp", return_value=str(workspace)):
        with patch("pdf_reader.translation_orchestrator.do_translate_async_stream", slow_completing_source):
            with patch("pdf_reader.sse_stream.debug_trace"):
                gen = generate_batch(ctx)
                next(gen)
                gen.close()

    assert not workspace.exists()
    replace_pages.assert_not_called()
    cancel_job.assert_called_once_with("job-batch-disconnect")


# --- P2-05: SSE error sanitization ---


def test_generate_upstream_error_event_not_leaked(tmp_path, caplog):
    """上游 error 事件只发稳定 code+安全消息；原始错误仅进服务端日志。"""
    sentinel = "UPSTREAM-RAW sk-secret-999 C:\\Users\\priv\\file <img src=x onerror=alert(1)>"
    events = [{"type": "error", "error": sentinel}]
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    ctx = _make_ctx(cache_dir=cache_dir)

    with patch("pdf_reader.sse_stream.run_translation", return_value=iter(events)):
        with patch("pdf_reader.sse_stream.debug_trace"):
            with caplog.at_level("WARNING", logger="pdf_reader.translate"):
                result = list(generate(ctx))

    assert result[-1] == EXPECTED_ERROR_SSE
    joined = "".join(result)
    assert "UPSTREAM-RAW" not in joined
    assert "sk-secret-999" not in joined
    assert "onerror" not in joined
    # P1-04：原始上游错误正文既不进 SSE，也不进日志；只记录分类后的稳定码。
    assert sentinel not in caplog.text
    assert "code=translation_error" in caplog.text


def test_generate_generic_exception_not_leaked(tmp_path, caplog):
    """普通异常只发 internal_error 安全摘要；原始异常保留在服务端日志。"""
    sentinel = "BOOM sk-secret-777 C:\\Users\\x <img src=x onerror=alert(1)>"
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    ctx = _make_ctx(
        cache_dir=cache_dir,
        extract_page=MagicMock(side_effect=RuntimeError(sentinel)),
    )

    with patch("pdf_reader.sse_stream.run_translation"):
        with patch("pdf_reader.sse_stream.debug_trace"):
            with caplog.at_level("ERROR", logger="pdf_reader.translate"):
                result = list(generate(ctx))

    error_events = [item for item in result if '"type": "error"' in item]
    assert error_events
    assert '"code": "internal_error"' in error_events[-1]
    joined = "".join(result)
    assert "BOOM sk-secret-777" not in joined
    assert "onerror" not in joined
    assert sentinel in caplog.text


def test_generate_no_translate_result_sanitized(tmp_path, caplog):
    events = [{"type": "progress_start", "stage": "layout_analysis"}]
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    ctx = _make_ctx(cache_dir=cache_dir)

    with patch("pdf_reader.sse_stream.run_translation", return_value=iter(events)):
        with patch("pdf_reader.sse_stream.debug_trace"):
            with caplog.at_level("WARNING", logger="pdf_reader.translate"):
                result = list(generate(ctx))

    expected = (
        "data: " + json.dumps({"type": "error", "code": "translation_error", "error": "未获取到翻译结果"}) + "\n\n"
    )
    assert result[-1] == expected
    assert "no translation result" in caplog.text


def test_generate_batch_error_event_not_leaked(tmp_path, caplog):
    sentinel = "BATCH-RAW sk-secret-888 C:\\Users\\priv\\file"
    events = [{"type": "error", "error": sentinel}]
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    ctx = _make_batch_ctx(cache_dir=cache_dir)

    with patch("pdf_reader.sse_stream.run_translation", return_value=iter(events)):
        with patch("pdf_reader.sse_stream.debug_trace"):
            with caplog.at_level("WARNING", logger="pdf_reader.translate"):
                result = list(generate_batch(ctx))

    assert result[-1] == EXPECTED_ERROR_SSE
    joined = "".join(result)
    assert "BATCH-RAW" not in joined
    assert "sk-secret-888" not in joined
    # P1-04：原始上游错误正文既不进 SSE，也不进日志；只记录分类后的稳定码。
    assert sentinel not in caplog.text
    assert "code=translation_error" in caplog.text


def test_generate_batch_translation_error_not_leaked(tmp_path, caplog):
    """批量 TranslationError：客户端固定 translation_error 安全摘要，原始错误只进日志。"""
    from pdf_reader.translation_orchestrator import TranslationError

    sentinel = (
        "BATCH-TRANSLATION sk-secret-555 C:\\Users\\priv\\file /home/user/private/file <img src=x onerror=alert(1)>"
    )
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    fail_job = MagicMock(return_value=True)
    finish_job = MagicMock(return_value=True)
    ctx = _make_batch_ctx(
        cache_dir=cache_dir,
        fail_job=fail_job,
        finish_job=finish_job,
    )

    def error_iter() -> Iterator[dict]:
        yield {"type": "progress_start", "stage": "layout_analysis"}
        raise TranslationError(sentinel)

    with patch("pdf_reader.sse_stream.run_translation", return_value=error_iter()):
        with patch("pdf_reader.sse_stream.debug_trace"):
            with caplog.at_level("WARNING", logger="pdf_reader.translate"):
                result = list(generate_batch(ctx))

    assert result[-1] == EXPECTED_ERROR_SSE
    joined = "".join(result)
    assert "BATCH-TRANSLATION" not in joined
    assert "sk-secret-555" not in joined
    assert "onerror" not in joined
    assert "/home/user" not in joined
    assert sentinel in caplog.text
    fail_job.assert_called_once_with("test-job")
    finish_job.assert_not_called()


def test_generate_batch_generic_exception_not_leaked_and_cleans_up(tmp_path, caplog):
    """批量普通异常：internal_error 安全摘要、完整日志、fail_job 与目录清理不变量不变。"""
    sentinel = "BATCH-BOOM sk-secret-666 C:\\Users\\x\\file /tmp/private/file <img src=x onerror=alert(1)>"
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    fail_job = MagicMock(return_value=True)
    finish_job = MagicMock(return_value=True)
    ctx = _make_batch_ctx(
        cache_dir=cache_dir,
        fail_job=fail_job,
        finish_job=finish_job,
        extract_pages=MagicMock(side_effect=RuntimeError(sentinel)),
    )

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with patch("pdf_reader.cache_ops.tempfile.mkdtemp", return_value=str(workspace)):
        with patch("pdf_reader.sse_stream.run_translation"):
            with patch("pdf_reader.sse_stream.debug_trace"):
                with caplog.at_level("ERROR", logger="pdf_reader.translate"):
                    result = list(generate_batch(ctx))

    error_events = [item for item in result if '"type": "error"' in item]
    assert error_events
    assert '"code": "internal_error"' in error_events[-1]
    joined = "".join(result)
    assert "BATCH-BOOM" not in joined
    assert "sk-secret-666" not in joined
    assert "onerror" not in joined
    assert sentinel in caplog.text
    fail_job.assert_called_once_with("test-job")
    finish_job.assert_not_called()
    assert not workspace.exists()


# --- P3-05: per-task owned workspace boundary (single page and batch) ---


def test_generate_uses_owned_workspace_boundaries(tmp_path):
    """单页翻译：cache 根一个带前缀+标记的根工作区；抽取在 input/，上游输出指向
    output/，标记在任务期间存在，成功后整个根工作区被删除。"""
    mock_result = MagicMock()
    mock_result.mono_pdf_path = str(tmp_path / "translated.pdf")
    mock_result.dual_pdf_path = None
    mock_result.auto_extracted_glossary_path = None

    events = [{"type": "finish", "stage": "generating_pdf", "translate_result": mock_result, "token_usage": {}}]

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    captured = {}

    def extract_spy(page, tmpdir, func) -> Path:
        captured["workspace"] = Path(tmpdir).parent
        captured["tmpdir"] = Path(tmpdir)
        captured["output_present"] = (Path(tmpdir).parent / "output").is_dir()
        captured["marker_present"] = (Path(tmpdir).parent / cache_ops.TEMP_MARKER_NAME).is_file()
        return Path("/fake/page.pdf")

    settings = MagicMock()
    ctx = _make_ctx(settings=settings, cache_dir=cache_dir, extract_page=extract_spy)

    with patch("pdf_reader.sse_stream.run_translation", return_value=iter(events)):
        with patch("pdf_reader.sse_stream.debug_trace"):
            list(generate(ctx))

    workspace = captured["workspace"]
    assert workspace.parent == cache_dir
    assert workspace.name.startswith(cache_ops.TEMP_WORKSPACE_PREFIX)
    assert captured["tmpdir"] == workspace / "input"
    assert captured["output_present"] is True
    assert captured["marker_present"] is True
    assert str(settings.translation.output) == str(workspace / "output")
    assert not workspace.exists()


def test_generate_batch_uses_owned_workspace_boundaries(tmp_path):
    """批量翻译与单页一致：同一根工作区边界，input/output/marker 归属与清理不变。"""
    mock_result = MagicMock()
    mock_result.mono_pdf_path = str(tmp_path / "translated.pdf")
    mock_result.dual_pdf_path = None
    mock_result.auto_extracted_glossary_path = None

    events = [{"type": "finish", "stage": "generating_pdf", "translate_result": mock_result, "token_usage": {}}]

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    captured = {}

    def extract_spy(indices, tmpdir, func) -> Path:
        captured["workspace"] = Path(tmpdir).parent
        captured["tmpdir"] = Path(tmpdir)
        captured["output_present"] = (Path(tmpdir).parent / "output").is_dir()
        captured["marker_present"] = (Path(tmpdir).parent / cache_ops.TEMP_MARKER_NAME).is_file()
        return Path("/fake/pages.pdf")

    settings = MagicMock()
    ctx = _make_batch_ctx(settings=settings, cache_dir=cache_dir, extract_pages=extract_spy)

    with patch("pdf_reader.sse_stream.run_translation", return_value=iter(events)):
        with patch("pdf_reader.sse_stream.debug_trace"):
            with patch("pdf_reader.sse_stream.merge_glossary_only"):
                list(generate_batch(ctx))

    workspace = captured["workspace"]
    assert workspace.parent == cache_dir
    assert workspace.name.startswith(cache_ops.TEMP_WORKSPACE_PREFIX)
    assert captured["tmpdir"] == workspace / "input"
    assert captured["output_present"] is True
    assert captured["marker_present"] is True
    assert str(settings.translation.output) == str(workspace / "output")
    assert not workspace.exists()


def test_generate_uses_one_based_page_in_flow_label_and_glossary(tmp_path):
    """单页翻译：0-based ctx.page=2 在 flow_label 与 finish_translation（glossary
    字段）中统一显示为 1-based page=3。"""
    mock_result = MagicMock()
    mock_result.mono_pdf_path = str(tmp_path / "translated.pdf")
    mock_result.dual_pdf_path = None
    mock_result.auto_extracted_glossary_path = None

    events = [{"type": "finish", "stage": "generating_pdf", "translate_result": mock_result, "token_usage": {}}]

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    captured = {}

    def fake_finish(result, replace_page, merge_glossary, page, job_id) -> None:
        captured["page"] = page
        captured["job_id"] = job_id

    ctx = _make_ctx(page=2, cache_dir=cache_dir)

    with patch("pdf_reader.sse_stream.run_translation", return_value=iter(events)) as rt:
        with patch("pdf_reader.sse_stream.debug_trace"):
            with patch("pdf_reader.sse_stream.finish_translation", side_effect=fake_finish):
                list(generate(ctx))

    assert rt.call_args.kwargs["flow_label"] == "page=3"
    assert captured["page"] == 3
    assert captured["job_id"] == "test-job"


def test_generate_batch_debug_session_and_glossary_pages_consistent(tmp_path):
    """批量翻译：debug_session 收到 0-based 首页索引（内部 +1），glossary 字段收到
    1-based 起始页，二者显示一致。"""
    mock_result = MagicMock()
    mock_result.mono_pdf_path = str(tmp_path / "translated.pdf")
    mock_result.dual_pdf_path = None
    mock_result.auto_extracted_glossary_path = None

    events = [{"type": "finish", "stage": "generating_pdf", "translate_result": mock_result, "token_usage": {}}]

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    ctx = _make_batch_ctx(from_page=2, to_page=3, cache_dir=cache_dir)

    with patch("pdf_reader.sse_stream.run_translation", return_value=iter(events)) as rt:
        with patch("pdf_reader.sse_stream.debug_trace.debug_session") as ds:
            with patch("pdf_reader.sse_stream.merge_glossary_only") as mg:
                list(generate_batch(ctx))

    assert rt.call_args.kwargs["flow_label"] == "pages=2-3"
    assert ds.call_args.args[1] == 1
    assert mg.call_args.args[2] == 2


def test_generate_logs_temp_rmtree_failure_with_path_and_exception(tmp_path, caplog):
    """临时目录删除失败：记录具体异常与路径，仍保持安全清理语义（不删除、返回 False）。"""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    ctx = _make_ctx(cache_dir=cache_dir)

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with patch("pdf_reader.cache_ops.tempfile.mkdtemp", return_value=str(workspace)):
        with patch("pdf_reader.sse_stream.run_translation", return_value=iter([{"type": "error", "error": "boom"}])):
            with patch("pdf_reader.sse_stream.debug_trace"):
                with patch("pdf_reader.sse_stream.shutil.rmtree", side_effect=OSError("locked")) as rmtree:
                    with caplog.at_level(logging.WARNING, logger="pdf_reader.translate"):
                        list(generate(ctx))

    assert workspace.exists()
    rmtree.assert_called_once_with(workspace)
    assert "failed to remove temp workspace" in caplog.text
    assert str(workspace) in caplog.text
    assert "locked" in caplog.text
    assert "cleanup deferred" in caplog.text


# --- P1-04: 上游 error 事件的保守下载失败分类 ---


def _sse_payload(text: str) -> dict:
    assert text.startswith("data: ")
    return json.loads(text[len("data: ") :])


@pytest.mark.parametrize(
    "raw_error",
    [
        "Failed to download model: huggingface.co returned 503",
        "hf_hub_download: connection refused while fetching file",
        "snapshot_download(model) timed out",
        "ModelScope download failed: no such host",
        "Could not download font file SourceHanSans.ttf: SSL certificate verify failed",
        "下载模型失败：网络连接超时",
        "字体下载失败",
    ],
)
def test_download_failure_event_maps_to_the_fixed_safe_code(raw_error):
    result = format_sse_event({"type": "error", "error": raw_error})

    payload = _sse_payload(result)
    assert payload == {
        "type": "error",
        "code": MODEL_DOWNLOAD_FAILED_CODE,
        "error": MODEL_DOWNLOAD_FAILED_MESSAGE,
    }
    assert raw_error not in result


@pytest.mark.parametrize(
    "raw_error",
    [
        "raw upstream error",
        "thread crashed",
        "UPSTREAM-RAW sk-secret-999 C:\\Users\\priv\\file <img src=x onerror=alert(1)>",
        "Connection refused",
        "translation model returned an error",
        "rate limit exceeded",
        "the font is too small for this page",
        "",
    ],
)
def test_ordinary_error_event_keeps_the_existing_translation_error_semantics(raw_error):
    result = format_sse_event({"type": "error", "error": raw_error})

    payload = _sse_payload(result)
    assert payload == {"type": "error", "code": "translation_error", "error": "上游翻译失败"}


def test_download_failure_detection_accepts_nested_error_shapes():
    nested = format_sse_event({"type": "error", "error": {"message": "huggingface download error"}})
    listed = format_sse_event({"type": "error", "error": ["download", "failed"]})

    assert _sse_payload(nested)["code"] == MODEL_DOWNLOAD_FAILED_CODE
    assert _sse_payload(listed)["code"] == MODEL_DOWNLOAD_FAILED_CODE


def test_download_failure_code_is_shared_with_the_portable_error_catalog():
    from pdf_reader import portable_errors

    presentation = portable_errors.describe_error(MODEL_DOWNLOAD_FAILED_CODE)
    assert presentation.code == MODEL_DOWNLOAD_FAILED_CODE
    assert MODEL_DOWNLOAD_FAILED_CODE in portable_errors.ERROR_CATALOG


def test_generate_download_failure_not_leaked_to_client(tmp_path, caplog):
    sentinel = "DOWNLOAD-FAIL sk-secret-424 C:\\Users\\priv\\model <img src=x onerror=alert(1)> huggingface"
    events = [{"type": "error", "error": sentinel}]
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    ctx = _make_ctx(cache_dir=cache_dir)

    with patch("pdf_reader.sse_stream.run_translation", return_value=iter(events)):
        with patch("pdf_reader.sse_stream.debug_trace"):
            with caplog.at_level("WARNING", logger="pdf_reader.translate"):
                result = list(generate(ctx))

    assert result[-1] == (
        "data: "
        + json.dumps({"type": "error", "code": MODEL_DOWNLOAD_FAILED_CODE, "error": MODEL_DOWNLOAD_FAILED_MESSAGE})
        + "\n\n"
    )
    joined = "".join(result)
    assert "DOWNLOAD-FAIL" not in joined
    assert "sk-secret-424" not in joined
    assert "onerror" not in joined
    assert "huggingface" not in joined
    # 原始正文既不进 SSE，也不进日志；日志只记录分类后的稳定码。
    assert sentinel not in caplog.text
    assert f"code={MODEL_DOWNLOAD_FAILED_CODE}" in caplog.text


def test_generate_batch_download_failure_not_leaked_to_client(tmp_path, caplog):
    sentinel = "BATCH-DL sk-secret-313 /home/priv/model huggingface download error"
    events = [{"type": "error", "error": sentinel}]
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    ctx = _make_batch_ctx(cache_dir=cache_dir)

    with patch("pdf_reader.sse_stream.run_translation", return_value=iter(events)):
        with patch("pdf_reader.sse_stream.debug_trace"):
            with caplog.at_level("WARNING", logger="pdf_reader.translate"):
                result = list(generate_batch(ctx))

    assert result[-1] == (
        "data: "
        + json.dumps({"type": "error", "code": MODEL_DOWNLOAD_FAILED_CODE, "error": MODEL_DOWNLOAD_FAILED_MESSAGE})
        + "\n\n"
    )
    joined = "".join(result)
    assert "BATCH-DL" not in joined
    assert "sk-secret-313" not in joined
    assert "/home/priv" not in joined
    # 原始正文既不进 SSE，也不进日志；日志只记录分类后的稳定码。
    assert sentinel not in caplog.text
    assert f"code={MODEL_DOWNLOAD_FAILED_CODE}" in caplog.text


# --- P1-04: 分类器的鲁棒性（畸形输入不能打断 SSE 流） ---


class ExplodingStr:
    def __str__(self) -> str:
        raise RuntimeError("__str__ exploded")


class ExplodingGetMapping(dict):
    def get(self, key, default=None):
        raise RuntimeError("get exploded")


def test_upstream_error_text_tolerates_hostile_objects():
    """任意对象的 __str__/get 抛异常时必须退化为普通错误，绝不打断 SSE。"""

    hostile = ExplodingStr()

    assert format_sse_event({"type": "error", "error": hostile}) == EXPECTED_ERROR_SSE
    assert classify_upstream_error({"error": hostile}) == ("translation_error", "上游翻译失败")
    assert format_sse_event({"type": "error", "error": ExplodingGetMapping()}) == EXPECTED_ERROR_SSE


def test_upstream_error_text_bounds_container_traversal():
    """容器遍历有界：超出上限的条目既不参与判定，也不放大工作量。"""

    padding = ["neutral"] * (MAXIMUM_UPSTREAM_ERROR_ITEMS + 5)

    assert classify_upstream_error({"error": ["download failed", *padding]})[0] == MODEL_DOWNLOAD_FAILED_CODE
    assert classify_upstream_error({"error": [*padding, "download failed"]})[0] == "translation_error"


def test_upstream_error_text_bounds_nesting_depth():
    nested: object = "download failed"
    for _ in range(20):
        nested = [nested]

    assert classify_upstream_error({"error": nested})[0] == "translation_error"
