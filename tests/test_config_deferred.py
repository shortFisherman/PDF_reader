import logging
import os
import sys
from unittest.mock import patch

import pytest

import pdf_reader


def _cfg(
    *,
    model: dict | None = None,
    translation: dict | None = None,
    pdf_reader: dict | None = None,
    pdf2zh: dict | None = None,
    term_extraction: dict | None = None,
) -> dict:
    cfg = {
        "model": {"provider": "deepseek", "model": "deepseek-chat", "api_key": "sk-test"},
        "pdf_reader": {"dpi": 200, "cache_dir": "cache"},
        "translation": {"lang_in": "en", "lang_out": "zh"},
        "pdf2zh": {},
    }
    if model is not None:
        cfg["model"].update(model)
    if translation is not None:
        cfg["translation"].update(translation)
    if pdf_reader is not None:
        cfg["pdf_reader"].update(pdf_reader)
    if pdf2zh is not None:
        cfg["pdf2zh"].update(pdf2zh)
    if term_extraction is not None:
        cfg["term_extraction"] = term_extraction
    return cfg


def test_import_config_without_config_toml():
    original_config = pdf_reader.__dict__.get("config")
    with patch.dict(sys.modules):
        sys.modules.pop("pdf_reader.config", None)
        pdf_reader.__dict__.pop("config", None)
        with patch("builtins.open", side_effect=FileNotFoundError):
            from pdf_reader import config

            assert config.CONFIG == {}
            assert config.MODEL == ""
            assert config.MODEL_API_KEY == ""
            assert config.MODEL_PROVIDER == "openai_compatible"
    pdf_reader.__dict__["config"] = original_config


def test_validate_passes_when_api_key_from_env(monkeypatch):
    from pdf_reader import config

    monkeypatch.setattr(config, "MODEL_API_KEY", "sk-from-env")
    monkeypatch.setattr(config, "MODEL", "some-model")

    config._validate_required_config()


def test_env_model_api_key_overrides_file_value():
    original_config = pdf_reader.__dict__.get("config")
    with patch.dict(sys.modules):
        sys.modules.pop("pdf_reader.config", None)
        pdf_reader.__dict__.pop("config", None)
        with patch.dict(os.environ, {"MODEL_API_KEY": "sk-env-key"}):
            from pdf_reader import config

            assert config.MODEL_API_KEY == "sk-env-key"
    pdf_reader.__dict__["config"] = original_config


def test_runtime_config_defaults(monkeypatch):
    from pdf_reader import config

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    upstream = config.build_upstream_runtime_config(_cfg())

    assert upstream.model.provider == "deepseek"
    assert upstream.model.api_key == "sk-test"
    assert upstream.model.send_temperature is False
    assert upstream.model.send_reasoning_effort is False
    assert upstream.translation.min_text_length == 5
    assert upstream.translation.qps == 4
    assert upstream.translation.pool_max_workers is None
    assert upstream.translation.term_qps is None
    assert upstream.translation.term_pool_max_workers is None
    assert upstream.translation.auto_extract_glossary is True
    assert upstream.translation.primary_font_family is None
    assert upstream.translation.default_system_prompt is None
    assert isinstance(upstream.pdf, config.Pdf2zhRuntimeConfig)
    assert upstream.term_extraction.enabled is True
    assert upstream.term_extraction.timeout == 30.0
    assert upstream.term_extraction.qps == 2
    assert upstream.term_extraction.max_workers == 1
    assert upstream.term_extraction.retry_count == 1
    assert upstream.term_extraction.max_input_chars == 80_000
    assert upstream.term_extraction.prompt is None


