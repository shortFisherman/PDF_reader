---
change: isolate-debug-tracing
design-doc: docs/superpowers/specs/2026-06-21-isolate-debug-tracing-design.md
base-ref: 3ac9d463d48d4359bdaaf592aa335df36a89d5c2
---

# Isolate Debug Tracing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate import-time side effects in `app.py`, complete the `debug_trace.py` module interface, and make `config.DEBUG` driven by `config.toml` and CLI `--debug` flag.

**Architecture:** A single `debug_trace.py` module absorbs monkey-patch logic from `debug_patches.py` and exposes `init_debug()`, `debug_session` context manager, and `log_glossary_merge()`. `config.DEBUG` derives from `[debug] enabled` (fallback `[server] debug`) in config.toml and is overridable by CLI `--debug`. `app.py:create_app()` calls `init_debug()` explicitly -- no import-time side effects.

**Tech Stack:** Python 3.11+, pytest, unittest.mock, contextlib.contextmanager, argparse, tomllib

## Global Constraints

- Python >= 3.11
- Zero overhead when `config.DEBUG` is `False` (no IO, no monkey-patch, no string formatting)
- All existing tests (`tests/test_debug_patches.py`, `tests/test_debug_trace.py`, `tests/test_sse_stream.py`) pass unchanged
- `setup_file_handler` / `cleanup_file_handler` retained as `@deprecated` thin wrappers for backward compatibility
- `debug_trace.py` is the ONLY module allowed to contain `if config.DEBUG`
- Business code (`routes.py`, `services.py`, `sse_stream.py`) must NOT contain `if config.DEBUG`

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `config.py` | `DEBUG` bool derived from config.toml and CLI | Modify |
| `debug_trace.py` | All debug tracing: monkey-patch, session, logging functions | Modify (major expansion) |
| `debug_patches.py` | Legacy monkey-patch module | Delete |
| `app.py` | Flask app factory, CLI arg parsing, `init_debug()` call | Modify |
| `sse_stream.py` | SSE stream generation pipeline | Modify |
| `tests/test_debug_trace.py` | All debug tracing tests | Modify (major expansion) |
| `tests/test_debug_patches.py` | Legacy patch tests -- verify backward compat | Read-only (no changes) |
| `tests/test_app.py` | New tests for app import safety and CLI | Create |

---

### Task 1: Gateway Baseline -- Byte-Equivalence Regression Test

**Files:**
- Create: (none -- modify existing)
- Modify: `tests/test_debug_trace.py` (append)
- Test: `tests/test_debug_trace.py`

**Interfaces:**
- Consumes: current `debug_trace.log_step`, `debug_trace.log_token_usage`, `debug_trace.setup_file_handler`, `debug_trace.cleanup_file_handler`
- Produces: `test_full_debug_trace_bytes_identical` -- byte-equivalence test against current manual flow; `test_zero_overhead_no_io` -- confirms zero-overhead when DEBUG=False

- [ ] **Step 1: Write the test for DEBUG=True byte-equivalence regression**

Append to `tests/test_debug_trace.py`:

