---
change: refactor-module-cohesion
design-doc: docs/superpowers/specs/2026-06-22-refactor-module-cohesion-design.md
base-ref: e1a8f51bd5869e368cb0b8bf4e28b95fa2299ff1
---

# Refactor Module Cohesion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decompose `services.py` into 3 cohesive modules, extract translation lifecycle from `sse_stream.py`, narrow interface dependencies, and eliminate debug-trace duplication—without changing any behavior.

**Architecture:** 4 independent task groups executed sequentially. Each group ends with a `pytest tests/ -v` gate (all 111 tests must pass). New modules follow strict one-way dependency: routes → lifecycle → state, no reverse imports.

**Tech Stack:** Python 3.12+, pytest, ruff, pymupdf, pdf2zh-next, flask

## Global Constraints

- No function behavior changes—only import paths and module boundaries change
- No frontend changes
- 111 existing tests must all pass after every task group
- `ruff check .` must produce zero errors at final verification
- New modules must not introduce circular imports (one-way: routes → lifecycle → state)
- Only import paths are adjusted; function signatures stay identical except where design doc explicitly changes them: GenerateContext fields, glossary_service resolve_glossary_paths param, finish_translation signature

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `file_hash.py` | **NEW** | `sha256()` — pure file hashing, no deps on pymupdf/pdf2zh |
| `engine_resolver.py` | **NEW** | `resolve_engine()`, `build_engine_kwargs()`, `CONFIG_ATTR_MAP` |
| `pdf_renderer.py` | **NEW** | `render_page()`, `build_settings()` |
| `translation_lifecycle.py` | **NEW** | `finish_translation()` — replace_page + merge + cleanup |
| `services.py` | **DELETE** | All 5 functions migrated out |
| `sse_stream.py` | **MODIFY** | GenerateContext fields change; generate() delegates to finish_translation() |
| `routes.py` | **MODIFY** | Update imports; construct GenerateContext from extracted state fields; pass cache_path not state to glossary_service |
| `glossary_service.py` | **MODIFY** | `resolve_glossary_paths(state)` → `resolve_glossary_paths(cache_path)` |
| `debug_trace.py` | **MODIFY** | Merge setup/cleanup handlers into debug_session; delete standalone functions |
| `tests/test_services.py` | **MODIFY** | Update imports from `services` → new modules |
| `tests/test_sse_stream.py` | **MODIFY** | Adapt GenerateContext construction |
| `tests/test_glossary_service.py` | **MODIFY** | Pass `Path` not `MagicMock(state)` |
| `tests/test_debug_trace.py` | **MODIFY** | Remove tests for deleted functions; update full_trace test |
| `tests/test_state.py` | **MODIFY** | `from services import sha256` → `from file_hash import sha256` |
| `tests/test_routes.py` | **MODIFY** | `from services import sha256` → `from file_hash import sha256` |
| `tests/test_engine_registry.py` | **MODIFY** | `from services import ...` → `from engine_resolver import ...` |

---

### Task 1: Create file_hash.py — extract sha256()

**Files:**
- Create: `file_hash.py`

**Interfaces:**
- Produces: `sha256(filepath: str) -> str`

- [x] **Step 1: Create file_hash.py with sha256()**

```python
import hashlib


def sha256(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()
```

- [x] **Step 2: Verify the new module is importable**

Run: `python -c "from file_hash import sha256; print(sha256)"`
Expected: `<function sha256 at 0x...>`

- [x] **Step 3: Commit**

```bash
git add file_hash.py
git commit -m "refactor: extract sha256() into file_hash.py"
```

---

### Task 2: Create engine_resolver.py — extract engine resolution

**Files:**
- Create: `engine_resolver.py`

**Interfaces:**
- Produces: `resolve_engine(provider: str) -> config.EngineSpec`
- Produces: `build_engine_kwargs(spec: config.EngineSpec) -> dict`
- Produces: `CONFIG_ATTR_MAP: dict[str, str]`

- [x] **Step 1: Create engine_resolver.py**

Copy verbatim from `services.py` lines 1-2, 10-12, 31-80 (imports + functions). New file:

