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

def test_build_settings_basic():
    settings = build_settings("dummy.pdf")
    assert settings.translation.lang_in == "en"
    assert settings.translation.lang_out == "zh"
    assert settings.translation.ignore_cache is True

def test_build_settings_with_prompt():
    settings = build_settings("dummy.pdf", "translate waveguide as 波导")
    assert settings.translation.custom_system_prompt == "translate waveguide as 波导"

def test_build_settings_with_output_dir():
    settings = build_settings("dummy.pdf", output_dir="/tmp/translate_output")
    assert settings.translation.output == "/tmp/translate_output"

def test_build_settings_without_output_dir():
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
    from services import resolve_engine
    from pdf2zh_next.config.translate_engine_model import DeepSeekSettings
    assert resolve_engine("deepseek") is DeepSeekSettings


def test_resolve_engine_unknown_fallback(mock_config, monkeypatch):
    monkeypatch.setattr(config, "MODEL_PROVIDER", "nonexistent")
    from services import resolve_engine
    from pdf2zh_next.config.translate_engine_model import OpenAICompatibleSettings
    assert resolve_engine("nonexistent") is OpenAICompatibleSettings


def test_build_engine_kwargs_deepseek(mock_config, monkeypatch):
    monkeypatch.setattr(config, "MODEL_API_KEY", "sk-test")
    monkeypatch.setattr(config, "MODEL", "deepseek-chat")
    monkeypatch.setattr(config, "MODEL_BASE_URL", "https://api.deepseek.com/v1")
    from services import build_engine_kwargs
    from pdf2zh_next.config.translate_engine_model import DeepSeekSettings
    kwargs = build_engine_kwargs(DeepSeekSettings)
    assert kwargs["deepseek_api_key"] == "sk-test"
    assert kwargs["deepseek_model"] == "deepseek-chat"


def test_build_engine_kwargs_zhipu_ignores_thinking_mode(mock_config, monkeypatch):
    monkeypatch.setattr(config, "MODEL_THINKING_MODE", "enabled")
    from services import build_engine_kwargs
    from pdf2zh_next.config.translate_engine_model import ZhipuSettings
    kwargs = build_engine_kwargs(ZhipuSettings)
    assert "zhipu_thinking_mode" not in kwargs


def test_build_engine_kwargs_missing_api_key_raises(mock_config, monkeypatch):
    monkeypatch.setattr(config, "MODEL_API_KEY", None)
    monkeypatch.setattr(config, "MODEL", "some-model")
    from services import build_engine_kwargs
    from pdf2zh_next.config.translate_engine_model import DeepSeekSettings
    with pytest.raises(RuntimeError, match="未配置"):
        build_engine_kwargs(DeepSeekSettings)
