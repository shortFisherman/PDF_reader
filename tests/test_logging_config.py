import io
import logging
import os
import re
import sys
import threading
import time
from collections.abc import Iterator
from logging.handlers import RotatingFileHandler
from pathlib import Path
from unittest.mock import patch

import pytest

from pdf_reader import config, debug_trace, logging_config


def _injected_config_snapshot(cache_dir: Path) -> dict:
    """显式注入的配置快照：build_app_settings 消费的是模块 import 期从
    config.toml 加载的 CONFIG 快照，而不是被 monkeypatch 的模块常量；
    因此测试必须替换 config.CONFIG 才能不依赖本地 config.toml（CI 没有）。"""
    return {
        "model": {
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "api_key": "sk-secret-test-123",
        },
        "pdf_reader": {"dpi": 200, "cache_dir": str(cache_dir)},
        "translation": {"lang_in": "en", "lang_out": "zh"},
    }


@pytest.fixture(autouse=True)
def _cleanup_logging() -> Iterator[None]:
    """每个测试前后清理托管 logger 的状态，保证隔离可靠。"""
    logging_config.reset_logging()
    yield
    logging_config.reset_logging()


def _managed_logger_names() -> tuple[str, ...]:
    return ("pdf_reader", "werkzeug", "pdf2zh_next", "babeldoc")


def _handlers_of(logger_name: str) -> list[logging.Handler]:
    return logging.getLogger(logger_name).handlers


class TestSetupLoggingInfoMode:
    def test_has_exactly_one_stream_and_one_rotating_handler(self, tmp_path):
        """setup_logging(False) 后 pdf_reader logger 恰好有 1 个 StreamHandler + 1 个 RotatingFileHandler"""
        with patch("pdf_reader.logging_config.LOG_DIR", tmp_path / "logs"):
            logging_config.setup_logging(False)

        root = logging.getLogger("pdf_reader")
        handlers = root.handlers

        stream_handlers = [h for h in handlers if type(h) is logging.StreamHandler]
        rotating_handlers = [h for h in handlers if isinstance(h, RotatingFileHandler)]

        assert len(stream_handlers) == 1
        assert len(rotating_handlers) == 1
        assert len(handlers) == 2

    def test_third_party_loggers_share_the_same_handler_instances(self, tmp_path):
        """同一对控制台/RotatingFileHandler 实例统一接入四个托管 logger"""
        with patch("pdf_reader.logging_config.LOG_DIR", tmp_path / "logs"):
            logging_config.setup_logging(False)

        pdf_handlers = set(_handlers_of("pdf_reader"))
        for name in _managed_logger_names()[1:]:
            assert set(_handlers_of(name)) == pdf_handlers

    def test_rotating_handler_configuration(self, tmp_path):
        """主日志 128 KiB、5 份备份、UTF-8；文件 handler 放行 DEBUG"""
        with patch("pdf_reader.logging_config.LOG_DIR", tmp_path / "logs"):
            logging_config.setup_logging(False)

        rotating = [h for h in _handlers_of("pdf_reader") if isinstance(h, RotatingFileHandler)][0]
        assert isinstance(rotating, logging_config.RetentionRotatingFileHandler)
        assert rotating.maxBytes == 128 * 1024
        assert rotating.backupCount == 5
        assert rotating.encoding == "utf-8"
        assert rotating.level == logging.DEBUG

    def test_root_level_is_info_when_debug_false(self, tmp_path):
        with patch("pdf_reader.logging_config.LOG_DIR", tmp_path / "logs"):
            logging_config.setup_logging(False)
        assert logging.getLogger("pdf_reader").level == logging.INFO

    def test_stream_handler_level_is_info_when_debug_false(self, tmp_path):
        with patch("pdf_reader.logging_config.LOG_DIR", tmp_path / "logs"):
            logging_config.setup_logging(False)
        stream = [h for h in _handlers_of("pdf_reader") if type(h) is logging.StreamHandler][0]
        assert stream.level == logging.INFO

    def test_formatter_uses_main_log_format(self, tmp_path):
        """所有 handler 使用同一套 SafeFormatter 与统一格式字符串"""
        with patch("pdf_reader.logging_config.LOG_DIR", tmp_path / "logs"):
            logging_config.setup_logging(False)

        formatters = {h.formatter for h in _handlers_of("pdf_reader")}
        assert len(formatters) == 1
        formatter = formatters.pop()
        assert isinstance(formatter, logging_config.PipelineSafeFormatter)
        assert formatter._fmt == logging_config.MAIN_LOG_FORMAT

    def test_log_line_has_iso_time_level_run_id_pid_thread_logger(self, tmp_path):
        """主日志行包含稳定可读的 ISO 风格元数据字段"""
        with patch("pdf_reader.logging_config.LOG_DIR", tmp_path / "logs"):
            logging_config.setup_logging(False)

        logging.getLogger("pdf_reader.app").info("metadata-marker-001")
        line = (tmp_path / "logs" / "pdf_reader.log").read_text(encoding="utf-8").strip().splitlines()[-1]

        pattern = re.compile(
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}(?:[+-]\d{4})? "
            r"INFO run_id=[0-9a-f]{12} pid=\d+ thread=[^\s]+ logger=pdf_reader\.app "
            r"\[metadata-marker-001\]$"
        )
        assert pattern.match(line), line


