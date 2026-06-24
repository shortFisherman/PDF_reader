# engine-config Delta: defer-config-validation

## ADDED Requirements

### Requirement: Config import shall not fail on missing config

The `config` module SHALL be importable in any environment, including when `config.toml` does not exist or required model fields are unconfigured. The system SHALL NOT raise any exception at module import time due to missing configuration. When `config.toml` is missing, the loaded `CONFIG` SHALL default to an empty mapping.

#### Scenario: Import config with no config.toml present

- **WHEN** the `config` module is imported in a fresh clone where `config.toml` does not exist
- **THEN** the import SHALL succeed without raising, and `config.CONFIG` SHALL be an empty mapping

#### Scenario: Import config with unconfigured API key present

- **WHEN** the `config` module is imported while `MODEL_API_KEY` / `MODEL` are missing or sentinel (`sk-your-api-key`)
- **THEN** the import SHALL succeed without raising

### Requirement: Required model config validated at consumption time

The system SHALL validate that required model configuration (`MODEL_API_KEY`, `MODEL`) is present at the first business consumption point (`engine_resolver.resolve_engine`), raising a user-facing error matching the original Chinese messages when the configuration is missing or unconfigured.

#### Scenario: Translation consumption reports missing config

- **WHEN** `resolve_engine` is invoked while `MODEL` is unconfigured
- **THEN** the system SHALL raise an error with the original "请设置 model.model" message

#### Scenario: Translation consumption reports missing API key

- **WHEN** `resolve_engine` is invoked while `MODEL_API_KEY` is missing or the `sk-your-api-key` sentinel
- **THEN** the system SHALL raise an error with the original "请设置 model.api_key 或环境变量 MODEL_API_KEY" message

#### Scenario: Correctly configured environment behaves unchanged

- **WHEN** `config.toml` is present and fully configured and a translation is requested
- **THEN** the system SHALL behave exactly as before the change (same validation messages emitted at the same consumption point, same runtime behavior)