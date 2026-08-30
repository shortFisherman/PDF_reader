"""P0-02 文档级权威术语存储与全局词表只读加载。"""

import csv
import os
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pdf_reader import user_glossary
from pdf_reader.term_model import (
    GlossaryConflictError,
    GlossaryLockedError,
    GlossaryRevisionConflictError,
    TermStoreError,
)
from pdf_reader.user_glossary import USER_GLOSSARY_FILENAME, UserGlossaryStore, load_global_glossary


def doc_dir(tmp_path: Path) -> Path:
    directory = tmp_path / ("a" * 64)
    directory.mkdir()
    return directory


def test_document_dir_must_be_64_hex_hash(tmp_path):
    for bad in (tmp_path, tmp_path / "cache", tmp_path / ("A" * 64), tmp_path / ("g" * 64)):
        with pytest.raises(TermStoreError, match="64-char hex hash"):
            UserGlossaryStore(bad)


def test_load_missing_file_returns_empty_and_zero_revision(tmp_path):
    store = UserGlossaryStore(doc_dir(tmp_path))
    assert store.load() == ([], 0)


def test_add_creates_versioned_csv_and_increments_revision(tmp_path):
    store = UserGlossaryStore(doc_dir(tmp_path))
    term, revision = store.add("AD", "特应性皮炎", note="main abbreviation")
    assert revision == 1
    assert term.scope == "document"
    assert term.locked is False
    assert term.note == "main abbreviation"

    terms, loaded_revision = store.load()
    assert loaded_revision == 1
    assert len(terms) == 1
    assert terms[0].source == "AD"
    assert terms[0].target == "特应性皮炎"
    assert terms[0].scope == "document"
    assert terms[0].note == "main abbreviation"

    header_lines = store.path.read_text(encoding="utf-8-sig").splitlines()
    assert header_lines[0] == "# schema_version=1; revision=1"
    assert header_lines[1] == "source,target,locked,created_at,updated_at,note"


def test_add_rejects_duplicate_normalized_source(tmp_path):
    store = UserGlossaryStore(doc_dir(tmp_path))
    store.add("AD", "特应性皮炎")
    with pytest.raises(GlossaryConflictError):
        store.add(" ad ", "特应性皮炎")


def test_add_requires_nonempty_clean_text(tmp_path):
    store = UserGlossaryStore(doc_dir(tmp_path))
    with pytest.raises(TermStoreError):
        store.add("", "译")
    with pytest.raises(TermStoreError):
        store.add("AD", "  ")
    with pytest.raises(TermStoreError):
        store.add("AD\nBAD", "译")


def test_edit_updates_target_note_and_revision(tmp_path):
    store = UserGlossaryStore(doc_dir(tmp_path))
    _, revision_after_add = store.add("TCS", "外用糖皮质激素", note="old")
    term, revision = store.edit("tcs", "外用皮质类固醇", note="updated", expected_revision=revision_after_add)
    assert revision == revision_after_add + 1
    assert term.target == "外用皮质类固醇"
    assert term.note == "updated"
    assert term.source == "TCS"
    assert store.load()[0][0].updated_at >= term.created_at


def test_edit_rejects_stale_revision(tmp_path):
    store = UserGlossaryStore(doc_dir(tmp_path))
    store.add("TCS", "外用糖皮质激素")
    with pytest.raises(GlossaryRevisionConflictError) as excinfo:
        store.edit("TCS", "外用皮质类固醇", expected_revision=99)
    assert excinfo.value.expected == 99
    assert excinfo.value.actual == 1


def test_delete_removes_term(tmp_path):
    store = UserGlossaryStore(doc_dir(tmp_path))
    store.add("AD", "特应性皮炎")
    store.add("TCS", "外用糖皮质激素")
    removed, revision = store.delete("ad")
    assert removed.source == "AD"
    assert revision == 3
    assert [t.source for t in store.load()[0]] == ["TCS"]


def test_delete_missing_term_raises(tmp_path):
    store = UserGlossaryStore(doc_dir(tmp_path))
    with pytest.raises(TermStoreError, match="not found"):
        store.delete("missing")


def test_locked_term_cannot_be_edited_or_deleted(tmp_path):
    store = UserGlossaryStore(doc_dir(tmp_path))
    store.add("AD", "特应性皮炎", locked=True)
    with pytest.raises(GlossaryLockedError):
        store.edit("AD", "其他译法")
    with pytest.raises(GlossaryLockedError):
        store.delete("AD")
    term, revision = store.unlock("AD")
    assert term.locked is False
    assert revision == 2
    term, _ = store.edit("AD", "其他译法")
    assert term.target == "其他译法"


