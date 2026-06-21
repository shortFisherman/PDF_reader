"""等价回归基线：对所有 10 引擎，新旧路径产出一致"""
import config
from services import resolve_engine, build_engine_kwargs


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
        cls = resolve_engine(provider)
        expected = config.PROVIDER_MAP[provider]
        assert cls is expected, (
            f"resolve_engine('{provider}') → {cls.__name__}, "
            f"expected {expected.__name__}"
        )


def test_unknown_provider_falls_back_to_openai_compatible():
    cls = resolve_engine("nonexistent_provider_xyz")
    from pdf2zh_next.config.translate_engine_model import OpenAICompatibleSettings
    assert cls is OpenAICompatibleSettings


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
        engine_cls = resolve_engine(provider)
        kwargs = build_engine_kwargs(engine_cls)
        assert isinstance(kwargs, dict), (
            f"build_engine_kwargs({engine_cls.__name__}) returned {type(kwargs)}"
        )
        assert "api_key" in config.FIELD_MAP, "baseline FIELD_MAP must have api_key"
        engine_name = engine_cls.__name__
        api_field = config.FIELD_MAP["api_key"].get(engine_name)
        model_field = config.FIELD_MAP["model"].get(engine_name)
        assert kwargs[api_field] == "sk-test-key", (
            f"{engine_name}: expected api_key at '{api_field}'"
        )
        assert kwargs[model_field] == "test-model", (
            f"{engine_name}: expected model at '{model_field}'"
        )