def test_runtime_config_parses_new_fields(monkeypatch):
    from pdf_reader import config

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    upstream = config.build_upstream_runtime_config(
        _cfg(
            model={
                "provider": "openai",
                "model": "gpt-4o-mini",
                "api_key": "sk-test",
                "temperature": "0.7",
                "send_temperature": True,
                "reasoning_effort": "high",
                "send_reasoning_effort": True,
                "timeout": "30.5",
            },
            translation={
                "min_text_length": 12,
                "qps": 7,
                "pool_max_workers": 3,
                "term_qps": 2,
                "term_pool_max_workers": 0,
                "auto_extract_glossary": False,
                "primary_font_family": "serif",
                "default_system_prompt": "/no_think default",
            },
            term_extraction={
                "enabled": False,
                "timeout": 60.0,
                "qps": 4,
                "max_workers": 2,
                "retry_count": 2,
                "max_input_chars": 200_000,
                "prompt": "custom prompt",
            },
        )
    )
    assert upstream.model.temperature == "0.7"
    assert upstream.model.send_temperature is True
    assert upstream.model.reasoning_effort == "high"
    assert upstream.model.send_reasoning_effort is True
    assert upstream.model.timeout == "30.5"
    assert upstream.translation.min_text_length == 12
    assert upstream.translation.qps == 7
    assert upstream.translation.pool_max_workers == 3
    assert upstream.translation.term_qps == 2
    assert upstream.translation.term_pool_max_workers == 0
    assert upstream.translation.auto_extract_glossary is False
    assert upstream.translation.primary_font_family == "serif"
    assert upstream.translation.default_system_prompt == "/no_think default"
    assert upstream.term_extraction.enabled is False
    assert upstream.term_extraction.timeout == 60.0
    assert upstream.term_extraction.qps == 4
    assert upstream.term_extraction.max_workers == 2
    assert upstream.term_extraction.retry_count == 2
    assert upstream.term_extraction.max_input_chars == 200_000
    assert upstream.term_extraction.prompt == "custom prompt"


def test_term_extraction_enabled_follows_legacy_when_section_absent(monkeypatch):
    from pdf_reader import config

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    upstream = config.build_upstream_runtime_config(_cfg(translation={"auto_extract_glossary": False}))
    assert upstream.term_extraction.enabled is False

    upstream = config.build_upstream_runtime_config(
        _cfg(
            translation={"auto_extract_glossary": False},
            term_extraction={"enabled": True},
        )
    )
    assert upstream.term_extraction.enabled is True


def test_term_extraction_section_present_takes_priority_over_legacy(monkeypatch):
    """规范 [term_extraction] 段存在时优先：省略 enabled 不回落旧键，显式值不被旧键覆盖。"""
    from pdf_reader import config

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    upstream = config.build_upstream_runtime_config(
        _cfg(
            translation={"auto_extract_glossary": False},
            term_extraction={"qps": 3},
        )
    )
    assert upstream.term_extraction.enabled is True
    assert upstream.term_extraction.qps == 3

    upstream = config.build_upstream_runtime_config(
        _cfg(
            translation={"auto_extract_glossary": True},
            term_extraction={"enabled": False},
        )
    )
    assert upstream.term_extraction.enabled is False


def test_legacy_translation_keys_emit_safe_migration_warnings(monkeypatch, caplog):
    """启动验证时三个 1.x 兼容键必须给出不含敏感值的 WARNING 与迁移提示。"""
    from pdf_reader import config

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    with caplog.at_level(logging.WARNING, logger="pdf_reader.config"):
        config.validate_startup_requirements(
            _cfg(
                translation={
                    "auto_extract_glossary": False,
                    "term_qps": 2,
                    "term_pool_max_workers": 0,
                }
            )
        )
    messages = [record.message for record in caplog.records if record.name == "pdf_reader.config"]
    joined = "\n".join(messages)
    assert "auto_extract_glossary" in joined
    assert "term_qps" in joined
    assert "term_pool_max_workers" in joined
    assert "1.x 兼容" in joined
    assert "2.0.0" in joined
    assert "[term_extraction].qps" in joined
    assert "[term_extraction].max_workers" in joined
    assert "sk-" not in joined


