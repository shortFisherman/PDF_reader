import logging
import shutil
import time
from contextlib import contextmanager
from pathlib import Path

import config

logger = logging.getLogger("pdf_reader.debug_trace")

_original_extract = None

_original_handler = None


def _apply_monkey_patches() -> None:
    global _original_extract
    try:
        from babeldoc.format.pdf.document_il.midend.automatic_term_extractor import (
            AutomaticTermExtractor,
        )
    except ImportError:
        logger.warning(
            "Cannot import AutomaticTermExtractor -- monkey-patch skipped. "
            "Term batch tracing will not be available."
        )
        return

    _original_extract = AutomaticTermExtractor.extract_terms_from_paragraphs

    def patched_extract(self, paragraphs, pbar=None, paragraph_token_count=0):
        n_paras = len(paragraphs.paragraphs)
        chars = sum(len(p.unicode or "") for p in paragraphs.paragraphs)
        trace_logger.info("Term batch: %d paragraphs, %d chars", n_paras, chars)

        terms_before = len(self.shared_context.raw_extracted_terms)

        result = _original_extract(self, paragraphs, pbar, paragraph_token_count)

        terms_after = len(self.shared_context.raw_extracted_terms)
        trace_logger.info("Term batch done: extracted %d terms", terms_after - terms_before)

        tracker = paragraphs.tracker
        llm_input = getattr(tracker, "input", "")
        llm_output = getattr(tracker, "output", "")
        if llm_output:
            trace_logger.info("Term batch prompt: %d chars", len(llm_input))
            trace_logger.info("Term batch response: %d chars", len(llm_output))
            trace_logger.info("Term batch raw (500 chars): %s", llm_output[:500])
        elif not llm_input and terms_after == terms_before:
            trace_logger.info("Term batch: no LLM call made (empty inputs)")

        return result

    AutomaticTermExtractor.extract_terms_from_paragraphs = patched_extract


def init_debug(debug_enabled: bool) -> None:
    if debug_enabled:
        _apply_monkey_patches()


@contextmanager
def debug_session(glossary_path: Path | None, page: int):
    if not config.DEBUG or glossary_path is None:
        yield
        return

    handler = None
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
        handler = file_handler
    except Exception:
        logging.getLogger("pdf_reader").warning(
            "Failed to create debug_trace.log file handler", exc_info=True
        )
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


def log_glossary_merge(action: str, **fields) -> None:
    if not config.DEBUG:
        return
    parts = [f"{k}={v}" for k, v in fields.items()]
    trace_logger.info("[glossary %s] %s", action, " ".join(parts))
