import tempfile
from pathlib import Path

import pymupdf
import pytest

import config
from services import build_settings, render_page, sha256


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
    settings = build_settings("dummy.pdf")
    assert settings.translation.lang_in == "en"
    assert settings.translation.lang_out == "zh"
    assert settings.translation.ignore_cache is True

def test_build_settings_with_prompt(mock_config):
    settings = build_settings("dummy.pdf", "translate waveguide as 波导")
    assert settings.translation.custom_system_prompt == "translate waveguide as 波导"

def test_build_settings_with_output_dir(mock_config):
    settings = build_settings("dummy.pdf", output_dir="/tmp/translate_output")
    assert settings.translation.output == "/tmp/translate_output"

def test_build_settings_without_output_dir(mock_config):
    settings = build_settings("dummy.pdf")
    assert getattr(settings.translation, "output", None) is None


def test_config_provider_map_has_deepseek():
    assert "deepseek" in config.PROVIDER_MAP
    assert config.PROVIDER_MAP["deepseek"].__name__ == "DeepSeekSettings"


def test_config_field_map_api_key_exists():
    assert "DeepSeekSettings" in config.FIELD_MAP["api_key"]
    assert config.FIELD_MAP["api_key"]["DeepSeekSettings"] == "deepseek_api_key"


def test_resolve_engine_deepseek(mock_config, monkeypatch):
    monkeypatch.setattr(config, "MODEL_PROVIDER", "deepseek")
    from pdf2zh_next.config.translate_engine_model import DeepSeekSettings

    from services import resolve_engine
    assert resolve_engine("deepseek") is DeepSeekSettings


def test_resolve_engine_unknown_fallback(mock_config, monkeypatch):
    monkeypatch.setattr(config, "MODEL_PROVIDER", "nonexistent")
    from pdf2zh_next.config.translate_engine_model import OpenAICompatibleSettings

    from services import resolve_engine
    assert resolve_engine("nonexistent") is OpenAICompatibleSettings


def test_build_engine_kwargs_deepseek(mock_config, monkeypatch):
    monkeypatch.setattr(config, "MODEL_API_KEY", "sk-test")
    monkeypatch.setattr(config, "MODEL", "deepseek-chat")
    monkeypatch.setattr(config, "MODEL_BASE_URL", "https://api.deepseek.com/v1")
    from pdf2zh_next.config.translate_engine_model import DeepSeekSettings

    from services import build_engine_kwargs
    kwargs = build_engine_kwargs(DeepSeekSettings)
    assert kwargs["deepseek_api_key"] == "sk-test"
    assert kwargs["deepseek_model"] == "deepseek-chat"


def test_build_engine_kwargs_zhipu_ignores_thinking_mode(mock_config, monkeypatch):
    monkeypatch.setattr(config, "MODEL_THINKING_MODE", "enabled")
    from pdf2zh_next.config.translate_engine_model import ZhipuSettings

    from services import build_engine_kwargs
    kwargs = build_engine_kwargs(ZhipuSettings)
    assert "zhipu_thinking_mode" not in kwargs


def test_build_engine_kwargs_missing_api_key_raises(mock_config, monkeypatch):
    monkeypatch.setattr(config, "MODEL_API_KEY", None)
    monkeypatch.setattr(config, "MODEL", "some-model")
    from pdf2zh_next.config.translate_engine_model import DeepSeekSettings

    from services import build_engine_kwargs
    with pytest.raises(RuntimeError, match="未配置"):
        build_engine_kwargs(DeepSeekSettings)


def test_build_settings_deepseek_with_thinking(mock_config, monkeypatch):
    monkeypatch.setattr(config, "MODEL_PROVIDER", "deepseek")
    monkeypatch.setattr(config, "MODEL_THINKING_MODE", "enabled")
    monkeypatch.setattr(config, "MODEL_REASONING_EFFORT", "high")
    from pdf2zh_next.config.translate_engine_model import DeepSeekSettings

    settings = build_settings("dummy.pdf")
    engine = settings.translate_engine_settings

    assert isinstance(engine, DeepSeekSettings)
    assert engine.deepseek_api_key == "sk-test-key"
    assert engine.deepseek_model == "deepseek-v4-flash"
    assert engine.deepseek_thinking_mode == "enabled"
    assert engine.deepseek_reasoning_effort == "high"


def test_build_settings_unknown_provider(mock_config, monkeypatch):
    monkeypatch.setattr(config, "MODEL_PROVIDER", "some_custom_gateway")
    monkeypatch.setattr(config, "MODEL_API_KEY", "sk-custom")
    monkeypatch.setattr(config, "MODEL", "custom-model")
    monkeypatch.setattr(config, "MODEL_BASE_URL", "https://custom.api/v1")
    from pdf2zh_next.config.translate_engine_model import OpenAICompatibleSettings

    settings = build_settings("dummy.pdf")
    engine = settings.translate_engine_settings

    assert isinstance(engine, OpenAICompatibleSettings)
    assert engine.openai_compatible_api_key == "sk-custom"
    assert engine.openai_compatible_model == "custom-model"
    assert engine.openai_compatible_base_url == "https://custom.api/v1"


def test_build_settings_unsupported_field_ignored(mock_config, monkeypatch):
    monkeypatch.setattr(config, "MODEL_PROVIDER", "zhipu")
    monkeypatch.setattr(config, "MODEL_THINKING_MODE", "enabled")
    monkeypatch.setattr(config, "MODEL_TEMPERATURE", "0.5")
    from pdf2zh_next.config.translate_engine_model import ZhipuSettings

    settings = build_settings("dummy.pdf")
    engine = settings.translate_engine_settings

    assert isinstance(engine, ZhipuSettings)
    assert engine.zhipu_api_key == "sk-test-key"
    assert engine.zhipu_model == "deepseek-v4-flash"
    assert not hasattr(engine, "zhipu_thinking_mode")
    assert not hasattr(engine, "zhipu_temperature")


def test_build_settings_missing_api_key_raises(mock_config, monkeypatch):
    monkeypatch.setattr(config, "MODEL_API_KEY", None)
    with pytest.raises(RuntimeError, match="未配置"):
        build_settings("dummy.pdf")