class TestMainLogBackupRetention:
    """主日志 128 KiB × 5 轮转 + 编号备份 14 天过期清理。"""

    @staticmethod
    def _write_with_mtime(path, content, mtime) -> None:
        path.write_text(content, encoding="utf-8")
        os.utime(path, (mtime, mtime))

    def test_setup_deletes_only_expired_pdf_reader_backups(self, tmp_path):
        """setup 启动清理：只删本日志过期编号备份，保留未过期与无关文件"""
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        now = time.time()
        old = now - 15 * 24 * 60 * 60
        fresh = now - 24 * 60 * 60

        main = log_dir / "pdf_reader.log"
        main.write_text("current log", encoding="utf-8")
        expired1 = log_dir / "pdf_reader.log.1"
        expired9 = log_dir / "pdf_reader.log.9"
        fresh2 = log_dir / "pdf_reader.log.2"
        self._write_with_mtime(expired1, "EXPIRED-1", old)
        self._write_with_mtime(expired9, "EXPIRED-9", old)
        self._write_with_mtime(fresh2, "FRESH-2", fresh)
        unrelated = [
            log_dir / "debug_trace.log",
            log_dir / "debug_trace.log.1",
            log_dir / "pdf_reader.log.bak",
            log_dir / "pdf_reader.log.0",
        ]
        for path in unrelated:
            self._write_with_mtime(path, "UNRELATED", old)

        with patch("pdf_reader.logging_config.LOG_DIR", log_dir):
            logging_config.setup_logging(False)

        assert main.is_file()
        assert not expired1.exists(), "过期编号备份应被删除"
        assert not expired9.exists(), "过期编号备份（任意编号）应被删除"
        assert fresh2.exists(), "未过期备份应保留"
        assert fresh2.stat().st_mtime > old
        for path in unrelated:
            assert path.exists(), f"无关文件应保留: {path}"

    def test_rollover_cleans_expired_backups(self, tmp_path):
        """doRollover 后清理：删除过期备份，保留未过期备份与无关文件"""
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        now = time.time()
        old = now - 15 * 24 * 60 * 60
        fresh = now - 24 * 60 * 60
        (log_dir / "pdf_reader.log").write_text("BASE", encoding="utf-8")

        handler = logging_config.RetentionRotatingFileHandler(
            str(log_dir / "pdf_reader.log"),
            maxBytes=100,
            backupCount=5,
            encoding="utf-8",
        )
        try:
            # 构造后再创建备份，专门覆盖 doRollover 路径的过期清理
            expired1 = log_dir / "pdf_reader.log.1"
            fresh2 = log_dir / "pdf_reader.log.2"
            self._write_with_mtime(expired1, "EXPIRED", old)
            self._write_with_mtime(fresh2, "FRESH", fresh)
            unrelated = [log_dir / "debug_trace.log.1", log_dir / "pdf_reader.log.bak"]
            for path in unrelated:
                self._write_with_mtime(path, "UNRELATED", old)

            handler.doRollover()
        finally:
            handler.close()

        assert not any(p.read_text(encoding="utf-8") == "EXPIRED" for p in log_dir.glob("pdf_reader.log.*"))
        assert (log_dir / "pdf_reader.log.1").read_text(encoding="utf-8") == "BASE"
        assert any(p.read_text(encoding="utf-8") == "FRESH" for p in log_dir.glob("pdf_reader.log.*"))
        for path in (log_dir / "debug_trace.log.1", log_dir / "pdf_reader.log.bak"):
            assert path.read_text(encoding="utf-8") == "UNRELATED"

    def test_setup_cleanup_failure_degrades_and_warns(self, tmp_path, capsys):
        """setup 清理失败：不抛异常、日志仍可用、只记 warning"""
        with patch("pdf_reader.logging_config._cleanup_expired_backups", return_value=["simulated setup failure"]):
            with patch("pdf_reader.logging_config.LOG_DIR", tmp_path / "logs"):
                logging_config.setup_logging(False)

        assert (tmp_path / "logs" / "pdf_reader.log").is_file()
        rotating = [h for h in _handlers_of("pdf_reader") if isinstance(h, RotatingFileHandler)]
        assert len(rotating) == 1
        assert "Failed to clean expired pdf_reader.log backups" in capsys.readouterr().out

    def test_rollover_cleanup_failure_degrades_and_warns(self, tmp_path, caplog):
        """轮转后清理失败：不抛异常、轮转仍完成、只记 warning"""
        caplog.set_level(logging.WARNING, logger="pdf_reader")
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        with patch("pdf_reader.logging_config._cleanup_expired_backups", return_value=["simulated rollover failure"]):
            handler = logging_config.RetentionRotatingFileHandler(
                str(log_dir / "pdf_reader.log"),
                maxBytes=100,
                backupCount=5,
                encoding="utf-8",
            )
            try:
                handler.doRollover()
            finally:
                handler.close()

        messages = [record.getMessage() for record in caplog.records if record.name == "pdf_reader"]
        assert any(
            "Failed to clean expired pdf_reader.log backups" in message and "simulated rollover failure" in message
            for message in messages
        )

    def test_cleanup_warning_does_not_recurse_through_same_handler(self, tmp_path, caplog):
        """清理告警经同一 handler 写入时不触发嵌套轮转/清理（无递归日志）"""
        caplog.set_level(logging.WARNING, logger="pdf_reader")
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        # Python 3.12 的 RotatingFileHandler 不轮转空文件；预填 base 使首次 emit 触发轮转
        (log_dir / "pdf_reader.log").write_text("a" * 100, encoding="utf-8")
        warning_text = "Failed to clean expired pdf_reader.log backups: persistent failure"
        with patch("pdf_reader.logging_config._cleanup_expired_backups", return_value=["persistent failure"]):
            handler = logging_config.RetentionRotatingFileHandler(
                str(log_dir / "pdf_reader.log"),
                maxBytes=1,
                backupCount=5,
                encoding="utf-8",
            )
            target = logging.getLogger("pdf_reader")
            target.addHandler(handler)
            try:
                target.warning("x" * 200)
            finally:
                target.removeHandler(handler)
                handler.close()

        messages = [record.getMessage() for record in caplog.records if record.name == "pdf_reader"]
        assert messages.count(warning_text) == 1


