## ADDED Requirements

### Requirement: Translation output is written to a temporary directory
The system SHALL write all translation byproduct files to a dedicated temporary directory instead of the project root directory.

#### Scenario: Successful translation does not pollute root
- **WHEN** a page translation is triggered via `/api/translate/<page>`
- **THEN** no `*.glossary.csv`, `*.mono.pdf`, or other byproduct files are created in the project root directory

#### Scenario: Translated content is correctly integrated
- **WHEN** a page translation completes successfully
- **THEN** the translated PDF content is correctly inserted into the right-side document

### Requirement: Temporary output directory is cleaned up after translation
The system SHALL remove the temporary output directory and all its contents when the translation operation completes, regardless of success or failure.

#### Scenario: Cleanup after successful translation
- **WHEN** a page translation completes successfully
- **THEN** the temporary output directory no longer exists

#### Scenario: Cleanup after failed translation
- **WHEN** a page translation fails with an error
- **THEN** the temporary output directory no longer exists
