# Brainstorm Summary

- Change: fix-concurrency-resource-cleanup
- Date: 2026-06-25

## Confirmed Technical Approach

**Approach A: try/finally in generate() + dirs owned by generate()**

1. Move `tmpdir` and `output_dir` creation from `routes.py translate_page()` into `sse_stream.generate()`, both as `Path`
2. Wrap the entire `generate()` body in `try/finally`; cleanup `tmpdir`/`output_dir` in `finally` with `shutil.rmtree(ignore_errors=True)`, logged on failure
3. Add `AppState.extract_page(self, page, tmpdir, extract_func)` under `self._lock`, mirroring `render_page` pattern — lock → validate `_left_doc` → call `extract_func(doc, page, tmpdir)`
4. Remove `tmpdir` and `output_dir` parameters from `finish_translation()` signature; it handles only page-replacement + glossary-merge
5. `routes.py translate_page()`: remove directory creation, remove direct `extract_single_page` call and bare `state.left_doc` access; `GenerateContext` fields: `tmpdir`/`output_dir` replaced by `page: int`, `cache_dir: Path`, `single_page_pdf` now set inside generate() after extraction
6. `pdf_extraction.extract_single_page` signature unchanged — already matches `(doc, page, tmpdir)` pattern

## Key Trade-offs and Risks

- **Lock contention**: IO (`insert_pdf` + `save`) under lock → acceptable: single-page extraction is lightweight, translation endpoint is low-frequency
- **finally in generator**: CPython `finally` fires on `return`, exception, and `GeneratorExit` (Flask calls `.close()` on disconnect). Tested with `gen.close()` simulation
- **Cleanup never masks errors**: `shutil.rmtree(ignore_errors=True)` + `logger.debug`; never raises, never suppresses business exceptions

## Testing Strategy

8 test cases from tasks.md:
1. Error event early exit → dirs deleted
2. No translate_result early exit → dirs deleted  
3. gen.close() (GeneratorExit) → dirs deleted (client disconnect)
4. Success path → dirs deleted exactly once
5. extract_page holds lock during execution (mock-based)
6. Extract + render concurrent → serialized via lock, no races (threaded)
7. Adjust existing tests for finish_translation signature change
8. ruff check . + pytest -q all pass

## Spec Patches

None — existing delta specs in `specs/code-quality-foundations/`, `specs/page-translation/`, and `specs/translation-lifecycle/` already cover the acceptance scenarios.
