"""等价回归基线：对所有 10 引擎，新旧路径产出一致"""

from unittest.mock import MagicMock

import pytest

from pdf_reader import config
from pdf_reader.engine_resolver import build_engine_kwargs, resolve_engine

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


def _model_cfg(**overrides: object) -> config.ModelRuntimeConfig:
    values: dict = {
        "provider": "deepseek",
        "api_key": "sk-test-key",
        "model": "test-model",
        "base_url": None,
        "thinking_mode": None,
        "reasoning_effort": None,
        "send_reasoning_effort": False,
        "enable_json_mode": None,
        "temperature": None,
        "send_temperature": False,
        "timeout": None,
    }
    values.update(overrides)
    return config.ModelRuntimeConfig(**values)


def test_all_providers_resolve_to_correct_class(mock_config):
    for provider in ALL_PROVIDERS:
        spec = resolve_engine(provider)
        expected = config.PROVIDER_INDEX[provider].settings_cls
        assert spec.settings_cls is expected, (
            f"resolve_engine('{provider}') → {spec.settings_cls.__name__}, expected {expected.__name__}"
        )


def test_unknown_provider_raises(mock_config):
    with pytest.raises(config.ConfigError, match="未知 Provider"):
        resolve_engine("nonexistent_provider_xyz")


def test_aliyun_enable_json_mode_is_mapped():
    """aliyun field_map 必须映射 enable_json_mode，且值能透传到 engine_kwargs。"""
    spec = resolve_engine("aliyun")
    assert "enable_json_mode" in spec.field_map, "aliyun field_map 漏映射 enable_json_mode"
    model_cfg = _model_cfg(provider="aliyun", model="qwen-plus-latest", enable_json_mode=True)
    kwargs = build_engine_kwargs(spec, model_cfg)
    assert kwargs.get("aliyun_dashscope_enable_json_mode") is True


def test_all_engines_build_kwargs_structure():
    model_cfg = _model_cfg(
        base_url="https://test.api/v1",
        thinking_mode="enabled",
        reasoning_effort="high",
        enable_json_mode=True,
        temperature="0.3",
        timeout="60",
    )

    for provider in ALL_PROVIDERS:
        spec = resolve_engine(provider)
        kwargs = build_engine_kwargs(spec, model_cfg)
        assert isinstance(kwargs, dict), f"build_engine_kwargs({spec.settings_cls.__name__}) returned {type(kwargs)}"
        engine_name = spec.settings_cls.__name__
        api_field = spec.field_map.get("api_key", "")
        model_field = spec.field_map.get("model", "")
        assert api_field, f"{engine_name}: no api_key in field_map"
        assert kwargs[api_field] == "sk-test-key", f"{engine_name}: expected api_key at '{api_field}'"
        assert kwargs[model_field] == "test-model", f"{engine_name}: expected model at '{model_field}'"


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
        "AliyunDashScopeSettings": "aliyun_dashscope_enable_json_mode",
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
    settings_to_provider = {spec.settings_cls.__name__: spec.provider for spec in config.PROVIDER_INDEX.values()}
    expected_providers = {settings_to_provider[name] for name in _OLD_FIELD_MAP["api_key"]}
    registry_providers = set(config.PROVIDER_INDEX.keys())
    assert registry_providers == expected_providers, (
        f"Provider mismatch: registry={sorted(registry_providers)}, "
        f"expected from _OLD_FIELD_MAP={sorted(expected_providers)}"
    )


