---
change: fix-concurrency-resource-cleanup
design-doc: docs/superpowers/specs/2026-06-25-fix-concurrency-resource-cleanup-design.md
base-ref: fffa539a2e74fb9806d058e31dcd02bcd84ce67a
---

# fix-concurrency-resource-cleanup 实现计划

> **对于 agentic worker:** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 来逐个任务实现此计划。步骤使用 checkbox (`- [ ]`) 语法进行跟踪。

**目标：** 修复两个并发相关缺陷：（1）`generate()` 提前返回/异常/客户端断连时 tmpdir/output_dir 泄漏；（2）`extract_single_page` 绕过 AppState 锁，与 `render_page` 产生 data race。

**架构：** 将 tmpdir/output_dir 的创建和清理职责统一收归到 `sse_stream.generate()` 的 try/finally 中（资源创建者即清理者）；在 `AppState` 新增 `extract_page()` 方法，与 `render_page` 同模式在锁内执行提取操作；`routes.py` 移除裸 `state.left_doc` 访问和目录创建逻辑。

**技术栈：** Python 3.12+, pymupdf, Flask SSE streaming, threading.Lock

## 全局约束

- Python 版本不低于 3.12
- 使用现有 `threading.Lock`（非重入锁），不引入读写锁或更细粒度并发模型
- `extract_page` 方法文档化约束：`extract_func` 不得回调 AppState（与 `render_page` 同模式）
- `shutil.rmtree` 必须使用 `ignore_errors=True`，失败仅 `logger.debug`
- 清理逻辑绝不抛出异常，绝不掩盖业务错误
- 遵循现有代码风格：无类型注解冗余注释、dataclass、与 `render_page` 同模式的 docstring 风格

---

## 文件结构

| 文件 | 职责 | 操作 |
|------|------|------|
| `state.py` | 新增 `extract_page()` 方法 | 修改 |
| `sse_stream.py` | GenerateContext 数据类简化、generate() 新增 try/finally、_safe_rmtree 辅助函数 | 修改 |
| `routes.py` | 移除 tmpdir/output_dir 创建和裸 state.left_doc 访问 | 修改 |
| `translation_lifecycle.py` | 移除 tmpdir/output_dir 参数及 shutil.rmtree 调用 | 修改 |
| `tests/test_sse_stream.py` | 新增清理测试，适配 GenerateContext 签名变更 | 修改 |
| `tests/test_state.py` | 新增 extract_page 测试 | 修改 |

---

### 任务 1：AppState 新增 extract_page 方法

**文件：**
- 修改：`state.py:90-96`（在 `render_page` 方法之后插入）

**接口：**
- 消费：无（独立任务）
- 产出：`AppState.extract_page(self, page: int, tmpdir: Path, extract_func) -> Path`

**描述：** 在 `AppState` 类中新增 `extract_page` 方法，与 `render_page` 同模式——锁内获取 `_left_doc`，校验非空，回调 `extract_func`。

- [x] **Step 1：在 state.py 中新增 extract_page 方法**

在 `state.py` 第 96 行（`render_page` 方法结束的 `return render_func(doc, page_num, dpi)` 之后，空行处）插入以下代码：

```python
    def extract_page(self, page: int, tmpdir: Path, extract_func) -> Path:
        """Extract a single page under the state lock.
        extract_func must not reenter AppState (non-reentrant lock)."""
        with self._lock:
            if self._left_doc is None:
                raise ValueError("no document opened")
            return extract_func(self._left_doc, page, tmpdir)
```

- [x] **Step 2：运行现有 state 测试确认无回归**

```bash
pytest tests/test_state.py -q
```

预期：全部 PASS。

- [x] **Step 3：提交**

```bash
git add state.py
git commit -m "feat(state): add extract_page method under lock for concurrency safety"
```

---

### 任务 2：GenerateContext 数据类重构 + generate() try/finally 清理 + _safe_rmtree

**文件：**
- 修改：`sse_stream.py:1-13`（import 区域）、`sse_stream.py:23-32`（GenerateContext）、`sse_stream.py:65-115`（generate 函数体）

