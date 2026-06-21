import io
import contextlib
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import debug_trace


def test_trace_logger_exists():
    assert isinstance(debug_trace.trace_logger, logging.Logger)
    assert debug_trace.trace_logger.name == "pdf_reader.debug_trace"
    assert debug_trace.trace_logger.level == logging.INFO


def test_log_step_no_op_when_debug_false():
    with patch("debug_trace.config") as mock_config:
        mock_config.DEBUG = False
        with patch.object(debug_trace.trace_logger, "info") as mock_info:
            debug_trace.log_step("test step %d", 1)
            mock_info.assert_not_called()


def test_log_step_logs_when_debug_true():
    with patch("debug_trace.config") as mock_config:
        mock_config.DEBUG = True
        with patch.object(debug_trace.trace_logger, "info") as mock_info:
            debug_trace.log_step("test step %d", 1)
            mock_info.assert_called_once_with("[step] test step %d", 1)


def test_setup_file_handler_returns_none_when_no_glossary_path():
    with patch("debug_trace.config") as mock_config:
        mock_config.DEBUG = True
        result = debug_trace.setup_file_handler(None, 0)
        assert result is None


def test_setup_file_handler_returns_none_when_debug_false():
    with patch("debug_trace.config") as mock_config:
        mock_config.DEBUG = False
        result = debug_trace.setup_file_handler(Path("/some/path"), 0)
        assert result is None


def test_cleanup_file_handler_none_is_noop():
    debug_trace.cleanup_file_handler(None)


def test_cleanup_file_handler_removes_and_closes():
    handler = MagicMock(spec=logging.FileHandler)
    with patch.object(debug_trace.trace_logger, "removeHandler") as mock_remove:
        debug_trace.cleanup_file_handler(handler)
        mock_remove.assert_called_once_with(handler)
    handler.close.assert_called_once()


def test_log_token_usage_no_op_when_empty():
    with patch("debug_trace.config") as mock_config:
        mock_config.DEBUG = True
        with patch.object(debug_trace.trace_logger, "info") as mock_info:
            debug_trace.log_token_usage({})
            mock_info.assert_not_called()


def test_log_token_usage_logs_when_has_data():
    with patch("debug_trace.config") as mock_config:
        mock_config.DEBUG = True
        token_usage = {"main": {"total": 100}, "term": {"total": 50}}
        with patch.object(debug_trace.trace_logger, "info") as mock_info:
            debug_trace.log_token_usage(token_usage)
            mock_info.assert_called_once_with("Token usage: main=%d, term=%d", 100, 50)


def test_full_debug_trace_bytes_identical(tmp_path):
    """DEBUG=True: a full trace flow produces exact expected log output."""
    glossary_path = tmp_path / "glossary"
    glossary_path.mkdir()

    buffer = io.StringIO()
    stream_handler = logging.StreamHandler(buffer)
    stream_handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s:%(name)s:%(message)s"
    ))

    original_handlers = list(debug_trace.trace_logger.handlers)
    for h in original_handlers:
        debug_trace.trace_logger.removeHandler(h)
    debug_trace.trace_logger.addHandler(stream_handler)

    try:
        with patch("debug_trace.config") as mock_config:
            mock_config.DEBUG = True

            handler = debug_trace.setup_file_handler(glossary_path, page=1)

            debug_trace.log_step("submit translate page %d", 1)
            debug_trace.log_step("translate page %d done (%.2fs)", 1, 1.23)
            debug_trace.log_token_usage({"main": {"total": 100}, "term": {"total": 50}})
            debug_trace.log_step("merge glossary for page %d", 1)
            debug_trace.log_step("merge glossary done (%.2fs)", 0.02)

            debug_trace.cleanup_file_handler(handler)
    finally:
        debug_trace.trace_logger.removeHandler(stream_handler)
        for h in original_handlers:
            debug_trace.trace_logger.addHandler(h)

    output = buffer.getvalue()

    assert "[step] submit translate page 1" in output
    assert "[step] translate page 1 done (1.23s)" in output
    assert "Token usage: main=100, term=50" in output
    assert "[step] merge glossary for page 1" in output
    assert "[step] merge glossary done (0.02s)" in output
    assert "=== Debug session start: page 1 ===" in output

    log_file = glossary_path / "debug_trace.log"
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "=== Debug session start: page 1 ===" in content


def test_zero_overhead_no_io_when_debug_false(tmp_path):
    """DEBUG=False: log_step, log_token_usage, setup_file_handler produce no IO."""
    glossary_path = tmp_path / "glossary"
    glossary_path.mkdir()

    buffer = io.StringIO()
    stream_handler = logging.StreamHandler(buffer)
    stream_handler.setFormatter(logging.Formatter("%(message)s"))

    original_handlers = list(debug_trace.trace_logger.handlers)
    for h in original_handlers:
        debug_trace.trace_logger.removeHandler(h)
    debug_trace.trace_logger.addHandler(stream_handler)

    try:
        with patch("debug_trace.config") as mock_config:
            mock_config.DEBUG = False

            handler = debug_trace.setup_file_handler(glossary_path, page=1)
            debug_trace.log_step("submit translate page %d", 1)
            debug_trace.log_token_usage({"main": {"total": 100}})
            debug_trace.cleanup_file_handler(handler)
    finally:
        debug_trace.trace_logger.removeHandler(stream_handler)
        for h in original_handlers:
            debug_trace.trace_logger.addHandler(h)

    output = buffer.getvalue()
    assert output == ""

    log_file = glossary_path / "debug_trace.log"
    assert not log_file.exists()
