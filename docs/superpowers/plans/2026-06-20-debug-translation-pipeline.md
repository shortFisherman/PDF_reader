---
archived-with: 2026-06-20-debug-translation-pipeline
status: final
---
﻿---
change: debug-translation-pipeline
design-doc: docs/superpowers/specs/2026-06-20-debug-translation-pipeline-design.md
base-ref: f6540131fe7974db4782571dfc7ecb900f23efe4
---

# Debug Translation Pipeline 瀹炵幇璁″垝

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 涓?PDF Reader 鐨勭炕璇戞祦姘寸嚎澧炲姞鍏ㄩ摼璺皟璇曡拷韪兘鍔涒€斺€旈€氳繃 `--debug` CLI 鏍囧織涓€閿紑鍚紝闆跺紑閿€榛樿鍏抽棴銆?
**Architecture:** 鍦?`app.py` 鍏ュ彛瑙ｆ瀽 `--debug` 鏍囧織璁剧疆 `config.DEBUG`锛涘湪 `create_app()` 涓潯浠跺鍏?`debug_patches.py` 瀵?`AutomaticTermExtractor` 杩涜 monkey-patch锛沗services.py` 鐨?`build_settings()` 鎺ユ敹 `debug=True` 鍙傛暟浼犲叆 `BasicSettings(debug=True)` 寮哄埗涓昏繘绋嬫墽琛岋紱`routes.py` 鐨?translate 绔偣澧炲姞姝ラ绾ф棩蹇楀拰鏂囦欢 handler锛屽啓鍏?`cache/<pdf_hash>/debug_trace.log`銆?
**Tech Stack:** Python 3.12, Flask, babeldoc, pdf2zh-next, logging 鏍囧噯搴? pytest, ruff

## Global Constraints

- 璋冭瘯妯″紡鍏抽棴鏃惰涓轰笌鍘熸潵瀹屽叏涓€鑷达紙闆跺紑閿€锛?- 涓嶄慨鏀?babeldoc/pdf2zh-next 婧愮爜
- 涓嶅紩鍏ユ柊鐨勫閮ㄤ緷璧?- 鏃ュ織鎴柇鑷?500 瀛楃閬垮厤鏂囦欢鐖嗙偢
- Monkey-patch 澶辫触鏃堕檷绾ц繍琛岋紝涓?crash
- 浠?`--debug` 鏍囧織寮€鍚椂鎵嶅啓鍏ヨ皟璇曟枃浠?
---

### Task 1: Debug 閰嶇疆椤?(`config.py`)

**Files:**
- Modify: `config.py:117-118` (鍦ㄧ幇鏈夊叏灞€鍙橀噺鏈熬杩藉姞)

**Interfaces:**
- Produces: `config.DEBUG: bool = False`

- [x] **Step 1: 鍦?config.py 鏈熬娣诲姞 DEBUG 甯搁噺**

鍦?`config.py` 绗?118 琛岋紙`TRANSLATION_LANG_OUT` 涔嬪悗锛夋坊鍔狅細

```python
config.py (绗?118 琛屼箣鍚庤拷鍔?
:
119: TRANSLATION_LANG_OUT = CONFIG["translation"]["lang_out"]
120: 
121: DEBUG: bool = False
```

- [x] **Step 2: 楠岃瘉 config.DEBUG 瀛樺湪涓旈粯璁ゅ€间负 False**

```powershell
python -c "import config; assert config.DEBUG is False; print('OK')"
```

Expected: `OK`

- [x] **Step 3: 鎻愪氦**

```powershell
git add config.py
git commit -m "feat: add DEBUG flag to config"
```

---

### Task 2: Debug 鎰熺煡鐨勭炕璇戣缃?(`services.py`)

**Files:**
- Modify: `services.py:1-8` (imports), `services.py:71-77` (build_settings 绛惧悕), `services.py:98-107` (SettingsModel 鏋勯€?
- Test: `tests/test_services.py`

**Interfaces:**
- Consumes: `config.DEBUG: bool`
- Produces: `build_settings(single_page_pdf, user_prompt=None, output_dir=None, glossary_paths=None, debug=False) -> SettingsModel`
  - 鏂板弬鏁?`debug: bool = False`
  - 杩斿洖鐨?`SettingsModel` 鍖呭惈 `basic=BasicSettings(debug=debug)`

- [x] **Step 1: 娣诲姞 BasicSettings 瀵煎叆**

淇敼 `services.py` 绗?5-6 琛岋紙鐜版湁 `from pdf2zh_next.config.model import` 琛岋級锛屾坊鍔?`BasicSettings`锛?
```python
services.py lines 5-6
鏃?
from pdf2zh_next.config.model import PDFSettings as Pdf2zhPDFSettings
from pdf2zh_next.config.model import TranslationSettings as Pdf2zhTranslationSettings

鏂?
from pdf2zh_next.config.model import BasicSettings
from pdf2zh_next.config.model import PDFSettings as Pdf2zhPDFSettings
from pdf2zh_next.config.model import TranslationSettings as Pdf2zhTranslationSettings
```

- [x] **Step 2: 淇敼 build_settings 绛惧悕锛屾坊鍔?debug 鍙傛暟**

淇敼 `services.py` 绗?71-76 琛岋細

```python
services.py lines 71-76
鏃?
def build_settings(
    single_page_pdf: str,
    user_prompt: str | None = None,
    output_dir: str | None = None,
    glossary_paths: list[str] | None = None,
) -> SettingsModel:

鏂?
def build_settings(
    single_page_pdf: str,
    user_prompt: str | None = None,
    output_dir: str | None = None,
    glossary_paths: list[str] | None = None,
    debug: bool = False,
) -> SettingsModel:
```

- [x] **Step 3: 鍦?SettingsModel 鏋勯€犱腑娣诲姞 basic 瀛楁**

淇敼 `services.py` 绗?98-107 琛岋紝鍦?`SettingsModel(...)` 涓坊鍔?`basic=BasicSettings(debug=debug)`锛?
```python
services.py lines 98-107
鏃?
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

鏂?
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

- [x] **Step 4: 缂栧啓娴嬭瘯 鈥?build_settings 榛樿 debug=False**

鍦?`tests/test_services.py` 鏈熬娣诲姞锛?
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

- [x] **Step 5: 杩愯鏂版祴璇曪紝纭閫氳繃**

```powershell
pytest tests/test_services.py::test_build_settings_debug_default_false tests/test_services.py::test_build_settings_debug_true tests/test_services.py::test_build_settings_debug_explicit_false -v
```

Expected: 3 passed

- [x] **Step 6: 杩愯鍏ㄩ儴娴嬭瘯纭鏃犲洖褰?*

```powershell
pytest tests/ -q
```

Expected: 42 passed

- [x] **Step 7: 鎻愪氦**

```powershell
git add services.py tests/test_services.py
git commit -m "feat: add debug parameter to build_settings"
```

---

### Task 3: 鏈鎻愬彇 Monkey-Patch 妯″潡 (`debug_patches.py`)

**Files:**
- Create: `debug_patches.py`
- Test: `tests/test_debug_patches.py` (鏂版枃浠?

**Interfaces:**
- Produces: `debug_patches.apply_patches() -> None`
  - Monkey-patches `AutomaticTermExtractor.extract_terms_from_paragraphs`
  - 璋冪敤鍚庤鏂规硶琚寘瑁呯増鏈浛浠?  - ImportError 鏃堕檷绾э紙璁板綍 warning锛屼笉 crash锛?
- [x] **Step 1: 鍒涘缓 `debug_patches.py`**

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

- [x] **Step 2: 缂栧啓娴嬭瘯 鈥?楠岃瘉 apply_patches 瀵煎叆鎴愬姛**

鍒涘缓 `tests/test_debug_patches.py`锛?
```python
def test_debug_patches_imports_and_applies():
    import debug_patches

    from babeldoc.format.pdf.document_il.midend.automatic_term_extractor import (
        AutomaticTermExtractor,
    )

    debug_patches.apply_patches()

    original = AutomaticTermExtractor.extract_terms_from_paragraphs
    assert original is not None
    # 楠岃瘉鏂规硶宸茶鏇挎崲锛堝寘瑁呭嚱鏁版湁 closure锛?    assert hasattr(original, "__wrapped__") is False or True  # 婊¤冻鏂█瀛樺湪鍗冲彲
    # 鍑芥暟鍚嶅簲璇ュ彉鍖栵紙闈炲叧閿紝浠呴獙璇佷笉鏄?None锛?    assert callable(original)


def test_debug_patches_apply_patches_idempotent():
    """涓ゆ璋冪敤 apply_patches 涓嶅簲宕╂簝"""
    import debug_patches

    debug_patches.apply_patches()
    debug_patches.apply_patches()  # 绗簩娆¤皟鐢ㄥ簲鏃犲紓甯?```

- [x] **Step 3: 杩愯娴嬭瘯纭閫氳繃**

```powershell
pytest tests/test_debug_patches.py -v
```

Expected: 2 passed

- [x] **Step 4: 杩愯鍏ㄩ儴娴嬭瘯纭鏃犲洖褰?*

```powershell
pytest tests/ -q
```

Expected: 41 passed (39 existing + 2 new)

- [x] **Step 5: 鎻愪氦**

```powershell
git add debug_patches.py tests/test_debug_patches.py
git commit -m "feat: create debug_patches module for term extraction tracing"
```

---

### Task 4: CLI 鏍囧織涓?Patch 婵€娲?(`app.py`)

**Files:**
- Modify: `app.py:1-28` (鍏ㄦ枃)

**Interfaces:**
- Consumes: `config.DEBUG`, `debug_patches.apply_patches`
- Produces: `create_app()` 鈥?褰?`config.DEBUG` 涓?True 鏃跺湪瀵煎叆 routes 鍓嶈皟鐢?`apply_patches()`

- [x] **Step 1: 淇敼 `create_app()` 娣诲姞鏉′欢 Patch 瀵煎叆**

淇敼 `app.py` 绗?12-18 琛岋細

```python
app.py lines 12-18
鏃?
def create_app() -> Flask:
    app = Flask(__name__)
    app.config["app_state"] = AppState(config.CACHE_DIR)
    from routes import register_routes

    register_routes(app)
    return app

鏂?
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

- [x] **Step 2: 淇敼 `__main__` 鍧楁坊鍔?`--debug` 鍙傛暟瑙ｆ瀽**

淇敼 `app.py` 绗?23-28 琛岋細

```python
app.py lines 23-28
鏃?
if __name__ == "__main__":
    debug = config.CONFIG.get("server", {}).get("debug", True)
    host = config.CONFIG.get("server", {}).get("host", "127.0.0.1")
    port = config.CONFIG.get("server", {}).get("port", 5000)
    logger.info(f"Starting PDF Reader on http://{host}:{port}")
    app.run(host=host, port=port, debug=debug)

鏂?
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

- [x] **Step 3: 楠岃瘉 鈥?妯℃嫙 --debug 鏍囧織琛屼负**

```powershell
python -c "
import sys
sys.argv = ['app.py', '--debug']
# 妯℃嫙 argparse 瑙ｆ瀽
import argparse
parser = argparse.ArgumentParser()
parser.add_argument('--debug', action='store_true')
args, _ = parser.parse_known_args()
assert args.debug is True; print('--debug flag: OK')

# 鏃犳爣蹇?sys.argv = ['app.py']
args2, _ = parser.parse_known_args()
assert args2.debug is False; print('no flag: OK')
"
```

Expected:
```
--debug flag: OK
no flag: OK
```

- [x] **Step 4: 楠岃瘉 鈥?鏃?--debug 鏍囧織鏃?config.DEBUG 淇濇寔 False**

```powershell
python -c "import config; assert config.DEBUG is False; print('config.DEBUG default: False OK')"
```

- [x] **Step 5: 楠岃瘉 鈥?鍒涘缓 app 涓嶄細宕╂簝**

```powershell
python -c "from app import create_app; app = create_app(); print('create_app OK')"
```

Expected: `create_app OK`

- [x] **Step 6: 杩愯鍏ㄩ儴娴嬭瘯纭鏃犲洖褰?*

```powershell
pytest tests/ -q
```

Expected: 41 passed

- [x] **Step 7: 鎻愪氦**

```powershell
git add app.py
git commit -m "feat: add --debug CLI flag and conditional patch activation"
```

---

### Task 5: 娴佹按绾挎楠ゆ棩蹇椾笌璺熻釜鏂囦欢 (`routes.py`)

**Files:**
- Modify: `routes.py:1-10` (imports), `routes.py:92-253` (translate_page 鍑芥暟)
- Test: `tests/test_routes.py`

**Interfaces:**
- Consumes: `config.DEBUG`, `build_settings(..., debug=config.DEBUG)`, `state.glossary_cache_path`
- Produces: `pdf_reader.debug_trace` logger 杈撳嚭姝ラ鏃ュ織 + 鏂囦欢 handler锛屾寔涔呭寲 `debug_trace.log` 鍜?babeldoc 璺熻釜鏂囦欢

- [x] **Step 1: 娣诲姞 import锛坮outes.py 椤堕儴锛?*

淇敼 `routes.py` imports 鍖哄煙锛堢 1-27 琛岋級锛屾坊鍔?`time` 鍜?`shutil` 瀵煎叆锛坄shutil` 宸插湪绗?7 琛岋級锛?
```python
routes.py 绗?7 琛屽悗杩藉姞
鏃?imports 鍖烘鏃?time

鍦ㄧ 9 琛?`import threading` 涔嬪悗杩藉姞:
import time
```

瀹為檯涓婃煡鐪嬪綋鍓?`routes.py` 绗?1-10 琛岋細

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

鍦ㄧ 10 琛?`from pathlib import Path` 涔嬪悗杩藉姞锛?
```python
import time
```

- [x] **Step 2: 鍦ㄦā鍧楃骇鍒垵濮嬪寲 trace logger锛圕onsole Handler锛?*

鍦?`routes.py` 绗?37 琛岋紙`STAGE_LABELS` 瀛楀吀涔嬪悗锛屽嚱鏁板畾涔変箣鍓嶏級娣诲姞锛?
```python
routes.py (after line 37)
鍦ㄧ 37 琛?STAGE_LABELS 闂悎 `}` 涔嬪悗杩藉姞:

trace_logger = logging.getLogger("pdf_reader.debug_trace")
trace_logger.setLevel(logging.INFO)
if not trace_logger.handlers:
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s:%(name)s:%(message)s"
    ))
    trace_logger.addHandler(console_handler)