```python
import logging

import config

logger = logging.getLogger("pdf_reader")

CONFIG_ATTR_MAP: dict[str, str] = {
    "model": "MODEL",
    "api_key": "MODEL_API_KEY",
    "base_url": "MODEL_BASE_URL",
    "thinking_mode": "MODEL_THINKING_MODE",
    "reasoning_effort": "MODEL_REASONING_EFFORT",
    "enable_json_mode": "MODEL_ENABLE_JSON_MODE",
    "temperature": "MODEL_TEMPERATURE",
    "timeout": "MODEL_TIMEOUT",
}


def resolve_engine(provider: str) -> config.EngineSpec:  # noqa: ANN201
    spec = config.PROVIDER_INDEX.get(provider)
    if spec is None:
        logger.info("Provider '%s' not found, falling back to OpenAI Compatible", provider)
        spec = config.PROVIDER_INDEX["openai_compatible"]
    logger.info("Using engine: %s (%s)", spec.settings_cls.__name__, config.MODEL)
    return spec


def build_engine_kwargs(spec: config.EngineSpec) -> dict:  # noqa: ANN001, ANN201
    engine_fields = spec.settings_cls.model_fields
    kwargs: dict = {}

    for unified_name, engine_field in spec.field_map.items():
        config_attr = CONFIG_ATTR_MAP[unified_name]
        value = getattr(config, config_attr, None)

        if engine_field not in engine_fields:
            logger.warning("引擎 %s 不支持字段 %s，已跳过", spec.provider, engine_field)
            continue

        if value is not None:
            kwargs[engine_field] = value
        elif unified_name in spec.required_fields:
            raise RuntimeError(f"model.{unified_name} 未配置")
        elif unified_name == "base_url":
            pass
        else:
            logger.warning("当前引擎不支持 %s，已忽略", unified_name)

    optional_fields = ("thinking_mode", "reasoning_effort", "enable_json_mode", "temperature", "timeout")
    for unified_name in optional_fields:
        if unified_name not in spec.field_map:
            value = getattr(config, CONFIG_ATTR_MAP[unified_name], None)
            if value is not None:
                logger.warning("当前引擎不支持 %s，已忽略", unified_name)

    return kwargs
```

- [x] **Step 2: Verify import**

Run: `python -c "from engine_resolver import resolve_engine, build_engine_kwargs, CONFIG_ATTR_MAP; print(CONFIG_ATTR_MAP['model'])"`
Expected: `MODEL`

- [x] **Step 3: Commit**

```bash
git add engine_resolver.py
git commit -m "refactor: extract engine resolution into engine_resolver.py"
```

---

### Task 3: Create pdf_renderer.py — extract PDF rendering and settings building

**Files:**
- Create: `pdf_renderer.py`

**Interfaces:**
- Produces: `render_page(doc: pymupdf.Document, page_num: int, dpi: int) -> bytes`
- Produces: `build_settings(single_page_pdf: str, user_prompt: str | None = None, output_dir: str | None = None, glossary_paths: list[str] | None = None) -> SettingsModel`

- [x] **Step 1: Create pdf_renderer.py**

Copy verbatim the remaining imports + `render_page()` + `build_settings()` from `services.py`:

