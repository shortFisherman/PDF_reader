import tempfile
from pathlib import Path

import pymupdf
import pytest

from pdf_reader import config
from pdf_reader.file_hash import sha256
from pdf_reader.pdf_renderer import render_page
from pdf_reader.translation_settings import build_settings


def _upstream(
    model: config.ModelRuntimeConfig | None = None,
    translation: config.TranslationRuntimeConfig | None = None,
    pdf: config.Pdf2zhRuntimeConfig | None = None,
) -> config.UpstreamRuntimeConfig:
    return config.UpstreamRuntimeConfig(
        model=model
        or config.ModelRuntimeConfig(
            provider="deepseek",
            api_key="sk-test-key",
            model="deepseek-v4-flash",
        ),
        translation=translation or config.TranslationRuntimeConfig(lang_in="en", lang_out="zh"),
        pdf=pdf or config.Pdf2zhRuntimeConfig(),
    )


def test_sha256_consistent():
    import tempfile

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
    tmp.write(b"hello world")
    tmp.close()
    h1 = sha256(tmp.name)
    h2 = sha256(tmp.name)
    assert h1 == h2
    assert len(h1) == 64
    Path(tmp.name).unlink()


def test_sha256_different():
    tmp1 = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
    tmp1.write(b"hello")
    tmp1.close()
    tmp2 = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
    tmp2.write(b"world")
    tmp2.close()
    assert sha256(tmp1.name) != sha256(tmp2.name)
    Path(tmp1.name).unlink()
    Path(tmp2.name).unlink()


def test_render_page_valid(sample_pdf):
    doc = pymupdf.open(str(sample_pdf))
    data = render_page(doc, 0, 72)
    assert isinstance(data, bytes)
    assert len(data) > 0
    doc.close()


def test_render_page_out_of_range(sample_pdf):
    doc = pymupdf.open(str(sample_pdf))
    with pytest.raises(ValueError, match="page out of range"):
        render_page(doc, 999, 72)
    doc.close()


def test_build_settings_basic(mock_config):
    settings = build_settings(_upstream(), "dummy.pdf")
    assert settings.translation.lang_in == "en"
    assert settings.translation.lang_out == "zh"
    assert settings.translation.ignore_cache is True


def test_build_settings_with_prompt(mock_config):
    settings = build_settings(_upstream(), "dummy.pdf", "translate waveguide as 波导")
    assert settings.translation.custom_system_prompt == "translate waveguide as 波导"


def test_build_settings_with_output_dir(mock_config):
    settings = build_settings(_upstream(), "dummy.pdf", output_dir="/tmp/translate_output")
    assert settings.translation.output == "/tmp/translate_output"


def test_build_settings_without_output_dir(mock_config):
    settings = build_settings(_upstream(), "dummy.pdf")
    assert getattr(settings.translation, "output", None) is None


def test_config_provider_index_has_deepseek():
    assert "deepseek" in config.PROVIDER_INDEX
    assert config.PROVIDER_INDEX["deepseek"].settings_cls.__name__ == "DeepSeekSettings"


def test_config_deepseek_field_map_api_key():
    spec = config.PROVIDER_INDEX["deepseek"]
    assert "api_key" in spec.field_map
    assert spec.field_map["api_key"] == "deepseek_api_key"


def test_resolve_engine_deepseek(mock_config):
    from pdf2zh_next.config.translate_engine_model import DeepSeekSettings

    from pdf_reader.engine_resolver import resolve_engine

    spec = resolve_engine("deepseek")
    assert isinstance(spec, config.EngineSpec)
    assert spec.settings_cls is DeepSeekSettings


def test_resolve_engine_unknown_raises(mock_config):
    from pdf_reader.engine_resolver import resolve_engine

    with pytest.raises(config.ConfigError, match="未知 Provider"):
        resolve_engine("nonexistent")


def test_build_engine_kwargs_deepseek(mock_config):
    from pdf_reader.engine_resolver import build_engine_kwargs

    spec = config.PROVIDER_INDEX["deepseek"]
    model_cfg = config.ModelRuntimeConfig(
        provider="deepseek",
        api_key="sk-test",
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
    )
    kwargs = build_engine_kwargs(spec, model_cfg)
    assert kwargs["deepseek_api_key"] == "sk-test"
    assert kwargs["deepseek_model"] == "deepseek-chat"