class TestSetupLoggingDebugMode:
    def test_root_level_is_debug_when_debug_true(self, tmp_path):
        with patch("pdf_reader.logging_config.LOG_DIR", tmp_path / "logs"):
            logging_config.setup_logging(True)
        assert logging.getLogger("pdf_reader").level == logging.DEBUG

    def test_stream_handler_level_is_debug_when_debug_true(self, tmp_path):
        with patch("pdf_reader.logging_config.LOG_DIR", tmp_path / "logs"):
            logging_config.setup_logging(True)
        stream = [h for h in _handlers_of("pdf_reader") if type(h) is logging.StreamHandler][0]
        assert stream.level == logging.DEBUG


class TestSetupLoggingIdempotent:
    def test_calling_setup_logging_twice_does_not_double_handlers(self, tmp_path):
        with patch("pdf_reader.logging_config.LOG_DIR", tmp_path / "logs"):
            logging_config.setup_logging(False)
            logging_config.setup_logging(False)

        stream_handlers = [h for h in _handlers_of("pdf_reader") if type(h) is logging.StreamHandler]
        rotating_handlers = [h for h in _handlers_of("pdf_reader") if isinstance(h, RotatingFileHandler)]
        assert len(stream_handlers) == 1
        assert len(rotating_handlers) == 1

    def test_repeated_setup_updates_levels_instead_of_short_circuit(self, tmp_path):
        """同进程用不同 debug 再调用时必须更新级别"""
        with patch("pdf_reader.logging_config.LOG_DIR", tmp_path / "logs"):
            logging_config.setup_logging(False)
            first_run_id = logging_config.get_run_id()
            assert logging.getLogger("pdf_reader").level == logging.INFO
            assert logging.getLogger("werkzeug").getEffectiveLevel() == logging.WARNING

            logging_config.setup_logging(True)
            assert logging.getLogger("pdf_reader").level == logging.DEBUG
            assert logging.getLogger("werkzeug").getEffectiveLevel() == logging.DEBUG
            stream = [h for h in _handlers_of("pdf_reader") if type(h) is logging.StreamHandler][0]
            assert stream.level == logging.DEBUG

            logging_config.setup_logging(False)
            assert logging.getLogger("pdf_reader").level == logging.INFO
            assert logging.getLogger("werkzeug").getEffectiveLevel() == logging.WARNING
            assert logging_config.get_run_id() == first_run_id


class TestRunId:
    def test_run_id_unique_per_setup_lifecycle(self, tmp_path):
        """run_id 每次 setup 生命周期唯一：重复 setup 不变，reset 后重新生成"""
        with patch("pdf_reader.logging_config.LOG_DIR", tmp_path / "logs"):
            logging_config.setup_logging(False)
            first = logging_config.get_run_id()
            assert re.fullmatch(r"[0-9a-f]{12}", first)

            logging_config.setup_logging(True)
            assert logging_config.get_run_id() == first

            logging_config.reset_logging()
            assert logging_config.get_run_id() is None

            logging_config.setup_logging(False)
            second = logging_config.get_run_id()
            assert second is not None
            assert second != first


