import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from pdf_reader import debug_trace
from pdf_reader.task_logging import task_log

logger = logging.getLogger("pdf_reader.lifecycle")


class TranslateResult(Protocol):
    mono_pdf_path: str | Path | None
    dual_pdf_path: str | Path | None
    auto_extracted_glossary_path: str | Path | None


def finish_translation(
    translate_result: TranslateResult,
    replace_page: Callable[[str], None],
    merge_glossary: Callable[[str | Path | None], None],
    page: int = -1,
    job_id: str = "unknown",
) -> None:
    """完成单页翻译：替换页面并合并词表。

    ``page`` 是 1-based 显示页码，仅用于 glossary 等诊断日志字段。
    """
    translated_pdf = translate_result.mono_pdf_path
    if translated_pdf is None and translate_result.dual_pdf_path is not None:
        translated_pdf = translate_result.dual_pdf_path

    if translated_pdf is not None:
        replace_page(str(translated_pdf))

    merge_start = time.time()
    merge_glossary(translate_result.auto_extracted_glossary_path)
    elapsed = time.time() - merge_start
    task_log(logger, logging.INFO, "translation finished: page processed")
    debug_trace.log_glossary_merge("merge_done", job_id=job_id, page=page, elapsed=f"{elapsed:.2f}")


def merge_glossary_only(
    translate_result: TranslateResult,
    merge_glossary: Callable[[str | Path | None], None],
    page: int = -1,
    job_id: str = "unknown",
) -> None:
    """批量模式只合并词表，不替换页面。

    ``page`` 是 1-based 显示页码，仅用于 glossary 等诊断日志字段。
    """
    merge_start = time.time()
    merge_glossary(translate_result.auto_extracted_glossary_path)
    elapsed = time.time() - merge_start
    task_log(logger, logging.INFO, "glossary merge completed in %.2fs", elapsed)
    debug_trace.log_glossary_merge("merge_done", job_id=job_id, page=page, elapsed=f"{elapsed:.2f}")
