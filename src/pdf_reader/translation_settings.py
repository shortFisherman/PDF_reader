import logging

from pdf2zh_next import SettingsModel
from pdf2zh_next.config.model import BasicSettings
from pdf2zh_next.config.model import PDFSettings as Pdf2zhPDFSettings
from pdf2zh_next.config.model import TranslationSettings as Pdf2zhTranslationSettings

from pdf_reader import config
from pdf_reader.engine_resolver import build_engine_kwargs, resolve_engine

logger = logging.getLogger("pdf_reader.engine")


def _settings_summary() -> str:
    return (
        f"provider={config.MODEL_PROVIDER} model={config.MODEL} "
        f"lang={config.TRANSLATION_LANG_IN}->{config.TRANSLATION_LANG_OUT} "
        f"cache_dir={config.CACHE_DIR} dpi={config.DPI}"
    )


def build_settings(
    input_pdf: str,
    user_prompt: str | None = None,
    output_dir: str | None = None,
    glossary_paths: list[str] | None = None,
    pages: str = "1",
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

    logger.debug(
        "[settings] provider=%s model=%s lang=%s->%s pages=%s",
        config.MODEL_PROVIDER,
        config.MODEL,
        config.TRANSLATION_LANG_IN,
        config.TRANSLATION_LANG_OUT,
        pages,
    )

    return SettingsModel(
        basic=BasicSettings(debug=False),
        translation=Pdf2zhTranslationSettings(**translation_kwargs),
        pdf=Pdf2zhPDFSettings(
            pages=pages,
            no_dual=True,
            only_include_translated_page=True,
            watermark_output_mode="no_watermark",
        ),
        translate_engine_settings=spec.settings_cls(**engine_kwargs),
    )