def test_build_engine_kwargs_zhipu_ignores_thinking_mode(mock_config):
    from pdf_reader.engine_resolver import build_engine_kwargs

    spec = config.PROVIDER_INDEX["zhipu"]
    model_cfg = config.ModelRuntimeConfig(
        provider="zhipu",
        api_key="sk-test",
        model="glm-4-flash",
        thinking_mode="enabled",
    )
    kwargs = build_engine_kwargs(spec, model_cfg)
    assert "zhipu_thinking_mode" not in kwargs


def test_build_engine_kwargs_missing_api_key_raises(mock_config):
    from pdf_reader.engine_resolver import build_engine_kwargs

    spec = config.PROVIDER_INDEX["deepseek"]
    model_cfg = config.ModelRuntimeConfig(
        provider="deepseek",
        api_key=None,  # type: ignore[arg-type]
        model="some-model",
    )
    with pytest.raises(config.ConfigError, match="未配置"):
        build_engine_kwargs(spec, model_cfg)


def test_build_settings_deepseek_with_thinking(mock_config):
    from pdf2zh_next.config.translate_engine_model import DeepSeekSettings

    model_cfg = config.ModelRuntimeConfig(
        provider="deepseek",
        api_key="sk-test-key",
        model="deepseek-v4-flash",
        thinking_mode="enabled",
        reasoning_effort="high",
    )
    settings = build_settings(_upstream(model=model_cfg), "dummy.pdf")
    engine = settings.translate_engine_settings

    assert isinstance(engine, DeepSeekSettings)
    assert engine.deepseek_api_key == "sk-test-key"
    assert engine.deepseek_model == "deepseek-v4-flash"
    assert engine.deepseek_thinking_mode == "enabled"
    assert engine.deepseek_reasoning_effort == "high"


def test_build_settings_unknown_provider_raises(mock_config):
    model_cfg = config.ModelRuntimeConfig(
        provider="some_custom_gateway",
        api_key="sk-custom",
        model="custom-model",
        base_url="https://custom.api/v1",
    )
    with pytest.raises(config.ConfigError, match="未知 Provider"):
        build_settings(_upstream(model=model_cfg), "dummy.pdf")


def test_build_settings_unsupported_field_ignored(mock_config):
    from pdf2zh_next.config.translate_engine_model import ZhipuSettings

    model_cfg = config.ModelRuntimeConfig(
        provider="zhipu",
        api_key="sk-test-key",
        model="glm-4-flash",
        thinking_mode="enabled",
        temperature="0.5",
    )
    settings = build_settings(_upstream(model=model_cfg), "dummy.pdf")
    engine = settings.translate_engine_settings

    assert isinstance(engine, ZhipuSettings)
    assert engine.zhipu_api_key == "sk-test-key"
    assert engine.zhipu_model == "glm-4-flash"
    assert not hasattr(engine, "zhipu_thinking_mode")
    assert not hasattr(engine, "zhipu_temperature")


def test_build_settings_missing_api_key_raises(mock_config):
    model_cfg = config.ModelRuntimeConfig(
        provider="deepseek",
        api_key=None,  # type: ignore[arg-type]
        model="some-model",
    )
    with pytest.raises(ValueError, match="api_key"):
        build_settings(_upstream(model=model_cfg), "dummy.pdf")


def test_build_settings_with_glossary_paths(mock_config, monkeypatch):
    monkeypatch.setattr(config, "GLOSSARY_PATH", Path("nonexistent.csv"))
    settings = build_settings(_upstream(), "dummy.pdf", glossary_paths=["/a/one.csv", "/b/two.csv"])
    assert settings.translation.glossaries == "/a/one.csv,/b/two.csv"


def test_build_settings_glossary_paths_none(mock_config, monkeypatch):
    monkeypatch.setattr(config, "GLOSSARY_PATH", Path("nonexistent.csv"))
    settings = build_settings(_upstream(), "dummy.pdf")
    assert getattr(settings.translation, "glossaries", None) is None


def test_build_settings_glossary_paths_empty_list(mock_config, monkeypatch):
    monkeypatch.setattr(config, "GLOSSARY_PATH", Path("nonexistent.csv"))
    settings = build_settings(_upstream(), "dummy.pdf", glossary_paths=[])
    assert getattr(settings.translation, "glossaries", None) is None


def test_build_settings_debug_always_false(mock_config):
    settings = build_settings(_upstream(), "dummy.pdf")
    assert settings.basic.debug is False


def test_build_settings_translation_debug_independent_of_config_debug(mock_config, monkeypatch):
    monkeypatch.setattr(config, "DEBUG", True)
    settings = build_settings(_upstream(), "dummy.pdf")
    assert settings.basic.debug is False