def test_no_legacy_warnings_without_legacy_keys(monkeypatch, caplog):
    from pdf_reader import config

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    with caplog.at_level(logging.WARNING, logger="pdf_reader.config"):
        config.validate_startup_requirements(_cfg())
    assert not any(record.name == "pdf_reader.config" and "兼容" in record.message for record in caplog.records)


def test_legacy_auto_extract_glossary_type_rejected(monkeypatch):
    from pdf_reader import config

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    with pytest.raises(config.ConfigError, match="auto_extract_glossary"):
        config.build_upstream_runtime_config(_cfg(translation={"auto_extract_glossary": "yes"}))


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("enabled", "yes", "布尔值"),
        ("timeout", True, "非布尔数值"),
        ("timeout", 0.5, "timeout"),
        ("timeout", 121.0, "timeout"),
        ("qps", 0, "qps"),
        ("qps", 101, "qps"),
        ("max_workers", 0, "max_workers"),
        ("max_workers", 9, "max_workers"),
        ("retry_count", -1, "retry_count"),
        ("retry_count", 4, "retry_count"),
        ("max_input_chars", 999, "max_input_chars"),
        ("max_input_chars", 1_000_001, "max_input_chars"),
        ("prompt", "   ", "prompt"),
    ],
)
def test_term_extraction_invalid_values_rejected(monkeypatch, key, value, message):
    from pdf_reader import config

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    with pytest.raises(config.ConfigError, match=message):
        config.build_upstream_runtime_config(_cfg(term_extraction={key: value}))


@pytest.mark.parametrize(
    ("key", "message"),
    [
        ("min_text_length", "必须是非布尔整数"),
        ("qps", "必须是不小于 1 的整数"),
        ("pool_max_workers", "必须是不小于 1 的整数"),
        ("term_qps", "必须是不小于 1 的整数"),
        ("term_pool_max_workers", "必须是不小于 0 的整数"),
    ],
)
def test_bool_cannot_imitate_int(monkeypatch, key, message):
    from pdf_reader import config

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    with pytest.raises(config.ConfigError, match=message):
        config.build_upstream_runtime_config(_cfg(translation={key: True}))


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("min_text_length", -1),
        ("qps", 0),
        ("pool_max_workers", 0),
        ("term_qps", 0),
        ("term_pool_max_workers", -1),
    ],
)
def test_range_rejected(monkeypatch, key, value):
    from pdf_reader import config

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    with pytest.raises(config.ConfigError):
        config.build_upstream_runtime_config(_cfg(translation={key: value}))


def test_primary_font_family_auto_maps_to_none_and_invalid_rejected(monkeypatch):
    from pdf_reader import config

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    upstream = config.build_upstream_runtime_config(_cfg(translation={"primary_font_family": "auto"}))
    assert upstream.translation.primary_font_family is None
    with pytest.raises(config.ConfigError, match="primary_font_family"):
        config.build_upstream_runtime_config(_cfg(translation={"primary_font_family": "comic-sans"}))


def test_default_system_prompt_blank_rejected(monkeypatch):
    from pdf_reader import config

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    with pytest.raises(config.ConfigError, match="default_system_prompt"):
        config.build_upstream_runtime_config(_cfg(translation={"default_system_prompt": "   "}))


def test_send_temperature_requires_temperature(monkeypatch):
    from pdf_reader import config

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    with pytest.raises(config.ConfigError, match="send_temperature"):
        config.build_upstream_runtime_config(_cfg(model={"provider": "openai", "send_temperature": True}))


def test_send_temperature_unsupported_provider_rejected(monkeypatch):
    from pdf_reader import config

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    with pytest.raises(config.ConfigError, match="send_temperature"):
        config.build_upstream_runtime_config(
            _cfg(model={"provider": "deepseek", "temperature": "0.5", "send_temperature": True})
        )


