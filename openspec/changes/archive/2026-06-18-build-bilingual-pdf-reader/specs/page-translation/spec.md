## ADDED Requirements

### Requirement: Manual per-page translation trigger

The system SHALL allow the user to trigger translation of the currently visible page via a button in the floating toolbar.

#### Scenario: Translate untranslated page

- **WHEN** the user clicks "Translate" on a page that has not been translated
- **THEN** the system SHALL extract the page from the original PDF, send it to the translation engine, and replace the corresponding page in right.pdf with the translated output

#### Scenario: Re-translate already translated page

- **WHEN** the user clicks "Translate" on a page that has already been translated
- **THEN** the system SHALL re-translate the page, overwriting the previous translation in right.pdf

#### Scenario: Translation in progress

- **WHEN** a translation is in progress for a page
- **THEN** the translate button SHALL be disabled and display "Translating..." until completion

#### Scenario: Translation completion

- **WHEN** a page translation completes
- **THEN** the right-column image for that page SHALL refresh to show the translated content within 2 seconds

### Requirement: Custom user prompt per translation

The system SHALL allow the user to provide a custom instruction string that is passed to the translation engine alongside the default translation prompt.

#### Scenario: Translation with custom prompt

- **WHEN** the user enters a custom prompt (e.g., "translate waveguide as 波导") before clicking translate
- **THEN** the translation engine SHALL receive the custom prompt and incorporate it into the translation

#### Scenario: Translation without custom prompt

- **WHEN** the user clicks translate without entering a custom prompt
- **THEN** the translation engine SHALL use only the default translation prompt

### Requirement: Translation uses pdf2zh-next with DeepSeek

The system SHALL use pdf2zh-next's `do_translate_async_stream` API with DeepSeek engine settings for all translation operations.

#### Scenario: Correct engine configuration

- **WHEN** a translation is requested
- **THEN** the system SHALL configure pdf2zh-next with `DeepSeekSettings` using the API key and model from config.toml

#### Scenario: Progress streaming during translation

- **WHEN** a translation is in progress
- **THEN** the system SHALL relay progress events from the translation engine to the frontend via Server-Sent Events (SSE)

### Requirement: Force retranslation ignores cache

The system SHALL bypass any translation cache when translating a page, ensuring fresh results each time.

#### Scenario: Force retranslation

- **WHEN** any translation request is made
- **THEN** the system SHALL configure the translation engine with `ignore_cache=True`

### Requirement: Single-page translation output

The system SHALL configure the translation engine to output only the translated page, not the entire document.

#### Scenario: Single page output

- **WHEN** translating page N
- **THEN** the translation engine SHALL be configured with `pages=N` and `only_include_translated_page=True`, returning a PDF containing only page N's translation
