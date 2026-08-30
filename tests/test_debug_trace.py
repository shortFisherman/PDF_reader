import io
import logging
import logging.handlers
import re
from collections.abc import Iterator
from unittest.mock import patch

import pytest

from pdf_reader import debug_trace, logging_config
from pdf_reader.task_logging import TaskContext, task_log_context


@pytest.fixture(autouse=True)
def _cleanup_logging() -> Iterator[None]:
    logging_config.reset_logging()
    yield
    logging_config.reset_logging()


def _trace_handlers(logger_name: str) -> list[logging.Handler]:
    return [
        h
        for h in logging.getLogger(logger_name).handlers
        if isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", "").endswith("debug_trace.log")
    ]


def test_trace_logger_exists():
    assert isinstance(debug_trace.trace_logger, logging.Logger)
    assert debug_trace.trace_logger.name == "pdf_reader.debug_trace"
    assert debug_trace.trace_logger.level == logging.NOTSET


def test_log_step_logs_info_when_debug_false():
    """log_step produces INFO output even when config.DEBUG is False."""
    with patch.object(debug_trace.logger, "log") as mock_log:
        debug_trace.log_step("test step %d", 1)
        mock_log.assert_called_once_with(logging.INFO, "[step] test step %d", 1)


def test_log_step_logs_info():
    with patch.object(debug_trace.logger, "log") as mock_log:
        debug_trace.log_step("test step %d", 1)
        mock_log.assert_called_once_with(logging.INFO, "[step] test step %d", 1)


def test_log_token_usage_no_op_when_empty():
    with patch.object(debug_trace.logger, "debug") as mock_debug:
        debug_trace.log_token_usage({})
        mock_debug.assert_not_called()


def test_log_token_usage_logs_when_has_data():
    token_usage = {"main": {"total": 100}, "term": {"total": 50}}
    with patch.object(debug_trace.logger, "log") as mock_log:
        debug_trace.log_token_usage(token_usage)
        mock_log.assert_called_once_with(logging.DEBUG, "Token usage: main=%d, term=%d", 100, 50)


def test_log_glossary_merge_logs_info_always():
    with patch.object(debug_trace.logger, "log") as mock_log:
        debug_trace.log_glossary_merge("merge_done", page=1, elapsed=0.02, entries=5)
        mock_log.assert_called_once()
        call_args = mock_log.call_args
        assert call_args[0][0] == logging.INFO
        assert "merge_done" in str(call_args)


def test_log_glossary_merge_logs_info_even_when_debug_false():
    with patch.object(debug_trace.logger, "log") as mock_log:
        debug_trace.log_glossary_merge("merge_done", page=1)
        mock_log.assert_called_once()


def test_level_stratification_when_debug_false():
    """log_step(INFO) 可见；log_token_usage(DEBUG) 被抑制。"""
    buffer = io.StringIO()
    stream_handler = logging.StreamHandler(buffer)
    stream_handler.setFormatter(logging.Formatter("%(message)s"))

    original_handlers = list(debug_trace.trace_logger.handlers)
    for h in original_handlers:
        debug_trace.trace_logger.removeHandler(h)
    debug_trace.trace_logger.addHandler(stream_handler)
    debug_trace.trace_logger.setLevel(logging.INFO)
    try:
        debug_trace.log_step("submit translate page %d", 1)
        debug_trace.log_token_usage({"main": {"total": 100}})
    finally:
        debug_trace.trace_logger.removeHandler(stream_handler)
        debug_trace.trace_logger.setLevel(logging.NOTSET)
        for h in original_handlers:
            debug_trace.trace_logger.addHandler(h)

    output = buffer.getvalue()
    assert "[step] submit translate page 1" in output
    assert "Token usage" not in output


def test_debug_session_no_op_when_debug_false(tmp_path):
    """debug=False 必须无 IO：不创建目录也不创建文件。"""
    target = tmp_path / "missing" / "hash"
    with debug_trace.debug_session(target, page=3, debug=False):
        assert not target.exists()
    assert not target.exists()
    assert not (target / "debug_trace.log").exists()


