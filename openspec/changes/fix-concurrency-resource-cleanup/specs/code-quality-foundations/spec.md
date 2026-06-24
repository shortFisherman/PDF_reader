# code-quality-foundations Delta: fix-concurrency-resource-cleanup

## MODIFIED Requirements

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