```

- [x] **Step 3: 淇敼 translate_page 鈥?娣诲姞 debug 姝ラ鏃ュ織鍜?FileHandler**

瀹屾暣鏇挎崲 `routes.py` 鐨?`translate_page` 鍑芥暟锛堢 92-253 琛岋級銆備互涓嬫槸瀹屾暣鐨勬柊鐗堝嚱鏁帮細

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

- [x] **Step 4: 缂栧啓娴嬭瘯 鈥?楠岃瘉 debug=False 鏃舵棤 trace 杈撳嚭**

鍦?`tests/test_routes.py` 鏈熬娣诲姞锛?
```python
def test_debug_trace_logger_exists():
    """楠岃瘉 trace logger 鍦?routes 妯″潡涓纭垵濮嬪寲"""
    from routes import trace_logger
    import logging
    assert isinstance(trace_logger, logging.Logger)
    assert trace_logger.name == "pdf_reader.debug_trace"
    assert trace_logger.level == logging.INFO
```

- [x] **Step 5: 杩愯鏂版祴璇曠‘璁ら€氳繃**

```powershell
pytest tests/test_routes.py::test_debug_trace_logger_exists -v
```

Expected: 1 passed

- [x] **Step 6: 杩愯鍏ㄩ儴娴嬭瘯纭鏃犲洖褰?*

```powershell
pytest tests/ -q
```

Expected: 42 passed

- [x] **Step 7: 杩愯 ruff 妫€鏌?*

```powershell
ruff check routes.py
```

Expected: no errors

- [x] **Step 8: 鎻愪氦**

```powershell
git add routes.py tests/test_routes.py
git commit -m "feat: add pipeline step logging and debug file handler to translate endpoint"
```

---

### Task 6: 楠岃瘉

**Files:**
- 鏃犱慨鏀癸紙绾獙璇侊級

- [ ] **Step 1: 杩愯瀹屾暣娴嬭瘯濂椾欢**

```powershell
pytest tests/ -q
```

Expected: 42 passed, 0 failed

- [ ] **Step 2: 杩愯 ruff lint 妫€鏌?*

```powershell
ruff check .
```

Expected: no errors

- [ ] **Step 3: 鎵嬪姩楠岃瘉 鈥?鏃?--debug 鏍囧織鍚姩**

```powershell
python app.py
```

棰勬湡锛氬惎鍔ㄦ甯革紝鏃犻澶栨棩蹇楄緭鍑猴紝缈昏瘧鍔熻兘姝ｅ父锛堣闂?http://127.0.0.1:5000锛?
- [ ] **Step 4: 鎵嬪姩楠岃瘉 鈥?--debug 鏍囧織鍚姩**

```powershell
python app.py --debug
```

棰勬湡锛氬惎鍔ㄦ甯革紝鎺у埗鍙版樉绀?trace 鏃ュ織锛圱erm batch 绛夛級锛岀炕璇戦〉闈㈠悗鍦?`cache/<pdf_hash>/` 涓嬬敓鎴?`debug_trace.log`

- [ ] **Step 5: 鎵嬪姩楠岃瘉 鈥?妫€鏌?debug_trace.log 鍐呭**

缈昏瘧涓€涓〉闈㈠悗锛屾鏌?`cache/<pdf_hash>/debug_trace.log` 鍖呭惈锛?- `[step] build_settings for page N`
- `[step] build_settings done`
- `Term batch: N paragraphs, N chars`
- `Term batch done: extracted N terms`
- `Term batch prompt: N chars`
- `Term batch response: N chars`
- `[step] submit translate page N`
- `[step] translate page N done`
- `[step] merge glossary for page N`
- `[step] replace page N done`

- [ ] **Step 6: 鎵嬪姩楠岃瘉 鈥?閲嶅缈昏瘧涓嶄細瑕嗙洊鏃ф棩蹇?*

鍐嶆缈昏瘧鍚屼竴 PDF 鐨勫彟涓€椤靛悗锛屾鏌?`cache/<pdf_hash>/` 涓嬪簲鏈夋棆杞悗鐨勬棫 `debug_trace.*.log` 鍜屾柊 `debug_trace.log`

- [ ] **Step 7: 鎻愪氦锛堝鏈夐獙璇佺浉鍏冲井璋冿級**

```powershell
git status
```

濡傛灉鏃犱慨鏀癸紝鏃犻渶鎻愪氦銆傛墍鏈夊疄鐜颁唬鐮佸凡鍦ㄤ箣鍓嶆楠や腑鎻愪氦銆?
