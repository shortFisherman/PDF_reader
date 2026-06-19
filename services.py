import hashlib

import pymupdf
from pdf2zh_next import SettingsModel
from pdf2zh_next.config.model import PDFSettings as Pdf2zhPDFSettings
from pdf2zh_next.config.model import TranslationSettings as Pdf2zhTranslationSettings
from pdf2zh_next.config.translate_engine_model import DeepSeekSettings

import config


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


def build_settings(single_page_pdf: str, user_prompt: str | None = None, output_dir: str | None = None) -> SettingsModel:
    translation_kwargs = {
        "lang_in": config.TRANSLATION_LANG_IN,
        "lang_out": config.TRANSLATION_LANG_OUT,
        "ignore_cache": True,
    }
    if user_prompt and user_prompt.strip():
        translation_kwargs["custom_system_prompt"] = user_prompt.strip()
    if config.GLOSSARY_PATH.exists() and config.GLOSSARY_PATH.stat().st_size > 0:
        translation_kwargs["glossaries"] = str(config.GLOSSARY_PATH)
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
        translate_engine_settings=DeepSeekSettings(
            deepseek_api_key=config.DEEPSEEK_API_KEY,
            deepseek_model=config.DEEPSEEK_MODEL,
            deepseek_base_url=config.DEEPSEEK_BASE_URL,
        ),
    )
