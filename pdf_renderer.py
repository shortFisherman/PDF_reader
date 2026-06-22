import logging

import pymupdf
from pdf2zh_next import SettingsModel
from pdf2zh_next.config.model import BasicSettings
from pdf2zh_next.config.model import PDFSettings as Pdf2zhPDFSettings
from pdf2zh_next.config.model import TranslationSettings as Pdf2zhTranslationSettings

import config
from engine_resolver import build_engine_kwargs, resolve_engine

logger = logging.getLogger("pdf_reader")


def render_page(doc: pymupdf.Document, page_num: int, dpi: int) -> bytes:
    if page_num < 0 or page_num >= doc.page_count:
        raise ValueError("page out of range")
    page = doc[page_num]
    pix = page.get_pixmap(dpi=dpi)
    return pix.tobytes(output="png")


def build_settings(
    single_page_pdf: str,
    user_prompt: str | None = None,
    output_dir: str | None = None,
    glossary_paths: list[str] | None = None,
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
        basic=BasicSettings(debug=False),
        translation=Pdf2zhTranslationSettings(**translation_kwargs),
        pdf=Pdf2zhPDFSettings(
            pages="1",
            no_dual=True,
            only_include_translated_page=True,
            watermark_output_mode="no_watermark",
        ),
        translate_engine_settings=spec.settings_cls(**engine_kwargs),
    )