```python
import logging

import pymupdf
from pdf2zh_next import SettingsModel
from pdf2zh_next.config.model import BasicSettings
from pdf2zh_next.config.model import PDFSettings as Pdf2zhPDFSettings
from pdf2zh_next.config.model import TranslationSettings as Pdf2zhTranslationSettings

import config
from engine_resolver import build_engine_kwargs, resolve_engine

logger = logging.getLogger("pdf_reader")


def render_page(doc: pymupdf.Document, page_num: int, dpi: int) -> bytes:
    if page_num < 0 or page_num >= doc.page_count:
        raise ValueError("page out of range")
    page = doc[page_num]
    pix = page.get_pixmap(dpi=dpi)
    return pix.tobytes(output="png")


def build_settings(
    single_page_pdf: str,
    user_prompt: str | None = None,
    output_dir: str | None = None,
    glossary_paths: list[str] | None = None,
) -> SettingsModel:
    spec = resolve_engine(config.MODEL_PROVIDER)
    engine_kwargs = build_engine_kwargs(spec)

    translation_kwargs = {
        "lang_in": config.TRANSLATION_LANG_IN,
        "lang_out": config.TRANSLATION_LANG_OUT,
        "ignore_cache": True,
        "save_auto_extracted_glossary": True,
    }
    if user_prompt and user_prompt.strip():
        translation_kwargs["custom_system_prompt"] = user_prompt.strip()
    paths = []
    if config.GLOSSARY_PATH.exists() and config.GLOSSARY_PATH.stat().st_size > 0:
        paths.append(str(config.GLOSSARY_PATH))
    if glossary_paths:
        paths.extend(glossary_paths)
    if paths:
        translation_kwargs["glossaries"] = ",".join(paths)
    if output_dir is not None:
        translation_kwargs["output"] = output_dir

    return SettingsModel(
        basic=BasicSettings(debug=False),
        translation=Pdf2zhTranslationSettings(**translation_kwargs),
        pdf=Pdf2zhPDFSettings(
            pages="1",
            no_dual=True,
            only_include_translated_page=True,
            watermark_output_mode="no_watermark",
        ),
        translate_engine_settings=spec.settings_cls(**engine_kwargs),
    )
```

- [x] **Step 2: Verify import**

Run: `python -c "from pdf_renderer import render_page, build_settings; print(render_page, build_settings)"`

- [x] **Step 3: Commit**

```bash
git add pdf_renderer.py
git commit -m "refactor: extract PDF rendering and settings into pdf_renderer.py"
```

---

### Task 4: Update routes.py imports

**Files:**
- Modify: `routes.py:17-22`

- [x] **Step 1: Replace imports in routes.py**

Old lines 17-22:
```python
import config
import glossary_service
import pdf_extraction
import services
import sse_stream
from services import render_page, sha256
```

Replace with:
```python
import config
import glossary_service
import pdf_extraction
import sse_stream
from file_hash import sha256
from pdf_renderer import build_settings, render_page
```

- [x] **Step 2: Update routes.py line 94 — replace `services.build_settings(` with `build_settings(`**

In `translate_page()`, line 94 currently:
```python
    settings = services.build_settings(
```
Replace with:
```python
    settings = build_settings(
```

- [x] **Step 3: Verify no remaining `services.` references in routes.py**

Run: `python -c "content=open('routes.py').read(); assert 'services.' not in content, 'Found remaining services. reference'; print('OK')"`
Expected: `OK`

- [x] **Step 4: Commit**

```bash
git add routes.py
git commit -m "refactor: update routes.py imports to new modules"
```

---

### Task 5: Verify state.py needs no changes

**Files:**
- No changes needed

`state.py` does not import from `services` directly. `sha256` and `render_page` are passed as parameters to `open_pdf()` and `render_page()`. Only tests need import updates (Task 6).

- [x] **Step 1: Confirm state.py has no import of services**

```bash
grep -n "services" state.py
```
Expected: no matches.

---

### Task 6: Update all test imports + delete services.py

**Files:**
- Modify: `tests/test_services.py`
- Modify: `tests/test_state.py`
- Modify: `tests/test_routes.py`
- Modify: `tests/test_engine_registry.py`
- DELETE: `services.py`

- [x] **Step 1: Update test_services.py imports**

Line 8 — top-level import:
```python
# Old
from services import build_settings, render_page, sha256
# New
from file_hash import sha256
from pdf_renderer import build_settings, render_page
```

Lines 80, 90 — local imports in test functions:
```python
# Old
from services import resolve_engine
# New
from engine_resolver import resolve_engine
```

Lines 100, 109, 118 — local imports:
```python
# Old
from services import build_engine_kwargs
# New
from engine_resolver import build_engine_kwargs
```

- [x] **Step 2: Update test_state.py imports**

Lines 20, 31, 43, 58:
```python
# Old
from services import sha256
# New
from file_hash import sha256
```

Lines 66, 118:
```python
# Old
from services import sha256 as sha256_func
# New
from file_hash import sha256 as sha256_func
```

- [x] **Step 3: Update test_routes.py imports**

