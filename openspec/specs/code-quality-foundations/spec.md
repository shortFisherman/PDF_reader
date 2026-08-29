# code-quality-foundations Specification

## Purpose
TBD - created by archiving change code-quality-improvements. Update Purpose after archive.
## Requirements
### Requirement: Thread-safe global state access

The system SHALL protect all read and write access to the global application state with locking to prevent race conditions under concurrent Flask requests. `replace_page` SHALL hold the state lock for its entire duration (delete, insert, save, close, os.replace, reopen) so concurrent translations serialize and cannot corrupt `right.pdf`. `render_page` SHALL hold the state lock for the entire duration of the render call so the underlying `pymupdf.Document` cannot be closed or replaced mid-render. Single-page extraction (`extract_page`) SHALL hold the state lock for its full duration so the shared `pymupdf.Document` is never read concurrently with rendering or replacement.

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

#### Scenario: Extraction serializes with rendering via state lock

- **WHEN** a single-page extraction request runs concurrently with a render request on the same opened document
- **THEN** the extraction and render SHALL be serialized by the state lock, and neither SHALL observe a document handle that is closed or being replaced

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

The system SHALL include a ruff configuration file and SHALL pass linting checks with zero errors when `ruff check` is run against the project. The ruff configuration SHALL NOT list any rules that have been removed from ruff (such as `ANN101` / `ANN102`) in its `ignore` set, so running `ruff check` produces no "rules removed, ignoring has no effect" warnings while still passing with zero errors.

#### Scenario: Ruff check passes

- **WHEN** `ruff check` is executed in the project root
- **THEN** the command SHALL exit with code 0, produce no error output, and produce no warning about ignored removed rules

#### Scenario: Removed rules not in ignore set

- **WHEN** `ruff.toml` is inspected
- **THEN** the `ignore` list SHALL NOT contain `ANN101` or `ANN102` (or any other rule ruff reports as removed), while the existing effective lint guarantees are preserved

### Requirement: Modular source code organization

The system SHALL be organized into separate Python modules with clear separation of concerns. `src/pdf_reader/app.py` SHALL be free of import-time side effects: no monkey-patching, no hardcoded debug flags, and no logging at module import. Debug initialization SHALL occur explicitly inside `create_app()`. Debug tracing SHALL be encapsulated in a dedicated `pdf_reader.debug_trace` module.

#### Scenario: Config loading is independent

- **WHEN** config.py is imported
- **THEN** it SHALL load and expose all configuration values without depending on Flask or other modules

#### Scenario: Routes are registered via app

- **WHEN** `pdf_reader.app` creates the Flask application
- **THEN** it SHALL import and register routes from the routes module

#### Scenario: app.py import has no side effects

- **WHEN** `pdf_reader.app` is imported without executing the server
- **THEN** no monkey-patching SHALL be applied, no debug flag SHALL be hardcoded, and no debug logging SHALL occur

#### Scenario: Debug tracing is module-isolated

- **WHEN** business modules need debug tracing
- **THEN** they SHALL call the `debug_trace` module interfaces, and all `if config.DEBUG` branching SHALL live inside `debug_trace.py`, not in route or service business logic

### Requirement: Frontend JavaScript in separate file

The system's frontend JavaScript SHALL be organized into separately importable ES Module files by responsibility, loaded via `<script type="module" src="/static/app.js">` where `app.js` is the thin entry point composing the other modules. All functionality SHALL work identically to the pre-refactor single-file implementation.

#### Scenario: JavaScript loaded as ES modules

- **WHEN** the index page is loaded in a browser
- **THEN** the JavaScript SHALL be loaded as ES Modules starting from `static/app.js`, which imports responsibility-specific modules, and all functionality SHALL work identically

#### Scenario: Frontend network error handling

- **WHEN** an open PDF or translation request fails due to network error
- **THEN** the user SHALL see an error message indicating the failure, handled by the appropriate module

### Requirement: Frontend network error handling

The system's frontend SHALL display user-visible error messages when network requests fail, rather than silently ignoring errors.

#### Scenario: Open PDF fails

- **WHEN** the open PDF request fails due to network error
- **THEN** the user SHALL see an error message indicating the failure

#### Scenario: Translation fails

- **WHEN** a translation request fails
- **THEN** the translate button SHALL return to its enabled state and an error message SHALL be displayed

### Requirement: Requirements lock file for reproducible installs

The system SHALL include a requirements.lock file (generated by pip-tools from `pyproject.toml`, including the `dev` extra) that pins exact dependency versions for reproducible environment setup.

#### Scenario: Lock file matches installed packages

- **WHEN** `pip install -r requirements.lock` is run
- **THEN** the installed package versions SHALL match exactly the versions in the lock file

