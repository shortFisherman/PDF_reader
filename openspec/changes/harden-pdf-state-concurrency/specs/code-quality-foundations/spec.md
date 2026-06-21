## MODIFIED Requirements

### Requirement: Thread-safe global state access

The system SHALL protect all read and write access to the global application state with locking to prevent race conditions under concurrent Flask requests. Critical sections SHALL be minimized: disk IO (file save, os.replace, reopen) SHALL NOT execute while holding the state lock; a separate write lock SHALL serialize atomic file replacement so concurrent translation of different pages cannot corrupt `right.pdf`. Rendering a page SHALL hold the state lock for the entire duration of the render call so the underlying `pymupdf.Document` cannot be closed or replaced mid-render.

#### Scenario: Concurrent page requests

- **WHEN** two HTTP requests read from or write to the global state simultaneously
- **THEN** the state SHALL remain consistent with no corrupted data or KeyError exceptions

#### Scenario: Translation updates translated_pages set

- **WHEN** a translation completes and adds a page number to the translated_pages set
- **THEN** the operation SHALL be atomic and visible to concurrent readers

#### Scenario: Rendering holds lock for full duration

- **WHEN** a render request runs concurrently with a page replacement on the same document
- **THEN** the render SHALL complete against a stable document handle that is not closed or half-saved, and SHALL NOT raise due to a closed/invalid document

#### Scenario: Slow disk IO does not block all state access

- **WHEN** a page replacement performs file save, os.replace, and reopen
- **THEN** the state lock SHALL be released before os.replace and reopen, so concurrent render/open requests are not blocked by disk IO
