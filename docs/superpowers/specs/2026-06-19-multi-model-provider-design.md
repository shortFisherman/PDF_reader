---
comet_change: multi-model-provider
role: technical-design
canonical_spec: openspec
---

# 多模型供应商支持 — 技术设计

## 概述

当前 `services.py:build_settings` 硬编码 `DeepSeekSettings`，无法切换模型供应商。本设计将翻译引擎选择从代码中解耦到配置文件，支持 pdf2zh-next 内置的 10 种专用引擎 + OpenAI 通用兼容接口。

## 架构

```
config.toml ──→ config.py ──→ services.py ──→ pdf2zh-next
[model]         MODEL_PROVIDER  build_settings()  动态选择:
 provider ────→ PROVIDER_MAP ──→ engine_cls        DeepSeekSettings / ZhipuSettings / ...
 api_key   ────→ FIELD_MAP ───→ engine_kwargs      OpenAICompatibleSettings (兜底)
 model
 base_url        ───→ 默认兜底
 ...options
```

## 配置文件结构

### config.toml

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

### 支持的 provider

| provider | 引擎类 | 特有功能 |
|----------|--------|----------|
| `deepseek` | DeepSeekSettings | thinking_mode / reasoning_effort |
| `zhipu` | ZhipuSettings | enable_json_mode |
| `siliconflow` | SiliconFlowSettings | enable_thinking / enable_json_mode |
| `aliyun` | AliyunDashScopeSettings | temperature / timeout / enable_json_mode |
| `gemini` | GeminiSettings | enable_json_mode |
| `groq` | GroqSettings | enable_json_mode |
| `grok` | GrokSettings | enable_json_mode |
| `modelscope` | ModelScopeSettings | enable_json_mode |
| `openai` | OpenAISettings | temperature / timeout / reasoning_effort / enable_json_mode |
| `openai_compatible` | OpenAICompatibleSettings | temperature / timeout / reasoning_effort / enable_json_mode |

未匹配的 provider 名自动走 `OpenAICompatibleSettings` 兜底（info 日志提示）。

## 引擎路由

### PROVIDER_MAP（config.py）

```python
from pdf2zh_next.config.translate_engine_model import (
    DeepSeekSettings, ZhipuSettings, SiliconFlowSettings,
    AliyunDashScopeSettings, GeminiSettings, GroqSettings,
    GrokSettings, ModelScopeSettings, OpenAISettings,
    OpenAICompatibleSettings,
)

PROVIDER_MAP: dict[str, type[BaseModel]] = {
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

### 路由逻辑（services.py）

```python
def resolve_engine(provider: str) -> type[BaseModel]:
    engine_cls = PROVIDER_MAP.get(provider)
    if engine_cls is None:
        logging.info("Provider '%s' not found, falling back to OpenAI Compatible", provider)
        return OpenAICompatibleSettings
    logging.info("Using engine: %s (%s)", engine_cls.__name__, config.MODEL)
    return engine_cls
