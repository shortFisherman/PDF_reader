import os
import tomllib
from pathlib import Path

from pdf2zh_next.config.translate_engine_model import (
    AliyunDashScopeSettings,
    DeepSeekSettings,
    GeminiSettings,
    GrokSettings,
    GroqSettings,
    ModelScopeSettings,
    OpenAICompatibleSettings,
    OpenAISettings,
    SiliconFlowSettings,
    ZhipuSettings,
)

CONFIG_PATH = Path(__file__).parent / "config.toml"
with open(CONFIG_PATH, "rb") as f:
    CONFIG = tomllib.load(f)

model_cfg = CONFIG["model"]
MODEL_PROVIDER = model_cfg["provider"]
_raw_api_key = os.environ.get("MODEL_API_KEY", model_cfg.get("api_key", ""))
MODEL_API_KEY = (_raw_api_key or "").strip()
MODEL = model_cfg["model"]
MODEL_BASE_URL = model_cfg.get("base_url") or None

MODEL_THINKING_MODE = model_cfg.get("thinking_mode")
MODEL_REASONING_EFFORT = model_cfg.get("reasoning_effort")
MODEL_ENABLE_JSON_MODE = model_cfg.get("enable_json_mode")
MODEL_TEMPERATURE = model_cfg.get("temperature")
MODEL_TIMEOUT = model_cfg.get("timeout")

if not MODEL_API_KEY or MODEL_API_KEY.startswith("sk-your-api-key"):
    raise ValueError("请设置 model.api_key 或环境变量 MODEL_API_KEY")
if not MODEL:
    raise ValueError("请设置 model.model")

PROVIDER_MAP: dict[str, type] = {
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

DPI = CONFIG["pdf_reader"]["dpi"]
CACHE_DIR = Path(CONFIG["pdf_reader"]["cache_dir"]).resolve()
GLOSSARY_PATH = Path(__file__).parent / "docs" / "glossary.csv"
TRANSLATION_LANG_IN = CONFIG["translation"]["lang_in"]
TRANSLATION_LANG_OUT = CONFIG["translation"]["lang_out"]
