## MODIFIED Requirements

### Requirement: Debug trace module isolation

The system SHALL provide a `debug_trace` module that encapsulates debug-detail tracing concerns: per-translation file handler management with log rotation (via `debug_session`), and step/token/glossary trace logging. Business code SHALL interact with debug tracing only through this module's interfaces. The `debug_session` context manager SHALL internally handle file handler creation and cleanup without exposing separate `setup_file_handler` / `cleanup_file_handler` public functions that duplicate its logic. The module SHALL NOT perform monkey-patching of third-party libraries; the former `AutomaticTermExtractor` monkey-patch is removed.

#### Scenario: Business code uses debug_trace interfaces

- **WHEN** the translation flow needs to log a step, token usage, or glossary merge
- **THEN** it SHALL call `debug_trace.log_step` / `log_token_usage` / `log_glossary_merge`, and SHALL NOT contain inline `if config.DEBUG` checks

#### Scenario: Debug session context management

- **WHEN** a translation starts with debug enabled
- **THEN** a `debug_session` context manager SHALL create the file handler (with log rotation), add it to the trace logger, and SHALL remove and close it on exit, even if the translation raises

#### Scenario: No duplicate file handler logic

- **WHEN** `debug_trace.py` is inspected
- **THEN** the file handler creation/cleanup logic SHALL exist in exactly one place (`debug_session`), not duplicated in separate public functions

#### Scenario: No monkey-patching

- **WHEN** `debug_trace.py` is inspected
- **THEN** there is no `_apply_monkey_patches`, no `patched_extract`, no `_original_extract`, and no `AutomaticTermExtractor` import or attribute reassignment

#### Scenario: No inline debug checks in route/service code

- **WHEN** `routes.py` and service modules are scanned
- **THEN** there SHALL be zero occurrences of `if config.DEBUG` or `if debug` inline checks in business logic; all debug branching SHALL live inside `debug_trace.py`
