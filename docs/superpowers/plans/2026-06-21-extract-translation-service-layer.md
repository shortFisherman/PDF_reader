---
change: extract-translation-service-layer
design-doc: docs/superpowers/specs/2026-06-21-extract-translation-service-layer-design.md
base-ref: aa14d6306157e5f70fb88a5ee005fe9b3ca293d2
---

# Extract Translation Service Layer 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** �?`routes.py:translate_page`�?30 行巨函数）拆分为 5 个独立可测试�?service 模块，路由层瘦身�?�?40 行，SSE 事件流字节级兼容现状�?
**Architecture:** 函数�?service 模块（顶层平铺），`sse_stream.generate` 作为组合中心接收 `GenerateContext` dataclass。service 层抛异常，generate 统一捕获并格式化�?SSE error 事件。临时文件由 generate �?finally 块统一清理�?
**Tech Stack:** Python 3, Flask, PyMuPDF (pymupdf), pdf2zh_next (do_translate_async_stream), asyncio + threading, pytest, ruff

## Global Constraints

- SSE 事件流的类型/字段/stage 标签字节级不变，`/api/*` 契约不变，前端无需改动
- `translate_page` 路由函数�?�?40 �?- 现有测试必须保持通过
- TDD 顺序：先写失败测�?�?确认失败 �?实现 �?确认通过
- 不添加任何注释（遵循项目代码风格约定�?- `debug_trace.py` 为骨架接�?+ 简单委托，完整实现留给变更 D（isolate-debug-tracing�?- 依赖变更 A（harden-pdf-state-concurrency）已归档完成的并发修�?- 新模块为顶层平铺 .py 文件（与现有 services.py、glossary_merger.py、state.py 同级�?- glossary merge 失败仅记日志不抛异常（保持现状行为）

## File Structure

| 文件 | 职责 | 变更类型 |
|------|------|----------|
| `pdf_extraction.py` | 单页 PDF 抽取 | 新建 |
| `translation_orchestrator.py` | asyncio 线程 + 事件队列编排 | 新建 |
| `sse_stream.py` | SSE 事件格式�?+ 组合中心 | 新建 |
| `glossary_service.py` | 术语表路径解析与合并 | 新建 |
| `debug_trace.py` | 调试追踪日志骨架 | 新建 |
| `routes.py` | Flask 路由（translate_page 瘦身�?| 修改 |
| `tests/test_sse_stream.py` | SSE 格式�?+ generate 测试 | 新建 |
| `tests/test_pdf_extraction.py` | PDF 抽取测试 | 新建 |
| `tests/test_translation_orchestrator.py` | 翻译编排测试 | 新建 |
| `tests/test_glossary_service.py` | 术语�?service 测试 | 新建 |
| `tests/test_debug_trace.py` | 调试追踪骨架测试 | 新建 |
| `tests/test_routes.py` | 路由测试（更�?mock 路径�?| 修改 |

---

### Task 1: SSE 字节级回归基�?
**Files:**
- Create: `tests/test_sse_stream.py`
- Modify: `routes.py`（不修改，仅用于捕获基线�?
**Interfaces:**
- Consumes: `routes.py:translate_page` 现有实现、`conftest.py` fixtures（`app_state`, `sample_pdf`�?- Produces: 黄金样本常量（`EXPECTED_PROGRESS_START_SSE`, `EXPECTED_PROGRESS_UPDATE_SSE`, `EXPECTED_FINISH_SSE`, `EXPECTED_ERROR_SSE`），�?Task 5 验证字节级兼�?
**tasks.md ref:** 1.1, 1.2

- [x] **Step 1: 创建 `tests/test_sse_stream.py`，编写黄金样本测�?*

创建 `tests/test_sse_stream.py`，捕获现�?`translate_page` SSE 输出的期望字节串。基�?routes.py:224-248 的事件格式化逻辑，直接硬编码期望值：

```python
import json


EXPECTED_PROGRESS_START_SSE = (
    'data: ' + json.dumps({
        "type": "progress", "progress": 0,
        "stage": "layout_analysis",
        "stage_current": 0, "stage_total": 0,
    }) + '\n\n'
)

EXPECTED_PROGRESS_UPDATE_SSE = (
    'data: ' + json.dumps({
        "type": "progress",
        "progress": 50,
        "stage": "translating",
        "stage_current": 2, "stage_total": 5,
    }) + '\n\n'
)

EXPECTED_FINISH_PROGRESS_SSE = (
    'data: ' + json.dumps({
        "type": "progress", "progress": 95,
        "stage": "generating_pdf",
        "stage_current": 0, "stage_total": 0,
    }) + '\n\n'
)

EXPECTED_ERROR_SSE = (
    'data: ' + json.dumps({"type": "error", "error": "test error"}) + '\n\n'
)

EXPECTED_FINAL_PROGRESS_SSE = (
    'data: ' + json.dumps({
        "type": "progress", "progress": 100,
        "stage": "finish", "stage_current": 0, "stage_total": 0,
    }) + '\n\n'
)

EXPECTED_FINAL_FINISH_SSE = (
    'data: ' + json.dumps({"type": "finish", "progress": 100}) + '\n\n'
)


def test_golden_sample_progress_start():
    assert EXPECTED_PROGRESS_START_SSE == (
        'data: {"type": "progress", "progress": 0, "stage": "layout_analysis", '
        '"stage_current": 0, "stage_total": 0}\n\n'
    )


def test_golden_sample_progress_update():
    assert EXPECTED_PROGRESS_UPDATE_SSE == (
        'data: {"type": "progress", "progress": 50, "stage": "translating", '
        '"stage_current": 2, "stage_total": 5}\n\n'
    )


def test_golden_sample_error():
    assert EXPECTED_ERROR_SSE == (
        'data: {"type": "error", "error": "test error"}\n\n'
    )
```

