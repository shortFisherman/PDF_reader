import ipaddress
import logging
import math
import os
import re
import tomllib
from dataclasses import dataclass, field
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

logger = logging.getLogger("pdf_reader.config")

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


@dataclass(frozen=True)
class ModelRuntimeConfig:
    """冻结的模型请求配置（API Key 永不进入 repr/日志/异常）。"""

    provider: str
    api_key: str = field(repr=False)
    model: str
    base_url: str | None = None
    thinking_mode: str | None = None
    reasoning_effort: str | None = None
    send_reasoning_effort: bool = False
    enable_json_mode: bool | None = None
    temperature: str | None = None
    send_temperature: bool = False
    timeout: str | None = None


@dataclass(frozen=True)
class TranslationRuntimeConfig:
    """冻结的翻译任务配置。"""

    lang_in: str
    lang_out: str
    min_text_length: int = 5
    qps: int = 4
    pool_max_workers: int | None = None
    term_qps: int | None = None
    term_pool_max_workers: int | None = None
    auto_extract_glossary: bool = True
    primary_font_family: str | None = None
    default_system_prompt: str | None = None


@dataclass(frozen=True)
class Pdf2zhRuntimeConfig:
    """冻结的 PDF 高级处理配置（设计文档阶段 3 已批准字段）。"""

    split_short_lines: bool = False
    short_line_split_factor: float = 0.8
    skip_clean: bool = False
    disable_rich_text_translate: bool = False
    enhance_compatibility: bool = False
    translate_table_text: bool = True
    skip_scanned_detection: bool = False
    ocr_workaround: bool = False
    auto_enable_ocr_workaround: bool = False
    no_merge_alternating_line_numbers: bool = False
    skip_formula_offset_calculation: bool = False
    non_formula_line_iou_threshold: float = 0.9
    figure_table_protection_threshold: float = 0.9
    formula_font_pattern: str | None = None
    formula_char_pattern: str | None = None


@dataclass(frozen=True)
class UpstreamRuntimeConfig:
    """传递给 ``translation_settings.build_settings`` 的冻结上游配置。"""

    model: ModelRuntimeConfig
    translation: TranslationRuntimeConfig
    pdf: Pdf2zhRuntimeConfig


@dataclass(frozen=True)
class AppSettings:
    """``create_app`` 的显式、不可变应用设置（P3-02）。

    只包含 ``create_app``/路由直接消费的关键运行值；翻译引擎的其余配置仍由
    ``translation_settings.build_settings`` 从配置模块读取，避免过度重构。
    """

    debug: bool
    cache_dir: Path
    dpi: int
    glossary_path: Path
    model_provider: str
    model: str
    lang_in: str
    lang_out: str
    upstream: UpstreamRuntimeConfig


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
            "send_temperature": "aliyun_dashscope_send_temperature",
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
            "send_reasoning_effort": "openai_send_reasoning_effort",
            "enable_json_mode": "openai_enable_json_mode",
            "temperature": "openai_temperature",
            "send_temperature": "openai_send_temprature",
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
            "send_reasoning_effort": "openai_compatible_send_reasoning_effort",
            "enable_json_mode": "openai_compatible_enable_json_mode",
            "temperature": "openai_compatible_temperature",
            "send_temperature": "openai_compatible_send_temperature",
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


_KNOWN_SECTION_KEYS: dict[str, frozenset[str]] = {
    "pdf_reader": frozenset({"dpi", "cache_dir"}),
    "model": frozenset(
        {
            "provider",
            "api_key",
            "model",
            "base_url",
            "thinking_mode",
            "reasoning_effort",
            "send_reasoning_effort",
            "enable_json_mode",
            "temperature",
            "send_temperature",
            "timeout",
        }
    ),
    "translation": frozenset(
        {
            "lang_in",
            "lang_out",
            "min_text_length",
            "qps",
            "pool_max_workers",
            "term_qps",
            "term_pool_max_workers",
            "auto_extract_glossary",
            "primary_font_family",
            "default_system_prompt",
        }
    ),
    "server": frozenset({"host", "port", "debug"}),
    "pdf2zh": frozenset(
        {
            "split_short_lines",
            "short_line_split_factor",
            "skip_clean",
            "disable_rich_text_translate",
            "enhance_compatibility",
            "translate_table_text",
            "skip_scanned_detection",
            "ocr_workaround",
            "auto_enable_ocr_workaround",
            "no_merge_alternating_line_numbers",
            "skip_formula_offset_calculation",
            "non_formula_line_iou_threshold",
            "figure_table_protection_threshold",
            "formula_font_pattern",
            "formula_char_pattern",
        }
    ),
}