def test_debug_session_no_op_when_glossary_path_none():
    with debug_trace.debug_session(None, page=3, debug=True):
        pass


def test_debug_session_creates_file_and_detaches_handler(tmp_path):
    glossary_path = tmp_path / "cache" / "hash"
    with debug_trace.debug_session(glossary_path, page=3, job_id="job-1", debug=True):
        assert (glossary_path / "debug_trace.log").exists()
        assert len(_trace_handlers("pdf_reader")) == 1

    for name in ("pdf_reader", "werkzeug", "pdf2zh_next", "babeldoc"):
        assert _trace_handlers(name) == [], f"trace handler leaked on {name}"


def test_debug_session_records_start_end_and_elapsed(tmp_path):
    with patch("pdf_reader.logging_config.LOG_DIR", tmp_path / "logs"):
        logging_config.setup_logging(True)

    glossary_path = tmp_path / "cache" / "hash"
    with debug_trace.debug_session(glossary_path, page=1, job_id="job-abc", debug=True):
        pass

    content = (glossary_path / "debug_trace.log").read_text(encoding="utf-8")
    assert "=== Debug session start: page=2 job=job-abc ===" in content
    assert re.search(r"=== Debug session end: page=2 job=job-abc elapsed=\d+\.\d{3}s ===", content)
    assert content.index("Debug session start") < content.index("Debug session end")


def test_debug_session_captures_pdf_reader_and_third_party_logs(tmp_path):
    """会话内 pdf_reader + 三个第三方 logger 均写入同一 debug_trace.log，不重复且脱敏。"""
    with patch("pdf_reader.logging_config.LOG_DIR", tmp_path / "logs"):
        logging_config.setup_logging(True)

    glossary_path = tmp_path / "cache" / "hash"
    session_ctx = TaskContext(job_id="job-1", document_id="doc-1", pdf_hash="hash-1")
    with debug_trace.debug_session(glossary_path, page=0, job_id="job-1", debug=True):
        with task_log_context(session_ctx):
            logging.getLogger("pdf_reader.app").info("pdf-trace-marker-001")
            logging.getLogger("werkzeug").warning("werkzeug-trace-marker-002")
            logging.getLogger("pdf2zh_next").warning("pdf2zh-trace-marker-003")
            logging.getLogger("babeldoc").warning("babeldoc-trace-marker-004")
            logging.getLogger("werkzeug").warning("secret api_key=sk-trace-secret-999 prompt=do not log this prompt")

    content = (glossary_path / "debug_trace.log").read_text(encoding="utf-8")
    for marker in (
        "pdf-trace-marker-001",
        "werkzeug-trace-marker-002",
        "pdf2zh-trace-marker-003",
        "babeldoc-trace-marker-004",
    ):
        assert content.count(marker) == 1, f"{marker} should appear exactly once"
    assert "sk-trace-secret-999" not in content
    assert "do not log this prompt" not in content
    assert "prompt=<redacted>" in content


def test_debug_session_trace_format_has_iso_metadata(tmp_path):
    """debug trace 行使用与主日志相同的 ISO 风格元数据与 run_id。"""
    with patch("pdf_reader.logging_config.LOG_DIR", tmp_path / "logs"):
        logging_config.setup_logging(True)

    glossary_path = tmp_path / "cache" / "hash"
    with debug_trace.debug_session(glossary_path, page=0, job_id="job-fmt", debug=True):
        pass

    run_id = logging_config.get_run_id()
    line = (glossary_path / "debug_trace.log").read_text(encoding="utf-8").strip().splitlines()[0]
    pattern = re.compile(
        rf"^\d{{4}}-\d{{2}}-\d{{2}}T\d{{2}}:\d{{2}}:\d{{2}}\.\d{{3}}(?:[+-]\d{{4}})? "
        rf"INFO run_id={run_id} pid=\d+ thread=[^\s]+ logger=pdf_reader\.debug_trace "
        r"\[=== Debug session start: page=1 job=job-fmt ===\]$"
    )
    assert pattern.match(line), line