Lines 55, 134:
```python
# Old
from services import sha256 as sha256_func
# New
from file_hash import sha256 as sha256_func
```

- [x] **Step 3.5: Update test_routes.py monkeypatch target (line 105)**

The `test_translate_page_integrates_cumulative_glossary` test monkeypatches `services.build_settings`:

```python
# Old (line 105)
    monkeypatch.setattr("services.build_settings", fake_build_settings)
# New
    monkeypatch.setattr("pdf_renderer.build_settings", fake_build_settings)
```

- [x] **Step 4: Update test_engine_registry.py import**

Line 5:
```python
# Old
from services import build_engine_kwargs, resolve_engine
# New
from engine_resolver import build_engine_kwargs, resolve_engine
```

- [x] **Step 5: Delete services.py**

```bash
git rm services.py
```

- [x] **Step 6: Run full test suite — Group 1 gate**

Run: `pytest tests/ -v`
Expected: all 111 tests pass. If any fail, fix the import in the failing test and re-run.

- [x] **Step 7: Commit**

```bash
git add tests/
git commit -m "refactor: update test imports and delete services.py"
```

---

### Task 7: Create translation_lifecycle.py

**Files:**
- Create: `translation_lifecycle.py`

**Interfaces:**
- Produces: `finish_translation(translate_result, replace_page: Callable[[str], None], glossary_cache_path: Path | None, tmpdir: Path, output_dir: str) -> None`

- [x] **Step 1: Create translation_lifecycle.py**

```python
import logging
import shutil
import time
from collections.abc import Callable
from pathlib import Path

import debug_trace
from glossary_service import merge_after_translate

logger = logging.getLogger("pdf_reader")


def finish_translation(
    translate_result,
    replace_page: Callable[[str], None],
    glossary_cache_path: Path | None,
    tmpdir: Path,
    output_dir: str,
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

    shutil.rmtree(tmpdir, ignore_errors=True)
    shutil.rmtree(output_dir, ignore_errors=True)
```

**Note:** The `page=-1` in `log_glossary_merge` is intentional — the page number is lost at this layer since `replace_page` is a pre-bound callable. The debug log is informational; this does not affect behavior.

- [x] **Step 2: Verify import**

Run: `python -c "from translation_lifecycle import finish_translation; print(finish_translation)"`

- [x] **Step 3: Commit**

```bash
git add translation_lifecycle.py
git commit -m "refactor: create translation_lifecycle.py with finish_translation()"
```

---

### Task 8: Modify sse_stream.py — narrow GenerateContext and delegate to lifecycle

**Files:**
- Modify: `sse_stream.py:1-134`

**Interfaces:**
- Consumes: `finish_translation` from `translation_lifecycle`
- Changes: GenerateContext drops `state: AppState`, gains `replace_page: Callable[[str], None]` + `glossary_cache_path: Path | None`

- [x] **Step 1: Update imports in sse_stream.py**

Old imports (lines 1-14):
```python
import json
import logging
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
```

Replace with:
```python
import json
import logging
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from pdf2zh_next import SettingsModel

import debug_trace
from translation_lifecycle import finish_translation
from translation_orchestrator import TranslationError, run_translation
```

- [x] **Step 2: Replace GenerateContext dataclass**

Old (lines 25-33):
```python
@dataclass
class GenerateContext:
    settings: SettingsModel
    single_page_pdf: Path
    state: AppState
    page: int
    glossary_paths: list[str] | None
    tmpdir: Path
    output_dir: str
```

New:
```python
@dataclass
class GenerateContext:
    settings: SettingsModel
    single_page_pdf: Path
    replace_page: Callable[[str], None]
    glossary_cache_path: Path | None
    page: int
    glossary_paths: list[str] | None
    tmpdir: Path
    output_dir: str
```

- [x] **Step 3: Replace generate() function**

Replace the entire `generate()` function (lines 66-134) with:

```python
def generate(ctx: GenerateContext) -> Iterator[str]:
    try:
        with debug_trace.debug_session(ctx.glossary_cache_path, ctx.page):
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

            finish_translation(
                translate_result,
                ctx.replace_page,
                ctx.glossary_cache_path,
                ctx.tmpdir,
                ctx.output_dir,
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
```

