# translation-lifecycle Delta: fix-concurrency-resource-cleanup

## MODIFIED Requirements

### Requirement: Translation lifecycle module

The system SHALL provide a `translation_lifecycle` module that encapsulates all post-translation operations: persisting the translated page into right.pdf and merging auto-extracted terminology into the cumulative glossary. Temporary directory cleanup SHALL NOT be the responsibility of the lifecycle module's success path alone; the SSE streaming layer SHALL guarantee cleanup of the temporary directories (`tmpdir` and `output_dir`) on every exit path from the translation stream — success, error event, missing translation result, raised exception, or client disconnect. The SSE streaming module SHALL delegate page-replacement and glossary-merge to the lifecycle module rather than calling state.replace_page and glossary merging directly.

#### Scenario: Translation completion triggers lifecycle

- **WHEN** a translation completes successfully (translate_result is available)
- **THEN** the translation lifecycle module SHALL replace the translated page in right.pdf via AppState.replace_page and merge auto-extracted glossary terms

#### Scenario: Lifecycle handles missing output

- **WHEN** translate_result has no mono_pdf_path and no dual_pdf_path
- **THEN** the translation lifecycle module SHALL raise an error that propagates as an SSE error event

#### Scenario: Cleanup on successful translation

- **WHEN** a translation completes successfully and the stream exits normally
- **THEN** the temporary directories created for single-page extraction and translation output SHALL be removed

#### Scenario: Cleanup on error event early return

- **WHEN** the translation stream yields an error event and the generator returns early before invoking the lifecycle module
- **THEN** the temporary directories SHALL still be removed

#### Scenario: Cleanup on missing translation result

- **WHEN** the translation stream finishes without producing a translate_result (no translation result) and the generator returns early
- **THEN** the temporary directories SHALL still be removed

#### Scenario: Cleanup on client disconnect

- **WHEN** the client disconnects mid-stream, causing the generator to be closed (GeneratorExit)
- **THEN** the temporary directories SHALL still be removed