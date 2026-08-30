import logging

from pdf2zh_next import SettingsModel
from pdf2zh_next.config.model import BasicSettings
from pdf2zh_next.config.model import PDFSettings as Pdf2zhPDFSettings
from pdf2zh_next.config.model import TranslationSettings as Pdf2zhTranslationSettings

from pdf_reader import config
from pdf_reader.engine_resolver import build_engine_kwargs, resolve_engine

logger = logging.getLogger("pdf_reader.engine")


def build_settings(
    upstream: config.UpstreamRuntimeConfig,
    input_pdf: str,
    user_prompt: str | None = None,
    output_dir: str | None = None,
    glossary_paths: list[str] | None = None,
    pages: str = "1",
) -> SettingsModel:
    model_cfg = upstream.model
    translation_cfg = upstream.translation
    spec = resolve_engine(model_cfg.provider)
    engine_kwargs = build_engine_kwargs(spec, model_cfg)

    translation_kwargs = {
        "lang_in": translation_cfg.lang_in,
        "lang_out": translation_cfg.lang_out,
        "min_text_length": translation_cfg.min_text_length,
        "qps": translation_cfg.qps,
        "ignore_cache": True,
        "no_auto_extract_glossary": not translation_cfg.auto_extract_glossary,
        "save_auto_extracted_glossary": translation_cfg.auto_extract_glossary,
    }
    if translation_cfg.pool_max_workers is not None:
        translation_kwargs["pool_max_workers"] = translation_cfg.pool_max_workers
    if translation_cfg.term_qps is not None:
        translation_kwargs["term_qps"] = translation_cfg.term_qps
    if translation_cfg.term_pool_max_workers is not None:
        translation_kwargs["term_pool_max_workers"] = translation_cfg.term_pool_max_workers
    if translation_cfg.primary_font_family is not None:
        translation_kwargs["primary_font_family"] = translation_cfg.primary_font_family
    # 页面任务 Prompt（非空）> translation.default_system_prompt > 上游默认。
    prompt = (user_prompt or "").strip() or translation_cfg.default_system_prompt
    if prompt:
        translation_kwargs["custom_system_prompt"] = prompt
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
        model_cfg.provider,
        model_cfg.model,
        translation_cfg.lang_in,
        translation_cfg.lang_out,
        pages,
    )

    pdf_cfg = upstream.pdf
    pdf_kwargs = {
        "pages": pages,
        "no_dual": True,
        "only_include_translated_page": True,
        "watermark_output_mode": "no_watermark",
        "split_short_lines": pdf_cfg.split_short_lines,
        "short_line_split_factor": pdf_cfg.short_line_split_factor,
        "skip_clean": pdf_cfg.skip_clean,
        "disable_rich_text_translate": pdf_cfg.disable_rich_text_translate,
        "enhance_compatibility": pdf_cfg.enhance_compatibility,
        "translate_table_text": pdf_cfg.translate_table_text,
        "skip_scanned_detection": pdf_cfg.skip_scanned_detection,
        "ocr_workaround": pdf_cfg.ocr_workaround,
        "auto_enable_ocr_workaround": pdf_cfg.auto_enable_ocr_workaround,
        "no_merge_alternating_line_numbers": pdf_cfg.no_merge_alternating_line_numbers,
        "skip_formula_offset_calculation": pdf_cfg.skip_formula_offset_calculation,
        "non_formula_line_iou_threshold": pdf_cfg.non_formula_line_iou_threshold,
        "figure_table_protection_threshold": pdf_cfg.figure_table_protection_threshold,
        # 本项目使用正确拼写 formula_*，上游 PDFSettings 是历史拼写 formular_*。
        "formular_font_pattern": pdf_cfg.formula_font_pattern,
        "formular_char_pattern": pdf_cfg.formula_char_pattern,
    }

    return SettingsModel(
        basic=BasicSettings(debug=False),
        translation=Pdf2zhTranslationSettings(**translation_kwargs),
        pdf=Pdf2zhPDFSettings(**pdf_kwargs),
        translate_engine_settings=spec.settings_cls(**engine_kwargs),
    )
