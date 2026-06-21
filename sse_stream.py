import json
import shutil
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from pdf2zh_next import SettingsModel

import debug_trace
from glossary_service import merge_after_translate
from state import AppState
from translation_orchestrator import TranslationError, run_translation

STAGE_LABELS = {
    "layout_analysis": "\u6b63\u5728\u5206\u6790\u7248\u9762\u2026",
    "translating": "\u6b63\u5728\u7ffb\u8bd1\u2026",
    "generating_pdf": "\u6b63\u5728\u751f\u6210\u8bd1\u6587\u2026",
    "generating_pdf_bilingual": "\u6b63\u5728\u751f\u6210\u8bd1\u6587\u2026",
    "finish": "\u7ffb\u8bd1\u5b8c\u6210",
}


@dataclass
class GenerateContext:
    settings: SettingsModel
    single_page_pdf: Path
    state: AppState
    page: int
    glossary_paths: list[str] | None
    tmpdir: Path
    output_dir: str


def format_sse_event(evt: dict) -> str | None:
    evt_type = evt.get("type", "")

    if evt_type == "progress_start":
        return "data: " + json.dumps({
            "type": "progress", "progress": 0,
            "stage": evt.get("stage", ""),
            "stage_current": evt.get("stage_current", 0),
            "stage_total": evt.get("stage_total", 0),
        }) + "\n\n"
    elif evt_type == "progress_update":
        return "data: " + json.dumps({
            "type": "progress",
            "progress": evt.get("overall_progress", 0),
            "stage": evt.get("stage", ""),
            "stage_current": evt.get("stage_current", 0),
            "stage_total": evt.get("stage_total", 0),
        }) + "\n\n"
    elif evt_type == "finish":
        return "data: " + json.dumps({
            "type": "progress", "progress": 95,
            "stage": evt.get("stage", "generating_pdf"),
            "stage_current": 0, "stage_total": 0,
        }) + "\n\n"
    elif evt_type == "error":
        return f"data: {json.dumps({'type': 'error', 'error': evt.get('error', 'unknown')})}\n\n"
    else:
        return None


def generate(ctx: GenerateContext) -> Iterator[str]:
    handler = None
    try:
        handler = debug_trace.setup_file_handler(ctx.state.glossary_cache_path, ctx.page)
        debug_trace.log_step("submit translate page %d", ctx.page)

        translate_start = time.time()
        translate_result = None
        token_usage_finish = None

        for evt in run_translation(ctx.settings, str(ctx.single_page_pdf)):
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

        debug_trace.log_step("translate page %d done (%.2fs)", ctx.page, time.time() - translate_start)
        if token_usage_finish:
            debug_trace.log_token_usage(token_usage_finish)

        translated_pdf = translate_result.mono_pdf_path
        if translated_pdf is None and translate_result.dual_pdf_path is not None:
            translated_pdf = translate_result.dual_pdf_path

        if translated_pdf is not None:
            ctx.state.replace_page(str(translated_pdf), ctx.page)
        else:
            yield f"data: {json.dumps({'type': 'error', 'error': 'no output PDF'})}\n\n"
            return

        cumulative_glossary_file: Path | None = None
        if ctx.state.glossary_cache_path is not None:
            cumulative_glossary_file = ctx.state.glossary_cache_path / "cumulative_glossary.csv"
        merge_after_translate(
            cumulative_glossary_file,
            translate_result.auto_extracted_glossary_path,
        )

        yield "data: " + json.dumps({
            "type": "progress", "progress": 100,
            "stage": "finish", "stage_current": 0, "stage_total": 0,
        }) + "\n\n"
        yield f"data: {json.dumps({'type': 'finish', 'progress': 100})}\n\n"

    except TranslationError as e:
        yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
    finally:
        debug_trace.cleanup_file_handler(handler)
        shutil.rmtree(ctx.tmpdir, ignore_errors=True)
        shutil.rmtree(ctx.output_dir, ignore_errors=True)
