## MODIFIED Requirements

### Requirement: Translation uses pdf2zh-next with DeepSeek

The system SHALL use pdf2zh-next's `do_translate_async_stream` API with DeepSeek engine settings for all translation operations.

#### Scenario: Correct engine configuration

- **WHEN** a translation is requested
- **THEN** the system SHALL configure pdf2zh-next with `DeepSeekSettings` using the API key and model from config.toml

#### Scenario: Progress streaming with stage information

- **WHEN** a translation is in progress
- **THEN** the system SHALL relay progress events from the translation engine to the frontend via Server-Sent Events (SSE), and each progress event SHALL include the current stage name (e.g., "layout_analysis", "translating") and the overall progress percentage

#### Scenario: Paragraph-level progress in streaming

- **WHEN** the translation engine produces a progress_update event with stage_current and stage_total fields
- **THEN** the SSE event SHALL include the current paragraph index and total paragraph count so the frontend can display progress like "正在翻译 第 3/8 段"

## ADDED Requirements

### Requirement: User-facing stage status display

The system SHALL display user-readable Chinese text describing the current translation stage in the progress bar area during translation.

#### Scenario: Layout analysis stage display

- **WHEN** the translation enters the layout_analysis stage
- **THEN** the progress bar area SHALL display "正在分析版面..." in Chinese

#### Scenario: Translating stage display

- **WHEN** the translation enters the translating stage
- **THEN** the progress bar area SHALL display "正在翻译..." followed by paragraph-level progress if available (e.g., "正在翻译... 第 3/8 段")

#### Scenario: Generating PDF stage display

- **WHEN** the translation completes text translation and begins generating the output PDF
- **THEN** the progress bar area SHALL display "正在生成译文..." in Chinese

#### Scenario: Translation complete display

- **WHEN** the translation finishes successfully
- **THEN** the progress bar area SHALL display "翻译完成" briefly before returning to its idle state

#### Scenario: Translation error display

- **WHEN** a translation error occurs
- **THEN** the progress bar area SHALL display the error information in red text
