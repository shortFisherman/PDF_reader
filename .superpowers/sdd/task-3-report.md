# Task 3 Report: Refactor services to use EngineSpec

## Status: DONE

## What was implemented

Refactored `resolve_engine` and `build_engine_kwargs` in `services.py` to use `EngineSpec` from `config.py` instead of the deprecated `PROVIDER_MAP` and `FIELD_MAP`. Deleted `PROVIDER_MAP`, `FIELD_MAP`, and `_derive_field_map` from `config.py`. Inlined all `field_map` entries in `ENGINE_REGISTRY`.

### Files changed

| File | Change |
|------|--------|
| `config.py` | Deleted `PROVIDER_MAP` (12 lines), `FIELD_MAP` (70 lines), `_derive_field_map` (8 lines). Inlined field_map dicts into 10 `EngineSpec` entries. |
| `services.py` | Rewrote `resolve_engine` (returns `EngineSpec`), `build_engine_kwargs` (takes `EngineSpec`), added `CONFIG_ATTR_MAP`. Updated `build_settings` call chain. Removed unused `OpenAICompatibleSettings` import. |
| `tests/test_engine_registry.py` | Added `test_engine_registry_covers_all_providers`, `_old_build_engine_kwargs`, `_new_build_engine_kwargs`, `test_new_path_matches_old_path`. Updated all existing tests to use `EngineSpec`/`PROVIDER_INDEX` instead of `PROVIDER_MAP`/`FIELD_MAP`. Embedded `_OLD_FIELD_MAP` snapshot for equivalence comparison. |
| `tests/test_services.py` | Renamed `test_config_provider_map_has_deepseek` → `test_config_provider_index_has_deepseek`. Renamed `test_config_field_map_api_key_exists` → `test_config_deepseek_field_map_api_key`. Updated 5 engine tests to pass `EngineSpec` to `build_engine_kwargs`. |

### Key design decision

The fallback `EngineSpec` in `resolve_engine` for unknown providers now reuses `config.PROVIDER_INDEX["openai_compatible"]` instead of constructing a new `EngineSpec` with empty `field_map`. This ensures the fallback properly populates all openai_compatible fields (api_key, model, base_url, etc.) from config values.

## TDD evidence

| Phase | Test | Result |
|-------|------|--------|
| RED (Step 2) | `test_new_path_matches_old_path`, `test_engine_registry_covers_all_providers` | Both PASSED (self-contained test helpers proved equivalence upfront) |
| GREEN (Step 6) | All 5 `test_engine_registry.py` tests | All PASSED |
| GREEN (Step 9) | Full test suite (89 tests) | 88 passed, 1 failed (`test_build_settings_unknown_provider` — fallback field_map was empty) |
| GREEN (fix) | Full test suite after fallback fix | 89/89 PASSED |
| GREEN (final) | Full test suite after cleanup | 89/89 PASSED |

## Test results

- **89/89 passing** (across 10 test files)
- `test_new_path_matches_old_path` — verifies old vs new `build_engine_kwargs` equivalence across all 10 providers
- `test_engine_registry_covers_all_providers` — verifies 10 providers in `PROVIDER_INDEX`
- All existing `build_settings` tests continue to pass with `mock_config` fixture

## Self-review findings

1. **Fallback fix needed**: Initial implementation created fallback `EngineSpec` with empty `field_map`, causing `test_build_settings_unknown_provider` to fail. Fixed by reusing `PROVIDER_INDEX["openai_compatible"]` directly.
2. **`_old_build_engine_kwargs` snapshot**: Embedded `_OLD_FIELD_MAP` as a local constant in the test file to preserve equivalence comparison after `FIELD_MAP` deletion from `config.py`.
3. **Import cleanup**: Removed unused `OpenAICompatibleSettings` import from `services.py` (no longer needed since fallback uses `PROVIDER_INDEX`).

## Concerns

- None. All tests pass. The equivalence test confirms new path produces identical results to old path across all 10 providers.

## Commit

- `d0d9e0f` — `refactor: migrate resolve_engine and build_engine_kwargs to EngineSpec`
- `d0ceef9` — `fix: address code review findings — use production build_engine_kwargs in equivalence test, remove _new_build_engine_kwargs helper, add _OLD_FIELD_MAP docstring, use set equality for provider coverage check`

## Code Review Fixes (d0ceef9)

| Finding | Severity | Fix |
|---------|----------|-----|
| `test_new_path_matches_old_path` compared two local helpers instead of production `build_engine_kwargs` | Critical | Changed to compare `_old_build_engine_kwargs(spec.settings_cls)` vs production `build_engine_kwargs(spec)` |
| `_new_build_engine_kwargs` had `import logging` inside function body | Important | Removed the entire `_new_build_engine_kwargs` function (no longer needed) |
| `_OLD_FIELD_MAP` lacked explanatory comment | Minor | Added docstring explaining it's a migration snapshot preserved after `FIELD_MAP` deletion from config.py |
| `test_engine_registry_covers_all_providers` used hard `assert len(...) == 10` | Minor | Replaced with set equality check derived from `_OLD_FIELD_MAP["api_key"]` |

**Test results after fixes**: 89/89 passing

## Branch Review Fixes (2026-06-21)

| Finding | Severity | Fix |
|---------|----------|-----|
| Lost "engine doesn't support optional field" warning — new `build_engine_kwargs` only iterates `spec.field_map`, so optional fields (thinking_mode, reasoning_effort, enable_json_mode, temperature, timeout) configured but not in the engine's field_map are silently ignored | Important | Added second pass in `build_engine_kwargs` over optional_fields to log `当前引擎不支持 %s，已忽略` for fields NOT in `spec.field_map` with non-None config values |
| Unknown provider fallback uses hardcoded dict key `PROVIDER_INDEX["openai_compatible"]` — if the entry is renamed/removed, KeyError | Important | Added comment above `openai_compatible` entry in `ENGINE_REGISTRY`: `# openai_compatible entry MUST remain — it serves as the fallback in resolve_engine` |

### Files changed

| File | Change |
|------|--------|
| `services.py` | Added 6-line second pass in `build_engine_kwargs` (lines 75-80) to warn about unsupported optional fields |
| `config.py` | Added 1-line comment above `openai_compatible` `EngineSpec` entry |

### Commit

- `(pending)` — `fix: restore unsupported-field warnings and add fallback safety comment`

**Test results after fixes**: 91/91 passing, ruff zero errors
