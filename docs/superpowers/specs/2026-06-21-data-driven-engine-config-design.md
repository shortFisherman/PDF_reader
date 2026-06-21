---
comet_change: data-driven-engine-config
role: technical-design
canonical_spec: openspec
status: draft
archived-with: 2026-06-21-data-driven-engine-config
status: final
---

# Design: Data-Driven Engine Configuration

## Problem

`config.py:40-113` 用 `PROVIDER_MAP`（1 子字典，10 条目）和 `FIELD_MAP`（8 子字典，79 条目）描述 10 个翻译引擎的字段映射。新增一个引擎需在 ~10 处各加条目，极易遗漏。

`services.build_engine_kwargs` 遍历硬编码的 8 个 `unified_name`，与 `FIELD_MAP` 结构强耦合，逻辑不可复用于新引擎。

## Architecture: Declarative Engine Registry

```
config.py
  ┌─────────────────────────────────────┐
  │  EngineSpec (frozen dataclass)       │
  │  - provider: str                    │
  │  - settings_cls: type               │
  │  - field_map: dict[str, str]        │  unified_name → engine_field_name
  │  - required_fields: tuple[str, ...] │  e.g. ("api_key", "model")
  └─────────────────────────────────────┘
  │
  ▼
  ENGINE_REGISTRY: list[EngineSpec]   ← 10 engines, one line each
  │
  ▼ (derived)
  PROVIDER_INDEX: dict[str, EngineSpec]

services.py
  resolve_engine(provider) → EngineSpec
       │  lookup PROVIDER_INDEX; fallback → OpenAICompatibleSettings spec
       ▼
  build_engine_kwargs(spec: EngineSpec) → dict[str, Any]
       │  iterate spec.field_map; lookup config via CONFIG_ATTR_MAP;
       │  validate required_fields; skip+warn on unsupported engine fields
       ▼
  build_settings(...)
       │  spec.settings_cls(**engine_kwargs)
       ▼
  config.toml  [model]  section (unchanged)
```

### Data Structures

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class EngineSpec:
    provider: str
    settings_cls: type
    field_map: dict[str, str]       # {"api_key": "deepseek_api_key", ...}
    required_fields: tuple[str, ...] # ("api_key", "model")
```

**field_map validation**: `build_engine_kwargs` checks `engine_field in spec.settings_cls.model_fields` at runtime; if the engine field does not exist, logs a warning and skips. No registration-time validation (tolerates pdf2zh-next version upgrades).

**required_fields**: api_key and model are required; base_url is silently optional; all other fields (thinking_mode, reasoning_effort, enable_json_mode, temperature, timeout) log a warning when the engine does not support them but a config value is set.

**config attribute mapping**: An internal `CONFIG_ATTR_MAP` in `build_engine_kwargs` maps unified_names to config module attributes:

```python
CONFIG_ATTR_MAP: dict[str, str] = {
    "model": "MODEL",
    "api_key": "MODEL_API_KEY",
    "base_url": "MODEL_BASE_URL",
    "thinking_mode": "MODEL_THINKING_MODE",
    "reasoning_effort": "MODEL_REASONING_EFFORT",
    "enable_json_mode": "MODEL_ENABLE_JSON_MODE",
    "temperature": "MODEL_TEMPERATURE",
    "timeout": "MODEL_TIMEOUT",
}
```

Note: `model` maps to `MODEL` (not `MODEL_MODEL`), preserving the existing config.toml convention.

### EngineSpec derivation from existing FIELD_MAP

Each engine's `field_map` is mechanically derived: for each `(unified_name, class_name_dict)` in `FIELD_MAP`, if the engine's Settings class name appears as a key, include `unified_name → engine_field_name` in that engine's `field_map`. The `required_fields` tuple is `("api_key", "model")` for all 10 engines.

### Function Interfaces

**`resolve_engine(provider: str) -> EngineSpec`**

Looks up `config.PROVIDER_INDEX[provider]`. If not found, logs info and returns an `EngineSpec` for `OpenAICompatibleSettings` (existing fallback behavior preserved).

**`build_engine_kwargs(spec: EngineSpec) -> dict`**

For each `(unified_name, engine_field)` in `spec.field_map`:
1. Look up `config_attr = CONFIG_ATTR_MAP[unified_name]`
2. Read `value = getattr(config, config_attr, None)`
3. If `value is not None` → `kwargs[engine_field] = value`
4. If `value is None` and `unified_name in spec.required_fields` → `raise RuntimeError`
5. If `value is None` and `unified_name == "base_url"` → silently skip
6. If `value is None` and other optional → `logger.warning`
7. If `engine_field not in spec.settings_cls.model_fields` → `logger.warning`, skip

**`build_settings(...) -> SettingsModel`** (updated call chain)

```python
spec = resolve_engine(config.MODEL_PROVIDER)
engine_kwargs = build_engine_kwargs(spec)
# ...
translate_engine_settings=spec.settings_cls(**engine_kwargs),
```

## Impact

| File | Change |
|------|--------|
| `config.py` | +`EngineSpec`, +`ENGINE_REGISTRY`, +`PROVIDER_INDEX`; −`PROVIDER_MAP`, −`FIELD_MAP` (79 entries) |
| `services.py` | `resolve_engine` return type `type` → `EngineSpec`; `build_engine_kwargs` param `engine_cls` → `spec: EngineSpec`; add `CONFIG_ATTR_MAP`; update `build_settings` call chain |
| `tests/test_engine_registry.py` | New: 10-engine equivalence regression + fake engine extensibility |
| `tests/test_services.py` | Update: remove direct references to `PROVIDER_MAP`/`FIELD_MAP`; `test_config_provider_map_has_deepseek` → equivalents |

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Migration field mapping error (missed or wrong entry) | Equivalence regression tests compare new vs old output for all 10 engines before deleting old code |
| pdf2zh-next Settings class field changes across versions | Runtime `model_fields` check (skip + warn), not registration-time fail-fast |
| Breaking downstream code that imports `PROVIDER_MAP`/`FIELD_MAP` | Only `services.py` imports them; both are deleted together after all call sites migrated |

## Testing Strategy

1. **Equivalence baseline** (`test_engine_registry.py`): For all 10 engines, compare `resolve_engine(provider)` + `build_engine_kwargs` output between old (PROVIDER_MAP + FIELD_MAP) and new (ENGINE_REGISTRY) paths. Capture current behavior as ground truth.
2. **Existing regression** (`test_services.py`): `test_build_settings_*` series must pass unchanged.
3. **Extensibility**: Declare a fake `EngineSpec` with a mock Settings class, verify `resolve_engine("fake")` and `build_engine_kwargs` work correctly from a single declaration.
4. **Full suite**: `pytest tests/ -v` all green, `ruff check` zero errors.

## Non-Goals

- No changes to `config.toml` field names or structure
- No changes to runtime engine selection behavior
- No plugin system or dynamic registration (static registry is sufficient)
