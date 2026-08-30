"""P0-02 权威术语存储。

- 文档级：``cache/<pdf_hash>/user_glossary.csv``，带 schema/revision 注释头，
  原子读写、乐观 revision；locked 词条拒绝编辑/删除。
- 全局：``docs/glossary.csv`` 保留现有 ``source,target`` 手工入口，服务层只读；
  自动流程没有写入口，因此全局词条天然不会被自动改写。
"""

from __future__ import annotations

import csv
import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path

from pdf_reader.path_locks import lock_for_path
from pdf_reader.term_model import (
    USER_GLOSSARY_SCHEMA_VERSION,
    AuthoritativeTerm,
    GlossaryConflictError,
    GlossaryLockedError,
    GlossaryRevisionConflictError,
    TermNotFoundError,
    TermStoreError,
    format_timestamp,
    normalize_source_key,
    parse_timestamp,
    validate_note,
    validate_term_text,
)

logger = logging.getLogger("pdf_reader.glossary")

USER_GLOSSARY_FILENAME = "user_glossary.csv"
_DOCUMENT_DIR_RE = re.compile(r"^[0-9a-f]{64}$")
_HEADER_RE = re.compile(r"^#\s*schema_version=(\d+)(?:;\s*revision=(\d+))?\s*$")
_CSV_FIELDS = ("source", "target", "locked", "created_at", "updated_at", "note")


def validate_document_dir(document_dir: Path) -> None:
    """路径控制：文档缓存目录名必须是 64 位小写十六进制 PDF 哈希。"""
    if not isinstance(document_dir, Path) or not _DOCUMENT_DIR_RE.fullmatch(document_dir.name):
        raise TermStoreError(f"document cache dir must be a 64-char hex hash, got {str(document_dir)!r}")


def _check_revision(actual: int, expected: int | None) -> None:
    if expected is not None and actual != expected:
        raise GlossaryRevisionConflictError(
            f"glossary revision conflict: expected {expected}, actual {actual}",
            expected,
            actual,
        )


def _find_term(terms: list[AuthoritativeTerm], source: str) -> tuple[int, AuthoritativeTerm]:
    key = normalize_source_key(source)
    for index, term in enumerate(terms):
        if term.source_key == key:
            return index, term
    raise TermNotFoundError(f"source not found: {source!r}")