def test_send_reasoning_effort_requires_value(monkeypatch):
    from pdf_reader import config

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    with pytest.raises(config.ConfigError, match="send_reasoning_effort"):
        config.build_upstream_runtime_config(_cfg(model={"provider": "openai", "send_reasoning_effort": True}))


def test_send_reasoning_effort_unsupported_provider_rejected(monkeypatch):
    from pdf_reader import config

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    with pytest.raises(config.ConfigError, match="send_reasoning_effort"):
        config.build_upstream_runtime_config(
            _cfg(model={"provider": "zhipu", "reasoning_effort": "high", "send_reasoning_effort": True})
        )


def test_deepseek_reasoning_effort_only_high_or_max(monkeypatch):
    from pdf_reader import config

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    with pytest.raises(config.ConfigError, match="high/max"):
        config.build_upstream_runtime_config(_cfg(model={"reasoning_effort": "low"}))


def test_openai_reasoning_effort_enum_rejected(monkeypatch):
    from pdf_reader import config

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    with pytest.raises(config.ConfigError, match="minimal/low/medium/high"):
        config.build_upstream_runtime_config(_cfg(model={"provider": "openai", "reasoning_effort": "auto"}))


def test_openai_compatible_missing_base_url_rejected(monkeypatch):
    from pdf_reader import config

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    with pytest.raises(config.ConfigError, match="base_url 是 openai_compatible 必填项"):
        config.build_upstream_runtime_config(
            _cfg(model={"provider": "openai_compatible", "model": "m", "api_key": "sk-test"})
        )


def test_unknown_provider_rejected(monkeypatch):
    from pdf_reader import config

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    with pytest.raises(config.ConfigError, match="未知"):
        config.build_upstream_runtime_config(_cfg(model={"provider": "typo_provider"}))


def test_unknown_section_and_key_rejected(monkeypatch):
    from pdf_reader import config

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    bad_section = _cfg()
    bad_section["mystery"] = {}
    with pytest.raises(config.ConfigError, match="未知配置段"):
        config.validate_startup_requirements(bad_section)

    bad_key = _cfg(model={"send_temprature": True})
    with pytest.raises(config.ConfigError, match="未知字段"):
        config.validate_startup_requirements(bad_key)


def test_temperature_and_timeout_must_be_float_strings(monkeypatch):
    from pdf_reader import config

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    with pytest.raises(config.ConfigError, match="temperature"):
        config.build_upstream_runtime_config(_cfg(model={"provider": "openai", "temperature": "not-a-float"}))
    with pytest.raises(config.ConfigError, match="timeout"):
        config.build_upstream_runtime_config(_cfg(model={"provider": "openai", "timeout": "0"}))
    with pytest.raises(config.ConfigError, match="temperature"):
        config.build_upstream_runtime_config(_cfg(model={"provider": "openai", "temperature": 0.7}))


def test_model_runtime_config_repr_hides_api_key():
    from pdf_reader import config

    model_cfg = config.ModelRuntimeConfig(
        provider="openai",
        api_key="sk-super-secret-value",
        model="gpt-4o-mini",
    )
    assert "sk-super-secret-value" not in repr(model_cfg)
    assert "sk-super-secret-value" not in str(model_cfg)


def test_errors_never_include_api_key(monkeypatch):
    from pdf_reader import config

    monkeypatch.setenv("MODEL_API_KEY", "sk-super-secret-value")
    with pytest.raises(config.ConfigError) as excinfo:
        config.build_upstream_runtime_config(_cfg(model={"provider": "typo_provider"}))
    assert "sk-super-secret-value" not in str(excinfo.value)


def test_env_model_api_key_override_reaches_runtime_config(monkeypatch):
    from pdf_reader import config

    monkeypatch.setenv("MODEL_API_KEY", "sk-env-runtime")
    upstream = config.build_upstream_runtime_config(_cfg())
    assert upstream.model.api_key == "sk-env-runtime"


