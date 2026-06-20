---
change: cumulative-glossary-across-pages
design-doc: docs/superpowers/specs/2026-06-20-cumulative-glossary-design.md
base-ref: 41e77d5e9521db9aa137611209b24b93aff0e5e9
---

# Cumulative Glossary Across Pages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist auto-extracted glossary terms across page translations within the same PDF session, so LLM translations on later pages reference previously extracted terminology.

**Architecture:** Three touch points: `AppState` gains a `glossary_cache_path` property pointing to `CACHE_DIR/<pdf_hash>/`. `build_settings()` accepts an optional `glossary_paths` list to pass multiple glossary CSVs (user static + cumulative) to the pdf2zh-next pipeline. `translate_page()` checks for a cumulative glossary before translation and merges newly extracted terms after translation (before the `finally` cleanup).

**Tech Stack:** Python 3, Flask, pymupdf, pdf2zh-next (unchanged), csv (stdlib), pathlib

## Global Constraints

- Do not modify pdf2zh-next / babeldoc source code
- Glossary storage path: `CACHE_DIR/<pdf_hash>/cumulative_glossary.csv`
- Merge strategy: majority vote on `target` per `source` column
- Static glossary (`docs/glossary.csv`) and cumulative glossary coexist via comma-separated `glossaries` param
- Merge must execute before `finally` block's `shutil.rmtree(output_dir)`
- CSV columns: `source,target`
- First translation: cumulative CSV absent → skip loading, proceed normally

---

### Task 1: Add `glossary_cache_path` property to `AppState` ✅

**Files:**
- Modify: `state.py:9-22` (AppState class body)
- Test: `tests/test_state.py`

**Interfaces:**
- Produces: `AppState.glossary_cache_path` → `Path | None`

- [ ] **Step 1: Write the failing test**

In `tests/test_state.py`, add a new test after the existing `test_translated_pages_tracking`:

```python
def test_glossary_cache_path_no_pdf(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    state = AppState(cache_dir)
    assert state.glossary_cache_path is None

def test_glossary_cache_path_after_open(sample_pdf, tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    state = AppState(cache_dir)
    from services import sha256
    state.open_pdf(str(sample_pdf), sha256)
    expected = cache_dir / state.pdf_hash
    assert state.glossary_cache_path == expected
    state._close_docs()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_state.py::test_glossary_cache_path_no_pdf tests/test_state.py::test_glossary_cache_path_after_open -v`

Expected: FAIL — `AttributeError: 'AppState' object has no attribute 'glossary_cache_path'`

- [ ] **Step 3: Add the `glossary_cache_path` property**

In `state.py`, add after the `translated_pages` property (after line 53):

```python
    @property
    def glossary_cache_path(self) -> Path | None:
        if self._pdf_hash is None:
            return None
        return self._cache_dir / self._pdf_hash
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_state.py::test_glossary_cache_path_no_pdf tests/test_state.py::test_glossary_cache_path_after_open -v`

Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add state.py tests/test_state.py
git commit -m "feat(state): add glossary_cache_path property to AppState"
```

---

### Task 2: Create `merge_glossary_csvs` in `glossary_merger.py`

**Files:**
- Create: `glossary_merger.py`
- Test: `tests/test_glossary_merger.py`

**Interfaces:**
- Produces: `merge_glossary_csvs(cumulative_path: Path, auto_extracted_path: Path) -> None`

- [ ] **Step 1: Write the failing test suite**

Create `tests/test_glossary_merger.py`:

```python
import csv
import tempfile
from pathlib import Path

from glossary_merger import merge_glossary_csvs


