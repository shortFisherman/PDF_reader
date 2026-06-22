## ADDED Requirements

### Requirement: Translation lifecycle module

The system SHALL provide a `translation_lifecycle` module that encapsulates all post-translation operations: persisting the translated page into right.pdf, merging auto-extracted terminology into the cumulative glossary, and cleaning up temporary directories. The SSE streaming module SHALL delegate to this module for post-translation actions rather than calling state.replace_page and glossary merging directly.

#### Scenario: Translation completion triggers lifecycle

- **WHEN** a translation completes successfully (translate_result is available)
- **THEN** the translation lifecycle module SHALL replace the translated page in right.pdf via AppState.replace_page and merge auto-extracted glossary terms

#### Scenario: Lifecycle handles missing output

- **WHEN** translate_result has no mono_pdf_path and no dual_pdf_path
- **THEN** the translation lifecycle module SHALL raise an error that propagates as an SSE error event

#### Scenario: Temporary directory cleanup

- **WHEN** translation lifecycle runs (success or failure)
- **THEN** the temporary directories created for single-page extraction and translation output SHALL be removed
