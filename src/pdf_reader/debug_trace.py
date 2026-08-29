import logging
import shutil
import time
from contextlib import contextmanager
from pathlib import Path

from pdf_reader.task_logging import SafeFormatter, task_log

logger = logging.getLogger("pdf_reader.debug_trace")


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

    handler = None
    log_path = glossary_path / "debug_trace.log"
    if log_path.exists():
        try:
            rotated = glossary_path / ("debug_trace." + time.strftime("%Y%m%d_%H%M%S") + ".log")
            shutil.move(str(log_path), str(rotated))
        except Exception:
            logging.getLogger("pdf_reader").warning("Failed to rotate debug_trace.log, continuing", exc_info=True)
    try:
        file_handler = logging.FileHandler(str(log_path), encoding="utf-8")
        file_handler.setFormatter(SafeFormatter("%(asctime)s %(levelname)s:%(name)s:%(message)s"))
        trace_logger.addHandler(file_handler)
        task_log(trace_logger, logging.INFO, "=== Debug session start: page %d ===", page + 1)
        handler = file_handler
    except Exception:
        logging.getLogger("pdf_reader").warning("Failed to create debug_trace.log file handler", exc_info=True)
    try:
        yield
    finally:
        if handler is not None:
            try:
                trace_logger.removeHandler(handler)
                handler.close()
            except Exception:
                pass


trace_logger = logging.getLogger("pdf_reader.debug_trace")


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
