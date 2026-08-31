"""P1-02 候选后置过滤：普通词、源文证据与边界匹配。

本模块只作用于模型自动候选，绝不读取、删除、降级或重写任何权威术语、
用户决定或有效词表。过滤规则带显式版本号（``CANDIDATE_FILTER_VERSION``），
并组合进入候选 ``strategy_version``（``CANDIDATE_STRATEGY_VERSION``），
规则更新后旧候选仍可通过其策略版本解释。

所有判断都是纯函数且确定性：同一输入产生相同的保留/拒绝、页码、证据与
原因顺序。``sent_text`` 必须是实际送给模型的（含截断后的）源文本；
``page_chunks`` 是逐页、同样截断后的原文，页码为 1-based 原文页码。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from string import punctuation as _ASCII_PUNCT

from pdf_reader.candidate_store import MAX_EVIDENCE_SNIPPETS
from pdf_reader.term_extraction import STRATEGY_VERSION, TermCandidate

CANDIDATE_FILTER_VERSION = "candidate-filter/1"
CANDIDATE_STRATEGY_VERSION = f"{STRATEGY_VERSION}+{CANDIDATE_FILTER_VERSION}"

# 稳定过滤 reason 白名单（P2-02 诊断字段的唯一允许集合；新增拒绝原因必须同步）。
FILTER_REASONS = frozenset(
    {
        "placeholder",
        "invalid_source",
        "too_long",
        "too_many_words",
        "numeric",
        "formula",
        "variable",
        "page_number",
        "complete_sentence",
        "common_word",
        "bad_target",
        "no_source_match",
        "no_evidence_page",
    }
)

MAX_SOURCE_CHARS = 80
MAX_SOURCE_WORDS = 6
EVIDENCE_WINDOW_CHARS = 80
MAX_EVIDENCE_LENGTH = 160

_WHITESPACE_RE = re.compile(r"\s+")
_WORD_CHAR = r"\w"
_SOURCE_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['\u2019\-][A-Za-z0-9]+)*")
_HAN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_NUMERIC_RE = re.compile(r"^[\d\s.,%+\-/()]+$")
_FORMULA_RE = re.compile(r"[=^*_]+")
_BINARY_EXPR_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:[A-Za-z]\d*|\d+(?:\.\d+)?)"
    r"(?:\s*[+*/]\s*(?:[A-Za-z]\d*|\d+(?:\.\d+)?))+"
)
_VARIABLE_RE = re.compile(r"^[A-Za-z]$")
_PAGE_REF_RE = re.compile(
    r"\b(?:page|fig(?:ure)?|table|section|chapter|eq(?:uation)?|"
    r"ref(?:erence)?|appendix)(?:\.\s*|\s+)\d+"
    r"|(?<![A-Za-z0-9_])p(?:p)?(?:\.\s*|\s+)\d+",
    re.IGNORECASE,
)
_PLACEHOLDER_EXACT = frozenset({"tbd", "todo", "placeholder", "lorem ipsum", "xxx"})
_PLACEHOLDER_RE = re.compile(
    r"^(?:\?{2,}|\.{3,}|\[[^\]]{1,40}\]|\{\{[^}]+\}\}|x{3,})$",
    re.IGNORECASE,
)
_SENTENCE_STARTERS = frozenset(
    {
        "the",
        "a",
        "an",
        "this",
        "that",
        "these",
        "those",
        "our",
        "their",
        "his",
        "her",
        "its",
        "your",
        "we",
        "they",
        "he",
        "she",
        "it",
        "there",
        "here",
        "how",
        "what",
        "why",
        "when",
        "where",
        "who",
        "which",
        "if",
        "because",
        "although",
        "while",
        "since",
    }
)
_SENTENCE_VERBS = frozenset(
    {
        "benefit",
        "show",
        "shows",
        "demonstrate",
        "demonstrates",
        "suggest",
        "suggests",
        "indicate",
        "indicates",
        "report",
        "reports",
        "use",
        "uses",
        "receive",
        "receives",
        "experience",
        "experiences",
        "present",
        "presents",
        "occur",
        "occurs",
        "appear",
        "appears",
        "improve",
        "improves",
        "reduce",
        "reduces",
        "increase",
        "increases",
        "decrease",
        "decreases",
        "provide",
        "provides",
        "include",
        "includes",
        "represent",
        "represents",
        "remain",
        "remains",
        "lead",
        "leads",
        "cause",
        "causes",
        "recommend",
        "recommends",
        "support",
        "supports",
        "confirm",
        "confirms",
        "highlight",
        "highlights",
    }
)
_SENTENCE_CONNECTORS = frozenset(
    {
        "from",
        "of",
        "for",
        "with",
        "in",
        "on",
        "at",
        "to",
        "by",
        "that",
        "and",
        "or",
        "but",
        "after",
        "before",
        "during",
        "between",
        "without",
        "within",
        "among",
        "about",
        "against",
        "over",
        "under",
        "through",
        "as",
        "than",
    }
)
_EXTRA_PUNCT = "—–‘’“”…·«»©®™§¶±°µ"
_PUNCT_CHARS = _ASCII_PUNCT + _EXTRA_PUNCT
_LEADING_DECOR = "—–•·▪◦※"
_TRAILING_PUNCT = ".!?;:,，。！？；：、"
_WRAPPER_PAIRS = (
    ("“", "”"),
    ("‘", "’"),
    ("(", ")"),
    ("[", "]"),
    ("{", "}"),
    ("《", "》"),
    ("〈", "〉"),
    ("【", "】"),
    ("「", "」"),
    ("『", "』"),
    ("（", "）"),
    ("〔", "〕"),
    ("«", "»"),
    ("<", ">"),
    ('"', '"'),
    ("'", "'"),
)

# 小型可维护的普通词/功能词/通用学术词拒绝集合：只精确匹配清洗后的完整
# source，不拦截包含这些词的复合术语（如 “atopic dermatitis”）。
COMMON_TERMS = frozenset(
    {
        # 计划列出的真实污染词与上下文短语
        "benefits",
        "benefit",
        "cost",
        "costs",
        "confusion",
        "education",
        "burden",
        "gaining control",
        "gaining control over",
        # 高频功能词
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "for",
        "with",
        "in",
        "on",
        "at",
        "by",
        "to",
        "from",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "can",
        "could",
        "may",
        "might",
        "should",
        "would",
        "will",
        "shall",
        "must",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "they",
        "their",
        "them",
        "we",
        "our",
        "us",
        "you",
        "your",
        "he",
        "she",
        "him",
        "her",
        "his",
        "who",
        "whom",
        "whose",
        "which",
        "what",
        "when",
        "where",
        "why",
        "how",
        "not",
        "no",
        "yes",
        "so",
        "but",
        "because",
        "if",
        "then",
        "than",
        "as",
        "also",
        "too",
        "very",
        "more",
        "most",
        "less",
        "least",
        "some",
        "any",
        "each",
        "every",
        "all",
        "both",
        "many",
        "much",
        "few",
        "such",
        "only",
        "just",
        "about",
        "after",
        "before",
        "during",
        "while",
        "through",
        "between",
        "under",
        "over",
        "against",
        "without",
        "within",
        "across",
        "among",
        "along",
        "toward",
        "towards",
        # 通用学术/临床词（精确匹配；复合术语不受影响）
        "patient",
        "patients",
        "care",
        "treatment",
        "management",
        "therapy",
        "therapies",
        "medication",
        "medications",
        "drug",
        "drugs",
        "quality",
        "outcome",
        "outcomes",
        "improvement",
        "improvements",
        "risk",
        "risks",
        "effect",
        "effects",
        "impact",
        "importance",
        "need",
        "needs",
        "goal",
        "goals",
        "objective",
        "objectives",
        "concern",
        "concerns",
        "issue",
        "issues",
        "problem",
        "problems",
        "question",
        "questions",
        "result",
        "results",
        "data",
        "study",
        "studies",
        "research",
        "analysis",
        "approach",
        "approaches",
        "method",
        "methods",
        "role",
        "roles",
        "group",
        "groups",
        "level",
        "levels",
        "factor",
        "factors",
        "rate",
        "rates",
        "score",
        "scores",
        "value",
        "values",
        "mean",
        "average",
        "summary",
        "overview",
        "introduction",
        "background",
        "conclusion",
        "conclusions",
        "discussion",
        "limitation",
        "limitations",
    }
)


@dataclass(frozen=True)
class FilteredCandidate:
    """一条候选经过过滤后的结果：``reason is None`` 表示保留。

    ``source`` 是确定性清理后的源术语；``pages`` 是实际命中页（1-based、
    升序）；``evidence`` 是每条命中页上的有界、折叠空白后的原文片段。
    """

    source: str
    target: str
    pages: tuple[int, ...] = ()
    evidence: tuple[str, ...] = ()
    reason: str | None = None


def filter_candidates(
    candidates: Sequence[TermCandidate],
    sent_text: str,
    page_chunks: Sequence[tuple[int, str]],
) -> tuple[FilteredCandidate, ...]:
    """按确定性规则过滤一批候选；单条坏候选只被拒绝，不使整批失败。"""
    ordered_chunks = sorted(
        ((page, text) for page, text in page_chunks if text),
        key=lambda item: item[0],
    )
    return tuple(_filter_one(candidate, sent_text, ordered_chunks) for candidate in candidates)


def _filter_one(
    candidate: TermCandidate,
    sent_text: str,
    page_chunks: list[tuple[int, str]],
) -> FilteredCandidate:
    target = candidate.target.strip()
    folded_raw = _fold_whitespace(candidate.source).strip()
    source = _clean_source(candidate.source)

    def reject(reason: str) -> FilteredCandidate:
        return FilteredCandidate(source=source, target=target, reason=reason)

    if not source:
        return reject("placeholder" if _is_placeholder(folded_raw) else "invalid_source")
    if len(source) > MAX_SOURCE_CHARS:
        return reject("too_long")
    words = _SOURCE_WORD_RE.findall(source)
    if len(words) > MAX_SOURCE_WORDS:
        return reject("too_many_words")
    if _NUMERIC_RE.fullmatch(source):
        return reject("numeric")
    formula_or_variable = _formula_or_variable_reason(source)
    if formula_or_variable is not None:
        return reject(formula_or_variable)
    if _PAGE_REF_RE.search(source):
        return reject("page_number")
    if _is_placeholder(source):
        return reject("placeholder")
    if _is_complete_sentence(folded_raw, source):
        return reject("complete_sentence")
    if _fold_whitespace(source).strip().lower() in COMMON_TERMS:
        return reject("common_word")
    if not _HAN_RE.search(target):
        return reject("bad_target")
    if _source_pattern(source).search(sent_text) is None:
        return reject("no_source_match")
    hit_pages, evidence = _collect_hits(source, page_chunks)
    if not hit_pages:
        return reject("no_evidence_page")
    return FilteredCandidate(
        source=source,
        target=target,
        pages=hit_pages,
        evidence=evidence,
        reason=None,
    )


def _fold_whitespace(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", value)


def _clean_source(source: str) -> str:
    """保守包装/句读/项目符号清理与异常空白折叠。

    只剥前导项目符号、尾部句读和成对包裹（引号/括号），保留 CD4+、C++、
    .NET 等带语义的边缘符号，避免静默改写合法术语。
    """
    value = _fold_whitespace(source).strip()
    while True:
        previous = value
        value = value.lstrip(_LEADING_DECOR + " \t")
        value = value.rstrip(_TRAILING_PUNCT + " \t")
        value = _strip_wrappers(value)
        if value == previous:
            break
    return value


def _strip_wrappers(value: str) -> str:
    for open_, close in _WRAPPER_PAIRS:
        if value.startswith(open_) and value.endswith(close) and len(value) > len(open_) + len(close):
            return value[len(open_) : -len(close)].strip()
    return value


def _is_complete_sentence(folded_raw: str, cleaned: str) -> bool:
    """明显完整句判定：内部句读 + 首词引导 + 有限动词启发式。

    尾部 .!? 属于可清洗的句读，单独出现不构成句子（如 ``Staphylococcus
    aureus.``、``AD?``）；完整句主要依赖内容结构而非尾标点。
    """
    words = _SOURCE_WORD_RE.findall(cleaned)
    if not words:
        return False
    if len(words) >= 2 and re.search(r"\w[.!?]\s", folded_raw):
        return True
    first = words[0].strip(_PUNCT_CHARS).lower()
    if len(words) >= 2 and first in _SENTENCE_STARTERS:
        return True
    return _is_verb_sentence(words)


def _is_verb_sentence(words: list[str]) -> bool:
    if len(words) < 2 or words[1].lower() not in _SENTENCE_VERBS:
        return False
    first = words[0].strip(_PUNCT_CHARS).lower()
    if first in _SENTENCE_STARTERS:
        return True
    if first.endswith("s"):
        return True
    return len(words) >= 3 and words[2].lower() in _SENTENCE_CONNECTORS


def _formula_or_variable_reason(source: str) -> str | None:
    if _FORMULA_RE.search(source) or _BINARY_EXPR_RE.search(source):
        return "formula"
    if _VARIABLE_RE.fullmatch(source):
        return "variable"
    return None


def _is_placeholder(source: str) -> bool:
    folded = _fold_whitespace(source).strip().lower()
    return folded in _PLACEHOLDER_EXACT or _PLACEHOLDER_RE.fullmatch(folded) is not None


def _source_pattern(source: str) -> re.Pattern[str]:
    """英文单词/缩写边界感知匹配：内部空白按折叠后等价（``\\s+``）。"""
    inner = r"\s+".join(re.escape(token) for token in source.split())
    return re.compile(rf"(?<!{_WORD_CHAR}){inner}(?!{_WORD_CHAR})", re.IGNORECASE)


def _evidence_snippet(text: str, match: re.Match[str]) -> str:
    start = max(0, match.start() - EVIDENCE_WINDOW_CHARS)
    end = min(len(text), match.end() + EVIDENCE_WINDOW_CHARS)
    snippet = _fold_whitespace(text[start:end]).strip()
    return snippet[:MAX_EVIDENCE_LENGTH]


def _collect_hits(
    source: str,
    page_chunks: list[tuple[int, str]],
) -> tuple[tuple[int, ...], tuple[str, ...]]:
    pattern = _source_pattern(source)
    hit_pages: list[int] = []
    evidence: list[str] = []
    for page, text in page_chunks:
        match = pattern.search(text)
        if match is None:
            continue
        if page in hit_pages:
            continue
        hit_pages.append(page)
        if len(evidence) < MAX_EVIDENCE_SNIPPETS:
            evidence.append(_evidence_snippet(text, match))
    return tuple(sorted(hit_pages)), tuple(evidence)