def _validate_known_sections_and_keys(config_data: dict) -> None:
    unknown_sections = sorted(set(config_data) - set(_KNOWN_SECTION_KEYS))
    if unknown_sections:
        raise ConfigError(
            "未知配置段 [" + "], [".join(unknown_sections) + f"]；仅支持: {', '.join(sorted(_KNOWN_SECTION_KEYS))}"
        )
    for section_name, known_keys in _KNOWN_SECTION_KEYS.items():
        section = config_data.get(section_name)
        if section is None:
            continue
        if not isinstance(section, dict):
            raise ConfigError(f"[{section_name}] 必须是 TOML table")
        unknown_keys = sorted(set(section) - set(known_keys))
        if unknown_keys:
            raise ConfigError(f"[{section_name}] 存在未知字段: {', '.join(unknown_keys)}")


def _optional_bool(section: dict, key: str, path: str) -> bool | None:
    value = section.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ConfigError(f"{path}.{key} 必须是布尔值 true 或 false")
    return value


def _optional_non_bool_int(
    section: dict,
    key: str,
    path: str,
    *,
    minimum: int,
) -> int | None:
    value = section.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ConfigError(f"{path}.{key} 必须是不小于 {minimum} 的整数（布尔值不算）")
    return value


def _parse_model_runtime_config(model_cfg: dict) -> ModelRuntimeConfig:
    provider = model_cfg.get("provider", "openai_compatible")
    if not isinstance(provider, str) or not provider.strip():
        raise ConfigError("[model].provider 必须是非空字符串")
    provider = provider.strip()
    if provider not in PROVIDER_INDEX:
        available = "、".join(sorted(PROVIDER_INDEX))
        raise ConfigError(f"[model].provider 未知: {provider!r}（可用: {available}）")

    model_name = model_cfg.get("model", "")
    if not isinstance(model_name, str) or not model_name.strip():
        raise ConfigError("[model].model 必须是非空字符串")

    env_key = os.environ.get("MODEL_API_KEY")
    if env_key is not None:
        api_key = env_key.strip()
    else:
        file_key = model_cfg.get("api_key", "")
        api_key = file_key.strip() if isinstance(file_key, str) else ""
    if not api_key:
        raise ConfigError("请设置 model.api_key 或环境变量 MODEL_API_KEY")
    if api_key.startswith("sk-your-api-key"):
        raise ConfigError("请设置 model.api_key 或环境变量 MODEL_API_KEY（当前为示例占位值）")

    base_url = model_cfg.get("base_url")
    if base_url is not None and (not isinstance(base_url, str) or not base_url.strip()):
        raise ConfigError("[model].base_url 若设置必须是非空字符串")
    base_url = base_url.strip() if isinstance(base_url, str) and base_url else None

    thinking_mode = model_cfg.get("thinking_mode")
    if thinking_mode is not None:
        if not isinstance(thinking_mode, str) or thinking_mode.strip() not in ("enabled", "disabled"):
            raise ConfigError("[model].thinking_mode 仅支持 enabled/disabled")
        thinking_mode = thinking_mode.strip()

    reasoning_effort = model_cfg.get("reasoning_effort")
    if reasoning_effort is not None:
        if not isinstance(reasoning_effort, str) or not reasoning_effort.strip():
            raise ConfigError("[model].reasoning_effort 必须是非空字符串")
        reasoning_effort = reasoning_effort.strip()

    send_reasoning_effort = model_cfg.get("send_reasoning_effort", False)
    if not isinstance(send_reasoning_effort, bool):
        raise ConfigError("[model].send_reasoning_effort 必须是布尔值 true 或 false")

    enable_json_mode = _optional_bool(model_cfg, "enable_json_mode", "[model]")

    temperature = model_cfg.get("temperature")
    if temperature is not None:
        if not isinstance(temperature, str) or not temperature.strip():
            raise ConfigError('[model].temperature 必须是非空字符串形式，例如 "0.7"')
        temperature = temperature.strip()
        try:
            temperature_number = float(temperature)
        except ValueError:
            raise ConfigError("[model].temperature 必须可解析为浮点数") from None
        if not math.isfinite(temperature_number):
            raise ConfigError("[model].temperature 必须是有限浮点数（不接受 nan/inf）")

    send_temperature = model_cfg.get("send_temperature", False)
    if not isinstance(send_temperature, bool):
        raise ConfigError("[model].send_temperature 必须是布尔值 true 或 false")

    timeout = model_cfg.get("timeout")
    if timeout is not None:
        if not isinstance(timeout, str) or not timeout.strip():
            raise ConfigError('[model].timeout 必须是非空字符串形式，例如 "500"')
        timeout = timeout.strip()
        try:
            timeout_number = float(timeout)
        except ValueError:
            raise ConfigError("[model].timeout 必须是正数形式的字符串") from None
        if not math.isfinite(timeout_number) or timeout_number <= 0:
            raise ConfigError("[model].timeout 必须是有限正数形式的字符串（不接受 nan/inf/0/负数）")

    if provider in ("aliyun", "openai", "openai_compatible"):
        if send_temperature and not temperature:
            raise ConfigError("[model].send_temperature=true 时必须设置可解析为浮点数的 [model].temperature")
        if temperature is not None and not send_temperature:
            logger.warning("[model].temperature 已配置但 send_temperature=false，不会进入实际 API 请求")
    else:
        if send_temperature:
            raise ConfigError(
                f"[model].send_temperature 不适用于 provider={provider}（仅 aliyun/openai/openai_compatible）"
            )
        if temperature is not None:
            logger.warning("[model].temperature 不适用于 provider=%s，已忽略", provider)

    if provider in ("openai", "openai_compatible"):
        if reasoning_effort is not None and reasoning_effort not in (
            "minimal",
            "low",
            "medium",
            "high",
        ):
            raise ConfigError(f"[model].reasoning_effort 仅支持 minimal/low/medium/high（当前值 {reasoning_effort!r}）")
        if send_reasoning_effort and not reasoning_effort:
            raise ConfigError("[model].send_reasoning_effort=true 时必须设置 [model].reasoning_effort")
        if reasoning_effort is not None and not send_reasoning_effort:
            logger.warning("[model].reasoning_effort 已配置但 send_reasoning_effort=false，不会进入实际 API 请求")
    elif provider == "deepseek":
        if reasoning_effort is not None and reasoning_effort not in ("high", "max"):
            raise ConfigError("[model].reasoning_effort（DeepSeek）仅支持 high/max")
        if send_reasoning_effort:
            logger.warning(
                "[model].send_reasoning_effort 不适用于 DeepSeek："
                "v4 thinking transform 会自动发送 reasoning effort，该开关已忽略"
            )
    else:
        if send_reasoning_effort:
            raise ConfigError(
                f"[model].send_reasoning_effort 不适用于 provider={provider}（仅 openai/openai_compatible）"
            )
        if reasoning_effort is not None:
            logger.warning("[model].reasoning_effort 不适用于 provider=%s，已忽略", provider)

    if thinking_mode is not None and provider != "deepseek":
        logger.warning("[model].thinking_mode 仅适用于 provider=deepseek，已忽略")

    if timeout is not None and provider not in ("aliyun", "openai", "openai_compatible"):
        logger.warning("[model].timeout 不适用于 provider=%s，已忽略", provider)

    if provider == "openai_compatible" and not base_url:
        raise ConfigError("[model].base_url 是 openai_compatible 必填项")
    if base_url and provider not in ("siliconflow", "aliyun", "openai", "openai_compatible"):
        logger.warning("[model].base_url 对 provider=%s 无效，已忽略", provider)

    return ModelRuntimeConfig(
        provider=provider,
        api_key=api_key,
        model=model_name.strip(),
        base_url=base_url,
        thinking_mode=thinking_mode,
        reasoning_effort=reasoning_effort,
        send_reasoning_effort=send_reasoning_effort,
        enable_json_mode=enable_json_mode,
        temperature=temperature,
        send_temperature=send_temperature,
        timeout=timeout,
    )


