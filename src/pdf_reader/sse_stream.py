import json
import logging
import shutil
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from pdf2zh_next import SettingsModel

from pdf_reader import cache_ops, debug_trace, pdf_extraction, strict_glossary, terminology_compliance
from pdf_reader.candidate_service import CandidateExtractionService
from pdf_reader.strict_glossary import StrictTranslationContext
from pdf_reader.task_logging import (
    STATUS_CANCELLING,
    STATUS_CLEANED,
    STATUS_CLEANUP_DEFERRED,
    STATUS_CLIENT_DISCONNECTED,
    STATUS_DISCARDED,
    STATUS_FAILED,
    TaskContext,
    task_log,
    task_log_context,
    with_status,
)
from pdf_reader.terminology_compliance import ComplianceStatus
from pdf_reader.translation_lifecycle import TranslateResult, finish_translation, merge_glossary_only
from pdf_reader.translation_orchestrator import (
    WORKER_JOIN_TIMEOUT,
    TranslationError,
    TranslationStream,
    run_translation,
)

STAGE_LABELS = {
    "layout_analysis": "\u6b63\u5728\u5206\u6790\u7248\u9762\u2026",
    "translating": "\u6b63\u5728\u7ffb\u8bd1\u2026",
    "generating_pdf": "\u6b63\u5728\u751f\u6210\u8bd1\u6587\u2026",
    "generating_pdf_bilingual": "\u6b63\u5728\u751f\u6210\u8bd1\u6587\u2026",
    "glossary_retry": "\u672f\u8bed\u5408\u89c4\u68c0\u67e5\u672a\u901a\u8fc7\uff0c\u6b63\u5728\u91cd\u8bd5\u2026",
    "finish": "\u7ffb\u8bd1\u5b8c\u6210",
}

logger = logging.getLogger("pdf_reader.translate")

# P0-05 提交门：首次不合规最多整页/整批有界重试 1 次；无活跃权威词条时降为 1。
MAX_COMPLIANCE_ATTEMPTS = 2
GLOSSARY_COMPLIANCE_FAILED_CODE = "glossary_compliance_failed"
GLOSSARY_VERIFICATION_UNAVAILABLE_CODE = "glossary_verification_unavailable"
GLOSSARY_RETRY_STAGE = "glossary_retry"
GLOSSARY_RETRY_PROGRESS = 95
# 有活跃术语时按 attempt 分配明确进度窗口：attempt1 0..95（finish=95）、
# attempt2 95..99（finish=99）、最终提交 100；无活跃术语保持旧事件字节。
ATTEMPT_1_MAX_PROGRESS = 95
ATTEMPT_2_MIN_PROGRESS = 95
ATTEMPT_2_MAX_PROGRESS = 99


def _safe_rmtree(path: Path | None) -> bool:
    """删除任务工作区（根目录，含 input/output）并返回可验证结果；目标原本不存在也算成功。"""
    if path is None or not path.exists():
        return True
    try:
        shutil.rmtree(path)
    except Exception:
        logger.warning("failed to remove temp workspace %s", path, exc_info=True)
        return False
    if path.exists():
        logger.warning("temp workspace %s still exists after removal", path)
        return False
    return True


@dataclass
class GenerateContext:
    settings: SettingsModel
    job_id: str
    finish_job: Callable[[str], bool]
    fail_job: Callable[[str], bool]
    cancel_job: Callable[[str], bool]
    replace_page: Callable[[str], None]
    merge_glossary: Callable[[str | Path | None], None]
    glossary_cache_path: Path | None
    page: int  # 0-based page index（日志/用户显示时统一转 1-based）
    glossary_paths: list[str] | None
    cache_dir: Path
    extract_page: Callable[[int, Path, Callable], Path]
    task_ctx: TaskContext | None = None
    provider: str = ""
    model: str = ""
    lang_in: str = "en"
    lang_out: str = "zh"
    debug: bool = False
    register_stream: Callable[[str, object], None] | None = None
    unregister_stream: Callable[[str], None] | None = None
    strict_context: StrictTranslationContext | None = None
    candidate_service: CandidateExtractionService | None = None


