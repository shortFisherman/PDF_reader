# page-translation Delta: fix-concurrency-resource-cleanup

## MODIFIED Requirements

### Requirement: Single-page translation output

The system SHALL configure the translation engine to output only the translated page, not the entire document. The single-page PDF extraction SHALL be performed under the AppState lock via a dedicated `extract_page` entry point, so that extraction and rendering share the same lock and cannot race on the underlying `pymupdf.Document` handle.

#### Scenario: Single page output

- **WHEN** translating page N
- **THEN** the translation engine SHALL be configured with `pages=N` and `only_include_translated_page=True`, returning a PDF containing only page N's translation

#### Scenario: Extraction holds the state lock

- **WHEN** a single-page extraction runs concurrently with a render request on the same document
- **THEN** the extraction SHALL hold the AppState lock for its full duration, serializing against rendering so the shared document handle is not used concurrently

#### Scenario: No raw document handle escapes AppState

- **WHEN** the translate route needs a single-page PDF
- **THEN** it SHALL obtain it via `AppState.extract_page` and SHALL NOT pass `state.left_doc` directly to `pdf_extraction`, so all document reads occur under the lock