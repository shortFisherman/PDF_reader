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