class TestThirdPartyLoggerRouting:
    @pytest.mark.parametrize("logger_name", ["werkzeug", "pdf2zh_next", "babeldoc"])
    def test_level_is_warning_when_debug_off(self, tmp_path, logger_name):
        with patch("pdf_reader.logging_config.LOG_DIR", tmp_path / "logs"):
            logging_config.setup_logging(False)
        assert logging.getLogger(logger_name).getEffectiveLevel() == logging.WARNING
        assert logging.getLogger(logger_name).propagate is False
        assert logging.getLogger(logger_name).disabled is False

    @pytest.mark.parametrize("logger_name", ["werkzeug", "pdf2zh_next", "babeldoc"])
    def test_level_is_debug_when_debug_on(self, tmp_path, logger_name):
        with patch("pdf_reader.logging_config.LOG_DIR", tmp_path / "logs"):
            logging_config.setup_logging(True)
        assert logging.getLogger(logger_name).getEffectiveLevel() == logging.DEBUG

    def test_all_managed_loggers_propagate_false_disabled_false(self, tmp_path):
        """setup 期间四个托管 logger 均 propagate=False 且 disabled=False"""
        with patch("pdf_reader.logging_config.LOG_DIR", tmp_path / "logs"):
            logging_config.setup_logging(False)
        for name in _managed_logger_names():
            logger = logging.getLogger(name)
            assert logger.propagate is False
            assert logger.disabled is False

    def test_root_handler_receives_no_raw_records_and_no_duplicates(self, tmp_path):
        """注入 root handler：每条记录只输出一次且 root 收不到 raw"""
        root_records: list[logging.LogRecord] = []
        root_handler = logging.Handler()
        root_handler.setLevel(logging.DEBUG)
        root_handler.emit = lambda record: root_records.append(record)
        logging.getLogger().addHandler(root_handler)
        try:
            with patch("pdf_reader.logging_config.LOG_DIR", tmp_path / "logs"):
                logging_config.setup_logging(False)

            logging.getLogger("pdf_reader.app").warning("root-probe-pdf-111")
            logging.getLogger("werkzeug").warning("root-probe-wk-222")
            logging.getLogger("pdf2zh_next").warning("root-probe-pz-333")
            logging.getLogger("babeldoc").warning("root-probe-bd-444")

            content = (tmp_path / "logs" / "pdf_reader.log").read_text(encoding="utf-8")
            for marker in ("root-probe-pdf-111", "root-probe-wk-222", "root-probe-pz-333", "root-probe-bd-444"):
                assert content.count(marker) == 1, f"{marker} should appear exactly once"
            assert root_records == [], "root handler 不应收到任何托管记录"
        finally:
            logging.getLogger().removeHandler(root_handler)
            root_handler.close()

    def test_info_blocked_when_debug_off(self, tmp_path):
        with patch("pdf_reader.logging_config.LOG_DIR", tmp_path / "logs"):
            logging_config.setup_logging(False)

        wk = logging.getLogger("werkzeug")
        records = []
        handler = logging.Handler()
        handler.emit = lambda record: records.append(record)
        handler.setLevel(logging.DEBUG)
        wk.addHandler(handler)
        try:
            wk.debug("debug msg")
            wk.info("info msg")
            wk.warning("warn msg")
            assert [r.levelno for r in records] == [logging.WARNING]
        finally:
            wk.removeHandler(handler)
            handler.close()

    def test_info_passes_when_debug_on(self, tmp_path):
        with patch("pdf_reader.logging_config.LOG_DIR", tmp_path / "logs"):
            logging_config.setup_logging(True)

        wk = logging.getLogger("werkzeug")
        records = []
        handler = logging.Handler()
        handler.emit = lambda record: records.append(record)
        handler.setLevel(logging.DEBUG)
        wk.addHandler(handler)
        try:
            wk.info("info msg")
            assert [r.levelno for r in records] == [logging.INFO]
        finally:
            wk.removeHandler(handler)
            handler.close()

    @pytest.mark.parametrize("logger_name", ["werkzeug", "pdf2zh_next", "babeldoc"])
    def test_third_party_real_handler_redacts_secrets_and_prompts(self, tmp_path, logger_name):
        """第三方日志经真实 RotatingFileHandler 写入时按脱敏契约处理"""
        with patch("pdf_reader.logging_config.LOG_DIR", tmp_path / "logs"):
            logging_config.setup_logging(False)

        fake_api_key = "sk-third-party-" + "secret-001"
        sentinel = (
            f"api_key={fake_api_key} Authorization: Bearer abcdefghijklmnop "
            "prompt=translate this confidential instruction"
        )
        logging.getLogger(logger_name).warning("third party %s", sentinel)

        content = (tmp_path / "logs" / "pdf_reader.log").read_text(encoding="utf-8")
        assert fake_api_key not in content
        assert "abcdefghijklmnop" not in content
        assert "translate this confidential instruction" not in content
        assert "api_key=<redacted>" in content
        assert "Authorization: Bearer <redacted>" in content
        assert "prompt=<redacted>" in content

    def test_third_party_records_never_bypass_via_last_resort(self, tmp_path, monkeypatch):
        """托管期间第三方日志不会落入 lastResort 兜底 handler"""
        seen = []
        fallback = logging.Handler()
        fallback.setLevel(logging.DEBUG)
        fallback.emit = lambda record: seen.append(record)
        monkeypatch.setattr(logging, "lastResort", fallback)

        with patch("pdf_reader.logging_config.LOG_DIR", tmp_path / "logs"):
            logging_config.setup_logging(False)
        logging.getLogger("werkzeug").warning("must-not-hit-lastresort")

        assert seen == []

    def test_no_duplicate_output_for_managed_loggers(self, tmp_path, capsys):
        """第三方与 pdf_reader 记录在控制台与文件里各出现一次，不重复"""
        with patch("pdf_reader.logging_config.LOG_DIR", tmp_path / "logs"):
            logging_config.setup_logging(False)

        logging.getLogger("pdf_reader.app").warning("unique-pdf-marker-111")
        logging.getLogger("werkzeug").warning("unique-werkzeug-marker-222")

        content = (tmp_path / "logs" / "pdf_reader.log").read_text(encoding="utf-8")
        assert content.count("unique-pdf-marker-111") == 1
        assert content.count("unique-werkzeug-marker-222") == 1

        console = capsys.readouterr().out
        assert console.count("unique-pdf-marker-111") == 1
        assert console.count("unique-werkzeug-marker-222") == 1

    def test_reset_restores_external_handler_level_propagate_disabled(self, tmp_path):
        """既有外部 handler/level/propagate/disabled 状态在 reset 后精确恢复"""
        werkzeug = logging.getLogger("werkzeug")
        werkzeug.setLevel(logging.INFO)
        werkzeug.propagate = True
        werkzeug.disabled = True
        buffer = io.StringIO()
        external = logging.StreamHandler(buffer)
        external.setFormatter(logging.Formatter("%(message)s"))
        werkzeug.addHandler(external)
        original_handlers = list(werkzeug.handlers)
        original_level = werkzeug.level
        original_propagate = werkzeug.propagate
        original_disabled = werkzeug.disabled
        try:
            with patch("pdf_reader.logging_config.LOG_DIR", tmp_path / "logs"):
                logging_config.setup_logging(False)
            assert werkzeug.getEffectiveLevel() == logging.WARNING
            assert werkzeug.propagate is False
            assert werkzeug.disabled is False
            assert external not in werkzeug.handlers

            fake_api_key = "sk-secret-" + "before-reset-123"
            logging.getLogger("werkzeug").warning("leak %s", fake_api_key)
            assert fake_api_key not in buffer.getvalue()

            logging_config.reset_logging()
            assert werkzeug.level == original_level
            assert werkzeug.propagate is original_propagate
            assert werkzeug.disabled is original_disabled
            assert werkzeug.handlers == original_handlers

            werkzeug.disabled = False
            logging.getLogger("werkzeug").warning("after-reset-marker-333")
            assert "after-reset-marker-333" in buffer.getvalue()
        finally:
            werkzeug.removeHandler(external)
            external.close()
            werkzeug.setLevel(logging.NOTSET)
            werkzeug.propagate = True
            werkzeug.disabled = False