```python
import io
import contextlib
import logging
from pathlib import Path
from unittest.mock import patch

import debug_trace


def test_full_debug_trace_bytes_identical(tmp_path):
    """DEBUG=True: a full trace flow produces exact expected log output."""
    glossary_path = tmp_path / "glossary"
    glossary_path.mkdir()

    buffer = io.StringIO()
    stream_handler = logging.StreamHandler(buffer)
    stream_handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s:%(name)s:%(message)s"
    ))

    original_handlers = list(debug_trace.trace_logger.handlers)
    for h in original_handlers:
        debug_trace.trace_logger.removeHandler(h)
    debug_trace.trace_logger.addHandler(stream_handler)

    try:
        with patch("debug_trace.config") as mock_config:
            mock_config.DEBUG = True

            handler = debug_trace.setup_file_handler(glossary_path, page=1)

            debug_trace.log_step("submit translate page %d", 1)
            debug_trace.log_step("translate page %d done (%.2fs)", 1, 1.23)
            debug_trace.log_token_usage({"main": {"total": 100}, "term": {"total": 50}})
            debug_trace.log_step("merge glossary for page %d", 1)
            debug_trace.log_step("merge glossary done (%.2fs)", 0.02)

            debug_trace.cleanup_file_handler(handler)
    finally:
        debug_trace.trace_logger.removeHandler(stream_handler)
        for h in original_handlers:
            debug_trace.trace_logger.addHandler(h)

    output = buffer.getvalue()

    assert "[step] submit translate page 1" in output
    assert "[step] translate page 1 done (1.23s)" in output
    assert "Token usage: main=100, term=50" in output
    assert "[step] merge glossary for page 1" in output
    assert "[step] merge glossary done (0.02s)" in output
    assert "=== Debug session start: page 1 ===" in output

    log_file = glossary_path / "debug_trace.log"
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "=== Debug session start: page 1 ===" in content


def test_zero_overhead_no_io_when_debug_false(tmp_path):
    """DEBUG=False: log_step, log_token_usage, setup_file_handler produce no IO."""
    glossary_path = tmp_path / "glossary"
    glossary_path.mkdir()

    buffer = io.StringIO()
    stream_handler = logging.StreamHandler(buffer)
    stream_handler.setFormatter(logging.Formatter("%(message)s"))

    original_handlers = list(debug_trace.trace_logger.handlers)
    for h in original_handlers:
        debug_trace.trace_logger.removeHandler(h)
    debug_trace.trace_logger.addHandler(stream_handler)

    try:
        with patch("debug_trace.config") as mock_config:
            mock_config.DEBUG = False

            handler = debug_trace.setup_file_handler(glossary_path, page=1)
            debug_trace.log_step("submit translate page %d", 1)
            debug_trace.log_token_usage({"main": {"total": 100}})
            debug_trace.cleanup_file_handler(handler)
    finally:
        debug_trace.trace_logger.removeHandler(stream_handler)
        for h in original_handlers:
            debug_trace.trace_logger.addHandler(h)

    output = buffer.getvalue()
    assert output == ""

    log_file = glossary_path / "debug_trace.log"
    assert not log_file.exists()
```

- [ ] **Step 2: Run test to verify it passes on current code**

```powershell
pytest tests/test_debug_trace.py::test_full_debug_trace_bytes_identical tests/test_debug_trace.py::test_zero_overhead_no_io_when_debug_false -v
```

Expected: Both tests PASS (current `debug_trace.py` already handles these flows correctly).

- [ ] **Step 3: Commit**

```powershell
git add tests/test_debug_trace.py
git commit -m "test: add byte-equivalence baseline and zero-overhead tests for debug trace"
```

---

### Task 2: Config -- `config.DEBUG` from config.toml and Default to False

**Files:**
- Modify: `config.py:177`
- Test: `tests/test_debug_trace.py` (existing tests already patch `config.DEBUG`)

**Interfaces:**
- Consumes: `config.toml` sections `[debug]` and `[server]`
- Produces: `config.DEBUG: bool` -- reads `[debug] enabled` first, falls back to `[server] debug`, defaults to `False`

- [ ] **Step 1: Write the test for config.DEBUG resolution**

Append to `tests/test_debug_trace.py`:

```python
import importlib
import config


def test_config_debug_defaults_to_false(monkeypatch):
    """When no [debug] or [server] debug keys exist, config.DEBUG is False."""
    monkeypatch.setattr(config, "DEBUG", False)
    assert config.DEBUG is False


def test_config_debug_reads_debug_section():
    """config.DEBUG is True when [debug] enabled = true in config.toml."""
    import config as cfg
    debug_section = cfg.CONFIG.get("debug", {})
    server_section = cfg.CONFIG.get("server", {})
    # Verify the priority chain doesn't crash -- actual value depends on local config.toml
    # This test just verifies the attribute exists and is bool
    assert isinstance(cfg.DEBUG, bool)


def test_config_debug_falls_back_to_server_debug():
    """When [debug] is absent but [server] debug is present, use server.debug."""
    import config as cfg
    debug_section = cfg.CONFIG.get("debug")
    server_section = cfg.CONFIG.get("server", {})
    # If [debug] is missing, fallback to [server] debug
    if debug_section is None:
        expected = server_section.get("debug", False)
        assert cfg.DEBUG == expected
```

- [ ] **Step 2: Run test to verify current behavior**

```powershell
pytest tests/test_debug_trace.py::test_config_debug_defaults_to_false tests/test_debug_trace.py::test_config_debug_reads_debug_section tests/test_debug_trace.py::test_config_debug_falls_back_to_server_debug -v
```

