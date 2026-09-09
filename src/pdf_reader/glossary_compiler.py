"""P0-03 确定性的有效词表编译服务。

从权威输入编译只读 ``cache/<pdf_hash>/effective_glossary.csv`` 与确定性
sidecar 元数据 ``effective_glossary.meta.json``：

- 优先级固定：当前文档 ``user_glossary.csv``（locked 或用户定义）
  > ``term_candidates.json`` 中 ``status=accepted`` 的 ``accepted_target``
  > 全局 ``docs/glossary.csv``；高优先级按规范化 source key 覆盖低优先级。
- candidate/rejected 无论观察次数多少都不进入有效词表；只有用户执行接受
  后才从候选存储读取 accepted_target。
- 同一优先级同一规范化 source 出现不同 target 时 fail closed（抛
  ``GlossaryCompileError``），绝不按文件顺序静默选择；相同 target 确定性去重。
- sidecar 对候选文件同时记录完整文件摘要（present/revision/rows/sha256，
  供历史审计）与确定性的 accepted 投影（仅 ``status=accepted`` 的
  normalized source + accepted_target 的 rows + sha256）。stale 判断对
  user/global 比较完整摘要，对候选只比较 accepted 投影：candidate/rejected
  的新增、观察次数/页码/证据/策略/last_seen 变化不会让有效词表 stale；
  accepted 新增、accepted_target 修改或 accepted→rejected/candidate 才
  报告 stale。候选文件损坏时读取本身 fail closed。
- 比较只统一英文大小写与连续空白（``term_model.normalize_source_key``），
  不合并单复数、连字符、缩写/全称；输出保留获胜记录的原始 source 展示文本。
- 每个输入的“解析内容 + revision/rows + 字节 SHA-256”都在该输入路径的共享
  可重入锁内取得，sidecar 记录的是实际参与本次编译的字节摘要，不读取编译后
  的新版本。编译全程持有 effective CSV 路径锁（锁顺序：输出锁 → 输入锁，
  无反向持锁路径，不会成环）。
- CSV 与 sidecar 按确定性字节写出；相同输入重复编译字节一致。
- 新内容经同目录临时文件 flush/fsync/close 后 ``os.replace`` 原子提交，
  sidecar 提交失败时回滚 CSV，尽量保持“旧 CSV + 旧 sidecar”整体不变。
- ``verify_effective_glossary`` 在 effective CSV 锁内严格校验 sidecar 字段、
  真实 CSV 行数与哈希，并比较三类输入当前快照与 sidecar 记录；任一输入在
  编译后变化时抛 ``GlossaryStaleError``。``load_effective_glossary`` 不绕过
  sidecar：任一产物缺失/损坏即报错，只有两者都不存在时才返回空表。
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from pdf_reader.candidate_store import CANDIDATE_FILENAME, CandidateEntry, CandidateStore
from pdf_reader.path_locks import lock_for_path
from pdf_reader.paths import get_glossary_path, require_data_path
from pdf_reader.term_model import (
    AuthoritativeTerm,
    TermStoreError,
    normalize_source_key,
    validate_term_text,
)
from pdf_reader.user_glossary import (
    USER_GLOSSARY_FILENAME,
    UserGlossaryStore,
    load_global_glossary,
    validate_document_dir,
)

logger = logging.getLogger("pdf_reader.glossary")

EFFECTIVE_GLOSSARY_FILENAME = "effective_glossary.csv"
EFFECTIVE_GLOSSARY_META_FILENAME = "effective_glossary.meta.json"
GLOSSARY_COMPILER_VERSION = "glossary-compiler/1"
SIDECAR_SCHEMA_VERSION = 1
GLOBAL_GLOSSARY_LABEL = "glossary.csv"

_CSV_HEADER = ("source", "target")
_INPUT_FILENAMES = (USER_GLOSSARY_FILENAME, CANDIDATE_FILENAME, GLOBAL_GLOSSARY_LABEL)
_SIDECAR_TOP_LEVEL_KEYS = frozenset({"schema_version", "compiler_version", "inputs", "output"})
_OUTPUT_KEYS = frozenset({"filename", "sha256", "rows"})
_REVISION_INPUTS = frozenset({USER_GLOSSARY_FILENAME, CANDIDATE_FILENAME})
_SHA256_LENGTH = 64
_EMPTY_ACCEPTED_PROJECTION: dict[str, object] = {
    "rows": 0,
    "sha256": hashlib.sha256((json.dumps([], ensure_ascii=False) + "\n").encode("utf-8")).hexdigest(),
}


class GlossaryCompileError(TermStoreError):
    """有效词表编译或校验失败；失败时保留最后有效的 CSV/元数据对。"""

    def __init__(self, message: str, *, inconsistent: bool = False) -> None:
        super().__init__(message)
        self.inconsistent = inconsistent


class GlossaryStaleError(GlossaryCompileError):
    """有效词表产物仍存在，但至少一个输入在编译后发生变化。"""

    def __init__(self, message: str, changed_inputs: tuple[str, ...]) -> None:
        super().__init__(message)
        self.changed_inputs = changed_inputs


@dataclass(frozen=True)
class CompileResult:
    """一次成功编译的产物摘要。"""

    csv_path: Path
    meta_path: Path
    csv_sha256: str
    meta_sha256: str
    rows: int
    document_terms: int
    accepted_candidates: int
    global_terms: int


@dataclass(frozen=True)
class EffectiveOutput:
    """验证通过的有效词表产物信息。"""

    csv_path: Path
    meta_path: Path
    csv_sha256: str
    meta_sha256: str
    rows: int


@dataclass(frozen=True)
class _Sidecar:
    """严格解析后的 sidecar 内容。"""

    output_filename: str
    output_sha256: str
    output_rows: int
    inputs: dict[str, dict[str, object]]


def compile_effective_glossary(document_dir: Path, global_glossary: Path | None = None) -> CompileResult:
    """确定性编译文档有效词表；失败保留最后有效的 CSV/sidecar 对。"""
    validate_document_dir(document_dir)
    document_dir = require_data_path(document_dir, label="有效术语文档目录")
    global_path = Path(global_glossary) if global_glossary is not None else get_glossary_path()
    csv_path = document_dir / EFFECTIVE_GLOSSARY_FILENAME
    meta_path = document_dir / EFFECTIVE_GLOSSARY_META_FILENAME
    csv_tmp = csv_path.with_name(csv_path.name + ".tmp")
    meta_tmp = meta_path.with_name(meta_path.name + ".tmp")
    backup_tmp = csv_path.with_name(csv_path.name + ".bak.tmp")

    try:
        with lock_for_path(csv_path):
            try:
                document_terms, _, user_meta = _snapshot_user_glossary(document_dir)
                candidates, _, candidate_meta = _snapshot_candidates(document_dir)
                global_terms, global_meta = _snapshot_global(global_path)

                doc_map = _dedupe_tier(
                    [(term.source, term.target) for term in document_terms],
                    "document user glossary",
                )
                accepted_records: list[tuple[str, str]] = []
                for entry in candidates:
                    if entry.status == "accepted":
                        if entry.accepted_target is None:
                            raise GlossaryCompileError(
                                f"accepted candidate {entry.source_key!r} has no accepted_target"
                            )
                        accepted_records.append((entry.source, entry.accepted_target))
                accepted_map = _dedupe_tier(accepted_records, "accepted candidates")
                global_map = _dedupe_tier(
                    [(term.source, term.target) for term in global_terms],
                    "global glossary",
                )

                merged: dict[str, tuple[str, str]] = {}
                for tier in (doc_map, accepted_map, global_map):
                    for key, record in tier.items():
                        merged.setdefault(key, record)

                rows = sorted(
                    merged.values(),
                    key=lambda record: (normalize_source_key(record[0]), record[0], record[1]),
                )
                csv_text = _render_csv(rows)
                _stage_text(csv_tmp, csv_text)
                csv_sha256 = _sha256_file(csv_tmp)

                meta_payload: dict[str, object] = {
                    "schema_version": SIDECAR_SCHEMA_VERSION,
                    "compiler_version": GLOSSARY_COMPILER_VERSION,
                    "inputs": {
                        USER_GLOSSARY_FILENAME: user_meta,
                        CANDIDATE_FILENAME: candidate_meta,
                        GLOBAL_GLOSSARY_LABEL: global_meta,
                    },
                    "output": {
                        "filename": EFFECTIVE_GLOSSARY_FILENAME,
                        "sha256": csv_sha256,
                        "rows": len(rows),
                    },
                }
                _stage_text(meta_tmp, _render_meta(meta_payload))
                _, meta_sha256 = _commit_pair(csv_path, meta_path, csv_tmp, meta_tmp, backup_tmp)
                return CompileResult(
                    csv_path=csv_path,
                    meta_path=meta_path,
                    csv_sha256=csv_sha256,
                    meta_sha256=meta_sha256,
                    rows=len(rows),
                    document_terms=len(document_terms),
                    accepted_candidates=len(accepted_records),
                    global_terms=len(global_terms),
                )
            finally:
                # 必须在释放锁之前清理固定名临时文件：若延后到锁外，下一个并发编译
                # 可能已用同名路径写入暂存，这里的清理会误删对方刚建好的文件，导致
                # 其 _commit_pair 的 os.replace 报 FileNotFoundError。锁内清理保证
                # 本调用的临时文件只在本调用范围内消失（提交后这些 .tmp 已不存在，
                # unlink 命中 FileNotFoundError 时自动放行）。
                _cleanup_temps(csv_tmp, meta_tmp, backup_tmp)
    except GlossaryCompileError:
        raise
    except TermStoreError as exc:
        raise GlossaryCompileError(f"failed to compile effective glossary from inputs: {exc}") from exc
    except Exception as exc:
        raise GlossaryCompileError(f"failed to compile effective glossary {csv_path}: {exc}") from exc


def verify_effective_glossary(document_dir: Path, global_glossary: Path | None = None) -> EffectiveOutput:
    """在 effective CSV 锁内严格校验产物对，并检查输入快照是否仍与 sidecar 一致。"""
    validate_document_dir(document_dir)
    global_path = Path(global_glossary) if global_glossary is not None else get_glossary_path()
    csv_path = document_dir / EFFECTIVE_GLOSSARY_FILENAME
    meta_path = document_dir / EFFECTIVE_GLOSSARY_META_FILENAME
    with lock_for_path(csv_path):
        if not csv_path.exists():
            raise GlossaryCompileError(f"effective glossary CSV missing: {csv_path}")
        if not meta_path.exists():
            raise GlossaryCompileError(f"effective glossary sidecar missing: {meta_path}")
        sidecar = _read_sidecar(meta_path)
        rows = _parse_csv_rows(csv_path)
        actual_hash = _sha256_file(csv_path)
        if actual_hash != sidecar.output_sha256:
            raise GlossaryCompileError(
                f"effective glossary CSV/sidecar mismatch: sidecar {sidecar.output_sha256}, CSV {actual_hash}"
            )
        if len(rows) != sidecar.output_rows:
            raise GlossaryCompileError(
                f"effective glossary row count mismatch: sidecar {sidecar.output_rows}, CSV {len(rows)}"
            )
        current_inputs = _current_input_meta(document_dir, global_path)
        changed_names: list[str] = []
        for name in _INPUT_FILENAMES:
            recorded = sidecar.inputs[name]
            current = current_inputs[name]
            if name == CANDIDATE_FILENAME:
                if _candidate_freshness(recorded) != _candidate_freshness(current):
                    changed_names.append(name)
            elif recorded != current:
                changed_names.append(name)
        changed = tuple(changed_names)
        if changed:
            raise GlossaryStaleError(
                f"effective glossary inputs changed after compile: {', '.join(changed)}",
                changed,
            )
        return EffectiveOutput(
            csv_path=csv_path,
            meta_path=meta_path,
            csv_sha256=actual_hash,
            meta_sha256=_sha256_file(meta_path),
            rows=len(rows),
        )


def load_effective_glossary(document_dir: Path, global_glossary: Path | None = None) -> list[tuple[str, str]]:
    """读取有效词表行；产物对不存在时返回空表，任一缺失/损坏则报错。"""
    validate_document_dir(document_dir)
    csv_path = document_dir / EFFECTIVE_GLOSSARY_FILENAME
    meta_path = document_dir / EFFECTIVE_GLOSSARY_META_FILENAME
    with lock_for_path(csv_path):
        if not csv_path.exists() and not meta_path.exists():
            return []
        verify_effective_glossary(document_dir, global_glossary)
        return _parse_csv_rows(csv_path)


def _snapshot_user_glossary(document_dir: Path) -> tuple[list[AuthoritativeTerm], int, dict[str, object]]:
    """在 user_glossary 路径锁内读取词条并计算同版本字节摘要。"""
    path = document_dir / USER_GLOSSARY_FILENAME
    with lock_for_path(path):
        try:
            terms, revision = UserGlossaryStore(document_dir).load()
        except TermStoreError as exc:
            raise GlossaryCompileError(f"failed to read user glossary snapshot {path}: {exc}") from exc
        return terms, revision, _input_meta(path, revision=revision, rows=len(terms))


def _snapshot_candidates(document_dir: Path) -> tuple[list[CandidateEntry], int, dict[str, object]]:
    """在候选存储路径锁内读取候选并计算同版本字节摘要。"""
    path = document_dir / CANDIDATE_FILENAME
    with lock_for_path(path):
        try:
            entries, revision, _ = CandidateStore(document_dir).load()
        except TermStoreError as exc:
            raise GlossaryCompileError(f"failed to read candidate snapshot {path}: {exc}") from exc
        meta = _input_meta(path, revision=revision, rows=len(entries))
        if meta["present"] is True:
            meta["accepted_projection"] = _accepted_projection_meta(entries)
        return entries, revision, meta


def _snapshot_global(global_path: Path) -> tuple[list[AuthoritativeTerm], dict[str, object]]:
    """在全局词表路径锁内读取词条并计算同版本字节摘要。"""
    with lock_for_path(global_path):
        try:
            terms = load_global_glossary(global_path)
        except TermStoreError as exc:
            raise GlossaryCompileError(f"failed to read global glossary snapshot {global_path}: {exc}") from exc
        return terms, _input_meta(global_path, rows=len(terms))


def _current_input_meta(document_dir: Path, global_path: Path) -> dict[str, dict[str, object]]:
    """当前三类输入的一致快照摘要，供 stale 检查与 sidecar 记录比较。"""
    _, _, user_meta = _snapshot_user_glossary(document_dir)
    _, _, candidate_meta = _snapshot_candidates(document_dir)
    _, global_meta = _snapshot_global(global_path)
    return {
        USER_GLOSSARY_FILENAME: user_meta,
        CANDIDATE_FILENAME: candidate_meta,
        GLOBAL_GLOSSARY_LABEL: global_meta,
    }


def _dedupe_tier(records: list[tuple[str, str]], tier_label: str) -> dict[str, tuple[str, str]]:
    """同一优先级内按规范化 source 分组；冲突 target 抛错，相同 target 确定性去重。"""
    grouped: dict[str, list[tuple[str, str]]] = {}
    for source, target in records:
        key = normalize_source_key(source)
        grouped.setdefault(key, []).append((source, target))
    result: dict[str, tuple[str, str]] = {}
    for key, items in grouped.items():
        distinct_targets = sorted({target for _, target in items})
        if len(distinct_targets) > 1:
            raise GlossaryCompileError(
                f"conflicting targets for normalized source {key!r} in {tier_label}: "
                + ", ".join(repr(target) for target in distinct_targets)
            )
        result[key] = sorted(items, key=lambda item: (item[0], item[1]))[0]
    return result


def _render_csv(rows: list[tuple[str, str]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(_CSV_HEADER)
    writer.writerows(rows)
    return buffer.getvalue()


def _render_meta(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _stage_text(path: Path, text: str) -> None:
    path = require_data_path(path, label="有效术语暂存文件")
    with path.open("w", encoding="utf-8", newline="") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _input_meta(path: Path, *, revision: int | None = None, rows: int) -> dict[str, object]:
    """输入文件的确定性摘要：存在性、revision（如有）、行数与 SHA-256。"""
    if not path.exists():
        return {"present": False}
    meta: dict[str, object] = {"present": True}
    if revision is not None:
        meta["revision"] = revision
    meta["rows"] = rows
    try:
        meta["sha256"] = _sha256_file(path)
    except OSError as exc:
        raise GlossaryCompileError(f"failed to hash input {path}: {exc}") from exc
    return meta


def _accepted_projection_meta(entries: list[CandidateEntry]) -> dict[str, object]:
    """accepted 条目的确定性投影：仅 normalized source + accepted_target。"""
    accepted: list[tuple[str, str]] = []
    for entry in entries:
        if entry.status == "accepted":
            if entry.accepted_target is None:
                raise GlossaryCompileError(f"accepted candidate {entry.source_key!r} has no accepted_target")
            accepted.append((entry.source_key, entry.accepted_target))
    accepted.sort(key=lambda item: item[0])
    text = json.dumps(accepted, ensure_ascii=False) + "\n"
    return {
        "rows": len(accepted),
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def _candidate_freshness(entry: dict[str, object]) -> dict[str, object]:
    """候选输入的新鲜度键：accepted 投影；文件缺失时视为空投影。"""
    projection = entry.get("accepted_projection")
    if projection is None:
        return _EMPTY_ACCEPTED_PROJECTION
    if not isinstance(projection, dict):
        raise GlossaryCompileError("invalid accepted_projection in candidate freshness comparison")
    return projection


def _parse_csv_rows(path: Path) -> list[tuple[str, str]]:
    """严格解析有效词表 CSV：精确表头、每行恰好两列且均为规范文本。"""
    try:
        with path.open("r", newline="", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header != ["source", "target"]:
                raise GlossaryCompileError(f"invalid effective glossary header in {path}: {header!r}")
            rows: list[tuple[str, str]] = []
            for row in reader:
                if not row or (len(row) == 1 and row[0] == ""):
                    continue
                if len(row) != 2 or not row[0] or not row[1]:
                    raise GlossaryCompileError(f"invalid effective glossary row in {path}: {row!r}")
                source_raw, target_raw = row
                try:
                    source = validate_term_text(source_raw, "source")
                    target = validate_term_text(target_raw, "target")
                except TermStoreError as exc:
                    raise GlossaryCompileError(f"invalid effective glossary row in {path}: {exc}") from exc
                if source != source_raw or target != target_raw:
                    raise GlossaryCompileError(f"non-canonical effective glossary row in {path}")
                rows.append((source, target))
            return rows
    except GlossaryCompileError:
        raise
    except Exception as exc:
        raise GlossaryCompileError(f"failed to read effective glossary {path}: {exc}") from exc


def _read_sidecar(meta_path: Path) -> _Sidecar:
    """严格校验 sidecar：顶层/inputs/output 键精确，字段类型与取值严格。"""
    try:
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise GlossaryCompileError(f"failed to read effective glossary sidecar {meta_path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise GlossaryCompileError(f"invalid effective glossary sidecar payload in {meta_path}")
    if set(payload) != _SIDECAR_TOP_LEVEL_KEYS:
        raise GlossaryCompileError(f"invalid effective glossary sidecar keys in {meta_path}: {sorted(payload)}")
    schema = payload.get("schema_version")
    if schema != SIDECAR_SCHEMA_VERSION:
        raise GlossaryCompileError(f"unsupported effective glossary sidecar schema version: {schema!r}")
    compiler = payload.get("compiler_version")
    if compiler != GLOSSARY_COMPILER_VERSION:
        raise GlossaryCompileError(f"unexpected effective glossary compiler version: {compiler!r}")
    output_raw = payload.get("output")
    if not isinstance(output_raw, dict):
        raise GlossaryCompileError(f"invalid effective glossary sidecar output in {meta_path}")
    if set(output_raw) != _OUTPUT_KEYS:
        raise GlossaryCompileError(
            f"invalid effective glossary sidecar output keys in {meta_path}: {sorted(output_raw)}"
        )
    filename = output_raw.get("filename")
    if not isinstance(filename, str) or filename != EFFECTIVE_GLOSSARY_FILENAME:
        raise GlossaryCompileError(f"unexpected effective glossary filename in sidecar: {filename!r}")
    digest = output_raw.get("sha256")
    if not isinstance(digest, str) or len(digest) != _SHA256_LENGTH:
        raise GlossaryCompileError("invalid effective glossary sha256 in sidecar")
    try:
        int(digest, 16)
    except ValueError as exc:
        raise GlossaryCompileError("invalid effective glossary sha256 in sidecar") from exc
    rows = output_raw.get("rows")
    if isinstance(rows, bool) or not isinstance(rows, int) or rows < 0:
        raise GlossaryCompileError("invalid effective glossary row count in sidecar")
    inputs_raw = payload.get("inputs")
    if not isinstance(inputs_raw, dict):
        raise GlossaryCompileError("invalid effective glossary sidecar inputs")
    if set(inputs_raw) != set(_INPUT_FILENAMES):
        raise GlossaryCompileError(
            f"invalid effective glossary sidecar input entries in {meta_path}: {sorted(inputs_raw)}"
        )
    inputs: dict[str, dict[str, object]] = {}
    for name in _INPUT_FILENAMES:
        inputs[name] = _parse_input_meta(inputs_raw.get(name), name)
    return _Sidecar(
        output_filename=filename,
        output_sha256=digest,
        output_rows=rows,
        inputs=inputs,
    )


def _parse_input_meta(entry: object, name: str) -> dict[str, object]:
    """严格校验单个输入摘要条目；返回与 ``_input_meta`` 相同的规范键集。"""
    if not isinstance(entry, dict):
        raise GlossaryCompileError(f"invalid effective glossary sidecar input entry: {name}")
    present = entry.get("present")
    if present is False:
        if set(entry) != {"present"}:
            raise GlossaryCompileError(f"invalid fields in effective glossary sidecar input entry: {name}")
        return {"present": False}
    if present is not True:
        raise GlossaryCompileError(f"invalid present value in effective glossary sidecar input entry: {name}")
    allowed = {"present", "rows", "sha256"}
    if name in _REVISION_INPUTS:
        allowed.add("revision")
    if name == CANDIDATE_FILENAME:
        allowed.add("accepted_projection")
    if set(entry) != allowed:
        raise GlossaryCompileError(f"invalid fields in effective glossary sidecar input entry: {name}")
    rows = entry.get("rows")
    if isinstance(rows, bool) or not isinstance(rows, int) or rows < 0:
        raise GlossaryCompileError(f"invalid rows in effective glossary sidecar input entry: {name}")
    digest = entry.get("sha256")
    if not isinstance(digest, str) or len(digest) != _SHA256_LENGTH:
        raise GlossaryCompileError(f"invalid sha256 in effective glossary sidecar input entry: {name}")
    try:
        int(digest, 16)
    except ValueError as exc:
        raise GlossaryCompileError(f"invalid sha256 in effective glossary sidecar input entry: {name}") from exc
    result: dict[str, object] = {"present": True, "rows": rows, "sha256": digest}
    if name in _REVISION_INPUTS:
        revision = entry.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise GlossaryCompileError(f"invalid revision in effective glossary sidecar input entry: {name}")
        result["revision"] = revision
    if name == CANDIDATE_FILENAME:
        projection = entry.get("accepted_projection")
        if not isinstance(projection, dict):
            raise GlossaryCompileError(f"invalid accepted_projection in effective glossary sidecar input entry: {name}")
        if set(projection) != {"rows", "sha256"}:
            raise GlossaryCompileError(f"invalid accepted_projection in effective glossary sidecar input entry: {name}")
        projection_rows = projection.get("rows")
        if isinstance(projection_rows, bool) or not isinstance(projection_rows, int) or projection_rows < 0:
            raise GlossaryCompileError(
                f"invalid accepted_projection rows in effective glossary sidecar input entry: {name}"
            )
        projection_digest = projection.get("sha256")
        if not isinstance(projection_digest, str) or len(projection_digest) != _SHA256_LENGTH:
            raise GlossaryCompileError(
                f"invalid accepted_projection sha256 in effective glossary sidecar input entry: {name}"
            )
        try:
            int(projection_digest, 16)
        except ValueError as exc:
            raise GlossaryCompileError(
                f"invalid accepted_projection sha256 in effective glossary sidecar input entry: {name}"
            ) from exc
        result["accepted_projection"] = {"rows": projection_rows, "sha256": projection_digest}
    return result


def _commit_pair(
    csv_path: Path,
    meta_path: Path,
    csv_tmp: Path,
    meta_tmp: Path,
    backup_tmp: Path,
) -> tuple[str, str]:
    """先替换 CSV、再替换 sidecar；sidecar 失败时回滚 CSV，保持旧产物对。"""
    csv_path = require_data_path(csv_path, label="有效术语 CSV")
    meta_path = require_data_path(meta_path, label="有效术语 sidecar")
    csv_tmp = require_data_path(csv_tmp, label="有效术语 CSV 临时文件")
    meta_tmp = require_data_path(meta_tmp, label="有效术语 sidecar 临时文件")
    backup_tmp = require_data_path(backup_tmp, label="有效术语回滚备份")
    had_old_csv = csv_path.exists()
    if had_old_csv:
        shutil.copy2(csv_path, backup_tmp)
        with backup_tmp.open("r+b") as f:
            os.fsync(f.fileno())
    try:
        os.replace(csv_tmp, csv_path)
    except Exception as exc:
        raise GlossaryCompileError(f"failed to commit effective glossary CSV {csv_path}: {exc}") from exc
    try:
        os.replace(meta_tmp, meta_path)
    except Exception as exc:
        try:
            if had_old_csv:
                os.replace(backup_tmp, csv_path)
            else:
                csv_path.unlink()
        except Exception as rollback_exc:
            raise GlossaryCompileError(
                f"failed to commit effective glossary sidecar {meta_path} and rollback failed; "
                f"CSV and sidecar may be inconsistent: {exc} / {rollback_exc}",
                inconsistent=True,
            ) from rollback_exc
        raise GlossaryCompileError(
            f"failed to commit effective glossary sidecar {meta_path}; previous outputs restored: {exc}"
        ) from exc
    return _sha256_file(csv_path), _sha256_file(meta_path)


def _cleanup_temps(*paths: Path) -> None:
    for path in paths:
        try:
            safe_path = require_data_path(path, label="有效术语待清理临时文件")
            safe_path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            logger.warning("failed to remove compile temp file %s", path, exc_info=True)
