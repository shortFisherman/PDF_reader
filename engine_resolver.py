import logging

import config

logger = logging.getLogger("pdf_reader")

CONFIG_ATTR_MAP: dict[str, str] = {
    "model": "MODEL",
    "api_key": "MODEL_API_KEY",
    "base_url": "MODEL_BASE_URL",
    "thinking_mode": "MODEL_THINKING_MODE",
    "reasoning_effort": "MODEL_REASONING_EFFORT",
    "enable_json_mode": "MODEL_ENABLE_JSON_MODE",
    "temperature": "MODEL_TEMPERATURE",
    "timeout": "MODEL_TIMEOUT",
}


def resolve_engine(provider: str) -> config.EngineSpec:  # noqa: ANN201
    config._validate_required_config()
    spec = config.PROVIDER_INDEX.get(provider)
    if spec is None:
        logger.info("Provider '%s' not found, falling back to OpenAI Compatible", provider)
        spec = config.PROVIDER_INDEX["openai_compatible"]
    logger.info("Using engine: %s (%s)", spec.settings_cls.__name__, config.MODEL)
    return spec


def build_engine_kwargs(spec: config.EngineSpec) -> dict:  # noqa: ANN001, ANN201
    engine_fields = spec.settings_cls.model_fields
    kwargs: dict = {}

    for unified_name, engine_field in spec.field_map.items():
        config_attr = CONFIG_ATTR_MAP[unified_name]
        value = getattr(config, config_attr, None)

        if engine_field not in engine_fields:
            logger.warning("引擎 %s 不支持字段 %s，已跳过", spec.provider, engine_field)
            continue

        if value is not None:
            kwargs[engine_field] = value
        elif unified_name in spec.required_fields:
            raise RuntimeError(f"model.{unified_name} 未配置")
        elif unified_name == "base_url":
            pass
        else:
            logger.warning("当前引擎不支持 %s，已忽略", unified_name)

    optional_fields = ("thinking_mode", "reasoning_effort", "enable_json_mode", "temperature", "timeout")
    for unified_name in optional_fields:
        if unified_name not in spec.field_map:
            value = getattr(config, CONFIG_ATTR_MAP[unified_name], None)
            if value is not None:
                logger.warning("当前引擎不支持 %s，已忽略", unified_name)

    return kwargs
