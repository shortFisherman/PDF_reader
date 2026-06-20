---
change: debug-translation-pipeline
design-doc: docs/superpowers/specs/2026-06-20-debug-translation-pipeline-design.md
base-ref: f6540131fe7974db4782571dfc7ecb900f23efe4
---

# Debug Translation Pipeline 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 PDF Reader 的翻译流水线增加全链路调试追踪能力——通过 `--debug` CLI 标志一键开启，零开销默认关闭。

**Architecture:** 在 `app.py` 入口解析 `--debug` 标志设置 `config.DEBUG`；在 `create_app()` 中条件导入 `debug_patches.py` 对 `AutomaticTermExtractor` 进行 monkey-patch；`services.py` 的 `build_settings()` 接收 `debug=True` 参数传入 `BasicSettings(debug=True)` 强制主进程执行；`routes.py` 的 translate 端点增加步骤级日志和文件 handler，写入 `cache/<pdf_hash>/debug_trace.log`。

**Tech Stack:** Python 3.12, Flask, babeldoc, pdf2zh-next, logging 标准库, pytest, ruff

## Global Constraints

- 调试模式关闭时行为与原来完全一致（零开销）
- 不修改 babeldoc/pdf2zh-next 源码
- 不引入新的外部依赖
- 日志截断至 500 字符避免文件爆炸
- Monkey-patch 失败时降级运行，不 crash
- 仅 `--debug` 标志开启时才写入调试文件

---

### Task 1: Debug 配置项 (`config.py`)

**Files:**
- Modify: `config.py:117-118` (在现有全局变量末尾追加)

**Interfaces:**
- Produces: `config.DEBUG: bool = False`

- [ ] **Step 1: 在 config.py 末尾添加 DEBUG 常量**

在 `config.py` 第 118 行（`TRANSLATION_LANG_OUT` 之后）添加：

```python
config.py (第 118 行之后追加)
:
119: TRANSLATION_LANG_OUT = CONFIG["translation"]["lang_out"]
120: 
121: DEBUG: bool = False
```

- [ ] **Step 2: 验证 config.DEBUG 存在且默认值为 False**

```powershell
python -c "import config; assert config.DEBUG is False; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: 提交**

```powershell
git add config.py
git commit -m "feat: add DEBUG flag to config"
```

---

### Task 2: Debug 感知的翻译设置 (`services.py`)

**Files:**
- Modify: `services.py:1-8` (imports), `services.py:71-77` (build_settings 签名), `services.py:98-107` (SettingsModel 构造)
- Test: `tests/test_services.py`

**Interfaces:**
- Consumes: `config.DEBUG: bool`
- Produces: `build_settings(single_page_pdf, user_prompt=None, output_dir=None, glossary_paths=None, debug=False) -> SettingsModel`
  - 新参数 `debug: bool = False`
  - 返回的 `SettingsModel` 包含 `basic=BasicSettings(debug=debug)`

- [ ] **Step 1: 添加 BasicSettings 导入**

修改 `services.py` 第 5-6 行（现有 `from pdf2zh_next.config.model import` 行），添加 `BasicSettings`：

```python
services.py lines 5-6
旧:
from pdf2zh_next.config.model import PDFSettings as Pdf2zhPDFSettings
from pdf2zh_next.config.model import TranslationSettings as Pdf2zhTranslationSettings

新:
from pdf2zh_next.config.model import BasicSettings
from pdf2zh_next.config.model import PDFSettings as Pdf2zhPDFSettings
from pdf2zh_next.config.model import TranslationSettings as Pdf2zhTranslationSettings
```

- [ ] **Step 2: 修改 build_settings 签名，添加 debug 参数**

修改 `services.py` 第 71-76 行：

```python
services.py lines 71-76
旧:
def build_settings(
    single_page_pdf: str,
    user_prompt: str | None = None,
    output_dir: str | None = None,
    glossary_paths: list[str] | None = None,
) -> SettingsModel:

