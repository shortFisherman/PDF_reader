## MODIFIED Requirements

### Requirement: Translation output is written to a temporary directory
The system SHALL write all translation byproduct files to a dedicated temporary directory instead of the project root directory. Page replacement into `right.pdf` SHALL use atomic write (temporary file in the same directory + `os.replace`), and concurrent page replacements on the same `right.pdf` SHALL be serialized so they cannot corrupt each other.

#### Scenario: Successful translation does not pollute root
- **WHEN** a page translation is triggered via `/api/translate/<page>`
- **THEN** no `*.glossary.csv`, `*.mono.pdf`, or other byproduct files are created in the project root directory

#### Scenario: Translated content is correctly integrated
- **WHEN** a page translation completes successfully
- **THEN** the translated PDF content is correctly inserted into the right-side document

#### Scenario: Concurrent translations do not corrupt right.pdf
- **WHEN** two page translations complete concurrently and both replace pages in right.pdf
- **THEN** right.pdf SHALL remain a valid PDF containing both translated pages, with no interleaved or truncated writes
