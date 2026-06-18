# translation-persistence

## Purpose

Persist translation state across sessions by maintaining a right.pdf file keyed on the original PDF's SHA256 hash. Translated pages replace their counterpart in right.pdf, while untranslated pages remain as copies of the original. Reopening the same PDF restores all prior translations.

## Requirements

### Requirement: Right.pdf as translation state

The system SHALL maintain a right.pdf file that stores the current translation state, where translated pages contain translated content and untranslated pages contain the original content.

#### Scenario: First open creates right.pdf

- **WHEN** a PDF is opened for the first time
- **THEN** the system SHALL compute the SHA256 hash of the original PDF and create `cache/<sha256>/right.pdf` as an exact copy of the original

#### Scenario: Subsequent open restores state

- **WHEN** a PDF that was previously opened and partially translated is opened again
- **THEN** the system SHALL detect the existing right.pdf via SHA256 hash match and load it, preserving all prior translations

#### Scenario: Translation updates right.pdf

- **WHEN** a page is translated
- **THEN** the system SHALL replace the corresponding page in right.pdf with the translated output and save the file

### Requirement: SHA256-based cache identification

The system SHALL use the SHA256 hash of the original PDF file as the cache directory name to uniquely identify each document's translation state.

#### Scenario: Hash computation on open

- **WHEN** a PDF is opened via the API
- **THEN** the system SHALL compute the SHA256 hash of the entire file content and use it to resolve the cache directory

#### Scenario: Different PDFs have separate caches

- **WHEN** two different PDF files are opened
- **THEN** the system SHALL create separate cache directories for each, identified by their respective SHA256 hashes

#### Scenario: Same PDF reuses cache

- **WHEN** the same PDF file (identical content) is opened again
- **THEN** the system SHALL reuse the existing cache directory with matching SHA256 hash

### Requirement: PDF file save strategy

The system SHALL save right.pdf using full rewrite mode (not incremental) after each translation to prevent file fragmentation.

#### Scenario: Full rewrite on save

- **WHEN** right.pdf is modified (a page is inserted or replaced)
- **THEN** the system SHALL call `pymupdf.Document.save()` without incremental mode to fully rewrite and compact the file