def test_debug_session_exception_logs_traceback_and_reraises(tmp_path):
    """异常时保留 traceback 写入 trace 文件，清理 handler 后重新抛出。"""
    with patch("pdf_reader.logging_config.LOG_DIR", tmp_path / "logs"):
        logging_config.setup_logging(True)

    glossary_path = tmp_path / "cache" / "hash"
    with pytest.raises(RuntimeError, match="simulated crash"):
        with debug_trace.debug_session(glossary_path, page=5, job_id="job-err", debug=True):
            raise RuntimeError("simulated crash sk-secret-321")

    content = (glossary_path / "debug_trace.log").read_text(encoding="utf-8")
    assert "=== Debug session failed: page=6 job=job-err ===" in content
    assert "Traceback" in content
    assert "RuntimeError" in content
    assert "sk-secret-321" not in content
    assert "=== Debug session end: page=6 job=job-err" in content
    assert _trace_handlers("pdf_reader") == []


def test_debug_session_existing_log_is_appended_not_timestamp_rotated(tmp_path):
    """已有 debug_trace.log 直接追加，不再生成无限 timestamp 历史文件。"""
    with patch("pdf_reader.logging_config.LOG_DIR", tmp_path / "logs"):
        logging_config.setup_logging(True)

    glossary_path = tmp_path / "cache" / "hash"
    glossary_path.mkdir(parents=True)
    (glossary_path / "debug_trace.log").write_text("old content\n", encoding="utf-8")

    with debug_trace.debug_session(glossary_path, page=1, job_id="job-x", debug=True):
        pass

    content = (glossary_path / "debug_trace.log").read_text(encoding="utf-8")
    assert "old content" in content
    assert "=== Debug session start: page=2 job=job-x ===" in content
    assert not list(glossary_path.glob("debug_trace.*.log"))


def test_debug_session_rotates_bounded(tmp_path, monkeypatch):
    """debug_trace.log 使用有界 RotatingFileHandler（2MB/3 备份配置可测）。"""
    monkeypatch.setattr(debug_trace, "TRACE_LOG_MAX_BYTES", 300)
    monkeypatch.setattr(debug_trace, "TRACE_LOG_BACKUP_COUNT", 3)
    with patch("pdf_reader.logging_config.LOG_DIR", tmp_path / "logs"):
        logging_config.setup_logging(True)

    glossary_path = tmp_path / "cache" / "hash"
    with debug_trace.debug_session(glossary_path, page=0, job_id="job-rot", debug=True):
        with task_log_context(TaskContext(job_id="job-rot", document_id="d", pdf_hash="h")):
            logger = logging.getLogger("pdf_reader.app")
            for i in range(40):
                logger.warning("rotation-line-%03d %s", i, "x" * 200)

    files = [p.name for p in glossary_path.iterdir()]
    assert "debug_trace.log" in files
    backups = [name for name in files if re.fullmatch(r"debug_trace\.log\.\d+", name)]
    assert backups
    assert all(int(name.rsplit(".", 1)[1]) <= 3 for name in backups)
    assert not [name for name in files if re.fullmatch(r"debug_trace\.\d{8}_\d{6}\.log", name)]