def test_build_app_settings_embeds_frozen_upstream(monkeypatch):
    from pdf_reader import config

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    settings = config.build_app_settings(
        _cfg(
            model={"provider": "openai", "model": "gpt-4o-mini", "api_key": "sk-test"},
            translation={"qps": 9, "min_text_length": 8},
        )
    )
    assert settings.upstream.model.provider == "openai"
    assert settings.upstream.model.api_key == "sk-test"
    assert settings.upstream.translation.qps == 9
    assert settings.upstream.translation.min_text_length == 8


def test_build_app_settings_lenient_without_config(monkeypatch):
    """无 config.toml 的环境（CI/测试）仍可装配 AppSettings；生产启动由 main 严格校验。"""
    from pdf_reader import config

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("PDF_READER_DEBUG", raising=False)
    settings = config.build_app_settings({})
    assert settings.upstream.model.provider == "openai_compatible"
    assert settings.upstream.model.model == ""
    assert settings.upstream.model.api_key == ""
    assert settings.upstream.translation.min_text_length == 5
    assert settings.upstream.translation.qps == 4
    assert settings.upstream.translation.auto_extract_glossary is True


def test_build_app_settings_reuses_provided_upstream_without_reparse(monkeypatch):
    from pdf_reader import config

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    upstream = config.build_upstream_runtime_config(_cfg())
    run_cfg = config.ServerConfig()

    with patch.object(
        config,
        "build_upstream_runtime_config",
        wraps=config.build_upstream_runtime_config,
    ) as spy:
        settings = config.build_app_settings(_cfg(), run_cfg=run_cfg, upstream=upstream)

    spy.assert_not_called()
    assert settings.upstream is upstream
    assert settings.model_provider == upstream.model.provider
    assert settings.model == upstream.model.model
    assert settings.lang_in == upstream.translation.lang_in
    assert settings.lang_out == upstream.translation.lang_out


def test_build_app_settings_derives_values_from_upstream_only(monkeypatch):
    """model_provider/model/lang 必须来自冻结 upstream，不能与 raw section 两套漂移。"""
    from pdf_reader import config

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    upstream = config.build_upstream_runtime_config(
        _cfg(
            model={"provider": "openai", "model": "gpt-4o-mini"},
            translation={"lang_in": "ja", "lang_out": "ko"},
        )
    )
    raw = _cfg(
        model={"provider": "zhipu", "model": "zhipu-ai"},
        translation={"lang_in": "en", "lang_out": "zh"},
    )

    settings = config.build_app_settings(raw, run_cfg=config.ServerConfig(), upstream=upstream)

    assert settings.model_provider == "openai"
    assert settings.model == "gpt-4o-mini"
    assert settings.lang_in == "ja"
    assert settings.lang_out == "ko"
    assert settings.upstream is upstream


def test_pdf2zh_runtime_defaults(monkeypatch):
    from pdf_reader import config

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    pdf = config.build_upstream_runtime_config(_cfg()).pdf
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
    assert pdf.formula_font_pattern is None
    assert pdf.formula_char_pattern is None


def test_pdf2zh_runtime_parses_all_fields(monkeypatch):
    from pdf_reader import config

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    pdf = config.build_upstream_runtime_config(
        _cfg(
            pdf2zh={
                "split_short_lines": True,
                "short_line_split_factor": 0.5,
                "skip_clean": True,
                "disable_rich_text_translate": True,
                "enhance_compatibility": True,
                "translate_table_text": False,
                "skip_scanned_detection": True,
                "ocr_workaround": True,
                "auto_enable_ocr_workaround": True,
                "no_merge_alternating_line_numbers": True,
                "skip_formula_offset_calculation": True,
                "non_formula_line_iou_threshold": 0.4,
                "figure_table_protection_threshold": 0.6,
                "formula_font_pattern": "^math",
                "formula_char_pattern": "\\d+",
            }
        )
    ).pdf
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
    assert pdf.formula_font_pattern == "^math"
    assert pdf.formula_char_pattern == "\\d+"


