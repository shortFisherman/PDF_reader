import json
import logging
import shutil
import tempfile
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from pdf2zh_next import SettingsModel

import config
import debug_trace
import pdf_extraction
from translation_lifecycle import finish_translation, merge_glossary_only
from translation_orchestrator import WORKER_JOIN_TIMEOUT, TranslationError, TranslationStream, run_translation

STAGE_LABELS = {
    "layout_analysis": "\u6b63\u5728\u5206\u6790\u7248\u9762\u2026",
    "translating": "\u6b63\u5728\u7ffb\u8bd1\u2026",
    "generating_pdf": "\u6b63\u5728\u751f\u6210\u8bd1\u6587\u2026",
    "generating_pdf_bilingual": "\u6b63\u5728\u751f\u6210\u8bd1\u6587\u2026",
    "finish": "\u7ffb\u8bd1\u5b8c\u6210",
}

logger = logging.getLogger("pdf_reader.translate")


def _safe_rmtree(path: Path) -> None:
    try:
        shutil.rmtree(path, ignore_errors=True)
    except Exception:
        logger.debug("failed to clean up temp dir %s", path)


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
    page: int
    glossary_paths: list[str] | None
    cache_dir: Path
    extract_page: Callable[[int, Path, Callable], Path]


@dataclass
class GenerateBatchContext:
    settings: SettingsModel
    job_id: str
    finish_job: Callable[[str], bool]
    fail_job: Callable[[str], bool]
    cancel_job: Callable[[str], bool]
    from_page: int
    to_page: int
    page_indices: list[int]
    replace_pages: Callable[[str], None]
    merge_glossary: Callable[[str | Path | None], None]
    glossary_cache_path: Path | None
    glossary_paths: list[str] | None
    cache_dir: Path
    extract_pages: Callable[[list[int], Path, Callable], Path]


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
        logger.error("[job=%s] failed to release translation coordinator", ctx.job_id, exc_info=True)


def _shutdown_worker(stream: TranslationStream | None, job_id: str) -> bool:
    """Request cooperative cancellation and wait for the real worker thread.

    Returns True only when the worker is confirmed finished, so the job's temp
    directories are safe to remove.  A worker that ignores cancellation (or is
    still running after the join timeout) keeps its directories for recovery.
    """
    if not isinstance(stream, TranslationStream):
        return True
    if stream.is_alive:
        logger.info("[job=%s] SSE stream closed before worker exit; requesting cancellation", job_id)
        stream.cancel()
    stream.join(timeout=WORKER_JOIN_TIMEOUT)
    if stream.is_alive:
        logger.warning(
            "[job=%s] worker still running after %.0fs join timeout; temp dirs kept for recovery",
            job_id,
            WORKER_JOIN_TIMEOUT,
        )
        return False
    return True


