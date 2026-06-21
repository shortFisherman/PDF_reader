## MODIFIED Requirements

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
