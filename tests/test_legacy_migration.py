"""P0-02 旧 cumulative_glossary.csv 的一次性幂等安全迁移。"""

import csv
import json
import os
import threading
import time
from pathlib import Path

import pytest

from pdf_reader import candidate_store, legacy_migration
from pdf_reader.candidate_store import CandidateStore
from pdf_reader.glossary_compiler import compile_effective_glossary
from pdf_reader.glossary_merger import merge_glossary_csvs
from pdf_reader.legacy_migration import LEGACY_CUMULATIVE_BACKUP_NAME, migrate_legacy_cumulative
from pdf_reader.term_model import (
    LEGACY_CUMULATIVE_FILENAME,
    LEGACY_CUMULATIVE_STRATEGY,
    MigrationError,
    TermStoreError,
)


def doc_dir(tmp_path: Path) -> Path:
    directory = tmp_path / ("c" * 64)
    directory.mkdir()
    return directory


def write_cumulative(path: Path, rows: list[tuple[str, str]], encoding: str = "utf-8") -> None:
    with open(path, "w", newline="", encoding=encoding) as f:
        writer = csv.writer(f)
        writer.writerow(["source", "target"])
        for source, target in rows:
            writer.writerow([source, target])


def _as_bytes(text: str) -> bytes:
    return text.encode()


def test_migrate_imports_rows_as_unreviewed_candidates_and_backs_up(tmp_path):
    document_dir = doc_dir(tmp_path)
    cumulative = document_dir / LEGACY_CUMULATIVE_FILENAME
    write_cumulative(cumulative, [("AD", "特应性皮炎"), ("TCS", "外用糖皮质激素")])
    original_bytes = cumulative.read_bytes()

    result = migrate_legacy_cumulative(document_dir)

    assert result.status == "migrated"
    assert result.rows == 2
    assert result.backup_path.name == LEGACY_CUMULATIVE_BACKUP_NAME
    assert cumulative.exists(), "旧累计词表在兼容期内不得删除"
    assert cumulative.read_bytes() == original_bytes
    assert result.backup_path.read_bytes() == original_bytes

    entries, revision, metadata = CandidateStore(document_dir).load()
    assert revision == 1
    assert metadata["legacy_migration"]["from"] == LEGACY_CUMULATIVE_FILENAME
    assert metadata["legacy_migration"]["rows"] == 2
    assert {e.source for e in entries} == {"AD", "TCS"}
    for entry in entries:
        assert entry.status == "candidate"
        assert entry.strategy_version == LEGACY_CUMULATIVE_STRATEGY
        assert entry.targets[0].observations == 1
        assert entry.targets[0].pages == ()
        assert entry.targets[0].evidence == ()
        assert entry.accepted_target is None
        assert entry.rejected_targets == []


def test_migrate_merges_duplicate_rows_and_conflicting_targets(tmp_path):
    document_dir = doc_dir(tmp_path)
    cumulative = document_dir / LEGACY_CUMULATIVE_FILENAME
    write_cumulative(
        cumulative,
        [("AD", "特应性皮炎"), ("ad", "特应性皮炎"), ("TCS", "外用糖皮质激素"), ("TCS", "外用皮质类固醇")],
    )
    result = migrate_legacy_cumulative(document_dir)
    assert result.rows == 4
    entries, _, _ = CandidateStore(document_dir).load()
    assert len(entries) == 2
    by_key = {entry.source_key: entry for entry in entries}
    assert by_key["ad"].source == "AD"
    ad_suggestion = by_key["ad"].targets[0]
    assert ad_suggestion.observations == 2
    tcs_targets = [s.target for s in by_key["tcs"].targets]
    assert tcs_targets == ["外用皮质类固醇", "外用糖皮质激素"]


