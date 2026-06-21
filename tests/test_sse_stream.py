import json

from sse_stream import format_sse_event

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
