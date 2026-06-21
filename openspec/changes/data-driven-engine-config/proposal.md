## Why

`config.py:40-113` 用 `PROVIDER_MAP` + `FIELD_MAP`（含 `api_key`/`model`/`base_url`/`thinking_mode`/`reasoning_effort`/`enable_json_mode`/`temperature`/`timeout` 共 8 个子字典）描述 10 个引擎的字段映射。新增一个引擎需在 ~10 个字典里各加条目，极易遗漏且难以发现。这是扩展性最差的部分。

## What Changes

- 用数据驱动的引擎注册表替代分散的多字典：每个引擎用一个声明式结构（dataclass 或TypedDict）描述其 `provider key`、`SettingsClass`、以及支持的字段名映射，集中在一处
- 新增引擎只需在注册表加一条声明，无需改动多处字典
- `services.build_engine_kwargs` 改为遍历注册表声明构建 kwargs，逻辑统一
- `config.toml` 的 `[model]` 字段（provider/api_key/model/base_url 等）保持不变，用户无感
- 现有 10 引擎行为保持一致，现有测试全绿，新增"假引擎"注册测试验证扩展性

## Capabilities

### New Capabilities

- `engine-registry`: 翻译引擎注册表——以声明式数据结构集中描述所有支持的引擎及其字段映射，新增引擎只需一处声明

### Modified Capabilities

- `page-translation`: "翻译使用 pdf2zh-next"需求的引擎配置部分——引擎解析 SHALL 通过注册表完成，而非散落的多字典；行为对外不变
- `code-quality-foundations`: "模块化源码组织"需求——配置加载与引擎映射 SHALL 数据驱动，单一来源

## Impact

- **代码**：`config.py`（删除 `PROVIDER_MAP`/`FIELD_MAP` 多字典，新增 `ENGINE_REGISTRY`）、`services.py`（`resolve_engine`/`build_engine_kwargs` 改用注册表）
- **配置**：`config.toml` 的 `[model]` 字段不变
- **API**：无影响
- **测试**：现有引擎配置测试保持通过；新增注册表测试（含假引擎声明即生效）
- **风险**：迁移需保证 10 引擎字段映射完全等价，需逐引擎对照回归
