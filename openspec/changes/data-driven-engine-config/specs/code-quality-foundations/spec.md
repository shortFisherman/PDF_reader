## MODIFIED Requirements

### Requirement: Modular source code organization

The system SHALL be organized into separate Python modules with clear separation of concerns. Engine configuration SHALL be data-driven via a single declarative registry rather than scattered dictionaries. `config.py` SHALL expose the engine registry as the single source of truth for provider-to-settings-class and unified-field-to-engine-field mappings.

#### Scenario: Config loading is independent

- **WHEN** config.py is imported
- **THEN** it SHALL load and expose all configuration values without depending on Flask or other modules

#### Scenario: Routes are registered via app

- **WHEN** app.py creates the Flask application
- **THEN** it SHALL import and register routes from the routes module

#### Scenario: Engine mapping is data-driven

- **WHEN** the engine configuration is inspected
- **THEN** it SHALL be driven by a single registry structure, and no separate `PROVIDER_MAP` or multi-key `FIELD_MAP` dictionaries SHALL exist alongside it
