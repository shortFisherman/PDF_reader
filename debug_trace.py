import logging
import shutil
import time
from contextlib import contextmanager
from pathlib import Path

import config

logger = logging.getLogger("pdf_reader.debug_trace")


@contextmanager
def debug_session(glossary_path: Path | None, page: int):
    if not config.DEBUG or glossary_path is None:
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
        file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s:%(name)s:%(message)s"))
        trace_logger.addHandler(file_handler)
        trace_logger.info("=== Debug session start: page %d ===", page)
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
    logger.info(f"[step] {step}", *args)


def log_token_usage(token_usage: dict) -> None:
    if not token_usage:
        return
    total = token_usage.get("main", {}).get("total", 0)
    term_total = token_usage.get("term", {}).get("total", 0)
    if total or term_total:
        logger.debug("Token usage: main=%d, term=%d", total, term_total)


def log_glossary_merge(action: str, **fields) -> None:
    parts = [f"{k}={v}" for k, v in fields.items()]
    logger.info("[glossary %s] %s", action, " ".join(parts))
