import logging
from logging.handlers import RotatingFileHandler
from unittest.mock import patch

import pytest

import logging_config


@pytest.fixture(autouse=True)
def _cleanup_logger():
    """每个测试后清理 pdf_reader logger 的 handler 以避免污染其他测试"""
    yield
    root = logging.getLogger("pdf_reader")
    for h in list(root.handlers):
        root.removeHandler(h)
        h.close()
    root.setLevel(logging.NOTSET)


class TestSetupLoggingInfoMode:
    def test_has_exactly_one_stream_and_one_rotating_handler(self, tmp_path):
        """setup_logging(False) 后 pdf_reader logger 恰好有 1 个 StreamHandler + 1 个 RotatingFileHandler"""
        with patch("logging_config.LOG_DIR", tmp_path / "logs"):
            logging_config.setup_logging(False)

        root = logging.getLogger("pdf_reader")
        handlers = root.handlers

        # RotatingFileHandler 继承自 StreamHandler，需用 type() 精确区分
        stream_handlers = [h for h in handlers if type(h) is logging.StreamHandler]
        rotating_handlers = [h for h in handlers if isinstance(h, RotatingFileHandler)]

        assert len(stream_handlers) == 1
        assert len(rotating_handlers) == 1
        assert len(handlers) == 2

    def test_root_level_is_info_when_debug_false(self, tmp_path):
        """debug=False 时 pdf_reader logger 级别为 INFO"""
        with patch("logging_config.LOG_DIR", tmp_path / "logs"):
            logging_config.setup_logging(False)

        root = logging.getLogger("pdf_reader")
        assert root.level == logging.INFO

    def test_stream_handler_level_is_info_when_debug_false(self, tmp_path):
        """debug=False 时 StreamHandler 级别为 INFO"""
        with patch("logging_config.LOG_DIR", tmp_path / "logs"):
            logging_config.setup_logging(False)

        root = logging.getLogger("pdf_reader")
        stream = [h for h in root.handlers if isinstance(h, logging.StreamHandler)][0]
        assert stream.level == logging.INFO

    def test_formatter_format_string(self, tmp_path):
        """formatter 使用指定的格式字符串"""
        with patch("logging_config.LOG_DIR", tmp_path / "logs"):
            logging_config.setup_logging(False)

        root = logging.getLogger("pdf_reader")
        expected_fmt = "%(asctime)s %(levelname)s %(name)s [%(message)s]"

        for handler in root.handlers:
            fmt = handler.formatter
            assert fmt is not None
            # logging.Formatter 内部将用户传入的 fmt 字符串存储为 _fmt；直接比较 _fmt
            assert fmt._fmt == expected_fmt


class TestSetupLoggingDebugMode:
    def test_root_level_is_debug_when_debug_true(self, tmp_path):
        """debug=True 时 pdf_reader logger 级别为 DEBUG"""
        with patch("logging_config.LOG_DIR", tmp_path / "logs"):
            logging_config.setup_logging(True)

        root = logging.getLogger("pdf_reader")
        assert root.level == logging.DEBUG

    def test_stream_handler_level_is_debug_when_debug_true(self, tmp_path):
        """debug=True 时 StreamHandler 级别为 DEBUG"""
        with patch("logging_config.LOG_DIR", tmp_path / "logs"):
            logging_config.setup_logging(True)

        root = logging.getLogger("pdf_reader")
        stream = [h for h in root.handlers if isinstance(h, logging.StreamHandler)][0]
        assert stream.level == logging.DEBUG


class TestSetupLoggingIdempotent:
    def test_calling_setup_logging_twice_does_not_double_handlers(self, tmp_path):
        """重复调用 setup_logging 不会增加 handler 数量"""
        with patch("logging_config.LOG_DIR", tmp_path / "logs"):
            logging_config.setup_logging(False)
            logging_config.setup_logging(False)

        root = logging.getLogger("pdf_reader")
        stream_handlers = [h for h in root.handlers if type(h) is logging.StreamHandler]
        rotating_handlers = [h for h in root.handlers if isinstance(h, RotatingFileHandler)]

        assert len(stream_handlers) == 1
        assert len(rotating_handlers) == 1
