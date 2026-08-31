"""P0-02/P1-03 术语状态模型：权威/候选/拒绝语义、source key 规范化与共享错误。

本模块只定义数据形状、常量与校验，不负责文件读写；持久化见
``user_glossary``、``candidate_store`` 与 ``legacy_migration``。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

CANDIDATE_SCHEMA_VERSION = 3
CANDIDATE_SCHEMA_VERSION_V1 = 1
CANDIDATE_SCHEMA_VERSION_V2 = 2
USER_GLOSSARY_SCHEMA_VERSION = 1

LEGACY_CUMULATIVE_FILENAME = "cumulative_glossary.csv"
LEGACY_CUMULATIVE_STRATEGY = "legacy-cumulative-csv/1"

# 自动流程禁止写入的文件名：文档权威术语、全局权威术语、编译产物与候选状态。
PROTECTED_AUTHORITATIVE_FILENAMES = frozenset(
    {"user_glossary.csv", "effective_glossary.csv", "glossary.csv", "term_candidates.json"}
)

CandidateStatus = Literal["candidate", "rejected", "accepted"]
TermScope = Literal["global", "document"]

_WHITESPACE_RE = re.compile(r"\s+")
_INVALID_TEXT_RE = re.compile(r"[\x00\r\n]")


class TermStoreError(RuntimeError):
    """术语存储层错误基类：损坏文件、路径控制、非法字段等。"""


class GlossaryRevisionConflictError(TermStoreError):
    """乐观并发冲突：磁盘 revision 与调用方期望不一致。"""

    def __init__(self, message: str, expected: int, actual: int) -> None:
        super().__init__(message)
        self.expected = expected
        self.actual = actual


class GlossaryLockedError(TermStoreError):
    """锁定词条不允许编辑/删除，需先解锁。"""


class GlossaryConflictError(TermStoreError):
    """同规范化 source 已存在，不允许重复新增。"""


class TermNotFoundError(TermStoreError):
    """按规范化 source 找不到记录。"""


class CandidateStateError(TermStoreError):
    """候选状态不允许当前操作。"""


class MigrationError(TermStoreError):
    """旧累计词表迁移失败；旧文件保持原样。"""


def normalize_source_key(source: str) -> str:
    """英文源术语的规范化 key：统一大小写与连续空白（P0-02 最小边界）。"""
    return _WHITESPACE_RE.sub(" ", source.strip()).lower()


def validate_term_text(value: str, field_name: str) -> str:
    """清洗并校验 source/target：非空、去首尾空白、禁止换行/NUL。"""
    if not isinstance(value, str):
        raise TermStoreError(f"{field_name} must be a string")
    text = value.strip()
    if not text:
        raise TermStoreError(f"{field_name} must not be empty")
    if _INVALID_TEXT_RE.search(text):
        raise TermStoreError(f"{field_name} contains invalid control characters")
    return text


def validate_note(value: str) -> str:
    """校验可选备注：允许为空，但禁止换行/NUL。"""
    if not isinstance(value, str):
        raise TermStoreError("note must be a string")
    text = value.strip()
    if _INVALID_TEXT_RE.search(text):
        raise TermStoreError("note contains invalid control characters")
    return text


def validate_strategy_version(value: str) -> str:
    """校验候选策略版本：非空、禁止控制字符，返回去首尾空白后的规范值。"""
    if not isinstance(value, str):
        raise TermStoreError("strategy_version must be a string")
    text = value.strip()
    if not text:
        raise TermStoreError("strategy_version must not be empty")
    if _INVALID_TEXT_RE.search(text):
        raise TermStoreError("strategy_version contains invalid control characters")
    return text


def format_timestamp(value: datetime) -> str:
    """统一 UTC ISO-8601 秒精度格式，保证输出字节稳定。"""
    return value.astimezone(UTC).isoformat(timespec="seconds")


def parse_timestamp(value: str) -> datetime:
    """解析 ISO-8601 时间戳；缺失时区视为 UTC。"""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise TermStoreError(f"invalid timestamp {value!r}") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


@dataclass(frozen=True)
class AuthoritativeTerm:
    """权威术语记录：用户创建/确认/锁定后的 source → target 决定。"""

    source: str
    target: str
    scope: TermScope
    locked: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    note: str = ""

    @property
    def source_key(self) -> str:
        return normalize_source_key(self.source)


@dataclass(frozen=True)
class TargetSuggestion:
    """一个 target 建议及其真实观察次数、去重页码、有界证据与最近观察时间。"""

    target: str
    observations: int = 1
    pages: tuple[int, ...] = ()
    evidence: tuple[str, ...] = ()
    last_observed_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def distinct_page_count(self) -> int:
        """去重后的不同页覆盖数（存储层已去重排序，此处对任何输入都安全）。"""
        return len(set(self.pages))


@dataclass
class CandidateEntry:
    """候选术语条目：自动观察只改 targets/时间，状态由用户操作决定。"""

    source: str
    status: CandidateStatus = "candidate"
    strategy_version: str = "unknown/1"
    first_seen_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_seen_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    targets: list[TargetSuggestion] = field(default_factory=list)
    accepted_target: str | None = None
    rejected_targets: list[str] = field(default_factory=list)
    locked: bool = False

    @property
    def source_key(self) -> str:
        return normalize_source_key(self.source)


@dataclass(frozen=True)
class CandidateTargetSummary:
    """P1-03 服务层摘要：单个 target 的用户状态、统计与确定性推荐顺序。"""

    target: str
    status: CandidateStatus
    accepted: bool
    rejected: bool
    suppressed: bool
    observations: int
    distinct_page_count: int
    pages: tuple[int, ...]
    last_observed_at: datetime
    rank: int


@dataclass(frozen=True)
class CandidateSuggestionSummary:
    """P1-03 服务层摘要：一个 source 的候选 target 列表与统计（供未来 UI/API）。"""

    source: str
    source_key: str
    status: CandidateStatus
    accepted_target: str | None
    locked: bool
    first_seen_at: datetime
    last_seen_at: datetime
    targets: tuple[CandidateTargetSummary, ...]


def rank_target_suggestions(entry: CandidateEntry) -> tuple[TargetSuggestion, ...]:
    """P1-03 确定性推荐顺序，与批输入/线程完成顺序无关。

    accepted target > 普通未拒绝建议 > rejected target；组内先按不同页覆盖数
    降序，再按观察次数降序，最后按 target 字典序升序。
    """
    rejected = frozenset(entry.rejected_targets)
    accepted_target = entry.accepted_target if entry.status == "accepted" else None

    def tier(suggestion: TargetSuggestion) -> int:
        if accepted_target is not None and suggestion.target == accepted_target:
            return 0
        if suggestion.target in rejected:
            return 2
        return 1

    return tuple(
        sorted(
            entry.targets,
            key=lambda item: (
                tier(item),
                -item.distinct_page_count,
                -item.observations,
                item.target,
            ),
        )
    )


def summarize_candidate_entry(entry: CandidateEntry) -> CandidateSuggestionSummary:
    """把候选条目折叠为服务层摘要；target 顺序即确定性推荐顺序。"""
    source_rejected = entry.status == "rejected"
    rejected = frozenset(entry.rejected_targets)
    accepted_target = entry.accepted_target if entry.status == "accepted" else None
    targets = tuple(
        CandidateTargetSummary(
            target=suggestion.target,
            status=entry.status,
            accepted=accepted_target is not None and suggestion.target == accepted_target,
            rejected=suggestion.target in rejected,
            suppressed=source_rejected or suggestion.target in rejected,
            observations=suggestion.observations,
            distinct_page_count=suggestion.distinct_page_count,
            pages=suggestion.pages,
            last_observed_at=suggestion.last_observed_at,
            rank=index + 1,
        )
        for index, suggestion in enumerate(rank_target_suggestions(entry))
    )
    return CandidateSuggestionSummary(
        source=entry.source,
        source_key=entry.source_key,
        status=entry.status,
        accepted_target=entry.accepted_target,
        locked=entry.locked,
        first_seen_at=entry.first_seen_at,
        last_seen_at=entry.last_seen_at,
        targets=targets,
    )