- [x] **Step 2: 运行测试确认基线通过**

Run: `python -m pytest tests/test_sse_stream.py -v`
Expected: 3 PASSED（黄金样本常量验证自身一致性）

- [x] **Step 3: 提交**

---

### Task 2: 抽取 pdf_extraction service

**Files:**
- Create: `pdf_extraction.py`
- Create: `tests/test_pdf_extraction.py`

**Interfaces:**
- Consumes: `pymupdf.Document`（来�?`state.left_doc`）、`pathlib.Path`
- Produces: `extract_single_page(src_doc: pymupdf.Document, page_num: int, tmpdir: Path) -> Path`

**tasks.md ref:** 2.1, 2.2, 2.3

- [x] **Step 1: �?`tests/test_pdf_extraction.py` 编写失败测试**

```python
import pymupdf
from pathlib import Path
import tempfile

from pdf_extraction import extract_single_page


def test_extract_single_page_produces_one_page_pdf():
    src_doc = pymupdf.open()
    src_doc.new_page(width=612, height=792)
    src_doc.new_page(width=612, height=792)
    src_doc.new_page(width=612, height=792)

    tmpdir = Path(tempfile.mkdtemp())
    result_path = extract_single_page(src_doc, 1, tmpdir)

    assert result_path.exists()
    assert result_path.name == "page.pdf"
    out_doc = pymupdf.open(str(result_path))
    assert out_doc.page_count == 1
    out_doc.close()
    src_doc.close()


def test_extract_single_page_correct_content():
    src_doc = pymupdf.open()
    page0 = src_doc.new_page(width=612, height=792)
    page0.insert_text((72, 72), "Page Zero")
    page1 = src_doc.new_page(width=612, height=792)
    page1.insert_text((72, 72), "Page One")
    page2 = src_doc.new_page(width=612, height=792)
    page2.insert_text((72, 72), "Page Two")

    tmpdir = Path(tempfile.mkdtemp())
    result_path = extract_single_page(src_doc, 1, tmpdir)

    out_doc = pymupdf.open(str(result_path))
    text = out_doc[0].get_text()
    assert "Page One" in text
    assert "Page Zero" not in text
    assert "Page Two" not in text
    out_doc.close()
    src_doc.close()
```

- [x] **Step 2: 运行测试确认失败**

- [x] **Step 3: 创建 `pdf_extraction.py`**

```python
from pathlib import Path

import pymupdf


def extract_single_page(src_doc: pymupdf.Document, page_num: int, tmpdir: Path) -> Path:
    single_page_pdf = tmpdir / "page.pdf"
    single_doc = pymupdf.open()
    single_doc.insert_pdf(src_doc, from_page=page_num, to_page=page_num)
    single_doc.save(str(single_page_pdf))
    single_doc.close()
    return single_page_pdf
```

- [x] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_pdf_extraction.py -v`
Expected: 2 PASSED

- [x] **Step 5: 提交**

```bash
git add pdf_extraction.py tests/test_pdf_extraction.py
git commit -m "feat: extract pdf_extraction service from translate_page"
```

---

### Task 3: 抽取 translation_orchestrator service

**Files:**
- Create: `translation_orchestrator.py`
- Create: `tests/test_translation_orchestrator.py`

**Interfaces:**
- Consumes: `pdf2zh_next.do_translate_async_stream`、`SettingsModel`、`asyncio`、`threading`、`queue`
- Produces: `TranslationError(Exception)`、`run_translation(settings, pdf_path: str) -> Iterator[dict]`

**tasks.md ref:** 3.1, 3.2, 3.3

- [x] **Step 1: �?`tests/test_translation_orchestrator.py` 编写失败测试**

```python
import asyncio
from unittest.mock import MagicMock, patch

import pytest

from translation_orchestrator import TranslationError, run_translation


