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

    return SettingsModel(
        translation=...,
        pdf=...,
        translate_engine_settings=engine_cls(**engine_kwargs),
    )
```

`build_engine_kwargs` 遍历统一配置字段，通过字段映射表找到引擎类中的实际字段名，只填入引擎类存在的字段。

## Risks / Trade-offs

- **[风险] 用户填了引擎不支持的字段 → 静默忽略**：可能让用户困惑「为什么我设置了这个没用」。缓解：config.example.toml 中明确标注每个可选参数的支持范围
- **[风险] 配置段重命名是 BREAKING CHANGE**：现有用户的 `[deepseek]` 段需手动改为 `[model]`。缓解：README 更新中说明迁移步骤