def test_migrate_is_idempotent_and_never_duplicates(tmp_path):
    document_dir = doc_dir(tmp_path)
    cumulative = document_dir / LEGACY_CUMULATIVE_FILENAME
    write_cumulative(cumulative, [("AD", "特应性皮炎")])
    first = migrate_legacy_cumulative(document_dir)
    candidates_path = document_dir / "term_candidates.json"
    candidates_bytes = candidates_path.read_bytes()

    cumulative.write_text("source,target\nAD,特应性皮炎\nTCS,外用糖皮质激素\n", encoding="utf-8")
    second = migrate_legacy_cumulative(document_dir)

    assert first.status == "migrated"
    assert second.status == "noop"
    assert second.rows == 0
    assert candidates_path.read_bytes() == candidates_bytes
    entries, _, _ = CandidateStore(document_dir).load()
    assert len(entries) == 1
    assert entries[0].targets[0].observations == 1


def test_migrate_noop_when_cumulative_missing(tmp_path):
    document_dir = doc_dir(tmp_path)
    result = migrate_legacy_cumulative(document_dir)
    assert result.status == "noop"
    assert result.rows == 0
    assert not (document_dir / "term_candidates.json").exists()


def test_migrate_noop_for_empty_cumulative(tmp_path):
    document_dir = doc_dir(tmp_path)
    cumulative = document_dir / LEGACY_CUMULATIVE_FILENAME
    cumulative.write_text("source,target\n", encoding="utf-8")
    result = migrate_legacy_cumulative(document_dir)
    assert result.status == "noop"
    assert not (document_dir / "term_candidates.json").exists()
    assert not (document_dir / LEGACY_CUMULATIVE_BACKUP_NAME).exists()


def test_migrate_handles_bom_cumulative(tmp_path):
    document_dir = doc_dir(tmp_path)
    cumulative = document_dir / LEGACY_CUMULATIVE_FILENAME
    write_cumulative(cumulative, [("AD", "特应性皮炎")], encoding="utf-8-sig")
    result = migrate_legacy_cumulative(document_dir)
    assert result.status == "migrated"
    entries, _, _ = CandidateStore(document_dir).load()
    assert entries[0].source == "AD"


@pytest.mark.parametrize(
    ("content", "match"),
    [
        (_as_bytes("source,only\nAD,特应性皮炎\n"), "header"),
        (_as_bytes("source,target\nAD,\n"), "row"),
        (b"\xff\xfe not utf-8", "read"),
    ],
)
def test_migrate_failure_keeps_old_file_untouched(tmp_path, content: bytes, match: str):
    document_dir = doc_dir(tmp_path)
    cumulative = document_dir / LEGACY_CUMULATIVE_FILENAME
    cumulative.write_bytes(content)
    with pytest.raises(MigrationError, match=match):
        migrate_legacy_cumulative(document_dir)
    assert cumulative.read_bytes() == content
    assert not (document_dir / "term_candidates.json").exists()
    assert not (document_dir / LEGACY_CUMULATIVE_BACKUP_NAME).exists()
    assert not list(document_dir.glob("*.tmp"))


@pytest.mark.parametrize(
    ("row_line", "match"),
    [
        ("AD ,特应性皮炎\n", "row"),
        ("AD, 特应性皮炎\n", "row"),
    ],
)
def test_migrate_rejects_non_canonical_rows(tmp_path, row_line: str, match: str):
    document_dir = doc_dir(tmp_path)
    cumulative = document_dir / LEGACY_CUMULATIVE_FILENAME
    cumulative.write_text("source,target\n" + row_line, encoding="utf-8")
    original = cumulative.read_bytes()
    with pytest.raises(MigrationError, match=match):
        migrate_legacy_cumulative(document_dir)
    assert cumulative.read_bytes() == original
    assert not (document_dir / "term_candidates.json").exists()
    assert not (document_dir / LEGACY_CUMULATIVE_BACKUP_NAME).exists()


def test_migrate_fails_closed_when_backup_is_directory(tmp_path):
    document_dir = doc_dir(tmp_path)
    cumulative = document_dir / LEGACY_CUMULATIVE_FILENAME
    write_cumulative(cumulative, [("AD", "特应性皮炎")])
    backup = document_dir / LEGACY_CUMULATIVE_BACKUP_NAME
    backup.mkdir()
    original = cumulative.read_bytes()

    with pytest.raises(MigrationError):
        migrate_legacy_cumulative(document_dir)

    assert cumulative.read_bytes() == original
    assert backup.is_dir(), "目录不得被当作有效恢复副本覆盖"
    assert not (document_dir / "term_candidates.json").exists()
    assert not list(document_dir.glob("*.tmp"))


