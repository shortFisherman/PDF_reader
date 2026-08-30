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

    # P0-04 严格正文路径：正文翻译固定关闭上游自动术语提取与自动保存，
    # 不再由 translation.auto_extract_glossary 反转；该配置在 P1-01 候选服务
    # 落地前对正文保持惰性。glossaries 只由调用方传入本次 fresh 的有效词表。
    translation_kwargs = {
        "lang_in": translation_cfg.lang_in,
        "lang_out": translation_cfg.lang_out,
        "min_text_length": translation_cfg.min_text_length,
        "qps": translation_cfg.qps,
        "ignore_cache": True,
        "no_auto_extract_glossary": True,
        "save_auto_extracted_glossary": False,
    }
    if translation_cfg.pool_max_workers is not None:
        translation_kwargs["pool_max_workers"] = translation_cfg.pool_max_workers
    if translation_cfg.term_qps is not None:
        translation_kwargs["term_qps"] = translation_cfg.term_qps
    # PDF2ZH/BabelDOC 2.9.0/0.6.2 契约不一致：pdf2zh_next 文档宣称 0 表示跟随
    # pool_max_workers，但 high_level.py 会把 0 原样传给 BabelDOC
    # TranslationConfig，而 BabelDOC 只在值为 None 时回退；0 最终会进入
    # PriorityThreadPoolExecutor 并报 max_workers must be greater than 0。
    # 本项目保留 0 的公开语义，在这里把 0 规范化为省略，正整数照常传递。
    term_pool_max_workers = translation_cfg.term_pool_max_workers
    if term_pool_max_workers is not None and term_pool_max_workers > 0:
        translation_kwargs["term_pool_max_workers"] = term_pool_max_workers
    if translation_cfg.primary_font_family is not None:
        translation_kwargs["primary_font_family"] = translation_cfg.primary_font_family
    # 页面任务 Prompt（非空）> translation.default_system_prompt > 上游默认。
    prompt = (user_prompt or "").strip() or translation_cfg.default_system_prompt
    if prompt:
        translation_kwargs["custom_system_prompt"] = prompt
    if glossary_paths:
        translation_kwargs["glossaries"] = ",".join(glossary_paths)
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