@dataclass
class GenerateBatchContext:
    settings: SettingsModel
    job_id: str
    finish_job: Callable[[str], bool]
    fail_job: Callable[[str], bool]
    cancel_job: Callable[[str], bool]
    from_page: int  # 1-based 起始页
    to_page: int  # 1-based 结束页
    page_indices: list[int]  # 0-based 页索引
    replace_pages: Callable[[str], None]
    merge_glossary: Callable[[str | Path | None], None]
    glossary_cache_path: Path | None
    glossary_paths: list[str] | None
    cache_dir: Path
    extract_pages: Callable[[list[int], Path, Callable], Path]
    task_ctx: TaskContext | None = None
    provider: str = ""
    model: str = ""
    lang_in: str = "en"
    lang_out: str = "zh"
    debug: bool = False
    register_stream: Callable[[str, object], None] | None = None
    unregister_stream: Callable[[str], None] | None = None
    strict_context: StrictTranslationContext | None = None
    candidate_service: CandidateExtractionService | None = None


def format_batch_info(from_page: int, to_page: int, total: int) -> str:
    return (
        "data: "
        + json.dumps(
            {
                "type": "batch_info",
                "from": from_page,
                "to": to_page,
                "total": total,
            }
        )
        + "\n\n"
    )


def _clamp_progress(
    value: object,
    min_progress: int | None = None,
    max_progress: int | None = None,
) -> object:
    """把 progress 钳制到 [min_progress, max_progress]；两者都缺省时原样返回。"""
    if min_progress is None and max_progress is None:
        return value
    if isinstance(value, (int, float)):
        numeric = int(value)
    elif isinstance(value, str):
        try:
            numeric = int(float(value))
        except ValueError:
            numeric = 0
    else:
        numeric = 0
    if min_progress is not None:
        numeric = max(numeric, min_progress)
    if max_progress is not None:
        numeric = min(numeric, max_progress)
    return numeric


def format_sse_event(
    evt: dict,
    min_progress: int | None = None,
    max_progress: int | None = None,
) -> str | None:
    evt_type = evt.get("type", "")

    if evt_type == "progress_start":
        return (
            "data: "
            + json.dumps(
                {
                    "type": "progress",
                    "progress": _clamp_progress(0, min_progress, max_progress),
                    "stage": evt.get("stage", ""),
                    "stage_current": evt.get("stage_current", 0),
                    "stage_total": evt.get("stage_total", 0),
                }
            )
            + "\n\n"
        )
    elif evt_type == "progress_update":
        return (
            "data: "
            + json.dumps(
                {
                    "type": "progress",
                    "progress": _clamp_progress(
                        evt.get("overall_progress", 0),
                        min_progress,
                        max_progress,
                    ),
                    "stage": evt.get("stage", ""),
                    "stage_current": evt.get("stage_current", 0),
                    "stage_total": evt.get("stage_total", 0),
                }
            )
            + "\n\n"
        )
    elif evt_type == "finish":
        # 无窗口时精确保持旧字节 95；有窗口时 finish 用窗口上限（attempt1=95、
        # attempt2=99），避免已钳制的 overall_progress 之后 finish 倒退。
        if min_progress is None and max_progress is None:
            finish_progress = 95
        else:
            finish_progress = max_progress if max_progress is not None else (min_progress or 95)
        return (
            "data: "
            + json.dumps(
                {
                    "type": "progress",
                    "progress": finish_progress,
                    "stage": evt.get("stage", "generating_pdf"),
                    "stage_current": 0,
                    "stage_total": 0,
                }
            )
            + "\n\n"
        )
    elif evt_type == "error":
        return format_sse_error("translation_error", "上游翻译失败")
    else:
        return None


