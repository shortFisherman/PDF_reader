import logging
from pathlib import Path

from glossary_merger import merge_glossary_csvs
from state import AppState

logger = logging.getLogger("pdf_reader")


def resolve_glossary_paths(state: AppState) -> list[str] | None:
    cumulative_glossary_path = state.glossary_cache_path
    if cumulative_glossary_path is None:
        return None
    cumulative_file = cumulative_glossary_path / "cumulative_glossary.csv"
    if cumulative_file.exists() and cumulative_file.stat().st_size > 0:
        return [str(cumulative_file)]
    return None


def merge_after_translate(cumulative_path: Path | None, auto_extracted_path: Path | None) -> None:
    if not cumulative_path or not auto_extracted_path:
        return
    try:
        merge_glossary_csvs(Path(cumulative_path), Path(auto_extracted_path))
    except Exception:
        logger.warning("Failed to merge glossary", exc_info=True)