```

## 字段映射

### 设计原则

- 统一配置字段名（小写）→ 引擎实际字段名（引擎前缀 + 功能名）
- 通过白名单映射表查询，引擎不存在的字段不传入（静默跳过，warning 日志提示）
- 必填字段缺失时报错

### 字段映射表（config.py）

```python
FIELD_MAP: dict[str, dict[str, str]] = {
    "api_key": {
        "DeepSeekSettings":    "deepseek_api_key",
        "ZhipuSettings":       "zhipu_api_key",
        "SiliconFlowSettings": "siliconflow_api_key",
        "AliyunDashScopeSettings": "aliyun_dashscope_api_key",
        "GeminiSettings":      "gemini_api_key",
        "GroqSettings":        "groq_api_key",
        "GrokSettings":        "grok_api_key",
        "ModelScopeSettings":  "modelscope_api_key",
        "OpenAISettings":      "openai_api_key",
        "OpenAICompatibleSettings": "openai_compatible_api_key",
    },
    "model": {
        "DeepSeekSettings":    "deepseek_model",
        "ZhipuSettings":       "zhipu_model",
        "SiliconFlowSettings": "siliconflow_model",
        "AliyunDashScopeSettings": "aliyun_dashscope_model",
        "GeminiSettings":      "gemini_model",
        "GroqSettings":        "groq_model",
        "GrokSettings":        "grok_model",
        "ModelScopeSettings":  "modelscope_model",
        "OpenAISettings":      "openai_model",
        "OpenAICompatibleSettings": "openai_compatible_model",
    },
    "base_url": {
        "SiliconFlowSettings": "siliconflow_base_url",
        "AliyunDashScopeSettings": "aliyun_dashscope_base_url",
        "OpenAISettings":      "openai_base_url",
        "OpenAICompatibleSettings": "openai_compatible_base_url",
    },
    "thinking_mode": {
        "DeepSeekSettings": "deepseek_thinking_mode",
    },
    "reasoning_effort": {
        "DeepSeekSettings": "deepseek_reasoning_effort",
        "OpenAISettings":   "openai_reasoning_effort",
        "OpenAICompatibleSettings": "openai_compatible_reasoning_effort",
    },
    "enable_json_mode": {
        "DeepSeekSettings":    "deepseek_enable_json_mode",
        "ZhipuSettings":       "zhipu_enable_json_mode",
        "SiliconFlowSettings": "siliconflow_enable_json_mode",
        "GeminiSettings":      "gemini_enable_json_mode",
        "GroqSettings":        "groq_enable_json_mode",
        "GrokSettings":        "grok_enable_json_mode",
        "ModelScopeSettings":  "modelscope_enable_json_mode",
        "OpenAISettings":      "openai_enable_json_mode",
        "OpenAICompatibleSettings": "openai_compatible_enable_json_mode",
    },
    "temperature": {
        "OpenAISettings":      "openai_temperature",
        "AliyunDashScopeSettings": "aliyun_dashscope_temperature",
        "OpenAICompatibleSettings": "openai_compatible_temperature",
    },
    "timeout": {
        "OpenAISettings":      "openai_timeout",
        "AliyunDashScopeSettings": "aliyun_dashscope_timeout",
        "OpenAICompatibleSettings": "openai_compatible_timeout",
    },
}
```

### build_engine_kwargs（services.py）

```python
def build_engine_kwargs(engine_cls: type[BaseModel]) -> dict:
    engine_fields = engine_cls.model_fields
    engine_name = engine_cls.__name__
    kwargs = {}

    for unified_name in ("api_key", "model", "base_url", "thinking_mode",
                         "reasoning_effort", "enable_json_mode",
                         "temperature", "timeout"):
        engine_field = FIELD_MAP.get(unified_name, {}).get(engine_name)
        if engine_field is None:
            continue
        if engine_field not in engine_fields:
            continue

        value = getattr(config, f"MODEL_{unified_name.upper()}", None)

        if value is not None:
            kwargs[engine_field] = value
        elif unified_name in ("api_key", "model"):
            raise ConfigError(f"model.{unified_name} 未配置")
        elif unified_name == "base_url":
            pass  # 引擎内置默认值
        else:
            logging.warning("当前引擎不支持 %s，已忽略", unified_name)

    return kwargs
```

## 配置读取（config.py）

```python
CONFIG_PATH = Path(__file__).parent / "config.toml"
with open(CONFIG_PATH, "rb") as f:
    CONFIG = tomllib.load(f)

model_cfg = CONFIG["model"]
MODEL_PROVIDER = model_cfg["provider"]
MODEL_API_KEY = os.environ.get("MODEL_API_KEY", model_cfg["api_key"])
MODEL = model_cfg["model"]
MODEL_BASE_URL = model_cfg.get("base_url", "")

MODEL_THINKING_MODE = model_cfg.get("thinking_mode")
MODEL_REASONING_EFFORT = model_cfg.get("reasoning_effort")
MODEL_ENABLE_JSON_MODE = model_cfg.get("enable_json_mode")
MODEL_TEMPERATURE = model_cfg.get("temperature")
MODEL_TIMEOUT = model_cfg.get("timeout")

if not MODEL_API_KEY or MODEL_API_KEY.startswith("sk-your-api-key"):
    raise ValueError("请设置 model.api_key 或环境变量 MODEL_API_KEY")
if not MODEL:
    raise ValueError("请设置 model.model")
```

## build_settings 改造（services.py）

```python
def build_settings(single_page_pdf, user_prompt=None, output_dir=None):
    engine_cls = resolve_engine(config.MODEL_PROVIDER)
    engine_kwargs = build_engine_kwargs(engine_cls)

    return SettingsModel(
        translation=Pdf2zhTranslationSettings(...),
        pdf=Pdf2zhPDFSettings(...),
        translate_engine_settings=engine_cls(**engine_kwargs),
    )
```

## 错误处理与日志

| 情况 | 处理 |
|------|------|
| provider 不在 PROVIDER_MAP | 走 OpenAICompatibleSettings，info 日志 |
| base_url 为空且引擎不支持自定义 | 引擎内置默认值 |
| 高级字段引擎不支持 | warning 日志提示已忽略 |
| api_key / model 缺失 | 启动时 raise ValueError |
| 旧 `[deepseek]` 配置段 | TOML 解析失败，提示用户迁移 |
| 旧 `DEEPSEEK_API_KEY` 环境变量 | 不兼容，提示用 `MODEL_API_KEY` |

## 测试策略

1. 更新 `test_build_settings_basic` / `test_build_settings_with_prompt` 等适配新配置结构
2. 新增 `test_build_settings_deepseek_with_thinking` — 验证 thinking_mode 正确传入 DeepSeekSettings
3. 新增 `test_build_settings_unknown_provider` — 验证未知 provider 走 OpenAICompatibleSettings 兜底
4. 新增 `test_build_settings_unsupported_field_ignored` — 验证不支持的字段不被传入引擎
5. 新增 `test_build_settings_missing_api_key` — 验证缺少 api_key 时报错