class TestExcepthook:
    def test_setup_installs_and_reset_restores_hooks(self, tmp_path, monkeypatch):
        sys_calls = []
        threading_calls = []

        def fake_sys(exc_type, exc_value, exc_tb) -> None:
            sys_calls.append(exc_type)

        def fake_threading(args) -> None:
            threading_calls.append(args)

        monkeypatch.setattr(sys, "excepthook", fake_sys)
        monkeypatch.setattr(threading, "excepthook", fake_threading)

        with patch("pdf_reader.logging_config.LOG_DIR", tmp_path / "logs"):
            logging_config.setup_logging(False)
        assert sys.excepthook is not fake_sys
        assert threading.excepthook is not fake_threading

        logging_config.reset_logging()
        assert sys.excepthook is fake_sys
        assert threading.excepthook is fake_threading

    def test_sys_excepthook_logs_once_redacted_and_skips_original(self, tmp_path, monkeypatch, capsys):
        """普通异常：统一日志成功写入后不再调用原 hook，stderr 无 raw secret"""
        calls = []
        monkeypatch.setattr(sys, "excepthook", lambda t, v, tb: calls.append((t, v)))
        with patch("pdf_reader.logging_config.LOG_DIR", tmp_path / "logs"):
            logging_config.setup_logging(False)

        try:
            raise RuntimeError("boom sk-secret-777 Authorization: Bearer abcdef123 prompt=top secret instruction")
        except RuntimeError:
            sys.excepthook(*sys.exc_info())

        content = (tmp_path / "logs" / "pdf_reader.log").read_text(encoding="utf-8")
        assert content.count("unhandled exception") == 1
        assert "RuntimeError" in content
        assert "sk-secret-777" not in content
        assert "abcdef123" not in content
        assert "top secret instruction" not in content
        assert "***REDACTED***" in content
        assert calls == [], "普通异常不应再调用原 hook"

        err = capsys.readouterr().err
        assert "sk-secret-777" not in err
        assert "abcdef123" not in err
        assert "top secret instruction" not in err

    def test_sys_excepthook_skips_keyboard_interrupt_log(self, tmp_path, monkeypatch):
        calls = []
        monkeypatch.setattr(sys, "excepthook", lambda t, v, tb: calls.append(t))
        with patch("pdf_reader.logging_config.LOG_DIR", tmp_path / "logs"):
            logging_config.setup_logging(False)

        try:
            raise KeyboardInterrupt()
        except KeyboardInterrupt:
            sys.excepthook(*sys.exc_info())

        content = (tmp_path / "logs" / "pdf_reader.log").read_text(encoding="utf-8")
        assert "unhandled exception" not in content
        assert calls == [KeyboardInterrupt]

    def test_sys_excepthook_falls_back_to_original_when_logging_fails(self, tmp_path, monkeypatch):
        """统一记录失败时回退原 hook，避免完全静默"""
        calls = []
        monkeypatch.setattr(sys, "excepthook", lambda t, v, tb: calls.append(t))
        with patch("pdf_reader.logging_config.LOG_DIR", tmp_path / "logs"):
            logging_config.setup_logging(False)
        monkeypatch.setattr(
            logging.getLogger("pdf_reader"),
            "error",
            lambda *a, **k: (_ for _ in ()).throw(OSError("logging down")),
        )

        try:
            raise RuntimeError("fallback sk-secret-555")
        except RuntimeError:
            sys.excepthook(*sys.exc_info())

        assert calls == [RuntimeError]
        content = (tmp_path / "logs" / "pdf_reader.log").read_text(encoding="utf-8")
        assert "unhandled exception" not in content

    def test_threading_excepthook_logs_once_redacted_and_skips_original(self, tmp_path, monkeypatch, capsys):
        """线程未捕获异常：统一日志一次且脱敏，原 threading hook 不再调用"""
        calls = []

        def fake_threading(args) -> None:
            calls.append(args)

        monkeypatch.setattr(threading, "excepthook", fake_threading)
        with patch("pdf_reader.logging_config.LOG_DIR", tmp_path / "logs"):
            logging_config.setup_logging(False)

        try:
            raise ValueError("thread boom sk-secret-888 Authorization: Bearer zyxwvutsrq prompt=thread secret")
        except ValueError:
            args = threading.ExceptHookArgs([*sys.exc_info(), threading.current_thread()])
        threading.excepthook(args)

        content = (tmp_path / "logs" / "pdf_reader.log").read_text(encoding="utf-8")
        assert content.count("unhandled exception") == 1
        assert "ValueError" in content
        assert "sk-secret-888" not in content
        assert "zyxwvutsrq" not in content
        assert "thread secret" not in content
        assert calls == [], "普通线程异常不应再调用原 hook"

        err = capsys.readouterr().err
        assert "sk-secret-888" not in err
        assert "zyxwvutsrq" not in err
        assert "thread secret" not in err

    def test_threading_excepthook_skips_system_exit_log(self, tmp_path, monkeypatch):
        calls = []
        monkeypatch.setattr(threading, "excepthook", lambda args: calls.append(args))
        with patch("pdf_reader.logging_config.LOG_DIR", tmp_path / "logs"):
            logging_config.setup_logging(False)

        args = threading.ExceptHookArgs([SystemExit, SystemExit(1), None, threading.current_thread()])
        threading.excepthook(args)

        content = (tmp_path / "logs" / "pdf_reader.log").read_text(encoding="utf-8")
        assert "unhandled exception" not in content
        assert calls == [args]

    def test_threading_excepthook_falls_back_to_original_when_logging_fails(self, tmp_path, monkeypatch):
        calls = []
        monkeypatch.setattr(threading, "excepthook", lambda args: calls.append(args))
        with patch("pdf_reader.logging_config.LOG_DIR", tmp_path / "logs"):
            logging_config.setup_logging(False)
        monkeypatch.setattr(
            logging.getLogger("pdf_reader"),
            "error",
            lambda *a, **k: (_ for _ in ()).throw(OSError("logging down")),
        )

        args = threading.ExceptHookArgs([RuntimeError, RuntimeError("boom"), None, threading.current_thread()])
        threading.excepthook(args)

        assert len(calls) == 1
        content = (tmp_path / "logs" / "pdf_reader.log").read_text(encoding="utf-8")
        assert "unhandled exception" not in content