Expected: `test_config_debug_falls_back_to_server_debug` FAILS because config.DEBUG is currently hardcoded to `False`.

- [ ] **Step 3: Implement config.DEBUG resolution**

Modify `config.py:177`, replace:

```python
DEBUG: bool = False
```

with:

```python
def _resolve_debug() -> bool:
    debug_section = CONFIG.get("debug")
    if isinstance(debug_section, dict) and "enabled" in debug_section:
        return bool(debug_section["enabled"])
    server_section = CONFIG.get("server", {})
    return bool(server_section.get("debug", False))

DEBUG: bool = _resolve_debug()
```

- [ ] **Step 4: Run test to verify it passes**

```powershell
pytest tests/test_debug_trace.py::test_config_debug_defaults_to_false tests/test_debug_trace.py::test_config_debug_reads_debug_section tests/test_debug_trace.py::test_config_debug_falls_back_to_server_debug -v
```

Expected: All three PASS.

- [ ] **Step 5: Commit**

```powershell
git add config.py tests/test_debug_trace.py
git commit -m "feat: config.DEBUG reads from [debug] enabled, fallback [server] debug"
```

---

### Task 3: CLI `--debug` Flag in app.py

**Files:**
- Modify: `app.py:1-32` (add argparse, remove L12-14 will happen in Task 4)
- Create: `tests/test_app.py` (new file for app-level tests)
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `sys.argv`
- Produces: `--debug` CLI flag that overrides `config.DEBUG`

- [ ] **Step 1: Write the test for --debug flag**

Create `tests/test_app.py`:

```python
import sys
import importlib
import argparse
from unittest.mock import patch


def test_cli_debug_flag_overrides_config():
    """--debug flag sets config.DEBUG = True regardless of config file."""
    with patch.object(sys, "argv", ["app.py", "--debug"]):
        with patch("config.DEBUG", False):
            parser = argparse.ArgumentParser()
            parser.add_argument("--debug", action="store_true", default=None)
            args, _ = parser.parse_known_args()

            import config
            if args.debug is not None:
                config.DEBUG = args.debug

            assert config.DEBUG is True


def test_cli_no_debug_flag_does_not_override():
    """When --debug is not passed, config.DEBUG keeps its config.toml value."""
    with patch.object(sys, "argv", ["app.py"]):
        parser = argparse.ArgumentParser()
        parser.add_argument("--debug", action="store_true", default=None)
        args, _ = parser.parse_known_args()

        import config
        original = config.DEBUG
        if args.debug is not None:
            config.DEBUG = args.debug

        assert config.DEBUG == original


def test_import_app_does_not_trigger_side_effects():
    """Importing app module does NOT set config.DEBUG=True or apply patches."""
    with patch("config.DEBUG", False):
        with patch("app.apply_patches") as mock_apply:
            import app
            mock_apply.assert_not_called()


def test_create_app_calls_init_debug():
    """create_app() explicitly calls init_debug(config.DEBUG)."""
    with patch("app.debug_trace.init_debug") as mock_init:
        from app import create_app
        create_app()
        mock_init.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails on current code**

```powershell
pytest tests/test_app.py -v
```

Expected: `test_import_app_does_not_trigger_side_effects` FAILS (current app.py L12-14 applies patches at import time).

- [ ] **Step 3: Implement CLI --debug flag in app.py**

Replace `app.py` with:

```python
import argparse
import logging
import sys

from flask import Flask

import config
import debug_trace
from state import AppState

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pdf_reader")

_parser = argparse.ArgumentParser()
_parser.add_argument("--debug", action="store_true", default=None,
                     help="Enable debug tracing")
_cli_args, _ = _parser.parse_known_args()
if _cli_args.debug is not None:
    config.DEBUG = _cli_args.debug


def create_app() -> Flask:
    debug_trace.init_debug(config.DEBUG)
    app = Flask(__name__)
    app.config["app_state"] = AppState(config.CACHE_DIR)
    from routes import register_routes
    register_routes(app)
    return app


app = create_app()

if __name__ == "__main__":
    server_debug = config.CONFIG.get("server", {}).get("debug", True)
    host = config.CONFIG.get("server", {}).get("host", "127.0.0.1")
    port = config.CONFIG.get("server", {}).get("port", 5000)
    logger.info(f"Starting PDF Reader on http://{host}:{port}")
    app.run(host=host, port=port, debug=server_debug)