`finish_translation` handles `replace_page` + `merge_after_translate` + tmpdir cleanup. `generate()` focuses only on SSE event formatting and forwarding. `import shutil` is removed from sse_stream.py since cleanup lives in the lifecycle module. The `test_generate_cleans_up_tmpdir` test still passes because `finish_translation` calls `rmtree` on the success path.

- [x] **Step 4: Commit**

```bash
git add sse_stream.py
git commit -m "refactor: delegate post-translation work to finish_translation(), narrow GenerateContext"
```

---

### Task 9: Modify routes.py — construct GenerateContext from state fields

**Files:**
- Modify: `routes.py:80-106` (translate_page function)

- [x] **Step 1: Update translate_page() — GenerateContext construction**

Lines 98-101 — old:
```python
    ctx = sse_stream.GenerateContext(
        settings=settings, single_page_pdf=single_page_pdf, state=state,
        page=page, glossary_paths=glossary_paths, tmpdir=tmpdir, output_dir=output_dir,
    )
```

New:
```python
    ctx = sse_stream.GenerateContext(
        settings=settings,
        single_page_pdf=single_page_pdf,
        replace_page=lambda path: state.replace_page(path, page),
        glossary_cache_path=state.glossary_cache_path,
        page=page,
        glossary_paths=glossary_paths,
        tmpdir=tmpdir,
        output_dir=output_dir,
    )
```

**Note:** `replace_page` is passed as a lambda that binds `page` — this way the lifecycle module doesn't need to know about page numbers, matching the narrower interface.

- [x] **Step 2: Verify routes.py imports correctly**

Run: `python -c "import py_compile; py_compile.compile('routes.py', doraise=True)"`
Expected: no output (successful compile).

- [x] **Step 3: Commit**

```bash
git add routes.py
git commit -m "refactor: routes constructs GenerateContext from state fields"
```

---

### Task 10: Update test_sse_stream.py — adapt to new GenerateContext

**Files:**
- Modify: `tests/test_sse_stream.py`

- [x] **Step 1: Update all GenerateContext constructions**

Every test that creates `GenerateContext(state=state, ...)` must change to `GenerateContext(replace_page=..., glossary_cache_path=...)`.

The pattern across all test functions (`test_generate_full_flow_byte_level_compatible`, `test_generate_error_event_stops_stream`, `test_generate_translation_error_yields_error_event`, `test_generate_cleans_up_tmpdir`, `test_generate_merges_glossary_with_str_auto_path`, `test_generate_passes_through_keepalive_empty_string`):

Old pattern in each test:
```python
    state = MagicMock()
    state.glossary_cache_path = None
    state.replace_page = MagicMock()
    ...
    ctx = GenerateContext(
        settings=MagicMock(),
        single_page_pdf=single_page_pdf,
        state=state,
        page=0,
        glossary_paths=None,
        tmpdir=tmpdir,
        output_dir=output_dir,
    )
```

New pattern:
```python
    replace_page = MagicMock()
    glossary_cache_path = None
    ...
    ctx = GenerateContext(
        settings=MagicMock(),
        single_page_pdf=single_page_pdf,
        replace_page=replace_page,
        glossary_cache_path=glossary_cache_path,
        page=0,
        glossary_paths=None,
        tmpdir=tmpdir,
        output_dir=output_dir,
    )
```

For tests that use `state.glossary_cache_path = glossary_cache` (e.g., `test_generate_merges_glossary_with_str_auto_path`):
```python
    glossary_cache_path = glossary_cache  # previously: state.glossary_cache_path = glossary_cache
    replace_page = MagicMock()
    ...
    ctx = GenerateContext(
        ...,
        replace_page=replace_page,
        glossary_cache_path=glossary_cache_path,
        ...
    )
```

- [x] **Step 2: Update assertions that reference `state.replace_page`**

In `test_generate_full_flow_byte_level_compatible` (line 164):
```python
# Old
    state.replace_page.assert_called_once_with(str(tmp_path / "translated.pdf"), 0)
# New — but note: replace_page is now called with ONE arg (the page is pre-bound)
    replace_page.assert_called_once_with(str(tmp_path / "translated.pdf"))
```

