import logging
from pathlib import Path

from glossary_merger import merge_glossary_csvs

logger = logging.getLogger("pdf_reader")


def resolve_glossary_paths(cache_path: Path | None) -> list[str] | None:
    if cache_path is None:
        return None
    cumulative_file = cache_path / "cumulative_glossary.csv"
    if cumulative_file.exists() and cumulative_file.stat().st_size > 0:
        return [str(cumulative_file)]
    return None


def merge_after_translate(cumulative_path: Path | None, auto_extracted_path: Path | None) -> None:
    if not cumulative_path or not auto_extracted_path:
        logger.warning(
            "glossary merge skipped: cumulative_path=%r auto_extracted_path=%r",
            cumulative_path,
            auto_extracted_path,
        )
        return
    try:
        merge_glossary_csvs(Path(cumulative_path), Path(auto_extracted_path))
    except Exception:
        logger.warning("Failed to merge glossary", exc_info=True)
