import logging
import shutil
import time
from pathlib import Path

import config

trace_logger = logging.getLogger("pdf_reader.debug_trace")
trace_logger.setLevel(logging.INFO)
if not trace_logger.handlers:
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s:%(name)s:%(message)s"
    ))
    trace_logger.addHandler(console_handler)


def log_step(step: str, *args: object) -> None:
    if config.DEBUG:
        trace_logger.info(f"[step] {step}", *args)


def setup_file_handler(glossary_path: Path | None, page: int) -> logging.FileHandler | None:
    if not config.DEBUG or glossary_path is None:
        return None
    try:
        log_path = glossary_path / "debug_trace.log"
        if log_path.exists():
            rotated = glossary_path / (
                "debug_trace." + time.strftime("%Y%m%d_%H%M%S") + ".log"
            )
            shutil.move(str(log_path), str(rotated))
        file_handler = logging.FileHandler(str(log_path), encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s:%(name)s:%(message)s"
        ))
        trace_logger.addHandler(file_handler)
        trace_logger.info("=== Debug session start: page %d ===", page)
        return file_handler
    except Exception:
        logging.getLogger("pdf_reader").warning(
            "Failed to create debug_trace.log file handler", exc_info=True
        )
        return None


def cleanup_file_handler(handler: logging.FileHandler | None) -> None:
    if handler is None:
        return
    try:
        trace_logger.removeHandler(handler)
        handler.close()
    except Exception:
        pass


def log_token_usage(token_usage: dict) -> None:
    if not config.DEBUG:
        return
    if not token_usage:
        return
    total = token_usage.get("main", {}).get("total", 0)
    term_total = token_usage.get("term", {}).get("total", 0)
    if total or term_total:
        trace_logger.info("Token usage: main=%d, term=%d", total, term_total)