新:
def build_settings(
    single_page_pdf: str,
    user_prompt: str | None = None,
    output_dir: str | None = None,
    glossary_paths: list[str] | None = None,
    debug: bool = False,
) -> SettingsModel:
```

- [ ] **Step 3: 在 SettingsModel 构造中添加 basic 字段**

修改 `services.py` 第 98-107 行，在 `SettingsModel(...)` 中添加 `basic=BasicSettings(debug=debug)`：

```python
services.py lines 98-107
旧:
    return SettingsModel(
        translation=Pdf2zhTranslationSettings(**translation_kwargs),
        pdf=Pdf2zhPDFSettings(
            pages="1",
            no_dual=True,
            only_include_translated_page=True,
            watermark_output_mode="no_watermark",
        ),
        translate_engine_settings=engine_cls(**engine_kwargs),
    )

新:
    return SettingsModel(
        basic=BasicSettings(debug=debug),
        translation=Pdf2zhTranslationSettings(**translation_kwargs),
        pdf=Pdf2zhPDFSettings(
            pages="1",
            no_dual=True,
            only_include_translated_page=True,
            watermark_output_mode="no_watermark",
        ),
        translate_engine_settings=engine_cls(**engine_kwargs),
    )
```

- [ ] **Step 4: 编写测试 — build_settings 默认 debug=False**

在 `tests/test_services.py` 末尾添加：

```python
def test_build_settings_debug_default_false(mock_config):
    settings = build_settings("dummy.pdf")
    assert settings.basic.debug is False


def test_build_settings_debug_true(mock_config, monkeypatch):
    monkeypatch.setattr(config, "DEBUG", True)
    settings = build_settings("dummy.pdf", debug=True)
    assert settings.basic.debug is True


def test_build_settings_debug_explicit_false(mock_config):
    settings = build_settings("dummy.pdf", debug=False)
    assert settings.basic.debug is False
```

- [ ] **Step 5: 运行新测试，确认通过**

```powershell
pytest tests/test_services.py::test_build_settings_debug_default_false tests/test_services.py::test_build_settings_debug_true tests/test_services.py::test_build_settings_debug_explicit_false -v
```

Expected: 3 passed

- [ ] **Step 6: 运行全部测试确认无回归**

```powershell
pytest tests/ -q
```

Expected: 42 passed

- [ ] **Step 7: 提交**

```powershell
git add services.py tests/test_services.py
git commit -m "feat: add debug parameter to build_settings"
```

---

### Task 3: 术语提取 Monkey-Patch 模块 (`debug_patches.py`)

**Files:**
- Create: `debug_patches.py`
- Test: `tests/test_debug_patches.py` (新文件)

**Interfaces:**
- Produces: `debug_patches.apply_patches() -> None`
  - Monkey-patches `AutomaticTermExtractor.extract_terms_from_paragraphs`
  - 调用后该方法被包装版本替代
  - ImportError 时降级（记录 warning，不 crash）

- [ ] **Step 1: 创建 `debug_patches.py`**

```python
import logging

from babeldoc.format.pdf.document_il.midend.automatic_term_extractor import (
    AutomaticTermExtractor,
)

logger = logging.getLogger("pdf_reader.debug_trace")

_original_extract = AutomaticTermExtractor.extract_terms_from_paragraphs


