"""P0-02 术语状态模型：权威/候选/拒绝语义、source key 规范化与共享错误。

本模块只定义数据形状、常量与校验，不负责文件读写；持久化见
``user_glossary``、``candidate_store`` 与 ``legacy_migration``。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

CANDIDATE_SCHEMA_VERSION = 1
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
    """一个 target 建议及其观察次数、页码与有界原文证据。"""

    target: str
    observations: int = 1
    pages: tuple[int, ...] = ()
    evidence: tuple[str, ...] = ()


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

    @property
    def source_key(self) -> str:
        return normalize_source_key(self.source)
