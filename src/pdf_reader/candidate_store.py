"""P0-02 候选术语存储（``term_candidates.json``）。

- 自动流程唯一写入口是 ``record_observation``：只新增/追加 target 观察，
  永不改变 candidate/accepted/rejected 状态，也不改写 ``accepted_target``。
- 用户接受/拒绝通过 ``accept``/``reject``；被拒绝的 target 保留在
  ``rejected_targets``，自动观察不会把拒绝记录恢复为可提示状态。
- 同一规范路径的所有实例共享同一把进程内锁；读—改—写全程互斥，原子提交。
- 持久文件读取 fail closed：字段缺失、类型异常、状态与 accepted_target 不一致、
  normalized key 与 source 不一致、重复规范化 source、无效 pages/evidence/
  rejected_targets 或损坏 migration 标记都拒绝加载，绝不静默更正后覆盖。
- ``merge_legacy`` 在锁内先原子创建恢复副本（已有副本绝不覆盖），再把旧累计
  行合入已有候选（保留用户状态），只写一次成功迁移标记。
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

from pdf_reader.path_locks import lock_for_path
from pdf_reader.term_model import (
    CANDIDATE_SCHEMA_VERSION,
    LEGACY_CUMULATIVE_STRATEGY,
    CandidateEntry,
    CandidateStatus,
    GlossaryRevisionConflictError,
    TargetSuggestion,
    TermNotFoundError,
    TermStoreError,
    format_timestamp,
    normalize_source_key,
    parse_timestamp,
    validate_strategy_version,
    validate_term_text,
)
from pdf_reader.user_glossary import validate_document_dir

logger = logging.getLogger("pdf_reader.glossary")

CANDIDATE_FILENAME = "term_candidates.json"
MAX_EVIDENCE_SNIPPETS = 5
MAX_EVIDENCE_LENGTH = 200


@dataclass(frozen=True)
class CandidateObservation:
    """P1-01 批量候选观察：一次响应整体校验后原子合入。"""

    source: str
    target: str
    pages: tuple[int, ...] = ()
    evidence: tuple[str, ...] = ()


_WHITESPACE_RE = re.compile(r"\s+")
_VALID_STATUSES = ("candidate", "rejected", "accepted")


def _bounded_evidence(evidence: list[str]) -> list[str]:
    """去重、折叠空白、截断并限制证据片段数量（有界原文证据）。"""
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in evidence:
        snippet = _WHITESPACE_RE.sub(" ", str(item)).strip()
        if not snippet:
            continue
        snippet = snippet[:MAX_EVIDENCE_LENGTH]
        if snippet in seen:
            continue
        seen.add(snippet)
        cleaned.append(snippet)
        if len(cleaned) >= MAX_EVIDENCE_SNIPPETS:
            break
    return cleaned


def _bounded_pages(pages: list[int] | tuple[int, ...]) -> tuple[int, ...]:
    result: list[int] = []
    for page in pages:
        if isinstance(page, bool) or not isinstance(page, int) or page < 0:
            raise TermStoreError(f"invalid page number: {page!r}")
        if page not in result:
            result.append(page)
    return tuple(sorted(result))


def _check_revision(actual: int, expected: int | None) -> None:
    if expected is not None and actual != expected:
        raise GlossaryRevisionConflictError(
            f"candidate revision conflict: expected {expected}, actual {actual}",
            expected,
            actual,
        )


def _find_or_none(entries: list[CandidateEntry], source: str) -> CandidateEntry | None:
    key = normalize_source_key(source)
    for entry in entries:
        if entry.source_key == key:
            return entry
    return None


def _require_str(raw: dict[str, object], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise TermStoreError(f"candidate entry missing {key}")
    return value


def _entry_from_dict(key: str, raw: dict[str, object]) -> CandidateEntry:
    if not isinstance(raw, dict):
        raise TermStoreError("invalid candidate entry")
    source = _require_str(raw, "source")
    try:
        canonical_source = validate_term_text(source, "source")
    except TermStoreError as exc:
        raise TermStoreError(f"invalid candidate source: {exc}") from exc
    if canonical_source != source:
        raise TermStoreError("non-canonical candidate source")
    source = canonical_source
    expected_key = normalize_source_key(source)
    if raw.get("normalized_source") != expected_key or key != expected_key:
        raise TermStoreError(f"candidate normalized_source mismatch for key {key!r}")
    status_value = raw.get("status", "candidate")
    if status_value not in _VALID_STATUSES:
        raise TermStoreError(f"invalid candidate status: {status_value!r}")
    status = cast(CandidateStatus, status_value)
    strategy = _require_str(raw, "strategy_version")
    try:
        canonical_strategy = validate_strategy_version(strategy)
    except TermStoreError as exc:
        raise TermStoreError(f"invalid strategy_version: {exc}") from exc
    if canonical_strategy != strategy:
        raise TermStoreError("non-canonical strategy_version")
    strategy = canonical_strategy
    first_seen_at = parse_timestamp(_require_str(raw, "first_seen_at"))
    last_seen_at = parse_timestamp(_require_str(raw, "last_seen_at"))
    targets_raw = raw.get("targets")
    if not isinstance(targets_raw, list) or not targets_raw:
        raise TermStoreError("invalid candidate targets")
    targets: list[TargetSuggestion] = []
    for item in targets_raw:
        if not isinstance(item, dict):
            raise TermStoreError("invalid target suggestion")
        target = item.get("target")
        if not isinstance(target, str) or not target.strip():
            raise TermStoreError("target suggestion missing target")
        try:
            canonical_target = validate_term_text(target, "target")
        except TermStoreError as exc:
            raise TermStoreError(f"invalid target suggestion: {exc}") from exc
        if canonical_target != target:
            raise TermStoreError("non-canonical target suggestion")
        target = canonical_target
        observations = item.get("observations")
        if isinstance(observations, bool) or not isinstance(observations, int) or observations < 1:
            raise TermStoreError("invalid observations")
        pages_raw = item.get("pages")
        if not isinstance(pages_raw, list):
            raise TermStoreError("invalid pages")
        pages_list: list[int] = []
        for page in pages_raw:
            if isinstance(page, bool) or not isinstance(page, int) or page < 0:
                raise TermStoreError(f"invalid page number: {page!r}")
            if page in pages_list:
                raise TermStoreError(f"duplicate page number: {page!r}")
            pages_list.append(page)
        evidence_raw = item.get("evidence")
        if not isinstance(evidence_raw, list) or len(evidence_raw) > MAX_EVIDENCE_SNIPPETS:
            raise TermStoreError("invalid evidence")
        evidence: list[str] = []
        for snippet in evidence_raw:
            if not isinstance(snippet, str) or not snippet.strip():
                raise TermStoreError("invalid evidence snippet")
            if len(snippet) > MAX_EVIDENCE_LENGTH:
                raise TermStoreError("evidence snippet exceeds bound")
            evidence.append(snippet)
        targets.append(
            TargetSuggestion(
                target=target,
                observations=observations,
                pages=tuple(pages_list),
                evidence=tuple(evidence),
            )
        )
    accepted_target = raw.get("accepted_target")
    if accepted_target is not None and (not isinstance(accepted_target, str) or not accepted_target.strip()):
        raise TermStoreError("invalid accepted_target")
    if accepted_target is not None:
        try:
            canonical_accepted = validate_term_text(accepted_target, "accepted_target")
        except TermStoreError as exc:
            raise TermStoreError(f"invalid accepted_target: {exc}") from exc
        if canonical_accepted != accepted_target:
            raise TermStoreError("non-canonical accepted_target")
        accepted_target = canonical_accepted
    if status == "accepted":
        if accepted_target is None:
            raise TermStoreError("accepted candidate missing accepted_target")
        if not any(suggestion.target == accepted_target for suggestion in targets):
            raise TermStoreError("accepted_target not present in targets")
    elif accepted_target is not None:
        raise TermStoreError("accepted_target set on non-accepted candidate")
    rejected_raw = raw.get("rejected_targets", [])
    if not isinstance(rejected_raw, list):
        raise TermStoreError("invalid rejected_targets")
    rejected: list[str] = []
    for item in rejected_raw:
        if not isinstance(item, str) or not item.strip():
            raise TermStoreError("invalid rejected target")
        try:
            canonical_item = validate_term_text(item, "rejected_targets")
        except TermStoreError as exc:
            raise TermStoreError(f"invalid rejected target: {exc}") from exc
        if canonical_item != item:
            raise TermStoreError("non-canonical rejected target")
        item = canonical_item
        if item in rejected:
            raise TermStoreError("duplicate rejected target")
        rejected.append(item)
    return CandidateEntry(
        source=source,
        status=status,
        strategy_version=strategy,
        first_seen_at=first_seen_at,
        last_seen_at=last_seen_at,
        targets=targets,
        accepted_target=accepted_target,
        rejected_targets=rejected,
    )


def _entry_to_dict(entry: CandidateEntry) -> dict[str, object]:
    return {
        "source": entry.source,
        "normalized_source": entry.source_key,
        "status": entry.status,
        "strategy_version": entry.strategy_version,
        "first_seen_at": format_timestamp(entry.first_seen_at),
        "last_seen_at": format_timestamp(entry.last_seen_at),
        "targets": [
            {
                "target": suggestion.target,
                "observations": suggestion.observations,
                "pages": list(suggestion.pages),
                "evidence": list(suggestion.evidence),
            }
            for suggestion in sorted(entry.targets, key=lambda item: item.target)
        ],
        "accepted_target": entry.accepted_target,
        "rejected_targets": list(entry.rejected_targets),
    }


def _create_backup_if_missing(source: Path, backup: Path) -> None:
    """原子创建恢复副本；已有副本绝不覆盖，失败不留下半备份。"""
    if backup.exists():
        if not backup.is_file():
            raise TermStoreError(f"backup path is not a regular file: {backup}")
        return
    tmp = backup.with_name(backup.name + ".tmp")
    try:
        shutil.copy2(source, tmp)
        with tmp.open("r+b") as f:
            os.fsync(f.fileno())
        os.replace(tmp, backup)
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


class CandidateStore:
    """候选术语存储：自动观察合并 + 用户 accept/reject + 原子持久化。"""

    def __init__(self, document_dir: Path) -> None:
        validate_document_dir(document_dir)
        self.document_dir = document_dir
        self.path = document_dir / CANDIDATE_FILENAME
        # 同一规范路径的所有实例共享同一把进程内锁，避免双实例读改写竞态。
        self._lock = lock_for_path(self.path)

    def load(self) -> tuple[list[CandidateEntry], int, dict[str, object]]:
        """返回 (entries, revision, metadata)；文件不存在时返回 ([], 0, {})。"""
        with self._lock:
            return self._read_unlocked()

    def record_observation(
        self,
        source: str,
        target: str,
        *,
        pages: list[int] | tuple[int, ...] = (),
        evidence: list[str] | tuple[str, ...] = (),
        strategy_version: str = "auto/1",
        expected_revision: int | None = None,
    ) -> int:
        """自动流程观察入口：合并计数/页码/证据，绝不改变状态或用户决定。"""
        return self.record_observations(
            [CandidateObservation(source=source, target=target, pages=tuple(pages), evidence=tuple(evidence))],
            strategy_version=strategy_version,
            expected_revision=expected_revision,
        )

    def record_observations(
        self,
        observations: list[CandidateObservation] | tuple[CandidateObservation, ...],
        *,
        strategy_version: str = "auto/1",
        expected_revision: int | None = None,
    ) -> int:
        """P1-01 批量原子观察入口。

        一次响应内的全部观察先完成类型/文本/页码/证据校验，全部合法后才在
        同一把路径锁内一次性合并并只写一次 revision；任一观察非法则不写任何
        内容。自动观察只新增/追加 target 观察，永不改变 candidate/accepted/
        rejected 状态，也不改写 ``accepted_target``。
        """
        with self._lock:
            entries, revision, metadata = self._read_unlocked()
            _check_revision(revision, expected_revision)
            clean_strategy = validate_strategy_version(strategy_version)
            prepared: list[tuple[str, str, tuple[int, ...], tuple[str, ...]]] = []
            for observation in observations:
                if not isinstance(observation, CandidateObservation):
                    raise TermStoreError("invalid candidate observation")
                clean_source = validate_term_text(observation.source, "source")
                clean_target = validate_term_text(observation.target, "target")
                clean_pages = _bounded_pages(list(observation.pages))
                clean_evidence = tuple(_bounded_evidence(list(observation.evidence)))
                prepared.append((clean_source, clean_target, clean_pages, clean_evidence))
            if not prepared:
                return revision
            now = datetime.now(UTC)
            for clean_source, clean_target, clean_pages, clean_evidence in prepared:
                entry = _find_or_none(entries, clean_source)
                if entry is None:
                    entries.append(
                        CandidateEntry(
                            source=clean_source,
                            status="candidate",
                            strategy_version=clean_strategy,
                            first_seen_at=now,
                            last_seen_at=now,
                            targets=[
                                TargetSuggestion(
                                    target=clean_target,
                                    observations=1,
                                    pages=clean_pages,
                                    evidence=clean_evidence,
                                )
                            ],
                        )
                    )
                else:
                    entry.last_seen_at = now
                    for index, suggestion in enumerate(entry.targets):
                        if suggestion.target == clean_target:
                            entry.targets[index] = TargetSuggestion(
                                target=clean_target,
                                observations=suggestion.observations + 1,
                                pages=tuple(sorted(set(suggestion.pages) | set(clean_pages))),
                                evidence=tuple(_bounded_evidence([*suggestion.evidence, *clean_evidence])),
                            )
                            break
                    else:
                        entry.targets.append(
                            TargetSuggestion(
                                target=clean_target,
                                observations=1,
                                pages=clean_pages,
                                evidence=clean_evidence,
                            )
                        )
            return self._write_unlocked(entries, revision, metadata)

    def accept(
        self,
        source: str,
        *,
        target: str | None = None,
        expected_revision: int | None = None,
    ) -> tuple[CandidateEntry, int]:
        """用户接受候选；可同时编辑最终 target。状态改为 accepted。"""
        with self._lock:
            entries, revision, metadata = self._read_unlocked()
            _check_revision(revision, expected_revision)
            entry = _find_or_none(entries, source)
            if entry is None:
                raise TermNotFoundError(f"candidate not found: {source!r}")
            if target is None:
                if not entry.targets:
                    raise TermStoreError("candidate has no target suggestion to accept")
                final_target = entry.targets[0].target
            else:
                final_target = validate_term_text(target, "target")
                if not any(suggestion.target == final_target for suggestion in entry.targets):
                    entry.targets.insert(0, TargetSuggestion(target=final_target, observations=1))
            entry.status = "accepted"
            entry.accepted_target = final_target
            entry.last_seen_at = datetime.now(UTC)
            return entry, self._write_unlocked(entries, revision, metadata)

    def reject(
        self,
        source: str,
        *,
        target: str | None = None,
        expected_revision: int | None = None,
    ) -> tuple[CandidateEntry, int]:
        """用户拒绝候选；可同时拒绝具体 target。状态改为 rejected。"""
        with self._lock:
            entries, revision, metadata = self._read_unlocked()
            _check_revision(revision, expected_revision)
            entry = _find_or_none(entries, source)
            if entry is None:
                raise TermNotFoundError(f"candidate not found: {source!r}")
            if target is not None:
                rejected = validate_term_text(target, "target")
                if rejected not in entry.rejected_targets:
                    entry.rejected_targets.append(rejected)
            entry.status = "rejected"
            entry.accepted_target = None
            entry.last_seen_at = datetime.now(UTC)
            return entry, self._write_unlocked(entries, revision, metadata)

    def merge_legacy(
        self,
        rows: list[tuple[str, str]],
        *,
        from_file: str,
        backup_source: Path,
        backup_path: Path,
        completed_at: datetime | None = None,
    ) -> tuple[Literal["migrated", "noop"], int]:
        """把旧累计行合入已有候选并写迁移标记；已有标记则 noop。

        整个 读取→备份→合入→提交 在候选路径共享锁内完成；备份不覆盖已有
        恢复副本。合入只追加/累加 target 观察，保留已有
        candidate/accepted/rejected 状态、accepted_target 与 rejected_targets。
        """
        with self._lock:
            entries, revision, metadata = self._read_unlocked()
            if metadata.get("legacy_migration") is not None:
                return "noop", revision
            _create_backup_if_missing(backup_source, backup_path)
            now = completed_at or datetime.now(UTC)
            for source, target in rows:
                entry = _find_or_none(entries, source)
                if entry is None:
                    entries.append(
                        CandidateEntry(
                            source=source,
                            status="candidate",
                            strategy_version=LEGACY_CUMULATIVE_STRATEGY,
                            first_seen_at=now,
                            last_seen_at=now,
                            targets=[TargetSuggestion(target=target, observations=1)],
                        )
                    )
                else:
                    entry.last_seen_at = now
                    for index, suggestion in enumerate(entry.targets):
                        if suggestion.target == target:
                            entry.targets[index] = TargetSuggestion(
                                target=target,
                                observations=suggestion.observations + 1,
                                pages=suggestion.pages,
                                evidence=suggestion.evidence,
                            )
                            break
                    else:
                        entry.targets.append(TargetSuggestion(target=target, observations=1))
            updated_metadata = dict(metadata)
            updated_metadata["legacy_migration"] = {
                "from": from_file,
                "rows": len(rows),
                "completed_at": format_timestamp(now),
            }
            return "migrated", self._write_unlocked(entries, revision, updated_metadata)

    def _read_unlocked(self) -> tuple[list[CandidateEntry], int, dict[str, object]]:
        if not self.path.exists():
            return [], 0, {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise TermStoreError(f"failed to read candidate store {self.path}: {exc}") from exc
        if not isinstance(data, dict):
            raise TermStoreError(f"invalid candidate store payload in {self.path}")
        schema_version = data.get("schema_version")
        if schema_version != CANDIDATE_SCHEMA_VERSION:
            raise TermStoreError(f"unsupported candidate schema version: {schema_version!r}")
        revision = data.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise TermStoreError("invalid candidate revision")
        updated_at = data.get("updated_at")
        if not isinstance(updated_at, str) or not updated_at.strip():
            raise TermStoreError("invalid candidate updated_at")
        try:
            parse_timestamp(updated_at)
        except TermStoreError as exc:
            raise TermStoreError("invalid candidate updated_at") from exc
        marker = data.get("legacy_migration")
        if marker is not None:
            if not isinstance(marker, dict):
                raise TermStoreError("invalid legacy_migration marker")
            marker_from = marker.get("from")
            marker_rows = marker.get("rows")
            marker_completed_at = marker.get("completed_at")
            if not isinstance(marker_from, str) or not marker_from.strip():
                raise TermStoreError("invalid legacy_migration.from")
            if isinstance(marker_rows, bool) or not isinstance(marker_rows, int) or marker_rows < 0:
                raise TermStoreError("invalid legacy_migration.rows")
            if not isinstance(marker_completed_at, str) or not marker_completed_at.strip():
                raise TermStoreError("invalid legacy_migration.completed_at")
            try:
                parse_timestamp(marker_completed_at)
            except TermStoreError as exc:
                raise TermStoreError("invalid legacy_migration.completed_at") from exc
        raw_candidates = data.get("candidates")
        if not isinstance(raw_candidates, dict):
            raise TermStoreError("invalid candidates object")
        entries = [_entry_from_dict(key, raw) for key, raw in raw_candidates.items()]
        entries.sort(key=lambda entry: entry.source_key)
        metadata = {
            key: value
            for key, value in data.items()
            if key not in ("schema_version", "revision", "updated_at", "candidates")
        }
        return entries, revision, metadata

    def _write_unlocked(
        self,
        entries: list[CandidateEntry],
        revision: int,
        metadata: dict[str, object],
    ) -> int:
        new_revision = revision + 1
        payload: dict[str, object] = {
            "schema_version": CANDIDATE_SCHEMA_VERSION,
            "revision": new_revision,
            "updated_at": format_timestamp(datetime.now(UTC)),
            **metadata,
            "candidates": {
                entry.source_key: _entry_to_dict(entry) for entry in sorted(entries, key=lambda item: item.source_key)
            },
        }
        tmp_path = self.path.with_name(self.path.name + ".tmp")
        try:
            with tmp_path.open("w", encoding="utf-8", newline="\n") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
                f.write("\n")
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