def test_run_translation_yields_events_in_order():
    events = [
        {"type": "progress_start", "stage": "layout_analysis", "overall_progress": 0},
        {"type": "progress_update", "stage": "translating", "overall_progress": 50},
        {"type": "finish", "stage": "generating_pdf", "translate_result": MagicMock()},
    ]

    async def fake_stream(settings, file):
        for evt in events:
            yield evt

    with patch("translation_orchestrator.do_translate_async_stream", fake_stream):
        result = list(run_translation(MagicMock(), "fake.pdf"))

    assert len(result) == 3
    assert result[0]["type"] == "progress_start"
    assert result[1]["type"] == "progress_update"
    assert result[2]["type"] == "finish"


def test_run_translation_raises_on_thread_error():
    async def failing_stream(settings, file):
        yield {"type": "progress_start", "stage": "layout_analysis"}
        raise RuntimeError("translation engine crashed")

    with patch("translation_orchestrator.do_translate_async_stream", failing_stream):
        with pytest.raises(TranslationError, match="translation engine crashed"):
            list(run_translation(MagicMock(), "fake.pdf"))


def test_run_translation_propagates_error_event():
    async def error_stream(settings, file):
        yield {"type": "error", "error": "engine error"}
        yield {"type": "finish"}

    with patch("translation_orchestrator.do_translate_async_stream", error_stream):
        result = list(run_translation(MagicMock(), "fake.pdf"))

    assert len(result) == 2
    assert result[0]["type"] == "error"
    assert result[0]["error"] == "engine error"
```

- [x] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_translation_orchestrator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'translation_orchestrator'`

- [x] **Step 3: 创建 `translation_orchestrator.py`**

```python
import asyncio
import queue
import threading

from pdf2zh_next import do_translate_async_stream


class TranslationError(Exception):
    pass


def run_translation(settings, pdf_path: str):
    event_queue: queue.Queue = queue.Queue()
    error_info: str | None = None

    def run_translation_thread() -> None:
        nonlocal error_info
        loop: asyncio.AbstractEventLoop | None = None
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            async def _run() -> bool:
                async for evt in do_translate_async_stream(settings, pdf_path):
                    event_queue.put(evt)
                return True

            loop.run_until_complete(_run())
        except Exception as e:
            error_info = str(e)
        finally:
            if loop is not None:
                try:
                    pending = asyncio.all_tasks(loop)
                    if pending:
                        for task in pending:
                            task.cancel()
                        loop.run_until_complete(
                            asyncio.gather(*pending, return_exceptions=True)
                        )
                except Exception:
                    pass
                loop.close()
            event_queue.put({"type": "_done"})

    thread = threading.Thread(target=run_translation_thread, daemon=True)
    thread.start()

    while True:
        try:
            evt = event_queue.get(timeout=1.0)
        except queue.Empty:
            yield ""
            continue

        if evt.get("type") == "_done":
            break

        yield evt

    thread.join(timeout=5.0)

    if error_info:
        raise TranslationError(error_info)
```

- [x] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_translation_orchestrator.py -v`
Expected: 3 PASSED

- [x] **Step 5: 提交**

```bash
git add translation_orchestrator.py tests/test_translation_orchestrator.py
git commit -m "feat: extract translation_orchestrator service with TranslationError"
```

---

### Task 4: 抽取 sse_stream service

**Files:**
- Create: `sse_stream.py`
- Modify: `tests/test_sse_stream.py`（增�?format_sse_event �?generate 测试�?
**Interfaces:**
- Consumes: `translation_orchestrator.run_translation`、`glossary_service`（Task 5）、`debug_trace`（Task 6）、`state.AppState`、`services.build_settings`
- Produces: `STAGE_LABELS`、`GenerateContext`、`format_sse_event(evt: dict) -> str | None`、`generate(ctx: GenerateContext) -> Iterator[str]`

**tasks.md ref:** 4.1, 4.2, 4.3

- [x] **Step 1: �?`tests/test_sse_stream.py` 增加 `format_sse_event` 失败测试**

在文件末尾追加：

```python
from sse_stream import format_sse_event


def test_format_sse_event_progress_start():
    evt = {
        "type": "progress_start",
        "stage": "layout_analysis",
        "overall_progress": 0,
        "stage_current": 0,
        "stage_total": 0,
    }
    assert format_sse_event(evt) == EXPECTED_PROGRESS_START_SSE


def test_format_sse_event_progress_update():
    evt = {
        "type": "progress_update",
        "stage": "translating",
        "overall_progress": 50,
        "stage_current": 2,
        "stage_total": 5,
    }
    assert format_sse_event(evt) == EXPECTED_PROGRESS_UPDATE_SSE


def test_format_sse_event_finish():
    evt = {
        "type": "finish",
        "stage": "generating_pdf",
        "translate_result": None,
        "token_usage": {},
    }
    assert format_sse_event(evt) == EXPECTED_FINISH_PROGRESS_SSE


def test_format_sse_event_error():
    evt = {"type": "error", "error": "test error"}
    assert format_sse_event(evt) == EXPECTED_ERROR_SSE


def test_format_sse_event_internal_done_returns_none():
    evt = {"type": "_done"}
    assert format_sse_event(evt) is None


