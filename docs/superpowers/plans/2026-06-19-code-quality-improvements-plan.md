---
change: code-quality-improvements
design-doc: docs/superpowers/specs/2026-06-19-code-quality-improvements-design.md
base-ref: b5ffe2aa3cefc363bcc5426c6d5d624f8532654f
---

# Code Quality Improvements — Implementation Plan

## 1. Security: API Key Environment Variable

- [ ] 1.1 In config.py, read `DEEPSEEK_API_KEY` from `os.environ.get("DEEPSEEK_API_KEY")`, fallback to config.toml
- [ ] 1.2 Verify `.env` is in `.gitignore`; add `.env.example` template file with placeholder values

**Verification**: `echo %DEEPSEEK_API_KEY%` set → app uses env var; unset → falls back to config.toml

## 2. Module Split: Backend Structure

- [ ] 2.1 Create `config.py` — extract all CONFIG loading, DPI, CACHE_DIR, DEEPSEEK_*, TRANSLATION_*, GLOSSARY_PATH from app.py
- [ ] 2.2 Create `state.py` — `AppState` class with `__init__`, `open_pdf`, `close`, `get_doc`, `render_page`, `replace_translated_page` methods, internal `threading.Lock`
- [ ] 2.3 Create `services.py` — extract `_sha256`, `_render_page`, `_build_settings`, `_replace_page_in_right_pdf` as pure functions (state passed as arg where needed)
- [ ] 2.4 Create `routes.py` — move all `@app.route` handlers, access state via `current_app.config['app_state']`, add `error_response()` helper
- [ ] 2.5 Rewrite `app.py` — Flask app creation, `AppState()` init → `app.config['app_state']`, import and register routes, error handlers
- [ ] 2.6 Fix missing `base_url` in `DeepSeekSettings` constructor (pass `deepseek_base_url` from config)
- [ ] 2.7 Move all function-body `import` statements to module top level

**Verification**: `python app.py` starts without import errors; all existing API endpoints return correct responses

## 3. Concurrency: Thread-Safe AppState

- [ ] 3.1 Add `threading.Lock()` as `self._lock` in `AppState.__init__`
- [ ] 3.2 Wrap all state-mutating methods with `with self._lock:` context manager
- [ ] 3.3 Use `frozenset` for `translated_pages` reads; convert to `set` only inside locked write methods

**Verification**: Test with concurrent requests via pytest (see Section 6); no `RuntimeError` or corrupted state

## 4. Resource Management: PDF Document Lifecycle

- [ ] 4.1 In `AppState.open_pdf()`, close previous `self._left_doc` and `self._right_doc` before opening new ones
- [ ] 4.2 Add `AppState.close()` method for explicit cleanup
- [ ] 4.3 In `routes.py` translate handler, verify `shutil.rmtree(tmpdir)` in finally block is robust

**Verification**: Open PDF A → Open PDF B → no open file handles leaked (check via pymupdf internals or OS tools)

## 5. Type Annotations (PEP 484)

- [ ] 5.1 Add type annotations to `config.py` — all module-level constants
- [ ] 5.2 Add type annotations to `state.py` — `AppState` class attributes and method signatures
- [ ] 5.3 Add type annotations to `services.py` — all function signatures and return types
- [ ] 5.4 Add type annotations to `routes.py` — all route handler signatures
- [ ] 5.5 Define `StateDict` TypedDict for legacy compatibility if needed

**Verification**: Run `mypy` or `pyright` with minimal errors (ruff's type rules pass)

## 6. Tests

- [ ] 6.1 Add `pytest` to `requirements.txt` as dev dependency
- [ ] 6.2 Create `tests/conftest.py` — fixtures: `sample_pdf_path` (temp PDF with 2 pages), `app_state` (in-memory AppState), `test_client` (Flask test client)
- [ ] 6.3 Write `tests/test_config.py` — verify all config values loaded correctly
- [ ] 6.4 Write `tests/test_services.py` — `test_sha256_consistent`, `test_sha256_different`, `test_render_page_valid`, `test_render_page_out_of_range`, `test_build_settings_basic`, `test_build_settings_with_glossary`, `test_build_settings_with_prompt`
- [ ] 6.5 Write `tests/test_state.py` — `test_open_pdf_creates_cache`, `test_open_pdf_restores_state`, `test_reopen_closes_old_docs`, `test_concurrent_access` (threading)
- [ ] 6.6 Write `tests/test_routes.py` — `test_open_valid_pdf`, `test_open_missing_file`, `test_get_page_valid`, `test_get_page_out_of_range`, `test_get_page_invalid_side`, `test_translate_no_doc`
- [ ] 6.7 Run `pytest -v` — all tests pass

## 7. Linting & Formatting

- [ ] 7.1 Create `ruff.toml` — enable: `E` (pycodestyle), `F` (pyflakes), `I` (isort), `UP` (pyupgrade), `ANN` (flake8-annotations) with per-file ignores where necessary
- [ ] 7.2 Run `ruff check --fix` on all Python files
- [ ] 7.3 Run `ruff format` on all Python files
- [ ] 7.4 Verify `ruff check` exits with code 0

## 8. Frontend: JS Extraction & Error Handling

- [ ] 8.1 Move all `<script>` content from `index.html` to `static/app.js`
- [ ] 8.2 Add `<script src="/static/app.js" defer></script>` to `index.html`
- [ ] 8.3 Extract `calculatePlaceholderHeight(pageWidth, pageHeight)` function to eliminate duplication
- [ ] 8.4 Add try/catch in `openPdf()` → show error in `#file-input-area` rather than silent failure
- [ ] 8.5 Fix SSE parser error catch: only skip JSON parse errors, re-throw business errors
- [ ] 8.6 In `translateCurrentPage` finally block, always restore button state

## 9. SSE Busy-Wait Fix

- [ ] 9.1 Replace `event_queue` list + `time.sleep(0.1)` polling with `queue.Queue`
- [ ] 9.2 Translation thread puts events via `queue.put(evt)`
- [ ] 9.3 Generator blocks on `queue.get()` with timeout for heartbeat
- [ ] 9.4 Add `queue.put({"type": "_done"})` sentinel on thread completion

## 10. CSS & Logging

- [ ] 10.1 Replace `overflow: hidden` on `body` with `overflow: hidden` on `#app` container only
- [ ] 10.2 Add structured logging: `logging.getLogger("pdf_reader")` in app.py
- [ ] 10.3 Replace all `print()` calls with `logger.info/warning/error`
- [ ] 10.4 Log: PDF open, translation start, translation complete, translation error, server start

## 11. Dependency Lock & Cleanup

- [ ] 11.1 Run `pip freeze > requirements.lock`
- [ ] 11.2 Update `requirements.txt` to separate runtime vs dev dependencies with comments
- [ ] 11.3 Verify `pip install -r requirements.txt` followed by `pip install -r requirements.lock` works

## 12. Verification

- [ ] 12.1 `pytest -v` — all tests pass
- [ ] 12.2 `ruff check` — zero errors
- [ ] 12.3 Manual: open a PDF, translate page 2, verify right column shows translation
- [ ] 12.4 Manual: open a second PDF, verify old state released
- [ ] 12.5 Manual: reload page, verify translated state restored
- [ ] 12.6 Manual: test with custom prompt and glossary.csv