class TestConcurrency:
    def test_concurrent_setup_reset_no_errors_no_duplicate_handlers(self, tmp_path, monkeypatch):
        """并发 setup/reset 无异常、无重复 handler"""
        monkeypatch.setattr(logging_config, "LOG_DIR", tmp_path / "logs")
        errors: list[Exception] = []

        def worker(seed: int) -> None:
            try:
                for i in range(20):
                    logging_config.setup_logging((seed + i) % 2 == 0)
                    logging_config.reset_logging()
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert errors == []
        logging_config.reset_logging()
        logging_config.setup_logging(False)
        stream_handlers = [h for h in _handlers_of("pdf_reader") if type(h) is logging.StreamHandler]
        rotating_handlers = [h for h in _handlers_of("pdf_reader") if isinstance(h, RotatingFileHandler)]
        assert len(stream_handlers) == 1
        assert len(rotating_handlers) == 1

    def test_concurrent_attach_detach_no_errors_no_duplicates(self, tmp_path):
        with patch("pdf_reader.logging_config.LOG_DIR", tmp_path / "logs"):
            logging_config.setup_logging(False)

        probe = logging.Handler()
        errors: list[Exception] = []

        def worker() -> None:
            try:
                for _ in range(40):
                    logging_config.attach_handler(probe, ["werkzeug"])
                    logging_config.detach_handler(probe, ["werkzeug"])
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert errors == []
        assert probe not in logging.getLogger("werkzeug").handlers
        probe.close()

    def test_attach_handler_never_duplicates_instance(self, tmp_path):
        with patch("pdf_reader.logging_config.LOG_DIR", tmp_path / "logs"):
            logging_config.setup_logging(False)

        probe = logging.Handler()
        try:
            for _ in range(3):
                logging_config.attach_handler(probe, ["werkzeug"])
            assert logging.getLogger("werkzeug").handlers.count(probe) == 1
        finally:
            logging_config.detach_handler(probe, ["werkzeug"])
            probe.close()


