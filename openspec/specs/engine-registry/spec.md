# engine-registry Specification

## Purpose
TBD - created by archiving change data-driven-engine-config. Update Purpose after archive.
## Requirements
### Requirement: Declarative translation engine registry

The system SHALL maintain a declarative engine registry where each supported translation engine is described by a single `EngineSpec` record. The engine resolution and kwargs building logic SHALL reside in a dedicated `engine_resolver` module, not in `services.py`. The `EngineSpec` dataclass and `ENGINE_REGISTRY` list SHALL remain in `config.py`.

#### Scenario: Engine resolution is in dedicated module

- **WHEN** the system needs to resolve an engine or build engine kwargs
- **THEN** it SHALL import from `engine_resolver`, not from `services`

#### Scenario: Registry remains the single source of truth

- **WHEN** the system resolves an engine class or builds engine kwargs
- **THEN** it SHALL consult only the engine registry in `config.py`, and no separate `PROVIDER_MAP` or multi-key `FIELD_MAP` dictionaries SHALL exist

