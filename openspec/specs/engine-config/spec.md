# engine-config Specification

## Purpose
TBD - created by archiving change refactor-module-cohesion. Update Purpose after archive.
## Requirements
### Requirement: Engine configuration module

The system SHALL provide an `engine_resolver` module that encapsulates engine lookup, field mapping, and kwargs building. The module SHALL export `resolve_engine()`, `build_engine_kwargs()`, and `CONFIG_ATTR_MAP`, and SHALL NOT import or depend on `services.py`.

#### Scenario: Engine resolution from provider name

- **WHEN** `resolve_engine("deepseek")` is called
- **THEN** the module SHALL return the EngineSpec matching the provider, using `PROVIDER_INDEX` from `config.py`

#### Scenario: Unknown provider falls back

- **WHEN** `resolve_engine("unknown_provider")` is called
- **THEN** the module SHALL fall back to the `openai_compatible` engine spec

#### Scenario: Engine kwargs built from config

- **WHEN** `build_engine_kwargs(spec)` is called for a valid EngineSpec
- **THEN** the module SHALL dynamically map unified config field names to engine-specific field names using `spec.field_map`