def test_build_settings_multi_page_pages_param(mock_config, monkeypatch):
    monkeypatch.setattr(config, "GLOSSARY_PATH", Path("/nonexistent"))

    settings = build_settings(_upstream(), "/tmp/multi.pdf", None, pages="1-4")
    assert settings.pdf.pages == "1-4"
    assert settings.pdf.only_include_translated_page is True
    assert settings.pdf.no_dual is True


def test_build_settings_default_pages_is_one(mock_config, monkeypatch):
    monkeypatch.setattr(config, "GLOSSARY_PATH", Path("/nonexistent"))

    settings = build_settings(_upstream(), "/tmp/single.pdf", None)
    assert settings.pdf.pages == "1"


def test_build_settings_new_translation_defaults(mock_config):
    settings = build_settings(_upstream(), "dummy.pdf")
    translation = settings.translation
    assert translation.min_text_length == 5
    assert translation.qps == 4
    assert translation.pool_max_workers is None
    assert translation.term_qps is None
    assert translation.term_pool_max_workers is None
    assert translation.no_auto_extract_glossary is False
    assert translation.save_auto_extracted_glossary is True
    assert translation.primary_font_family is None
    assert translation.custom_system_prompt is None


def test_build_settings_translation_fields_map_through(mock_config):
    translation = config.TranslationRuntimeConfig(
        lang_in="en",
        lang_out="zh",
        min_text_length=12,
        qps=7,
        pool_max_workers=3,
        term_qps=2,
        term_pool_max_workers=2,
        auto_extract_glossary=False,
        primary_font_family="serif",
        default_system_prompt="/no_think default prompt",
    )
    settings = build_settings(_upstream(translation=translation), "dummy.pdf")
    assert settings.translation.min_text_length == 12
    assert settings.translation.qps == 7
    assert settings.translation.pool_max_workers == 3
    assert settings.translation.term_qps == 2
    assert settings.translation.term_pool_max_workers == 2
    assert settings.translation.no_auto_extract_glossary is True
    assert settings.translation.save_auto_extracted_glossary is False
    assert settings.translation.primary_font_family == "serif"
    assert settings.translation.custom_system_prompt == "/no_think default prompt"


def test_build_settings_term_pool_max_workers_zero_is_normalized_to_follow(mock_config, monkeypatch):
    monkeypatch.setattr(config, "GLOSSARY_PATH", Path("nonexistent.csv"))
    translation = config.TranslationRuntimeConfig(
        lang_in="en",
        lang_out="zh",
        pool_max_workers=3,
        term_pool_max_workers=0,
    )
    settings = build_settings(_upstream(translation=translation), "dummy.pdf")
    assert settings.translation.term_pool_max_workers is None
    assert "term_pool_max_workers" not in settings.translation.model_fields_set


def test_build_settings_term_pool_max_workers_none_is_omitted(mock_config, monkeypatch):
    monkeypatch.setattr(config, "GLOSSARY_PATH", Path("nonexistent.csv"))
    translation = config.TranslationRuntimeConfig(
        lang_in="en",
        lang_out="zh",
        pool_max_workers=3,
        term_pool_max_workers=None,
    )
    settings = build_settings(_upstream(translation=translation), "dummy.pdf")
    assert settings.translation.term_pool_max_workers is None
    assert "term_pool_max_workers" not in settings.translation.model_fields_set


def test_build_settings_term_pool_max_workers_positive_passes_through(mock_config, monkeypatch):
    monkeypatch.setattr(config, "GLOSSARY_PATH", Path("nonexistent.csv"))
    translation = config.TranslationRuntimeConfig(
        lang_in="en",
        lang_out="zh",
        pool_max_workers=3,
        term_pool_max_workers=2,
    )
    settings = build_settings(_upstream(translation=translation), "dummy.pdf")
    assert settings.translation.term_pool_max_workers == 2
    assert "term_pool_max_workers" in settings.translation.model_fields_set


def test_build_settings_page_prompt_overrides_default_prompt(mock_config):
    translation = config.TranslationRuntimeConfig(
        lang_in="en",
        lang_out="zh",
        default_system_prompt="default prompt",
    )
    settings = build_settings(
        _upstream(translation=translation),
        "dummy.pdf",
        "  page prompt  ",
    )
    assert settings.translation.custom_system_prompt == "page prompt"


def test_build_settings_blank_page_prompt_uses_default_prompt(mock_config):
    translation = config.TranslationRuntimeConfig(
        lang_in="en",
        lang_out="zh",
        default_system_prompt="default prompt",
    )
    settings = build_settings(_upstream(translation=translation), "dummy.pdf", "   ")
    assert settings.translation.custom_system_prompt == "default prompt"


