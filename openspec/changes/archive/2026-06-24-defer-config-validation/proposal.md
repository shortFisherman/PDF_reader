# Proposal: defer-config-validation

## Why

当前 `config.py` 在模块导入期（`config.py:36-39`）即校验 `MODEL_API_KEY` 和 `MODEL`，一旦缺失就 `raise ValueError`。`config.toml` 已被 `.gitignore` 忽略，导致全新克隆（如 CI 环境、新协作者）中任何 `import config` 都会立即抛错，使整个测试套件无法运行、CI 无法建立。本变更将校验从导入期推迟到配置首次被实际消费时，让模块导入在任意环境下都能成功，为后续 CI 变更和测试可移植性铺路。

## What Changes

- 将 `MODEL_API_KEY` / `MODEL` 的强制校验从模块导入期移至首次使用时（延迟校验），导入 `config` 不再因未配置而抛错。
- 保留延迟到真正消费配置的服务层入口触发校验（如 `engine_resolver.resolve_engine` / `translation_settings.build_settings`）。
- **BREAKING**（仅对未配置环境下直接 `import config` 的外部脚本）：原先导入即报错，现在改为导入成功、使用时才报错。
- 调整 `tests/conftest.py` 的 `mock_config` 及受影响测试，确保测试可在无 `config.toml` 的环境下运行。
- 不改 `config.toml` 的 schema、不改业务运行时行为（已正确配置的环境表现完全一致）。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `engine-config`: 配置校验时机改变——从模块导入期延迟到消费期；新增「导入不抛错、缺失配置在消费时报错」的需求。

## Impact

- **代码**：`config.py`（校验逻辑迁移）、`engine_resolver.py`（消费期校验触发点）、`tests/conftest.py` 与若干测试 fixture。
- **依赖**：无新增依赖。
- **下游**：是 `add-ci-and-lint-cleanup` 变更的前置依赖（CI 全新克隆需 `import config` 成功）。
- **风险**：延迟校验可能让「配置缺失」错误晚于预期暴露；通过在翻译端点等关键消费点显式校验并保持原错误文案来控制。