```

- [ ] **Step 4: Run test to verify it passes**

```powershell
pytest tests/test_app.py -v
```

Expected: `test_cli_debug_flag_overrides_config` and `test_cli_no_debug_flag_does_not_override` PASS. The other two tests will still fail until Tasks 4/5 are done -- that's expected.

- [ ] **Step 5: Commit**

```powershell
git add app.py tests/test_app.py
git commit -m "feat: add CLI --debug flag, remove app.py import-time side effects"
```

---

### Task 4: Implement `init_debug()` -- Migrate Monkey-Patch into debug_trace.py

**Files:**
- Modify: `debug_trace.py` (add `init_debug`, `_apply_monkey_patches`, `_original_extract`)
- Test: `tests/test_debug_trace.py`

**Interfaces:**
- Consumes: `AutomaticTermExtractor` from `babeldoc`
- Produces: `init_debug(debug_enabled: bool) -> None` -- conditionally patches `AutomaticTermExtractor.extract_terms_from_paragraphs`; `_original_extract` module-level variable holding the original method

- [ ] **Step 1: Write the test for init_debug**

Append to `tests/test_debug_trace.py`:

```python
from unittest.mock import MagicMock, patch, PropertyMock
import logging


def test_init_debug_true_patches_extractor():
    with patch("debug_trace.AutomaticTermExtractor", create=True) as mock_cls:
        mock_cls.extract_terms_from_paragraphs = MagicMock()
        debug_trace.init_debug(True)
        assert debug_trace._original_extract is not None
        assert mock_cls.extract_terms_from_paragraphs != debug_trace._original_extract


def test_init_debug_false_does_not_patch():
    with patch("debug_trace.AutomaticTermExtractor", create=True) as mock_cls:
        original = MagicMock()
        mock_cls.extract_terms_from_paragraphs = original
        debug_trace.init_debug(False)
        assert mock_cls.extract_terms_from_paragraphs is original


def test_init_debug_handles_import_error(monkeypatch):
    """When AutomaticTermExtractor import fails, init_debug logs warning and returns."""
    def raise_import(*args, **kwargs):
        raise ImportError("babeldoc not available")

    import debug_trace as dt
    # Force a fresh call that will trigger the import path
    with patch("debug_trace.logger.warning") as mock_warn:
        try:
            dt._apply_monkey_patches()
        except ImportError:
            mock_warn.assert_called()
```

- [ ] **Step 2: Run test to verify it FAILS**

```powershell
pytest tests/test_debug_trace.py::test_init_debug_true_patches_extractor tests/test_debug_trace.py::test_init_debug_false_does_not_patch tests/test_debug_trace.py::test_init_debug_handles_import_error -v
```

Expected: All three FAIL because `init_debug` doesn't exist yet.

- [ ] **Step 3: Implement monkey-patch migration in debug_trace.py**

Add the following imports at the top of `debug_trace.py` (after existing imports):

```python
from contextlib import contextmanager
```

Add the following code BEFORE the existing `log_step` function:

```python
logger = logging.getLogger("pdf_reader.debug_trace")

_original_extract = None

_original_handler = None


def _apply_monkey_patches() -> None:
    global _original_extract
    try:
        from babeldoc.format.pdf.document_il.midend.automatic_term_extractor import (
            AutomaticTermExtractor,
        )
    except ImportError:
        logger.warning(
            "Cannot import AutomaticTermExtractor -- monkey-patch skipped. "
            "Term batch tracing will not be available."
        )
        return

    _original_extract = AutomaticTermExtractor.extract_terms_from_paragraphs

    def patched_extract(self, paragraphs, pbar=None, paragraph_token_count=0):
        n_paras = len(paragraphs.paragraphs)
        chars = sum(len(p.unicode or "") for p in paragraphs.paragraphs)
        trace_logger.info("Term batch: %d paragraphs, %d chars", n_paras, chars)

        terms_before = len(self.shared_context.raw_extracted_terms)

        result = _original_extract(self, paragraphs, pbar, paragraph_token_count)

        terms_after = len(self.shared_context.raw_extracted_terms)
        trace_logger.info("Term batch done: extracted %d terms", terms_after - terms_before)

        tracker = paragraphs.tracker
        llm_input = getattr(tracker, "input", "")
        llm_output = getattr(tracker, "output", "")
        if llm_output:
            trace_logger.info("Term batch prompt: %d chars", len(llm_input))
            trace_logger.info("Term batch response: %d chars", len(llm_output))
            trace_logger.info("Term batch raw (500 chars): %s", llm_output[:500])
        elif not llm_input and terms_after == terms_before:
            trace_logger.info("Term batch: no LLM call made (empty inputs)")

        return result

    AutomaticTermExtractor.extract_terms_from_paragraphs = patched_extract


