"""等价回归基线：对所有 10 引擎，新旧路径产出一致"""
import config
from services import resolve_engine, build_engine_kwargs
from unittest.mock import MagicMock


ALL_PROVIDERS = [
    "deepseek",
    "zhipu",
    "siliconflow",
    "aliyun",
    "gemini",
    "groq",
    "grok",
    "modelscope",
    "openai",
    "openai_compatible",
]


def test_all_providers_resolve_to_correct_class():
    for provider in ALL_PROVIDERS:
        spec = resolve_engine(provider)
        expected = config.PROVIDER_INDEX[provider].settings_cls
        assert spec.settings_cls is expected, (
            f"resolve_engine('{provider}') → {spec.settings_cls.__name__}, "
            f"expected {expected.__name__}"
        )


def test_unknown_provider_falls_back_to_openai_compatible():
    spec = resolve_engine("nonexistent_provider_xyz")
    from pdf2zh_next.config.translate_engine_model import OpenAICompatibleSettings
    assert spec.settings_cls is OpenAICompatibleSettings


def test_all_engines_build_kwargs_structure(monkeypatch):
    monkeypatch.setattr(config, "MODEL_API_KEY", "sk-test-key")
    monkeypatch.setattr(config, "MODEL", "test-model")
    monkeypatch.setattr(config, "MODEL_BASE_URL", "https://test.api/v1")
    monkeypatch.setattr(config, "MODEL_THINKING_MODE", "enabled")
    monkeypatch.setattr(config, "MODEL_REASONING_EFFORT", "high")
    monkeypatch.setattr(config, "MODEL_ENABLE_JSON_MODE", "true")
    monkeypatch.setattr(config, "MODEL_TEMPERATURE", "0.3")
    monkeypatch.setattr(config, "MODEL_TIMEOUT", "60")

    for provider in ALL_PROVIDERS:
        spec = resolve_engine(provider)
        kwargs = build_engine_kwargs(spec)
        assert isinstance(kwargs, dict), (
            f"build_engine_kwargs({spec.settings_cls.__name__}) returned {type(kwargs)}"
        )
        engine_name = spec.settings_cls.__name__
        api_field = spec.field_map.get("api_key", "")
        model_field = spec.field_map.get("model", "")
        assert api_field, f"{engine_name}: no api_key in field_map"
        assert kwargs[api_field] == "sk-test-key", (
            f"{engine_name}: expected api_key at '{api_field}'"
        )
        assert kwargs[model_field] == "test-model", (
            f"{engine_name}: expected model at '{model_field}'"
        )


# Migration-equivalence snapshot of the original FIELD_MAP that was
# once defined in config.py and later deleted in favour of EngineSpec.
# Preserved here so the old-code path can still be compared against the
# production path in test_new_path_matches_old_path.
_OLD_FIELD_MAP = {
    "api_key": {
        "DeepSeekSettings": "deepseek_api_key",
        "ZhipuSettings": "zhipu_api_key",
        "SiliconFlowSettings": "siliconflow_api_key",
        "AliyunDashScopeSettings": "aliyun_dashscope_api_key",
        "GeminiSettings": "gemini_api_key",
        "GroqSettings": "groq_api_key",
        "GrokSettings": "grok_api_key",
        "ModelScopeSettings": "modelscope_api_key",
        "OpenAISettings": "openai_api_key",
        "OpenAICompatibleSettings": "openai_compatible_api_key",
    },
    "model": {
        "DeepSeekSettings": "deepseek_model",
        "ZhipuSettings": "zhipu_model",
        "SiliconFlowSettings": "siliconflow_model",
        "AliyunDashScopeSettings": "aliyun_dashscope_model",
        "GeminiSettings": "gemini_model",
        "GroqSettings": "groq_model",
        "GrokSettings": "grok_model",
        "ModelScopeSettings": "modelscope_model",
        "OpenAISettings": "openai_model",
        "OpenAICompatibleSettings": "openai_compatible_model",
    },
    "base_url": {
        "SiliconFlowSettings": "siliconflow_base_url",
        "AliyunDashScopeSettings": "aliyun_dashscope_base_url",
        "OpenAISettings": "openai_base_url",
        "OpenAICompatibleSettings": "openai_compatible_base_url",
    },
    "thinking_mode": {
        "DeepSeekSettings": "deepseek_thinking_mode",
    },
    "reasoning_effort": {
        "DeepSeekSettings": "deepseek_reasoning_effort",
        "OpenAISettings": "openai_reasoning_effort",
        "OpenAICompatibleSettings": "openai_compatible_reasoning_effort",
    },
    "enable_json_mode": {
        "DeepSeekSettings": "deepseek_enable_json_mode",
        "ZhipuSettings": "zhipu_enable_json_mode",
        "SiliconFlowSettings": "siliconflow_enable_json_mode",
        "GeminiSettings": "gemini_enable_json_mode",
        "GroqSettings": "groq_enable_json_mode",
        "GrokSettings": "grok_enable_json_mode",
        "ModelScopeSettings": "modelscope_enable_json_mode",
        "OpenAISettings": "openai_enable_json_mode",
        "OpenAICompatibleSettings": "openai_compatible_enable_json_mode",
    },
    "temperature": {
        "OpenAISettings": "openai_temperature",
        "AliyunDashScopeSettings": "aliyun_dashscope_temperature",
        "OpenAICompatibleSettings": "openai_compatible_temperature",
    },
    "timeout": {
        "OpenAISettings": "openai_timeout",
        "AliyunDashScopeSettings": "aliyun_dashscope_timeout",
        "OpenAICompatibleSettings": "openai_compatible_timeout",
    },
}


