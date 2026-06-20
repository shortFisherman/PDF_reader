import csv
import tempfile
from pathlib import Path

import pytest

from glossary_merger import merge_glossary_csvs


def write_csv(path: Path, rows: list[tuple[str, str]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["source", "target"])
        for source, target in rows:
            w.writerow([source, target])


def read_csv(path: Path) -> list[tuple[str, str]]:
    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [(row["source"], row["target"]) for row in reader]


def test_first_merge_creates_cumulative():
    tmpdir = Path(tempfile.mkdtemp())
    try:
        cumulative_path = tmpdir / "cumulative.csv"
        auto_path = tmpdir / "auto.csv"
        write_csv(auto_path, [("waveguide", "波导"), ("laser", "激光")])

        merge_glossary_csvs(cumulative_path, auto_path)

        rows = read_csv(cumulative_path)
        assert len(rows) == 2
        assert ("waveguide", "波导") in rows
        assert ("laser", "激光") in rows
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_append_merge_with_voting():
    tmpdir = Path(tempfile.mkdtemp())
    try:
        cumulative_path = tmpdir / "cumulative.csv"
        auto_path = tmpdir / "auto.csv"

        write_csv(cumulative_path, [("waveguide", "波导"), ("laser", "激光")])
        write_csv(auto_path, [("waveguide", "波导"), ("laser", "雷射"), ("grating", "光栅")])

        merge_glossary_csvs(cumulative_path, auto_path)

        rows = read_csv(cumulative_path)
        assert len(rows) == 3
        source_to_target = dict(rows)
        assert source_to_target["waveguide"] == "波导"
        # Incumbent "激光" wins by majority vote: 1 existing + 1 incoming same = 2 votes,
        # vs 1 for "雷射"
        assert source_to_target["laser"] == "激光"
        assert source_to_target["grating"] == "光栅"
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_auto_empty_does_not_change_cumulative():
    tmpdir = Path(tempfile.mkdtemp())
    try:
        cumulative_path = tmpdir / "cumulative.csv"
        auto_path = tmpdir / "auto.csv"

        write_csv(cumulative_path, [("waveguide", "波导")])
        # Write header only, no data rows
        with open(auto_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["source", "target"])

        merge_glossary_csvs(cumulative_path, auto_path)

        rows = read_csv(cumulative_path)
        assert rows == [("waveguide", "波导")]
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_auto_file_missing_does_not_create_cumulative():
    tmpdir = Path(tempfile.mkdtemp())
    try:
        cumulative_path = tmpdir / "cumulative.csv"
        auto_path = tmpdir / "nonexistent.csv"

        assert not cumulative_path.exists()
        merge_glossary_csvs(cumulative_path, auto_path)
        assert not cumulative_path.exists()
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)
