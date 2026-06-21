# Brainstorm Summary

- Change: data-driven-engine-config
- Date: 2026-06-21

## Confirmed Technical Approach

Replace scattered `PROVIDER_MAP` + `FIELD_MAP` (8 sub-dicts, 79 entries) with a centralized declarative `EngineSpec` frozen dataclass + `ENGINE_REGISTRY: list[EngineSpec]`. Each engine is one declaration: provider key, SettingsClass, field_map (unified_name → engine_field), and required_fields tuple.

Key implementation decisions confirmed:
1. `EngineSpec.required_fields: tuple[str, ...]` encodes api_key/model as required; base_url handled silently; rest warn on unsupported
2. Internal `CONFIG_ATTR_MAP` in `build_engine_kwargs` maps unified_name → config module attribute (e.g. `"model" → "MODEL"`)
3. `EngineSpec` and `ENGINE_REGISTRY` stay in `config.py`
4. Runtime field validation against `settings_cls.model_fields` preserved (skip + warn), no registration-time validation

## Key Trade-offs and Risks

- Migration correctness: 79 field map entries across 10 engines must be mechanically derived without drift → equivalence regression tests
- pdf2zh-next version upgrades: Settings class fields may change → runtime model_fields check tolerates inconsistencies
- `build_settings` call chain updates: `engine_cls` → `spec.settings_cls` at instantiation point

## Testing Strategy

1. Equivalence regression baseline: compare new vs old `resolve_engine + build_engine_kwargs` output for all 10 engines
2. Existing tests: `test_services.py` `test_build_settings_*` series must remain green
3. Extensibility: fake engine with mock Settings class, single declaration test
4. Full regression: `pytest tests/ -v` + `ruff check`

## Spec Patches

None — OpenSpec delta specs (engine-registry, page-translation, code-quality-foundations) are complete.