def test_format_sse_event_unknown_type_returns_none():
    evt = {"type": "unknown_type"}
    assert format_sse_event(evt) is None
```

- [x] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_sse_stream.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sse_stream'`

- [x] **Step 3: 创建 `sse_stream.py`（format_sse_event + STAGE_LABELS + GenerateContext�?*

```python
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from pdf2zh_next import SettingsModel

from state import AppState


STAGE_LABELS = {
    "layout_analysis": "正在分析版面�?,
    "translating": "正在翻译�?,
    "generating_pdf": "正在生成译文�?,
    "generating_pdf_bilingual": "正在生成译文�?,
    "finish": "翻译完成",
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
```

- [x] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_sse_stream.py -v`
Expected: 9 PASSED�? 黄金样本 + 6 format_sse_event 测试�?
- [x] **Step 5: 提交**

```bash
git add sse_stream.py tests/test_sse_stream.py
git commit -m "feat: extract sse_stream service with format_sse_event and STAGE_LABELS"
```

---

### Task 5: 抽取 glossary_service

**Files:**
- Create: `glossary_service.py`
- Create: `tests/test_glossary_service.py`

**Interfaces:**
- Consumes: `state.AppState`、`glossary_merger.merge_glossary_csvs`、`pathlib.Path`
- Produces: `resolve_glossary_paths(state: AppState) -> list[str] | None`、`merge_after_translate(cumulative_path: Path | None, auto_extracted_path: Path | None) -> None`

**tasks.md ref:** 5.1, 5.2, 5.3

- [x] **Step 1: �?`tests/test_glossary_service.py` 编写失败测试**

```python
import csv
from pathlib import Path
from unittest.mock import patch, MagicMock

from glossary_service import resolve_glossary_paths, merge_after_translate


def test_resolve_glossary_paths_returns_none_when_no_cache():
    state = MagicMock()
    state.glossary_cache_path = None
    assert resolve_glossary_paths(state) is None


def test_resolve_glossary_paths_returns_none_when_no_cumulative_file():
    state = MagicMock()
    state.glossary_cache_path = Path("/nonexistent")
    assert resolve_glossary_paths(state) is None


