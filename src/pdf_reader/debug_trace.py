"""按任务调试会话：写入 ``cache/<hash>/debug_trace.log`` 的有界轮转诊断文件。

``debug_session`` 在有界 RotatingFileHandler（2MB、3 份备份）上捕获会话内
``pdf_reader`` 与 ``werkzeug``/``pdf2zh_next``/``babeldoc`` 的日志，全部经统一
SafeFormatter（含 run_id）脱敏；记录 session start/end 与耗时；异常时保留
traceback 后重新抛出。``debug=False`` 时完全无 IO。
"""

import logging
import time
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

from pdf_reader import logging_config
from pdf_reader.task_logging import STATUS_STARTED, TaskContext, get_current_task, task_log, task_log_context

logger = logging.getLogger("pdf_reader.debug_trace")
trace_logger = logger

TRACE_LOG_MAX_BYTES = 2_000_000
TRACE_LOG_BACKUP_COUNT = 3


class _JobFilter(logging.Filter):
    """生产传入 job_id 时，仅放行当前 TaskContext.job_id 匹配的记录。"""

    def __init__(self, job_id: str | None) -> None:
        super().__init__()
        self.job_id = job_id

    def filter(self, record: logging.LogRecord) -> bool:
        if self.job_id is None:
            return True
        ctx = get_current_task()
        return ctx is not None and ctx.job_id == self.job_id


def _make_trace_handler(log_path: Path) -> RotatingFileHandler:
    handler = RotatingFileHandler(
        str(log_path),
        maxBytes=TRACE_LOG_MAX_BYTES,
        backupCount=TRACE_LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging_config.make_safe_formatter())
    return handler


def _log_session_marker(
    job_id: str,
    message: str,
    *args: object,
    level: int = logging.INFO,
    exc_info: bool = False,
) -> None:
    """在匹配的 job 上下文内记录 session 标记，使 job filter 接受 start/end/failed。"""
    marker_ctx = TaskContext(job_id=job_id or "-", document_id="-", pdf_hash="-", status=STATUS_STARTED)
    try:
        with task_log_context(marker_ctx):
            logger.log(level, message, *args, exc_info=exc_info)
    except Exception:
        pass


@contextmanager
def debug_session(
    glossary_path: Path | None,
    page: int,
    job_id: str | None = None,
    *,
    debug: bool = False,
):
    if not debug or glossary_path is None:
        yield
        return

    log_path = Path(glossary_path) / "debug_trace.log"
    handler: RotatingFileHandler | None = None
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handler = _make_trace_handler(log_path)
        handler.addFilter(_JobFilter(job_id))
        logging_config.attach_handler(handler)
    except Exception:
        logging.getLogger("pdf_reader").warning(
            "Failed to create debug_trace.log handler: %s",
            log_path,
            exc_info=True,
        )

    started = time.monotonic()
    page_label = page + 1
    job_label = job_id or "-"
    try:
        _log_session_marker(job_label, "=== Debug session start: page=%d job=%s ===", page_label, job_label)
        yield
    except BaseException:
        try:
            _log_session_marker(
                job_label,
                "=== Debug session failed: page=%d job=%s ===",
                page_label,
                job_label,
                level=logging.ERROR,
                exc_info=True,
            )
        except Exception:
            pass
        raise
    finally:
        elapsed = time.monotonic() - started
        try:
            _log_session_marker(
                job_label,
                "=== Debug session end: page=%d job=%s elapsed=%.3fs ===",
                page_label,
                job_label,
                elapsed,
            )
        except Exception:
            pass
        if handler is not None:
            logging_config.detach_handler(handler)
            try:
                handler.close()
            except Exception:
                try:
                    logging.getLogger("pdf_reader").warning(
                        "Failed to close debug_trace handler: %s",
                        log_path,
                        exc_info=True,
                    )
                except Exception:
                    pass


def log_step(step: str, *args: object) -> None:
    task_log(logger, logging.INFO, "[step] " + step, *args)


def log_token_usage(token_usage: dict, job_id: str | None = None) -> None:
    if not token_usage:
        return
    total = token_usage.get("main", {}).get("total", 0)
    term_total = token_usage.get("term", {}).get("total", 0)
    if total or term_total:
        task_log(logger, logging.DEBUG, "Token usage: main=%d, term=%d", total, term_total)


def log_glossary_merge(action: str, **fields) -> None:
    parts = [f"{k}={v}" for k, v in fields.items()]
    task_log(logger, logging.INFO, "[glossary %s] %s", action, " ".join(parts))
