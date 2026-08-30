"""P0-02 旧 ``cumulative_glossary.csv`` 的只读、幂等迁移。

迁移只读旧文件：``CandidateStore.merge_legacy`` 在候选路径共享锁内先把旧行
合入已有候选（保留 candidate/accepted/rejected 状态与 accepted_target），
再写成功迁移标记。只有已存在成功迁移标记时才 noop；备份绝不覆盖已有恢复
副本，创建过程不留下半备份；任何失败都保持旧文件原样。
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pdf_reader.candidate_store import CANDIDATE_FILENAME, CandidateStore
from pdf_reader.path_locks import lock_for_path
from pdf_reader.term_model import (
    LEGACY_CUMULATIVE_FILENAME,
    MigrationError,
    TermStoreError,
    validate_term_text,
)
from pdf_reader.user_glossary import validate_document_dir

logger = logging.getLogger("pdf_reader.glossary")

LEGACY_CUMULATIVE_BACKUP_NAME = "cumulative_glossary.csv.bak"


@dataclass(frozen=True)
class MigrateResult:
    """迁移结果：migrated=已合入候选；noop=无需/已有成功迁移标记。"""

    status: Literal["migrated", "noop"]
    rows: int
    backup_path: Path | None
    candidates_path: Path


def migrate_legacy_cumulative(document_dir: Path) -> MigrateResult:
    """把旧累计词表幂等地合入候选存储并写迁移标记，保留已有用户状态。"""
    validate_document_dir(document_dir)
    cumulative = document_dir / LEGACY_CUMULATIVE_FILENAME
    candidates_path = document_dir / CANDIDATE_FILENAME
    backup = document_dir / LEGACY_CUMULATIVE_BACKUP_NAME
    # 锁顺序固定 cumulative → candidate：读取 rows 与备份来源在同一快照下，
    # 自动合并（merge_glossary_csvs）只持有 cumulative 锁，不会成环。
    with lock_for_path(cumulative):
        if not cumulative.exists():
            return MigrateResult("noop", 0, None, candidates_path)

        store = CandidateStore(document_dir)
        _, _, metadata = store.load()
        if metadata.get("legacy_migration") is not None:
            return MigrateResult("noop", 0, backup if backup.exists() else None, candidates_path)

        rows = _read_cumulative_rows(cumulative)
        if not rows:
            return MigrateResult("noop", 0, None, candidates_path)

        try:
            status, _ = store.merge_legacy(
                rows,
                from_file=LEGACY_CUMULATIVE_FILENAME,
                backup_source=cumulative,
                backup_path=backup,
                completed_at=datetime.now(UTC),
            )
        except MigrationError:
            raise
        except Exception as exc:
            raise MigrationError(f"failed to migrate cumulative glossary {cumulative}: {exc}") from exc
        rows_migrated = len(rows) if status == "migrated" else 0
        return MigrateResult(
            status,
            rows_migrated,
            backup if backup.exists() else None,
            candidates_path,
        )


def _read_cumulative_rows(path: Path) -> list[tuple[str, str]]:
    try:
        with path.open("r", newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None or not {"source", "target"}.issubset(reader.fieldnames):
                raise MigrationError(f"invalid cumulative glossary header in {path}: {reader.fieldnames}")
            rows: list[tuple[str, str]] = []
            for row in reader:
                source_raw = row.get("source") or ""
                target_raw = row.get("target") or ""
                if not source_raw and not target_raw:
                    continue
                try:
                    source = validate_term_text(source_raw, "source")
                    target = validate_term_text(target_raw, "target")
                except TermStoreError as exc:
                    raise MigrationError(f"invalid cumulative glossary row in {path}: {exc}") from exc
                if source != source_raw or target != target_raw:
                    raise MigrationError(f"non-canonical cumulative glossary row in {path}")
                rows.append((source, target))
            return rows
    except MigrationError:
        raise
    except Exception as exc:
        raise MigrationError(f"failed to read cumulative glossary {path}: {exc}") from exc
