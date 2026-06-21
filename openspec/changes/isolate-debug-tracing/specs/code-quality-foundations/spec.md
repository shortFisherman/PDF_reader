## MODIFIED Requirements

### Requirement: Modular source code organization

The system SHALL be organized into separate Python modules with clear separation of concerns. `app.py` SHALL be free of import-time side effects: no monkey-patching, no hardcoded debug flags, and no logging at module import. Debug initialization SHALL occur explicitly inside `create_app()`. Debug tracing SHALL be encapsulated in a dedicated `debug_trace` module.

#### Scenario: Config loading is independent

- **WHEN** config.py is imported
- **THEN** it SHALL load and expose all configuration values without depending on Flask or other modules

#### Scenario: Routes are registered via app

- **WHEN** app.py creates the Flask application
- **THEN** it SHALL import and register routes from the routes module

#### Scenario: app.py import has no side effects

- **WHEN** `app.py` is imported without executing the server
- **THEN** no monkey-patching SHALL be applied, no debug flag SHALL be hardcoded, and no debug logging SHALL occur

#### Scenario: Debug tracing is module-isolated

- **WHEN** business modules need debug tracing
- **THEN** they SHALL call the `debug_trace` module interfaces, and all `if config.DEBUG` branching SHALL live inside `debug_trace.py`, not in route or service business logic
