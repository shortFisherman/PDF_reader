## MODIFIED Requirements

### Requirement: Modular source code organization

The system SHALL be organized into separate Python modules with clear separation of concerns: `config.py` (configuration), `routes.py` (HTTP routing, thin), `services.py` (pure helpers), and a translation service layer (`pdf_extraction`, `translation_orchestrator`, `sse_stream`, `glossary_service`, `debug_trace`) that isolates business orchestration from HTTP handling. `app.py` serves as the application entry point and factory.

#### Scenario: Config loading is independent

- **WHEN** config.py is imported
- **THEN** it SHALL load and expose all configuration values without depending on Flask or other modules

#### Scenario: Routes are registered via app

- **WHEN** app.py creates the Flask application
- **THEN** it SHALL import and register routes from the routes module

#### Scenario: Route layer delegates to service layer

- **WHEN** a translation request is handled by the route function
- **THEN** the route SHALL delegate PDF extraction, translation orchestration, SSE formatting, glossary handling, and debug tracing to dedicated service modules, and SHALL NOT contain those concerns inline