def _old_build_engine_kwargs(engine_cls) -> dict:
    engine_fields = engine_cls.model_fields
    engine_name = engine_cls.__name__
    kwargs = {}
    for unified_name in (
        "api_key",
        "model",
        "base_url",
        "thinking_mode",
        "reasoning_effort",
        "enable_json_mode",
        "temperature",
        "timeout",
    ):
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
    monkeypatch.setattr(config, "MODEL_ENABLE_JSON_MODE", True)
    monkeypatch.setattr(config, "MODEL_TEMPERATURE", "0.3")
    monkeypatch.setattr(config, "MODEL_TIMEOUT", "60")
    model_cfg = _model_cfg(
        base_url="https://test.api/v1",
        thinking_mode="enabled",
        reasoning_effort="high",
        enable_json_mode=True,
        temperature="0.3",
        timeout="60",
    )

    for provider, spec in config.PROVIDER_INDEX.items():
        old_kwargs = _old_build_engine_kwargs(spec.settings_cls)
        new_kwargs = build_engine_kwargs(spec, model_cfg)
        assert old_kwargs == new_kwargs, f"{provider}: old={old_kwargs} != new={new_kwargs}"


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

    model_cfg = _model_cfg(provider="fake", api_key="sk-fake-key", model="fake-model-v1")
    kwargs = build_engine_kwargs(fake_spec, model_cfg)

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

    model_cfg = _model_cfg(
        provider="minimal",
        api_key="sk-minimal",
        model="minimal-model",
        temperature="0.5",
    )
    kwargs = build_engine_kwargs(fake_spec, model_cfg)

    assert kwargs["minimal_key"] == "sk-minimal"
    assert kwargs["minimal_model"] == "minimal-model"
    assert any("不支持字段" in record.message for record in caplog.records)


def test_build_engine_kwargs_missing_model_fields_fails_fast():
    """settings_cls 缺 model_fields 时保持直接属性访问，必须抛 AttributeError。"""
    no_fields_cls = type("NoFields", (), {})
    spec = config.EngineSpec(
        provider="no-fields",
        settings_cls=no_fields_cls,
        field_map={"model": "model"},
        required_fields=("model",),
    )
    with pytest.raises(AttributeError):
        build_engine_kwargs(spec, _model_cfg(model="m"))


def test_openai_send_temperature_maps_to_historical_temprature_field():
    """OpenAI 上游 2.9.0 使用历史拼写 openai_send_temprature，契约测试必须锁死。"""
    spec = resolve_engine("openai")
    model_cfg = _model_cfg(
        provider="openai",
        temperature="0.7",
        send_temperature=True,
    )
    kwargs = build_engine_kwargs(spec, model_cfg)
    assert kwargs["openai_send_temprature"] is True
    assert kwargs["openai_temperature"] == "0.7"


def test_openai_send_reasoning_effort_mapped():
    spec = resolve_engine("openai")
    model_cfg = _model_cfg(
        provider="openai",
        reasoning_effort="high",
        send_reasoning_effort=True,
    )
    kwargs = build_engine_kwargs(spec, model_cfg)
    assert kwargs["openai_send_reasoning_effort"] is True
    assert kwargs["openai_reasoning_effort"] == "high"


def test_openai_compatible_send_switches_mapped():
    spec = resolve_engine("openai_compatible")
    model_cfg = _model_cfg(
        provider="openai_compatible",
        base_url="https://example.com/v1",
        temperature="0.2",
        send_temperature=True,
        reasoning_effort="low",
        send_reasoning_effort=True,
    )
    kwargs = build_engine_kwargs(spec, model_cfg)
    assert kwargs["openai_compatible_send_temperature"] is True
    assert kwargs["openai_compatible_send_reasoning_effort"] is True


def test_aliyun_send_temperature_mapped():
    spec = resolve_engine("aliyun")
    model_cfg = _model_cfg(
        provider="aliyun",
        temperature="0.5",
        send_temperature=True,
    )
    kwargs = build_engine_kwargs(spec, model_cfg)
    assert kwargs["aliyun_dashscope_send_temperature"] is True


def test_send_switches_false_are_omitted_to_preserve_old_behavior():
    for provider in ("openai", "openai_compatible", "aliyun"):
        spec = resolve_engine(provider)
        model_cfg = _model_cfg(provider=provider)
        kwargs = build_engine_kwargs(spec, model_cfg)
        for engine_field in spec.field_map.values():
            if "send_" in engine_field:
                assert engine_field not in kwargs, f"{provider}: {engine_field} 不应写入"


def test_enable_json_mode_false_is_passed_explicitly():
    """普通布尔字段的 False 不能被发送开关的省略逻辑吞掉。"""
    spec = resolve_engine("openai")
    model_cfg = _model_cfg(provider="openai", enable_json_mode=False)
    kwargs = build_engine_kwargs(spec, model_cfg)
    assert kwargs["openai_enable_json_mode"] is False

    deepseek_spec = resolve_engine("deepseek")
    deepseek_kwargs = build_engine_kwargs(
        deepseek_spec,
        _model_cfg(provider="deepseek", enable_json_mode=False),
    )
    assert deepseek_kwargs["deepseek_enable_json_mode"] is False