**接口：**
- 消费：任务 1 的 `AppState.extract_page`
- 产出：`GenerateContext` 新字段 `page: int`、`cache_dir: Path`、`extract_page: Callable[[int, Path, Callable], Path]`；`generate()` 内部创建和清理 tmpdir/output_dir

**描述：** 一步完成 sse_stream.py 的所有变更：import 补充、GenerateContext 简化、_safe_rmtree 辅助函数、generate() 重写为 try/finally 模式。

- [x] **Step 1：更新 import 区域**

将 `sse_stream.py` 第 1-12 行替换为：

```python
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
from translation_lifecycle import finish_translation
from translation_orchestrator import TranslationError, run_translation
```

（相对于原文件，新增 `import shutil`、`import tempfile`、`import pdf_extraction`）

- [x] **Step 2：替换 STAGE_LABELS 之后、GenerateContext 之前的区域，添加 _safe_rmtree 辅助函数**

`STAGE_LABELS` 保持不变。在其后（第 20 行之后）插入：

```python
logger = logging.getLogger("pdf_reader")


def _safe_rmtree(path: Path) -> None:
    try:
        shutil.rmtree(path, ignore_errors=True)
    except Exception:
        logger.debug("failed to clean up temp dir %s", path)
```

- [x] **Step 3：替换 GenerateContext 数据类**

将 `sse_stream.py` 原第 23-32 行替换为：

```python
@dataclass
class GenerateContext:
    settings: SettingsModel
    replace_page: Callable[[str], None]
    glossary_cache_path: Path | None
    page: int
    glossary_paths: list[str] | None
    cache_dir: Path
    extract_page: Callable[[int, Path, Callable], Path]
```

- [x] **Step 4：替换 generate() 函数体**

将 `sse_stream.py` 原第 65-115 行（`def generate` 完整函数）替换为：

```python
def generate(ctx: GenerateContext) -> Iterator[str]:
    tmpdir = Path(tempfile.mkdtemp())
    output_dir = Path(tempfile.mkdtemp(dir=str(ctx.cache_dir)))
    ctx.settings.translation.output = str(output_dir)
    try:
        with debug_trace.debug_session(ctx.glossary_cache_path, ctx.page):
            debug_trace.log_step("submit translate page %d", ctx.page)

            translate_start = time.time()
            translate_result = None
            token_usage_finish = None

            single_page_pdf = ctx.extract_page(
                ctx.page, tmpdir, pdf_extraction.extract_single_page
            )

            for evt in run_translation(ctx.settings, str(single_page_pdf)):
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

            finish_translation(
                translate_result,
                ctx.replace_page,
                ctx.glossary_cache_path,
            )

            yield "data: " + json.dumps({
                "type": "progress", "progress": 100,
                "stage": "finish", "stage_current": 0, "stage_total": 0,
            }) + "\n\n"
            yield f"data: {json.dumps({'type': 'finish', 'progress': 100})}\n\n"

    except TranslationError as e:
        yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
    except Exception as e:
        logging.getLogger("pdf_reader").warning("translate_page generate error", exc_info=True)
        yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
    finally:
        _safe_rmtree(tmpdir)
        _safe_rmtree(output_dir)
```

**注意：** 第 4 行 `ctx.settings.translation.output = str(output_dir)` 是必要的——因为 output_dir 在 generate() 内部创建，必须告知 pdf2zh 翻译引擎输出位置。`build_settings` 的 `single_page_pdf` 参数（第一个位置参数）实际上在函数体内未被使用（详见 `translation_settings.py:14-51`），因此 routes.py 中不再传 pdf 路径无副作用。

- [x] **Step 5：运行现有测试确认无回归**

```bash
pytest tests/test_sse_stream.py -q
```

预期：部分测试因 GenerateContext 签名变更和 generate 行为变更而失败（将在任务 7 中修复）。

- [x] **Step 6：提交**

```bash
git add sse_stream.py
git commit -m "feat(sse_stream): wrap generate in try/finally, delegate extraction via ctx callable"
```

---

### 任务 3：finish_translation 移除 tmpdir/output_dir 参数和 rmtree 调用

**文件：**
- 修改：`translation_lifecycle.py:1-42`

**接口：**
- 消费：无
- 产出：`finish_translation(translate_result, replace_page, glossary_cache_path)` 新签名

