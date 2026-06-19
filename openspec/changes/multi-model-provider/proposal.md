## Why

当前翻译服务硬编码了 DeepSeekSettings，用户无法切换模型供应商。pdf2zh-next 底层已内置十几种翻译引擎和通用 OpenAICompatibleSettings，但项目没有暴露出切换能力。用户需要频繁在 DeepSeek、MiniMax、小米 MIMO 等厂商间切换，每次切换不应需改代码。

## What Changes

- **BREAKING**: `config.toml` 中 `[deepseek]` 段重命名为 `[model]`，字段统一为 `provider` / `api_key` / `model` / `base_url` + 可选高级选项
- 新增引擎查表路由：根据 `provider` 值自动选择 pdf2zh-next 对应引擎类，专用引擎优先，未匹配的走 OpenAICompatibleSettings 通用兜底
- 支持可选的模型高级参数（thinking_mode / reasoning_effort / enable_json_mode / temperature / timeout），不支持的引擎自动忽略
- 创建 `config.example.toml` 完整模板，含所有厂商示例和可选参数说明
- 更新 README 配置章节

## Capabilities

### New Capabilities

- `multi-model-provider`: 支持多模型供应商的配置和引擎路由能力，用户通过 config.toml 中的 provider 字段选择厂商，程序自动选择对应引擎类，切换厂商无需改代码

### Modified Capabilities

<!-- 无 -->

## Impact

- `config.toml`: 配置段重命名，字段变更（BREAKING）
- `config.py`: 去掉 DeepSeek 专用常量，新增引擎查表映射和字段路由
- `services.py`: `build_settings` 改为动态引擎选择 + 字段映射
- `config.example.toml`: 重写为多厂商模板
- `README.md`: 更新配置章节
- `tests/test_services.py`: 更新/新增测试
