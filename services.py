import hashlib
import logging

import pymupdf
from pdf2zh_next import SettingsModel
from pdf2zh_next.config.model import BasicSettings
from pdf2zh_next.config.model import PDFSettings as Pdf2zhPDFSettings
from pdf2zh_next.config.model import TranslationSettings as Pdf2zhTranslationSettings

import config

logger = logging.getLogger("pdf_reader")


def sha256(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def render_page(doc: pymupdf.Document, page_num: int, dpi: int) -> bytes:
    if page_num < 0 or page_num >= doc.page_count:
        raise ValueError("page out of range")
    page = doc[page_num]
    pix = page.get_pixmap(dpi=dpi)
    return pix.tobytes(output="png")


def resolve_engine(provider: str) -> config.EngineSpec:  # noqa: ANN201
    spec = config.PROVIDER_INDEX.get(provider)
    if spec is None:
        logger.info("Provider '%s' not found, falling back to OpenAI Compatible", provider)
        spec = config.PROVIDER_INDEX["openai_compatible"]
    logger.info("Using engine: %s (%s)", spec.settings_cls.__name__, config.MODEL)
    return spec


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


def build_settings(
    single_page_pdf: str,
    user_prompt: str | None = None,
    output_dir: str | None = None,
    glossary_paths: list[str] | None = None,
    debug: bool = False,
) -> SettingsModel:
    spec = resolve_engine(config.MODEL_PROVIDER)
    engine_kwargs = build_engine_kwargs(spec)

    translation_kwargs = {
        "lang_in": config.TRANSLATION_LANG_IN,
        "lang_out": config.TRANSLATION_LANG_OUT,
        "ignore_cache": True,
        "save_auto_extracted_glossary": True,
    }
    if user_prompt and user_prompt.strip():
        translation_kwargs["custom_system_prompt"] = user_prompt.strip()
    paths = []
    if config.GLOSSARY_PATH.exists() and config.GLOSSARY_PATH.stat().st_size > 0:
        paths.append(str(config.GLOSSARY_PATH))
    if glossary_paths:
        paths.extend(glossary_paths)
    if paths:
        translation_kwargs["glossaries"] = ",".join(paths)
    if output_dir is not None:
        translation_kwargs["output"] = output_dir

    return SettingsModel(
        basic=BasicSettings(debug=debug),
        translation=Pdf2zhTranslationSettings(**translation_kwargs),
        pdf=Pdf2zhPDFSettings(
            pages="1",
            no_dual=True,
            only_include_translated_page=True,
            watermark_output_mode="no_watermark",
        ),
        translate_engine_settings=spec.settings_cls(**engine_kwargs),
    )
