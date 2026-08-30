import logging
from typing import Any, cast

from pdf_reader import config

logger = logging.getLogger("pdf_reader.engine")

CONFIG_ATTR_MAP: dict[str, str] = {
    "model": "model",
    "api_key": "api_key",
    "base_url": "base_url",
    "thinking_mode": "thinking_mode",
    "reasoning_effort": "reasoning_effort",
    "send_reasoning_effort": "send_reasoning_effort",
    "enable_json_mode": "enable_json_mode",
    "temperature": "temperature",
    "send_temperature": "send_temperature",
    "timeout": "timeout",
}

_SEND_SWITCH_NAMES = frozenset({"send_temperature", "send_reasoning_effort"})


def resolve_engine(provider: str) -> config.EngineSpec:  # noqa: ANN201
    spec = config.PROVIDER_INDEX.get(provider)
    if spec is None:
        raise config.ConfigError(f"未知 Provider: {provider!r}")
    logger.info("Using engine: %s (%s)", spec.settings_cls.__name__, provider)
    return spec


def build_engine_kwargs(
    spec: config.EngineSpec,
    model_cfg: config.ModelRuntimeConfig,
) -> dict:  # noqa: ANN001, ANN201
    # 保持运行时直接属性访问：settings_cls 缺 model_fields 时仍快速抛 AttributeError，
    # 不静默回退空字段。cast(Any) 只解决静态类型，不改变运行时行为。
    engine_fields = cast(Any, spec.settings_cls).model_fields
    kwargs: dict = {}

    for unified_name, engine_field in spec.field_map.items():
        config_attr = CONFIG_ATTR_MAP[unified_name]
        value = getattr(model_cfg, config_attr, None)

        if engine_field not in engine_fields:
            logger.warning("引擎 %s 不支持字段 %s，已跳过", spec.provider, engine_field)
            continue

        # 发送开关显式为 False 时与省略等价，不写入 Settings（保持旧请求行为）；
        # 其它字段（如 enable_json_mode=False）必须显式透传，不能吞掉 False。
        if unified_name in _SEND_SWITCH_NAMES and value is False:
            pass
        elif value is not None:
            kwargs[engine_field] = value
        elif unified_name in spec.required_fields:
            raise config.ConfigError(f"model.{unified_name} 未配置")
        elif unified_name == "base_url":
            pass
        else:
            logger.warning("当前引擎不支持 %s，已忽略", unified_name)

    optional_fields = ("thinking_mode", "reasoning_effort", "enable_json_mode", "temperature", "timeout")
    for unified_name in optional_fields:
        if unified_name not in spec.field_map:
            value = getattr(model_cfg, CONFIG_ATTR_MAP[unified_name], None)
            if value is not None:
                logger.warning("当前引擎不支持 %s，已忽略", unified_name)

    return kwargs