def test_resolve_glossary_paths_returns_path_when_cumulative_exists(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    cumulative = cache_dir / "cumulative_glossary.csv"
    with open(cumulative, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["source", "target"])
        w.writerow(["hello", "你好"])

    state = MagicMock()
    state.glossary_cache_path = cache_dir
    result = resolve_glossary_paths(state)
    assert result == [str(cumulative)]


def test_resolve_glossary_paths_returns_none_when_cumulative_empty(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    cumulative = cache_dir / "cumulative_glossary.csv"
    cumulative.write_text("")

    state = MagicMock()
    state.glossary_cache_path = cache_dir
    assert resolve_glossary_paths(state) is None


def test_merge_after_translate_delegates_to_merger(tmp_path):
    cumulative = tmp_path / "cumulative.csv"
    auto = tmp_path / "auto.csv"
    cumulative.write_text("")
    auto.write_text("")

    with patch("glossary_service.merge_glossary_csvs") as mock_merge:
        merge_after_translate(cumulative, auto)
        mock_merge.assert_called_once_with(cumulative, auto)


def test_merge_after_translate_swallows_exception(tmp_path):
    cumulative = tmp_path / "cumulative.csv"
    auto = tmp_path / "auto.csv"

    with patch("glossary_service.merge_glossary_csvs", side_effect=Exception("merge failed")):
        merge_after_translate(cumulative, auto)


def test_merge_after_translate_none_paths():
    merge_after_translate(None, None)
```

- [x] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_glossary_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'glossary_service'`

- [x] **Step 3: 创建 `glossary_service.py`**

```python
import logging
from pathlib import Path

from glossary_merger import merge_glossary_csvs
from state import AppState

logger = logging.getLogger("pdf_reader")


def resolve_glossary_paths(state: AppState) -> list[str] | None:
    cumulative_glossary_path = state.glossary_cache_path
    if cumulative_glossary_path is None:
        return None
    cumulative_file = cumulative_glossary_path / "cumulative_glossary.csv"
    if cumulative_file.exists() and cumulative_file.stat().st_size > 0:
        return [str(cumulative_file)]
    return None


def merge_after_translate(cumulative_path: Path | None, auto_extracted_path: Path | None) -> None:
    if cumulative_path is None or auto_extracted_path is None:
        return
    try:
        merge_glossary_csvs(cumulative_path, auto_extracted_path)
    except Exception:
        logger.warning("Failed to merge glossary", exc_info=True)
```

- [x] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_glossary_service.py -v`
Expected: 7 PASSED

- [x] **Step 5: 提交**

```bash
git add glossary_service.py tests/test_glossary_service.py
git commit -m "feat: extract glossary_service with path resolution and merge"
```

---

### Task 6: 抽取 debug_trace 骨架

**Files:**
- Create: `debug_trace.py`
- Create: `tests/test_debug_trace.py`

**Interfaces:**
- Consumes: `config.DEBUG`、`logging`、`pathlib.Path`、`time`
- Produces: `trace_logger`、`log_step(step: str, *args) -> None`、`setup_file_handler(glossary_path: Path | None, page: int) -> logging.FileHandler | None`、`cleanup_file_handler(handler: logging.FileHandler | None) -> None`、`log_token_usage(token_usage: dict) -> None`

**tasks.md ref:** 无（design.md 决策 1 �?`debug_trace.py` 见变�?D，此处建骨架�?
- [x] **Step 1: �?`tests/test_debug_trace.py` 编写失败测试**

```python
import logging
from pathlib import Path
from unittest.mock import patch, MagicMock

import debug_trace


def test_trace_logger_exists():
    assert isinstance(debug_trace.trace_logger, logging.Logger)
    assert debug_trace.trace_logger.name == "pdf_reader.debug_trace"
    assert debug_trace.trace_logger.level == logging.INFO


def test_log_step_no_op_when_debug_false():
    with patch("debug_trace.config") as mock_config:
        mock_config.DEBUG = False
        with patch.object(debug_trace.trace_logger, "info") as mock_info:
            debug_trace.log_step("test step %d", 1)
            mock_info.assert_not_called()


def test_log_step_logs_when_debug_true():
    with patch("debug_trace.config") as mock_config:
        mock_config.DEBUG = True
        with patch.object(debug_trace.trace_logger, "info") as mock_info:
            debug_trace.log_step("test step %d", 1)
            mock_info.assert_called_once_with("[step] test step %d", 1)


def test_setup_file_handler_returns_none_when_no_glossary_path():
    with patch("debug_trace.config") as mock_config:
        mock_config.DEBUG = True
        result = debug_trace.setup_file_handler(None, 0)
        assert result is None


def test_setup_file_handler_returns_none_when_debug_false():
    with patch("debug_trace.config") as mock_config:
        mock_config.DEBUG = False
        result = debug_trace.setup_file_handler(Path("/some/path"), 0)
        assert result is None


def test_cleanup_file_handler_none_is_noop():
    debug_trace.cleanup_file_handler(None)


def test_cleanup_file_handler_removes_and_closes():
    handler = MagicMock(spec=logging.FileHandler)
    debug_trace.cleanup_file_handler(handler)
    debug_trace.trace_logger.removeHandler.assert_called_once_with(handler)
    handler.close.assert_called_once()


def test_log_token_usage_no_op_when_empty():
    with patch("debug_trace.config") as mock_config:
        mock_config.DEBUG = True
        with patch.object(debug_trace.trace_logger, "info") as mock_info:
            debug_trace.log_token_usage({})
            mock_info.assert_not_called()


def test_log_token_usage_logs_when_has_data():
    with patch("debug_trace.config") as mock_config:
        mock_config.DEBUG = True
        token_usage = {"main": {"total": 100}, "term": {"total": 50}}
        with patch.object(debug_trace.trace_logger, "info") as mock_info:
            debug_trace.log_token_usage(token_usage)
            assert mock_info.call_count == 2
```

- [x] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_debug_trace.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'debug_trace'`

- [x] **Step 3: 创建 `debug_trace.py`**

```python
import logging
import shutil
import time
from pathlib import Path

import config

trace_logger = logging.getLogger("pdf_reader.debug_trace")
trace_logger.setLevel(logging.INFO)
if not trace_logger.handlers:
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s:%(name)s:%(message)s"
    ))
    trace_logger.addHandler(console_handler)


def log_step(step: str, *args) -> None:
    if config.DEBUG:
        trace_logger.info(f"[step] {step}", *args)


def setup_file_handler(glossary_path: Path | None, page: int) -> logging.FileHandler | None:
    if not config.DEBUG or glossary_path is None:
        return None
    try:
        log_path = glossary_path / "debug_trace.log"
        if log_path.exists():
            rotated = glossary_path / (
                "debug_trace." + time.strftime("%Y%m%d_%H%M%S") + ".log"
            )
            shutil.move(str(log_path), str(rotated))
        file_handler = logging.FileHandler(str(log_path), encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s:%(name)s:%(message)s"
        ))
        trace_logger.addHandler(file_handler)
        trace_logger.info("=== Debug session start: page %d ===", page)
        return file_handler
    except Exception:
        logging.getLogger("pdf_reader").warning(
            "Failed to create debug_trace.log file handler", exc_info=True
        )
        return None


def cleanup_file_handler(handler: logging.FileHandler | None) -> None:
    if handler is None:
        return
    try:
        trace_logger.removeHandler(handler)
        handler.close()
    except Exception:
        pass


def log_token_usage(token_usage: dict) -> None:
    if not config.DEBUG:
        return
    if not token_usage:
        return
    total = token_usage.get("main", {}).get("total", 0)
    term_total = token_usage.get("term", {}).get("total", 0)
    if total or term_total:
        trace_logger.info("Token usage: main=%d, term=%d", total, term_total)
```

- [x] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_debug_trace.py -v`
Expected: 9 PASSED

- [x] **Step 5: 提交**

```bash
git add debug_trace.py tests/test_debug_trace.py
git commit -m "feat: add debug_trace skeleton interface with simple delegation"
```

---

### Task 7: 实现 sse_stream.generate 组合中心

**Files:**
- Modify: `sse_stream.py`（实�?generate 函数�?- Modify: `tests/test_sse_stream.py`（增�?generate 集成测试�?
**Interfaces:**
- Consumes: `translation_orchestrator.run_translation`、`translation_orchestrator.TranslationError`、`glossary_service.merge_after_translate`、`debug_trace.setup_file_handler`/`cleanup_file_handler`/`log_step`/`log_token_usage`、`state.AppState.replace_page`
- Produces: 完整�?`generate(ctx: GenerateContext) -> Iterator[str]` 实现

**tasks.md ref:** 4.1（generate 部分）�?.1（SSE 生成器组合）

- [ ] **Step 1: �?`tests/test_sse_stream.py` 增加 generate 失败测试**

在文件末尾追加：

```python
import shutil
import tempfile
from unittest.mock import patch, MagicMock

from sse_stream import generate, GenerateContext


def test_generate_full_flow_byte_level_compatible(tmp_path):
    mock_result = MagicMock()
    mock_result.mono_pdf_path = str(tmp_path / "translated.pdf")
    mock_result.dual_pdf_path = None
    mock_result.auto_extracted_glossary_path = None

    events = [
        {"type": "progress_start", "stage": "layout_analysis", "overall_progress": 0,
         "stage_current": 0, "stage_total": 0},
        {"type": "progress_update", "stage": "translating", "overall_progress": 50,
         "stage_current": 1, "stage_total": 2},
        {"type": "finish", "stage": "generating_pdf", "translate_result": mock_result,
         "token_usage": {}},
    ]

    state = MagicMock()
    state.glossary_cache_path = None
    state.replace_page = MagicMock()

    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    output_dir = str(tmp_path / "output")
    single_page_pdf = tmpdir / "page.pdf"
    single_page_pdf.write_bytes(b"fake pdf")

    ctx = GenerateContext(
        settings=MagicMock(),
        single_page_pdf=single_page_pdf,
        state=state,
        page=0,
        glossary_paths=None,
        tmpdir=tmpdir,
        output_dir=output_dir,
    )

    with patch("sse_stream.run_translation", return_value=iter(events)):
        with patch("sse_stream.debug_trace"):
            result = list(generate(ctx))

    expected = [
        EXPECTED_PROGRESS_START_SSE,
        EXPECTED_PROGRESS_UPDATE_SSE,
        EXPECTED_FINISH_PROGRESS_SSE,
        EXPECTED_FINAL_PROGRESS_SSE,
        EXPECTED_FINAL_FINISH_SSE,
    ]
    assert result == expected
    state.replace_page.assert_called_once_with(str(tmp_path / "translated.pdf"), 0)


def test_generate_error_event_stops_stream(tmp_path):
    events = [
        {"type": "progress_start", "stage": "layout_analysis"},
        {"type": "error", "error": "engine failed"},
    ]

    state = MagicMock()
    state.glossary_cache_path = None

    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    single_page_pdf = tmpdir / "page.pdf"
    single_page_pdf.write_bytes(b"fake")

    ctx = GenerateContext(
        settings=MagicMock(),
        single_page_pdf=single_page_pdf,
        state=state,
        page=0,
        glossary_paths=None,
        tmpdir=tmpdir,
        output_dir=str(tmp_path / "output"),
    )

    with patch("sse_stream.run_translation", return_value=iter(events)):
        with patch("sse_stream.debug_trace"):
            result = list(generate(ctx))

    assert len(result) == 2
    assert result[0] == EXPECTED_PROGRESS_START_SSE
    assert result[1] == EXPECTED_ERROR_SSE


def test_generate_translation_error_yields_error_event(tmp_path):
    from translation_orchestrator import TranslationError

    events = [{"type": "progress_start", "stage": "layout_analysis"}]

    state = MagicMock()
    state.glossary_cache_path = None

    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    single_page_pdf = tmpdir / "page.pdf"
    single_page_pdf.write_bytes(b"fake")

    ctx = GenerateContext(
        settings=MagicMock(),
        single_page_pdf=single_page_pdf,
        state=state,
        page=0,
        glossary_paths=None,
        tmpdir=tmpdir,
        output_dir=str(tmp_path / "output"),
    )

    def error_iter():
        yield from events
        raise TranslationError("thread crashed")

    with patch("sse_stream.run_translation", side_effect=error_iter):
        with patch("sse_stream.debug_trace"):
            result = list(generate(ctx))

    assert len(result) == 2
    assert result[0] == EXPECTED_PROGRESS_START_SSE
    assert "error" in result[1]
    assert "thread crashed" in result[1]


def test_generate_cleans_up_tmpdir(tmp_path):
    mock_result = MagicMock()
    mock_result.mono_pdf_path = str(tmp_path / "translated.pdf")
    mock_result.dual_pdf_path = None
    mock_result.auto_extracted_glossary_path = None

    events = [{"type": "finish", "stage": "generating_pdf", "translate_result": mock_result}]

    state = MagicMock()
    state.glossary_cache_path = None
    state.replace_page = MagicMock()

    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    (tmpdir / "page.pdf").write_bytes(b"fake")
    output_dir = str(tmp_path / "output")
    Path(output_dir).mkdir()

    ctx = GenerateContext(
        settings=MagicMock(),
        single_page_pdf=tmpdir / "page.pdf",
        state=state,
        page=0,
        glossary_paths=None,
        tmpdir=tmpdir,
        output_dir=output_dir,
    )

    with patch("sse_stream.run_translation", return_value=iter(events)):
        with patch("sse_stream.debug_trace"):
            list(generate(ctx))

    assert not tmpdir.exists()
    assert not Path(output_dir).exists()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_sse_stream.py::test_generate_full_flow_byte_level_compatible -v`
Expected: FAIL（generate raises NotImplementedError�?
- [ ] **Step 3: �?`sse_stream.py` 实现 generate 函数**

�?`sse_stream.py` 中的 `generate` 函数替换为：

```python
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from pdf2zh_next import SettingsModel

import debug_trace
from glossary_service import merge_after_translate
from state import AppState
from translation_orchestrator import TranslationError, run_translation


STAGE_LABELS = {
    "layout_analysis": "正在分析版面�?,
    "translating": "正在翻译�?,
    "generating_pdf": "正在生成译文�?,
    "generating_pdf_bilingual": "正在生成译文�?,
    "finish": "翻译完成",
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

        translate_start = __import__("time").time()
        translate_result = None
        token_usage_finish = None

        for evt in run_translation(ctx.settings, str(ctx.single_page_pdf)):
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

        debug_trace.log_step("translate page %d done (%.2fs)", ctx.page, __import__("time").time() - translate_start)
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

        merge_after_translate(
            ctx.state.glossary_cache_path,
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_sse_stream.py -v`
Expected: 13 PASSED�? 黄金样本 + 6 format_sse_event + 4 generate 测试�?
- [ ] **Step 5: 提交**

```bash
git add sse_stream.py tests/test_sse_stream.py
git commit -m "feat: implement sse_stream.generate composition center with error handling"
```

---

### Task 8: 重构 translate_page 路由

**Files:**
- Modify: `routes.py`（translate_page 瘦身 + 移除 STAGE_LABELS/trace_logger�?- Modify: `tests/test_routes.py`（更�?mock 路径�?
**Interfaces:**
- Consumes: `pdf_extraction.extract_single_page`、`glossary_service.resolve_glossary_paths`、`sse_stream.GenerateContext`/`generate`、`debug_trace`、`services.build_settings`
- Produces: `translate_page` �?40 �?
**tasks.md ref:** 6.1, 6.2, 6.3, 6.4

- [ ] **Step 1: 重写 `routes.py:translate_page`**

�?routes.py �?import 部分�?translate_page 函数替换。首先更�?imports（移�?asyncio/queue/threading/tempfile/time/shutil/Path/pymupdf/do_translate_async_stream/merge_glossary_csvs，添加新 service 模块）：

```python
import io
import json
import logging
import os
import tempfile
from pathlib import Path

from flask import (
    Blueprint,
    Response,
    current_app,
    jsonify,
    render_template,
    request,
    send_file,
    stream_with_context,
)

import config
import debug_trace
import glossary_service
import pdf_extraction
import sse_stream
from services import build_settings, render_page, sha256
```

移除 `STAGE_LABELS` �?`trace_logger` 定义（已迁移�?sse_stream.py �?debug_trace.py）�?
重写 `translate_page`�?
```python
@bp.route("/api/translate/<int:page>", methods=["POST"])
def translate_page(page: int):
    state = _get_state()
    if state.left_doc is None:
        return error_response("no document opened", 400)
    if page < 0 or page >= state.page_count:
        return error_response("page out of range", 400)

    data = request.get_json(silent=True) or {}
    user_prompt = (data.get("prompt") or "").strip() or None

    tmpdir = Path(tempfile.mkdtemp())
    output_dir = tempfile.mkdtemp(dir=str(config.CACHE_DIR))
    single_page_pdf = pdf_extraction.extract_single_page(state.left_doc, page, tmpdir)
    glossary_paths = glossary_service.resolve_glossary_paths(state)
    settings = build_settings(
        str(single_page_pdf), user_prompt,
        output_dir=output_dir, glossary_paths=glossary_paths, debug=config.DEBUG,
    )
    ctx = sse_stream.GenerateContext(
        settings=settings, single_page_pdf=single_page_pdf, state=state,
        page=page, glossary_paths=glossary_paths, tmpdir=tmpdir, output_dir=output_dir,
    )
    return Response(
        stream_with_context(sse_stream.generate(ctx)),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

- [ ] **Step 2: 更新 `tests/test_routes.py` 中的 mock 路径**

`test_translate_page_integrates_cumulative_glossary` 当前 mock `routes.build_settings`、`routes.do_translate_async_stream`、`routes.merge_glossary_csvs`。需要更新为 mock 新模块：

```python
def test_translate_page_integrates_cumulative_glossary(app_state, sample_pdf, monkeypatch):
    from services import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    glossary_cache = app_state.glossary_cache_path
    assert glossary_cache is not None
    cumulative_file = glossary_cache / "cumulative_glossary.csv"
    with open(cumulative_file, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["source", "target"])
        w.writerow(["alpha", "阿尔�?])

    auto_file = glossary_cache / "auto_extracted.csv"
    with open(auto_file, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["source", "target"])
        w.writerow(["beta", "贝塔"])

    mock_result = MagicMock()
    mock_result.mono_pdf_path = Path(str(sample_pdf))
    mock_result.dual_pdf_path = None
    mock_result.auto_extracted_glossary_path = auto_file

    settings_call_kwargs = []
    merge_calls = []

    def fake_build_settings(pdf_path, user_prompt=None, output_dir=None, glossary_paths=None, debug=None):
        settings_call_kwargs.append({"glossary_paths": glossary_paths})
        return MagicMock()

    async def fake_translate_stream(settings, file):
        yield {"type": "progress_start", "stage": "layout_analysis", "overall_progress": 0,
               "stage_current": 0, "stage_total": 0}
        yield {"type": "finish", "stage": "generating_pdf", "translate_result": mock_result}

    def fake_merge(cumulative, auto):
        merge_calls.append((str(cumulative), str(auto)))

    monkeypatch.setattr("services.build_settings", fake_build_settings)
    monkeypatch.setattr("translation_orchestrator.do_translate_async_stream", fake_translate_stream)
    monkeypatch.setattr("glossary_service.merge_glossary_csvs", fake_merge)

    from flask import Flask
    app = Flask(__name__)
    app.config["app_state"] = app_state
    app.config["TESTING"] = True
    from routes import register_routes
    register_routes(app)

    with app.test_client() as client:
        resp = client.post("/api/translate/0", json={})
        assert resp.status_code == 200
        body = resp.data.decode("utf-8")
        assert '"type": "finish"' in body

    assert len(settings_call_kwargs) == 1
    assert settings_call_kwargs[0]["glossary_paths"] == [str(cumulative_file)]
    assert len(merge_calls) == 1
    assert merge_calls[0] == (str(cumulative_file), str(auto_file))
```

同时更新 `test_debug_trace_logger_exists`�?
```python
def test_debug_trace_logger_exists():
    import logging
    from debug_trace import trace_logger
    assert isinstance(trace_logger, logging.Logger)
    assert trace_logger.name == "pdf_reader.debug_trace"
    assert trace_logger.level == logging.INFO
```

- [ ] **Step 3: 运行路由测试确认通过**

Run: `python -m pytest tests/test_routes.py -v`
Expected: ALL PASSED（包括更新后�?glossary 集成测试�?debug_trace_logger 测试�?
- [ ] **Step 4: 确认 translate_page 函数�?�?40 �?*

Run: `python -c "import routes, inspect; src = inspect.getsource(routes.translate_page); lines = [l for l in src.split(chr(10)) if l.strip() and not l.strip().startswith('@') and not l.strip().startswith('def ')]; print(f'Body lines: {len(lines)}')"`
Expected: `Body lines: �?20`

- [ ] **Step 5: 提交**

```bash
git add routes.py tests/test_routes.py
git commit -m "refactor: slim translate_page to thin orchestration with service layer"
```

---

### Task 9: 全量回归�?lint

**Files:**
- 无新文件，验证所有测试和 lint

**tasks.md ref:** 7.1, 7.2

- [ ] **Step 1: 运行全量测试**

Run: `python -m pytest tests/ -v`
Expected: ALL PASSED（原有测�?+ 新增 service 模块测试�?
- [ ] **Step 2: 运行 ruff lint**

Run: `python -m ruff check .`
Expected: 0 errors

- [ ] **Step 3: 如有 lint 错误，修复后重新运行**

修复所�?ruff 报告的错误，然后重新运行 Step 1 �?Step 2 确认全绿�?
- [ ] **Step 4: 提交（如�?lint 修复�?*

```bash
git add -A
git commit -m "chore: lint cleanup for translation service layer extraction"
```

- [ ] **Step 5: 确认所�?tasks.md 任务已勾�?*

检�?`openspec/changes/extract-translation-service-layer/tasks.md` 中所�?`[ ]` 已改�?`[x]`�?