def write_csv(path: Path, rows: list[tuple[str, str]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["source", "target"])
        for source, target in rows:
            w.writerow([source, target])


def read_csv(path: Path) -> list[tuple[str, str]]:
    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [(row["source"], row["target"]) for row in reader]


def test_first_merge_creates_cumulative():
    with tempfile.TemporaryDirectory() as tmp:
        cumulative = Path(tmp) / "cumulative_glossary.csv"
        auto = Path(tmp) / "auto.csv"
        write_csv(auto, [("waveguide", "波导"), ("laser", "激光")])

        merge_glossary_csvs(cumulative, auto)

        rows = read_csv(cumulative)
        assert len(rows) == 2
        assert ("waveguide", "波导") in rows
        assert ("laser", "激光") in rows


def test_append_merge_with_voting():
    with tempfile.TemporaryDirectory() as tmp:
        cumulative = Path(tmp) / "cumulative_glossary.csv"
        auto = Path(tmp) / "auto.csv"

        write_csv(cumulative, [("waveguide", "波导"), ("laser", "激光")])
        write_csv(auto, [("waveguide", "波导"), ("laser", "雷射"), ("grating", "光栅")])

        merge_glossary_csvs(cumulative, auto)

        rows = read_csv(cumulative)
        assert len(rows) == 3
        assert ("waveguide", "波导") in rows
        assert ("laser", "激光") in rows          # incumbent wins by count
        assert ("grating", "光栅") in rows


def test_auto_empty_does_not_change_cumulative():
    with tempfile.TemporaryDirectory() as tmp:
        cumulative = Path(tmp) / "cumulative_glossary.csv"
        auto = Path(tmp) / "auto.csv"

        write_csv(cumulative, [("waveguide", "波导")])
        write_csv(auto, [])  # header only, no data rows

        merge_glossary_csvs(cumulative, auto)

        rows = read_csv(cumulative)
        assert rows == [("waveguide", "波导")]


def test_auto_missing_does_not_create_empty_cumulative():
    with tempfile.TemporaryDirectory() as tmp:
        cumulative = Path(tmp) / "cumulative_glossary.csv"
        auto = Path(tmp) / "auto.csv"
        # auto does not exist

        merge_glossary_csvs(cumulative, auto)

        assert not cumulative.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_glossary_merger.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'glossary_merger'`

- [ ] **Step 3: Implement `glossary_merger.py`**

Create `glossary_merger.py`:

```python
import csv
import logging
from collections import defaultdict
from pathlib import Path

logger = logging.getLogger("pdf_reader")


def merge_glossary_csvs(cumulative_path: Path, auto_extracted_path: Path) -> None:
    if not auto_extracted_path.exists():
        return

    source_targets: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    if cumulative_path.exists():
        try:
            with open(cumulative_path, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    source = row.get("source", "").strip()
                    target = row.get("target", "").strip()
                    if source and target:
                        source_targets[source][target] += 1
        except Exception:
            logger.warning("Failed to read cumulative glossary, starting fresh", exc_info=True)

    try:
        with open(auto_extracted_path, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                source = row.get("source", "").strip()
                target = row.get("target", "").strip()
                if source and target:
                    source_targets[source][target] += 1
    except Exception:
        logger.warning("Failed to read auto-extracted glossary, skipping merge", exc_info=True)
        return

    if not source_targets:
        return

    try:
        with open(cumulative_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["source", "target"])
            for source, targets in sorted(source_targets.items()):
                best_target = max(targets, key=lambda t: targets[t])
                writer.writerow([source, best_target])
    except Exception:
        logger.warning("Failed to write cumulative glossary", exc_info=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_glossary_merger.py -v`

Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add glossary_merger.py tests/test_glossary_merger.py
git commit -m "feat: add merge_glossary_csvs with majority-vote merge logic"
```

---

### Task 3: Add `glossary_paths` parameter to `build_settings`

**Files:**
- Modify: `services.py:71-100` (build_settings function)
- Test: `tests/test_services.py`

**Interfaces:**
- Consumes: (nothing new — changes the signature of an existing function)
- Produces: `build_settings(single_page_pdf, user_prompt=None, output_dir=None, glossary_paths=None) -> SettingsModel`

- [ ] **Step 1: Write the failing test**

In `tests/test_services.py`, add after the existing `test_build_settings_without_output_dir`:

```python
def test_build_settings_with_glossary_paths(mock_config):
    settings = build_settings("dummy.pdf", glossary_paths=["/a/one.csv", "/b/two.csv"])
    assert settings.translation.glossaries == "/a/one.csv,/b/two.csv"

def test_build_settings_glossary_paths_none(mock_config):
    settings = build_settings("dummy.pdf")
    assert getattr(settings.translation, "glossaries", None) is None

def test_build_settings_glossary_paths_empty_list(mock_config):
    settings = build_settings("dummy.pdf", glossary_paths=[])
    assert getattr(settings.translation, "glossaries", None) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_services.py::test_build_settings_with_glossary_paths tests/test_services.py::test_build_settings_glossary_paths_none tests/test_services.py::test_build_settings_glossary_paths_empty_list -v`

Expected: FAIL — `TypeError: build_settings() got an unexpected keyword argument 'glossary_paths'`

- [ ] **Step 3: Modify `build_settings` signature and glossaries logic**

In `services.py`, change the `build_settings` function signature and glossaries block at lines 71-91.

Replace:

```python
def build_settings(
    single_page_pdf: str,
    user_prompt: str | None = None,
    output_dir: str | None = None,
) -> SettingsModel:
```

With:

```python
def build_settings(
    single_page_pdf: str,
    user_prompt: str | None = None,
    output_dir: str | None = None,
    glossary_paths: list[str] | None = None,
) -> SettingsModel:
```

Then replace the glossaries block from lines 86-87:

```python
    if config.GLOSSARY_PATH.exists() and config.GLOSSARY_PATH.stat().st_size > 0:
        translation_kwargs["glossaries"] = str(config.GLOSSARY_PATH)
```

With:

```python
    paths = []
    if config.GLOSSARY_PATH.exists() and config.GLOSSARY_PATH.stat().st_size > 0:
        paths.append(str(config.GLOSSARY_PATH))
    if glossary_paths:
        paths.extend(glossary_paths)
    if paths:
        translation_kwargs["glossaries"] = ",".join(paths)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_services.py -v`

Expected: ALL PASS (the 3 new tests + all 17 existing tests)

- [ ] **Step 5: Commit**

```bash
git add services.py tests/test_services.py
git commit -m "feat(services): add glossary_paths parameter to build_settings"
```

---

### Task 4: Integrate glossary loading and merging into `translate_page`

**Files:**
- Modify: `routes.py:91-226` (translate_page function and its inner `generate()`)
- Modify: `routes.py:1-10` (imports block)

**Interfaces:**
- Consumes: `AppState.glossary_cache_path` (from Task 1), `merge_glossary_csvs` (from Task 2), `build_settings(glossary_paths=...)` (from Task 3)
- Produces: (no new public interfaces — internal integration)

- [ ] **Step 1: Add imports to `routes.py`**

In `routes.py`, the current imports are (lines 1-25):

```python
import asyncio
import io
import json
import os
import queue
import shutil
import tempfile
import threading
from pathlib import Path

import pymupdf
from flask import (...)
from pdf2zh_next import do_translate_async_stream

import config
from services import build_settings, render_page, sha256
```

Add `import logging` after line 6 (`import shutil`):

```python
import logging
```

And add after line 25 (`from services import build_settings, render_page, sha256`):

```python
from glossary_merger import merge_glossary_csvs
```

- [ ] **Step 2: Add glossary loading before translation starts**

In `translate_page()`, inside the `generate()` function, after computing `single_page_pdf` (after the line `settings = build_settings(...)`) — actually, glossary loading needs to happen **before** `build_settings()` is called. So locate this line in `generate()`:

```python
            settings = build_settings(str(single_page_pdf), user_prompt, output_dir=output_dir)
```

Replace it with:

```python
            cumulative_glossary_path = state.glossary_cache_path
            glossary_paths: list[str] | None = None
            if cumulative_glossary_path is not None:
                cumulative_file = cumulative_glossary_path / "cumulative_glossary.csv"
                if cumulative_file.exists() and cumulative_file.stat().st_size > 0:
                    glossary_paths = [str(cumulative_file)]

            settings = build_settings(
                str(single_page_pdf),
                user_prompt,
                output_dir=output_dir,
                glossary_paths=glossary_paths,
            )
```

- [ ] **Step 3: Add glossary merge after translation completes**

In `generate()`, after the successful translation result block — after line 202 (`state.replace_page(str(translated_pdf), page)`) and before the progress/finish SSE yields — add the merge logic.

Locate this block (lines 196-213):

```python
            try:
                translated_pdf = translate_result.mono_pdf_path
                if translated_pdf is None and translate_result.dual_pdf_path is not None:
                    translated_pdf = translate_result.dual_pdf_path

                if translated_pdf is not None:
                    state.replace_page(str(translated_pdf), page)
                else:
                    yield f"data: {json.dumps({'type': 'error', 'error': 'no output PDF'})}\n\n"
                    return
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
                return

            yield "data: " + json.dumps({
                "type": "progress", "progress": 100,
                "stage": "finish", "stage_current": 0, "stage_total": 0,
            }) + "\n\n"
            yield f"data: {json.dumps({'type': 'finish', 'progress': 100})}\n\n"
```

Insert glossary merge between `state.replace_page(...)` and the progress yields. The modified block becomes:

```python
            try:
                translated_pdf = translate_result.mono_pdf_path
                if translated_pdf is None and translate_result.dual_pdf_path is not None:
                    translated_pdf = translate_result.dual_pdf_path

                if translated_pdf is not None:
                    state.replace_page(str(translated_pdf), page)
                else:
                    yield f"data: {json.dumps({'type': 'error', 'error': 'no output PDF'})}\n\n"
                    return
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
                return

            if (
                cumulative_glossary_path is not None
                and translate_result.auto_extracted_glossary_path
            ):
                auto_path = Path(translate_result.auto_extracted_glossary_path)
                cumulative_file = cumulative_glossary_path / "cumulative_glossary.csv"
                try:
                    merge_glossary_csvs(cumulative_file, auto_path)
                except Exception:
                    logging.getLogger("pdf_reader").warning(
                        "Failed to merge glossary for page %d", page, exc_info=True
                    )

            yield "data: " + json.dumps({
                "type": "progress", "progress": 100,
                "stage": "finish", "stage_current": 0, "stage_total": 0,
            }) + "\n\n"
            yield f"data: {json.dumps({'type': 'finish', 'progress': 100})}\n\n"
```

- [ ] **Step 4: Verify existing tests still pass**

Run: `pytest tests/ -v`

Expected: ALL PASS (no regressions)

- [ ] **Step 5: Commit**

```bash
git add routes.py
git commit -m "feat(routes): integrate cumulative glossary loading and merging into translate_page"
```

---

### Task 5: Manual verification

**Files:**
- (no code changes — manual test only)

**Acceptance Criteria:**
- Translate page 5 of any PDF → `CACHE_DIR/<pdf_hash>/cumulative_glossary.csv` created with extracted terms
- Translate page 10 of the same PDF → cumulative glossary loaded (more terms in CSV), newly merged terms present
- Open a different PDF, translate → uses independent cumulative glossary file under a different hash subdirectory
- Translate a page with no extracted terms → cumulative glossary unchanged

- [ ] **Step 1: Manual test — first page in session**

1. Start the application: `python app.py`
2. Open a multi-page PDF via the API
3. Translate page 5: `POST /api/translate/5`
4. Confirm `CACHE_DIR/<hash>/cumulative_glossary.csv` exists and has entries
5. Inspect the CSV content — should have `source,target` rows from the page

- [ ] **Step 2: Manual test — second page accumulates**

1. In the same session, translate page 10: `POST /api/translate/10`
2. Confirm `cumulative_glossary.csv` has more rows (or at least as many as before)
3. Inspect — terms from page 5 and page 10 both present, no duplicate `source` rows

- [ ] **Step 3: Manual test — different PDF isolation**

1. Open a different PDF (different file path)
2. Translate page 1
3. Confirm a **new** `CACHE_DIR/<different_hash>/cumulative_glossary.csv` is created
4. Confirm the previous PDF's glossary is unchanged (different hash directory)

- [ ] **Step 4: Commit if no issues found**

No code to commit — verification only. If issues found, fix in new Task.

---

### Task 6: Final regression test run

**Files:**
- (no changes)

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/ -v`

Expected: ALL PASS

- [ ] **Step 2: Commit**

```bash
git add -A
git commit -m "chore: post-integration test verification"
```