def test_debug_session_job_filter_accepts_only_matching_context(tmp_path):
    """生产传入 job_id 时，仅接受当前 TaskContext.job_id 匹配的 pdf_reader/第三方记录。"""
    with patch("pdf_reader.logging_config.LOG_DIR", tmp_path / "logs"):
        logging_config.setup_logging(True)

    glossary_path = tmp_path / "cache" / "hash"
    matching = TaskContext(job_id="job-match", document_id="doc-m", pdf_hash="hash-m")
    other = TaskContext(job_id="job-other", document_id="doc-o", pdf_hash="hash-o")
    with debug_trace.debug_session(glossary_path, page=0, job_id="job-match", debug=True):
        with task_log_context(matching):
            logging.getLogger("pdf_reader.app").info("pdf-match-marker-001")
            logging.getLogger("pdf2zh_next").warning("pdf2zh-match-marker-002")
            logging.getLogger("babeldoc").warning("babeldoc-match-marker-003")
        with task_log_context(other):
            logging.getLogger("pdf_reader.app").info("pdf-other-marker-004")
            logging.getLogger("pdf2zh_next").warning("pdf2zh-other-marker-005")
        logging.getLogger("werkzeug").warning("no-context-marker-006")

    content = (glossary_path / "debug_trace.log").read_text(encoding="utf-8")
    for marker in ("pdf-match-marker-001", "pdf2zh-match-marker-002", "babeldoc-match-marker-003"):
        assert content.count(marker) == 1, f"{marker} should appear exactly once"
    assert "pdf-other-marker-004" not in content
    assert "pdf2zh-other-marker-005" not in content
    assert "no-context-marker-006" not in content
    assert "=== Debug session start: page=1 job=job-match ===" in content
    assert "=== Debug session end: page=1 job=job-match" in content


def test_debug_session_job_filter_none_accepts_all(tmp_path):
    """job_id=None 兼容：会话内全部记录均接受。"""
    with patch("pdf_reader.logging_config.LOG_DIR", tmp_path / "logs"):
        logging_config.setup_logging(True)

    glossary_path = tmp_path / "cache" / "hash"
    with debug_trace.debug_session(glossary_path, page=0, job_id=None, debug=True):
        logging.getLogger("pdf_reader.app").info("none-filter-marker-001")
        logging.getLogger("babeldoc").warning("none-filter-marker-002")

    content = (glossary_path / "debug_trace.log").read_text(encoding="utf-8")
    assert "none-filter-marker-001" in content
    assert "none-filter-marker-002" in content
    assert "=== Debug session start: page=1 job=- ===" in content


def test_debug_session_continues_when_trace_path_uncreatable(tmp_path):
    """目录/文件 handler 创建失败只写主日志 WARNING+traceback，业务继续。"""
    with patch("pdf_reader.logging_config.LOG_DIR", tmp_path / "logs"):
        logging_config.setup_logging(True)

    blocker = tmp_path / "blocker"
    blocker.write_text("occupied", encoding="utf-8")
    glossary_path = blocker / "hash"

    ran = False
    with debug_trace.debug_session(glossary_path, page=0, job_id="job-x", debug=True):
        ran = True
    assert ran is True

    content = (tmp_path / "logs" / "pdf_reader.log").read_text(encoding="utf-8")
    assert "Failed to create debug_trace.log handler" in content
    assert "Traceback" in content
    assert not (glossary_path / "debug_trace.log").exists()


def test_debug_session_logs_handler_close_failure(tmp_path, monkeypatch):
    """handler close 失败不再静默：主日志 WARNING+traceback，业务异常不被掩盖。"""
    with patch("pdf_reader.logging_config.LOG_DIR", tmp_path / "logs"):
        logging_config.setup_logging(True)

    class FailingCloseHandler(logging.handlers.RotatingFileHandler):
        def close(self) -> None:
            raise OSError("simulated close failure")

    monkeypatch.setattr(debug_trace, "RotatingFileHandler", FailingCloseHandler)
    glossary_path = tmp_path / "cache" / "hash"

    ran = False
    with debug_trace.debug_session(glossary_path, page=0, job_id="job-c", debug=True):
        ran = True
    assert ran is True

    content = (tmp_path / "logs" / "pdf_reader.log").read_text(encoding="utf-8")
    assert "Failed to close debug_trace handler" in content
    assert "simulated close failure" in content
    assert "Traceback" in content
