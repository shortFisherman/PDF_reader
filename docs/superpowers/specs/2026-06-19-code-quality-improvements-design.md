---
comet_change: code-quality-improvements
role: technical-design
canonical_spec: openspec
status: archived
archived-with: openspec/changes/archive/2026-06-19-code-quality-improvements
---

# Code Quality Improvements — Technical Design

## Architecture

Split monolithic `app.py` (309 lines) into 5 modules:

```
app.py                          # Entry: create Flask app, inject AppState instance
├── config.py                   # Configuration loading, constants
├── state.py                    # AppState class (encapsulated state + threading.Lock)
├── services.py                 # Pure functions: _sha256, _render_page, _build_settings
└── routes.py                   # Register all routes, access state via current_app
```

```
           ┌──────────┐
           │  app.py  │  creates Flask app + AppState instance
           └────┬─────┘
                │ current_app.config['app_state']
    ┌───────────┼───────────┐
    ▼           ▼           ▼
┌───────┐  ┌───────┐  ┌──────────┐
│routes │  │state  │  │services  │
│       │──▶      │──▶          │
│register│  │AppState│  │pure funcs│
│routes │  │+ Lock │  │(hash,    │
└───────┘  └───────┘  │ render…) │
    │                  └──────────┘
    ▼
┌───────┐
│config │  read-only config
└───────┘
```

### Key Decision: State Class + Flask app.config (Plan B)

The global `state` dict is replaced by an `AppState` class stored in `app.config['app_state']`. Internal `threading.Lock` protects all shared state access. Routes access via `current_app.config['app_state']`.

**AppState interface:**
```python
class AppState:
    pdf_path: str | None
    pdf_hash: str | None
    page_count: int

    def open_pdf(self, path: str) -> dict        # open/switch PDF, return metadata
    def get_doc(self, side: str) -> Document | None
    def render_page(self, side: str, page: int) -> bytes
    def replace_translated_page(self, src: str, page: int) -> None
    def close(self)                               # release resources
```

Each method uses `with self._lock:` to protect shared state. Previous documents are closed before new ones open (resource leak fix). `translated_pages` uses `frozenset` for safe reads.

**Why not Plan A (global + Lock):** Easier to implement but state is still global — testing requires module-level mocking, and future multi-document support would need significant refactoring.

**Why not Plan C (dependency injection):** Most decoupled but over-engineered for a single-user desktop tool. Requires Flask application factory pattern which adds boilerplate without proportional benefit.

## Data Flow

### PDF Open
```
POST /api/open {"path": "..."}
  → routes.py calls state.open_pdf(path)
  → state.py: compute SHA256, close old docs, open new, return metadata
  → response: {page_count, page_height, page_width, hash}
```

### Page Translation
```
POST /api/translate/5 {"prompt": "..."}
  → routes.py checks state has document
  → services.py:_build_settings(config, glossary, prompt) → SettingsModel
  → translation thread: do_translate_async_stream → queue.Queue
  → SSE generator: queue.get() (blocking, no polling) → yield SSE events
  → on finish: state.replace_translated_page(output_pdf, page)
    → pymupdf: delete old page, insert new, full rewrite save
```

### Page Rendering
```
GET /api/page/left/5
  → routes.py → state.render_page("left", 5)
  → state.py: with lock, get left_doc, call services._render_page
  → return PNG bytes
```

## Error Handling

**Unified error response:**
```python
def error_response(msg: str, code: int = 400) -> tuple[Response, int]:
    return jsonify({"error": msg}), code
```

**SSE generator refactored to queue.Queue:**
- Replace `while True: time.sleep(0.1); yield ""` busy-wait with `queue.Queue`
- Translation thread puts events; SSE generator blocks on `queue.get()`
- Eliminates idle CPU consumption

**Frontend:**
- `openPdf()`: try/catch around fetch with user-visible error alert
- SSE parser: specific error catch (not blanket silent)
- Translate button: restore enabled state on failure in finally block

**Logging:**
- Replace `print()` with `logging.getLogger("pdf_reader")`
- INFO: PDF open, translation start/complete
- ERROR: translation failures, file I/O errors
- WARNING: non-critical issues (e.g., glossary not found)

## Testing Strategy

```
tests/
├── conftest.py              # fixtures: temp PDF, mock AppState, Flask test client
├── test_config.py           # config loading correctness
├── test_state.py            # AppState: open, close, get_doc, thread safety
├── test_services.py         # _sha256, _render_page (boundaries), _build_settings
└── test_routes.py           # Flask test client: HTTP status codes, response shape
```

| Layer | Scope | Strategy |
|-------|-------|----------|
| Unit | `_sha256`, `_render_page`, `_build_settings` | Pure functions, direct test |
| State | `AppState` methods | Mock pymupdf.Document, verify lock safety |
| Integration | Route endpoints | Flask `test_client()`, mock pdf2zh-next |

**Key test cases:**
- `test_state.py`: concurrent open/close verifies no data race
- `test_services.py`: render out-of-range page raises ValueError
- `test_routes.py`: translate without opening PDF returns 400
- `test_routes.py`: SSE endpoint produces valid event stream

## Module Responsibilities

### config.py
- Load `config.toml` once at import
- Expose: `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL`, `DEEPSEEK_BASE_URL`, `DPI`, `CACHE_DIR`, `GLOSSARY_PATH`, `TRANSLATION_LANG_IN/OUT`
- Read API key from `DEEPSEEK_API_KEY` env var, fallback to config.toml

### state.py
- `AppState` class with thread-safe methods
- Manage `left_doc`, `right_doc` lifecycle (open, close, reload on replace)
- Track `translated_pages` as `frozenset` (safe for concurrent reads)

### services.py
- `_sha256(filepath) → str`: streaming hash computation
- `_render_page(doc, page, dpi) → bytes`: png rendering via pymupdf
- `_build_settings(..., user_prompt) → SettingsModel`: pdf2zh-next config
- `_replace_page_in_right_pdf(src, dst_path, page)`: page swap + save

### routes.py
- Register all endpoints on app Blueprint or direct decorator
- Thin handlers: validate input, call services/state, return response
- Error handling with unified `error_response()`

### app.py
- Create Flask app
- Initialize `AppState` instance, store in `app.config['app_state']`
- Register error handlers
- `if __name__ == "__main__": app.run()`

## Trade-offs

| Decision | Trade-off |
|----------|-----------|
| State in app.config vs module global | Requires `current_app` in routes, but enables testing without module mocking |
| Lock per-method vs fine-grained locks | Simpler code, negligible contention for single-user tool |
| Blueprint vs direct route decorator | Blueprint is more standard; direct decorator simpler for 5 routes |
| pytest vs unittest | pytest is the de-facto standard for modern Python |

## Spec Patches

None. All existing capabilities remain functionally unchanged. This change improves implementation quality without altering spec-level behavior.