def test_migrate_failure_during_candidate_write_keeps_old_file(tmp_path, monkeypatch):
    document_dir = doc_dir(tmp_path)
    cumulative = document_dir / LEGACY_CUMULATIVE_FILENAME
    write_cumulative(cumulative, [("AD", "特应性皮炎")])
    original_bytes = cumulative.read_bytes()

    monkeypatch.setattr(
        CandidateStore,
        "_write_unlocked",
        lambda *a, **k: (_ for _ in ()).throw(OSError("write failed")),
    )
    with pytest.raises(MigrationError, match="write failed"):
        migrate_legacy_cumulative(document_dir)

    assert cumulative.read_bytes() == original_bytes
    assert not (document_dir / "term_candidates.json").exists()
    assert not list(document_dir.glob("*.tmp"))
    # 备份已保留，旧文件可恢复；再次运行仍可重试迁移。
    backup = document_dir / LEGACY_CUMULATIVE_BACKUP_NAME
    backup_bytes = backup.read_bytes()
    assert backup_bytes == original_bytes
    monkeypatch.undo()
    result = migrate_legacy_cumulative(document_dir)
    assert result.status == "migrated"
    assert result.rows == 1
    assert backup.read_bytes() == backup_bytes, "重试不得覆盖已有恢复副本"


def test_migrate_failure_when_backup_copy_fails(tmp_path, monkeypatch):
    document_dir = doc_dir(tmp_path)
    cumulative = document_dir / LEGACY_CUMULATIVE_FILENAME
    write_cumulative(cumulative, [("AD", "特应性皮炎")])
    original_bytes = cumulative.read_bytes()

    monkeypatch.setattr(
        candidate_store.shutil,
        "copy2",
        lambda src, dst: (_ for _ in ()).throw(OSError("copy failed")),
    )
    with pytest.raises(MigrationError, match="copy failed"):
        migrate_legacy_cumulative(document_dir)

    assert cumulative.read_bytes() == original_bytes
    assert not (document_dir / "term_candidates.json").exists()
    assert not (document_dir / LEGACY_CUMULATIVE_BACKUP_NAME).exists()


def test_migrate_backup_replace_failure_leaves_no_half_backup(tmp_path, monkeypatch):
    document_dir = doc_dir(tmp_path)
    cumulative = document_dir / LEGACY_CUMULATIVE_FILENAME
    backup = document_dir / LEGACY_CUMULATIVE_BACKUP_NAME
    write_cumulative(cumulative, [("AD", "特应性皮炎")])
    original_bytes = cumulative.read_bytes()
    real_replace = os.replace

    def failing_replace(src, dst):  # noqa: ANN001, ANN202
        if Path(dst) == backup:
            raise OSError("backup replace failed")
        return real_replace(src, dst)

    monkeypatch.setattr(candidate_store.os, "replace", failing_replace)
    with pytest.raises(MigrationError, match="backup replace failed"):
        migrate_legacy_cumulative(document_dir)

    assert not backup.exists(), "失败后不得留下半备份"
    assert not list(document_dir.glob("*.tmp"))
    assert cumulative.read_bytes() == original_bytes
    assert not (document_dir / "term_candidates.json").exists()

    monkeypatch.undo()
    result = migrate_legacy_cumulative(document_dir)
    assert result.status == "migrated"
    assert backup.read_bytes() == original_bytes


