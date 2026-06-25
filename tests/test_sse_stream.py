import csv
import json
import tempfile
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sse_stream import GenerateContext, format_sse_event, generate

# --- Gold-standard SSE constants (preserved from original) ---
EXPECTED_PROGRESS_START_SSE = (
    'data: ' + json.dumps({
        "type": "progress", "progress": 0,
        "stage": "layout_analysis",
        "stage_current": 0, "stage_total": 0,
    }) + '\n\n'
)

EXPECTED_PROGRESS_UPDATE_SSE = (
    'data: ' + json.dumps({
        "type": "progress",
        "progress": 50,
        "stage": "translating",
        "stage_current": 2, "stage_total": 5,
    }) + '\n\n'
)

EXPECTED_FINISH_PROGRESS_SSE = (
    'data: ' + json.dumps({
        "type": "progress", "progress": 95,
        "stage": "generating_pdf",
        "stage_current": 0, "stage_total": 0,
    }) + '\n\n'
)

EXPECTED_ERROR_SSE = (
    'data: ' + json.dumps({"type": "error", "error": "test error"}) + '\n\n'
)

EXPECTED_FINAL_PROGRESS_SSE = (
    'data: ' + json.dumps({
        "type": "progress", "progress": 100,
        "stage": "finish", "stage_current": 0, "stage_total": 0,
    }) + '\n\n'
)

EXPECTED_FINAL_FINISH_SSE = (
    'data: ' + json.dumps({"type": "finish", "progress": 100}) + '\n\n'
)


def _make_ctx(settings=None, replace_page=None, glossary_cache_path=None, page=0,
              glossary_paths=None, cache_dir=None, extract_page=None):
    if settings is None:
        settings = MagicMock()
    if replace_page is None:
        replace_page = MagicMock()
    if cache_dir is None:
        cache_dir = Path(tempfile.mkdtemp())
    if extract_page is None:
        extract_page = MagicMock(return_value=Path("/fake/page.pdf"))
    return GenerateContext(
        settings=settings,
        replace_page=replace_page,
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
        'data: {"type": "progress", "progress": 50, "stage": "translating", '
        '"stage_current": 2, "stage_total": 5}\n\n'
    )


def test_golden_sample_error():
    assert EXPECTED_ERROR_SSE == (
        'data: {"type": "error", "error": "test error"}\n\n'
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
        {"type": "progress_start", "stage": "layout_analysis", "overall_progress": 0,
         "stage_current": 0, "stage_total": 0},
        {"type": "progress_update", "stage": "translating", "overall_progress": 50,
         "stage_current": 2, "stage_total": 5},
        {"type": "finish", "stage": "generating_pdf", "translate_result": mock_result,
         "token_usage": {}},
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
        {"type": "progress_start", "stage": "layout_analysis", "overall_progress": 0,
         "stage_current": 0, "stage_total": 0},
        {"type": "finish", "stage": "generating_pdf", "translate_result": mock_result,
         "token_usage": {}},
    ]

    replace_page = MagicMock()
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    ctx = _make_ctx(
        settings=MagicMock(),
        replace_page=replace_page,
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
        {"type": "finish", "stage": "generating_pdf", "translate_result": mock_result,
         "token_usage": {}},
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
    """3.3: gen.close() -> GeneratorExit -> dirs removed"""
    events = [
        {"type": "progress_start", "stage": "layout_analysis", "overall_progress": 0,
         "stage_current": 0, "stage_total": 0},
    ]

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
                gen = generate(ctx)
                next(gen)
                gen.close()

    assert not tmpdir.exists()
    assert not output_dir.exists()


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
