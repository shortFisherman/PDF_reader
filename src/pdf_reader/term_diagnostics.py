"""P2-02 术语诊断、统计与可解释性：受控安全摘要、稳定事件与故障隔离。

边界：
- 常规 INFO 日志只输出数量、状态、页码、耗时、token 计数、受控 reason/event
  名等稳定字段；source/target/证据/正文/Prompt/API Key 永不进入本模块产出
  的日志；
- event/status/reason 只允许显式常量集合，未知值统一输出 ``unknown``，绝不
  把原始字符串写入日志；
- prepare 批次口径为 proposed/kept/filtered/failed；``accepted``/``rejected``/
  ``pending`` 只表示 ``CandidateStore`` 中的真实持久状态，仅出现在 commit
  摘要中，避免与批内过滤计数同名异义；
- ``failed`` 的唯一事实源是按受控终态集合计算的 :func:`candidate_failed_count`，
  不依赖报告中的冗余字段；
- 诊断构造/格式化/发射都是可失败的非关键路径：任何异常都被吞掉并降级为固定
  fallback 日志，绝不阻止正文翻译、改变终态或损坏术语数据；
- token usage 三字段全部为非负 int 才可用（``TokenUsage.available`` 三者全真），
  缺失/非法明确 ``unavailable``，绝不伪造。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from pdf_reader.candidate_filter import FILTER_REASONS
from pdf_reader.task_logging import task_log

# 稳定失败口径：这些终态把本次候选批次整体计为 failed=1；安全门
# （identity_rejected）与空结果/未启用等状态不计入 failed，通过 status 区分。
CANDIDATE_FAILED_STATUSES = frozenset({"failed", "source_failed", "store_failed"})

CANDIDATE_EVENTS = frozenset({"candidate_prepare", "candidate_commit"})
CANDIDATE_STATUSES = frozenset(
    {
        "ok",
        "no_candidates",
        "all_filtered",
        "empty",
        "disabled",
        "unsupported",
        "identity_rejected",
        "source_failed",
        "failed",
        "store_failed",
    }
)

COMPLIANCE_EVENTS = frozenset(
    {
        "compliance_pass",
        "compliance_fail",
        "compliance_unknown",
        "compliance_unavailable",
        "compliance_retry_scheduled",
        "compliance_failed_final",
    }
)
COMPLIANCE_STATUSES = frozenset({"pass", "fail", "unknown", "unavailable"})
COMPLIANCE_REASONS = frozenset(
    {
        "no_rows",
        "no_hits",
        "ok",
        "source_extraction_failed",
        "empty_source_text",
        "missing_path",
        "empty_text",
        "empty_target",
        "target_not_found",
        "extraction_failed",
        "page_count_mismatch",
    }
)


@dataclass(frozen=True)
class CandidateStoreCounts:
    """commit 时从 ``CandidateStore`` 读取的真实持久状态计数。"""

    pending: int
    accepted: int
    rejected: int


def _safe_token(value: object, allowed: frozenset[str]) -> str:
    """只允许受控集合内的稳定 token；未知/非字符串一律输出 ``unknown``。"""
    if isinstance(value, str) and value in allowed:
        return value
    return "unknown"


def _safe_count(value: object) -> int:
    """数量字段只接受非负 int；其余一律 0，避免任意对象 __str__ 进入日志。"""
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(0, value)


def candidate_failed_count(report: object) -> int:
    """唯一失败事实源：按受控终态集合计算本批 failed（0 或 1）。"""
    status = _safe_token(getattr(report, "status", ""), CANDIDATE_STATUSES)
    return 1 if status in CANDIDATE_FAILED_STATUSES else 0


def format_usage(usage: object | None) -> str:
    """把 token 用量折叠为安全文本；缺失/部分/非法一律 ``unavailable``。"""
    if usage is None or getattr(usage, "available", False) is not True:
        return "unavailable"

    def fmt(value: object) -> str:
        if value is None or isinstance(value, bool) or not isinstance(value, int):
            return "-"
        return str(value)

    return (
        f"prompt={fmt(getattr(usage, 'prompt_tokens', None))} "
        f"completion={fmt(getattr(usage, 'completion_tokens', None))} "
        f"total={fmt(getattr(usage, 'total_tokens', None))}"
    )


def _reason_pairs(value: object) -> tuple[tuple[str, int], ...]:
    """过滤 reason 只允许 ``candidate_filter.FILTER_REASONS``；未知名输出 unknown。"""
    if not isinstance(value, (tuple, list)):
        return ()
    pairs: list[tuple[str, int]] = []
    for item in value:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            continue
        name = _safe_token(item[0], FILTER_REASONS)
        count = item[1]
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            continue
        pairs.append((name, count))
    return tuple(pairs)


def format_candidate_summary(
    report: object,
    *,
    store_counts: CandidateStoreCounts | None = None,
    event: str = "candidate_prepare",
) -> str:
    """生成候选阶段稳定摘要；只含数量/状态/页码/耗时/usage/受控 token。"""
    status = _safe_token(getattr(report, "status", ""), CANDIDATE_STATUSES)
    event_name = _safe_token(event, CANDIDATE_EVENTS)
    pages_value = getattr(report, "pages", ()) or ()
    pages = tuple(int(page) for page in pages_value) if isinstance(pages_value, (tuple, list)) else ()
    reasons = _reason_pairs(getattr(report, "filtered_by_reason", ()))
    parts = [
        f"event={event_name}",
        f"status={status}",
        f"proposed={_safe_count(getattr(report, 'proposed', 0))}",
        f"kept={_safe_count(getattr(report, 'candidates', 0))}",
        f"filtered={_safe_count(getattr(report, 'filtered', 0))}",
        f"failed={candidate_failed_count(report)}",
    ]
    if pages:
        parts.append(f"pages={pages}")
    if reasons:
        parts.append("reasons=" + ";".join(f"{name}:{count}" for name, count in reasons))
    parts.append(f"elapsed_ms={_safe_count(getattr(report, 'elapsed_ms', 0))}")
    parts.append(f"usage={format_usage(getattr(report, 'usage', None))}")
    if event_name == "candidate_commit":
        if store_counts is None:
            parts.append("pending=unavailable accepted=unavailable rejected=unavailable")
        else:
            parts.append(
                f"pending={_safe_count(getattr(store_counts, 'pending', None))} "
                f"accepted={_safe_count(getattr(store_counts, 'accepted', None))} "
                f"rejected={_safe_count(getattr(store_counts, 'rejected', None))}"
            )
    return "candidate summary " + " ".join(parts)


def safe_task_log(
    logger: logging.Logger,
    level: int,
    message: str,
    *args: object,
    task: object | None = None,
    exc_info: bool | BaseException | None = None,
) -> None:
    """诊断日志发射：任何异常只降级为固定 fallback，绝不上抛。"""
    try:
        task_log(logger, level, message, *args, task=task, exc_info=exc_info)  # type: ignore[arg-type]
    except Exception:
        try:
            logger.log(level, "diagnostics emission failed; task continues")
        except Exception:
            pass


def log_candidate_summary(
    logger: logging.Logger,
    level: int,
    report: object,
    *,
    task_ctx: object | None = None,
    store_counts: CandidateStoreCounts | None = None,
    event: str = "candidate_prepare",
) -> None:
    """发射候选摘要；格式化或发射失败只降级，不阻止候选/正文流程。"""
    try:
        message = format_candidate_summary(report, store_counts=store_counts, event=event)
        safe_task_log(logger, level, message, task=task_ctx)
    except Exception:
        try:
            logger.log(logging.WARNING, "candidate diagnostics unavailable; task continues")
        except Exception:
            pass


def log_compliance(
    logger: logging.Logger,
    level: int,
    *,
    task_ctx: object | None = None,
    event: str | None = None,
    attempt: object = 0,
    status: object = "",
    sources: object = 0,
    failed: object = 0,
    reason: str = "",
) -> None:
    """发射合规诊断；event/status/reason 只允许受控集合，未知输出 unknown。"""
    try:
        # 先做类型/白名单判断，再基于已验证的 status 派生默认 event：
        # 任意对象绝不进入格式化（不调用 __str__/__format__/__bool__）。
        if isinstance(status, str) and status in COMPLIANCE_STATUSES:
            safe_status = status
            derived_event = f"compliance_{status}"
        else:
            safe_status = "unknown"
            derived_event = None
        if event is None:
            event_name = _safe_token(derived_event, COMPLIANCE_EVENTS) if derived_event is not None else "unknown"
        else:
            event_name = _safe_token(event, COMPLIANCE_EVENTS)
        if isinstance(reason, str):
            safe_reason = _safe_token(reason, COMPLIANCE_REASONS) if reason else ""
        else:
            safe_reason = "unknown"
        detail = (
            f"event={event_name} attempt={_safe_count(attempt)} "
            f"status={safe_status} sources={_safe_count(sources)} failed={_safe_count(failed)}"
        )
        if safe_reason:
            detail += f" reason={safe_reason}"
        safe_task_log(logger, level, "compliance " + detail, task=task_ctx)
    except Exception:
        try:
            logger.log(level, "compliance diagnostics unavailable; task continues")
        except Exception:
            pass


def log_glossary_active_terms(
    logger: logging.Logger,
    level: int,
    *,
    task_ctx: object | None = None,
    active: object = 0,
    sources: object = 0,
) -> None:
    """发射活跃权威词条数量摘要；只含数量，不列 source/target。"""
    try:
        safe_task_log(
            logger,
            level,
            "glossary event=glossary_active_terms active=%d sources=%d",
            _safe_count(active),
            _safe_count(sources),
            task=task_ctx,
        )
    except Exception:
        try:
            logger.log(level, "glossary diagnostics unavailable; task continues")
        except Exception:
            pass
