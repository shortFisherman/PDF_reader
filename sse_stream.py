import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from pdf2zh_next import SettingsModel

from state import AppState

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
    raise NotImplementedError("Implemented in Task 7 with full integration")
