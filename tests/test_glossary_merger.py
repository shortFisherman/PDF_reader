import csv
import os
import tempfile
import threading
from pathlib import Path

import pytest

import glossary_merger
from glossary_merger import merge_glossary_csvs


def write_csv(path: Path, rows: list[tuple[str, str]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["source", "target"])
        for source, target in rows:
            w.writerow([source, target])


def read_csv(path: Path) -> list[tuple[str, str]]:
    with open(path, newline="", encoding="utf-8-sig") as f:
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


def test_bom_encoded_auto_glossary_is_merged():
    """babeldoc writes auto-extracted glossary with utf-8-sig (BOM) and 3 columns.
    The merger must handle the BOM so 'source' lookups don't silently fail."""
    tmpdir = Path(tempfile.mkdtemp())
    try:
        cumulative_path = tmpdir / "cumulative.csv"
        auto_path = tmpdir / "auto.csv"

        with open(auto_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=["source", "target", "tgt_lng"], doublequote=True)
            w.writeheader()
            w.writerow({"source": "AD", "target": "特应性皮炎", "tgt_lng": "zh"})
            w.writerow({"source": "panel", "target": "专家组", "tgt_lng": "zh"})

        merge_glossary_csvs(cumulative_path, auto_path)

        rows = read_csv(cumulative_path)
        assert len(rows) == 2
        source_to_target = dict(rows)
        assert source_to_target["AD"] == "特应性皮炎"
        assert source_to_target["panel"] == "专家组"
    finally:
        import shutil

        shutil.rmtree(tmpdir, ignore_errors=True)


def test_successful_merge_commits_via_same_dir_tmp_and_os_replace(tmp_path, monkeypatch):
    cumulative_path = tmp_path / "cumulative.csv"
    auto_path = tmp_path / "auto.csv"
    write_csv(cumulative_path, [("alpha", "阿尔法")])
    write_csv(auto_path, [("beta", "贝塔")])

    replace_calls: list[tuple[str, Path]] = []
    original_replace = os.replace

    def tracking_replace(src, dst):  # noqa: ANN001, ANN202
        replace_calls.append((Path(src).name, Path(dst)))
        return original_replace(src, dst)

    monkeypatch.setattr(glossary_merger.os, "replace", tracking_replace)

    merge_glossary_csvs(cumulative_path, auto_path)

    assert replace_calls == [("cumulative.csv.tmp", cumulative_path)]
    rows = read_csv(cumulative_path)
    assert dict(rows) == {"alpha": "阿尔法", "beta": "贝塔"}
    assert not list(tmp_path.glob("*.tmp"))


def test_os_replace_failure_keeps_old_csv_and_cleans_tmp(tmp_path, monkeypatch):
    cumulative_path = tmp_path / "cumulative.csv"
    auto_path = tmp_path / "auto.csv"
    write_csv(cumulative_path, [("alpha", "阿尔法")])
    write_csv(auto_path, [("beta", "贝塔")])
    old_bytes = cumulative_path.read_bytes()

    def failing_replace(src, dst):  # noqa: ANN001, ANN202
        raise OSError("replace failed")

    monkeypatch.setattr(glossary_merger.os, "replace", failing_replace)

    with pytest.raises(OSError, match="replace failed"):
        merge_glossary_csvs(cumulative_path, auto_path)

    assert cumulative_path.read_bytes() == old_bytes
    assert read_csv(cumulative_path) == [("alpha", "阿尔法")]
    assert not list(tmp_path.glob("*.tmp"))


def test_write_open_failure_keeps_old_csv_and_cleans_tmp(tmp_path, monkeypatch):
    cumulative_path = tmp_path / "cumulative.csv"
    auto_path = tmp_path / "auto.csv"
    write_csv(cumulative_path, [("alpha", "阿尔法")])
    write_csv(auto_path, [("beta", "贝塔")])
    old_bytes = cumulative_path.read_bytes()
    tmp_path_file = cumulative_path.with_name(cumulative_path.name + ".tmp")

    real_open = open

    def failing_open(path, *args, **kwargs) -> object:  # noqa: ANN001, ANN002, ANN003
        if Path(path) == tmp_path_file:
            raise OSError("write failed")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", failing_open)

    with pytest.raises(OSError, match="write failed"):
        merge_glossary_csvs(cumulative_path, auto_path)

    assert cumulative_path.read_bytes() == old_bytes
    assert read_csv(cumulative_path) == [("alpha", "阿尔法")]
    assert not list(tmp_path.glob("*.tmp"))


def test_fsync_failure_mid_write_keeps_old_csv_and_cleans_tmp(tmp_path, monkeypatch):
    """Inject failure after header/rows are flushed to the temp file but before os.replace."""

    cumulative_path = tmp_path / "cumulative.csv"
    auto_path = tmp_path / "auto.csv"
    write_csv(cumulative_path, [("alpha", "阿尔法")])
    write_csv(auto_path, [("beta", "贝塔")])
    old_bytes = cumulative_path.read_bytes()
    tmp_path_file = cumulative_path.with_name(cumulative_path.name + ".tmp")

    replace_calls: list[tuple[Path, Path]] = []
    original_replace = os.replace

    def tracking_replace(src: str, dst: str) -> None:
        replace_calls.append((Path(src), Path(dst)))
        original_replace(src, dst)

    fsync_seen = {}

    def failing_fsync(fd: int) -> None:
        fsync_seen["temp_exists"] = tmp_path_file.exists()
        fsync_seen["temp_size"] = tmp_path_file.stat().st_size if tmp_path_file.exists() else -1
        raise OSError("fsync failed")

    monkeypatch.setattr(glossary_merger.os, "replace", tracking_replace)
    monkeypatch.setattr(glossary_merger.os, "fsync", failing_fsync)

    with pytest.raises(OSError, match="fsync failed"):
        merge_glossary_csvs(cumulative_path, auto_path)

    assert fsync_seen["temp_exists"] is True
    assert fsync_seen["temp_size"] > 0
    assert replace_calls == [], "os.replace must not be reached after a mid-write failure"
    assert cumulative_path.read_bytes() == old_bytes
    assert read_csv(cumulative_path) == [("alpha", "阿尔法")]
    assert not list(tmp_path.glob("*.tmp"))


def test_merge_holds_process_lock_until_commit(tmp_path):
    cumulative_path = tmp_path / "cumulative.csv"
    auto_path = tmp_path / "auto.csv"
    write_csv(auto_path, [("beta", "贝塔")])

    started = threading.Event()
    finished = threading.Event()
    errors: list[BaseException] = []

    def worker() -> None:
        started.set()
        try:
            merge_glossary_csvs(cumulative_path, auto_path)
        except Exception as exc:
            errors.append(exc)
        finally:
            finished.set()

    glossary_merger._merge_lock.acquire()
    try:
        thread = threading.Thread(target=worker)
        thread.start()
        assert started.wait(timeout=5)
        thread.join(timeout=0.2)
        assert thread.is_alive(), "merge must hold the lock through the whole read-merge-write"
        assert not finished.is_set()
        assert not cumulative_path.exists(), "no commit may happen while the lock is held"
    finally:
        glossary_merger._merge_lock.release()

    assert finished.wait(timeout=5)
    thread.join(timeout=5)
    assert errors == []
    assert read_csv(cumulative_path) == [("beta", "贝塔")]
    assert not list(tmp_path.glob("*.tmp"))


def test_concurrent_merges_do_not_lose_updates(tmp_path):
    cumulative_path = tmp_path / "cumulative.csv"
    write_csv(cumulative_path, [("seed", "种子")])
    thread_count = 8
    terms_per_thread = 4
    barrier = threading.Barrier(thread_count)
    errors: list[BaseException] = []
    auto_paths: list[Path] = []

    for t in range(thread_count):
        auto = tmp_path / f"auto_{t}.csv"
        rows = [(f"term_{t}_{i}", f"译{t}{i}") for i in range(terms_per_thread)]
        write_csv(auto, rows)
        auto_paths.append(auto)

    def worker(auto: Path) -> None:
        try:
            barrier.wait(timeout=5)
            merge_glossary_csvs(cumulative_path, auto)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(path,)) for path in auto_paths]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert errors == []
    source_to_target = dict(read_csv(cumulative_path))
    assert source_to_target["seed"] == "种子"
    for t in range(thread_count):
        for i in range(terms_per_thread):
            assert source_to_target[f"term_{t}_{i}"] == f"译{t}{i}"
    assert not list(tmp_path.glob("*.tmp"))


