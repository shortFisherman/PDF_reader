import logging
from pathlib import Path

from pdf_reader.glossary_merger import merge_glossary_csvs
from pdf_reader.task_logging import task_log

logger = logging.getLogger("pdf_reader.glossary")


def resolve_glossary_paths(cache_path: Path | None) -> list[str] | None:
    if cache_path is None:
        result = None
    else:
        cumulative_file = cache_path / "cumulative_glossary.csv"
        if cumulative_file.exists() and cumulative_file.stat().st_size > 0:
            result = [str(cumulative_file)]
        else:
            result = None
    logger.debug("resolved glossary paths: %s", result)
    return result


def merge_after_translate(cumulative_path: Path | None, auto_extracted_path: Path | None) -> None:
    if not cumulative_path or not auto_extracted_path:
        task_log(
            logger,
            logging.WARNING,
            "glossary merge skipped: cumulative_path=%r auto_extracted_path=%r",
            cumulative_path,
            auto_extracted_path,
        )
        return
    try:
        merge_glossary_csvs(Path(cumulative_path), Path(auto_extracted_path))
    except Exception:
        task_log(
            logger,
            logging.WARNING,
            "[glossary] merge failed: cumulative=%s auto=%s",
            cumulative_path,
            auto_extracted_path,
            exc_info=True,
        )
