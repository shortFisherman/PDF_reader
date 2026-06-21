# page-translation

## Purpose

Enable on-demand, per-page translation of PDF content using pdf2zh-next with DeepSeek API. Supports custom user prompts per translation request, force retranslation bypassing cache, and single-page output for efficient right.pdf patching.
## Requirements
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

### Requirement: Custom user prompt per translation

The system SHALL allow the user to provide a custom instruction string that is passed to the translation engine alongside the default translation prompt.

#### Scenario: Translation with custom prompt

- **WHEN** the user enters a custom prompt (e.g., "translate waveguide as 波导") before clicking translate
- **THEN** the translation engine SHALL receive the custom prompt and incorporate it into the translation

#### Scenario: Translation without custom prompt

- **WHEN** the user clicks translate without entering a custom prompt
- **THEN** the translation engine SHALL use only the default translation prompt

### Requirement: Translation uses pdf2zh-next with DeepSeek

The system SHALL use pdf2zh-next's `do_translate_async_stream` API with engine settings resolved via the declarative engine registry for all translation operations. The registry SHALL map the configured `provider` to the corresponding pdf2zh-next Settings class and build kwargs from `config.toml`'s `[model]` section.

#### Scenario: Correct engine configuration

- **WHEN** a translation is requested
- **THEN** the system SHALL resolve the engine via the registry using the `provider` from config.toml and configure pdf2zh-next with the corresponding Settings class using the api key and model from config.toml

#### Scenario: Progress streaming with stage information

- **WHEN** a translation is in progress
- **THEN** the system SHALL relay progress events from the translation engine to the frontend via Server-Sent Events (SSE), and each progress event SHALL include the current stage name (e.g., "layout_analysis", "translating") and the overall progress percentage

#### Scenario: Paragraph-level progress in streaming

- **WHEN** the translation engine produces a progress_update event with stage_current and stage_total fields
- **THEN** the SSE event SHALL include the current paragraph index and total paragraph count so the frontend can display progress like "正在翻译 第3/8 段"

#### Scenario: Fallback to OpenAI Compatible for unknown provider

- **WHEN** the configured provider is not found in the engine registry
- **THEN** the system SHALL fall back to OpenAICompatibleSettings and log an info message, identical to current behavior

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

### Requirement: Translation page range validation

The system SHALL validate that the requested page index is within the opened document's page range before initiating translation. Out-of-range pages SHALL return a 400 error with a clear message, rather than triggering a low-level PDF engine exception.

#### Scenario: Translate page below range

- **WHEN** a translation is requested for a negative page index (via direct handler call; Flask's `<int:page>` route converter matches only non-negative integers, so this path is defensive for direct callers)
- **THEN** the system SHALL return HTTP 400 with an error response, without invoking the translation engine

#### Scenario: Translate page above range

- **WHEN** a translation is requested for a page index greater than or equal to the document's page count
- **THEN** the system SHALL return HTTP 400 with an error response, without invoking the translation engine

