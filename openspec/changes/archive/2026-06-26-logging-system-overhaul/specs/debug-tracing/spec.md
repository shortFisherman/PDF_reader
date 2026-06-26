## MODIFIED Requirements

### Requirement: Debug mode activation

The system SHALL support debug mode driven by `config.toml` (default False) or the `--debug` CLI flag. `config.DEBUG` SHALL NOT be hardcoded to True at import time; it SHALL be resolved from configuration. When debug mode is enabled, the root `pdf_reader` logger level SHALL be lowered to DEBUG so that DEBUG-level details (high-frequency render logs, token usage, third-party library detail) become visible; when disabled, the root level SHALL be INFO so that INFO flow milestones remain visible. The previous "debug off = zero overhead / behaves identically to pre-debug release / no trace logging" guarantee is superseded: INFO flow logging is now always active by design (see `application-logging` capability).

#### Scenario: Debug mode enabled via CLI

- **WHEN** user starts the app with `python app.py --debug`
- **THEN** `config.DEBUG` is `True` and `setup_logging(True)` sets the root `pdf_reader` logger level to DEBUG, making DEBUG-level details visible

#### Scenario: Debug mode enabled via config

- **WHEN** `config.toml` sets debug enabled to true and the app starts without `--debug`
- **THEN** `config.DEBUG` is `True` and the root logger level is DEBUG

#### Scenario: Debug mode disabled (default) still emits flow logs

- **WHEN** user starts the app with `python app.py` (no `--debug`) and config does not enable debug
- **THEN** the root `pdf_reader` logger level is INFO, INFO flow milestones are emitted, and DEBUG-only details (render per page, token usage, third-party detail) are not shown

#### Scenario: No import-time side effects

- **WHEN** `app.py` is imported (without running the server)
- **THEN** no logging initialization SHALL occur; `setup_logging` SHALL happen only inside `create_app()` based on resolved config

### Requirement: Translation pipeline step logging

The system SHALL log each major step in the translation pipeline via the `pdf_reader.translate` / `pdf_reader.lifecycle` loggers. Flow milestones (build settings, submit page/batch, translation done with elapsed time, replace page, merge glossary) SHALL be emitted at INFO regardless of debug mode. Detailed inputs (full PDF path, glossary paths, token usage, term batch internals) SHALL be emitted at DEBUG. Each record SHALL carry the page correlation marker (`[page=N]` or `[batch=from-to]`).

#### Scenario: Single page translation milestones

- **WHEN** user requests translation of page 1 with debug off
- **THEN** INFO logs show: submit page 1, translation done (with elapsed seconds), replace page 1, merge glossary done — each carrying `[page=1]`

#### Scenario: Detailed inputs at debug only

- **WHEN** debug is on and a translation runs
- **THEN** DEBUG logs include the full PDF path, glossary paths, and token usage; these DEBUG records are absent when debug is off

#### Scenario: Translation failure

- **WHEN** a translation step fails with an exception
- **THEN** an ERROR log includes the step name, the page correlation marker, the exception type and message, and the traceback via `exc_info`

## REMOVED Requirements

### Requirement: LLM term extraction transparency

**Reason**: The monkey-patch on `AutomaticTermExtractor.extract_terms_from_paragraphs` was introduced to diagnose a term-extraction failure that has since been resolved. It couples the project to babeldoc internals and breaks on babeldoc upgrades. The new `application-logging` capability provides flow-level observability (whether the term-extraction stage was reached) without introspecting babeldoc internals.

**Migration**: Term-extraction internal tracing is no longer provided by this project. If deep term-extraction debugging is needed in the future, set `TranslationConfig.debug = True` so babeldoc emits its own `term_extractor_tracking.json` / `term_extractor_freq.json` / `auto_extractor_glossary.csv`, or temporarily reintroduce a patch. The `debug-tracing` spec no longer requires this capability.
