# debug-trace-module Specification

## Purpose
TBD - created by archiving change isolate-debug-tracing. Update Purpose after archive.
## Requirements
### Requirement: Debug trace module isolation

The system SHALL provide a dedicated `debug_trace` module that encapsulates all debug tracing concerns: conditional monkey-patching, per-translation file handler management with log rotation, and step/token/glossary trace logging. Business code SHALL interact with debug tracing only through this module's interfaces, not via inline `if config.DEBUG` checks.

#### Scenario: Business code uses debug_trace interfaces

- **WHEN** the translation flow needs to log a step, token usage, or glossary merge
- **THEN** it SHALL call `debug_trace.log_step` / `log_token_usage` / `log_glossary_merge`, and SHALL NOT contain inline `if config.DEBUG` checks

#### Scenario: Debug session context management

- **WHEN** a translation starts with debug enabled
- **THEN** a `debug_session` context manager SHALL add the file handler (with log rotation) and SHALL remove it on exit, even if the translation raises

#### Scenario: No inline debug checks in route/service code

- **WHEN** `routes.py` and service modules are scanned
- **THEN** there SHALL be zero occurrences of `if config.DEBUG` or `if debug` inline checks in business logic; all debug branching SHALL live inside `debug_trace.py`