def test_engine_registry_covers_all_providers():
    settings_to_provider = {
        spec.settings_cls.__name__: spec.provider
        for spec in config.PROVIDER_INDEX.values()
    }
    expected_providers = {
        settings_to_provider[name]
        for name in _OLD_FIELD_MAP["api_key"]
    }
    registry_providers = set(config.PROVIDER_INDEX.keys())
    assert registry_providers == expected_providers, (
        f"Provider mismatch: registry={sorted(registry_providers)}, "
        f"expected from _OLD_FIELD_MAP={sorted(expected_providers)}"
    )


def _old_build_engine_kwargs(engine_cls):
    engine_fields = engine_cls.model_fields
    engine_name = engine_cls.__name__
    kwargs = {}
    for unified_name in ("api_key", "model", "base_url", "thinking_mode",
                         "reasoning_effort", "enable_json_mode",
                         "temperature", "timeout"):
        config_attr_name = "MODEL" if unified_name == "model" else f"MODEL_{unified_name.upper()}"
        value = getattr(config, config_attr_name, None)
        engine_field = _OLD_FIELD_MAP.get(unified_name, {}).get(engine_name)
        if engine_field is None:
            if value is not None and unified_name not in ("api_key", "model", "base_url"):
                continue
            continue
        if engine_field not in engine_fields:
            continue
        if value is not None:
            kwargs[engine_field] = value
        elif unified_name in ("api_key", "model"):
            raise RuntimeError(f"model.{unified_name} 未配置")
        elif unified_name == "base_url":
            pass
    return kwargs


def test_new_path_matches_old_path(monkeypatch):
    monkeypatch.setattr(config, "MODEL_API_KEY", "sk-test-key")
    monkeypatch.setattr(config, "MODEL", "test-model")
    monkeypatch.setattr(config, "MODEL_BASE_URL", "https://test.api/v1")
    monkeypatch.setattr(config, "MODEL_THINKING_MODE", "enabled")
    monkeypatch.setattr(config, "MODEL_REASONING_EFFORT", "high")
    monkeypatch.setattr(config, "MODEL_ENABLE_JSON_MODE", "true")
    monkeypatch.setattr(config, "MODEL_TEMPERATURE", "0.3")
    monkeypatch.setattr(config, "MODEL_TIMEOUT", "60")

    for provider, spec in config.PROVIDER_INDEX.items():
        old_kwargs = _old_build_engine_kwargs(spec.settings_cls)
        new_kwargs = build_engine_kwargs(spec)
        assert old_kwargs == new_kwargs, (
            f"{provider}: old={old_kwargs} != new={new_kwargs}"
        )


def test_fake_engine_extensibility(monkeypatch):
    fake_settings_cls = MagicMock()
    fake_settings_cls.__name__ = "FakeEngineSettings"
    fake_settings_cls.model_fields = {
        "fake_api_key": MagicMock(),
        "fake_model": MagicMock(),
    }

    fake_spec = config.EngineSpec(
        provider="fake",
        settings_cls=fake_settings_cls,
        field_map={
            "api_key": "fake_api_key",
            "model": "fake_model",
        },
        required_fields=("api_key", "model"),
    )

    monkeypatch.setattr(config, "MODEL_API_KEY", "sk-fake-key")
    monkeypatch.setattr(config, "MODEL", "fake-model-v1")

    kwargs = build_engine_kwargs(fake_spec)

    assert kwargs == {
        "fake_api_key": "sk-fake-key",
        "fake_model": "fake-model-v1",
    }


def test_fake_engine_optional_field_warns(monkeypatch, caplog):
    import logging
    caplog.set_level(logging.WARNING)

    fake_settings_cls = MagicMock()
    fake_settings_cls.__name__ = "MinimalEngineSettings"
    fake_settings_cls.model_fields = {
        "minimal_key": MagicMock(),
        "minimal_model": MagicMock(),
    }

    fake_spec = config.EngineSpec(
        provider="minimal",
        settings_cls=fake_settings_cls,
        field_map={
            "api_key": "minimal_key",
            "model": "minimal_model",
            "temperature": "nonexistent_field",
        },
        required_fields=("api_key", "model"),
    )

    monkeypatch.setattr(config, "MODEL_API_KEY", "sk-minimal")
    monkeypatch.setattr(config, "MODEL", "minimal-model")
    monkeypatch.setattr(config, "MODEL_TEMPERATURE", "0.5")

    kwargs = build_engine_kwargs(fake_spec)

    assert kwargs["minimal_key"] == "sk-minimal"
    assert kwargs["minimal_model"] == "minimal-model"
    assert any("不支持字段" in record.message for record in caplog.records)