def format_sse_error(code: str, message: str) -> str:
    return "data: " + json.dumps({"type": "error", "code": code, "error": message}) + "\n\n"


def _release_job(ctx: GenerateContext | GenerateBatchContext, outcome: str) -> None:
    try:
        if outcome == "finished":
            ctx.finish_job(ctx.job_id)
        elif outcome == "cancelled":
            ctx.cancel_job(ctx.job_id)
        else:
            ctx.fail_job(ctx.job_id)
    except Exception:
        task_log(
            logger,
            logging.ERROR,
            "failed to release translation coordinator",
            task=ctx.task_ctx,
            exc_info=True,
        )


def _run_candidate_extraction(
    ctx: GenerateContext | GenerateBatchContext,
    pdf_path: Path,
    page_indices: list[int] | tuple[int, ...],
) -> None:
    """正文提交成功后的旁路候选提取；任何失败都只降级日志，不影响 finish。"""
    service = ctx.candidate_service
    if service is None:
        return
    try:
        service.run_for_pdf(pdf_path, page_indices, ctx.glossary_cache_path, task_ctx=ctx.task_ctx)
    except Exception:
        task_log(
            logger,
            logging.WARNING,
            "candidate extraction degraded; translation remains finished",
            task=ctx.task_ctx,
        )


def _shutdown_worker(stream: TranslationStream | None, task_ctx: TaskContext | None) -> bool:
    """Request cooperative cancellation and wait for the real worker thread.

    Returns True only when the worker is confirmed finished, so the job's temp
    directories are safe to remove.  A worker that ignores cancellation (or is
    still running after the join timeout) keeps its directories for recovery.
    """
    if not isinstance(stream, TranslationStream):
        return True
    if stream.is_alive:
        task_log(
            logger,
            logging.INFO,
            "SSE stream closed before worker exit; requesting cancellation",
            task=with_status(task_ctx, STATUS_CANCELLING),
        )
        stream.cancel()
    stream.join(timeout=WORKER_JOIN_TIMEOUT)
    if stream.is_alive:
        task_log(
            logger,
            logging.WARNING,
            "worker still running after %.0fs join timeout; temp dirs kept for recovery",
            WORKER_JOIN_TIMEOUT,
            task=with_status(task_ctx, STATUS_CLEANUP_DEFERRED),
        )
        return False
    return True


def _select_translated_pdf(translate_result: TranslateResult | None) -> Path | None:
    """从 translate_result 选择 mono（缺失时 dual）作为待验证/待提交译文路径。"""
    if translate_result is None:
        return None
    path = translate_result.mono_pdf_path
    if path is None:
        path = translate_result.dual_pdf_path
    return Path(str(path)) if path is not None else None


def _build_retry_settings(
    settings: SettingsModel,
    retry_output_dir: Path,
    failed_terms: tuple[tuple[str, str], ...],
) -> SettingsModel:
    """构造重试 Settings 独立副本：独立输出目录，并在原 Prompt 后追加纠错块。"""
    retry_settings = settings.model_copy(deep=True)
    retry_settings.translation.output = str(retry_output_dir)
    retry_settings.translation.custom_system_prompt = terminology_compliance.compose_retry_correction_prompt(
        retry_settings.translation.custom_system_prompt,
        failed_terms,
    )
    return retry_settings


def _format_sse_glossary_retry(next_attempt: int, max_attempts: int) -> str:
    return (
        "data: "
        + json.dumps(
            {
                "type": "progress",
                "progress": GLOSSARY_RETRY_PROGRESS,
                "stage": GLOSSARY_RETRY_STAGE,
                "stage_current": next_attempt,
                "stage_total": max_attempts,
            }
        )
        + "\n\n"
    )


def _log_compliance(
    task_ctx: TaskContext | None,
    level: int,
    status: str,
    *,
    attempt: int,
    sources: int,
    failed: int = 0,
    reason: str = "",
) -> None:
    """只记录 job/page/数量/状态等必要诊断，不记录正文、target、路径或异常原文。"""
    detail = f"attempt={attempt} status={status} sources={sources} failed={failed}"
    if reason:
        detail += f" reason={reason}"
    task_log(logger, level, "compliance %s", detail, task=task_ctx)


