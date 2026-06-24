## Task 3 Report: engine_resolver.py 接入延迟校验

**Status:** Complete

**Commit:** `e5f474d` — `feat: call _validate_required_config() at resolve_engine entry`

### Changes

| File | Change |
|------|--------|
| `engine_resolver.py:20` | Added `config._validate_required_config()` at `resolve_engine` entry |
| `tests/test_engine_registry.py` | Added 3 new TDD tests (missing model, missing api_key, default api_key) |
| `tests/test_services.py:174-177` | Updated pre-existing `test_build_settings_missing_api_key_raises` — now expects `ValueError` (from earlier validation) instead of `RuntimeError` |

### Tests

- **110 passed**, 0 failed
- `ruff check .` — All checks passed

### TDD Cycle

1. **RED** — 3 new tests failed because `resolve_engine` didn't call validation yet
2. **GREEN** — Added single line `config._validate_required_config()` at function entry
3. **REFACTOR** — None needed; minimal change

### Concerns

- None. The pre-existing `test_build_settings_missing_api_key_raises` was updated to reflect that validation now happens at `resolve_engine` entry (raising `ValueError`) rather than later in `build_engine_kwargs` (which previously raised `RuntimeError`). This is the intended behavioral shift.