def test_migrate_merges_into_existing_candidates_preserving_user_state(tmp_path):
    document_dir = doc_dir(tmp_path)
    store = CandidateStore(document_dir)
    store.record_observation("AD", "特应性皮炎")
    store.accept("AD", target="特应性皮炎（AT）")
    store.record_observation("TCS", "外用糖皮质激素")
    store.reject("TCS", target="外用糖皮质激素")
    store.record_observation("benefits", "获益")
    write_cumulative(
        document_dir / LEGACY_CUMULATIVE_FILENAME,
        [
            ("AD", "特应性皮炎"),
            ("TCS", "外用糖皮质激素"),
            ("TCS", "外用皮质类固醇"),
            ("JAK inhibitors", "JAK抑制剂"),
        ],
    )

    result = migrate_legacy_cumulative(document_dir)

    assert result.status == "migrated"
    assert result.rows == 4
    entries, _, metadata = CandidateStore(document_dir).load()
    assert metadata["legacy_migration"]["rows"] == 4
    by_key = {entry.source_key: entry for entry in entries}
    ad = by_key["ad"]
    assert ad.status == "accepted"
    assert ad.accepted_target == "特应性皮炎（AT）"
    assert next(s for s in ad.targets if s.target == "特应性皮炎").observations == 2
    tcs = by_key["tcs"]
    assert tcs.status == "rejected"
    assert tcs.rejected_targets == ["外用糖皮质激素"]
    assert next(s for s in tcs.targets if s.target == "外用糖皮质激素").observations == 2
    assert {s.target for s in tcs.targets} == {"外用糖皮质激素", "外用皮质类固醇"}
    assert by_key["benefits"].status == "candidate"
    assert by_key["benefits"].targets[0].observations == 1
    assert by_key["jak inhibitors"].status == "candidate"
    assert by_key["jak inhibitors"].targets[0].observations == 1


def test_migrate_noop_when_marker_present_ignores_cumulative(tmp_path):
    document_dir = doc_dir(tmp_path)
    cumulative = document_dir / LEGACY_CUMULATIVE_FILENAME
    write_cumulative(cumulative, [("AD", "特应性皮炎")])
    migrate_legacy_cumulative(document_dir)
    candidates_path = document_dir / "term_candidates.json"
    candidates_bytes = candidates_path.read_bytes()
    cumulative.write_bytes(b"\xff broken")

    result = migrate_legacy_cumulative(document_dir)

    assert result.status == "noop"
    assert candidates_path.read_bytes() == candidates_bytes


def test_migrate_does_not_overwrite_existing_backup(tmp_path):
    document_dir = doc_dir(tmp_path)
    cumulative = document_dir / LEGACY_CUMULATIVE_FILENAME
    write_cumulative(cumulative, [("AD", "特应性皮炎")])
    backup = document_dir / LEGACY_CUMULATIVE_BACKUP_NAME
    backup.write_bytes(b"existing recovery copy")

    result = migrate_legacy_cumulative(document_dir)

    assert result.status == "migrated"
    assert backup.read_bytes() == b"existing recovery copy"


def test_concurrent_migrations_merge_once(tmp_path):
    document_dir = doc_dir(tmp_path)
    cumulative = document_dir / LEGACY_CUMULATIVE_FILENAME
    write_cumulative(cumulative, [("AD", "特应性皮炎")] * 3)
    barrier = threading.Barrier(2)
    results = []
    errors = []

    def worker() -> None:
        try:
            barrier.wait(timeout=5)
            results.append(migrate_legacy_cumulative(document_dir))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert errors == []
    assert sorted(result.status for result in results) == ["migrated", "noop"]
    entries, _, metadata = CandidateStore(document_dir).load()
    assert entries[0].targets[0].observations == 3, "并发迁移不得重复累加观察"
    assert metadata["legacy_migration"]["rows"] == 3
    assert (document_dir / LEGACY_CUMULATIVE_BACKUP_NAME).exists()
    assert not list(document_dir.glob("*.tmp"))


def _read_csv_rows(path: Path) -> list[tuple[str, str]]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return [(row["source"], row["target"]) for row in reader]


