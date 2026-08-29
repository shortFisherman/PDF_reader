# application-logging Specification

## Purpose
TBD - created by archiving change logging-system-overhaul. Update Purpose after archive.
## Requirements
### Requirement: Centralized logging configuration

The system SHALL provide a `logging_config` module that performs all logging setup via a single `setup_logging(debug: bool)` entry point, called once at application startup. The setup SHALL configure the root `pdf_reader.*` logger namespace, per-module child loggers, console + rotating file handlers, and formatters. `src/pdf_reader/app.py` SHALL NOT use `logging.basicConfig`; all logging configuration SHALL flow through `pdf_reader.logging_config.setup_logging`.

#### Scenario: Setup invoked at startup

- **WHEN** the application starts (via `create_app` or `app.run`)
- **THEN** `logging_config.setup_logging(config.DEBUG)` is called exactly once and the root `pdf_reader` logger has both a console handler and a rotating file handler attached

#### Scenario: No basicConfig in app

- **WHEN** `src/pdf_reader/app.py` is inspected
- **THEN** there is no call to `logging.basicConfig`; logging initialization is delegated to `logging_config`

### Requirement: Per-module logger hierarchy

The system SHALL organize loggers under a `pdf_reader.*` namespace with one child logger per concern: `pdf_reader.app`, `pdf_reader.state`, `pdf_reader.render`, `pdf_reader.extract`, `pdf_reader.translate`, `pdf_reader.lifecycle`, `pdf_reader.glossary`, `pdf_reader.engine`, `pdf_reader.routes`, and `pdf_reader.debug_trace`. Each module SHALL obtain its logger via `logging.getLogger("pdf_reader.<concern>")` and SHALL NOT log through the anonymous root logger.

#### Scenario: Module uses namespaced logger

- **WHEN** any covered module (`state.py`, `pdf_renderer.py`, `pdf_extraction.py`, `translation_orchestrator.py`, `sse_stream.py`, `translation_lifecycle.py`, `glossary_service.py`, `routes.py`, `engine_resolver.py`, `translation_settings.py`) logs a message
- **THEN** the log record's logger name is one of the `pdf_reader.<concern>` names, not `root` and not a bare third-party name

### Requirement: INFO flow logging is always active

The system SHALL emit INFO-level flow logs during normal operation regardless of the debug flag. Flow logs SHALL cover the milestones: opening a PDF, extracting page(s), translation start/end with elapsed time, replacing translated page(s) into `right.pdf`, and glossary merge completion. The debug flag SHALL NOT gate the existence of flow logs; it SHALL only adjust the root level (INFO when off, DEBUG when on) and whether third-party detail is shown.

#### Scenario: Flow logs present with debug off

- **WHEN** a user opens a PDF and translates one page with debug off
- **THEN** the logs contain INFO records for: open PDF (with hash and page count), extract page, translation start, translation end with elapsed seconds, replace page, glossary merge done

#### Scenario: Debug flag does not silence flow

- **WHEN** debug is off and a translation runs
- **THEN** the translation step / token usage trace functions do not return early solely because `config.DEBUG` is false; flow milestones are emitted at INFO

### Requirement: Open PDF logging

The system SHALL log at INFO when a PDF is opened, including the file hash, page count, page width/height, and whether the cache directory was newly created versus reused.

#### Scenario: Open PDF emits metadata

- **WHEN** `state.open_pdf` completes successfully
- **THEN** an INFO log record under `pdf_reader.state` contains the pdf hash, page count, and page dimensions

### Requirement: State change logging for right.pdf

The system SHALL log at INFO when translated page(s) are replaced into `right.pdf`, recording the page index (or indices), the target path, and success. A failed replace SHALL log at ERROR with `exc_info`.

#### Scenario: Replace page success

- **WHEN** `state.replace_page` successfully inserts a translated page into `right.pdf`
- **THEN** an INFO log record under `pdf_reader.state` contains the page index and the right.pdf path

#### Scenario: Replace page failure

- **WHEN** `state.replace_page` raises an exception
- **THEN** an ERROR log record under `pdf_reader.state` is emitted with `exc_info` and the page index

### Requirement: Translation orchestrator boundary logging

The system SHALL log at INFO when the async translation thread starts (with page context) and when it ends, and SHALL log at ERROR with `exc_info` if the thread captures an exception before signalling completion. The `thread.join(timeout=5)` timeout path SHALL log at WARNING if the thread did not terminate within the timeout.

#### Scenario: Thread starts and ends

- **WHEN** `run_translation` spawns its worker thread for a page
- **THEN** INFO records under `pdf_reader.translate` mark thread start and thread end

