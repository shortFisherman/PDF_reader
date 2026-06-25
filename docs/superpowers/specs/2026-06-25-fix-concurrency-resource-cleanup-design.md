---
comet_change: fix-concurrency-resource-cleanup
role: technical-design
canonical_spec: openspec
archived-with: 2026-06-25-fix-concurrency-resource-cleanup
status: final
---

# Design Doc: fix-concurrency-resource-cleanup

## Overview

Two defects found during code review:
1. **tempdir leak**: `tmpdir`/`output_dir` created in `routes.py` but cleaned only on the successful code path in `finish_translation`. Early returns (error event, no result) and client disconnects leak both directories.
2. **extract race**: `routes.py` passes `state.left_doc` directly to `pdf_extraction.extract_single_page`, bypassing `AppState._lock`, while `render_page` holds the lock. Concurrent read+render on the same `pymupdf.Document` is a data race.

## Architecture & Data Flow

**Before:**
```
routes.py:  mkdtemp(tmpdir) → mkdtemp(output_dir) → extract(state.left_doc, page, tmpdir) → stream(generate(ctx))
generate(): try: translate → finish_translation(cleanup)  |  return (leak)
```

**After:**
```
routes.py:  validate → build GenerateContext(page, cache_dir) → stream(generate(ctx))
generate(): try: mkdtemp → extract_page(lock) → translate → finally: rmtree
```

Key principle: **resource creator is resource cleaner**. `generate()` owns tmpdir/output_dir lifecycle end-to-end.

## Component Changes

### sse_stream.py

**`GenerateContext`**: `tmpdir: Path`, `output_dir: str`, and `single_page_pdf` replaced by:
- `page: int`
- `cache_dir: Path`
- `extract_page: Callable[[int, Path, Callable], Path]` — delegation callable for lock-guarded extraction, same pattern as existing `replace_page`

**`generate()`**: new structure:

```python
def generate(ctx: GenerateContext) -> Iterator[str]:
    tmpdir = Path(tempfile.mkdtemp())
    output_dir = Path(tempfile.mkdtemp(dir=str(ctx.cache_dir)))
    try:
        with debug_trace.debug_session(ctx.glossary_cache_path, ctx.page):
            single_page_pdf = _get_state().extract_page(
                ctx.page, tmpdir, pdf_extraction.extract_single_page
            )
            # ... existing translation loop ...
            finish_translation(translate_result, ctx.replace_page, ctx.glossary_cache_path)
            # ... yield finish events ...
    except TranslationError as e:
        yield error...
    except Exception as e:
        logger.warning(...)
        yield error...
    finally:
        _safe_rmtree(tmpdir)
        _safe_rmtree(output_dir)
```

`_safe_rmtree(dir)` is a helper: `shutil.rmtree(dir, ignore_errors=True)` with `logger.debug` on failure.

### state.py

New method, mirrors `render_page` pattern:

```python
def extract_page(self, page: int, tmpdir: Path, extract_func) -> Path:
    """Extract a single page under the state lock.
    extract_func must not reenter AppState (non-reentrant lock)."""
    with self._lock:
        if self._left_doc is None:
            raise ValueError("no document opened")
        return extract_func(self._left_doc, page, tmpdir)
```

### routes.py

`translate_page()`:
- Remove `tmpdir` and `output_dir` creation
- Remove `pdf_extraction.extract_single_page(state.left_doc, page, tmpdir)` call and bare `state.left_doc` access
- `GenerateContext` gets `page=page`, `cache_dir=config.CACHE_DIR`, `extract_page=lambda page, tmpdir, func: state.extract_page(page, tmpdir, func)` instead of `tmpdir`/`output_dir`/`single_page_pdf`

### translation_lifecycle.py

`finish_translation()`:
- Remove `tmpdir: Path` and `output_dir: str` parameters
- Remove `shutil.rmtree(tmpdir)` and `shutil.rmtree(output_dir)` lines
- Signature becomes: `finish_translation(translate_result, replace_page, glossary_cache_path)`

### pdf_extraction.py

No changes. `extract_single_page(doc, page, tmpdir)` signature already matches `(doc, page, tmpdir)`.

## Error Handling

| Scenario | Behavior |
|----------|----------|
| `_left_doc` is None at extract time | `extract_page` raises `ValueError`, caught by `except Exception`, error event yielded, `finally` cleans up |
| TranslationError during run | Caught, error event yielded, `finally` cleans up |
| Unexpected exception | `logger.warning`, error event yielded, `finally` cleans up |
| Client disconnect | Flask calls `.close()` on generator → `GeneratorExit` → enters `finally` → cleanup |
| rmtree raises (e.g. permissions) | `ignore_errors=True` + `logger.debug` — never masks business errors, never re-raises |

## Testing

| # | Test | Validates |
|---|------|-----------|
| 3.1 | Error event → generator returns early | tmpdir/output_dir deleted |
| 3.2 | No translate_result → generator returns early | tmpdir/output_dir deleted |
| 3.3 | gen.close() → GeneratorExit | tmpdir/output_dir deleted (client disconnect simulation) |
| 3.4 | Successful translation | tmpdir/output_dir deleted exactly once |
| 3.5 | Mock lock assertion on extract_page | Lock acquired during extraction |
| 3.6 | Threaded extract + render | Serialized via lock, no race |
| 3.7 | Existing tests for finish_translation | Updated for new signature |
| 3.8 | ruff check . & pytest -q | Full suite passes |

## Risks / Trade-offs

- **Lock contention (IO under lock)**: `insert_pdf` + `save` for a single page is lightweight (~milliseconds). Translation endpoint is low-frequency. Acceptable trade-off for correctness.
- **finally in generator edge cases**: CPython's `finally` fires on all exit paths including `GeneratorExit`. Verified in practice with `gen.close()` test.
- **generate() now triggers lock-guarded extraction**: Delegated via `GenerateContext.extract_page` callable (same pattern as existing `replace_page` lambda) — `generate()` never touches AppState directly, only calls through the delegated callable.

## Non-Goals

- No read-write lock or finer-grained concurrency model (keep single-lock simplicity)
- No multi-document support (separate architectural concern)
- No changes to extraction algorithm itself
