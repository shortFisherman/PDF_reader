import csv
import logging
from collections import defaultdict
from pathlib import Path

logger = logging.getLogger("pdf_reader")


def merge_glossary_csvs(cumulative_path: Path, auto_extracted_path: Path) -> None:
    if not auto_extracted_path.exists():
        logger.warning("Auto glossary file does not exist: %s", auto_extracted_path)
        return

    source_targets: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

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
            for row in reader:
                source = row.get("source", "").strip()
                target = row.get("target", "").strip()
                if source and target:
                    source_targets[source][target] += 1
    except Exception:
        logger.warning("Failed to read auto-extracted glossary, skipping merge", exc_info=True)
        return

    if not source_targets:
        return

    try:
        with open(cumulative_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["source", "target"])
            for source, targets in sorted(source_targets.items()):
                best_target = max(targets, key=lambda t: targets[t])
                writer.writerow([source, best_target])
    except Exception:
        logger.warning("Failed to write cumulative glossary", exc_info=True)
