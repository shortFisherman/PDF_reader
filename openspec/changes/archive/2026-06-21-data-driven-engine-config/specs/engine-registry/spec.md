## ADDED Requirements

### Requirement: Declarative translation engine registry

The system SHALL maintain a declarative engine registry where each supported translation engine is described by a single `EngineSpec` record containing: the provider key, the pdf2zh-next Settings class, and the complete field mapping from unified config names to engine-specific field names. Adding a new engine SHALL require exactly one new `EngineSpec` declaration and no edits to scattered dictionaries.

#### Scenario: Add a new engine via single declaration

- **WHEN** a developer adds a new engine by appending one `EngineSpec` to the registry
- **THEN** the engine SHALL be selectable via `config.toml`'s `provider` field and its settings SHALL be built correctly, with no other source edits required

#### Scenario: Registry is the single source of truth

- **WHEN** the system resolves an engine class or builds engine kwargs
- **THEN** it SHALL consult only the engine registry, and no separate `PROVIDER_MAP` or multi-key `FIELD_MAP` dictionaries SHALL exist

#### Scenario: Engine field mapping is colocated

- **WHEN** inspecting an engine's supported fields (api_key, model, base_url, thinking_mode, etc.)
- **THEN** all field mappings for that engine SHALL be found in its single `EngineSpec.field_map`, not spread across multiple top-level dictionaries