def test_build_settings_structural_invariants_are_fixed(mock_config, monkeypatch):
    monkeypatch.setattr(config, "GLOSSARY_PATH", Path("nonexistent.csv"))
    settings = build_settings(
        _upstream(),
        "dummy.pdf",
        output_dir="C:/tmp/out",
        glossary_paths=["/tmp/g.csv"],
        pages="1-3",
    )
    assert settings.translation.ignore_cache is True
    assert settings.translation.output == "C:/tmp/out"
    assert settings.translation.glossaries == "/tmp/g.csv"
    assert settings.pdf.pages == "1-3"
    assert settings.pdf.no_dual is True
    assert settings.pdf.only_include_translated_page is True
    assert settings.pdf.watermark_output_mode == "no_watermark"
    assert settings.basic.debug is False


def test_build_settings_pdf2zh_defaults(mock_config):
    settings = build_settings(_upstream(), "dummy.pdf")
    pdf = settings.pdf
    assert pdf.split_short_lines is False
    assert pdf.short_line_split_factor == 0.8
    assert pdf.skip_clean is False
    assert pdf.disable_rich_text_translate is False
    assert pdf.enhance_compatibility is False
    assert pdf.translate_table_text is True
    assert pdf.skip_scanned_detection is False
    assert pdf.ocr_workaround is False
    assert pdf.auto_enable_ocr_workaround is False
    assert pdf.no_merge_alternating_line_numbers is False
    assert pdf.skip_formula_offset_calculation is False
    assert pdf.non_formula_line_iou_threshold == 0.9
    assert pdf.figure_table_protection_threshold == 0.9
    assert pdf.formular_font_pattern is None
    assert pdf.formular_char_pattern is None


def test_build_settings_pdf2zh_fields_map_through(mock_config):
    pdf_cfg = config.Pdf2zhRuntimeConfig(
        split_short_lines=True,
        short_line_split_factor=0.5,
        skip_clean=True,
        disable_rich_text_translate=True,
        enhance_compatibility=True,
        translate_table_text=False,
        skip_scanned_detection=True,
        ocr_workaround=True,
        auto_enable_ocr_workaround=True,
        no_merge_alternating_line_numbers=True,
        skip_formula_offset_calculation=True,
        non_formula_line_iou_threshold=0.4,
        figure_table_protection_threshold=0.6,
        formula_font_pattern="^math",
        formula_char_pattern="\\d+",
    )
    settings = build_settings(_upstream(pdf=pdf_cfg), "dummy.pdf")
    pdf = settings.pdf
    assert pdf.split_short_lines is True
    assert pdf.short_line_split_factor == 0.5
    assert pdf.skip_clean is True
    assert pdf.disable_rich_text_translate is True
    assert pdf.enhance_compatibility is True
    assert pdf.translate_table_text is False
    assert pdf.skip_scanned_detection is True
    assert pdf.ocr_workaround is True
    assert pdf.auto_enable_ocr_workaround is True
    assert pdf.no_merge_alternating_line_numbers is True
    assert pdf.skip_formula_offset_calculation is True
    assert pdf.non_formula_line_iou_threshold == 0.4
    assert pdf.figure_table_protection_threshold == 0.6
    assert pdf.formular_font_pattern == "^math"
    assert pdf.formular_char_pattern == "\\d+"


def test_build_settings_pdf2zh_structural_fields_stay_hardcoded(mock_config):
    """[pdf2zh] 配置绝不能覆盖 pages/no_dual/only_include/watermark，也不开放结构字段。"""
    pdf_cfg = config.Pdf2zhRuntimeConfig(
        split_short_lines=True,
        translate_table_text=False,
    )
    settings = build_settings(
        _upstream(pdf=pdf_cfg),
        "dummy.pdf",
        output_dir="C:/tmp/out",
        glossary_paths=["/tmp/g.csv"],
        pages="2-5",
    )
    assert settings.pdf.pages == "2-5"
    assert settings.pdf.no_dual is True
    assert settings.pdf.no_mono is False
    assert settings.pdf.only_include_translated_page is True
    assert settings.pdf.watermark_output_mode == "no_watermark"
    assert settings.pdf.max_pages_per_part is None
    assert settings.pdf.use_alternating_pages_dual is False
    assert settings.pdf.dual_translate_first is False
    assert settings.translation.ignore_cache is True
