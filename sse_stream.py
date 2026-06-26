import json
import logging
import shutil
import tempfile
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from pdf2zh_next import SettingsModel

import debug_trace
import pdf_extraction
from translation_lifecycle import finish_translation, merge_glossary_only
from translation_orchestrator import TranslationError, run_translation

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
    replace_page: Callable[[str], None]
    glossary_cache_path: Path | None
    page: int
    glossary_paths: list[str] | None
    cache_dir: Path
    extract_page: Callable[[int, Path, Callable], Path]


@dataclass
class GenerateBatchContext:
    settings: SettingsModel
    from_page: int
    to_page: int
    page_indices: list[int]
    replace_pages: Callable[[str], None]
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
        return f"data: {json.dumps({'type': 'error', 'error': evt.get('error', 'unknown')})}\n\n"
    else:
        return None


def generate(ctx: GenerateContext) -> Iterator[str]:
    tmpdir = Path(tempfile.mkdtemp())
    output_dir = Path(tempfile.mkdtemp(dir=str(ctx.cache_dir)))
    ctx.settings.translation.output = str(output_dir)
    try:
        with debug_trace.debug_session(ctx.glossary_cache_path, ctx.page):
            logger.info("[page=%d] submit translate", ctx.page)

            translate_start = time.time()
            translate_result = None
            token_usage_finish = None

            single_page_pdf = ctx.extract_page(ctx.page, tmpdir, pdf_extraction.extract_single_page)

            for evt in run_translation(ctx.settings, str(single_page_pdf), flow_label=f"page={ctx.page}"):
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
                    return

            if translate_result is None:
                yield f"data: {json.dumps({'type': 'error', 'error': 'no translation result'})}\n\n"
                return

            elapsed = time.time() - translate_start
            logger.info("[page=%d] translate done (%.2fs)", ctx.page, elapsed)
            if token_usage_finish:
                debug_trace.log_token_usage(token_usage_finish)

            finish_translation(
                translate_result,
                ctx.replace_page,
                ctx.glossary_cache_path,
            )

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

    except TranslationError as e:
        yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
    except Exception as e:
        logger.warning("translate_page generate error", exc_info=True)
        yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
    finally:
        _safe_rmtree(tmpdir)
        _safe_rmtree(output_dir)


def generate_batch(ctx: GenerateBatchContext) -> Iterator[str]:
    tmpdir = Path(tempfile.mkdtemp())
    output_dir = Path(tempfile.mkdtemp(dir=str(ctx.cache_dir)))
    ctx.settings.translation.output = str(output_dir)
    try:
        with debug_trace.debug_session(ctx.glossary_cache_path, ctx.from_page):
            logger.info("[batch=%d-%d] submit translate", ctx.from_page, ctx.to_page)

            translate_start = time.time()
            translate_result = None
            token_usage_finish = None

            multi_page_pdf = ctx.extract_pages(ctx.page_indices, tmpdir, pdf_extraction.extract_pages)

            yield format_batch_info(ctx.from_page, ctx.to_page, len(ctx.page_indices))

            for evt in run_translation(ctx.settings, str(multi_page_pdf), flow_label=f"batch={ctx.from_page}-{ctx.to_page}"):
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
                    return

            if translate_result is None:
                yield f"data: {json.dumps({'type': 'error', 'error': 'no translation result'})}\n\n"
                return

            elapsed = time.time() - translate_start
            logger.info("[batch=%d-%d] translate done (%.2fs)", ctx.from_page, ctx.to_page, elapsed)
            if token_usage_finish:
                debug_trace.log_token_usage(token_usage_finish)

            translated_pdf = translate_result.mono_pdf_path
            if translated_pdf is None and translate_result.dual_pdf_path is not None:
                translated_pdf = translate_result.dual_pdf_path
            if translated_pdf is not None:
                ctx.replace_pages(str(translated_pdf))

            merge_glossary_only(translate_result, ctx.glossary_cache_path)

            yield (
                "data: "
                + json.dumps(
                    {"type": "progress", "progress": 100, "stage": "finish",
                     "stage_current": 0, "stage_total": 0}
                )
                + "\n\n"
            )
            yield f"data: {json.dumps({'type': 'finish', 'progress': 100})}\n\n"

    except TranslationError as e:
        yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
    except Exception as e:
        logger.warning("translate_batch generate error", exc_info=True)
        yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
    finally:
        _safe_rmtree(tmpdir)
        _safe_rmtree(output_dir)