class UserGlossaryStore:
    """文档级权威术语存储：用户新增/编辑/删除/锁定/解锁的唯一写入口。

    读—改—写全程在进程内互斥锁下执行；新内容写入同目录临时文件，
    flush/fsync/close 后 ``os.replace`` 原子提交。任何失败保留最后有效版本。
    """

    def __init__(self, document_dir: Path) -> None:
        validate_document_dir(document_dir)
        self.document_dir = document_dir
        self.path = document_dir / USER_GLOSSARY_FILENAME
        # 同一规范路径的所有 Store 实例共享同一把进程内锁，避免双实例竞态。
        self._lock = lock_for_path(self.path)

    def load(self) -> tuple[list[AuthoritativeTerm], int]:
        """返回 (terms, revision)；文件不存在时返回 ([], 0)。"""
        with self._lock:
            return self._read()

    def add(
        self,
        source: str,
        target: str,
        *,
        locked: bool = False,
        note: str = "",
        expected_revision: int | None = None,
    ) -> tuple[AuthoritativeTerm, int]:
        with self._lock:
            terms, revision = self._read()
            _check_revision(revision, expected_revision)
            term = AuthoritativeTerm(
                source=validate_term_text(source, "source"),
                target=validate_term_text(target, "target"),
                scope="document",
                locked=locked,
                note=validate_note(note),
            )
            if any(existing.source_key == term.source_key for existing in terms):
                raise GlossaryConflictError(f"source already exists: {term.source!r}")
            terms.append(term)
            return term, self._write(terms, revision)

    def edit(
        self,
        source: str,
        target: str,
        *,
        note: str | None = None,
        expected_revision: int | None = None,
    ) -> tuple[AuthoritativeTerm, int]:
        with self._lock:
            terms, revision = self._read()
            _check_revision(revision, expected_revision)
            index, existing = _find_term(terms, source)
            if existing.locked:
                raise GlossaryLockedError(f"locked term cannot be edited: {existing.source!r}")
            updated = AuthoritativeTerm(
                source=existing.source,
                target=validate_term_text(target, "target"),
                scope=existing.scope,
                locked=existing.locked,
                created_at=existing.created_at,
                updated_at=datetime.now(UTC),
                note=existing.note if note is None else validate_note(note),
            )
            terms[index] = updated
            return updated, self._write(terms, revision)

    def delete(
        self,
        source: str,
        *,
        expected_revision: int | None = None,
    ) -> tuple[AuthoritativeTerm, int]:
        with self._lock:
            terms, revision = self._read()
            _check_revision(revision, expected_revision)
            index, existing = _find_term(terms, source)
            if existing.locked:
                raise GlossaryLockedError(f"locked term cannot be deleted: {existing.source!r}")
            removed = terms.pop(index)
            return removed, self._write(terms, revision)

    def lock(
        self,
        source: str,
        *,
        expected_revision: int | None = None,
    ) -> tuple[AuthoritativeTerm, int]:
        return self._set_locked(source, True, expected_revision)

    def unlock(
        self,
        source: str,
        *,
        expected_revision: int | None = None,
    ) -> tuple[AuthoritativeTerm, int]:
        return self._set_locked(source, False, expected_revision)

    def _set_locked(
        self,
        source: str,
        locked: bool,
        expected_revision: int | None,
    ) -> tuple[AuthoritativeTerm, int]:
        with self._lock:
            terms, revision = self._read()
            _check_revision(revision, expected_revision)
            index, existing = _find_term(terms, source)
            updated = AuthoritativeTerm(
                source=existing.source,
                target=existing.target,
                scope=existing.scope,
                locked=locked,
                created_at=existing.created_at,
                updated_at=datetime.now(UTC),
                note=existing.note,
            )
            terms[index] = updated
            return updated, self._write(terms, revision)

    def _read(self) -> tuple[list[AuthoritativeTerm], int]:
        path = self.path
        if not path.exists():
            return [], 0
        try:
            with path.open("r", newline="", encoding="utf-8-sig") as f:
                first = f.readline()
                match = _HEADER_RE.match(first.strip())
                if match is None:
                    raise TermStoreError(f"missing schema header in {path}")
                schema_version = int(match.group(1))
                if schema_version != USER_GLOSSARY_SCHEMA_VERSION:
                    raise TermStoreError(f"unsupported user glossary schema version: {schema_version}")
                revision = int(match.group(2) or 0)
                reader = csv.DictReader(f)
                if reader.fieldnames != list(_CSV_FIELDS):
                    raise TermStoreError(f"invalid user glossary header in {path}: {reader.fieldnames}")
                terms: list[AuthoritativeTerm] = []
                for row in reader:
                    source_raw = row.get("source") or ""
                    target_raw = row.get("target") or ""
                    if not source_raw and not target_raw:
                        continue
                    try:
                        source = validate_term_text(source_raw, "source")
                        target = validate_term_text(target_raw, "target")
                    except TermStoreError as exc:
                        raise TermStoreError(f"invalid user glossary row in {path}: {exc}") from exc
                    if source != source_raw:
                        raise TermStoreError(f"non-canonical source in user glossary {path}")
                    if target != target_raw:
                        raise TermStoreError(f"non-canonical target in user glossary {path}")
                    note_raw = row.get("note") or ""
                    try:
                        note = validate_note(note_raw)
                    except TermStoreError as exc:
                        raise TermStoreError(f"invalid user glossary row in {path}: {exc}") from exc
                    if note != note_raw:
                        raise TermStoreError(f"non-canonical note in user glossary {path}")
                    locked_raw = (row.get("locked") or "").strip().lower()
                    if locked_raw not in ("true", "false"):
                        raise TermStoreError(f"invalid locked value in {path}: {row.get('locked')!r}")
                    terms.append(
                        AuthoritativeTerm(
                            source=source,
                            target=target,
                            scope="document",
                            locked=locked_raw == "true",
                            created_at=parse_timestamp(row.get("created_at") or ""),
                            updated_at=parse_timestamp(row.get("updated_at") or ""),
                            note=note,
                        )
                    )
                seen_keys: set[str] = set()
                for term in terms:
                    if term.source_key in seen_keys:
                        raise TermStoreError(f"duplicate normalized source in {path}: {term.source_key}")
                    seen_keys.add(term.source_key)
                return terms, revision
        except TermStoreError:
            raise
        except Exception as exc:
            raise TermStoreError(f"failed to read user glossary {path}: {exc}") from exc

    def _write(self, terms: list[AuthoritativeTerm], revision: int) -> int:
        new_revision = revision + 1
        tmp_path = self.path.with_name(self.path.name + ".tmp")
        try:
            with tmp_path.open("w", newline="", encoding="utf-8") as f:
                f.write(f"# schema_version={USER_GLOSSARY_SCHEMA_VERSION}; revision={new_revision}\n")
                writer = csv.writer(f)
                writer.writerow(_CSV_FIELDS)
                for term in sorted(terms, key=lambda item: (item.source_key, item.source, item.target)):
                    writer.writerow(
                        [
                            term.source,
                            term.target,
                            "true" if term.locked else "false",
                            format_timestamp(term.created_at),
                            format_timestamp(term.updated_at),
                            term.note,
                        ]
                    )
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.path)
        except Exception:
            try:
                tmp_path.unlink()
            except OSError:
                pass
            raise
        return new_revision


def load_global_glossary(path: Path) -> list[AuthoritativeTerm]:
    """读取全局 ``docs/glossary.csv``（source,target）为权威术语。

    不存在或空文件返回空表；表头或行损坏抛 ``TermStoreError``，
    调用方必须中止使用该文件，绝不静默丢弃用户决定。
    """
    if not path.exists() or path.stat().st_size == 0:
        return []
    try:
        with path.open("r", newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None or not {"source", "target"}.issubset(reader.fieldnames):
                raise TermStoreError(f"invalid global glossary header in {path}: {reader.fieldnames}")
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
            terms: list[AuthoritativeTerm] = []
            for row in reader:
                source = (row.get("source") or "").strip()
                target = (row.get("target") or "").strip()
                if not source and not target:
                    continue
                if not source or not target:
                    raise TermStoreError(f"invalid global glossary row in {path}: missing source/target")
                terms.append(
                    AuthoritativeTerm(
                        source=source,
                        target=target,
                        scope="global",
                        locked=False,
                        created_at=mtime,
                        updated_at=mtime,
                    )
                )
            return terms
    except TermStoreError:
        raise
    except Exception as exc:
        raise TermStoreError(f"failed to read global glossary {path}: {exc}") from exc
