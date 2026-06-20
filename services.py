import hashlib
import logging

import pymupdf
from pdf2zh_next import SettingsModel
from pdf2zh_next.config.model import PDFSettings as Pdf2zhPDFSettings
from pdf2zh_next.config.model import TranslationSettings as Pdf2zhTranslationSettings
from pdf2zh_next.config.translate_engine_model import OpenAICompatibleSettings

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


def resolve_engine(provider: str):  # noqa: ANN201
    engine_cls = config.PROVIDER_MAP.get(provider)
    if engine_cls is None:
        logger.info("Provider '%s' not found, falling back to OpenAI Compatible", provider)
        return OpenAICompatibleSettings
    logger.info("Using engine: %s (%s)", engine_cls.__name__, config.MODEL)
    return engine_cls


def build_engine_kwargs(engine_cls):  # noqa: ANN001, ANN201
    engine_fields = engine_cls.model_fields
    engine_name = engine_cls.__name__
    kwargs = {}

    for unified_name in ("api_key", "model", "base_url", "thinking_mode",
                         "reasoning_effort", "enable_json_mode",
                         "temperature", "timeout"):
        config_attr_name = "MODEL" if unified_name == "model" else f"MODEL_{unified_name.upper()}"
        value = getattr(config, config_attr_name, None)

        engine_field = config.FIELD_MAP.get(unified_name, {}).get(engine_name)
        if engine_field is None:
            if value is not None and unified_name not in ("api_key", "model", "base_url"):
                logger.warning("当前引擎不支持 %s，已忽略", unified_name)
            continue
        if engine_field not in engine_fields:
            continue

        if value is not None:
            kwargs[engine_field] = value
        elif unified_name in ("api_key", "model"):
            raise RuntimeError(f"model.{unified_name} 未配置")
        elif unified_name == "base_url":
            pass
        else:
            logger.warning("当前引擎不支持 %s，已忽略", unified_name)

    return kwargs


def build_settings(
    single_page_pdf: str,
    user_prompt: str | None = None,
    output_dir: str | None = None,
    glossary_paths: list[str] | None = None,
) -> SettingsModel:
    engine_cls = resolve_engine(config.MODEL_PROVIDER)
    engine_kwargs = build_engine_kwargs(engine_cls)

    translation_kwargs = {
        "lang_in": config.TRANSLATION_LANG_IN,
        "lang_out": config.TRANSLATION_LANG_OUT,
        "ignore_cache": True,
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
        translation=Pdf2zhTranslationSettings(**translation_kwargs),
        pdf=Pdf2zhPDFSettings(
            pages="1",
            no_dual=True,
            only_include_translated_page=True,
            watermark_output_mode="no_watermark",
        ),
        translate_engine_settings=engine_cls(**engine_kwargs),
    )
