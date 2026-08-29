import ipaddress
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

from pdf_reader import paths

CONFIG_PATH = paths.get_config_path()


class ConfigError(ValueError):
    """配置或启动参数错误。消息只包含可安全展示的内容，绝不包含 API Key。"""


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5000


def is_loopback_host(host: str) -> bool:
    """host 是否为明确 loopback（localhost、127/8、::1）。"""
    if not isinstance(host, str):
        return False
    normalized = host.strip().lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True)
class ServerConfig:
    """启动服务器所需的运行时配置（host/port/debug 的唯一最终来源）。"""

    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    debug: bool = False

    @property
    def use_reloader(self) -> bool:
        """reloader 语义：debug 开启时启用，关闭时显式关闭（不依赖 Flask 隐式默认）。"""
        return self.debug


_DEBUG_TRUE_VALUES = frozenset({"true", "1", "on", "yes"})
_DEBUG_FALSE_VALUES = frozenset({"false", "0", "off", "no"})


def parse_debug_env(value: str | None) -> bool | None:
    """解析 PDF_READER_DEBUG；未设置返回 None，非法值抛 ConfigError。"""
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in _DEBUG_TRUE_VALUES:
        return True
    if normalized in _DEBUG_FALSE_VALUES:
        return False
    raise ConfigError(
        f"环境变量 PDF_READER_DEBUG 非法值 {normalized!r}："
        "只接受 true/false/1/0/on/off/yes/no（不区分大小写，忽略首尾空白）"
    )


def _load_config(config_path: Path) -> dict:
    """读取 TOML 配置；文件缺失返回空映射，语法错误抛 ConfigError。"""
    try:
        with open(config_path, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"TOML 语法错误（{config_path}）：{exc}") from exc


try:
    CONFIG = _load_config(CONFIG_PATH)
    _CONFIG_LOAD_ERROR = None
except ConfigError as exc:
    CONFIG = {}
    _CONFIG_LOAD_ERROR = str(exc)


def _section(config_data: dict, name: str) -> dict:
    """安全提取 TOML section：非 table 时返回空映射，导入期不崩溃。"""
    section = config_data.get(name, {})
    return section if isinstance(section, dict) else {}


def _string(value: object, default: str = "") -> str:
    """安全字符串：非 str 时返回默认值，导入期不崩溃。"""
    return value if isinstance(value, str) else default


model_cfg = _section(CONFIG, "model")
MODEL_PROVIDER = _string(model_cfg.get("provider"), "openai_compatible")
_raw_api_key = os.environ.get("MODEL_API_KEY", model_cfg.get("api_key", ""))
MODEL_API_KEY = _raw_api_key.strip() if isinstance(_raw_api_key, str) else ""
MODEL = _string(model_cfg.get("model"), "")
MODEL_BASE_URL = _string(model_cfg.get("base_url")) or None

MODEL_THINKING_MODE = model_cfg.get("thinking_mode")
MODEL_REASONING_EFFORT = model_cfg.get("reasoning_effort")
MODEL_ENABLE_JSON_MODE = model_cfg.get("enable_json_mode")
MODEL_TEMPERATURE = model_cfg.get("temperature")
MODEL_TIMEOUT = model_cfg.get("timeout")


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
            "enable_json_mode": "aliyun_dashscope_enable_json_mode",
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


PROVIDER_INDEX: dict[str, EngineSpec] = {spec.provider: spec for spec in ENGINE_REGISTRY}

pdf_reader_cfg = _section(CONFIG, "pdf_reader")
DPI = pdf_reader_cfg.get("dpi", 200)
CACHE_DIR = paths.resolve_cache_dir(_string(pdf_reader_cfg.get("cache_dir"), "cache"))
GLOSSARY_PATH = paths.get_glossary_path()
translation_cfg = _section(CONFIG, "translation")
TRANSLATION_LANG_IN = _string(translation_cfg.get("lang_in"), "en")
TRANSLATION_LANG_OUT = _string(translation_cfg.get("lang_out"), "zh")


def _validate_required_config() -> None:
    if not isinstance(MODEL, str) or not MODEL:
        raise ConfigError("请设置 model.model")
    if not isinstance(MODEL_API_KEY, str) or not MODEL_API_KEY or MODEL_API_KEY.startswith("sk-your-api-key"):
        raise ConfigError("请设置 model.api_key 或环境变量 MODEL_API_KEY")


def _require_table(config_data: dict, name: str) -> dict:
    section = config_data.get(name, {})
    if not isinstance(section, dict):
        raise ConfigError(f"[{name}] 必须是 TOML table")
    return section


