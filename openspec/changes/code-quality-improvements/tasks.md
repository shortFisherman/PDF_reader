## 1. Security: API Key Management

- [ ] 1.1 Read DEEPSEEK_API_KEY from environment variable, fall back to config.toml
- [ ] 1.2 Add `.env` to `.gitignore`; document env var usage in README

## 2. Concurrency: Thread-Safe State

- [ ] 2.1 Add `threading.Lock` to protect `state` dict reads and writes
- [ ] 2.2 Wrap all state access in route handlers with lock context manager
- [ ] 2.3 Ensure translation thread callback (translated_pages set update) uses lock

## 3. Resource Management: PDF Document Cleanup

- [ ] 3.1 Close previous left_doc and right_doc before opening new PDF in open_pdf()
- [ ] 3.2 Add try/finally in translate_page generator to ensure temp dir cleanup is robust

## 4. Module Split: Backend

- [ ] 4.1 Create `config.py` — extract CONFIG loading, constants, GlossaryPath
- [ ] 4.2 Create `services.py` — extract _sha256, _render_page, _build_settings, _replace_page_in_right_pdf
- [ ] 4.3 Create `routes.py` — extract all @app.route handlers, import from services
- [ ] 4.4 Rewrite `app.py` as entry point: create Flask app, import routes, register error handlers
- [ ] 4.5 Move all function-body `import` statements to module top level
- [ ] 4.6 Fix missing base_url parameter in DeepSeekSettings construction

## 5. Type Annotations

- [ ] 5.1 Add type annotations to all functions in config.py
- [ ] 5.2 Add type annotations to all functions in services.py
- [ ] 5.3 Add type annotations to all functions in routes.py
- [ ] 5.4 Add type annotation for module-level state dict (TypedDict)

## 6. Linting Configuration

- [ ] 6.1 Create `ruff.toml` with pyflakes, pycodestyle, isort rules enabled
- [ ] 6.2 Run `ruff check --fix` and resolve all errors
- [ ] 6.3 Verify `ruff check` exits with zero errors

## 7. Tests

- [ ] 7.1 Add pytest to requirements.txt (dev dependency)
- [ ] 7.2 Create `tests/` directory and `tests/conftest.py` with PDF fixtures
- [ ] 7.3 Write `tests/test_services.py` — test _sha256, _render_page, _build_settings
- [ ] 7.4 Write `tests/test_routes.py` — test Flask routes with test client
- [ ] 7.5 Run `pytest` and verify all tests pass

## 8. Frontend: JS Split & Error Handling

- [ ] 8.1 Extract inline JS from index.html into `static/app.js`
- [ ] 8.2 Add `<script src="/static/app.js">` to index.html
- [ ] 8.3 Deduplicate placeholder dimension calculation (extract to function)
- [ ] 8.4 Add try/catch around fetch calls with user-visible error messages
- [ ] 8.5 Fix CSS: replace `overflow: hidden` on body with proper scroll containment

## 9. Dependency & Logging

- [ ] 9.1 Generate `requirements.lock` via `pip freeze > requirements.lock`
- [ ] 9.2 Replace `print()` with `logging` module for startup message and errors
- [ ] 9.3 Add logging for PDF open, translation start/complete/error events

## 10. Verification & Cleanup

- [ ] 10.1 Run full test suite (`pytest`) — all tests pass
- [ ] 10.2 Run ruff lint check — zero errors
- [ ] 10.3 Manual smoke test: open PDF, translate page, verify right column updates
- [ ] 10.4 Manual test: open new PDF, verify old documents are released
- [ ] 10.5 Verify `requirements.lock` installs identical versions
