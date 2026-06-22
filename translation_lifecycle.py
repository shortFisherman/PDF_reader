import logging
import shutil
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import debug_trace
from glossary_service import merge_after_translate

logger = logging.getLogger("pdf_reader")


def finish_translation(
    translate_result: Any,
    replace_page: Callable[[str], None],
    glossary_cache_path: Path | None,
    tmpdir: Path,
    output_dir: str,
) -> None:
    translated_pdf = translate_result.mono_pdf_path
    if translated_pdf is None and translate_result.dual_pdf_path is not None:
        translated_pdf = translate_result.dual_pdf_path

    if translated_pdf is not None:
        replace_page(str(translated_pdf))

    cumulative_glossary_file: Path | None = None
    if glossary_cache_path is not None:
        cumulative_glossary_file = glossary_cache_path / "cumulative_glossary.csv"
    merge_start = time.time()
    merge_after_translate(
        cumulative_glossary_file,
        translate_result.auto_extracted_glossary_path,
    )
    elapsed = time.time() - merge_start
    debug_trace.log_glossary_merge(
        "merge_done", page=-1, elapsed=f"{elapsed:.2f}"
    )

    shutil.rmtree(tmpdir, ignore_errors=True)
    shutil.rmtree(output_dir, ignore_errors=True)