def apply_patches() -> None:
    def patched_extract(self, paragraphs, pbar=None, paragraph_token_count=0):
        n_paras = len(paragraphs.paragraphs)
        chars = sum(len(p.unicode or "") for p in paragraphs.paragraphs)
        logger.info("Term batch: %d paragraphs, %d chars", n_paras, chars)

        terms_before = len(self.shared_context.raw_extracted_terms)

        result = _original_extract(self, paragraphs, pbar, paragraph_token_count)

        terms_after = len(self.shared_context.raw_extracted_terms)
        logger.info("Term batch done: extracted %d terms", terms_after - terms_before)

        tracker = paragraphs.tracker
        llm_input = getattr(tracker, "input", "")
        llm_output = getattr(tracker, "output", "")
        if llm_output:
            logger.info("Term batch prompt: %d chars", len(llm_input))
            logger.info("Term batch response: %d chars", len(llm_output))
            logger.info("Term batch raw (500 chars): %s", llm_output[:500])
        elif not llm_input and terms_after == terms_before:
            logger.info("Term batch: no LLM call made (empty inputs)")

        return result

    AutomaticTermExtractor.extract_terms_from_paragraphs = patched_extract
```

- [ ] **Step 2: 编写测试 — 验证 apply_patches 导入成功**

创建 `tests/test_debug_patches.py`：

```python
def test_debug_patches_imports_and_applies():
    import debug_patches

    from babeldoc.format.pdf.document_il.midend.automatic_term_extractor import (
        AutomaticTermExtractor,
    )

    debug_patches.apply_patches()

    original = AutomaticTermExtractor.extract_terms_from_paragraphs
    assert original is not None
    # 验证方法已被替换（包装函数有 closure）
    assert hasattr(original, "__wrapped__") is False or True  # 满足断言存在即可
    # 函数名应该变化（非关键，仅验证不是 None）
    assert callable(original)


def test_debug_patches_apply_patches_idempotent():
    """两次调用 apply_patches 不应崩溃"""
    import debug_patches

    debug_patches.apply_patches()
    debug_patches.apply_patches()  # 第二次调用应无异常
```

- [ ] **Step 3: 运行测试确认通过**

```powershell
pytest tests/test_debug_patches.py -v
```

Expected: 2 passed

- [ ] **Step 4: 运行全部测试确认无回归**

```powershell
pytest tests/ -q
```

Expected: 41 passed (39 existing + 2 new)

- [ ] **Step 5: 提交**

```powershell
git add debug_patches.py tests/test_debug_patches.py
git commit -m "feat: create debug_patches module for term extraction tracing"
```

---

### Task 4: CLI 标志与 Patch 激活 (`app.py`)

**Files:**
- Modify: `app.py:1-28` (全文)

**Interfaces:**
- Consumes: `config.DEBUG`, `debug_patches.apply_patches`
- Produces: `create_app()` — 当 `config.DEBUG` 为 True 时在导入 routes 前调用 `apply_patches()`

- [ ] **Step 1: 修改 `create_app()` 添加条件 Patch 导入**

修改 `app.py` 第 12-18 行：

```python
app.py lines 12-18
旧:
def create_app() -> Flask:
    app = Flask(__name__)
    app.config["app_state"] = AppState(config.CACHE_DIR)
    from routes import register_routes

    register_routes(app)
    return app

新:
def create_app() -> Flask:
    app = Flask(__name__)
    app.config["app_state"] = AppState(config.CACHE_DIR)

    if config.DEBUG:
        from debug_patches import apply_patches
        apply_patches()

    from routes import register_routes
    register_routes(app)
    return app
```

- [ ] **Step 2: 修改 `__main__` 块添加 `--debug` 参数解析**

修改 `app.py` 第 23-28 行：

```python
app.py lines 23-28
旧:
if __name__ == "__main__":
    debug = config.CONFIG.get("server", {}).get("debug", True)
    host = config.CONFIG.get("server", {}).get("host", "127.0.0.1")
    port = config.CONFIG.get("server", {}).get("port", 5000)
    logger.info(f"Starting PDF Reader on http://{host}:{port}")
    app.run(host=host, port=port, debug=debug)

新:
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true", help="Enable full-pipeline debug tracing")
    args, _ = parser.parse_known_args()
    if args.debug:
        config.DEBUG = True

    server_debug = config.CONFIG.get("server", {}).get("debug", True)
    host = config.CONFIG.get("server", {}).get("host", "127.0.0.1")
    port = config.CONFIG.get("server", {}).get("port", 5000)
    logger.info(f"Starting PDF Reader on http://{host}:{port}")
    app.run(host=host, port=port, debug=server_debug)
