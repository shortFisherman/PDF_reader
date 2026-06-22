## MODIFIED Requirements

### Requirement: Right.pdf as translation state

The system SHALL maintain a right.pdf file that stores the current translation state, where translated pages contain translated content and untranslated pages contain the original content. The page replacement operation SHALL be invoked by the translation lifecycle module, which receives the necessary callable context from the route layer rather than accessing AppState directly.

#### Scenario: First open creates right.pdf

- **WHEN** a PDF is opened for the first time
- **THEN** the system SHALL compute the SHA256 hash of the original PDF and create `cache/<sha256>/right.pdf` as an exact copy of the original

#### Scenario: Subsequent open restores state

- **WHEN** a PDF that was previously opened and partially translated is opened again
- **THEN** the system SHALL detect the existing right.pdf via SHA256 hash match and load it, preserving all prior translations

#### Scenario: Translation updates right.pdf

- **WHEN** a page is translated
- **THEN** the translation lifecycle module SHALL invoke the page replacement operation, which replaces the corresponding page in right.pdf with the translated output and saves the file
