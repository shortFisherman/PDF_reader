import asyncio
from unittest.mock import MagicMock, patch

import pytest

from translation_orchestrator import TranslationError, run_translation


def test_run_translation_yields_events_in_order():
    events = [
        {"type": "progress_start", "stage": "layout_analysis", "overall_progress": 0},
        {"type": "progress_update", "stage": "translating", "overall_progress": 50},
        {"type": "finish", "stage": "generating_pdf", "translate_result": MagicMock()},
    ]

    async def fake_stream(settings, file):
        for evt in events:
            yield evt

    with patch("translation_orchestrator.do_translate_async_stream", fake_stream):
        result = list(run_translation(MagicMock(), "fake.pdf"))

    assert len(result) == 3
    assert result[0]["type"] == "progress_start"
    assert result[1]["type"] == "progress_update"
    assert result[2]["type"] == "finish"


def test_run_translation_raises_on_thread_error():
    async def failing_stream(settings, file):
        yield {"type": "progress_start", "stage": "layout_analysis"}
        raise RuntimeError("translation engine crashed")

    with patch("translation_orchestrator.do_translate_async_stream", failing_stream):
        with pytest.raises(TranslationError, match="translation engine crashed"):
            list(run_translation(MagicMock(), "fake.pdf"))


def test_run_translation_propagates_error_event():
    async def error_stream(settings, file):
        yield {"type": "error", "error": "engine error"}
        yield {"type": "finish"}

    with patch("translation_orchestrator.do_translate_async_stream", error_stream):
        result = list(run_translation(MagicMock(), "fake.pdf"))

    assert len(result) == 2
    assert result[0]["type"] == "error"
    assert result[0]["error"] == "engine error"