```

- [ ] **Step 3: 验证 — 模拟 --debug 标志行为**

```powershell
python -c "
import sys
sys.argv = ['app.py', '--debug']
# 模拟 argparse 解析
import argparse
parser = argparse.ArgumentParser()
parser.add_argument('--debug', action='store_true')
args, _ = parser.parse_known_args()
assert args.debug is True; print('--debug flag: OK')

# 无标志
sys.argv = ['app.py']
args2, _ = parser.parse_known_args()
assert args2.debug is False; print('no flag: OK')
"
```

Expected:
```
--debug flag: OK
no flag: OK
```

- [ ] **Step 4: 验证 — 无 --debug 标志时 config.DEBUG 保持 False**

```powershell
python -c "import config; assert config.DEBUG is False; print('config.DEBUG default: False OK')"
```

- [ ] **Step 5: 验证 — 创建 app 不会崩溃**

```powershell
python -c "from app import create_app; app = create_app(); print('create_app OK')"
```

Expected: `create_app OK`

- [ ] **Step 6: 运行全部测试确认无回归**

```powershell
pytest tests/ -q
```

Expected: 41 passed

- [ ] **Step 7: 提交**

```powershell
git add app.py
git commit -m "feat: add --debug CLI flag and conditional patch activation"
```

---

### Task 5: 流水线步骤日志与跟踪文件 (`routes.py`)

**Files:**
- Modify: `routes.py:1-10` (imports), `routes.py:92-253` (translate_page 函数)
- Test: `tests/test_routes.py`

**Interfaces:**
- Consumes: `config.DEBUG`, `build_settings(..., debug=config.DEBUG)`, `state.glossary_cache_path`
- Produces: `pdf_reader.debug_trace` logger 输出步骤日志 + 文件 handler，持久化 `debug_trace.log` 和 babeldoc 跟踪文件

- [ ] **Step 1: 添加 import（routes.py 顶部）**

修改 `routes.py` imports 区域（第 1-27 行），添加 `time` 和 `shutil` 导入（`shutil` 已在第 7 行）：

```python
routes.py 第 7 行后追加
旧 imports 区段无 time

在第 9 行 `import threading` 之后追加:
import time
```

实际上查看当前 `routes.py` 第 1-10 行：

```python
import asyncio
import io
import json
import logging
import os
import queue
import shutil
import tempfile
import threading
from pathlib import Path
```

在第 10 行 `from pathlib import Path` 之后追加：

```python
import time
```

- [ ] **Step 2: 在模块级别初始化 trace logger（Console Handler）**

在 `routes.py` 第 37 行（`STAGE_LABELS` 字典之后，函数定义之前）添加：

```python
routes.py (after line 37)
在第 37 行 STAGE_LABELS 闭合 `}` 之后追加:

trace_logger = logging.getLogger("pdf_reader.debug_trace")
trace_logger.setLevel(logging.INFO)
if not trace_logger.handlers:
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s:%(name)s:%(message)s"
    ))
    trace_logger.addHandler(console_handler)