class TestApiKeyNeverLogged:
    """验证 api_key 与 prompt 绝不会出现在任何日志记录中"""

    def test_api_key_not_in_startup_log(self, monkeypatch, tmp_path):
        monkeypatch.setattr(config, "MODEL_API_KEY", "sk-secret-test-123")
        monkeypatch.setattr(config, "MODEL_PROVIDER", "deepseek")
        monkeypatch.setattr(config, "MODEL", "deepseek-v4-flash")
        monkeypatch.setattr(config, "TRANSLATION_LANG_IN", "en")
        monkeypatch.setattr(config, "TRANSLATION_LANG_OUT", "zh")
        monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
        monkeypatch.setattr(config, "DPI", 200)
        monkeypatch.setattr(config, "DEBUG", False)
        monkeypatch.setattr(config, "CONFIG", _injected_config_snapshot(tmp_path / "cache"))

        with patch("pdf_reader.logging_config.LOG_DIR", tmp_path / "logs"):
            logging_config.setup_logging(False)

        captured: list[str] = []
        handler = logging.Handler()
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler.emit = lambda record: captured.append(handler.format(record))
        app_logger = logging.getLogger("pdf_reader.app")
        app_logger.addHandler(handler)
        try:
            from pdf_reader import app as app_module

            app_module.create_app(config.build_app_settings())
        finally:
            app_logger.removeHandler(handler)
            handler.close()

        messages = "\n".join(captured)
        assert messages, "expected at least one startup log"
        assert "sk-secret-test-123" not in messages, "API key leaked in startup log"
        assert "provider=deepseek" in messages
        assert "model=deepseek-v4-flash" in messages

    def test_no_api_key_value_in_main_log(self, monkeypatch, tmp_path):
        monkeypatch.setattr(config, "MODEL_API_KEY", "sk-secret-test-123")
        monkeypatch.setattr(config, "MODEL_PROVIDER", "deepseek")
        monkeypatch.setattr(config, "MODEL", "deepseek-v4-flash")
        monkeypatch.setattr(config, "TRANSLATION_LANG_IN", "en")
        monkeypatch.setattr(config, "TRANSLATION_LANG_OUT", "zh")
        monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
        monkeypatch.setattr(config, "DPI", 200)
        monkeypatch.setattr(config, "DEBUG", False)
        monkeypatch.setattr(config, "CONFIG", _injected_config_snapshot(tmp_path / "cache"))

        with patch("pdf_reader.logging_config.LOG_DIR", tmp_path / "logs"):
            logging_config.setup_logging(False)

        from pdf_reader import app as app_module

        app_module.create_app(config.build_app_settings())

        content = (tmp_path / "logs" / "pdf_reader.log").read_text(encoding="utf-8")
        assert "sk-secret-test-123" not in content

    def test_debug_trace_functions_never_log_api_key(self, monkeypatch):
        monkeypatch.setattr(config, "MODEL_API_KEY", "sk-secret-test-123")
        captured: list[str] = []
        handler = logging.Handler()
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler.emit = lambda record: captured.append(handler.format(record))
        trace_logger = logging.getLogger("pdf_reader.debug_trace")
        original_level = trace_logger.level
        trace_logger.addHandler(handler)
        trace_logger.setLevel(logging.DEBUG)
        try:
            debug_trace.log_step("init")
            debug_trace.log_token_usage({"main": {"total": 100}, "term": {"total": 50}})
            debug_trace.log_glossary_merge("merge_done", page=1, elapsed="0.5")
        finally:
            trace_logger.removeHandler(handler)
            trace_logger.setLevel(original_level)
            handler.close()

        assert captured, "expected debug_trace log records"
        assert all("sk-secret-test-123" not in line for line in captured)

    def test_prompt_never_enters_main_log(self, tmp_path):
        """prompt 类字段值（含带引号文本）不会进入主日志"""
        with patch("pdf_reader.logging_config.LOG_DIR", tmp_path / "logs"):
            logging_config.setup_logging(True)

        logging.getLogger("pdf_reader.app").warning(
            'translate failed user_prompt=translate "TOP SECRET PROMPT" right now'
        )
        logging.getLogger("werkzeug").warning('{"prompt": "another secret instruction"}')

        content = (tmp_path / "logs" / "pdf_reader.log").read_text(encoding="utf-8")
        assert "TOP SECRET PROMPT" not in content
        assert "another secret instruction" not in content
        assert "user_prompt=<redacted>" in content
        assert '{"prompt": "<redacted>"}' in content


