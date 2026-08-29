import os
import sys
from unittest.mock import patch


def test_import_config_without_config_toml():
    with patch.dict(sys.modules):
        if "config" in sys.modules:
            del sys.modules["config"]
        with patch("builtins.open", side_effect=FileNotFoundError):
            import config

            assert config.CONFIG == {}
            assert config.MODEL == ""
            assert config.MODEL_API_KEY == ""
            assert config.MODEL_PROVIDER == "openai_compatible"


def test_validate_passes_when_api_key_from_env(monkeypatch):
    import config

    monkeypatch.setattr(config, "MODEL_API_KEY", "sk-from-env")
    monkeypatch.setattr(config, "MODEL", "some-model")

    config._validate_required_config()


def test_env_model_api_key_overrides_file_value():
    with patch.dict(sys.modules):
        if "config" in sys.modules:
            del sys.modules["config"]
        with patch.dict(os.environ, {"MODEL_API_KEY": "sk-env-key"}):
            import config

            assert config.MODEL_API_KEY == "sk-env-key"
