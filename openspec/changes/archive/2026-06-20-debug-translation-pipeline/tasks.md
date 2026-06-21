## 1. Debug Mode Infrastructure

- [x] 1.1 Add `--debug` CLI argument to `app.py` and store in `config.DEBUG`
- [x] 1.2 Update `config.py` with `DEBUG: bool = False` default

## 2. In-Process Translation via debug=True

- [x] 2.1 Update `services.py` `build_settings()` to accept `debug: bool` parameter
- [x] 2.2 When `debug=True`, pass `basic=BasicSettings(debug=True)` to `SettingsModel` (forces main-process execution)
- [x] 2.3 Import `BasicSettings` from `pdf2zh_next.config.model`

## 3. LLM Term Extraction Monkey-Patch

- [x] 3.1 Create `debug_patches.py` module with `apply_patches()` function
- [x] 3.2 Monkey-patch `AutomaticTermExtractor.extract_terms_from_paragraphs` — wrapper around original
- [x] 3.3 Before original call: log batch size (paragraph count + character count)
- [x] 3.4 After original call (finally): read `paragraphs.tracker.input`/`.output`, log prompt length, response length, raw response (truncated to 500 chars), term count delta
- [x] 3.5 Handle JSON parse errors: if response can't be parsed, log error + raw output
- [x] 3.6 Graceful degradation: if import fails, log warning and continue without patch

## 4. Pipeline Step Logging

- [x] 4.1 Add step-begin/step-end log entries in `routes.py` translate endpoint (build settings, submit translate, merge glossary, replace page)
- [x] 4.2 Include elapsed time for each major step when debug mode is active

## 5. Debug Trace Log File

- [x] 5.1 Create `logging.getLogger("pdf_reader.debug_trace")` with console handler (always) and file handler (debug mode only)
- [x] 5.2 File handler writes to `cache/<pdf_hash>/debug_trace.log`, created when translation starts
- [x] 5.3 Clean up file handler after translation completes to avoid accumulating handlers

## 6. Verification

- [x] 6.1 Manual test: start with `python app.py --debug`, translate a page, verify console shows batch logs + step logs
- [x] 6.2 Manual test: verify `cache/<hash>/debug_trace.log` exists and contains the same trace entries
- [x] 6.3 Manual test: start with `python app.py` (no flag), translate a page, verify no trace logs or files
- [x] 6.4 Run `pytest tests/ -q` — 45 tests pass
- [x] 6.5 Run `ruff check` — no new errors