**Important:** This is a test assertion change because the interface changed: `replace_page` in GenerateContext is now `Callable[[str], None]` (no page parameter). The lambda in routes.py binds the page. The test should verify the one-argument call.

- [x] **Step 3: Run tests to verify Group 2**

Run: `pytest tests/test_sse_stream.py tests/test_routes.py -v`
Expected: all tests pass. If any fail, fix and re-run.

- [x] **Step 4: Run full test suite — Group 2 gate**

Run: `pytest tests/ -v`
Expected: all 111 tests pass.

- [x] **Step 5: Commit**

```bash
git add tests/test_sse_stream.py
git commit -m "test: adapt sse_stream tests to new GenerateContext interface"
```

---

### Task 11: Narrow glossary_service interface

**Files:**
- Modify: `glossary_service.py:1-17`
- Modify: `tests/test_glossary_service.py`

- [x] **Step 1: Modify resolve_glossary_paths() signature**

In `glossary_service.py`, change lines 1-17:

```python
# Old imports
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
```

New:
```python
import logging
from pathlib import Path

from glossary_merger import merge_glossary_csvs

logger = logging.getLogger("pdf_reader")


def resolve_glossary_paths(cache_path: Path | None) -> list[str] | None:
    if cache_path is None:
        return None
    cumulative_file = cache_path / "cumulative_glossary.csv"
    if cumulative_file.exists() and cumulative_file.stat().st_size > 0:
        return [str(cumulative_file)]
    return None
```

**Changes:** Removed `from state import AppState`, changed parameter from `state: AppState` to `cache_path: Path | None`.

- [x] **Step 1.5: Update routes.py call site**

In `translate_page()` (routes.py line 93), update the call to pass `state.glossary_cache_path` instead of `state`:

```python
# Old (line 93)
    glossary_paths = glossary_service.resolve_glossary_paths(state)
# New
    glossary_paths = glossary_service.resolve_glossary_paths(state.glossary_cache_path)
```

- [x] **Step 2: Update test_glossary_service.py tests**

Each test currently passes `state = MagicMock(); state.glossary_cache_path = ...` then calls `resolve_glossary_paths(state)`. Change to pass the path directly:

`test_resolve_glossary_paths_returns_none_when_no_cache`:
```python
# Old
    state = MagicMock()
    state.glossary_cache_path = None
    assert resolve_glossary_paths(state) is None
# New
    assert resolve_glossary_paths(None) is None
```

`test_resolve_glossary_paths_returns_none_when_no_cumulative_file`:
```python
# Old
    state = MagicMock()
    state.glossary_cache_path = Path("/nonexistent")
    assert resolve_glossary_paths(state) is None
# New
    assert resolve_glossary_paths(Path("/nonexistent")) is None
```

`test_resolve_glossary_paths_returns_path_when_cumulative_exists`:
```python
# Old
    state = MagicMock()
    state.glossary_cache_path = cache_dir
    result = resolve_glossary_paths(state)
# New
    result = resolve_glossary_paths(cache_dir)
```

`test_resolve_glossary_paths_returns_none_when_cumulative_empty`:
```python
# Old
    state = MagicMock()
    state.glossary_cache_path = cache_dir
    assert resolve_glossary_paths(state) is None
# New
    assert resolve_glossary_paths(cache_dir) is None
```

- [x] **Step 3: Run tests to verify Group 3**

Run: `pytest tests/test_glossary_service.py -v`
Expected: all tests pass.

- [x] **Step 4: Run full test suite — Group 3 gate**

Run: `pytest tests/ -v`
Expected: all 111 tests pass.

- [x] **Step 5: Commit**

```bash
git add glossary_service.py tests/test_glossary_service.py
git commit -m "refactor: narrow glossary_service interface to cache_path instead of AppState"
```

---

### Task 12: Eliminate debug_trace.py duplication

**Files:**
- Modify: `debug_trace.py:117-148`
- Modify: `tests/test_debug_trace.py`

- [x] **Step 1: Delete setup_file_handler and cleanup_file_handler from debug_trace.py**

