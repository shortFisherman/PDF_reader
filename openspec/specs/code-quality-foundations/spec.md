# code-quality-foundations Specification

## Purpose
TBD - created by archiving change code-quality-improvements. Update Purpose after archive.
## Requirements
### Requirement: Thread-safe global state access

The system SHALL protect all read and write access to the global application state with locking to prevent race conditions under concurrent Flask requests. `replace_page` SHALL hold the state lock for its entire duration (delete, insert, save, close, os.replace, reopen) so concurrent translations serialize and cannot corrupt `right.pdf`. `render_page` SHALL hold the state lock for the entire duration of the render call so the underlying `pymupdf.Document` cannot be closed or replaced mid-render.

#### Scenario: Concurrent page requests

- **WHEN** two HTTP requests read from or write to the global state simultaneously
- **THEN** the state SHALL remain consistent with no corrupted data or KeyError exceptions

#### Scenario: Translation updates translated_pages set

- **WHEN** a translation completes and adds a page number to the translated_pages set
- **THEN** the operation SHALL be atomic and visible to concurrent readers

#### Scenario: Rendering holds lock for full duration

- **WHEN** a render request runs concurrently with a page replacement on the same document
- **THEN** the render SHALL complete against a stable document handle that is not closed or half-saved, and SHALL NOT raise due to a closed/invalid document

#### Scenario: Concurrent translations serialize via state lock

- **WHEN** two translation requests for different pages run concurrently and both attempt to replace pages in right.pdf
- **THEN** the state lock SHALL serialize the full replace_page operations, and the resulting right.pdf SHALL contain both translated pages without corruption

### Requirement: PDF document resource cleanup

The system SHALL close any previously opened pymupdf.Document instances before opening a new PDF file, preventing memory leaks from accumulated open documents.

#### Scenario: Re-open same PDF

- **WHEN** a user opens a PDF, then opens the same PDF again
- **THEN** the previous left_doc and right_doc SHALL be closed before new documents are opened

#### Scenario: Open different PDF

- **WHEN** a user opens a different PDF file
- **THEN** the previous left_doc and right_doc SHALL be closed and the cache directory for the new PDF SHALL be created independently

### Requirement: Type annotations on all Python functions

The system's Python source code SHALL have complete type annotations (PEP 484) on all function signatures, module-level variables, and class attributes.

#### Scenario: Static type checking

- **WHEN** a type checker (e.g., mypy or ruff) is run against the codebase
- **THEN** the checker SHALL report zero type errors

### Requirement: Automated tests for core backend logic

The system SHALL include pytest-based unit tests covering the core backend functions: SHA256 hashing, page rendering, settings model construction, and right.pdf page replacement.

#### Scenario: Test SHA256 computation

- **WHEN** tests are run
- **THEN** the SHA256 function SHALL be verified to produce consistent hashes for known inputs

#### Scenario: Test settings model construction

- **WHEN** tests are run
- **THEN** the settings builder SHALL be verified to produce correct SettingsModel instances with various input combinations (with/without glossary, with/without custom prompt)

#### Scenario: Test page rendering boundaries

- **WHEN** tests are run
- **THEN** the render function SHALL be verified to raise ValueError for out-of-range page numbers

### Requirement: Code linting with zero errors

The system SHALL include a ruff configuration file and SHALL pass linting checks with zero errors when `ruff check` is run against the project.

#### Scenario: Ruff check passes

- **WHEN** `ruff check` is executed in the project root
- **THEN** the command SHALL exit with code 0 and produce no error output

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

### Requirement: Frontend JavaScript in separate file

The system's frontend JavaScript SHALL be extracted from index.html into a separate static/app.js file loaded via a script tag.

#### Scenario: JavaScript loaded externally

- **WHEN** the index page is loaded in a browser
- **THEN** the JavaScript SHALL be loaded from `static/app.js` and all functionality SHALL work identically

### Requirement: Frontend network error handling

The system's frontend SHALL display user-visible error messages when network requests fail, rather than silently ignoring errors.

#### Scenario: Open PDF fails

- **WHEN** the open PDF request fails due to network error
- **THEN** the user SHALL see an error message indicating the failure

#### Scenario: Translation fails

- **WHEN** a translation request fails
- **THEN** the translate button SHALL return to its enabled state and an error message SHALL be displayed

### Requirement: Requirements lock file for reproducible installs

The system SHALL include a requirements.lock file (generated by `pip freeze`) that pins exact dependency versions for reproducible environment setup.

#### Scenario: Lock file matches installed packages

- **WHEN** `pip install -r requirements.lock` is run
- **THEN** the installed package versions SHALL match exactly the versions in the lock file