@pytest.mark.parametrize(
    "key",
    [
        "split_short_lines",
        "skip_clean",
        "disable_rich_text_translate",
        "enhance_compatibility",
        "translate_table_text",
        "skip_scanned_detection",
        "ocr_workaround",
        "auto_enable_ocr_workaround",
        "no_merge_alternating_line_numbers",
        "skip_formula_offset_calculation",
    ],
)
def test_pdf2zh_bool_fields_reject_numbers(monkeypatch, key):
    from pdf_reader import config

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    with pytest.raises(config.ConfigError, match="必须是布尔值"):
        config.build_upstream_runtime_config(_cfg(pdf2zh={key: 1}))


def test_pdf2zh_float_fields_reject_bool(monkeypatch):
    from pdf_reader import config

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    for key in (
        "short_line_split_factor",
        "non_formula_line_iou_threshold",
        "figure_table_protection_threshold",
    ):
        with pytest.raises(config.ConfigError, match="必须是非布尔数值"):
            config.build_upstream_runtime_config(_cfg(pdf2zh={key: True}))


def test_pdf2zh_float_ranges_enforced(monkeypatch):
    from pdf_reader import config

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    with pytest.raises(config.ConfigError, match="short_line_split_factor"):
        config.build_upstream_runtime_config(_cfg(pdf2zh={"short_line_split_factor": 0.09}))
    config.build_upstream_runtime_config(_cfg(pdf2zh={"short_line_split_factor": 0.1}))

    for key in ("non_formula_line_iou_threshold", "figure_table_protection_threshold"):
        with pytest.raises(config.ConfigError, match=key):
            config.build_upstream_runtime_config(_cfg(pdf2zh={key: -0.01}))
        with pytest.raises(config.ConfigError, match=key):
            config.build_upstream_runtime_config(_cfg(pdf2zh={key: 1.01}))
        config.build_upstream_runtime_config(_cfg(pdf2zh={key: 0.0}))
        config.build_upstream_runtime_config(_cfg(pdf2zh={key: 1.0}))


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("formula_font_pattern", "["),
        ("formula_char_pattern", "("),
        ("formula_font_pattern", ""),
        ("formula_char_pattern", "   "),
        ("formula_font_pattern", 123),
    ],
)
def test_pdf2zh_pattern_invalid_rejected(monkeypatch, key, value):
    from pdf_reader import config

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    with pytest.raises(config.ConfigError, match=key):
        config.build_upstream_runtime_config(_cfg(pdf2zh={key: value}))


@pytest.mark.parametrize(
    "key",
    [
        "pages",
        "no_dual",
        "no_mono",
        "only_include_translated_page",
        "watermark_output_mode",
        "max_pages_per_part",
        "use_alternating_pages_dual",
        "dual_translate_first",
    ],
)
def test_pdf2zh_structural_fields_are_not_exposed(monkeypatch, key):
    from pdf_reader import config

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    with pytest.raises(config.ConfigError, match="未知字段"):
        config.validate_startup_requirements(_cfg(pdf2zh={key: True}))


def test_pdf2zh_section_must_be_table(monkeypatch):
    from pdf_reader import config

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    bad = _cfg()
    bad["pdf2zh"] = "bad"
    with pytest.raises(config.ConfigError, match=r"\[pdf2zh\] 必须是 TOML table"):
        config.build_upstream_runtime_config(bad)


def test_validate_startup_requirements_rejects_bad_pdf2zh(monkeypatch):
    from pdf_reader import config

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    with pytest.raises(config.ConfigError, match="formula_font_pattern"):
        config.validate_startup_requirements(_cfg(pdf2zh={"formula_font_pattern": "["}))