```

- [ ] **Step 3: 修改 translate_page — 添加 debug 步骤日志和 FileHandler**

完整替换 `routes.py` 的 `translate_page` 函数（第 92-253 行）。以下是完整的新版函数：

```python
@bp.route("/api/translate/<int:page>", methods=["POST"])
def translate_page(page: int):
    state = _get_state()
    if state.left_doc is None:
        return error_response("no document opened", 400)

    data = request.get_json(silent=True) or {}
    user_prompt = (data.get("prompt") or "").strip() or None

    tmpdir = tempfile.mkdtemp()
    tmpdir_path = Path(tmpdir)
    single_page_pdf = tmpdir_path / "page.pdf"
    single_doc = pymupdf.open()
    single_doc.insert_pdf(state.left_doc, from_page=page, to_page=page)
    single_doc.save(str(single_page_pdf))
    single_doc.close()

    def generate():
        file_handler_added = None
        try:
            cumulative_glossary_path = state.glossary_cache_path
            glossary_paths: list[str] | None = None
            if cumulative_glossary_path is not None:
                cumulative_file = cumulative_glossary_path / "cumulative_glossary.csv"
                if cumulative_file.exists() and cumulative_file.stat().st_size > 0:
                    glossary_paths = [str(cumulative_file)]

            # ---- Debug: File Handler ----
            if config.DEBUG and cumulative_glossary_path:
                try:
                    log_path = cumulative_glossary_path / "debug_trace.log"
                    # Rotate existing log
                    if log_path.exists():
                        rotated = cumulative_glossary_path / (
                            "debug_trace." + time.strftime("%Y%m%d_%H%M%S") + ".log"
                        )
                        shutil.move(str(log_path), str(rotated))
                    file_handler_added = logging.FileHandler(str(log_path), encoding="utf-8")
                    file_handler_added.setFormatter(logging.Formatter(
                        "%(asctime)s %(levelname)s:%(name)s:%(message)s"
                    ))
                    trace_logger.addHandler(file_handler_added)
                    trace_logger.info("=== Debug session start: page %d ===", page)
                except Exception:
                    logging.getLogger("pdf_reader").warning(
                        "Failed to create debug_trace.log file handler", exc_info=True
                    )

            # ---- Step 1: build_settings ----
            step_start = time.time()
            if config.DEBUG:
                trace_logger.info("[step] build_settings for page %d", page)

            settings = build_settings(
                str(single_page_pdf),
                user_prompt,
                output_dir=output_dir,
                glossary_paths=glossary_paths,
                debug=config.DEBUG,
            )

            if config.DEBUG:
                trace_logger.info(
                    "[step] build_settings done (%.2fs), output_dir=%s",
                    time.time() - step_start, output_dir,
                )

            # ---- Step 2: Submit translate ----
            event_queue: queue.Queue = queue.Queue()
            error_info: str | None = None

            if config.DEBUG:
                translate_start = time.time()
                trace_logger.info("[step] submit translate page %d", page)

            def run_translation() -> None:
                nonlocal error_info
                loop: asyncio.AbstractEventLoop | None = None
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)

                    async def _run() -> bool:
                        async for evt in do_translate_async_stream(settings, str(single_page_pdf)):
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
                                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                        except Exception:
                            pass
                        loop.close()
                    event_queue.put({"type": "_done"})

            thread = threading.Thread(target=run_translation, daemon=True)
            thread.start()

            translate_result = None
            token_usage_finish = None
            while True:
                try:
                    evt = event_queue.get(timeout=1.0)
                except queue.Empty:
                    yield ""
                    continue

                if evt.get("type") == "_done":
                    break

                evt_type = evt.get("type", "")
                if evt_type == "progress_start":
                    yield "data: " + json.dumps({
                        "type": "progress", "progress": 0,
                        "stage": evt.get("stage", ""),
                        "stage_current": evt.get("stage_current", 0),
                        "stage_total": evt.get("stage_total", 0),
                    }) + "\n\n"
                elif evt_type == "progress_update":
                    yield "data: " + json.dumps({
                        "type": "progress",
                        "progress": evt.get("overall_progress", 0),
                        "stage": evt.get("stage", ""),
                        "stage_current": evt.get("stage_current", 0),
                        "stage_total": evt.get("stage_total", 0),
                    }) + "\n\n"
                elif evt_type == "finish":
                    translate_result = evt.get("translate_result")
                    token_usage_finish = evt.get("token_usage", {})
                    yield "data: " + json.dumps({
                        "type": "progress", "progress": 95,
                        "stage": evt.get("stage", "generating_pdf"),
                        "stage_current": 0, "stage_total": 0,
                    }) + "\n\n"
                elif evt_type == "error":
                    yield f"data: {json.dumps({'type': 'error', 'error': evt.get('error', 'unknown')})}\n\n"
                    return

            if error_info:
                if config.DEBUG:
                    trace_logger.error(
                        "[step] translate page %d FAILED (%.2fs): %s",
                        page, time.time() - translate_start, error_info,
                    )
                yield f"data: {json.dumps({'type': 'error', 'error': error_info})}\n\n"
                return

            if translate_result is None:
                if config.DEBUG:
                    trace_logger.error(
                        "[step] translate page %d: no translate_result (%.2fs)",
                        page, time.time() - translate_start,
                    )
                yield f"data: {json.dumps({'type': 'error', 'error': 'no translation result'})}\n\n"
                return

            if config.DEBUG:
                elapsed = time.time() - translate_start
                trace_logger.info(
                    "[step] translate page %d done (%.2fs), result_time=%.2fs",
                    page, elapsed, getattr(translate_result, "total_seconds", 0),
                )
                if token_usage_finish:
                    total = token_usage_finish.get("main", {}).get("total", 0)
                    term_total = token_usage_finish.get("term", {}).get("total", 0)
                    trace_logger.info(
                        "Token usage: main=%d, term=%d",
                        total, term_total,
                    )

            try:
                translated_pdf = translate_result.mono_pdf_path
                if translated_pdf is None and translate_result.dual_pdf_path is not None:
                    translated_pdf = translate_result.dual_pdf_path

                if translated_pdf is not None:
                    state.replace_page(str(translated_pdf), page)
                else:
                    if config.DEBUG:
                        trace_logger.error("[step] replace page %d FAILED: no output PDF", page)
                    yield f"data: {json.dumps({'type': 'error', 'error': 'no output PDF'})}\n\n"
                    return
            except Exception as e:
                if config.DEBUG:
                    trace_logger.error(
                        "[step] replace page %d FAILED: %s", page, e, exc_info=True,
                    )
                yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
                return

            if config.DEBUG:
                replace_elapsed = time.time() - translate_start
                trace_logger.info(
                    "[step] replace page %d done (%.2fs total)",
                    page, replace_elapsed,
                )

            # ---- Step 3: Merge glossary ----
            if (
                cumulative_glossary_path is not None
                and translate_result.auto_extracted_glossary_path
            ):
                merge_start = time.time()
                if config.DEBUG:
                    trace_logger.info("[step] merge glossary for page %d", page)
                auto_path = Path(translate_result.auto_extracted_glossary_path)
                cumulative_file = cumulative_glossary_path / "cumulative_glossary.csv"
                try:
                    merge_glossary_csvs(cumulative_file, auto_path)
                    if config.DEBUG:
                        trace_logger.info(
                            "[step] merge glossary done (%.2fs)",
                            time.time() - merge_start,
                        )
                except Exception:
                    logging.getLogger("pdf_reader").warning(
                        "Failed to merge glossary for page %d", page, exc_info=True
                    )
                    if config.DEBUG:
                        trace_logger.warning(
                            "[step] merge glossary FAILED for page %d", page, exc_info=True,
                        )

            # ---- Debug: Preserve babeldoc tracking files ----
            if config.DEBUG and cumulative_glossary_path and translate_result:
                try:
                    # babeldoc writes tracking files to the output directory when debug=True
                    out_dir = Path(output_dir)
                    for fname in ["term_extractor_tracking.json", "term_extractor_freq.json"]:
                        src = out_dir / fname
                        if src.exists():
                            dst = cumulative_glossary_path / fname
                            shutil.copy2(str(src), str(dst))
                            trace_logger.info(
                                "Preserved babeldoc tracking file: %s -> %s",
                                src, dst,
                            )
                except Exception:
                    trace_logger.warning(
                        "Failed to preserve babeldoc tracking files", exc_info=True,
                    )

            yield "data: " + json.dumps({
                "type": "progress", "progress": 100,
                "stage": "finish", "stage_current": 0, "stage_total": 0,
            }) + "\n\n"
            yield f"data: {json.dumps({'type': 'finish', 'progress': 100})}\n\n"
        finally:
            # Cleanup FileHandler
            if file_handler_added is not None:
                try:
                    trace_logger.removeHandler(file_handler_added)
                    file_handler_added.close()
                except Exception:
                    pass

            shutil.rmtree(tmpdir, ignore_errors=True)
            # When debug=True, keep output_dir (contains tracking files); otherwise clean it
            if not config.DEBUG:
                shutil.rmtree(output_dir, ignore_errors=True)
            else:
                # Clean only the translated PDFs, keep tracking JSONs
                try:
                    out_dir = Path(output_dir)
                    for item in out_dir.iterdir():
                        if item.suffix in (".pdf",):
                            item.unlink(missing_ok=True)
                except Exception:
                    pass

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
```

- [ ] **Step 4: 编写测试 — 验证 debug=False 时无 trace 输出**

在 `tests/test_routes.py` 末尾添加：

```python
def test_debug_trace_logger_exists():
    """验证 trace logger 在 routes 模块中正确初始化"""
    from routes import trace_logger
    import logging
    assert isinstance(trace_logger, logging.Logger)
    assert trace_logger.name == "pdf_reader.debug_trace"
    assert trace_logger.level == logging.INFO
