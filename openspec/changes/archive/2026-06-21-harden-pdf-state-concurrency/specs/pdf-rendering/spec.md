## ADDED Requirements

### Requirement: Concurrent-safe page rendering

The system SHALL render pages in a way that is safe under concurrent page replacement. While a page is being replaced (deleted, inserted, saved), concurrent render requests for any page of the same document SHALL NOT observe a closed or half-saved `pymupdf.Document`.

#### Scenario: Render during concurrent page replacement

- **WHEN** a render request for page A is in progress and a concurrent request triggers replacement of page B (or page A) on the same document
- **THEN** the render SHALL complete successfully and return a valid PNG, and SHALL NOT raise an exception or return corrupted bytes

#### Scenario: Document handle not closed mid-render

- **WHEN** a page replacement closes and reopens the right document while a render holds the document handle
- **THEN** the render SHALL have completed before the document is closed, because rendering holds the state lock for its full duration
