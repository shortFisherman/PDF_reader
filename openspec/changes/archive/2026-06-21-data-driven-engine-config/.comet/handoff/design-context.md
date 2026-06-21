# Comet Design Handoff

- Change: data-driven-engine-config
- Phase: design
- Mode: compact
- Context hash: eb890d4aca3e2eff5c8825135c344077caa04dbefd92cc815cf10033382abd2d

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/data-driven-engine-config/proposal.md

- Source: openspec/changes/data-driven-engine-config/proposal.md
- Lines: 1-30
- SHA256: 30a7bd6268dfc01ae8f055071c20cd345484e8ccb3d6952c57a8a9b7b9e063e3

```md
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
```

## openspec/changes/data-driven-engine-config/design.md

- Source: openspec/changes/data-driven-engine-config/design.md
- Lines: 1-63
- SHA256: 60052d197ea8958b5ee3226dfcedf677eedc2a5b3499e5fabed9a98c742c3683

```md
## Context

`config.py` 当前用两个顶层字典描述引擎：
- `PROVIDER_MAP: dict[str, type]`（provider key → SettingsClass）
- `FIELD_MAP: dict[str, dict[str, str]]`（unified_name → {SettingsClass_name → engine_field_name}），含 8 个子字典（api_key/model/base_url/thinking_mode/reasoning_effort/enable_json_mode/temperature/timeout）

新增引擎需在 `PROVIDER_MAP` 加 1 条 + 在 `FIELD_MAP` 的每个相关子字典加 1 条，散落 9 处。`services.build_engine_kwargs` 遍历硬编码的 8 个 unified_name，与 `FIELD_MAP` 结构强耦合。

约束：`config.toml` 的 `[model]` 字段不变，10 引擎行为字节等价，保守边界。

## Goals / Non-Goals

**Goals:**
- 每个引擎一处声明式定义（provider key、SettingsClass、字段映射）
- 新增引擎只加 1 处声明
- `build_engine_kwargs` 逻辑通用化，不再硬编码 unified_name 列表
- 10 引擎行为等价，现有测试全绿

**Non-Goals:**
- 不改 `config.toml` 字段名
- 不改运行时引擎选择行为
- 不引入插件系统或动态加载（静态注册表即可）

## Decisions

### 决策 1：注册表数据结构

**选择**：定义 `EngineSpec` dataclass + `ENGINE_REGISTRY: list[EngineSpec]`：

```python
@dataclass(frozen=True)
class EngineSpec:
    provider: str                      # "deepseek"
    settings_cls: type                  # DeepSeekSettings
    field_map: dict[str, str]           # unified_name -> engine_field_name（仅含该引擎支持的）
    # 例: {"api_key": "deepseek_api_key", "model": "deepseek_model", "thinking_mode": "deepseek_thinking_mode", ...}
```

`provider` → `EngineSpec` 的查找索引由注册表派生。每个引擎的字段映射集中在其 `EngineSpec` 内，不再分散到 8 个子字典。

**备选**：
- (a) 字典嵌套 `{"deepseek": {"cls": ..., "fields": {...}}}`——dataclass 有类型提示更安全
- (b) 装饰器注册 `@register_engine("deepseek", ...)`——动态注册增加隐式顺序，静态列表更显式

**理由**：dataclass 冻结实例 + 显式列表，类型安全、易读、新增引擎一处声明。

### 决策 2：build_engine_kwargs 通用化

**选择**：`build_engine_kwargs(spec: EngineSpec) -> dict` 遍历 `spec.field_map`，对每个 `unified_name` 从 `config` 读取 `MODEL_{unified_name.upper()}`（model 特例），值非空则写入 `engine_field`。缺失必填（api_key/model）抛错，可选字段忽略并警告。

**理由**：逻辑由 `EngineSpec.field_map` 驱动，不再硬编码 8 个字段名。

### 决策 3：10 引擎等价迁移

**选择**：从现有 `PROVIDER_MAP` + `FIELD_MAP` 机械推导每个引擎的 `EngineSpec.field_map`（只含该引擎在 FIELD_MAP 各子字典中实际出现的条目），逐引擎对照现有行为编写等价测试。

**理由**：避免行为漂移；现有 `test_services.py` 的引擎配置测试作为回归基线。

## Risks / Trade-offs

- [迁移遗漏某引擎某字段] → 逐引擎等价测试覆盖 10 引擎 × 8 字段矩阵
- [dataclass 引入轻微 import 成本] → 可忽略
- [注册表顺序影响 provider 查找] → 用 dict 索引而非列表遍历查找，顺序无关
```

## openspec/changes/data-driven-engine-config/tasks.md

- Source: openspec/changes/data-driven-engine-config/tasks.md
- Lines: 1-28
- SHA256: 3ca31e77693825f206e1b107f664d5f98824a4edf6ea63d7f77ff5016a2781a5