def _validate_model_section(section: dict) -> None:
    provider = section.get("provider", "openai_compatible")
    if not isinstance(provider, str) or not provider.strip():
        raise ConfigError("[model].provider 必须是非空字符串")

    model_name = section.get("model", "")
    if not isinstance(model_name, str) or not model_name.strip():
        raise ConfigError("[model].model 必须是非空字符串")

    base_url = section.get("base_url")
    if base_url is not None and (not isinstance(base_url, str) or not base_url.strip()):
        raise ConfigError("[model].base_url 若设置必须是非空字符串")

    env_key = os.environ.get("MODEL_API_KEY")
    if env_key is not None:
        key = env_key
    else:
        file_key = section.get("api_key", "")
        key = file_key if isinstance(file_key, str) else ""
    if not isinstance(key, str) or not key.strip():
        raise ConfigError("请设置 model.api_key 或环境变量 MODEL_API_KEY")
    if key.strip().startswith("sk-your-api-key"):
        raise ConfigError("请设置 model.api_key 或环境变量 MODEL_API_KEY（当前为示例占位值）")


def _validate_pdf_reader_section(section: dict) -> None:
    dpi = section.get("dpi", 200)
    if isinstance(dpi, bool) or not isinstance(dpi, int) or dpi <= 0:
        raise ConfigError("[pdf_reader].dpi 必须是正整数（布尔值不算）")
    cache_dir = section.get("cache_dir", "cache")
    if not isinstance(cache_dir, str) or not cache_dir.strip():
        raise ConfigError("[pdf_reader].cache_dir 必须是非空字符串")


def _validate_translation_section(section: dict) -> None:
    for key in ("lang_in", "lang_out"):
        value = section.get(key, "en" if key == "lang_in" else "zh")
        if not isinstance(value, str) or not value.strip():
            raise ConfigError(f"[translation].{key} 必须是非空字符串")


def validate_startup_requirements(config_data: dict | None = None) -> None:
    """启动服务器前的统一配置校验（[server] 由 resolve_server_config 校验）。

    直接消费的 section 必须为 table，核心字段类型/非空要求清晰；
    任何错误抛 ConfigError，由 main 以退出码 2 结束。
    """
    data = CONFIG if config_data is None else config_data
    if config_data is None and _CONFIG_LOAD_ERROR is not None:
        raise ConfigError(_CONFIG_LOAD_ERROR)
    model_section = _require_table(data, "model")
    pdf_reader_section = _require_table(data, "pdf_reader")
    translation_section = _require_table(data, "translation")
    _validate_model_section(model_section)
    _validate_pdf_reader_section(pdf_reader_section)
    _validate_translation_section(translation_section)


def _resolve_file_debug(config_data: dict) -> bool:
    """仅从 [server].debug 读取文件级默认值；CLI/env 覆盖由 resolve_server_config 处理。"""
    server = config_data.get("server")
    if isinstance(server, dict):
        value = server.get("debug", False)
        if isinstance(value, bool):
            return value
    return False


def resolve_server_config(config_data: dict | None = None, cli_debug: bool | None = None) -> ServerConfig:
    """按 CLI > PDF_READER_DEBUG > [server].debug > false 解析最终运行配置并严格校验。"""
    if config_data is None and _CONFIG_LOAD_ERROR is not None:
        raise ConfigError(_CONFIG_LOAD_ERROR)
    data = CONFIG if config_data is None else config_data

    server = data.get("server", {})
    if not isinstance(server, dict):
        raise ConfigError("[server] 必须是 TOML table（配置项应写在 [server] 段内）")

    host = server.get("host", DEFAULT_HOST)
    if not isinstance(host, str) or not host.strip():
        raise ConfigError('[server].host 必须是非空字符串，例如 "127.0.0.1"')

    port = server.get("port", DEFAULT_PORT)
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ConfigError("[server].port 必须是 1 到 65535 之间的整数，布尔值或字符串均不接受")

    file_debug = server.get("debug", False)
    if not isinstance(file_debug, bool):
        raise ConfigError("[server].debug 必须是布尔值 true 或 false，不接受字符串或数字")

    env_debug = parse_debug_env(os.environ.get("PDF_READER_DEBUG"))
    debug = file_debug
    if env_debug is not None:
        debug = env_debug
    if cli_debug is not None:
        debug = cli_debug

    return ServerConfig(host=host.strip(), port=port, debug=debug)


DEBUG: bool = _resolve_file_debug(CONFIG)