def test_lock_and_unlock_are_idempotent_and_visible(tmp_path):
    store = UserGlossaryStore(doc_dir(tmp_path))
    store.add("AD", "特应性皮炎")
    term, _ = store.lock("AD")
    assert term.locked is True
    term, _ = store.lock("AD")
    assert term.locked is True
    term, _ = store.unlock("AD")
    assert term.locked is False
    with pytest.raises(TermStoreError, match="not found"):
        store.lock("missing")


def test_write_failure_keeps_last_valid_version(tmp_path, monkeypatch):
    store = UserGlossaryStore(doc_dir(tmp_path))
    store.add("AD", "特应性皮炎")
    old_bytes = store.path.read_bytes()
    monkeypatch.setattr(user_glossary.os, "replace", lambda src, dst: (_ for _ in ()).throw(OSError("replace failed")))
    with pytest.raises(OSError, match="replace failed"):
        store.add("TCS", "外用糖皮质激素")
    assert store.path.read_bytes() == old_bytes
    assert not list(store.document_dir.glob("*.tmp"))


def test_fsync_failure_mid_write_keeps_last_valid_version(tmp_path, monkeypatch):
    store = UserGlossaryStore(doc_dir(tmp_path))
    store.add("AD", "特应性皮炎")
    old_bytes = store.path.read_bytes()
    replace_calls = []
    real_replace = os.replace
    monkeypatch.setattr(
        user_glossary.os,
        "replace",
        lambda src, dst: replace_calls.append((Path(src).name, Path(dst))) or real_replace(src, dst),
    )
    monkeypatch.setattr(user_glossary.os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("fsync failed")))
    with pytest.raises(OSError, match="fsync failed"):
        store.add("TCS", "外用糖皮质激素")
    assert replace_calls == []
    assert store.path.read_bytes() == old_bytes
    assert not list(store.document_dir.glob("*.tmp"))


def test_corrupt_file_is_refused_not_overwritten(tmp_path):
    store = UserGlossaryStore(doc_dir(tmp_path))
    store.path.write_bytes(b"\xff\xfe broken")
    with pytest.raises(TermStoreError):
        store.add("TCS", "外用糖皮质激素")
    assert store.path.read_bytes() == b"\xff\xfe broken"


def test_unsupported_schema_version_is_refused(tmp_path):
    store = UserGlossaryStore(doc_dir(tmp_path))
    store.path.write_text("# schema_version=99\nsource,target,locked,created_at,updated_at,note\n", encoding="utf-8")
    with pytest.raises(TermStoreError, match="schema version"):
        store.load()


def test_missing_schema_header_is_refused(tmp_path):
    store = UserGlossaryStore(doc_dir(tmp_path))
    store.path.write_text("source,target\nAD,特应性皮炎\n", encoding="utf-8")
    with pytest.raises(TermStoreError, match="schema header"):
        store.load()


def test_concurrent_adds_do_not_lose_terms(tmp_path):
    import threading

    store = UserGlossaryStore(doc_dir(tmp_path))
    thread_count = 8
    barrier = threading.Barrier(thread_count)
    errors = []

    def worker(index: int) -> None:
        try:
            barrier.wait(timeout=5)
            store.add(f"term {index}", f"译{index}")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(thread_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert errors == []
    terms, _ = store.load()
    assert len(terms) == thread_count
    assert not list(store.document_dir.glob("*.tmp"))


def test_global_loader_reads_source_target_csv(tmp_path):
    path = tmp_path / "docs_glossary.csv"
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["source", "target"])
        writer.writerow(["AD", "特应性皮炎"])
        writer.writerow(["", ""])
    terms = load_global_glossary(path)
    assert len(terms) == 1
    assert terms[0].scope == "global"
    assert terms[0].locked is False
    assert terms[0].created_at.tzinfo is not None
    assert terms[0].created_at == datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)


def test_global_loader_missing_or_empty_returns_empty(tmp_path):
    assert load_global_glossary(tmp_path / "missing.csv") == []
    empty = tmp_path / "empty.csv"
    empty.write_bytes(b"")
    assert load_global_glossary(empty) == []


def test_global_loader_rejects_bad_header_and_partial_rows(tmp_path):
    bad_header = tmp_path / "bad_header.csv"
    bad_header.write_text("foo,bar\nAD,特应性皮炎\n", encoding="utf-8")
    with pytest.raises(TermStoreError, match="header"):
        load_global_glossary(bad_header)
    partial = tmp_path / "partial.csv"
    partial.write_text("source,target\nAD,\n", encoding="utf-8")
    with pytest.raises(TermStoreError, match="row"):
        load_global_glossary(partial)


