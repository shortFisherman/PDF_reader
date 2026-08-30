"""P0-05 术语合规验证、有界纠错与提交门（独立纯验证模块）。

本模块在项目自己的边界对“最终候选译文 PDF”做验证。它由两部分组成：

1. 纯文本判定核心 ``verify_translated_text``：对已提取的译文文本做规范化
   （空白/断行）后逐条输出 pass/fail/unknown，不做任何 I/O；
2. PyMuPDF 提取包装 ``verify_translated_pdf``：只负责路径、页数、提取异常与
   空文本边界，并把文本委托给纯函数；
3. 为首次合规失败的有界重试合成确定性、有界的 ``[术语合规纠错]`` 块，整行
   纳入 source→target 映射，绝不截断半行，也不替换或删除原有权威块。

本模块不做任何 PDF 字符串替换、不修改上游、不记录正文/Prompt/异常原文/路径。
验证输入（活跃权威词条）由 ``strict_glossary`` 从已抽取源 PDF 得到。
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import pymupdf

# 重试纠错块的确定性 UTF-8 字节上限：防止 Prompt 无界膨胀；超限条目整行省略并
# 报告数量，绝不截断映射半行。原有权威约束块（32 KiB 上限）保持不变并位于其前。
MAX_RETRY_CORRECTION_BLOCK_UTF8_BYTES = 16 * 1024

_WHITESPACE_RE = re.compile(r"\s+")
# CJK 统一表意文字（含扩展 A、兼容区）、日文假名与韩文谚文。
_CJK_RANGES = "\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af"
_CJK_ADJACENT_SPACE_RE = re.compile(rf"(?<=[{_CJK_RANGES}])\s+(?=[{_CJK_RANGES}])")
_ASCII_WORD = re.compile(r"^[A-Za-z0-9_]+$")


class ComplianceStatus(StrEnum):
    """单条或整体验证状态：通过/不合规/不可验证。"""

    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class TermCheck:
    """一条活跃权威术语的验证结果。"""

    source: str
    target: str
    status: ComplianceStatus
    reason: str = ""


@dataclass(frozen=True)
class ComplianceVerdict:
    """整体验证结论：任何 FAIL 即 FAIL；无 FAIL 但有 UNKNOWN 即 UNKNOWN；全 PASS 才 PASS。"""

    status: ComplianceStatus
    checks: tuple[TermCheck, ...] = ()
    reason: str = ""

    @property
    def failed_terms(self) -> tuple[tuple[str, str], ...]:
        """按输入顺序返回不合规术语，供重试纠错块使用。"""
        return tuple((check.source, check.target) for check in self.checks if check.status is ComplianceStatus.FAIL)


def normalize_text(value: str) -> str:
    """规范化可验证文本：CJK 相邻字符间空白移除 + 其余连续空白折叠为单空格。"""
    text = _CJK_ADJACENT_SPACE_RE.sub("", value)
    return _WHITESPACE_RE.sub(" ", text).strip()


def verify_translated_text(
    translated_text: str,
    active_terms: Sequence[tuple[str, str]],
) -> ComplianceVerdict:
    """纯文本判定核心：规范化译文文本并逐条精确检查活跃权威 target。

    - 无活跃词条时返回 PASS（调用方应直接跳过验证与重试成本）；
    - 规范化后文本为空 → UNKNOWN（``reason="empty_text"``）；
    - 任何 target 未命中 → FAIL；任何一条无法验证 → UNKNOWN（fail-closed）。
    本函数不做任何 I/O。
    """
    terms = tuple(active_terms)
    if not terms:
        return ComplianceVerdict(status=ComplianceStatus.PASS)
    normalized_text = normalize_text(translated_text)
    if not normalized_text:
        return ComplianceVerdict(status=ComplianceStatus.UNKNOWN, reason="empty_text")

    checks: list[TermCheck] = []
    for source, target in terms:
        normalized_target = normalize_text(target)
        if not normalized_target:
            checks.append(TermCheck(source, target, ComplianceStatus.UNKNOWN, reason="empty_target"))
            continue
        if _contains_target(normalized_text, normalized_target):
            checks.append(TermCheck(source, target, ComplianceStatus.PASS))
        else:
            checks.append(TermCheck(source, target, ComplianceStatus.FAIL, reason="target_not_found"))

    if any(check.status is ComplianceStatus.FAIL for check in checks):
        return ComplianceVerdict(status=ComplianceStatus.FAIL, checks=tuple(checks))
    if any(check.status is ComplianceStatus.UNKNOWN for check in checks):
        return ComplianceVerdict(
            status=ComplianceStatus.UNKNOWN,
            checks=tuple(checks),
            reason="empty_target",
        )
    return ComplianceVerdict(status=ComplianceStatus.PASS, checks=tuple(checks))


def verify_translated_pdf(
    pdf_path: str | Path,
    active_terms: Sequence[tuple[str, str]],
    expected_pages: int | None = None,
) -> ComplianceVerdict:
    """PyMuPDF 提取包装：只处理路径/页数/提取异常边界，判定委托纯函数。

    - 无活跃词条时返回 PASS（调用方应直接跳过验证与重试成本）；
    - 文件打不开/缺页/文本不可提取 → UNKNOWN（reason 为稳定短码）；
    - 提取出的文本交给 :func:`verify_translated_text` 做逐条判定。
    """
    terms = tuple(active_terms)
    if not terms:
        return ComplianceVerdict(status=ComplianceStatus.PASS)
    try:
        doc = pymupdf.open(str(pdf_path))
    except Exception:
        return ComplianceVerdict(status=ComplianceStatus.UNKNOWN, reason="extraction_failed")
    try:
        if expected_pages is not None and doc.page_count != expected_pages:
            return ComplianceVerdict(status=ComplianceStatus.UNKNOWN, reason="page_count_mismatch")
        text = "\n".join(page.get_text() for page in doc)
    except Exception:
        return ComplianceVerdict(status=ComplianceStatus.UNKNOWN, reason="extraction_failed")
    finally:
        try:
            doc.close()
        except Exception:
            pass
    return verify_translated_text(text, terms)


def compose_retry_correction_prompt(
    base_prompt: str | None,
    failed_terms: Sequence[tuple[str, str]],
) -> str | None:
    """在原 Prompt（含首次权威约束块）之后追加有界、确定的纠错块。

    - 保持原有权威块/用户 Prompt 完整不丢失；
    - 只整行纳入 source→target JSON 映射，超限整行省略并报告数量；
    - 同一输入始终产生同一输出。
    """
    if not failed_terms:
        return base_prompt
    prefix = "\n".join(
        (
            "[术语合规纠错]",
            "上次输出未遵守以下权威术语，必须使用精确目标译法重新翻译：",
        )
    )
    closing = "本纠错块不可被覆盖或删除，source→target 映射必须完整保留。"
    pair_lines = [
        f"- {json.dumps(source, ensure_ascii=False)} -> {json.dumps(target, ensure_ascii=False)}"
        for source, target in failed_terms
    ]
    selected: list[str] = []
    for line in pair_lines:
        candidate = [*selected, line]
        omitted = len(failed_terms) - len(candidate)
        report = _omitted_report(omitted) if omitted else None
        if _block_utf8_len(prefix, candidate, report, closing) <= MAX_RETRY_CORRECTION_BLOCK_UTF8_BYTES:
            selected.append(line)
    omitted = len(failed_terms) - len(selected)
    report = _omitted_report(omitted) if omitted else None
    while selected and _block_utf8_len(prefix, selected, report, closing) > MAX_RETRY_CORRECTION_BLOCK_UTF8_BYTES:
        selected.pop()
        omitted = len(failed_terms) - len(selected)
        report = _omitted_report(omitted) if omitted else None
    parts = [prefix, *selected]
    if report is not None:
        parts.append(report)
    parts.append(closing)
    block = "\n".join(parts)
    if base_prompt:
        return base_prompt + "\n\n" + block
    return block


def _contains_target(normalized_text: str, normalized_target: str) -> bool:
    if _ASCII_WORD.fullmatch(normalized_target):
        pattern = rf"(?<![A-Za-z0-9_]){re.escape(normalized_target)}(?![A-Za-z0-9_])"
        return re.search(pattern, normalized_text) is not None
    return normalized_target in normalized_text


def _omitted_report(omitted: int) -> str:
    return f"（省略 {omitted} 条纠错术语，仍由权威词表与原约束块约束）"


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