```md
## 1. 等价回归基线

- [ ] 1.1 在 `tests/test_engine_registry.py` 编写测试：对现有 10 引擎，断言 `resolve_engine(provider)` 与 `build_engine_kwargs` 产出与现状 `PROVIDER_MAP`+`FIELD_MAP` 完全一致（捕获当前行为为基线）
- [ ] 1.2 运行确认基线在现状代码上通过

## 2. 实现 EngineSpec 注册表

- [ ] 2.1 在 `config.py` 定义 `EngineSpec` dataclass（provider/settings_cls/field_map）与 `ENGINE_REGISTRY: list[EngineSpec]`
- [ ] 2.2 从现有 `PROVIDER_MAP`+`FIELD_MAP` 机械推导 10 个引擎的 `EngineSpec`，逐引擎对照字段映射
- [ ] 2.3 派生 `PROVIDER_INDEX: dict[str, EngineSpec]` 供快速查找
- [ ] 2.4 运行等价回归测试（步骤1.1）通过

## 3. 重构 services.build_engine_kwargs

- [ ] 3.1 重写 `services.resolve_engine`：从 `PROVIDER_INDEX` 查找，未命中回退 `OpenAICompatibleSettings`
- [ ] 3.2 重写 `services.build_engine_kwargs`：接收 `EngineSpec`，遍历 `spec.field_map` 从 config 读值构建 kwargs，必填校验与可选警告保持现状语义
- [ ] 3.3 删除 `config.py` 的 `PROVIDER_MAP` 与 `FIELD_MAP`（已被注册表取代）
- [ ] 3.4 运行 `tests/test_services.py` 与等价回归测试通过

## 4. 扩展性验证

- [ ] 4.1 在 `tests/test_engine_registry.py` 编写测试：声明一个"假引擎" `EngineSpec`（mock Settings class），仅加 1 处声明，断言 `resolve_engine("fake")` 与 `build_engine_kwargs` 正确工作
- [ ] 4.2 运行扩展性测试通过

## 5. 全量回归与 lint

- [ ] 5.1 运行 `pytest tests/ -v`，全部测试通过
- [ ] 5.2 运行 `ruff check`，零错误
```

## openspec/changes/data-driven-engine-config/specs/code-quality-foundations/spec.md

- Source: openspec/changes/data-driven-engine-config/specs/code-quality-foundations/spec.md
- Lines: 1-20
- SHA256: ce20f56a02abdf492410f15614b6d3171758969299122187377d48686456c73f

```md
## MODIFIED Requirements

### Requirement: Modular source code organization

The system SHALL be organized into separate Python modules with clear separation of concerns. Engine configuration SHALL be data-driven via a single declarative registry rather than scattered dictionaries. `config.py` SHALL expose the engine registry as the single source of truth for provider-to-settings-class and unified-field-to-engine-field mappings.

#### Scenario: Config loading is independent

- **WHEN** config.py is imported
- **THEN** it SHALL load and expose all configuration values without depending on Flask or other modules

#### Scenario: Routes are registered via app

- **WHEN** app.py creates the Flask application
- **THEN** it SHALL import and register routes from the routes module

#### Scenario: Engine mapping is data-driven

- **WHEN** the engine configuration is inspected
- **THEN** it SHALL be driven by a single registry structure, and no separate `PROVIDER_MAP` or multi-key `FIELD_MAP` dictionaries SHALL exist alongside it
```

## openspec/changes/data-driven-engine-config/specs/engine-registry/spec.md

- Source: openspec/changes/data-driven-engine-config/specs/engine-registry/spec.md
- Lines: 1-20
- SHA256: 41dc775789630b01ebc6f37c48cb47540f3e5a42404156c53f264c51c28c9790

```md
## ADDED Requirements

### Requirement: Declarative translation engine registry

The system SHALL maintain a declarative engine registry where each supported translation engine is described by a single `EngineSpec` record containing: the provider key, the pdf2zh-next Settings class, and the complete field mapping from unified config names to engine-specific field names. Adding a new engine SHALL require exactly one new `EngineSpec` declaration and no edits to scattered dictionaries.

#### Scenario: Add a new engine via single declaration

- **WHEN** a developer adds a new engine by appending one `EngineSpec` to the registry
- **THEN** the engine SHALL be selectable via `config.toml`'s `provider` field and its settings SHALL be built correctly, with no other source edits required

#### Scenario: Registry is the single source of truth

- **WHEN** the system resolves an engine class or builds engine kwargs
- **THEN** it SHALL consult only the engine registry, and no separate `PROVIDER_MAP` or multi-key `FIELD_MAP` dictionaries SHALL exist

#### Scenario: Engine field mapping is colocated

- **WHEN** inspecting an engine's supported fields (api_key, model, base_url, thinking_mode, etc.)
- **THEN** all field mappings for that engine SHALL be found in its single `EngineSpec.field_map`, not spread across multiple top-level dictionaries
```

## openspec/changes/data-driven-engine-config/specs/page-translation/spec.md

- Source: openspec/changes/data-driven-engine-config/specs/page-translation/spec.md
- Lines: 1-25
- SHA256: d321b6047ef9b0c836a2df83c93df9cce483503d24114e65a5a16c16e01ddd35

```md
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
```