def _parse_translation_runtime_config(translation_cfg: dict) -> TranslationRuntimeConfig:
    lang_in = translation_cfg.get("lang_in", "en")
    if not isinstance(lang_in, str) or not lang_in.strip():
        raise ConfigError("[translation].lang_in 必须是非空字符串")
    lang_out = translation_cfg.get("lang_out", "zh")
    if not isinstance(lang_out, str) or not lang_out.strip():
        raise ConfigError("[translation].lang_out 必须是非空字符串")

    min_text_length = translation_cfg.get("min_text_length", 5)
    if isinstance(min_text_length, bool) or not isinstance(min_text_length, int):
        raise ConfigError("[translation].min_text_length 必须是非布尔整数")
    if min_text_length < 0:
        raise ConfigError("[translation].min_text_length 必须 >= 0")

    qps = translation_cfg.get("qps", 4)
    if isinstance(qps, bool) or not isinstance(qps, int) or qps < 1:
        raise ConfigError("[translation].qps 必须是不小于 1 的整数（布尔值不算）")
    if qps > 100:
        logger.warning(
            "[translation].qps=%d 较高：会显著增加并发连接数、API 消耗与限流概率",
            qps,
        )

    pool_max_workers = _optional_non_bool_int(
        translation_cfg,
        "pool_max_workers",
        "[translation]",
        minimum=1,
    )
    if pool_max_workers is not None and pool_max_workers > 100:
        logger.warning(
            "[translation].pool_max_workers=%d 较高：会显著增加并发连接数，请谨慎使用",
            pool_max_workers,
        )

    term_qps = _optional_non_bool_int(
        translation_cfg,
        "term_qps",
        "[translation]",
        minimum=1,
    )
    # 上游 2.9.0：term_pool_max_workers 为 0 时跟随 pool_max_workers，因此允许 0。
    term_pool_max_workers = _optional_non_bool_int(
        translation_cfg,
        "term_pool_max_workers",
        "[translation]",
        minimum=0,
    )

    auto_extract_glossary = translation_cfg.get("auto_extract_glossary", True)
    if not isinstance(auto_extract_glossary, bool):
        raise ConfigError("[translation].auto_extract_glossary 必须是布尔值 true 或 false")

    primary_font_family = translation_cfg.get("primary_font_family", "auto")
    if not isinstance(primary_font_family, str) or primary_font_family.strip() not in (
        "auto",
        "serif",
        "sans-serif",
        "script",
    ):
        raise ConfigError("[translation].primary_font_family 仅支持 auto/serif/sans-serif/script")
    primary_font_family = None if primary_font_family.strip() == "auto" else primary_font_family.strip()

    default_system_prompt = translation_cfg.get("default_system_prompt")
    if default_system_prompt is not None:
        if not isinstance(default_system_prompt, str) or not default_system_prompt.strip():
            raise ConfigError("[translation].default_system_prompt 必须是非空字符串")
        default_system_prompt = default_system_prompt.strip()

    return TranslationRuntimeConfig(
        lang_in=lang_in.strip(),
        lang_out=lang_out.strip(),
        min_text_length=min_text_length,
        qps=qps,
        pool_max_workers=pool_max_workers,
        term_qps=term_qps,
        term_pool_max_workers=term_pool_max_workers,
        auto_extract_glossary=auto_extract_glossary,
        primary_font_family=primary_font_family,
        default_system_prompt=default_system_prompt,
    )


