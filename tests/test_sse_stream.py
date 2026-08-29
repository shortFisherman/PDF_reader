import asyncio
import csv
import json
import tempfile
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

from sse_stream import (
    GenerateBatchContext,
    GenerateContext,
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

EXPECTED_ERROR_SSE = "data: " + json.dumps({"type": "error", "error": "test error"}) + "\n\n"

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
    assert EXPECTED_ERROR_SSE == ('data: {"type": "error", "error": "test error"}\n\n')


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

    with patch("sse_stream.run_translation", return_value=iter(events)):
        with patch("sse_stream.debug_trace"):
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

    with patch("sse_stream.run_translation", return_value=iter(events)):
        with patch("sse_stream.debug_trace"):
            result = list(generate(ctx))

    assert len(result) == 2
    assert result[0] == EXPECTED_PROGRESS_START_SSE
    assert result[1] == EXPECTED_ERROR_SSE


def test_generate_translation_error_yields_error_event(tmp_path):
    from translation_orchestrator import TranslationError

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

    with patch("sse_stream.run_translation", return_value=error_iter()):
        with patch("sse_stream.debug_trace"):
            result = list(generate(ctx))

    assert len(result) == 2
    assert result[0] == EXPECTED_PROGRESS_START_SSE
    assert "error" in result[1]
    assert "thread crashed" in result[1]


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
        merge_glossary=lambda auto_path: __import__("glossary_service").merge_after_translate(
            cumulative_file,
            auto_path,
        ),
        glossary_cache_path=glossary_cache,
        cache_dir=work_dir,
    )

    with patch("sse_stream.run_translation", return_value=iter(events)):
        with patch("sse_stream.debug_trace"):
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

    with patch("sse_stream.run_translation", return_value=iter(events)):
        with patch("sse_stream.debug_trace"):
            result = list(generate(ctx))

    assert result[0] == ""


# --- Cleanup tests ---


def test_generate_cleans_up_on_error_event(tmp_path):
    """3.1: error event early exit -> tmpdir/output_dir removed"""
    events = [{"type": "error", "error": "test error"}]

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    ctx = _make_ctx(cache_dir=cache_dir)

    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    with patch("sse_stream.tempfile.mkdtemp", side_effect=[str(tmpdir), str(output_dir)]):
        with patch("sse_stream.run_translation", return_value=iter(events)):
            with patch("sse_stream.debug_trace"):
                list(generate(ctx))

    assert not tmpdir.exists()
    assert not output_dir.exists()


def test_generate_cleans_up_on_no_translate_result(tmp_path):
    """3.2: no translate_result early exit -> tmpdir/output_dir removed"""
    events = [{"type": "progress_start", "stage": "layout_analysis"}]

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    ctx = _make_ctx(cache_dir=cache_dir)

    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    with patch("sse_stream.tempfile.mkdtemp", side_effect=[str(tmpdir), str(output_dir)]):
        with patch("sse_stream.run_translation", return_value=iter(events)):
            with patch("sse_stream.debug_trace"):
                list(generate(ctx))

    assert not tmpdir.exists()
    assert not output_dir.exists()


def test_generate_cleans_up_on_generator_close(tmp_path):
    """3.3: gen.close() -> GeneratorExit -> dirs removed, job released as cancelled"""
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

    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    with patch("sse_stream.tempfile.mkdtemp", side_effect=[str(tmpdir), str(output_dir)]):
        with patch("sse_stream.run_translation", return_value=iter(events)):
            with patch("sse_stream.debug_trace"):
                gen = generate(ctx)
                next(gen)
                gen.close()

    assert not tmpdir.exists()
    assert not output_dir.exists()
    cancel_job.assert_called_once_with("job-disconnect")
    fail_job.assert_not_called()


def test_generate_cleans_up_on_success(tmp_path):
    """3.4: success path -> dirs removed exactly once"""
    mock_result = MagicMock()
    mock_result.mono_pdf_path = str(tmp_path / "translated.pdf")
    mock_result.dual_pdf_path = None
    mock_result.auto_extracted_glossary_path = None

    events = [{"type": "finish", "stage": "generating_pdf", "translate_result": mock_result}]

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    ctx = _make_ctx(cache_dir=cache_dir)

    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    with patch("sse_stream.tempfile.mkdtemp", side_effect=[str(tmpdir), str(output_dir)]):
        with patch("sse_stream.run_translation", return_value=iter(events)):
            with patch("sse_stream.debug_trace"):
                list(generate(ctx))

    assert not tmpdir.exists()
    assert not output_dir.exists()