def test_migration_and_auto_merge_share_cumulative_snapshot(tmp_path, monkeypatch):
    """自动合并与迁移共用 cumulative 路径锁：备份与迁入 rows 必须是同一快照。"""
    document_dir = doc_dir(tmp_path)
    cumulative = document_dir / LEGACY_CUMULATIVE_FILENAME
    write_cumulative(cumulative, [("AD", "特应性皮炎")])
    auto = document_dir / "auto.csv"
    write_cumulative(auto, [("TCS", "外用糖皮质激素")])

    entered = threading.Event()
    release = threading.Event()
    merge_done = threading.Event()
    errors = []
    real_read = legacy_migration._read_cumulative_rows

    def slow_read(path: Path) -> list[tuple[str, str]]:
        entered.set()
        assert release.wait(timeout=10)
        return real_read(path)

    monkeypatch.setattr(legacy_migration, "_read_cumulative_rows", slow_read)

    def migrate_worker() -> None:
        try:
            migrate_legacy_cumulative(document_dir)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    def merge_worker() -> None:
        try:
            merge_glossary_csvs(cumulative, auto)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            merge_done.set()

    migrate_thread = threading.Thread(target=migrate_worker)
    migrate_thread.start()
    assert entered.wait(timeout=10), "迁移未进入 cumulative 锁内读取"

    merge_thread = threading.Thread(target=merge_worker)
    merge_thread.start()
    time.sleep(0.3)
    assert not merge_done.is_set(), "自动合并不得在迁移持有 cumulative 锁时替换旧文件"

    release.set()
    migrate_thread.join(timeout=20)
    merge_thread.join(timeout=20)

    assert errors == []
    assert merge_done.is_set()
    entries, _, _ = CandidateStore(document_dir).load()
    assert [entry.source_key for entry in entries] == ["ad"], "迁入 rows 只能是迁移锁内快照"
    backup = document_dir / LEGACY_CUMULATIVE_BACKUP_NAME
    assert _read_csv_rows(backup) == [("AD", "特应性皮炎")], "备份必须与迁入 rows 同一快照"
    assert _read_csv_rows(cumulative) == [("AD", "特应性皮炎"), ("TCS", "外用糖皮质激素")]
    assert not list(document_dir.glob("*.tmp"))


def test_migrate_requires_document_hash_dir(tmp_path):
    with pytest.raises(TermStoreError, match="64-char hex hash"):
        migrate_legacy_cumulative(tmp_path)


def test_migrated_candidates_remain_observable_by_auto_flow(tmp_path):
    document_dir = doc_dir(tmp_path)
    write_cumulative(document_dir / LEGACY_CUMULATIVE_FILENAME, [("AD", "特应性皮炎")])
    migrate_legacy_cumulative(document_dir)
    store = CandidateStore(document_dir)
    store.record_observation("AD", "特应性皮炎", pages=[4], evidence=["page 4"])
    store.record_observation("AD", "新建议", pages=[5])
    entries, _, _ = store.load()
    assert entries[0].status == "candidate"
    by_target = {s.target: s for s in entries[0].targets}
    assert by_target["特应性皮炎"].observations == 2
    assert by_target["特应性皮炎"].pages == (4,)
    assert by_target["新建议"].observations == 1
    payload = json.loads(store.path.read_text(encoding="utf-8"))
    assert payload["legacy_migration"]["rows"] == 1


def test_p203_legacy_cumulative_never_becomes_authoritative(tmp_path):
    """P2-03 不变量：旧累计词表只迁移为未审核候选，绝不进入权威或有效词表。"""
    document_dir = doc_dir(tmp_path)
    cumulative = document_dir / LEGACY_CUMULATIVE_FILENAME
    write_cumulative(cumulative, [("AD", "特应性皮炎"), ("TCS", "外用糖皮质激素")])
    original_bytes = cumulative.read_bytes()

    result = migrate_legacy_cumulative(document_dir)

    assert result.status == "migrated"
    assert cumulative.exists(), "兼容期内旧累计词表不得删除"
    assert cumulative.read_bytes() == original_bytes
    backup = document_dir / LEGACY_CUMULATIVE_BACKUP_NAME
    assert backup.exists() and backup.read_bytes() == original_bytes
    assert not (document_dir / "user_glossary.csv").exists(), "迁移不得创建或写入文档权威词表"

    entries, _, metadata = CandidateStore(document_dir).load()
    assert metadata["legacy_migration"]["rows"] == 2
    assert {entry.source for entry in entries} == {"AD", "TCS"}
    assert all(entry.status == "candidate" for entry in entries)
    assert all(entry.accepted_target is None for entry in entries)

    global_path = tmp_path / "global.csv"
    write_cumulative(global_path, [])
    compile_effective_glossary(document_dir, global_path)
    effective_path = document_dir / "effective_glossary.csv"
    assert effective_path.exists()
    assert _read_csv_rows(effective_path) == [], "未审核候选不得进入 effective_glossary.csv"
