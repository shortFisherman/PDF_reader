## Context

The bilingual PDF reader is a Flask + vanilla JS application in a single `app.py` file (309 lines) with all frontend logic inlined in `templates/index.html` (313 lines). It was built as a prototype and now needs engineering hardening before further feature development. The current codebase lacks tests, type annotations, linting, proper error handling, concurrency safety, and modular structure.

**Current state:**
- Monolithic `app.py` with global mutable `state` dict, mixed concerns
- `index.html` with 200+ lines of inline JS, duplicated logic
- No tests, no linting, no type checking
- API key embedded in `config.toml` (tracked by git)
- PDF document handles not released on re-open
- SSE generator uses busy-wait polling
- No logging framework

## Goals / Non-Goals

**Goals:**
- Thread-safe state management for concurrent Flask requests
- Close previous PDF documents when opening new ones
- Add pytest unit tests for core backend logic
- Add type annotations (PEP 484) throughout Python code
- Split `app.py` into `config.py`, `routes.py`, `services.py`
- Split frontend JS from `index.html` into `static/app.js`
- Add ruff linting configuration, ensure zero errors
- Generate `requirements.lock` for reproducible installs
- Fix frontend: error handling, code dedup, CSS overflow
- Move imports to top level, fix unused `base_url` parameter
- Add structured logging with `logging` module

**Non-Goals:**
- Adding new user-facing features
- Switching framework (stay on Flask + vanilla JS)
- Adding database, authentication, or multi-user support
- Responsive/mobile layout redesign
- Performance optimization beyond fixing busy-wait

## Decisions

### D1: State management → threading.Lock wrapper

Wrap the global `state` dict access behind `threading.Lock` for all read/write operations. Use a simple `with state_lock:` context manager pattern.

**Rationale**: Minimal change, no new dependencies, sufficient for single-process Flask with thread pool. A full session-based design (e.g., per-request state via Flask `g`) would require API redesign (session tokens, etc.) which exceeds the scope of quality improvement.

**Alternatives considered**:
- Flask `g` per-request context: Would require major API changes (passing session IDs)
- `multiprocessing` or Redis: Overkill for single-machine single-user tool

### D2: Module split → config / routes / services

```
app.py (entry point + app creation)
config.py (config loading, constants)
routes.py (Flask route handlers)
services.py (PDF operations: render, translate, replace page)
```

`app.py` creates the Flask app, imports and registers routes. Routes call services. Services access shared state through the lock-protected module.

**Rationale**: Follows Flask best practices (application factory pattern-adjacent). Each module is independently testable.

### D3: API key → environment variable with .env fallback

Read API key from `DEEPSEEK_API_KEY` environment variable first, then fall back to `config.toml` for local development convenience. Add `.env` to `.gitignore`.

**Rationale**: 12-factor app principle for secrets. Keeps local dev experience smooth (config.toml still works) while preventing accidental commits.

### D4: Testing → pytest with fixture-based setup

```python
# tests/test_services.py — test _sha256, _render_page, _build_settings
# tests/test_routes.py — test Flask routes with test client
```

Mock pdf2zh-next and pymupdf for translation tests. Use `tempfile` for PDF fixture creation.

### D5: Linting → ruff with strict ruleset

Single `ruff.toml` at project root. Enable pyflakes, pycodestyle, isort, and type-checking-compatible rules. Configure per-file ignores only where necessary (e.g., allow `import` inside function for the `generate()` closure pattern).

### D6: Frontend split → static/app.js

Move all `<script>` content to `static/app.js`, loaded via `<script src>`. Keep HTML structural only. This enables future minification and linting.

### D7: SSE polling → threading.Event or queue.Queue

Replace `while True: time.sleep(0.1)` with `queue.Queue` for the event relay between translation thread and SSE generator. The generator blocks on `queue.get()` instead of polling.

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| Module split breaks Flask route decorators | Routes use `Blueprint`, or import `app` from `app.py` in routes module |
| Lock contention slows concurrent requests | Single-user tool with manual translation; lock contention is negligible |
| pdf2zh-next API changes break tests | Pin pdf2zh-next version in requirements.txt; already done |
| Moving JS to external file breaks inline event handlers | All event handlers are already `addEventListener`, no `onclick` in HTML |
| `requirements.lock` diverges across platforms | Use `pip freeze` targeting Python 3.12 on Windows |

## Open Questions

1. Should `state` be per-session (support multiple PDFs open simultaneously) or remain single-document? → Keep single-document for now; multi-session is a feature change.
2. Should tests cover the SSE streaming endpoint? → Yes, but as an integration test with a real Flask test client.