def test_generate_cleans_up_on_exception(tmp_path):
    """Exception during translation -> dirs removed"""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    ctx = _make_ctx(cache_dir=cache_dir)

    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    with patch("sse_stream.tempfile.mkdtemp", side_effect=[str(tmpdir), str(output_dir)]):
        with patch("sse_stream.run_translation", side_effect=RuntimeError("boom")):
            with patch("sse_stream.debug_trace"):
                list(generate(ctx))

    assert not tmpdir.exists()
    assert not output_dir.exists()


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

    with patch("sse_stream.run_translation", return_value=iter(events)):
        with patch("sse_stream.debug_trace"):
            with patch("sse_stream.merge_glossary_only") as mg:
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
        "sse_stream.run_translation",
        return_value=iter(
            [{"type": "finish", "stage": "generating_pdf", "translate_result": mock_result, "token_usage": {}}]
        ),
    ):
        with patch("sse_stream.debug_trace"):
            with patch("sse_stream.merge_glossary_only"):
                list(generate_batch(ctx))

    assert captured_indices == [[0, 1, 2]]


def test_generate_batch_error_event_stops_stream(tmp_path):
    events = [{"type": "error", "error": "boom"}]
    cache_dir = tmp_path / "c"
    cache_dir.mkdir()
    ctx = _make_batch_ctx(cache_dir=cache_dir)
    with patch("sse_stream.run_translation", return_value=iter(events)):
        with patch("sse_stream.debug_trace"):
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
        "sse_stream.run_translation",
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

    with patch("sse_stream.run_translation", return_value=iter([{"type": "error", "error": "boom"}])):
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

    with patch("sse_stream.tempfile.mkdtemp", side_effect=OSError("no temp space")):
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

    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    with patch("sse_stream.tempfile.mkdtemp", side_effect=[str(tmpdir), str(output_dir)]):
        with patch("translation_orchestrator.do_translate_async_stream", slow_completing_source):
            with patch("sse_stream.debug_trace"):
                gen = generate(ctx)
                next(gen)
                gen.close()

    assert not tmpdir.exists()
    assert not output_dir.exists()
    replace_page.assert_not_called()
    finish_job.assert_not_called()
    fail_job.assert_not_called()
    cancel_job.assert_called_once_with("job-disconnect-late")


def test_generate_keeps_dirs_when_worker_survives_join_timeout(tmp_path):
    """A non-cooperative worker still running when SSE closes must not lose its
    temp dirs: after the join timeout the dirs are kept for recovery, the job is
    released as cancelled, and nothing is written to the document."""

    async def stuck_source(settings, file) -> AsyncIterator[dict]:
        yield {"type": "progress_start", "stage": "layout_analysis"}
        await asyncio.sleep(3600)

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

    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    with patch("sse_stream.tempfile.mkdtemp", side_effect=[str(tmpdir), str(output_dir)]):
        with patch("translation_orchestrator.do_translate_async_stream", stuck_source):
            with patch("sse_stream.WORKER_JOIN_TIMEOUT", 0.2):
                with patch("sse_stream.debug_trace"):
                    gen = generate(ctx)
                    next(gen)
                    gen.close()

    assert tmpdir.exists()
    assert output_dir.exists()
    replace_page.assert_not_called()
    cancel_job.assert_called_once_with("job-stuck")


def test_generate_batch_disconnect_cancels_worker(tmp_path):
    """generate_batch shares the same worker ownership: disconnect cancels the
    worker, discards the late result and cleans dirs only after worker exit."""
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

    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    with patch("sse_stream.tempfile.mkdtemp", side_effect=[str(tmpdir), str(output_dir)]):
        with patch("translation_orchestrator.do_translate_async_stream", slow_completing_source):
            with patch("sse_stream.debug_trace"):
                gen = generate_batch(ctx)
                next(gen)
                gen.close()

    assert not tmpdir.exists()
    assert not output_dir.exists()
    replace_pages.assert_not_called()
    cancel_job.assert_called_once_with("job-batch-disconnect")