def _pdf2zh_bool(pdf_cfg: dict, key: str, default: bool) -> bool:
    value = pdf_cfg.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"[pdf2zh].{key} 必须是布尔值 true 或 false")
    return value


def _pdf2zh_float(
    pdf_cfg: dict,
    key: str,
    default: float,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    value = pdf_cfg.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"[pdf2zh].{key} 必须是非布尔数值")
    number = float(value)
    if not math.isfinite(number):
        raise ConfigError(f"[pdf2zh].{key} 必须是有限数值（不接受 nan/inf）")
    if minimum is not None and number < minimum:
        raise ConfigError(f"[pdf2zh].{key} 必须 >= {minimum}")
    if maximum is not None and number > maximum:
        raise ConfigError(f"[pdf2zh].{key} 必须 <= {maximum}")
    return number


def _pdf2zh_pattern(pdf_cfg: dict, key: str) -> str | None:
    value = pdf_cfg.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"[pdf2zh].{key} 必须是非空字符串")
    pattern = value.strip()
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ConfigError(f"[pdf2zh].{key} 不是合法正则表达式：{exc}") from exc
    return pattern


def _parse_pdf2zh_runtime_config(pdf_cfg: dict) -> Pdf2zhRuntimeConfig:
    """严格解析 [pdf2zh]：类型、范围、正则全部在启动期校验。"""
    return Pdf2zhRuntimeConfig(
        split_short_lines=_pdf2zh_bool(pdf_cfg, "split_short_lines", False),
        short_line_split_factor=_pdf2zh_float(
            pdf_cfg,
            "short_line_split_factor",
            0.8,
            minimum=0.1,
        ),
        skip_clean=_pdf2zh_bool(pdf_cfg, "skip_clean", False),
        disable_rich_text_translate=_pdf2zh_bool(
            pdf_cfg,
            "disable_rich_text_translate",
            False,
        ),
        enhance_compatibility=_pdf2zh_bool(pdf_cfg, "enhance_compatibility", False),
        translate_table_text=_pdf2zh_bool(pdf_cfg, "translate_table_text", True),
        skip_scanned_detection=_pdf2zh_bool(pdf_cfg, "skip_scanned_detection", False),
        ocr_workaround=_pdf2zh_bool(pdf_cfg, "ocr_workaround", False),
        auto_enable_ocr_workaround=_pdf2zh_bool(
            pdf_cfg,
            "auto_enable_ocr_workaround",
            False,
        ),
        no_merge_alternating_line_numbers=_pdf2zh_bool(
            pdf_cfg,
            "no_merge_alternating_line_numbers",
            False,
        ),
        skip_formula_offset_calculation=_pdf2zh_bool(
            pdf_cfg,
            "skip_formula_offset_calculation",
            False,
        ),
        non_formula_line_iou_threshold=_pdf2zh_float(
            pdf_cfg,
            "non_formula_line_iou_threshold",
            0.9,
            minimum=0.0,
            maximum=1.0,
        ),
        figure_table_protection_threshold=_pdf2zh_float(
            pdf_cfg,
            "figure_table_protection_threshold",
            0.9,
            minimum=0.0,
            maximum=1.0,
        ),
        formula_font_pattern=_pdf2zh_pattern(pdf_cfg, "formula_font_pattern"),
        formula_char_pattern=_pdf2zh_pattern(pdf_cfg, "formula_char_pattern"),
    )


