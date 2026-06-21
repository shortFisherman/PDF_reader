# pdf-rendering

## Purpose

Render PDF pages as high-resolution PNG images on the server side for display in the bilingual reader's dual-column layout. Uses pymupdf (MuPDF) at 200 DPI to match the rendering quality of a native PDF reader.
## Requirements
### Requirement: Server renders PDF pages as PNG images

The system SHALL render each page of a PDF document as a high-resolution PNG image using pymupdf at 200 DPI.

#### Scenario: Render a single page

- **WHEN** the backend receives a request for page N of an opened PDF
- **THEN** it SHALL return a PNG image rendered at 200 DPI with the page's original dimensions preserved

#### Scenario: Render page from right.pdf (translated side)

- **WHEN** the backend receives a request for a translated page
- **THEN** it SHALL render the corresponding page from the right.pdf file, which may contain translated content

#### Scenario: Page out of range

- **WHEN** the backend receives a request for a page number that exceeds the document's page count
- **THEN** it SHALL return a 404 error

### Requirement: Concurrent-safe page rendering

The system SHALL render pages in a way that is safe under concurrent page replacement. While a page is being replaced (deleted, inserted, saved), concurrent render requests for any page of the same document SHALL NOT observe a closed or half-saved `pymupdf.Document`.

#### Scenario: Render during concurrent page replacement

- **WHEN** a render request for page A is in progress and a concurrent request triggers replacement of page B (or page A) on the same document
- **THEN** the render SHALL complete successfully and return a valid PNG, and SHALL NOT raise an exception or return corrupted bytes

#### Scenario: Document handle not closed mid-render

- **WHEN** a page replacement closes and reopens the right document while a render holds the document handle
- **THEN** the render SHALL have completed before the document is closed, because rendering holds the state lock for its full duration

