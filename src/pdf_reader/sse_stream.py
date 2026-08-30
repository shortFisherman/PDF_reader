import json
import logging
import shutil
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from pdf2zh_next import SettingsModel

from pdf_reader import cache_ops, debug_trace, pdf_extraction
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
from pdf_reader.translation_lifecycle import finish_translation, merge_glossary_only
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
    "finish": "\u7ffb\u8bd1\u5b8c\u6210",
}

logger = logging.getLogger("pdf_reader.translate")


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


def format_sse_event(evt: dict) -> str | None:
    evt_type = evt.get("type", "")

    if evt_type == "progress_start":
        return (
            "data: "
            + json.dumps(
                {
                    "type": "progress",
                    "progress": 0,
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
                    "progress": evt.get("overall_progress", 0),
                    "stage": evt.get("stage", ""),
                    "stage_current": evt.get("stage_current", 0),
                    "stage_total": evt.get("stage_total", 0),
                }
            )
            + "\n\n"
        )
    elif evt_type == "finish":
        return (
            "data: "
            + json.dumps(
                {
                    "type": "progress",
                    "progress": 95,
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


def generate(ctx: GenerateContext) -> Iterator[str]:
    with task_log_context(ctx.task_ctx):
        workspace: Path | None = None
        tmpdir: Path | None = None
        output_dir: Path | None = None
        stream = None
        outcome = "failed"
        try:
            workspace = cache_ops.create_temp_workspace(ctx.cache_dir, job_id=ctx.job_id)
            tmpdir = workspace / "input"
            output_dir = workspace / "output"
            ctx.settings.translation.output = str(output_dir)
            with debug_trace.debug_session(ctx.glossary_cache_path, ctx.page, ctx.job_id, debug=ctx.debug):
                task_log(logger, logging.INFO, "submit translate", task=ctx.task_ctx)

                translate_start = time.time()
                translate_result = None
                token_usage_finish = None

                single_page_pdf = ctx.extract_page(ctx.page, tmpdir, pdf_extraction.extract_single_page)

                stream = run_translation(
                    ctx.settings,
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

                    sse = format_sse_event(evt)
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

                elapsed = time.time() - translate_start
                task_log(logger, logging.INFO, "translate done (%.2fs)", elapsed, task=ctx.task_ctx)
                if token_usage_finish:
                    debug_trace.log_token_usage(token_usage_finish, ctx.job_id)

                finish_translation(
                    translate_result,
                    ctx.replace_page,
                    ctx.merge_glossary,
                    ctx.page + 1,
                    ctx.job_id,
                )

                outcome = "finished"
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

                translate_start = time.time()
                translate_result = None
                token_usage_finish = None

                multi_page_pdf = ctx.extract_pages(ctx.page_indices, tmpdir, pdf_extraction.extract_pages)

                yield format_batch_info(ctx.from_page, ctx.to_page, len(ctx.page_indices))

                stream = run_translation(
                    ctx.settings,
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

                    sse = format_sse_event(evt)
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

                elapsed = time.time() - translate_start
                task_log(logger, logging.INFO, "translate done (%.2fs)", elapsed, task=ctx.task_ctx)
                if token_usage_finish:
                    debug_trace.log_token_usage(token_usage_finish, ctx.job_id)

                translated_pdf = translate_result.mono_pdf_path
                if translated_pdf is None and translate_result.dual_pdf_path is not None:
                    translated_pdf = translate_result.dual_pdf_path
                if translated_pdf is not None:
                    ctx.replace_pages(str(translated_pdf))

                merge_glossary_only(translate_result, ctx.merge_glossary, ctx.from_page, ctx.job_id)

                outcome = "finished"
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