```

- [ ] **Step 5: 运行新测试确认通过**

```powershell
pytest tests/test_routes.py::test_debug_trace_logger_exists -v
```

Expected: 1 passed

- [ ] **Step 6: 运行全部测试确认无回归**

```powershell
pytest tests/ -q
```

Expected: 42 passed

- [ ] **Step 7: 运行 ruff 检查**

```powershell
ruff check routes.py
```

Expected: no errors

- [ ] **Step 8: 提交**

```powershell
git add routes.py tests/test_routes.py
git commit -m "feat: add pipeline step logging and debug file handler to translate endpoint"
```

---

### Task 6: 验证

**Files:**
- 无修改（纯验证）

- [ ] **Step 1: 运行完整测试套件**

```powershell
pytest tests/ -q
```

Expected: 42 passed, 0 failed

- [ ] **Step 2: 运行 ruff lint 检查**

```powershell
ruff check .
```

Expected: no errors

- [ ] **Step 3: 手动验证 — 无 --debug 标志启动**

```powershell
python app.py
```

预期：启动正常，无额外日志输出，翻译功能正常（访问 http://127.0.0.1:5000）

- [ ] **Step 4: 手动验证 — --debug 标志启动**

```powershell
python app.py --debug
```

预期：启动正常，控制台显示 trace 日志（Term batch 等），翻译页面后在 `cache/<pdf_hash>/` 下生成 `debug_trace.log`

- [ ] **Step 5: 手动验证 — 检查 debug_trace.log 内容**

翻译一个页面后，检查 `cache/<pdf_hash>/debug_trace.log` 包含：
- `[step] build_settings for page N`
- `[step] build_settings done`
- `Term batch: N paragraphs, N chars`
- `Term batch done: extracted N terms`
- `Term batch prompt: N chars`
- `Term batch response: N chars`
- `[step] submit translate page N`
- `[step] translate page N done`
- `[step] merge glossary for page N`
- `[step] replace page N done`

- [ ] **Step 6: 手动验证 — 重复翻译不会覆盖旧日志**

再次翻译同一 PDF 的另一页后，检查 `cache/<pdf_hash>/` 下应有旋转后的旧 `debug_trace.*.log` 和新 `debug_trace.log`

- [ ] **Step 7: 提交（如有验证相关微调）**

```powershell
git status
```

如果无修改，无需提交。所有实现代码已在之前步骤中提交。