class TestPromptRedactionKeepsLogStructure:
    """plain prompt 脱敏必须保留 PipelineSafeFormatter 的 [%(message)s] 尾部 ]。"""

    @pytest.mark.parametrize(
        ("message", "prompt_fragment"),
        [
            ("translate failed prompt=plain secret value", "plain secret value"),
            ("prompt=value with spaces and = and ] inside", "value with spaces and = and ] inside"),
            ("prompt=value ending with bracket]", "value ending with bracket]"),
            ('prompt="quoted secret value"', "quoted secret value"),
            ("status=ok prompt=inline secret", "inline secret"),
            ("prompt=inline secret status=ok", "inline secret status=ok"),
        ],
    )
    def test_final_line_keeps_wrapper_and_redacts_prompt(self, tmp_path, message, prompt_fragment):
        with patch("pdf_reader.logging_config.LOG_DIR", tmp_path / "logs"):
            logging_config.setup_logging(False)

        logging.getLogger("pdf_reader.app").warning("%s sk-secret-456", message)

        content = (tmp_path / "logs" / "pdf_reader.log").read_text(encoding="utf-8")
        line = content.strip().splitlines()[-1]
        assert prompt_fragment not in content
        assert "sk-secret-456" not in content
        assert line.endswith("]")
        assert re.match(
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}(?:[+-]\d{4})? "
            r"WARNING run_id=[0-9a-f]{12} pid=\d+ thread=[^\s]+ logger=pdf_reader\.app \[",
            line,
        )

    def test_multiline_message_prompt_line_redacted_and_record_closes(self, tmp_path):
        with patch("pdf_reader.logging_config.LOG_DIR", tmp_path / "logs"):
            logging_config.setup_logging(False)

        logging.getLogger("pdf_reader.app").warning("line1\nprompt=multiline secret\nline3 sk-secret-457")

        content = (tmp_path / "logs" / "pdf_reader.log").read_text(encoding="utf-8")
        assert "multiline secret" not in content
        assert "sk-secret-457" not in content
        assert "prompt=<redacted>" in content
        assert content.strip().endswith("]")
        assert re.match(r"^.* logger=pdf_reader\.app \[line1$", content.strip().splitlines()[0])

    def test_traceback_prompt_redacted_and_traceback_closes(self, tmp_path):
        with patch("pdf_reader.logging_config.LOG_DIR", tmp_path / "logs"):
            logging_config.setup_logging(False)

        try:
            raise RuntimeError("boom prompt=traceback top secret sk-secret-458")
        except RuntimeError:
            logging.getLogger("pdf_reader.app").error("task failed prompt=main secret", exc_info=True)

        content = (tmp_path / "logs" / "pdf_reader.log").read_text(encoding="utf-8")
        first_line = content.strip().splitlines()[0]
        assert "main secret" not in content
        assert "traceback top secret" not in content
        assert "sk-secret-458" not in content
        assert "prompt=<redacted>" in content
        assert first_line.endswith("[task failed prompt=<redacted>]")
        assert "RuntimeError" in content
        assert content.strip().endswith("RuntimeError: boom prompt=<redacted>")

    def test_redact_secrets_plain_prompt_without_wrapper_is_unchanged(self):
        from pdf_reader.task_logging import redact_secrets

        assert redact_secrets("prompt=secret") == "prompt=<redacted>"
        assert redact_secrets("prompt=a]b]") == "prompt=<redacted>]"
