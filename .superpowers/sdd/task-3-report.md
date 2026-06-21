# Task 3 Report: CLI `--debug` Flag in app.py

## Status: COMPLETE (partial — 2/4 tests pass as expected)

## TDD Evidence

### RED Phase (before app.py rewrite — old code)
- `test_cli_debug_flag_overrides_config` — PASSED (tested argparse logic in isolation)
- `test_cli_no_debug_flag_does_not_override` — PASSED (tested argparse logic in isolation)
- `test_import_app_does_not_trigger_side_effects` — PASSED (falsely — mock resolution order hid import-time side effects)
- `test_create_app_calls_init_debug` — FAILED (`debug_trace.init_debug` does not exist yet)

**Note:** The brief expected `test_import_app_does_not_trigger_side_effects` to FAIL on old code, but it passed because `patch("app.apply_patches")` triggered the real import before installing the mock, so the mock was never called.

### GREEN Phase (after app.py rewrite)
- `test_cli_debug_flag_overrides_config` — **PASSED**
- `test_cli_no_debug_flag_does_not_override` — **PASSED**
- `test_import_app_does_not_trigger_side_effects` — FAILED (`AttributeError: module 'debug_trace' has no attribute 'init_debug'` — expected, Task 4 will add `init_debug`)
- `test_create_app_calls_init_debug` — FAILED (`AttributeError: module 'debug_trace' has no attribute 'init_debug'` — expected, Task 4 will add `init_debug`)

## Changes Made

### `app.py` — rewritten
- Added `argparse` with `--debug` flag (default=None, action="store_true")
- Removed import-time `config.DEBUG = True`, `apply_patches()`, and logger call
- CLI args parsed at module level; `--debug` overrides `config.DEBUG` only when explicitly passed
- `create_app()` now calls `debug_trace.init_debug(config.DEBUG)` (the function will be created in Task 4)
- Removed `debug_patches` import

### `tests/test_app.py` — new file
- 4 tests total: 2 argparse isolation tests (PASS), 2 integration tests (will PASS in Task 4/5)

## Commits
- `865de56` feat: add CLI --debug flag, remove app.py import-time side effects

## Concerns
- The `app = create_app()` at module level crashes on import because `debug_trace.init_debug()` doesn't exist yet. This blocks all tests that import `app` through `conftest.py`. Task 4 must add `init_debug()` to unblock.
- `test_import_app_does_not_trigger_side_effects` currently patches `app.apply_patches` but the new app.py no longer imports `apply_patches` — this test will need updating in Task 5 (or earlier) to validate the correct behavior (no side effects on import).