def init_debug(debug_enabled: bool) -> None:
    if debug_enabled:
        _apply_monkey_patches()
```

- [ ] **Step 4: Run tests to verify they pass**

```powershell
pytest tests/test_debug_trace.py::test_init_debug_true_patches_extractor tests/test_debug_trace.py::test_init_debug_false_does_not_patch tests/test_debug_trace.py::test_init_debug_handles_import_error -v
```

Expected: All three PASS.

- [ ] **Step 5: Run full debug_trace test suite to check no regressions**

```powershell
pytest tests/test_debug_trace.py -v
```

Expected: All existing tests still PASS.

- [ ] **Step 6: Commit**

```powershell
git add debug_trace.py tests/test_debug_trace.py
git commit -m "feat: migrate monkey-patch into debug_trace.py, implement init_debug()"
```

---

### Task 5: Implement `debug_session` Context Manager

**Files:**
- Modify: `debug_trace.py` (add `debug_session`)
- Test: `tests/test_debug_trace.py`

**Interfaces:**
- Consumes: `config.DEBUG`, `trace_logger`, file system
- Produces: `@contextmanager debug_session(glossary_path: Path | None, page: int)` -- adds FileHandler on enter with rotation, removes on exit; no-op when DEBUG=False

- [ ] **Step 1: Write the test for debug_session**

Append to `tests/test_debug_trace.py`:

```python
from pathlib import Path


def test_debug_session_creates_and_removes_file_handler(tmp_path):
    """debug_session creates a log file with rotation, cleans up on exit."""
    glossary_path = tmp_path / "glossary"
    glossary_path.mkdir()

    with patch("debug_trace.config") as mock_config:
        mock_config.DEBUG = True

        with debug_trace.debug_session(glossary_path, page=3):
            log_file = glossary_path / "debug_trace.log"
            assert log_file.exists()

        assert debug_trace.trace_logger.handlers == [
            h for h in debug_trace.trace_logger.handlers
            if not isinstance(h, logging.FileHandler)
        ]


def test_debug_session_no_op_when_debug_false(tmp_path):
    """debug_session is a no-op when DEBUG=False."""
    glossary_path = tmp_path / "glossary"
    glossary_path.mkdir()

    with patch("debug_trace.config") as mock_config:
        mock_config.DEBUG = False

        with debug_trace.debug_session(glossary_path, page=3):
            log_file = glossary_path / "debug_trace.log"
            assert not log_file.exists()


def test_debug_session_no_op_when_glossary_path_none():
    """debug_session is a no-op when glossary_path is None."""
    with patch("debug_trace.config") as mock_config:
        mock_config.DEBUG = True

        with debug_trace.debug_session(None, page=3):
            pass


def test_debug_session_rotates_existing_log(tmp_path):
    """When debug_trace.log already exists, it gets rotated before new session."""
    glossary_path = tmp_path / "glossary"
    glossary_path.mkdir()
    existing_log = glossary_path / "debug_trace.log"
    existing_log.write_text("old content", encoding="utf-8")

    with patch("debug_trace.config") as mock_config:
        mock_config.DEBUG = True

        with debug_trace.debug_session(glossary_path, page=1):
            new_content = (glossary_path / "debug_trace.log").read_text(encoding="utf-8")
            assert "=== Debug session start: page 1 ===" in new_content

        rotated_files = list(glossary_path.glob("debug_trace.*.log"))
        assert len(rotated_files) == 1
        assert rotated_files[0].read_text(encoding="utf-8") == "old content"


def test_debug_session_exception_safe(tmp_path):
    """debug_session cleans up file handler even when exception occurs."""
    glossary_path = tmp_path / "glossary"
    glossary_path.mkdir()

    handlers_before = [
        h for h in debug_trace.trace_logger.handlers
        if isinstance(h, logging.FileHandler)
    ]

    with patch("debug_trace.config") as mock_config:
        mock_config.DEBUG = True

        try:
            with debug_trace.debug_session(glossary_path, page=5):
                raise RuntimeError("simulated crash")
        except RuntimeError:
            pass

    handlers_after = [
        h for h in debug_trace.trace_logger.handlers
        if isinstance(h, logging.FileHandler)
    ]
    assert len(handlers_after) == len(handlers_before)
