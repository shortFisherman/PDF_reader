import os
import tomllib
from dataclasses import dataclass
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
try:
    with open(CONFIG_PATH, "rb") as f:
        CONFIG = tomllib.load(f)
except FileNotFoundError:
    CONFIG = {}

model_cfg = CONFIG.get("model", {})
MODEL_PROVIDER = model_cfg.get("provider", "openai_compatible")
_raw_api_key = os.environ.get("MODEL_API_KEY", model_cfg.get("api_key", ""))
MODEL_API_KEY = (_raw_api_key or "").strip()
MODEL = model_cfg.get("model", "")
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

@dataclass(frozen=True)
class EngineSpec:
    provider: str
    settings_cls: type
    field_map: dict[str, str]
    required_fields: tuple[str, ...]


ENGINE_REGISTRY: list[EngineSpec] = [
    EngineSpec(
        provider="deepseek",
        settings_cls=DeepSeekSettings,
        field_map={
            "api_key": "deepseek_api_key",
            "model": "deepseek_model",
            "thinking_mode": "deepseek_thinking_mode",
            "reasoning_effort": "deepseek_reasoning_effort",
            "enable_json_mode": "deepseek_enable_json_mode",
        },
        required_fields=("api_key", "model"),
    ),
    EngineSpec(
        provider="zhipu",
        settings_cls=ZhipuSettings,
        field_map={
            "api_key": "zhipu_api_key",
            "model": "zhipu_model",
            "enable_json_mode": "zhipu_enable_json_mode",
        },
        required_fields=("api_key", "model"),
    ),
    EngineSpec(
        provider="siliconflow",
        settings_cls=SiliconFlowSettings,
        field_map={
            "api_key": "siliconflow_api_key",
            "model": "siliconflow_model",
            "base_url": "siliconflow_base_url",
            "enable_json_mode": "siliconflow_enable_json_mode",
        },
        required_fields=("api_key", "model"),
    ),
    EngineSpec(
        provider="aliyun",
        settings_cls=AliyunDashScopeSettings,
        field_map={
            "api_key": "aliyun_dashscope_api_key",
            "model": "aliyun_dashscope_model",
            "base_url": "aliyun_dashscope_base_url",
            "temperature": "aliyun_dashscope_temperature",
            "timeout": "aliyun_dashscope_timeout",
        },
        required_fields=("api_key", "model"),
    ),
    EngineSpec(
        provider="gemini",
        settings_cls=GeminiSettings,
        field_map={
            "api_key": "gemini_api_key",
            "model": "gemini_model",
            "enable_json_mode": "gemini_enable_json_mode",
        },
        required_fields=("api_key", "model"),
    ),
    EngineSpec(
        provider="groq",
        settings_cls=GroqSettings,
        field_map={
            "api_key": "groq_api_key",
            "model": "groq_model",
            "enable_json_mode": "groq_enable_json_mode",
        },
        required_fields=("api_key", "model"),
    ),
    EngineSpec(
        provider="grok",
        settings_cls=GrokSettings,
        field_map={
            "api_key": "grok_api_key",
            "model": "grok_model",
            "enable_json_mode": "grok_enable_json_mode",
        },
        required_fields=("api_key", "model"),
    ),
    EngineSpec(
        provider="modelscope",
        settings_cls=ModelScopeSettings,
        field_map={
            "api_key": "modelscope_api_key",
            "model": "modelscope_model",
            "enable_json_mode": "modelscope_enable_json_mode",
        },
        required_fields=("api_key", "model"),
    ),
    EngineSpec(
        provider="openai",
        settings_cls=OpenAISettings,
        field_map={
            "api_key": "openai_api_key",
            "model": "openai_model",
            "base_url": "openai_base_url",
            "reasoning_effort": "openai_reasoning_effort",
            "enable_json_mode": "openai_enable_json_mode",
            "temperature": "openai_temperature",
            "timeout": "openai_timeout",
        },
        required_fields=("api_key", "model"),
    ),
    # openai_compatible entry MUST remain — it serves as the fallback in resolve_engine
    EngineSpec(
        provider="openai_compatible",
        settings_cls=OpenAICompatibleSettings,
        field_map={
            "api_key": "openai_compatible_api_key",
            "model": "openai_compatible_model",
            "base_url": "openai_compatible_base_url",
            "reasoning_effort": "openai_compatible_reasoning_effort",
            "enable_json_mode": "openai_compatible_enable_json_mode",
            "temperature": "openai_compatible_temperature",
            "timeout": "openai_compatible_timeout",
        },
        required_fields=("api_key", "model"),
    ),
]


PROVIDER_INDEX: dict[str, EngineSpec] = {
    spec.provider: spec for spec in ENGINE_REGISTRY
}

DPI = CONFIG.get("pdf_reader", {}).get("dpi", 200)
CACHE_DIR = Path(CONFIG.get("pdf_reader", {}).get("cache_dir", "cache")).resolve()
GLOSSARY_PATH = Path(__file__).parent / "docs" / "glossary.csv"
TRANSLATION_LANG_IN = CONFIG.get("translation", {}).get("lang_in", "en")
TRANSLATION_LANG_OUT = CONFIG.get("translation", {}).get("lang_out", "zh")

def _resolve_debug() -> bool:
    debug_section = CONFIG.get("debug")
    if isinstance(debug_section, dict) and "enabled" in debug_section:
        return bool(debug_section["enabled"])
    server_section = CONFIG.get("server", {})
    return bool(server_section.get("debug", False))

DEBUG: bool = _resolve_debug()