#### Scenario: Thread exception captured

- **WHEN** the worker thread raises an exception
- **THEN** an ERROR record under `pdf_reader.translate` is emitted with `exc_info` before `TranslationError` is raised

#### Scenario: Join timeout

- **WHEN** `thread.join(timeout=5)` returns but the thread is still alive
- **THEN** a WARNING record under `pdf_reader.translate` is emitted noting the timeout

### Requirement: High-frequency render logging is DEBUG

The system SHALL log page rendering at DEBUG level (not INFO), because rendering is invoked per page view/scroll and would flood the logs at INFO.

#### Scenario: Render not logged at INFO

- **WHEN** debug is off and `state.render_page` renders a page
- **THEN** no INFO record is emitted for the render call; any render log appears only at DEBUG when debug is on

### Requirement: Translation flow page correlation

The system SHALL include a page correlation marker in all translation-flow log records: `[page=N]` for single-page translation and `[batch=from-to]` for batch translation. The marker SHALL be present on extract, translate, replace, and merge records for that flow.

#### Scenario: Single page correlation

- **WHEN** page 2 is translated
- **THEN** the extract, translate start, translate end, replace, and merge log records each contain `[page=2]`

#### Scenario: Batch correlation

- **WHEN** pages 3 through 5 are translated as a batch
- **THEN** the extract, translate start, translate end, replace, and merge log records each contain `[batch=3-5]`

### Requirement: Contextual error logging in SSE stream

The system SHALL, when `sse_stream.generate` / `generate_batch` catches an exception, emit an ERROR record that includes the page (or batch range), a settings summary (provider, model, lang_in, lang_out, pages), and the temp directory, in addition to `exc_info`. The bare `logger.warning("... generate error", exc_info=True)` form without context SHALL be removed.

#### Scenario: Translate page error carries context

- **WHEN** `generate` catches an exception for page N
- **THEN** the ERROR record contains `[page=N]`, the provider, the model, and `exc_info`

#### Scenario: Translate batch error carries context

- **WHEN** `generate_batch` catches an exception for batch from-to
- **THEN** the ERROR record contains `[batch=from-to]`, the provider, the model, and `exc_info`

### Requirement: Startup configuration summary

The system SHALL, at startup, emit one INFO record under `pdf_reader.app` summarizing the active configuration: provider, model, lang_in, lang_out, cache_dir, dpi, and debug state. The API key SHALL NOT appear in the summary.

#### Scenario: Startup log contains config summary and excludes api_key

- **WHEN** the application starts
- **THEN** an INFO record under `pdf_reader.app` lists provider, model, lang_in, lang_out, cache_dir, dpi, and debug flag, and does not contain the api_key value

### Requirement: Third-party library noise demotion

The system SHALL demote the `werkzeug`, `pdf2zh_next`, and `babeldoc` top-level loggers based on the debug flag: WARNING when debug is off (suppressing their INFO/DEBUG records) and DEBUG when debug is on (so their detail becomes visible because the root handler level permits DEBUG).

#### Scenario: Werkzeug request logs hidden when debug off

- **WHEN** debug is off and an HTTP request is served
- **THEN** no INFO record from `werkzeug` appears in the console or file output

#### Scenario: Third-party detail visible when debug on

- **WHEN** debug is on
- **THEN** the third-party loggers are at DEBUG, and INFO records from `pdf2zh_next` and `babeldoc` are visible because the handlers accept DEBUG-and-above

### Requirement: Console and rotating file dual output

The system SHALL attach a `StreamHandler` (console) and a `RotatingFileHandler` to `logs/pdf_reader.log` (maxBytes=5MB, backupCount=5, utf-8) to the `pdf_reader` namespace. Both handlers SHALL use the same formatter. The `logs/` directory SHALL be created if missing.

#### Scenario: Both handlers attached

- **WHEN** `setup_logging` completes
- **THEN** the `pdf_reader` logger has exactly one console handler and one rotating file handler, and `logs/pdf_reader.log` is writable

#### Scenario: File rotation caps disk usage

- **WHEN** the log file exceeds 5MB
- **THEN** the current file is rotated and at most 5 backup files are retained, capping total log disk usage at approximately 30MB

### Requirement: No secrets in logs

The system SHALL NOT log API keys or the raw `api_key` config value. Settings summaries SHALL include only provider, model, language, and path metadata.

#### Scenario: Api key never logged

- **WHEN** any logging statement executes, including startup summary and error context
- **THEN** the api_key value does not appear in any log record