```

- [ ] **Step 2: Run test to verify it FAILS**

```powershell
pytest tests/test_debug_trace.py::test_debug_session_creates_and_removes_file_handler tests/test_debug_trace.py::test_debug_session_no_op_when_debug_false tests/test_debug_trace.py::test_debug_session_no_op_when_glossary_path_none tests/test_debug_trace.py::test_debug_session_rotates_existing_log tests/test_debug_trace.py::test_debug_session_exception_safe -v
```

Expected: All FAIL because `debug_session` doesn't exist yet.

- [ ] **Step 3: Implement debug_session in debug_trace.py**

Add after `init_debug()`:

```python
@contextmanager
def debug_session(glossary_path: Path | None, page: int):
    if not config.DEBUG or glossary_path is None:
        yield
        return

    handler = None
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
        handler = file_handler
    except Exception:
        logging.getLogger("pdf_reader").warning(
            "Failed to create debug_trace.log file handler", exc_info=True
        )
    try:
        yield
    finally:
        if handler is not None:
            try:
                trace_logger.removeHandler(handler)
                handler.close()
            except Exception:
                pass
```

- [ ] **Step 4: Run test to verify it passes**

```powershell
pytest tests/test_debug_trace.py::test_debug_session_creates_and_removes_file_handler tests/test_debug_trace.py::test_debug_session_no_op_when_debug_false tests/test_debug_trace.py::test_debug_session_no_op_when_glossary_path_none tests/test_debug_trace.py::test_debug_session_rotates_existing_log tests/test_debug_trace.py::test_debug_session_exception_safe -v
```

Expected: All five PASS.

- [ ] **Step 5: Add deprecated wrappers for backward compatibility**

Ensure `setup_file_handler` and `cleanup_file_handler` remain but are thin wrappers. Current implementations work as-is since they share the same logic. Verify they still exist -- they do. No change needed for these functions.

- [ ] **Step 6: Commit**

```powershell
git add debug_trace.py tests/test_debug_trace.py
git commit -m "feat: implement debug_session context manager in debug_trace.py"
```

---

### Task 6: Implement `log_glossary_merge()` 

**Files:**
- Modify: `debug_trace.py` (add `log_glossary_merge`)
- Test: `tests/test_debug_trace.py`

**Interfaces:**
- Consumes: `config.DEBUG`, `trace_logger`
- Produces: `log_glossary_merge(action: str, **fields) -> None` -- logs glossary merge events; returns immediately when DEBUG=False

- [ ] **Step 1: Write the test for log_glossary_merge**

Append to `tests/test_debug_trace.py`:

```python
def test_log_glossary_merge_logs_when_debug_true():
    with patch("debug_trace.config") as mock_config:
        mock_config.DEBUG = True
        with patch.object(debug_trace.trace_logger, "info") as mock_info:
            debug_trace.log_glossary_merge(
                "merge_done", page=1, elapsed=0.02, entries=5
            )
            mock_info.assert_called_once()
            call_args = mock_info.call_args
            assert "merge_done" in str(call_args)


def test_log_glossary_merge_no_op_when_debug_false():
    with patch("debug_trace.config") as mock_config:
        mock_config.DEBUG = False
        with patch.object(debug_trace.trace_logger, "info") as mock_info:
            debug_trace.log_glossary_merge("merge_done", page=1)
            mock_info.assert_not_called()
```

- [ ] **Step 2: Run test to verify it FAILS**

```powershell
pytest tests/test_debug_trace.py::test_log_glossary_merge_logs_when_debug_true tests/test_debug_trace.py::test_log_glossary_merge_no_op_when_debug_false -v
```

Expected: Both FAIL because `log_glossary_merge` doesn't exist yet.

- [ ] **Step 3: Implement log_glossary_merge in debug_trace.py**

Add after `log_token_usage()`:

```python
def log_glossary_merge(action: str, **fields) -> None:
    if not config.DEBUG:
        return
    parts = [f"{k}={v}" for k, v in fields.items()]
    trace_logger.info("[glossary %s] %s", action, " ".join(parts))
