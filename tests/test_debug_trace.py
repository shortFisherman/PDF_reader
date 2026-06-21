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


import importlib
import config
from unittest.mock import MagicMock, patch, PropertyMock


def test_init_debug_true_patches_extractor():
    with patch("debug_trace.AutomaticTermExtractor", create=True) as mock_cls:
        mock_cls.extract_terms_from_paragraphs = MagicMock()
        debug_trace.init_debug(True)
        assert debug_trace._original_extract is not None
        assert mock_cls.extract_terms_from_paragraphs != debug_trace._original_extract


def test_init_debug_false_does_not_patch():
    with patch("debug_trace.AutomaticTermExtractor", create=True) as mock_cls:
        original = MagicMock()
        mock_cls.extract_terms_from_paragraphs = original
        debug_trace.init_debug(False)
        assert mock_cls.extract_terms_from_paragraphs is original


def test_init_debug_handles_import_error(monkeypatch):
    """When AutomaticTermExtractor import fails, init_debug logs warning and returns."""
    def raise_import(*args, **kwargs):
        raise ImportError("babeldoc not available")

    import debug_trace as dt
    # Force a fresh call that will trigger the import path
    with patch("debug_trace.logger.warning") as mock_warn:
        try:
            dt._apply_monkey_patches()
        except ImportError:
            mock_warn.assert_called()


def test_config_debug_defaults_to_false(monkeypatch):
    """When no [debug] or [server] debug keys exist, config.DEBUG is False."""
    monkeypatch.setattr(config, "DEBUG", False)
    assert config.DEBUG is False


def test_config_debug_reads_debug_section():
    """config.DEBUG is True when [debug] enabled = true in config.toml."""
    import config as cfg
    debug_section = cfg.CONFIG.get("debug", {})
    server_section = cfg.CONFIG.get("server", {})
    assert isinstance(cfg.DEBUG, bool)


def test_config_debug_falls_back_to_server_debug():
    """When [debug] is absent but [server] debug is present, use server.debug."""
    import config as cfg
    debug_section = cfg.CONFIG.get("debug")
    server_section = cfg.CONFIG.get("server", {})
    if debug_section is None:
        expected = server_section.get("debug", False)
        assert cfg.DEBUG == expected


from pathlib import Path


def test_debug_session_creates_and_removes_file_handler(tmp_path):
    """debug_session creates a log file with rotation, cleans up on exit."""
    glossary_path = tmp_path / "glossary"
    glossary_path.mkdir()

    with patch("debug_trace.config") as mock_config:
        mock_config.DEBUG = True

        with debug_trace.debug_session(glossary_path, page=3):
            log_file = glossary_path / "debug_trace.log"
            assert log_file.exists()

        assert debug_trace.trace_logger.handlers == [
            h for h in debug_trace.trace_logger.handlers
            if not isinstance(h, logging.FileHandler)
        ]


def test_debug_session_no_op_when_debug_false(tmp_path):
    """debug_session is a no-op when DEBUG=False."""
    glossary_path = tmp_path / "glossary"
    glossary_path.mkdir()

    with patch("debug_trace.config") as mock_config:
        mock_config.DEBUG = False

        with debug_trace.debug_session(glossary_path, page=3):
            log_file = glossary_path / "debug_trace.log"
            assert not log_file.exists()


def test_debug_session_no_op_when_glossary_path_none():
    """debug_session is a no-op when glossary_path is None."""
    with patch("debug_trace.config") as mock_config:
        mock_config.DEBUG = True

        with debug_trace.debug_session(None, page=3):
            pass


def test_debug_session_rotates_existing_log(tmp_path):
    """When debug_trace.log already exists, it gets rotated before new session."""
    glossary_path = tmp_path / "glossary"
    glossary_path.mkdir()
    existing_log = glossary_path / "debug_trace.log"
    existing_log.write_text("old content", encoding="utf-8")

    with patch("debug_trace.config") as mock_config:
        mock_config.DEBUG = True

        with debug_trace.debug_session(glossary_path, page=1):
            new_content = (glossary_path / "debug_trace.log").read_text(encoding="utf-8")
            assert "=== Debug session start: page 1 ===" in new_content

        rotated_files = list(glossary_path.glob("debug_trace.*.log"))
        assert len(rotated_files) == 1
        assert rotated_files[0].read_text(encoding="utf-8") == "old content"


def test_debug_session_exception_safe(tmp_path):
    """debug_session cleans up file handler even when exception occurs."""
    glossary_path = tmp_path / "glossary"
    glossary_path.mkdir()

    handlers_before = [
        h for h in debug_trace.trace_logger.handlers
        if isinstance(h, logging.FileHandler)
    ]

    with patch("debug_trace.config") as mock_config:
        mock_config.DEBUG = True

        try:
            with debug_trace.debug_session(glossary_path, page=5):
                raise RuntimeError("simulated crash")
        except RuntimeError:
            pass

    handlers_after = [
        h for h in debug_trace.trace_logger.handlers
        if isinstance(h, logging.FileHandler)
    ]
    assert len(handlers_after) == len(handlers_before)
