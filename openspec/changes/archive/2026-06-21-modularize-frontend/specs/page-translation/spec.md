## MODIFIED Requirements

### Requirement: Manual per-page translation trigger

The system SHALL allow the user to trigger translation of the currently visible page via a button in the floating toolbar. Translation orchestration and progress UI SHALL reside in dedicated `translator` and `sse-client` frontend modules; behavior SHALL remain identical to the pre-refactor implementation. Stage labels SHALL be fetched from the backend single source of truth rather than hardcoded.

#### Scenario: Translate untranslated page

- **WHEN** the user clicks "Translate" on a page that has not been translated
- **THEN** the `translator` module SHALL request translation and the system SHALL replace the corresponding page in right.pdf with the translated output

#### Scenario: Re-translate already translated page

- **WHEN** the user clicks "Translate" on a page that has already been translated
- **THEN** the system SHALL re-translate the page, overwriting the previous translation in right.pdf

#### Scenario: Translation in progress

- **WHEN** a translation is in progress for a page
- **THEN** the translate button SHALL be disabled and display "Translating..." until completion

#### Scenario: Translation completion

- **WHEN** a page translation completes
- **THEN** the right-column image for that page SHALL refresh to show the translated content within 2 seconds

#### Scenario: SSE stream parsed by sse-client module

- **WHEN** the translation SSE stream is received
- **THEN** the `sse-client` module SHALL read and parse the `data: {json}\n\n` events and invoke the `translator` module's event handlers, identical to pre-refactor behavior

### Requirement: User-facing stage status display

The system SHALL display user-readable Chinese text describing the current translation stage in the progress bar area during translation, using stage labels fetched from the backend single source of truth.

#### Scenario: Layout analysis stage display

- **WHEN** the translation enters the layout_analysis stage
- **THEN** the progress bar area SHALL display the stage label fetched from the backend (e.g., "正在分析版面...") in Chinese

#### Scenario: Translating stage display

- **WHEN** the translation enters the translating stage
- **THEN** the progress bar area SHALL display the fetched stage label followed by paragraph-level progress if available (e.g., "正在翻译... 第3/8 段")

#### Scenario: Generating PDF stage display

- **WHEN** the translation completes text translation and begins generating the output PDF
- **THEN** the progress bar area SHALL display the fetched stage label (e.g., "正在生成译文...") in Chinese

#### Scenario: Translation complete display

- **WHEN** the translation finishes successfully
- **THEN** the progress bar area SHALL display the fetched completion label briefly before returning to its idle state

#### Scenario: Translation error display

- **WHEN** a translation error occurs
- **THEN** the progress bar area SHALL display the error information in red text