def _lenient_model_runtime_config(model_cfg: dict) -> ModelRuntimeConfig:
    """宽松解析：缺失/类型错误回退默认值，供测试与 create_app fallback 装配。

    生产路径必须先通过 ``validate_startup_requirements``（严格解析）再调用
    ``build_app_settings``；宽松模式只保证无 config.toml 的环境也能装配。
    """

    def opt_str(key: str) -> str | None:
        value = model_cfg.get(key)
        if not isinstance(value, str) or not value.strip():
            return None
        stripped = value.strip()
        if key in ("temperature", "timeout"):
            try:
                number = float(stripped)
            except ValueError:
                return None
            if not math.isfinite(number):
                return None
            if key == "timeout" and number <= 0:
                return None
        return stripped

    def opt_bool(key: str, default: bool) -> bool:
        value = model_cfg.get(key, default)
        return value if isinstance(value, bool) else default

    env_key = os.environ.get("MODEL_API_KEY")
    if env_key is not None:
        api_key = env_key.strip() if isinstance(env_key, str) else ""
    else:
        file_key = model_cfg.get("api_key", "")
        api_key = file_key.strip() if isinstance(file_key, str) else ""

    json_mode = model_cfg.get("enable_json_mode")
    return ModelRuntimeConfig(
        provider=_string(model_cfg.get("provider"), "openai_compatible").strip() or "openai_compatible",
        api_key=api_key,
        model=_string(model_cfg.get("model"), ""),
        base_url=opt_str("base_url"),
        thinking_mode=opt_str("thinking_mode"),
        reasoning_effort=opt_str("reasoning_effort"),
        send_reasoning_effort=opt_bool("send_reasoning_effort", False),
        enable_json_mode=json_mode if isinstance(json_mode, bool) else None,
        temperature=opt_str("temperature"),
        send_temperature=opt_bool("send_temperature", False),
        timeout=opt_str("timeout"),
    )