def generate(ctx: GenerateContext) -> Iterator[str]:
    with task_log_context(ctx.task_ctx):
        workspace: Path | None = None
        tmpdir: Path | None = None
        output_dir: Path | None = None
        stream = None
        outcome = "failed"
        try:
            if ctx.strict_context is not None:
                strict_glossary.validate_strict_context_identity(
                    ctx.strict_context,
                    ctx.task_ctx,
                    ctx.glossary_cache_path,
                )
            workspace = cache_ops.create_temp_workspace(ctx.cache_dir, job_id=ctx.job_id)
            tmpdir = workspace / "input"
            output_dir = workspace / "output"
            ctx.settings.translation.output = str(output_dir)
            with debug_trace.debug_session(ctx.glossary_cache_path, ctx.page, ctx.job_id, debug=ctx.debug):
                task_log(logger, logging.INFO, "submit translate", task=ctx.task_ctx)

                single_page_pdf = ctx.extract_page(ctx.page, tmpdir, pdf_extraction.extract_single_page)
                active_terms: tuple[tuple[str, str], ...] = ()
                if ctx.strict_context is not None:
                    resolution = strict_glossary.resolve_active_terms_from_pdf(
                        single_page_pdf,
                        ctx.strict_context.effective_rows,
                    )
                    if not resolution.available:
                        _log_compliance(
                            ctx.task_ctx,
                            logging.WARNING,
                            "unavailable",
                            attempt=0,
                            sources=len(ctx.strict_context.effective_rows),
                            reason=resolution.reason,
                        )
                        yield format_sse_error(
                            GLOSSARY_VERIFICATION_UNAVAILABLE_CODE,
                            "术语合规验证不可用",
                        )
                        return
                    active_terms = strict_glossary.apply_resolved_active_terms(
                        ctx.settings,
                        resolution.active_terms,
                    )

                # P0-05 提交门：无活跃词条时不验证、不重试；有活跃词条时最多整页
                # 有界重试 1 次（同一 job/document identity，不启动第二个协调任务）。
                max_attempts = MAX_COMPLIANCE_ATTEMPTS if active_terms else 1
                failed_terms: tuple[tuple[str, str], ...] = ()

                for attempt in range(1, max_attempts + 1):
                    translate_start = time.time()
                    translate_result = None
                    token_usage_finish = None
                    attempt_settings = ctx.settings
                    if attempt > 1:
                        retry_output_dir = workspace / "attempt-2" / "output"
                        retry_output_dir.mkdir(parents=True, exist_ok=True)
                        attempt_settings = _build_retry_settings(
                            ctx.settings,
                            retry_output_dir,
                            failed_terms,
                        )
                    if not active_terms:
                        min_progress = None
                        max_progress = None
                    elif attempt == 1:
                        min_progress = 0
                        max_progress = ATTEMPT_1_MAX_PROGRESS
                    else:
                        min_progress = ATTEMPT_2_MIN_PROGRESS
                        max_progress = ATTEMPT_2_MAX_PROGRESS

                    stream = run_translation(
                        attempt_settings,
                        str(single_page_pdf),
                        flow_label=f"page={ctx.page + 1}",
                        task_ctx=ctx.task_ctx,
                    )
                    if ctx.register_stream is not None:
                        ctx.register_stream(ctx.job_id, stream)
                    for evt in stream:
                        if not isinstance(evt, dict):
                            yield ""
                            continue
                        if evt.get("type") == "finish":
                            translate_result = evt.get("translate_result")
                            token_usage_finish = evt.get("token_usage", {})

                        sse = format_sse_event(
                            evt,
                            min_progress=min_progress,
                            max_progress=max_progress,
                        )
                        if sse is not None:
                            yield sse

                        if evt.get("type") == "error":
                            task_log(
                                logger,
                                logging.WARNING,
                                "upstream translation error event: %s",
                                evt.get("error"),
                                task=with_status(ctx.task_ctx, STATUS_FAILED),
                            )
                            return

                    if translate_result is None:
                        task_log(
                            logger,
                            logging.WARNING,
                            "no translation result",
                            task=with_status(ctx.task_ctx, STATUS_FAILED),
                        )
                        yield format_sse_error("translation_error", "未获取到翻译结果")
                        return
                    if ctx.unregister_stream is not None:
                        ctx.unregister_stream(ctx.job_id)

                    elapsed = time.time() - translate_start
                    task_log(logger, logging.INFO, "translate done (%.2fs)", elapsed, task=ctx.task_ctx)
                    if token_usage_finish:
                        debug_trace.log_token_usage(token_usage_finish, ctx.job_id)

                    if not active_terms:
                        break

                    translated_pdf = _select_translated_pdf(translate_result)
                    if translated_pdf is None:
                        _log_compliance(
                            ctx.task_ctx,
                            logging.WARNING,
                            "unavailable",
                            attempt=attempt,
                            sources=len(active_terms),
                            reason="missing_path",
                        )
                        yield format_sse_error(
                            GLOSSARY_VERIFICATION_UNAVAILABLE_CODE,
                            "术语合规验证不可用",
                        )
                        return
                    verdict = terminology_compliance.verify_translated_pdf(
                        translated_pdf,
                        active_terms,
                        expected_pages=1,
                    )
                    _log_compliance(
                        ctx.task_ctx,
                        logging.INFO,
                        verdict.status.value,
                        attempt=attempt,
                        sources=len(active_terms),
                        failed=len(verdict.failed_terms),
                        reason=verdict.reason,
                    )
                    if verdict.status is ComplianceStatus.PASS:
                        break
                    if verdict.status is ComplianceStatus.UNKNOWN:
                        yield format_sse_error(
                            GLOSSARY_VERIFICATION_UNAVAILABLE_CODE,
                            "术语合规验证不可用",
                        )
                        return
                    failed_terms = verdict.failed_terms
                    if attempt < max_attempts:
                        task_log(
                            logger,
                            logging.INFO,
                            "compliance retry scheduled: attempt=%d failed=%d",
                            attempt,
                            len(failed_terms),
                            task=ctx.task_ctx,
                        )
                        yield _format_sse_glossary_retry(attempt + 1, max_attempts)
                        continue
                    task_log(
                        logger,
                        logging.WARNING,
                        "compliance failed after attempts: sources=%d failed=%d",
                        len(active_terms),
                        len(failed_terms),
                        task=with_status(ctx.task_ctx, STATUS_FAILED),
                    )
                    yield format_sse_error(GLOSSARY_COMPLIANCE_FAILED_CODE, "术语合规验证未通过")
                    return

                # 只有验证通过（或无活跃词条）才提交译文并合并词表；旧 right.pdf
                # 在验证通过前完全不动，失败路径绝不 merge 自动词表。
                assert translate_result is not None
                finish_translation(
                    translate_result,
                    ctx.replace_page,
                    ctx.merge_glossary,
                    ctx.page + 1,
                    ctx.job_id,
                )
                outcome = "finished"
                # 正文已提交：先冻结 finished 终态，再跑旁路候选。候选提取的
                # 任何失败（包括意外异常）都不会把已提交任务改判为 failed。
                _run_candidate_extraction(ctx, single_page_pdf, [ctx.page])
                yield (
                    "data: "
                    + json.dumps(
                        {
                            "type": "progress",
                            "progress": 100,
                            "stage": "finish",
                            "stage_current": 0,
                            "stage_total": 0,
                        }
                    )
                    + "\n\n"
                )
                yield f"data: {json.dumps({'type': 'finish', 'progress': 100})}\n\n"

        except GeneratorExit:
            task_log(
                logger,
                logging.INFO,
                "client disconnected",
                task=with_status(ctx.task_ctx, STATUS_CLIENT_DISCONNECTED),
            )
            outcome = "cancelled"
            raise
        except TranslationError as e:
            task_log(
                logger,
                logging.WARNING,
                "translation error: %s",
                e,
                task=with_status(ctx.task_ctx, STATUS_FAILED),
            )
            yield format_sse_error("translation_error", "上游翻译失败")
        except Exception:
            task_log(
                logger,
                logging.ERROR,
                "translate failed: provider=%s model=%s lang=%s->%s tmpdir=%s",
                ctx.provider,
                ctx.model,
                ctx.lang_in,
                ctx.lang_out,
                str(tmpdir),
                task=with_status(ctx.task_ctx, STATUS_FAILED),
                exc_info=True,
            )
            yield format_sse_error("internal_error", "翻译失败，请查看服务端日志")
        finally:
            worker_finished = _shutdown_worker(stream, ctx.task_ctx)
            if ctx.unregister_stream is not None:
                ctx.unregister_stream(ctx.job_id)
            cleanup_ok = worker_finished
            if worker_finished:
                if getattr(stream, "late_result_dropped", False):
                    task_log(
                        logger,
                        logging.WARNING,
                        "late worker result discarded",
                        task=with_status(ctx.task_ctx, STATUS_DISCARDED),
                    )
                if workspace is not None:
                    cleanup_ok = _safe_rmtree(workspace) and cleanup_ok
            _release_job(ctx, outcome)
            if cleanup_ok:
                task_log(
                    logger,
                    logging.INFO,
                    "temporary directories cleaned",
                    task=with_status(ctx.task_ctx, STATUS_CLEANED),
                )
            else:
                task_log(
                    logger,
                    logging.WARNING,
                    "cleanup deferred; temp dirs kept for recovery",
                    task=with_status(ctx.task_ctx, STATUS_CLEANUP_DEFERRED),
                )