def generate(ctx: GenerateContext) -> Iterator[str]:
    tmpdir: Path | None = None
    output_dir: Path | None = None
    stream = None
    outcome = "failed"
    try:
        tmpdir = Path(tempfile.mkdtemp())
        output_dir = Path(tempfile.mkdtemp(dir=str(ctx.cache_dir)))
        ctx.settings.translation.output = str(output_dir)
        with debug_trace.debug_session(ctx.glossary_cache_path, ctx.page, ctx.job_id):
            logger.info("[job=%s][page=%d] submit translate", ctx.job_id, ctx.page)

            translate_start = time.time()
            translate_result = None
            token_usage_finish = None

            single_page_pdf = ctx.extract_page(ctx.page, tmpdir, pdf_extraction.extract_single_page)

            stream = run_translation(
                ctx.settings,
                str(single_page_pdf),
                flow_label=f"job={ctx.job_id}][page={ctx.page}",
            )
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
                    logger.warning(
                        "[job=%s][page=%d] upstream translation error event: %s",
                        ctx.job_id,
                        ctx.page,
                        evt.get("error"),
                    )
                    return

            if translate_result is None:
                logger.warning("[job=%s][page=%d] no translation result", ctx.job_id, ctx.page)
                yield format_sse_error("translation_error", "未获取到翻译结果")
                return

            elapsed = time.time() - translate_start
            logger.info("[job=%s][page=%d] translate done (%.2fs)", ctx.job_id, ctx.page, elapsed)
            if token_usage_finish:
                debug_trace.log_token_usage(token_usage_finish, ctx.job_id)

            finish_translation(
                translate_result,
                ctx.replace_page,
                ctx.merge_glossary,
                ctx.page,
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
        outcome = "cancelled"
        raise
    except TranslationError as e:
        logger.warning("[job=%s][page=%d] translation error: %s", ctx.job_id, ctx.page, e)
        yield format_sse_error("translation_error", "上游翻译失败")
    except Exception:
        logger.error(
            "[job=%s][page=%d] translate failed: provider=%s model=%s lang=%s->%s tmpdir=%s",
            ctx.job_id,
            ctx.page,
            config.MODEL_PROVIDER,
            config.MODEL,
            config.TRANSLATION_LANG_IN,
            config.TRANSLATION_LANG_OUT,
            str(tmpdir),
            exc_info=True,
        )
        yield format_sse_error("internal_error", "翻译失败，请查看服务端日志")
    finally:
        worker_finished = _shutdown_worker(stream, ctx.job_id)
        if worker_finished:
            if tmpdir is not None:
                _safe_rmtree(tmpdir)
            if output_dir is not None:
                _safe_rmtree(output_dir)
        _release_job(ctx, outcome)


def generate_batch(ctx: GenerateBatchContext) -> Iterator[str]:
    tmpdir: Path | None = None
    output_dir: Path | None = None
    stream = None
    outcome = "failed"
    try:
        tmpdir = Path(tempfile.mkdtemp())
        output_dir = Path(tempfile.mkdtemp(dir=str(ctx.cache_dir)))
        ctx.settings.translation.output = str(output_dir)
        with debug_trace.debug_session(ctx.glossary_cache_path, ctx.from_page, ctx.job_id):
            logger.info("[job=%s][batch=%d-%d] submit translate", ctx.job_id, ctx.from_page, ctx.to_page)

            translate_start = time.time()
            translate_result = None
            token_usage_finish = None

            multi_page_pdf = ctx.extract_pages(ctx.page_indices, tmpdir, pdf_extraction.extract_pages)

            yield format_batch_info(ctx.from_page, ctx.to_page, len(ctx.page_indices))

            stream = run_translation(
                ctx.settings,
                str(multi_page_pdf),
                flow_label=f"job={ctx.job_id}][batch={ctx.from_page}-{ctx.to_page}",
            )
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
                    logger.warning(
                        "[job=%s][batch=%d-%d] upstream translation error event: %s",
                        ctx.job_id,
                        ctx.from_page,
                        ctx.to_page,
                        evt.get("error"),
                    )
                    return

            if translate_result is None:
                logger.warning(
                    "[job=%s][batch=%d-%d] no translation result",
                    ctx.job_id,
                    ctx.from_page,
                    ctx.to_page,
                )
                yield format_sse_error("translation_error", "未获取到翻译结果")
                return

            elapsed = time.time() - translate_start
            logger.info(
                "[job=%s][batch=%d-%d] translate done (%.2fs)",
                ctx.job_id,
                ctx.from_page,
                ctx.to_page,
                elapsed,
            )
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
                    {"type": "progress", "progress": 100, "stage": "finish", "stage_current": 0, "stage_total": 0}
                )
                + "\n\n"
            )
            yield f"data: {json.dumps({'type': 'finish', 'progress': 100})}\n\n"

    except GeneratorExit:
        outcome = "cancelled"
        raise
    except TranslationError as e:
        logger.warning(
            "[job=%s][batch=%d-%d] translation error: %s",
            ctx.job_id,
            ctx.from_page,
            ctx.to_page,
            e,
        )
        yield format_sse_error("translation_error", "上游翻译失败")
    except Exception:
        logger.error(
            "[job=%s][batch=%d-%d] translate failed: provider=%s model=%s lang=%s->%s tmpdir=%s",
            ctx.job_id,
            ctx.from_page,
            ctx.to_page,
            config.MODEL_PROVIDER,
            config.MODEL,
            config.TRANSLATION_LANG_IN,
            config.TRANSLATION_LANG_OUT,
            str(tmpdir),
            exc_info=True,
        )
        yield format_sse_error("internal_error", "翻译失败，请查看服务端日志")
    finally:
        worker_finished = _shutdown_worker(stream, ctx.job_id)
        if worker_finished:
            if tmpdir is not None:
                _safe_rmtree(tmpdir)
            if output_dir is not None:
                _safe_rmtree(output_dir)
        _release_job(ctx, outcome)