def test_corrupt_cumulative_is_preserved_and_merge_aborted(tmp_path):
    cumulative_path = tmp_path / "cumulative.csv"
    auto_path = tmp_path / "auto.csv"
    write_csv(auto_path, [("beta", "贝塔")])
    corrupt = b"\xff\xfe\x00 not utf-8 \x80"
    cumulative_path.write_bytes(corrupt)

    merge_glossary_csvs(cumulative_path, auto_path)

    assert cumulative_path.read_bytes() == corrupt
    assert not list(tmp_path.glob("*.tmp"))


def test_bad_header_cumulative_is_preserved_and_merge_aborted(tmp_path):
    cumulative_path = tmp_path / "cumulative.csv"
    auto_path = tmp_path / "auto.csv"
    write_csv(auto_path, [("beta", "贝塔")])
    with open(cumulative_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["foo", "bar"])
        writer.writerow(["x", "y"])

    merge_glossary_csvs(cumulative_path, auto_path)

    content = cumulative_path.read_text(encoding="utf-8")
    assert "foo" in content
    assert "beta" not in content
    assert not list(tmp_path.glob("*.tmp"))


def test_bad_header_auto_is_skipped_and_cumulative_unchanged(tmp_path):
    cumulative_path = tmp_path / "cumulative.csv"
    auto_path = tmp_path / "auto.csv"
    write_csv(cumulative_path, [("alpha", "阿尔法")])
    with open(auto_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["foo", "bar"])
        writer.writerow(["beta", "贝塔"])

    merge_glossary_csvs(cumulative_path, auto_path)

    assert read_csv(cumulative_path) == [("alpha", "阿尔法")]
    assert not list(tmp_path.glob("*.tmp"))


