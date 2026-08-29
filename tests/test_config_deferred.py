import os
import sys
from unittest.mock import patch

import pdf_reader


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
