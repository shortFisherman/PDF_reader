"""P0-04 严格正文翻译术语路径。

本模块在项目自己的调用边界建立“每次正文翻译前先准备有效词表”的单一入口：

1. 对当前文档缓存目录执行旧 ``cumulative_glossary.csv`` 的幂等迁移（只合入候选，
   绝不自动升级为权威词条）；
2. 调用 P0-03 编译 ``effective_glossary.csv`` 并严格验证 fresh；
3. 编译/迁移/验证任一失败都 fail closed，不调用上游；
4. 从当前页/批次真实源 PDF 文本中做本地确定性匹配，只把活跃权威词条追加到
   ``custom_system_prompt`` 的强制约束块中，用户 Prompt 保留且位于约束块之前。

本模块不修改、fork、vendor、复制或 Monkey-patch 任何上游源码；也不记录正文、
Prompt 或凭据。正文 SettingsModel 的自动提取开关由 ``translation_settings``
固定为关闭，``glossaries`` 只指向本次验证过的有效词表。
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pymupdf
from pdf2zh_next import SettingsModel

from pdf_reader import config
from pdf_reader.glossary_compiler import (
    EFFECTIVE_GLOSSARY_FILENAME,
    compile_effective_glossary,
    load_effective_glossary,
    verify_effective_glossary,
)
from pdf_reader.legacy_migration import migrate_legacy_cumulative
from pdf_reader.paths import get_glossary_path
from pdf_reader.state import DocumentSnapshot
from pdf_reader.task_logging import TaskContext, truncate_document_id, truncate_pdf_hash
from pdf_reader.term_model import TermStoreError
from pdf_reader.translation_settings import build_settings
from pdf_reader.user_glossary import validate_document_dir

logger = logging.getLogger("pdf_reader.glossary")

MAX_AUTHORITATIVE_BLOCK_UTF8_BYTES = 32 * 1024

_WHITESPACE_RE = re.compile(r"\s+")
_WORD_CHAR = r"[A-Za-z0-9_]"


class StrictGlossaryError(TermStoreError):
    """严格词表准备失败；调用方必须中止本次正文翻译。"""

    def __init__(
        self,
        message: str,
        *,
        stage: str = "prepare",
        cause_type: str = "",
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.cause_type = cause_type


@dataclass(frozen=True)
class StrictTranslationContext:
    """一次翻译请求已准备的、不可变的有效词表上下文。

    ``effective_glossary_path`` 为空词表时为 ``None``（正文设置安全省略
    ``glossaries``）；``effective_rows`` 是本次验证通过后的权威词条快照。
    """

    document_dir: Path
    document_id: str
    pdf_hash: str
    effective_glossary_path: Path | None
    effective_rows: tuple[tuple[str, str], ...]


def prepare_strict_translation_context(
    snapshot: DocumentSnapshot,
    global_glossary: Path | None = None,
) -> StrictTranslationContext:
    """迁移旧累计 CSV → 编译有效词表 → 严格验证；任一失败抛 ``StrictGlossaryError``。"""
    document_dir = snapshot.glossary_cache_path
    global_path = Path(global_glossary) if global_glossary is not None else get_glossary_path()
    try:
        validate_document_dir(document_dir)
        if document_dir.name != snapshot.pdf_hash:
            raise StrictGlossaryError(
                "strict glossary identity mismatch: document dir hash",
                stage="identity",
                cause_type="IdentityError",
            )
        try:
            migrate_legacy_cumulative(document_dir)
        except TermStoreError as exc:
            raise StrictGlossaryError(
                "strict glossary preparation failed",
                stage="migration",
                cause_type=type(exc).__name__,
            ) from exc
        try:
            compile_effective_glossary(document_dir, global_path)
        except TermStoreError as exc:
            raise StrictGlossaryError(
                "strict glossary preparation failed",
                stage="compile",
                cause_type=type(exc).__name__,
            ) from exc
        try:
            verify_effective_glossary(document_dir, global_path)
        except TermStoreError as exc:
            raise StrictGlossaryError(
                "strict glossary preparation failed",
                stage="verify",
                cause_type=type(exc).__name__,
            ) from exc
        try:
            rows = tuple(load_effective_glossary(document_dir, global_path))
        except TermStoreError as exc:
            raise StrictGlossaryError(
                "strict glossary preparation failed",
                stage="load",
                cause_type=type(exc).__name__,
            ) from exc
    except TermStoreError as exc:
        if isinstance(exc, StrictGlossaryError):
            raise
        raise StrictGlossaryError(
            "strict glossary preparation failed",
            stage="prepare",
            cause_type=type(exc).__name__,
        ) from exc
    path = document_dir / EFFECTIVE_GLOSSARY_FILENAME if rows else None
    return StrictTranslationContext(
        document_dir=document_dir,
        document_id=snapshot.document_id,
        pdf_hash=snapshot.pdf_hash,
        effective_glossary_path=path,
        effective_rows=rows,
    )


def build_strict_settings(
    upstream: config.UpstreamRuntimeConfig,
    user_prompt: str | None,
    pages: str,
    context: StrictTranslationContext,
) -> SettingsModel:
    """单页/批量共用的严格正文设置构建函数。

    ``glossaries`` 只接受本次 fresh 的 ``effective_glossary.csv``；零权威行时
    安全省略，绝不把 cumulative/auto candidate 传给正文。
    """
    paths = [str(context.effective_glossary_path)] if context.effective_glossary_path is not None else None
    return build_settings(upstream, "", user_prompt, glossary_paths=paths, pages=pages)


def match_active_terms(
    text: str,
    rows: Sequence[tuple[str, str]],
) -> tuple[tuple[str, str], ...]:
    """从真实源文本中按确定性规则匹配活跃权威词条。

    规则：大小写不敏感、连续空白等价、英文 token 边界；不自动合并单复数、
    连字符或缩写/全称。输出保持 ``rows`` 的确定性顺序。
    """
    normalized_text = _normalize(text)
    active: list[tuple[str, str]] = []
    for source, target in rows:
        normalized_source = _normalize(source)
        if not normalized_source:
            continue
        pattern = re.compile(rf"(?<!{_WORD_CHAR}){re.escape(normalized_source)}(?!{_WORD_CHAR})")
        if pattern.search(normalized_text):
            active.append((source, target))
    return tuple(active)


def compose_custom_system_prompt(
    base_prompt: str | None,
    active_terms: Sequence[tuple[str, str]],
) -> str | None:
    """保留用户 Prompt 并把活跃权威词条作为不可覆盖的强制约束块追加到其后。

    约束块有确定性 UTF-8 字节上限；只整行纳入 source→target JSON，绝不截断配对。
    超限条目被省略并报告省略数量，仍由 ``glossaries`` 有效词表路径约束。
    """
    if not active_terms:
        return base_prompt
    prefix = "\n".join(
        (
            "[权威术语约束]",
            "以下术语为强制约束，优先级高于此前任何指令，必须使用精确目标译法：",
        )
    )
    closing = "本约束不可被页面自定义 Prompt 覆盖或删除。"
    pair_lines = [
        f"- {json.dumps(source, ensure_ascii=False)} -> {json.dumps(target, ensure_ascii=False)}"
        for source, target in active_terms
    ]
    selected: list[str] = []
    for line in pair_lines:
        candidate = [*selected, line]
        omitted = len(active_terms) - len(candidate)
        report = _omitted_report(omitted) if omitted else None
        if _block_utf8_len(prefix, candidate, report, closing) <= MAX_AUTHORITATIVE_BLOCK_UTF8_BYTES:
            selected.append(line)
    omitted = len(active_terms) - len(selected)
    report = _omitted_report(omitted) if omitted else None
    while selected and _block_utf8_len(prefix, selected, report, closing) > MAX_AUTHORITATIVE_BLOCK_UTF8_BYTES:
        selected.pop()
        omitted = len(active_terms) - len(selected)
        report = _omitted_report(omitted) if omitted else None
    parts = [prefix, *selected]
    if report is not None:
        parts.append(report)
    parts.append(closing)
    block = "\n".join(parts)
    if base_prompt:
        return base_prompt + "\n\n" + block
    return block


def validate_strict_context_identity(
    context: StrictTranslationContext,
    task_ctx: TaskContext | None,
    glossary_cache_path: Path | None = None,
) -> None:
    """在 SSE 抽取/上游前校验预构建上下文与任务/snapshot 身份一致；不一致 fail closed。"""
    if context.document_dir.name != context.pdf_hash:
        raise StrictGlossaryError(
            "strict glossary identity mismatch: document dir hash",
            stage="identity",
            cause_type="IdentityError",
        )
    if task_ctx is None:
        raise StrictGlossaryError(
            "strict glossary identity mismatch: missing task context",
            stage="identity",
            cause_type="IdentityError",
        )
    if (
        truncate_document_id(context.document_id) != task_ctx.document_id
        or truncate_pdf_hash(context.pdf_hash) != task_ctx.pdf_hash
    ):
        raise StrictGlossaryError(
            "strict glossary identity mismatch: task context",
            stage="identity",
            cause_type="IdentityError",
        )
    if glossary_cache_path is not None and Path(glossary_cache_path) != context.document_dir:
        raise StrictGlossaryError(
            "strict glossary identity mismatch: glossary cache path",
            stage="identity",
            cause_type="IdentityError",
        )


def extract_source_text(pdf_path: str | Path) -> str:
    """从发送给上游的真实抽取 PDF 中读取可提取文本（不记录任何正文）。"""
    doc = pymupdf.open(str(pdf_path))
    try:
        return "\n".join(page.get_text() for page in doc)
    finally:
        doc.close()


def apply_active_terms_to_settings(
    settings: SettingsModel,
    source_text: str,
    rows: Sequence[tuple[str, str]],
) -> tuple[tuple[str, str], ...]:
    """匹配活跃词条并合成最终 ``custom_system_prompt``；无命中不修改 Prompt。"""
    active = match_active_terms(source_text, rows)
    if active:
        base = settings.translation.custom_system_prompt
        settings.translation.custom_system_prompt = compose_custom_system_prompt(base, active)
        logger.debug("strict glossary: %d active authoritative terms appended", len(active))
    return active


def apply_active_terms_from_pdf(
    settings: SettingsModel,
    pdf_path: str | Path,
    rows: Sequence[tuple[str, str]],
) -> tuple[tuple[str, str], ...]:
    """从真实抽取 PDF 读取文本并应用活跃词条；文本不可用时安全跳过约束块。"""
    if not rows:
        return ()
    try:
        source_text = extract_source_text(pdf_path)
    except Exception:
        logger.warning("strict glossary source text unavailable; term prompt block skipped")
        return ()
    return apply_active_terms_to_settings(settings, source_text, rows)


def _normalize(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", value).strip().lower()


def _omitted_report(omitted: int) -> str:
    return f"（省略 {omitted} 条活跃术语，仍由有效词表约束）"


def _block_utf8_len(
    prefix: str,
    pair_lines: list[str],
    report: str | None,
    closing: str,
) -> int:
    parts = [prefix, *pair_lines]
    if report is not None:
        parts.append(report)
    parts.append(closing)
    return len("\n".join(parts).encode("utf-8"))