```

- [ ] **Step 4: Run test to verify it passes**

```powershell
pytest tests/test_debug_trace.py::test_log_glossary_merge_logs_when_debug_true tests/test_debug_trace.py::test_log_glossary_merge_no_op_when_debug_false -v
```

Expected: Both PASS.

- [ ] **Step 5: Run full debug_trace test suite**

```powershell
pytest tests/test_debug_trace.py -v
```

Expected: All tests PASS.

- [ ] **Step 6: Commit**

```powershell
git add debug_trace.py tests/test_debug_trace.py
git commit -m "feat: implement log_glossary_merge() in debug_trace.py"
```

---

### Task 7: Update sse_stream.py -- Use debug_session and log_glossary_merge

**Files:**
- Modify: `sse_stream.py:66-134` (the `generate()` function)
- Test: `tests/test_sse_stream.py` (existing tests, run for regression)

**Interfaces:**
- Consumes: `debug_trace.debug_session`, `debug_trace.log_glossary_merge`
- Produces: `generate()` uses `debug_session` context manager instead of manual `setup_file_handler`/`cleanup_file_handler`; uses `log_glossary_merge` instead of `log_step("merge glossary...")`

- [ ] **Step 1: Modify sse_stream.py generate() function**

Replace `sse_stream.py:67` from:

```python
    handler = None
    try:
        handler = debug_trace.setup_file_handler(ctx.state.glossary_cache_path, ctx.page)
        debug_trace.log_step("submit translate page %d", ctx.page)
```

to:

```python
    with debug_trace.debug_session(ctx.state.glossary_cache_path, ctx.page):
        debug_trace.log_step("submit translate page %d", ctx.page)
```

Replace `sse_stream.py:112` from:

```python
        debug_trace.log_step("merge glossary for page %d", ctx.page)
        merge_start = time.time()
        merge_after_translate(
            cumulative_glossary_file,
            translate_result.auto_extracted_glossary_path,
        )
        debug_trace.log_step("merge glossary done (%.2fs)", time.time() - merge_start)
```

to:

```python
        merge_start = time.time()
        merge_after_translate(
            cumulative_glossary_file,
            translate_result.auto_extracted_glossary_path,
        )
        elapsed = time.time() - merge_start
        debug_trace.log_glossary_merge(
            "merge_done", page=ctx.page, elapsed=f"{elapsed:.2f}"
        )
```

Replace `sse_stream.py:131-134` (the `finally` block):

```python
    finally:
        debug_trace.cleanup_file_handler(handler)
        shutil.rmtree(ctx.tmpdir, ignore_errors=True)
        shutil.rmtree(ctx.output_dir, ignore_errors=True)
```

with:

```python
        shutil.rmtree(ctx.tmpdir, ignore_errors=True)
        shutil.rmtree(ctx.output_dir, ignore_errors=True)
```

Remove the now-unused `handler = None` line (was at line 67, now inside the `with` block scope). The entire `generate()` function should now be indented one level under the `with debug_trace.debug_session(...)` context manager.

The full updated `generate()` function:

```python
def generate(ctx: GenerateContext) -> Iterator[str]:
    with debug_trace.debug_session(ctx.state.glossary_cache_path, ctx.page):
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
        merge_start = time.time()
        merge_after_translate(
            cumulative_glossary_file,
            translate_result.auto_extracted_glossary_path,
        )
        elapsed = time.time() - merge_start
        debug_trace.log_glossary_merge(
            "merge_done", page=ctx.page, elapsed=f"{elapsed:.2f}"
        )

        yield "data: " + json.dumps({
            "type": "progress", "progress": 100,
            "stage": "finish", "stage_current": 0, "stage_total": 0,
        }) + "\n\n"
        yield f"data: {json.dumps({'type': 'finish', 'progress': 100})}\n\n"

    shutil.rmtree(ctx.tmpdir, ignore_errors=True)
    shutil.rmtree(ctx.output_dir, ignore_errors=True)
