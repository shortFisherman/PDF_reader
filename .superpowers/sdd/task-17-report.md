# Task 3.10 Report — Namespace + Settings Summary Logging

**Status**: Complete

## Changes

### engine_resolver.py
- Line 5: `logger = logging.getLogger("pdf_reader")` → `logger = logging.getLogger("pdf_reader.engine")`
- Existing `logger.info("Using engine: %s (%s)", ...)` kept unchanged (OK per spec)

### translation_settings.py
- Line 11: `logger = logging.getLogger("pdf_reader")` → `logger = logging.getLogger("pdf_reader.engine")`
- Line 53: Added `logger.debug("[settings] provider=%s model=%s lang=%s->%s pages=%s", ...)` before `return` in `build_settings()` — only safe fields, no API keys
- Lines 14–22: Added `_settings_summary()` helper returning a string with safe fields (provider/model/lang/cache_dir/dpi) — reusable by Task 4.1

## Verification
- All 26 tests in `tests/test_services.py` pass

## Commit
- `logging: add pdf_reader.engine namespace + safe settings debug log (Task 3.10)`

## Safety note
The debug log in `build_settings()` intentionally excludes `MODEL_API_KEY` and all other secrets. The `_settings_summary()` helper is equally safe.
