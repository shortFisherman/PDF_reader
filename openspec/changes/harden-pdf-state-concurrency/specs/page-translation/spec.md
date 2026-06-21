## ADDED Requirements

### Requirement: Translation page range validation

The system SHALL validate that the requested page index is within the opened document's page range before initiating translation. Out-of-range pages SHALL return a 400 error with a clear message, rather than triggering a low-level PDF engine exception.

#### Scenario: Translate page below range

- **WHEN** a translation is requested for a negative page index
- **THEN** the system SHALL return HTTP 400 with an error response, without invoking the translation engine

#### Scenario: Translate page above range

- **WHEN** a translation is requested for a page index greater than or equal to the document's page count
- **THEN** the system SHALL return HTTP 400 with an error response, without invoking the translation engine

### Requirement: Serialized page replacement for concurrent translations

The system SHALL serialize file replacement operations on the same `right.pdf` so that concurrent translation of different pages cannot corrupt the persisted file. Atomic file replacement (temporary file + `os.replace`) SHALL be used.

#### Scenario: Concurrent translation of different pages

- **WHEN** two translation requests for different pages run concurrently and both attempt to replace their respective pages in right.pdf
- **THEN** the file replacements SHALL be serialized, and the resulting right.pdf SHALL contain both translated pages without corruption

#### Scenario: Atomic write on replace

- **WHEN** a page replacement writes the updated right.pdf
- **THEN** the system SHALL write to a temporary file in the same directory and atomically replace right.pdf via os.replace, so a crash mid-write never leaves a partial right.pdf