def _lenient_translation_runtime_config(translation_cfg: dict) -> TranslationRuntimeConfig:
    def opt_int(key: str, default: int | None) -> int | None:
        value = translation_cfg.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int):
            return default
        return value

    auto_extract = translation_cfg.get("auto_extract_glossary", True)
    primary = translation_cfg.get("primary_font_family", "auto")
    if not isinstance(primary, str) or primary.strip() not in ("auto", "serif", "sans-serif", "script"):
        primary_family: str | None = None
    else:
        primary_family = None if primary.strip() == "auto" else primary.strip()

    default_prompt = translation_cfg.get("default_system_prompt")
    if isinstance(default_prompt, str) and default_prompt.strip():
        default_prompt = default_prompt.strip()
    else:
        default_prompt = None

    min_text_length_value = opt_int("min_text_length", 5)
    qps_value = opt_int("qps", 4)
    return TranslationRuntimeConfig(
        lang_in=_string(translation_cfg.get("lang_in"), "en").strip() or "en",
        lang_out=_string(translation_cfg.get("lang_out"), "zh").strip() or "zh",
        min_text_length=5 if min_text_length_value is None else min_text_length_value,
        qps=4 if qps_value is None else qps_value,
        pool_max_workers=opt_int("pool_max_workers", None),
        term_qps=opt_int("term_qps", None),
        term_pool_max_workers=opt_int("term_pool_max_workers", None),
        auto_extract_glossary=auto_extract if isinstance(auto_extract, bool) else True,
        primary_font_family=primary_family,
        default_system_prompt=default_prompt,
    )


