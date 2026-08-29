import csv
import logging
import os
import threading
from collections import defaultdict
from pathlib import Path

from task_logging import task_log

logger = logging.getLogger("pdf_reader")

_REQUIRED_COLUMNS = ("source", "target")
_merge_lock = threading.Lock()


def _read_glossary_counts(path: Path, label: str) -> dict[str, dict[str, int]] | None:
    """Read a glossary CSV into majority-vote counts.

    Returns None when the file exists but cannot be parsed safely (read error or
    a header missing the required source/target columns). Callers must then abort
    the merge so an unreadable cumulative file is never overwritten. Empty files
    (including BOM-only content) count as no rows.
    """
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is not None and not all(column in reader.fieldnames for column in _REQUIRED_COLUMNS):
                task_log(
                    logger, logging.WARNING, "Invalid %s glossary header %r, merge aborted", label, reader.fieldnames
                )
                return None
            counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
            for row in reader:
                source = row.get("source", "").strip()
                target = row.get("target", "").strip()
                if source and target:
                    counts[source][target] += 1
            return counts
    except Exception:
        task_log(logger, logging.WARNING, "Failed to read %s glossary %s, merge aborted", label, path, exc_info=True)
        return None


def merge_glossary_csvs(cumulative_path: Path, auto_extracted_path: Path) -> None:
    """Merge the auto-extracted glossary into the cumulative one atomically.

    The whole read-merge-write runs under a process-wide lock so concurrent
    merges cannot truncate the cumulative file or lose updates. New content is
    written to a same-directory temp file, flushed/fsynced and closed before
    os.replace commits it. On any read/write/replace failure the previous
    cumulative file stays in place and the temp file is removed.
    """
    with _merge_lock:
        if not auto_extracted_path.exists():
            task_log(logger, logging.WARNING, "auto-extracted glossary file not found: %s", auto_extracted_path)
            return

        counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        if cumulative_path.exists():
            cumulative_counts = _read_glossary_counts(cumulative_path, "cumulative")
            if cumulative_counts is None:
                return
            counts = cumulative_counts

        auto_counts = _read_glossary_counts(auto_extracted_path, "auto-extracted")
        if auto_counts is None:
            return
        for source, targets in auto_counts.items():
            for target, vote in targets.items():
                counts[source][target] += vote

        if not counts:
            return

        tmp_path = cumulative_path.with_name(cumulative_path.name + ".tmp")
        try:
            with open(tmp_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["source", "target"])
                for source, targets in sorted(counts.items()):
                    best_target = max(targets, key=lambda target: targets[target])
                    writer.writerow([source, best_target])
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, cumulative_path)
        except Exception:
            logger.error("Failed to write cumulative glossary %s", cumulative_path, exc_info=True)
            try:
                tmp_path.unlink()
            except OSError:
                pass
            raise
