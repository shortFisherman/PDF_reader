import csv
import logging
from collections import defaultdict
from pathlib import Path

logger = logging.getLogger("pdf_reader")
trace_logger = logging.getLogger("pdf_reader.debug_trace")


def merge_glossary_csvs(cumulative_path: Path, auto_extracted_path: Path) -> None:
    trace_logger.info("merge_glossary: auto=%s exists=%s size=%s",
                       auto_extracted_path, auto_extracted_path.exists(),
                       auto_extracted_path.stat().st_size if auto_extracted_path.exists() else "N/A")

    if not auto_extracted_path.exists():
        trace_logger.info("merge_glossary: auto file missing, skip")
        return

    source_targets: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    auto_rows = 0

    if cumulative_path.exists():
        try:
            with open(cumulative_path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    source = row.get("source", "").strip()
                    target = row.get("target", "").strip()
                    if source and target:
                        source_targets[source][target] += 1
        except Exception:
            logger.warning("Failed to read cumulative glossary, starting fresh", exc_info=True)

    try:
        with open(auto_extracted_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            trace_logger.info("merge_glossary: auto CSV fields=%s", reader.fieldnames)
            for row in reader:
                source = row.get("source", "").strip()
                target = row.get("target", "").strip()
                if source and target:
                    source_targets[source][target] += 1
                    auto_rows += 1
            trace_logger.info("merge_glossary: read %d rows from auto, total unique sources=%d",
                              auto_rows, len(source_targets))
    except Exception:
        logger.warning("Failed to read auto-extracted glossary, skipping merge", exc_info=True)
        return

    if not source_targets:
        trace_logger.info("merge_glossary: no source terms, skip write")
        return

    try:
        with open(cumulative_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["source", "target"])
            for source, targets in sorted(source_targets.items()):
                best_target = max(targets, key=lambda t: targets[t])
                writer.writerow([source, best_target])
        trace_logger.info("merge_glossary: wrote %d terms to %s", len(source_targets), cumulative_path)
    except Exception:
        logger.warning("Failed to write cumulative glossary", exc_info=True)