**描述：** 从 `finish_translation` 移除 `tmpdir: Path` 和 `output_dir: str` 参数以及末尾两行 `shutil.rmtree` 调用。清理职责已收敛到 `generate()` 的 finally 块。同时移除不再需要的 `import shutil`。

- [x] **Step 1：修改 finish_translation 函数签名和函数体**

将 `translation_lifecycle.py` 第 1-42 行替换为：

```python
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import debug_trace
from glossary_service import merge_after_translate

logger = logging.getLogger("pdf_reader")


def finish_translation(
    translate_result: Any,
    replace_page: Callable[[str], None],
    glossary_cache_path: Path | None,
) -> None:
    translated_pdf = translate_result.mono_pdf_path
    if translated_pdf is None and translate_result.dual_pdf_path is not None:
        translated_pdf = translate_result.dual_pdf_path

    if translated_pdf is not None:
        replace_page(str(translated_pdf))

    cumulative_glossary_file: Path | None = None
    if glossary_cache_path is not None:
        cumulative_glossary_file = glossary_cache_path / "cumulative_glossary.csv"
    merge_start = time.time()
    merge_after_translate(
        cumulative_glossary_file,
        translate_result.auto_extracted_glossary_path,
    )
    elapsed = time.time() - merge_start
    debug_trace.log_glossary_merge(
        "merge_done", page=-1, elapsed=f"{elapsed:.2f}"
    )
```

关键变更：
- 移除 `import shutil`（第 2 行原 import）
- 移除参数 `tmpdir: Path` 和 `output_dir: str`
- 移除末尾 `shutil.rmtree(tmpdir, ignore_errors=True)` 和 `shutil.rmtree(output_dir, ignore_errors=True)` 两行

- [x] **Step 2：提交**

```bash
git add translation_lifecycle.py
git commit -m "refactor(translation_lifecycle): remove tmpdir/output_dir cleanup, now in generate() finally"
```

---

### 任务 4：routes.py 移除目录创建和裸 state.left_doc 访问

**文件：**
- 修改：`routes.py:1-23`（import 区域）、`routes.py:80-113`（translate_page 函数）

**接口：**
- 消费：任务 1 的 `AppState.extract_page`、任务 2 的 `GenerateContext` 新字段
- 产出：`translate_page()` 简化为校验 + 构建 GenerateContext + 返回 Response

**描述：** 移除 `tmpdir`/`output_dir` 创建、移除 `pdf_extraction.extract_single_page(state.left_doc, page, tmpdir)` 调用、移除裸 `state.left_doc` 属性访问（改为通过 `state.page_count` 间接使用但保留 page_count 属性的 guard 逻辑）。`GenerateContext` 构造改为传入 `page`、`cache_dir`、`extract_page` lambda。

- [x] **Step 1：更新 import 区域——移除不再需要的 import**

将 `routes.py` 第 1-23 行替换为：

```python
import io
import os

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
import glossary_service
import sse_stream
from file_hash import sha256
from pdf_renderer import render_page
from translation_settings import build_settings
```

（移除 `import tempfile`、`import pdf_extraction`、`from pathlib import Path`——Path 在本文件其他地方未使用，`tempfile` 不再需要，`pdf_extraction` 不再需要）

- [x] **Step 2：替换 translate_page 函数**

