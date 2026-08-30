import asyncio
import threading
from collections.abc import AsyncIterator
from unittest.mock import MagicMock, patch

import pytest

from pdf_reader.translation_orchestrator import TranslationError, run_translation


def test_run_translation_yields_events_in_order():
    events = [
        {"type": "progress_start", "stage": "layout_analysis", "overall_progress": 0},
        {"type": "progress_update", "stage": "translating", "overall_progress": 50},
        {"type": "finish", "stage": "generating_pdf", "translate_result": MagicMock()},
    ]

    async def fake_stream(settings, file) -> AsyncIterator[dict]:
        for evt in events:
            yield evt

    with patch("pdf_reader.translation_orchestrator.do_translate_async_stream", fake_stream):
        result = list(run_translation(MagicMock(), "fake.pdf"))

    assert len(result) == 3
    assert result[0]["type"] == "progress_start"
    assert result[1]["type"] == "progress_update"
    assert result[2]["type"] == "finish"


def test_run_translation_raises_on_thread_error():
    async def failing_stream(settings, file) -> AsyncIterator[dict]:
        yield {"type": "progress_start", "stage": "layout_analysis"}
        raise RuntimeError("translation engine crashed")

    with patch("pdf_reader.translation_orchestrator.do_translate_async_stream", failing_stream):
        with pytest.raises(TranslationError, match="translation engine crashed"):
            list(run_translation(MagicMock(), "fake.pdf"))


def test_run_translation_propagates_error_event():
    async def error_stream(settings, file) -> AsyncIterator[dict]:
        yield {"type": "error", "error": "engine error"}
        yield {"type": "finish"}

    with patch("pdf_reader.translation_orchestrator.do_translate_async_stream", error_stream):
        result = list(run_translation(MagicMock(), "fake.pdf"))

    assert len(result) == 2
    assert result[0]["type"] == "error"
    assert result[0]["error"] == "engine error"


def test_translation_stream_cancel_stops_cooperative_worker():
    """cancel() asks the worker to stop at the next event boundary; the worker
    thread actually exits instead of relying on daemon process exit."""

    async def endless_stream(settings, file) -> AsyncIterator[dict]:
        i = 0
        while True:
            await asyncio.sleep(0)
            yield {
                "type": "progress_update",
                "overall_progress": i % 100,
                "stage": "translating",
                "stage_current": 0,
                "stage_total": 0,
            }
            i += 1

    with patch("pdf_reader.translation_orchestrator.do_translate_async_stream", endless_stream):
        stream = run_translation(MagicMock(), "fake.pdf")
        while not isinstance(next(stream), dict):
            pass
        stream.cancel()
        stream.join(timeout=5.0)

    assert not stream.is_alive


def test_translation_stream_join_timeout_reports_worker_alive():
    """A non-cooperative upstream that ignores cancellation stays alive after
    join timeout; is_alive reports the real worker state.  The fake upstream
    blocks on a test-owned release gate, and the test always releases and joins
    the real worker so no daemon thread outlives the case."""

    release = threading.Event()

    async def stuck_stream(settings, file) -> AsyncIterator[dict]:
        yield {"type": "progress_start", "stage": "layout_analysis"}
        release.wait(timeout=30)

    stream = None
    try:
        with patch("pdf_reader.translation_orchestrator.do_translate_async_stream", stuck_stream):
            stream = run_translation(MagicMock(), "fake.pdf")
            assert isinstance(next(stream), dict)
            stream.cancel()
            stream.join(timeout=0.3)

        assert stream.is_alive
    finally:
        release.set()
        if stream is not None:
            stream.join(timeout=5.0)
            assert not stream.is_alive


def test_translation_stream_heartbeat_when_worker_silent():
    """Empty queue yields heartbeat strings, not a terminal state."""

    async def slow_stream(settings, file) -> AsyncIterator[dict]:
        await asyncio.sleep(5)
        yield {"type": "progress_start", "stage": "layout_analysis"}

    with patch("pdf_reader.translation_orchestrator.do_translate_async_stream", slow_stream):
        with patch("pdf_reader.translation_orchestrator.QUEUE_POLL_TIMEOUT", 0.05):
            stream = run_translation(MagicMock(), "fake.pdf")
            first = next(stream)

    assert first == ""