def test_store_never_writes_global_or_other_files(tmp_path):
    store = UserGlossaryStore(doc_dir(tmp_path))
    store.add("AD", "特应性皮炎")
    files = [p.name for p in store.document_dir.iterdir()]
    assert files == [USER_GLOSSARY_FILENAME]


def test_two_store_instances_concurrent_writes_do_not_lose_terms(tmp_path):
    document_dir = doc_dir(tmp_path)
    store_a = UserGlossaryStore(document_dir)
    store_b = UserGlossaryStore(document_dir)
    thread_count = 8
    barrier = threading.Barrier(thread_count)
    errors = []

    def worker(index: int) -> None:
        store = store_a if index % 2 == 0 else store_b
        try:
            barrier.wait(timeout=5)
            store.add(f"term {index}", f"译{index}")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(thread_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert errors == []
    terms, revision = store_a.load()
    assert len(terms) == thread_count
    assert revision == thread_count
    assert not list(document_dir.glob("*.tmp"))


def _write_raw_user_glossary(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        f.write("# schema_version=1; revision=1\n")
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def test_invalid_locked_value_is_refused_and_bytes_unchanged(tmp_path):
    store = UserGlossaryStore(doc_dir(tmp_path))
    _write_raw_user_glossary(
        store.path,
        ["source", "target", "locked", "created_at", "updated_at", "note"],
        [["AD", "特应性皮炎", "maybe", "2026-08-31T10:00:00+00:00", "2026-08-31T10:00:00+00:00", ""]],
    )
    original = store.path.read_bytes()
    with pytest.raises(TermStoreError, match="locked"):
        store.load()
    with pytest.raises(TermStoreError, match="locked"):
        store.add("TCS", "外用糖皮质激素")
    assert store.path.read_bytes() == original


def test_missing_locked_field_is_refused(tmp_path):
    store = UserGlossaryStore(doc_dir(tmp_path))
    _write_raw_user_glossary(
        store.path,
        ["source", "target", "locked", "created_at", "updated_at", "note"],
        [["AD", "特应性皮炎", "", "2026-08-31T10:00:00+00:00", "2026-08-31T10:00:00+00:00", ""]],
    )
    original = store.path.read_bytes()
    with pytest.raises(TermStoreError, match="locked"):
        store.load()
    assert store.path.read_bytes() == original


def test_wrong_header_is_refused(tmp_path):
    store = UserGlossaryStore(doc_dir(tmp_path))
    _write_raw_user_glossary(
        store.path,
        ["source", "target", "locked", "created_at", "updated_at"],
        [["AD", "特应性皮炎", "false", "2026-08-31T10:00:00+00:00", "2026-08-31T10:00:00+00:00"]],
    )
    original = store.path.read_bytes()
    with pytest.raises(TermStoreError, match="header"):
        store.load()
    assert store.path.read_bytes() == original


def test_duplicate_normalized_source_is_refused(tmp_path):
    store = UserGlossaryStore(doc_dir(tmp_path))
    _write_raw_user_glossary(
        store.path,
        ["source", "target", "locked", "created_at", "updated_at", "note"],
        [
            ["AD", "特应性皮炎", "false", "2026-08-31T10:00:00+00:00", "2026-08-31T10:00:00+00:00", ""],
            ["ad", "特应性皮炎", "false", "2026-08-31T10:00:00+00:00", "2026-08-31T10:00:00+00:00", ""],
        ],
    )
    original = store.path.read_bytes()
    with pytest.raises(TermStoreError, match="duplicate"):
        store.load()
    assert store.path.read_bytes() == original


@pytest.mark.parametrize(
    ("row", "match"),
    [
        ([" AD ", "特应性皮炎", "false", "2026-08-31T10:00:00+00:00", "2026-08-31T10:00:00+00:00", ""], "source"),
        (["AD", " 特应性皮炎", "false", "2026-08-31T10:00:00+00:00", "2026-08-31T10:00:00+00:00", ""], "target"),
        (["AD", "特应性皮炎", "false", "2026-08-31T10:00:00+00:00", "2026-08-31T10:00:00+00:00", " note "], "note"),
    ],
)
def test_non_canonical_user_glossary_row_is_refused(tmp_path, row: list[str], match: str):
    store = UserGlossaryStore(doc_dir(tmp_path))
    _write_raw_user_glossary(
        store.path,
        ["source", "target", "locked", "created_at", "updated_at", "note"],
        [row],
    )
    original = store.path.read_bytes()
    with pytest.raises(TermStoreError, match=match):
        store.load()
    with pytest.raises(TermStoreError, match=match):
        store.add("TCS", "外用糖皮质激素")
    assert store.path.read_bytes() == original