def test_lenient_pdf2zh_fallback_uses_safe_defaults(monkeypatch):
    from pdf_reader import config

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("PDF_READER_DEBUG", raising=False)
    settings = config.build_app_settings(
        _cfg(
            pdf2zh={
                "short_line_split_factor": True,
                "non_formula_line_iou_threshold": 5,
                "figure_table_protection_threshold": -1,
                "formula_font_pattern": "[",
                "formula_char_pattern": "",
                "skip_clean": True,
                "translate_table_text": False,
            }
        )
    )
    pdf = settings.upstream.pdf
    assert pdf.short_line_split_factor == 0.8
    assert pdf.non_formula_line_iou_threshold == 0.9
    assert pdf.figure_table_protection_threshold == 0.9
    assert pdf.formula_font_pattern is None
    assert pdf.formula_char_pattern is None
    assert pdf.skip_clean is True
    assert pdf.translate_table_text is False


@pytest.mark.parametrize(
    "key",
    [
        "short_line_split_factor",
        "non_formula_line_iou_threshold",
        "figure_table_protection_threshold",
    ],
)
@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), float("-inf")])
def test_pdf2zh_float_rejects_non_finite(monkeypatch, key, bad_value):
    from pdf_reader import config

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    with pytest.raises(config.ConfigError, match="有限数值"):
        config.build_upstream_runtime_config(_cfg(pdf2zh={key: bad_value}))


def test_lenient_pdf2zh_non_finite_falls_back_to_defaults(monkeypatch):
    from pdf_reader import config

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("PDF_READER_DEBUG", raising=False)
    settings = config.build_app_settings(
        _cfg(
            pdf2zh={
                "short_line_split_factor": float("nan"),
                "non_formula_line_iou_threshold": float("inf"),
                "figure_table_protection_threshold": float("-inf"),
                "skip_clean": True,
            }
        )
    )
    pdf = settings.upstream.pdf
    assert pdf.short_line_split_factor == 0.8
    assert pdf.non_formula_line_iou_threshold == 0.9
    assert pdf.figure_table_protection_threshold == 0.9
    assert pdf.skip_clean is True


@pytest.mark.parametrize("bad_value", ["nan", "inf", "-inf"])
def test_model_temperature_rejects_non_finite(monkeypatch, bad_value):
    from pdf_reader import config

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    with pytest.raises(config.ConfigError, match="temperature"):
        config.build_upstream_runtime_config(_cfg(model={"provider": "openai", "temperature": bad_value}))


@pytest.mark.parametrize("bad_value", ["nan", "inf", "-inf"])
def test_model_timeout_rejects_non_finite(monkeypatch, bad_value):
    from pdf_reader import config

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    with pytest.raises(config.ConfigError, match="timeout"):
        config.build_upstream_runtime_config(_cfg(model={"provider": "openai", "timeout": bad_value}))


def test_model_temperature_allows_negative_finite_value(monkeypatch):
    """temperature 只要求有限且可解析，不武断增加范围。"""
    from pdf_reader import config

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    upstream = config.build_upstream_runtime_config(_cfg(model={"provider": "openai", "temperature": "-1.5"}))
    assert upstream.model.temperature == "-1.5"


def test_lenient_model_non_finite_temperature_timeout_fall_back_to_none(monkeypatch):
    from pdf_reader import config

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("PDF_READER_DEBUG", raising=False)
    settings = config.build_app_settings(
        _cfg(
            model={
                "provider": "openai",
                "temperature": "nan",
                "timeout": "inf",
            }
        )
    )
    assert settings.upstream.model.temperature is None
    assert settings.upstream.model.timeout is None

    valid = config.build_app_settings(
        _cfg(
            model={
                "provider": "openai",
                "temperature": "0.5",
                "timeout": "30",
            }
        )
    )
    assert valid.upstream.model.temperature == "0.5"
    assert valid.upstream.model.timeout == "30"
