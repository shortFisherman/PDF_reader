# Comet Design Handoff

- Change: multi-model-provider
- Phase: design
- Mode: compact
- Context hash: 3af97402182088ef7b90dc588bd3cf41f4075afb9409dd98253f1d093b5e336e

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/multi-model-provider/proposal.md

- Source: openspec/changes/multi-model-provider/proposal.md
- Lines: 1-30
- SHA256: e13e10b3b183c08be3a02d82d3a34f9928f9fd71cd6f5c342856c398e2de7c54

```md
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
```

## openspec/changes/multi-model-provider/design.md

- Source: openspec/changes/multi-model-provider/design.md
- Lines: 1-94
- SHA256: 3844f837ac7ccb2a02881bd5b0763cbbfbc971171664417edd1ff3a0b9f66c9e

[TRUNCATED]

```md
## Context

当前 `services.py:build_settings` 硬编码 `DeepSeekSettings`，配置被绑定在 `[deepseek]` 段。pdf2zh-next 的 `translate_engine_model.py` 已内置 20+ 种翻译引擎，其中 `OpenAICompatibleSettings` 可作为通用兜底，其余专用引擎（DeepSeekSettings、ZhipuSettings 等）提供各自特有功能。

## Goals / Non-Goals

**Goals:**
- 用户在 config.toml 中选 provider，程序自动路由到正确的引擎类
- 专用引擎优先，通用引擎兜底
- 配置文件用统一字段名，内部自动映射到各引擎的不同字段名
- 高级选项（thinking_mode 等）可配置，不支持的引擎自动忽略

**Non-Goals:**
- 不做界面内切换
- 不做多引擎并发
- 不新增 pdf2zh-next 不支持的引擎类

## Decisions

### 1. 配置结构：单一 `[model]` 段 + 统一字段名

```toml
[model]
provider = "deepseek"
api_key = "sk-xxx"
model = "deepseek-v4-flash"
base_url = "https://api.deepseek.com/v1"
# 可选高级参数
thinking_mode = "enabled"
reasoning_effort = "high"
enable_json_mode = false
temperature = "0.7"
timeout = "500"
```

理由：用户只需学一套字段名，切换厂商改 provider/api_key/model/base_url 四个值即可。`config.py` 负责把统一字段映射到各引擎类的实际字段名（如 `thinking_mode` → `deepseek_thinking_mode`）。

### 2. 引擎路由：查表法

```python
PROVIDER_MAP = {
    "deepseek":           DeepSeekSettings,
    "zhipu":              ZhipuSettings,
    "siliconflow":        SiliconFlowSettings,
    "aliyun":             AliyunDashScopeSettings,
    "gemini":             GeminiSettings,
    "groq":               GroqSettings,
    "grok":               GrokSettings,
    "modelscope":         ModelScopeSettings,
    "openai":             OpenAISettings,
    "openai_compatible":  OpenAICompatibleSettings,
}
```

查不到 → 走 `OpenAICompatibleSettings` 兜底。

### 3. 字段映射表：统一配置名 → 引擎字段名

```python
FIELD_MAP = {
    "thinking_mode":     "deepseek_thinking_mode",    # 仅 DeepSeekSettings 有此字段
    "reasoning_effort":  "deepseek_reasoning_effort", # 仅 DeepSeekSettings
    "enable_json_mode":  {
        "DeepSeekSettings":     "deepseek_enable_json_mode",
        "ZhipuSettings":        "zhipu_enable_json_mode",
        "SiliconFlowSettings":  "siliconflow_enable_json_mode",
        ...
    },
    ...
}
```

`build_settings` 中：根据选中的引擎类，只设置该类有定义的字段，不存在的字段静默跳过。

### 4. 引擎实例化：动态构造 kwargs

```python
def build_settings(single_page_pdf, user_prompt=None, output_dir=None):
    engine_cls = resolve_engine(config.MODEL_PROVIDER)
    engine_kwargs = build_engine_kwargs(engine_cls, config)
```

Full source: openspec/changes/multi-model-provider/design.md

## openspec/changes/multi-model-provider/tasks.md

- Source: openspec/changes/multi-model-provider/tasks.md
- Lines: 1-19
- SHA256: d4d1bf4df9f83d3f3872752f473b320c04e74e5d6c56c1c0dca97c704ac3c28c

```md
## 1. 配置层重构

- [ ] 1.1 重写 `config.toml`：`[deepseek]` → `[model]`，字段改为 `provider` / `api_key` / `model` / `base_url` + 可选高级选项
- [ ] 1.2 重写 `config.py`：去掉 DeepSeek 专用常量，新增 `MODEL_PROVIDER` / `MODEL_API_KEY` / `MODEL` / `MODEL_BASE_URL` 等统一配置项，以及 `PROVIDER_MAP` 引擎路由表和 `FIELD_MAP` 字段映射表

## 2. 引擎路由实现

- [ ] 2.1 重写 `services.py` 中 `build_settings`：根据 provider 动态选择引擎类，通过字段映射表将统一配置字段映射到引擎实例化参数，不存在的字段静默跳过
- [ ] 2.2 确保 `DEEPSEEK_API_KEY` 环境变量兼容性：新增 `MODEL_API_KEY` 环境变量覆盖，同时保留 `DEEPSEEK_API_KEY` 作为 fallback

## 3. 文档与模板

- [ ] 3.1 重写 `config.example.toml`：列出所有支持 provider 的可选值和示例，标注每个高级参数的支持范围（哪些引擎可用）
- [ ] 3.2 更新 `README.md` 配置章节：说明多 provider 切换方式，标注 `[deepseek]` → `[model]` 迁移步骤

## 4. 测试

- [ ] 4.1 更新 `tests/test_services.py` 现有测试适配新配置结构
- [ ] 4.2 新增测试：DeepSeek 引擎（含 thinking_mode）、OpenAICompatible 引擎、未知 provider 默认兜底、不支持的字段静默忽略
```

