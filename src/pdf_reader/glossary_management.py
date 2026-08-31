"""P1-04 用户术语管理服务。

该模块把 ``user_glossary.csv``、``term_candidates.json`` 与有效词表编译器
组合成一个面向 HTTP/UI 的本地服务边界。它不改变自动候选的写入权限：自动
流程仍只能记录观察，只有这里暴露的用户操作可以新增/编辑权威术语或改变候选
状态。
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeVar

from pdf_reader.candidate_store import CandidateStore
from pdf_reader.glossary_compiler import CompileResult, GlossaryCompileError, compile_effective_glossary
from pdf_reader.path_locks import lock_for_path
from pdf_reader.paths import get_glossary_path
from pdf_reader.term_model import (
    AuthoritativeTerm,
    CandidateEntry,
    GlossaryRevisionConflictError,
    TermStoreError,
    format_timestamp,
    normalize_source_key,
    rank_target_suggestions,
    validate_note,
    validate_term_text,
)
from pdf_reader.user_glossary import UserGlossaryStore, load_global_glossary, validate_document_dir

MAX_SOURCE_LENGTH = 200
MAX_TARGET_LENGTH = 500
MAX_NOTE_LENGTH = 500
MAX_IMPORT_BYTES = 1024 * 1024
MAX_IMPORT_ROWS = 1000
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

_DANGEROUS_CSV_PREFIXES = ("=", "+", "-", "@")
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_T = TypeVar("_T")


@dataclass(frozen=True)
class RevisionToken:
    user: int
    candidates: int

    def as_dict(self) -> dict[str, int]:
        return {"user": self.user, "candidates": self.candidates}


class GlossaryRequestError(TermStoreError):
    """管理 API 可安全返回的非法请求；消息不包含原始用户文本。"""


class GlossaryEffectiveUpdateError(TermStoreError):
    """用户决定已保存，但有效词表重编译失败。"""

    def __init__(self, revisions: RevisionToken) -> None:
        super().__init__("user decision saved but effective glossary compilation failed")
        self.revisions = revisions


class GlossaryManagementRevisionConflict(GlossaryRevisionConflictError):
    """包含两份存储 revision 的管理层乐观并发冲突。"""

    def __init__(self, expected: RevisionToken, actual: RevisionToken) -> None:
        super().__init__("glossary revision conflict", expected.user, actual.user)
        self.expected_token = expected
        self.actual_token = actual


def _validate_revision_value(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise GlossaryRequestError(f"invalid revision field: {field}")
    return value


def parse_revision_token(value: object) -> RevisionToken:
    if not isinstance(value, dict) or set(value) != {"user", "candidates"}:
        raise GlossaryRequestError("revision must contain user and candidates")
    return RevisionToken(
        user=_validate_revision_value(value.get("user"), "user"),
        candidates=_validate_revision_value(value.get("candidates"), "candidates"),
    )


def _validate_user_text(value: object, field: Literal["source", "target", "note"]) -> str:
    if not isinstance(value, str):
        raise GlossaryRequestError(f"{field} must be a string")
    try:
        text = validate_note(value) if field == "note" else validate_term_text(value, field)
    except TermStoreError as exc:
        raise GlossaryRequestError(f"invalid {field}") from exc
    limit = {"source": MAX_SOURCE_LENGTH, "target": MAX_TARGET_LENGTH, "note": MAX_NOTE_LENGTH}[field]
    if len(text) > limit or _CONTROL_CHARS_RE.search(text):
        raise GlossaryRequestError(f"invalid {field}")
    if field != "note" and text.startswith(_DANGEROUS_CSV_PREFIXES):
        raise GlossaryRequestError(f"unsafe CSV prefix in {field}")
    return text


def _check_revision(actual: RevisionToken, expected: RevisionToken) -> None:
    if actual != expected:
        raise GlossaryManagementRevisionConflict(expected, actual)


def _parse_locked(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("", "false", "0", "no"):
            return False
        if normalized in ("true", "1", "yes"):
            return True
    raise GlossaryRequestError("locked must be a boolean")


class GlossaryManagementService:
    """单文档术语管理服务；调用方负责保持 AppState 文档身份稳定。"""

    def __init__(self, document_dir: Path, global_glossary: Path | None = None) -> None:
        validate_document_dir(document_dir)
        self.document_dir = document_dir
        self.global_glossary = Path(global_glossary) if global_glossary is not None else get_glossary_path()
        self.user_store = UserGlossaryStore(document_dir)
        self.candidate_store = CandidateStore(document_dir)
        self._management_lock = lock_for_path(document_dir / ".glossary-management")

    def _input_snapshot(
        self,
    ) -> tuple[list[AuthoritativeTerm], list[CandidateEntry], list[AuthoritativeTerm], RevisionToken]:
        paths = (self.user_store.path, self.candidate_store.path, self.global_glossary)
        with ExitStack() as stack:
            for path in sorted(paths, key=lambda item: str(item.resolve())):
                stack.enter_context(lock_for_path(path))
            user_terms, user_revision = self.user_store.load()
            candidates, candidate_revision, _ = self.candidate_store.load()
            global_terms = load_global_glossary(self.global_glossary)
        return user_terms, candidates, global_terms, RevisionToken(user_revision, candidate_revision)

    def revisions(self) -> RevisionToken:
        _, _, _, revisions = self._input_snapshot()
        return revisions

    def _mutate(
        self,
        expected: RevisionToken,
        action: Callable[[int, int], _T],
    ) -> tuple[_T, RevisionToken, CompileResult]:
        with self._management_lock:
            with ExitStack() as stack:
                for path in sorted(
                    (self.user_store.path, self.candidate_store.path),
                    key=lambda item: str(item.resolve()),
                ):
                    stack.enter_context(lock_for_path(path))
                _, user_revision = self.user_store.load()
                _, candidate_revision, _ = self.candidate_store.load()
                actual = RevisionToken(user_revision, candidate_revision)
                _check_revision(actual, expected)
                result = action(user_revision, candidate_revision)
            try:
                compiled = compile_effective_glossary(self.document_dir, self.global_glossary)
            except GlossaryCompileError as exc:
                raise GlossaryEffectiveUpdateError(self.revisions()) from exc
            return result, self.revisions(), compiled

    def add_term(
        self,
        source: object,
        target: object,
        *,
        locked: object = False,
        note: object = "",
        expected: RevisionToken,
    ) -> tuple[AuthoritativeTerm, RevisionToken, CompileResult]:
        clean_source = _validate_user_text(source, "source")
        clean_target = _validate_user_text(target, "target")
        clean_note = _validate_user_text(note, "note")
        clean_locked = _parse_locked(locked)
        return self._mutate(
            expected,
            lambda user_revision, _candidate_revision: self.user_store.add(
                clean_source,
                clean_target,
                locked=clean_locked,
                note=clean_note,
                expected_revision=user_revision,
            )[0],
        )

    def edit_term(
        self,
        source: object,
        new_source: object,
        target: object,
        *,
        note: object = "",
        expected: RevisionToken,
    ) -> tuple[AuthoritativeTerm, RevisionToken, CompileResult]:
        clean_source = _validate_user_text(source, "source")
        clean_new_source = _validate_user_text(new_source, "source")
        clean_target = _validate_user_text(target, "target")
        clean_note = _validate_user_text(note, "note")
        return self._mutate(
            expected,
            lambda user_revision, _candidate_revision: self.user_store.edit(
                clean_source,
                clean_target,
                new_source=clean_new_source,
                note=clean_note,
                expected_revision=user_revision,
            )[0],
        )

    def delete_term(
        self,
        source: object,
        *,
        expected: RevisionToken,
    ) -> tuple[AuthoritativeTerm, RevisionToken, CompileResult]:
        clean_source = _validate_user_text(source, "source")
        return self._mutate(
            expected,
            lambda user_revision, _candidate_revision: self.user_store.delete(
                clean_source,
                expected_revision=user_revision,
            )[0],
        )

    def set_term_locked(
        self,
        source: object,
        locked: object,
        *,
        origin: object = "user",
        expected: RevisionToken,
    ) -> tuple[AuthoritativeTerm | CandidateEntry, RevisionToken, CompileResult]:
        clean_source = _validate_user_text(source, "source")
        clean_locked = _parse_locked(locked)
        if origin not in ("user", "accepted_candidate"):
            raise GlossaryRequestError("invalid authoritative origin")

        def action(user_revision: int, candidate_revision: int) -> AuthoritativeTerm | CandidateEntry:
            if origin == "accepted_candidate":
                candidate_operation = self.candidate_store.lock if clean_locked else self.candidate_store.unlock
                return candidate_operation(clean_source, expected_revision=candidate_revision)[0]
            user_operation = self.user_store.lock if clean_locked else self.user_store.unlock
            return user_operation(clean_source, expected_revision=user_revision)[0]

        return self._mutate(expected, action)

    def accept_candidate(
        self,
        source: object,
        target: object,
        *,
        expected: RevisionToken,
    ) -> tuple[CandidateEntry, RevisionToken, CompileResult]:
        clean_source = _validate_user_text(source, "source")
        clean_target = _validate_user_text(target, "target")
        return self._mutate(
            expected,
            lambda _user_revision, candidate_revision: self.candidate_store.accept(
                clean_source,
                target=clean_target,
                expected_revision=candidate_revision,
            )[0],
        )

    def reject_candidate(
        self,
        source: object,
        *,
        target: object | None = None,
        expected: RevisionToken,
    ) -> tuple[CandidateEntry, RevisionToken, CompileResult]:
        clean_source = _validate_user_text(source, "source")
        clean_target = None if target is None else _validate_user_text(target, "target")
        return self._mutate(
            expected,
            lambda _user_revision, candidate_revision: self.candidate_store.reject(
                clean_source,
                target=clean_target,
                expected_revision=candidate_revision,
            )[0],
        )

    def import_csv(
        self,
        csv_text: object,
        *,
        expected: RevisionToken,
    ) -> tuple[list[AuthoritativeTerm], RevisionToken, CompileResult]:
        records = self._parse_import(csv_text)
        return self._mutate(
            expected,
            lambda user_revision, _candidate_revision: self.user_store.add_many(
                records,
                expected_revision=user_revision,
            )[0],
        )

    def _parse_import(self, csv_text: object) -> list[tuple[str, str, bool, str]]:
        if not isinstance(csv_text, str):
            raise GlossaryRequestError("csv must be a string")
        if len(csv_text.encode("utf-8")) > MAX_IMPORT_BYTES:
            raise GlossaryRequestError("CSV import exceeds size limit")
        try:
            reader = csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff"), newline=""))
            fields = reader.fieldnames
            if fields is None or not {"source", "target"}.issubset(fields):
                raise GlossaryRequestError("CSV header must contain source and target")
            if set(fields) - {"source", "target", "locked", "note"}:
                raise GlossaryRequestError("CSV contains unsupported columns")
            records: list[tuple[str, str, bool, str]] = []
            seen: set[str] = set()
            for row in reader:
                if len(records) >= MAX_IMPORT_ROWS:
                    raise GlossaryRequestError("CSV import exceeds row limit")
                if None in row:
                    raise GlossaryRequestError("CSV row has too many columns")
                source_raw = row.get("source") or ""
                target_raw = row.get("target") or ""
                if not source_raw.strip() and not target_raw.strip():
                    continue
                source = _validate_user_text(source_raw, "source")
                target = _validate_user_text(target_raw, "target")
                note = _validate_user_text(row.get("note") or "", "note")
                locked = _parse_locked(row.get("locked") or False)
                key = normalize_source_key(source)
                if key in seen:
                    raise GlossaryRequestError("CSV contains duplicate source")
                seen.add(key)
                records.append((source, target, locked, note))
        except csv.Error as exc:
            raise GlossaryRequestError("invalid CSV payload") from exc
        if not records:
            raise GlossaryRequestError("CSV contains no terms")
        return records

    def export_csv(self) -> str:
        terms, _ = self.user_store.load()
        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(("source", "target", "locked", "note"))
        for term in sorted(terms, key=lambda item: (item.source_key, item.source, item.target)):
            source = _validate_user_text(term.source, "source")
            target = _validate_user_text(term.target, "target")
            note = _validate_user_text(term.note, "note")
            writer.writerow((source, target, "true" if term.locked else "false", note))
        return "\ufeff" + output.getvalue()

    def list_view(
        self,
        *,
        view: Literal["authoritative", "candidates"] = "authoritative",
        query: str = "",
        sort: str = "source",
        order: Literal["asc", "desc"] = "asc",
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> dict[str, object]:
        if view not in ("authoritative", "candidates"):
            raise GlossaryRequestError("invalid glossary view")
        if order not in ("asc", "desc"):
            raise GlossaryRequestError("invalid sort order")
        if page < 1 or page_size < 1 or page_size > MAX_PAGE_SIZE:
            raise GlossaryRequestError("invalid pagination")
        clean_query = query.strip().casefold()
        if len(clean_query) > MAX_SOURCE_LENGTH or _CONTROL_CHARS_RE.search(clean_query):
            raise GlossaryRequestError("invalid search query")
        user_terms, candidates, global_terms, revisions = self._input_snapshot()
        if view == "authoritative":
            items = self._authoritative_items(user_terms, candidates, global_terms)
            allowed_sorts = {"source", "target", "scope", "locked", "updated_at"}
        else:
            items = self._candidate_items(candidates)
            allowed_sorts = {"source", "status", "observations", "pages", "updated_at"}
        if sort not in allowed_sorts:
            raise GlossaryRequestError("invalid glossary sort")
        if clean_query:
            items = [
                item
                for item in items
                if clean_query in str(item.get("source", "")).casefold()
                or clean_query in str(item.get("target", item.get("recommended_target", ""))).casefold()
            ]
        items.sort(
            key=lambda item: (item.get(sort, ""), str(item.get("source", "")).casefold()),
            reverse=order == "desc",
        )
        total = len(items)
        start = (page - 1) * page_size
        page_items = items[start : start + page_size]
        total_pages = max(1, (total + page_size - 1) // page_size)
        return {
            "view": view,
            "items": page_items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "revision": revisions.as_dict(),
            "counts": {
                "authoritative": len(self._authoritative_items(user_terms, candidates, global_terms)),
                "candidates": len(candidates),
            },
            "candidate_notice": "候选不会影响正文；只有接受后才会进入有效词表。",
        }

    @staticmethod
    def _authoritative_items(
        user_terms: list[AuthoritativeTerm],
        candidates: list[CandidateEntry],
        global_terms: list[AuthoritativeTerm],
    ) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        document_keys = {term.source_key for term in user_terms}
        accepted = [entry for entry in candidates if entry.status == "accepted" and entry.accepted_target is not None]
        accepted_keys = {entry.source_key for entry in accepted}
        for term in user_terms:
            items.append(
                {
                    "source": term.source,
                    "target": term.target,
                    "scope": "document",
                    "origin": "user",
                    "locked": term.locked,
                    "effective": True,
                    "editable": not term.locked,
                    "lockable": True,
                    "deletable": not term.locked,
                    "note": term.note,
                    "updated_at": format_timestamp(term.updated_at),
                }
            )
        for entry in accepted:
            items.append(
                {
                    "source": entry.source,
                    "target": entry.accepted_target or "",
                    "scope": "document",
                    "origin": "accepted_candidate",
                    "locked": entry.locked,
                    "effective": entry.source_key not in document_keys,
                    "editable": not entry.locked,
                    "lockable": True,
                    "deletable": not entry.locked,
                    "note": "",
                    "updated_at": format_timestamp(entry.last_seen_at),
                }
            )
        for term in global_terms:
            items.append(
                {
                    "source": term.source,
                    "target": term.target,
                    "scope": "global",
                    "origin": "global",
                    "locked": False,
                    "effective": term.source_key not in document_keys | accepted_keys,
                    "editable": False,
                    "lockable": False,
                    "deletable": False,
                    "note": "",
                    "updated_at": format_timestamp(term.updated_at),
                }
            )
        return items

    @staticmethod
    def _candidate_items(candidates: list[CandidateEntry]) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        for entry in candidates:
            ranked = rank_target_suggestions(entry)
            targets: list[dict[str, object]] = []
            for rank, suggestion in enumerate(ranked, start=1):
                targets.append(
                    {
                        "target": suggestion.target,
                        "rank": rank,
                        "accepted": entry.status == "accepted" and entry.accepted_target == suggestion.target,
                        "rejected": suggestion.target in entry.rejected_targets,
                        "observations": suggestion.observations,
                        "distinct_page_count": suggestion.distinct_page_count,
                        "pages": [page + 1 for page in suggestion.pages],
                        "evidence": list(suggestion.evidence),
                        "last_observed_at": format_timestamp(suggestion.last_observed_at),
                    }
                )
            items.append(
                {
                    "source": entry.source,
                    "status": entry.status,
                    "affects_translation": entry.status == "accepted",
                    "accepted_target": entry.accepted_target,
                    "locked": entry.locked,
                    "recommended_target": ranked[0].target if ranked else "",
                    "observations": sum(item.observations for item in entry.targets),
                    "pages": len({page for item in entry.targets for page in item.pages}),
                    "updated_at": format_timestamp(entry.last_seen_at),
                    "targets": targets,
                }
            )
        return items