Delete lines 117-148 (the two standalone functions):
```python
# DELETE lines 117-148:
def setup_file_handler(glossary_path: Path | None, page: int) -> logging.FileHandler | None:
    ...

def cleanup_file_handler(handler: logging.FileHandler | None) -> None:
    ...
```

**Note:** These functions have zero external callers — only `test_debug_trace.py` references them. `debug_session` (lines 62-99 of the same file) already contains the identical logic inline. No production code calls `setup_file_handler` or `cleanup_file_handler`; sse_stream.py uses `debug_session` directly.

- [x] **Step 2: Update test_debug_trace.py**

Delete test functions that test the removed standalone functions:
- `test_setup_file_handler_returns_none_when_no_glossary_path` (lines 32-36)
- `test_setup_file_handler_returns_none_when_debug_false` (lines 39-43)
- `test_cleanup_file_handler_none_is_noop` (lines 46-47)
- `test_cleanup_file_handler_removes_and_closes` (lines 50-55)

Update `test_full_debug_trace_bytes_identical` (line 75): replace direct calls to `setup_file_handler`/`cleanup_file_handler` with `debug_session` context manager:

Old (lines 92-103):
```python
        with patch("debug_trace.config") as mock_config:
            mock_config.DEBUG = True

            handler = debug_trace.setup_file_handler(glossary_path, page=1)

            debug_trace.log_step("submit translate page %d", 1)
            debug_trace.log_step("translate page %d done (%.2fs)", 1, 1.23)
            debug_trace.log_token_usage({"main": {"total": 100}, "term": {"total": 50}})
            debug_trace.log_step("merge glossary for page %d", 1)
            debug_trace.log_step("merge glossary done (%.2fs)", 0.02)

            debug_trace.cleanup_file_handler(handler)
```

New:
```python
        with patch("debug_trace.config") as mock_config:
            mock_config.DEBUG = True

            with debug_trace.debug_session(glossary_path, page=1):
                debug_trace.log_step("submit translate page %d", 1)
                debug_trace.log_step("translate page %d done (%.2fs)", 1, 1.23)
                debug_trace.log_token_usage({"main": {"total": 100}, "term": {"total": 50}})
                debug_trace.log_step("merge glossary for page %d", 1)
                debug_trace.log_step("merge glossary done (%.2fs)", 0.02)
```

Update `test_zero_overhead_no_io_when_debug_false` (line 124): same direct-call replacement:

Old (lines 139-145):
```python
        with patch("debug_trace.config") as mock_config:
            mock_config.DEBUG = False

            handler = debug_trace.setup_file_handler(glossary_path, page=1)
            debug_trace.log_step("submit translate page %d", 1)
            debug_trace.log_token_usage({"main": {"total": 100}})
            debug_trace.cleanup_file_handler(handler)
```

New:
```python
        with patch("debug_trace.config") as mock_config:
            mock_config.DEBUG = False

            with debug_trace.debug_session(glossary_path, page=1):
                debug_trace.log_step("submit translate page %d", 1)
                debug_trace.log_token_usage({"main": {"total": 100}})
```

- [x] **Step 3: Run tests to verify Group 4**

Run: `pytest tests/test_debug_trace.py tests/test_debug_patches.py -v`
Expected: all tests pass.

- [x] **Step 4: Run full test suite — Group 4 gate**

Run: `pytest tests/ -v`
Expected: all 111 tests pass.

- [x] **Step 5: Commit**

```bash
git add debug_trace.py tests/test_debug_trace.py
git commit -m "refactor: merge setup/cleanup handlers into debug_session, delete duplicates"
```

---

### Task 13: Final verification

- [x] **Step 1: Run ruff check**

```bash
ruff check .
```
Expected: zero errors, zero warnings.

- [x] **Step 2: Run full test suite**

```bash
pytest tests/ -v
```
Expected: all 111 tests pass.

- [x] **Step 3: Verify services.py is deleted**

```bash
test -f services.py && echo "ERROR: services.py still exists" || echo "OK"
```
Expected: `OK`

- [x] **Step 4: Commit final state if any changes remain**

```bash
git status
```
If dirty, commit with:
```bash
git add -u
git commit -m "chore: final cleanup after refactor"
```
