import logging
from pathlib import Path
from unittest.mock import patch, MagicMock

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
            assert mock_info.call_count == 2