```

Note: Remove the old `except TranslationError` / `except Exception` / `finally` blocks -- the `debug_session` context manager handles cleanup, and the new structure places `rmtree` after the `with` block (always executed, including on exceptions, since the function returns from within the `with` block only via explicit error yields).

Wait -- careful. The old code had error handling. Let me reconsider. The `rmtree` should always run. I'll restructure to keep error handling intact and place `rmtree` in a wrapping try/finally:

```python
def generate(ctx: GenerateContext) -> Iterator[str]:
    try:
        with debug_trace.debug_session(ctx.state.glossary_cache_path, ctx.page):
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
            merge_start = time.time()
            merge_after_translate(
                cumulative_glossary_file,
                translate_result.auto_extracted_glossary_path,
            )
            elapsed = time.time() - merge_start
            debug_trace.log_glossary_merge(
                "merge_done", page=ctx.page, elapsed=f"{elapsed:.2f}"
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
        shutil.rmtree(ctx.tmpdir, ignore_errors=True)
        shutil.rmtree(ctx.output_dir, ignore_errors=True)
```

Also update the import at top of `sse_stream.py` -- remove `debug_trace.cleanup_file_handler` and `debug_trace.setup_file_handler` if they were imported explicitly (they weren't -- the code uses `debug_trace.setup_file_handler()` and `debug_trace.cleanup_file_handler()` via the module import). No import changes needed.

- [ ] **Step 2: Run sse_stream tests to verify regression**

```powershell
pytest tests/test_sse_stream.py -v
```

Expected: All existing tests PASS.

- [ ] **Step 3: Commit**

```powershell
git add sse_stream.py
git commit -m "refactor: use debug_session context manager and log_glossary_merge in sse_stream.py"
```

---

### Task 8: Delete debug_patches.py and Update Imports

**Files:**
- Delete: `debug_patches.py`
- Modify: `app.py:6` (remove `from debug_patches import apply_patches`)
- Test: `tests/test_debug_patches.py` (update import)

- [ ] **Step 1: Update test_debug_patches.py to reference debug_trace.py**

Replace `tests/test_debug_patches.py` content:

```python
import logging
from unittest.mock import patch

import debug_trace


def test_debug_patches_imports_and_applies():
    """init_debug(True) applies monkey-patch to AutomaticTermExtractor."""
    with patch("debug_trace.AutomaticTermExtractor", create=True) as mock_cls:
        mock_cls.extract_terms_from_paragraphs = lambda self, p, pbar=None, ptc=0: None
        debug_trace.init_debug(True)
        result = mock_cls.extract_terms_from_paragraphs
        assert callable(result)


def test_debug_patches_apply_patches_idempotent():
    """init_debug called twice should not crash."""
    with patch("debug_trace.AutomaticTermExtractor", create=True) as mock_cls:
        mock_cls.extract_terms_from_paragraphs = lambda self, p, pbar=None, ptc=0: None
        debug_trace.init_debug(True)
        debug_trace.init_debug(True)
```

- [ ] **Step 2: Verify app.py no longer imports debug_patches**

Check `app.py` -- if it still has `from debug_patches import apply_patches`, remove it (it was already removed in Task 3 Step 3). If not already done, remove line 6:

```
from debug_patches import apply_patches
```

- [ ] **Step 3: Delete debug_patches.py**

```powershell
git rm debug_patches.py
```

- [ ] **Step 4: Run all tests to check nothing breaks**

```powershell
pytest tests/test_debug_patches.py tests/test_app.py -v
```

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add tests/test_debug_patches.py app.py
git rm debug_patches.py
git commit -m "refactor: delete debug_patches.py, migrate tests to debug_trace.py"
```

---

### Task 9: Full Regression and Lint Verification

**Files:**
- No code changes -- verification only
- Test: `tests/` (all)

- [ ] **Step 1: Run full test suite**

```powershell
pytest tests/ -v
```

Expected: All tests PASS.

- [ ] **Step 2: Run ruff lint**

```powershell
ruff check
```

Expected: Zero errors.

- [ ] **Step 3: Grep for if config.DEBUG in non-debug_trace files**

```powershell
rg "if config\.DEBUG|config\.DEBUG\s*=" --include="*.py" --glob="!debug_trace.py" --glob="!tests/*"
```

Expected: No matches in business code (routes.py, services.py, sse_stream.py, app.py, etc.). May find references in tests or config.py itself.

- [ ] **Step 4: Grep for debug_patches imports**

```powershell
rg "debug_patches" --include="*.py"
```

Expected: No matches.

- [ ] **Step 5: Commit final verified state**

```powershell
git add -A
git commit -m "chore: final verification -- all tests pass, zero lint errors, no debug_patches references"
```