def _lenient_pdf2zh_runtime_config(pdf_cfg: dict) -> Pdf2zhRuntimeConfig:
    """宽松解析 [pdf2zh]：类型错误回退安全默认值，供无配置环境装配。"""

    def bool_value(key: str, default: bool) -> bool:
        value = pdf_cfg.get(key, default)
        return value if isinstance(value, bool) else default

    def float_value(
        key: str,
        default: float,
        *,
        minimum: float | None = None,
        maximum: float | None = None,
    ) -> float:
        value = pdf_cfg.get(key, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return default
        number = float(value)
        if not math.isfinite(number):
            return default
        if minimum is not None and number < minimum:
            return default
        if maximum is not None and number > maximum:
            return default
        return number

    def pattern_value(key: str) -> str | None:
        value = pdf_cfg.get(key)
        if not isinstance(value, str) or not value.strip():
            return None
        pattern = value.strip()
        try:
            re.compile(pattern)
        except re.error:
            return None
        return pattern

    return Pdf2zhRuntimeConfig(
        split_short_lines=bool_value("split_short_lines", False),
        short_line_split_factor=float_value("short_line_split_factor", 0.8, minimum=0.1),
        skip_clean=bool_value("skip_clean", False),
        disable_rich_text_translate=bool_value("disable_rich_text_translate", False),
        enhance_compatibility=bool_value("enhance_compatibility", False),
        translate_table_text=bool_value("translate_table_text", True),
        skip_scanned_detection=bool_value("skip_scanned_detection", False),
        ocr_workaround=bool_value("ocr_workaround", False),
        auto_enable_ocr_workaround=bool_value("auto_enable_ocr_workaround", False),
        no_merge_alternating_line_numbers=bool_value(
            "no_merge_alternating_line_numbers",
            False,
        ),
        skip_formula_offset_calculation=bool_value(
            "skip_formula_offset_calculation",
            False,
        ),
        non_formula_line_iou_threshold=float_value(
            "non_formula_line_iou_threshold",
            0.9,
            minimum=0.0,
            maximum=1.0,
        ),
        figure_table_protection_threshold=float_value(
            "figure_table_protection_threshold",
            0.9,
            minimum=0.0,
            maximum=1.0,
        ),
        formula_font_pattern=pattern_value("formula_font_pattern"),
        formula_char_pattern=pattern_value("formula_char_pattern"),
    )


def build_upstream_runtime_config(
    config_data: dict | None = None,
    *,
    strict: bool = True,
) -> UpstreamRuntimeConfig:
    """从配置快照严格解析并冻结上游运行时配置。

    API Key 原值只进入 ``ModelRuntimeConfig.api_key``（``repr=False``），
    绝不进入异常消息或日志。
    """
    data = CONFIG if config_data is None else config_data
    model_section = _require_table(data, "model")
    translation_section = _require_table(data, "translation")
    pdf_section = _require_table(data, "pdf2zh") if "pdf2zh" in data else {}
    if strict:
        model_cfg = _parse_model_runtime_config(model_section)
        translation_cfg = _parse_translation_runtime_config(translation_section)
        pdf_cfg = _parse_pdf2zh_runtime_config(pdf_section)
    else:
        model_cfg = _lenient_model_runtime_config(model_section)
        translation_cfg = _lenient_translation_runtime_config(translation_section)
        pdf_cfg = _lenient_pdf2zh_runtime_config(pdf_section)
    return UpstreamRuntimeConfig(
        model=model_cfg,
        translation=translation_cfg,
        pdf=pdf_cfg,
    )


def validate_startup_requirements(config_data: dict | None = None) -> UpstreamRuntimeConfig:
    """启动服务器前的统一配置校验（[server] 由 resolve_server_config 校验）。

    直接消费的 section 必须为 table，核心字段类型/非空要求清晰；
    任何错误抛 ConfigError，由 main 以退出码 2 结束。
    返回严格解析出的 ``UpstreamRuntimeConfig``，main 必须把该实例原样传给
    ``build_app_settings``，禁止宽松重解析。
    """
    data = CONFIG if config_data is None else config_data
    if config_data is None and _CONFIG_LOAD_ERROR is not None:
        raise ConfigError(_CONFIG_LOAD_ERROR)
    _validate_known_sections_and_keys(data)
    model_section = _require_table(data, "model")
    pdf_reader_section = _require_table(data, "pdf_reader")
    translation_section = _require_table(data, "translation")
    _validate_model_section(model_section)
    _validate_pdf_reader_section(pdf_reader_section)
    _validate_translation_section(translation_section)
    return build_upstream_runtime_config(data)


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


def build_app_settings(
    config_data: dict | None = None,
    *,
    cli_debug: bool | None = None,
    run_cfg: ServerConfig | None = None,
    upstream: UpstreamRuntimeConfig | None = None,
) -> AppSettings:
    """从配置快照构建冻结的 ``AppSettings``（供 ``main``/测试显式传给 ``create_app``）。

    默认按 ``resolve_server_config(config_data, cli_debug=cli_debug)`` 解析一次；
    传入 ``run_cfg`` 时直接复用该已解析结果（不再调用 ``resolve_server_config``，
    避免 ``main`` 内两次解析导致 debug/use_reloader 与 ``settings.debug`` 分叉，
    此时 ``run_cfg`` 优先于 ``cli_debug``）。传入 ``upstream`` 时原样复用
    （``main`` 必须传回 ``validate_startup_requirements`` 的严格实例）；
    未传入时以宽松模式装配，供无 config.toml 的测试/兼容 fallback 使用。
    """
    data = CONFIG if config_data is None else config_data
    if run_cfg is None:
        run_cfg = resolve_server_config(data, cli_debug=cli_debug)
    if upstream is None:
        upstream = build_upstream_runtime_config(data, strict=False)
    pdf_reader = _section(data, "pdf_reader")
    dpi = pdf_reader.get("dpi", 200)
    return AppSettings(
        debug=run_cfg.debug,
        cache_dir=paths.resolve_cache_dir(_string(pdf_reader.get("cache_dir"), "cache")),
        dpi=dpi if isinstance(dpi, int) and not isinstance(dpi, bool) else 200,
        glossary_path=paths.get_glossary_path(),
        model_provider=upstream.model.provider,
        model=upstream.model.model,
        lang_in=upstream.translation.lang_in,
        lang_out=upstream.translation.lang_out,
        upstream=upstream,
    )


DEBUG: bool = _resolve_file_debug(CONFIG)