def generate_batch(ctx: GenerateBatchContext) -> Iterator[str]:
    with task_log_context(ctx.task_ctx):
        workspace: Path | None = None
        tmpdir: Path | None = None
        output_dir: Path | None = None
        stream = None
        outcome = "failed"
        try:
            if ctx.strict_context is not None:
                strict_glossary.validate_strict_context_identity(
                    ctx.strict_context,
                    ctx.task_ctx,
                    ctx.glossary_cache_path,
                )
            workspace = cache_ops.create_temp_workspace(ctx.cache_dir, job_id=ctx.job_id)
            tmpdir = workspace / "input"
            output_dir = workspace / "output"
            ctx.settings.translation.output = str(output_dir)
            with debug_trace.debug_session(
                ctx.glossary_cache_path,
                ctx.from_page - 1,
                ctx.job_id,
                debug=ctx.debug,
            ):
                task_log(logger, logging.INFO, "submit translate", task=ctx.task_ctx)

                multi_page_pdf = ctx.extract_pages(ctx.page_indices, tmpdir, pdf_extraction.extract_pages)
                active_terms: tuple[tuple[str, str], ...] = ()
                if ctx.strict_context is not None:
                    resolution = strict_glossary.resolve_active_terms_from_pdf(
                        multi_page_pdf,
                        ctx.strict_context.effective_rows,
                    )
                    if not resolution.available:
                        _log_compliance(
                            ctx.task_ctx,
                            logging.WARNING,
                            "unavailable",
                            attempt=0,
                            sources=len(ctx.strict_context.effective_rows),
                            reason=resolution.reason,
                        )
                        yield format_sse_error(
                            GLOSSARY_VERIFICATION_UNAVAILABLE_CODE,
                            "术语合规验证不可用",
                        )
                        return
                    active_terms = strict_glossary.apply_resolved_active_terms(
                        ctx.settings,
                        resolution.active_terms,
                    )

                yield format_batch_info(ctx.from_page, ctx.to_page, len(ctx.page_indices))

                # P0-05 提交门：batch 首版采用整批原子验证与整批有界重试（最多 1 次），
                # 只在整批通过后一次性 replace_pages；失败不 merge 任何自动词表。
                max_attempts = MAX_COMPLIANCE_ATTEMPTS if active_terms else 1
                failed_terms: tuple[tuple[str, str], ...] = ()

                for attempt in range(1, max_attempts + 1):
                    translate_start = time.time()
                    translate_result = None
                    token_usage_finish = None
                    attempt_settings = ctx.settings
                    if attempt > 1:
                        retry_output_dir = workspace / "attempt-2" / "output"
                        retry_output_dir.mkdir(parents=True, exist_ok=True)
                        attempt_settings = _build_retry_settings(
                            ctx.settings,
                            retry_output_dir,
                            failed_terms,
                        )
                    if not active_terms:
                        min_progress = None
                        max_progress = None
                    elif attempt == 1:
                        min_progress = 0
                        max_progress = ATTEMPT_1_MAX_PROGRESS
                    else:
                        min_progress = ATTEMPT_2_MIN_PROGRESS
                        max_progress = ATTEMPT_2_MAX_PROGRESS

                    stream = run_translation(
                        attempt_settings,
                        str(multi_page_pdf),
                        flow_label=f"pages={ctx.from_page}-{ctx.to_page}",
                        task_ctx=ctx.task_ctx,
                    )
                    if ctx.register_stream is not None:
                        ctx.register_stream(ctx.job_id, stream)
                    for evt in stream:
                        if not isinstance(evt, dict):
                            yield ""
                            continue
                        if evt.get("type") == "finish":
                            translate_result = evt.get("translate_result")
                            token_usage_finish = evt.get("token_usage", {})

                        sse = format_sse_event(
                            evt,
                            min_progress=min_progress,
                            max_progress=max_progress,
                        )
                        if sse is not None:
                            yield sse

                        if evt.get("type") == "error":
                            task_log(
                                logger,
                                logging.WARNING,
                                "upstream translation error event: %s",
                                evt.get("error"),
                                task=with_status(ctx.task_ctx, STATUS_FAILED),
                            )
                            return

                    if translate_result is None:
                        task_log(
                            logger,
                            logging.WARNING,
                            "no translation result",
                            task=with_status(ctx.task_ctx, STATUS_FAILED),
                        )
                        yield format_sse_error("translation_error", "未获取到翻译结果")
                        return
                    if ctx.unregister_stream is not None:
                        ctx.unregister_stream(ctx.job_id)

                    elapsed = time.time() - translate_start
                    task_log(logger, logging.INFO, "translate done (%.2fs)", elapsed, task=ctx.task_ctx)
                    if token_usage_finish:
                        debug_trace.log_token_usage(token_usage_finish, ctx.job_id)

                    if not active_terms:
                        break

                    translated_pdf = _select_translated_pdf(translate_result)
                    if translated_pdf is None:
                        _log_compliance(
                            ctx.task_ctx,
                            logging.WARNING,
                            "unavailable",
                            attempt=attempt,
                            sources=len(active_terms),
                            reason="missing_path",
                        )
                        yield format_sse_error(
                            GLOSSARY_VERIFICATION_UNAVAILABLE_CODE,
                            "术语合规验证不可用",
                        )
                        return
                    verdict = terminology_compliance.verify_translated_pdf(
                        translated_pdf,
                        active_terms,
                        expected_pages=len(ctx.page_indices),
                    )
                    _log_compliance(
                        ctx.task_ctx,
                        logging.INFO,
                        verdict.status.value,
                        attempt=attempt,
                        sources=len(active_terms),
                        failed=len(verdict.failed_terms),
                        reason=verdict.reason,
                    )
                    if verdict.status is ComplianceStatus.PASS:
                        break
                    if verdict.status is ComplianceStatus.UNKNOWN:
                        yield format_sse_error(
                            GLOSSARY_VERIFICATION_UNAVAILABLE_CODE,
                            "术语合规验证不可用",
                        )
                        return
                    failed_terms = verdict.failed_terms
                    if attempt < max_attempts:
                        task_log(
                            logger,
                            logging.INFO,
                            "compliance retry scheduled: attempt=%d failed=%d",
                            attempt,
                            len(failed_terms),
                            task=ctx.task_ctx,
                        )
                        yield _format_sse_glossary_retry(attempt + 1, max_attempts)
                        continue
                    task_log(
                        logger,
                        logging.WARNING,
                        "compliance failed after attempts: sources=%d failed=%d",
                        len(active_terms),
                        len(failed_terms),
                        task=with_status(ctx.task_ctx, STATUS_FAILED),
                    )
                    yield format_sse_error(GLOSSARY_COMPLIANCE_FAILED_CODE, "术语合规验证未通过")
                    return

                # 整批验证通过（或无活跃词条）后才一次性提交并合并词表。
                assert translate_result is not None
                translated_pdf = _select_translated_pdf(translate_result)
                if translated_pdf is not None:
                    ctx.replace_pages(str(translated_pdf))

                merge_glossary_only(translate_result, ctx.merge_glossary, ctx.from_page, ctx.job_id)
                outcome = "finished"
                # 同单页：提交成功即冻结 finished，候选失败只降级，不改终态。
                _run_candidate_extraction(ctx, multi_page_pdf, ctx.page_indices)
                yield (
                    "data: "
                    + json.dumps(
                        {
                            "type": "progress",
                            "progress": 100,
                            "stage": "finish",
                            "stage_current": 0,
                            "stage_total": 0,
                        }
                    )
                    + "\n\n"
                )
                yield f"data: {json.dumps({'type': 'finish', 'progress': 100})}\n\n"

        except GeneratorExit:
            task_log(
                logger,
                logging.INFO,
                "client disconnected",
                task=with_status(ctx.task_ctx, STATUS_CLIENT_DISCONNECTED),
            )
            outcome = "cancelled"
            raise
        except TranslationError as e:
            task_log(
                logger,
                logging.WARNING,
                "translation error: %s",
                e,
                task=with_status(ctx.task_ctx, STATUS_FAILED),
            )
            yield format_sse_error("translation_error", "上游翻译失败")
        except Exception:
            task_log(
                logger,
                logging.ERROR,
                "translate failed: provider=%s model=%s lang=%s->%s tmpdir=%s",
                ctx.provider,
                ctx.model,
                ctx.lang_in,
                ctx.lang_out,
                str(tmpdir),
                task=with_status(ctx.task_ctx, STATUS_FAILED),
                exc_info=True,
            )
            yield format_sse_error("internal_error", "翻译失败，请查看服务端日志")
        finally:
            worker_finished = _shutdown_worker(stream, ctx.task_ctx)
            if ctx.unregister_stream is not None:
                ctx.unregister_stream(ctx.job_id)
            cleanup_ok = worker_finished
            if worker_finished:
                if getattr(stream, "late_result_dropped", False):
                    task_log(
                        logger,
                        logging.WARNING,
                        "late worker result discarded",
                        task=with_status(ctx.task_ctx, STATUS_DISCARDED),
                    )
                if workspace is not None:
                    cleanup_ok = _safe_rmtree(workspace) and cleanup_ok
            _release_job(ctx, outcome)
            if cleanup_ok:
                task_log(
                    logger,
                    logging.INFO,
                    "temporary directories cleaned",
                    task=with_status(ctx.task_ctx, STATUS_CLEANED),
                )
            else:
                task_log(
                    logger,
                    logging.WARNING,
                    "cleanup deferred; temp dirs kept for recovery",
                    task=with_status(ctx.task_ctx, STATUS_CLEANUP_DEFERRED),
                )