def test_empty_cumulative_file_is_treated_as_empty(tmp_path):
    cumulative_path = tmp_path / "cumulative.csv"
    auto_path = tmp_path / "auto.csv"
    cumulative_path.write_bytes(b"")
    write_csv(auto_path, [("beta", "贝塔")])

    merge_glossary_csvs(cumulative_path, auto_path)

    assert read_csv(cumulative_path) == [("beta", "贝塔")]
    assert not list(tmp_path.glob("*.tmp"))


def test_empty_auto_file_leaves_cumulative_unchanged(tmp_path):
    cumulative_path = tmp_path / "cumulative.csv"
    auto_path = tmp_path / "auto.csv"
    write_csv(cumulative_path, [("alpha", "阿尔法")])
    auto_path.write_bytes(b"")

    merge_glossary_csvs(cumulative_path, auto_path)

    assert read_csv(cumulative_path) == [("alpha", "阿尔法")]
    assert not list(tmp_path.glob("*.tmp"))


def test_bom_cumulative_is_read_and_merged(tmp_path):
    cumulative_path = tmp_path / "cumulative.csv"
    auto_path = tmp_path / "auto.csv"
    with open(cumulative_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["source", "target"])
        writer.writerow(["alpha", "阿尔法"])
    write_csv(auto_path, [("beta", "贝塔")])

    merge_glossary_csvs(cumulative_path, auto_path)

    rows = read_csv(cumulative_path)
    assert ("alpha", "阿尔法") in rows
    assert ("beta", "贝塔") in rows
    assert not list(tmp_path.glob("*.tmp"))