将 `routes.py` 第 80-113 行替换为：

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

    glossary_paths = glossary_service.resolve_glossary_paths(state.glossary_cache_path)
    settings = build_settings(
        "", user_prompt,
        glossary_paths=glossary_paths,
    )
    ctx = sse_stream.GenerateContext(
        settings=settings,
        replace_page=lambda path: state.replace_page(path, page),
        glossary_cache_path=state.glossary_cache_path,
        page=page,
        glossary_paths=glossary_paths,
        cache_dir=config.CACHE_DIR,
        extract_page=lambda page, tmpdir, func: state.extract_page(page, tmpdir, func),
    )
    return Response(
        stream_with_context(sse_stream.generate(ctx)),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

**注意：** `build_settings("", user_prompt, glossary_paths=glossary_paths)` — 第一个参数传空字符串 `""`。原因：
1. `translation_settings.py` 中 `single_page_pdf` 参数在函数体内未被使用（死代码参数）
2. `output_dir` 不传——因为 output_dir 现在在 `generate()` 内部创建，并通过 `ctx.settings.translation.output = str(output_dir)` 设置
3. 之前 `state.left_doc.page_count` 调用在第 85 行用于范围校验——`state.page_count` 已经是 `AppState` 的 property，它直接返回 `self._page_count`（锁外读取但这是打开 PDF 时设置的不可变值），保留不变。原 `state.left_doc` 在第 83 行的 `None` 检查也保留不变（通过 property 访问，无需锁——仅 null check）。

- [x] **Step 3：提交**

```bash
git add routes.py
git commit -m "refactor(routes): delegate extraction and cleanup to generate(), remove bare state.left_doc access"
```

---

### 任务 5：测试——AppState.extract_page 单元测试

**文件：**
- 修改：`tests/test_state.py`（末尾追加）

**接口：**
- 消费：任务 1 的 `AppState.extract_page`
- 产出：两个新测试函数

**描述：** 新增两个测试：（1）验证 extract_page 正常提取页面；（2）验证 extract_page 在锁内执行（通过 mock 断言）。

- [x] **Step 1：在 test_state.py 末尾追加测试**

在 `tests/test_state.py` 文件末尾追加：

```python
def test_extract_page_normal(app_state, sample_pdf, tmp_path):
    from file_hash import sha256 as sha256_func
    import pdf_extraction

    app_state.open_pdf(str(sample_pdf), sha256_func)

    extract_tmpdir = tmp_path / "extract"
    extract_tmpdir.mkdir()
    result = app_state.extract_page(0, extract_tmpdir, pdf_extraction.extract_single_page)

    assert result == extract_tmpdir / "page.pdf"
    assert result.exists()


def test_extract_page_under_lock(app_state, sample_pdf, tmp_path):
    from file_hash import sha256 as sha256_func
    import pdf_extraction

    app_state.open_pdf(str(sample_pdf), sha256_func)

    lock_held_during_extract = [False]

    def track_lock_extract_func(doc, page, tmpdir):
        lock_held_during_extract[0] = app_state._lock.locked()
        return pdf_extraction.extract_single_page(doc, page, tmpdir)

    extract_tmpdir = tmp_path / "extract"
    extract_tmpdir.mkdir()
    app_state.extract_page(0, extract_tmpdir, track_lock_extract_func)

    assert lock_held_during_extract[0] is True


def test_extract_page_no_document_raises(app_state, tmp_path):
    extract_tmpdir = tmp_path / "extract"
    extract_tmpdir.mkdir()

    import pdf_extraction
    with pytest.raises(ValueError, match="no document opened"):
        app_state.extract_page(0, extract_tmpdir, pdf_extraction.extract_single_page)
```

**注意：** `test_extract_page_no_document_raises` 需要 `import pytest`。检查 `test_state.py` 顶部已有 `import pytest` 吗？没有——原文件未导入 pytest。需要添加。

- [x] **Step 2：在 test_state.py 顶部添加 import pytest**

`tests/test_state.py` 第 1 行后已有 import。将第 1-7 行替换为：

```python
import threading
import time
from pathlib import Path

import pymupdf
import pytest

from state import AppState
```

- [x] **Step 3：运行新测试验证**

```bash
pytest tests/test_state.py::test_extract_page_normal tests/test_state.py::test_extract_page_under_lock tests/test_state.py::test_extract_page_no_document_raises -v
```

预期：3 PASS。

- [x] **Step 4：提交**

```bash
git add tests/test_state.py
git commit -m "test(state): add extract_page unit tests"
```

---

### 任务 6：测试——extract 与 render 并发线程安全测试

**文件：**
- 修改：`tests/test_state.py`（在任务 5 的测试之后追加）

**接口：**
- 消费：任务 1 的 `AppState.extract_page`、`AppState.render_page`
- 产出：一个并发测试函数

**描述：** 验证 extract_page 与 render_page 并发调用时通过锁正确串行化，无 data race。

- [x] **Step 1：在 test_state.py 末尾追加并发测试**

在 `tests/test_state.py` 文件末尾追加：

```python
def test_concurrent_extract_and_render_serialized(app_state, sample_pdf, tmp_path):
    import threading
    import time
    from file_hash import sha256 as sha256_func
    import pdf_extraction
    from pdf_renderer import render_page

    app_state.open_pdf(str(sample_pdf), sha256_func)

    extract_tmpdir = tmp_path / "extract"
    extract_tmpdir.mkdir()

    extract_started = threading.Event()
    extract_can_finish = threading.Event()
    render_done = threading.Event()

    def slow_extract_func(doc, page, tmpdir):
        extract_started.set()
        extract_can_finish.wait(timeout=5)
        return pdf_extraction.extract_single_page(doc, page, tmpdir)

    extract_result = [None]
    extract_error = [None]
    render_result = [None]
    render_error = [None]

    def run_extract():
        try:
            extract_result[0] = app_state.extract_page(
                0, extract_tmpdir, slow_extract_func
            )
        except Exception as e:
            extract_error[0] = e

    def run_render():
        extract_started.wait(timeout=5)
        try:
            render_result[0] = app_state.render_page(
                "left", 0, render_page, 72
            )
        except Exception as e:
            render_error[0] = e
        render_done.set()

    t1 = threading.Thread(target=run_extract)
    t2 = threading.Thread(target=run_render)
    t1.start()
    t2.start()

    # Give extract time to acquire the lock, render should block waiting
    time.sleep(0.2)
    extract_can_finish.set()

    t1.join(timeout=10)
    t2.join(timeout=10)

    assert extract_error[0] is None, f"extract crashed: {extract_error[0]}"
    assert render_error[0] is None, f"render crashed: {render_error[0]}"
    assert extract_result[0] is not None
    assert render_result[0] is not None
    assert isinstance(render_result[0], bytes)
    assert len(render_result[0]) > 0
```

- [x] **Step 2：运行新测试验证**

```bash
pytest tests/test_state.py::test_concurrent_extract_and_render_serialized -v
```

预期：PASS。

- [x] **Step 3：提交**

```bash
git add tests/test_state.py
git commit -m "test(state): add concurrent extract+render serialization test"
```

---

### 任务 7：测试——generate() 清理测试 + 适配现有测试

**文件：**
- 修改：`tests/test_sse_stream.py`（重大修改）

**接口：**
- 消费：任务 2 的 `GenerateContext` 新字段、任务 2 的 `generate()` 新行为
- 产出：清理测试 + 适配后的现有测试

**描述：** 新增 4 个清理测试（error 早退、无 translate_result 早退、GeneratorExit、成功路径）；适配所有现有测试使其使用新的 GenerateContext 签名和 generate() 行为。

- [x] **Step 1：替换 test_sse_stream.py 的全部内容**

将 `tests/test_sse_stream.py` 全部替换为：

```python
import csv
import json
import tempfile
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sse_stream import GenerateContext, format_sse_event, generate

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


# --- 辅助函数：构建新签名的 GenerateContext ---

def _make_ctx(settings, replace_page, glossary_cache_path, page, glossary_paths, cache_dir, extract_page=None):
    if extract_page is None:
        extract_page = MagicMock(return_value=Path("/fake/page.pdf"))
    return GenerateContext(
        settings=settings,
        replace_page=replace_page,
        glossary_cache_path=glossary_cache_path,
        page=page,
        glossary_paths=glossary_paths,
        cache_dir=cache_dir,
        extract_page=extract_page,
    )


# --- 黄金样本测试（不变）---

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


# --- format_sse_event 测试（不变）---

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


# --- generate() 完整流程测试 ---

def test_generate_full_flow_byte_level_compatible(tmp_path):
    mock_result = MagicMock()
    mock_result.mono_pdf_path = str(tmp_path / "translated.pdf")
    mock_result.dual_pdf_path = None
    mock_result.auto_extracted_glossary_path = None

    events = [
        {"type": "progress_start", "stage": "layout_analysis", "overall_progress": 0,
         "stage_current": 0, "stage_total": 0},
        {"type": "progress_update", "stage": "translating", "overall_progress": 50,
         "stage_current": 2, "stage_total": 5},
        {"type": "finish", "stage": "generating_pdf", "translate_result": mock_result,
         "token_usage": {}},
    ]

    replace_page = MagicMock()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    settings = MagicMock()
    settings.translation.output = None

    extract_page = MagicMock(return_value=tmp_path / "page.pdf")

    ctx = _make_ctx(
        settings=settings,
        replace_page=replace_page,
        glossary_cache_path=None,
        page=0,
        glossary_paths=None,
        cache_dir=cache_dir,
        extract_page=extract_page,
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
    replace_page.assert_called_once_with(str(tmp_path / "translated.pdf"))


def test_generate_error_event_stops_stream(tmp_path):
    events = [
        {"type": "progress_start", "stage": "layout_analysis"},
        {"type": "error", "error": "test error"},
    ]

    replace_page = MagicMock()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    settings = MagicMock()
    settings.translation.output = None

    extract_page = MagicMock(return_value=tmp_path / "page.pdf")

    ctx = _make_ctx(
        settings=settings,
        replace_page=replace_page,
        glossary_cache_path=None,
        page=0,
        glossary_paths=None,
        cache_dir=cache_dir,
        extract_page=extract_page,
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

    replace_page = MagicMock()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    settings = MagicMock()
    settings.translation.output = None

    extract_page = MagicMock(return_value=tmp_path / "page.pdf")

    ctx = _make_ctx(
        settings=settings,
        replace_page=replace_page,
        glossary_cache_path=None,
        page=0,
        glossary_paths=None,
        cache_dir=cache_dir,
        extract_page=extract_page,
    )

    def error_iter() -> Iterator[dict]:
        yield from events
        raise TranslationError("thread crashed")

    with patch("sse_stream.run_translation", return_value=error_iter()):
        with patch("sse_stream.debug_trace"):
            result = list(generate(ctx))

    assert len(result) == 2
    assert result[0] == EXPECTED_PROGRESS_START_SSE
    assert "error" in result[1]
    assert "thread crashed" in result[1]


def test_generate_merges_glossary_with_str_auto_path(tmp_path):
    glossary_cache = tmp_path / "cache_glossary"
    glossary_cache.mkdir()
    cumulative_file = glossary_cache / "cumulative_glossary.csv"
    with open(cumulative_file, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["source", "target"])
        w.writerow(["alpha", "\u963f\u5c14\u6cd5"])

    auto_file = glossary_cache / "auto_extracted.csv"
    with open(auto_file, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["source", "target"])
        w.writerow(["beta", "\u8d1d\u5854"])

    mock_result = MagicMock()
    mock_result.mono_pdf_path = str(tmp_path / "translated.pdf")
    mock_result.dual_pdf_path = None
    mock_result.auto_extracted_glossary_path = str(auto_file)

    events = [
        {"type": "progress_start", "stage": "layout_analysis", "overall_progress": 0,
         "stage_current": 0, "stage_total": 0},
        {"type": "finish", "stage": "generating_pdf", "translate_result": mock_result,
         "token_usage": {}},
    ]

    replace_page = MagicMock()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    settings = MagicMock()
    settings.translation.output = None

    extract_page = MagicMock(return_value=tmp_path / "page.pdf")

    ctx = _make_ctx(
        settings=settings,
        replace_page=replace_page,
        glossary_cache_path=glossary_cache,
        page=0,
        glossary_paths=None,
        cache_dir=cache_dir,
        extract_page=extract_page,
    )

    with patch("sse_stream.run_translation", return_value=iter(events)):
        with patch("sse_stream.debug_trace"):
            list(generate(ctx))

    with open(cumulative_file, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = {row["source"]: row["target"] for row in reader}

    assert rows.get("alpha") == "\u963f\u5c14\u6cd5"
    assert rows.get("beta") == "\u8d1d\u5854"


def test_generate_passes_through_keepalive_empty_string(tmp_path):
    mock_result = MagicMock()
    mock_result.mono_pdf_path = str(tmp_path / "translated.pdf")
    mock_result.dual_pdf_path = None
    mock_result.auto_extracted_glossary_path = None

    events = [
        "",
        {"type": "finish", "stage": "generating_pdf", "translate_result": mock_result,
         "token_usage": {}},
    ]

    replace_page = MagicMock()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    settings = MagicMock()
    settings.translation.output = None

    extract_page = MagicMock(return_value=tmp_path / "page.pdf")

    ctx = _make_ctx(
        settings=settings,
        replace_page=replace_page,
        glossary_cache_path=None,
        page=0,
        glossary_paths=None,
        cache_dir=cache_dir,
        extract_page=extract_page,
    )

    with patch("sse_stream.run_translation", return_value=iter(events)):
        with patch("sse_stream.debug_trace"):
            result = list(generate(ctx))

    assert result[0] == ""


# --- 新增：清理测试 ---

def test_generate_cleans_up_on_error_event(tmp_path):
    """3.1: error 事件早退后 tmpdir/output_dir 被删除"""
    events = [
        {"type": "progress_start", "stage": "layout_analysis"},
        {"type": "error", "error": "test error"},
    ]

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    cache_dir_str = str(cache_dir)

    settings = MagicMock()
    settings.translation.output = None

    extract_page = MagicMock(return_value=tmp_path / "page.pdf")

    ctx = _make_ctx(
        settings=settings,
        replace_page=MagicMock(),
        glossary_cache_path=None,
        page=0,
        glossary_paths=None,
        cache_dir=cache_dir,
        extract_page=extract_page,
    )

    with patch("sse_stream.run_translation", return_value=iter(events)):
        with patch("sse_stream.debug_trace"):
            result = list(generate(ctx))

    assert len(result) == 2
    assert "error" in result[1]

    # 验证 cache_dir 下无残留 output_dir
    remaining_dirs = [d for d in cache_dir.iterdir() if d.is_dir()]
    assert len(remaining_dirs) == 0, f"output_dir 残留: {remaining_dirs}"


def test_generate_cleans_up_on_no_translate_result(tmp_path):
    """3.2: 无 translate_result 早退后 tmpdir/output_dir 被删除"""
    events: list = []

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    settings = MagicMock()
    settings.translation.output = None

    extract_page = MagicMock(return_value=tmp_path / "page.pdf")

    ctx = _make_ctx(
        settings=settings,
        replace_page=MagicMock(),
        glossary_cache_path=None,
        page=0,
        glossary_paths=None,
        cache_dir=cache_dir,
        extract_page=extract_page,
    )

    with patch("sse_stream.run_translation", return_value=iter(events)):
        with patch("sse_stream.debug_trace"):
            result = list(generate(ctx))

    assert len(result) == 1
    assert "no translation result" in result[0]

    remaining_dirs = [d for d in cache_dir.iterdir() if d.is_dir()]
    assert len(remaining_dirs) == 0, f"output_dir 残留: {remaining_dirs}"


def test_generate_cleans_up_on_generator_close(tmp_path):
    """3.3: generator.close() → GeneratorExit → tmpdir/output_dir 被删除"""
    mock_result = MagicMock()
    mock_result.mono_pdf_path = str(tmp_path / "translated.pdf")
    mock_result.dual_pdf_path = None
    mock_result.auto_extracted_glossary_path = None

    events = [
        {"type": "progress_start", "stage": "layout_analysis", "overall_progress": 0,
         "stage_current": 0, "stage_total": 0},
        {"type": "finish", "stage": "generating_pdf", "translate_result": mock_result,
         "token_usage": {}},
    ]

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    settings = MagicMock()
    settings.translation.output = None

    extract_page = MagicMock(return_value=tmp_path / "page.pdf")

    ctx = _make_ctx(
        settings=settings,
        replace_page=MagicMock(),
        glossary_cache_path=None,
        page=0,
        glossary_paths=None,
        cache_dir=cache_dir,
        extract_page=extract_page,
    )

    with patch("sse_stream.run_translation", return_value=iter(events)):
        with patch("sse_stream.debug_trace"):
            gen = generate(ctx)
            # 消费第一个事件后立即关闭（模拟客户端断连）
            first = next(gen)
            assert first == EXPECTED_PROGRESS_START_SSE
            gen.close()

    # 关闭后检查 cleanup 是否执行
    remaining_dirs = [d for d in cache_dir.iterdir() if d.is_dir()]
    assert len(remaining_dirs) == 0, f"close() 后 output_dir 残留: {remaining_dirs}"


def test_generate_cleans_up_on_success(tmp_path):
    """3.4: 成功路径清理只发生一次且目录被删"""
    mock_result = MagicMock()
    mock_result.mono_pdf_path = str(tmp_path / "translated.pdf")
    mock_result.dual_pdf_path = None
    mock_result.auto_extracted_glossary_path = None

    events = [
        {"type": "progress_start", "stage": "layout_analysis", "overall_progress": 0,
         "stage_current": 0, "stage_total": 0},
        {"type": "finish", "stage": "generating_pdf", "translate_result": mock_result,
         "token_usage": {}},
    ]

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    settings = MagicMock()
    settings.translation.output = None

    extract_page = MagicMock(return_value=tmp_path / "page.pdf")

    ctx = _make_ctx(
        settings=settings,
        replace_page=MagicMock(),
        glossary_cache_path=None,
        page=0,
        glossary_paths=None,
        cache_dir=cache_dir,
        extract_page=extract_page,
    )

    with patch("sse_stream.run_translation", return_value=iter(events)):
        with patch("sse_stream.debug_trace"):
            result = list(generate(ctx))

    assert len(result) >= 3  # progress_start, finish_progress, final_progress, final_finish
    assert "finish" in result[-1]

    remaining_dirs = [d for d in cache_dir.iterdir() if d.is_dir()]
    assert len(remaining_dirs) == 0, f"成功路径后 output_dir 残留: {remaining_dirs}"


def test_generate_cleans_up_on_exception(tmp_path):
    """generate 中意外异常后 tmpdir/output_dir 被删除"""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    settings = MagicMock()
    settings.translation.output = None

    extract_page = MagicMock(return_value=tmp_path / "page.pdf")

    ctx = _make_ctx(
        settings=settings,
        replace_page=MagicMock(),
        glossary_cache_path=None,
        page=0,
        glossary_paths=None,
        cache_dir=cache_dir,
        extract_page=extract_page,
    )

    def crash_iter() -> Iterator[dict]:
        yield {"type": "progress_start", "stage": "layout_analysis"}
        raise RuntimeError("unexpected crash")

    with patch("sse_stream.run_translation", return_value=crash_iter()):
        with patch("sse_stream.debug_trace"):
            result = list(generate(ctx))

    assert len(result) == 2
    assert "error" in result[1]
    assert "unexpected crash" in result[1]

    remaining_dirs = [d for d in cache_dir.iterdir() if d.is_dir()]
    assert len(remaining_dirs) == 0, f"异常后 output_dir 残留: {remaining_dirs}"
```

- [x] **Step 2：运行全部 sse_stream 测试**

```bash
pytest tests/test_sse_stream.py -v
```

预期：全部 PASS（约 18 个测试）。

- [x] **Step 3：提交**

```bash
git add tests/test_sse_stream.py
git commit -m "test(sse_stream): add cleanup tests and adapt to new GenerateContext signature"
```

---

### 任务 8：最终验证——全量测试 + lint

**文件：**
- 无新建/修改（仅运行命令）

**接口：**
- 消费：所有前述任务的产出

**描述：** 运行全量测试套件和 lint，确保无回归。

- [x] **Step 1：运行全量测试**

```bash
pytest -q
```

预期：全部 PASS。

- [x] **Step 2：运行 ruff lint**

```bash
ruff check .
```

预期：无错误。

- [x] **Step 3：运行 ruff format 检查**

```bash
ruff format --check .
```

预期：格式正确（或仅有已存在的格式差异）。

- [x] **Step 4：提交（如有 lint/format 修正）**

```bash
git add -u
git commit -m "chore: apply lint and format fixes after concurrency cleanup changes"
```

---

### 任务 9：手动验证（可选）

**描述：** 启动应用进行手动冒烟测试，验证实际运行环境中无 tempdir 泄漏和并发问题。

- [x] **Step 1：启动应用，打开一个 PDF**

```bash
python app.py
```

- [x] **Step 2：触发一次翻译后中断（如停止浏览器请求），检查 CACHE_DIR 下无残留目录**

```bash
Get-ChildItem -LiteralPath "cache" -Directory
```

预期：仅有以 pdf hash 命名的缓存子目录，无临时目录残留。

- [x] **Step 3：并发测试——翻译某页同时滚动渲染其他页，确认无错误日志**

观察应用日志，预期无 pymupdf 相关异常。
```
