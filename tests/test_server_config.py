import io
import json
import sys
import types
from unittest.mock import patch

import pytest

import pdf_reader
from pdf_reader import config, paths


@pytest.fixture(autouse=True)
def _no_pdf_reader_debug(monkeypatch) -> None:
    """每个用例默认不读真实运行时环境变量，需要时再显式 setenv。"""
    monkeypatch.delenv("PDF_READER_DEBUG", raising=False)
    monkeypatch.delenv("MODEL_API_KEY", raising=False)


class TestServerConfigValidation:
    def test_defaults(self):
        cfg = config.resolve_server_config({})
        assert cfg.host == "127.0.0.1"
        assert cfg.port == 5000
        assert cfg.debug is False
        assert cfg.use_reloader is False

    def test_valid_server_table(self):
        cfg = config.resolve_server_config({"server": {"host": "0.0.0.0", "port": 8000, "debug": True}})
        assert cfg.host == "0.0.0.0"
        assert cfg.port == 8000
        assert cfg.debug is True
        assert cfg.use_reloader is True

    @pytest.mark.parametrize("debug", [False, True])
    def test_use_reloader_matches_debug(self, debug):
        cfg = config.resolve_server_config({"server": {"debug": debug}})
        assert cfg.use_reloader is debug

    @pytest.mark.parametrize("server", ["not-a-table", 42, ["server"]])
    def test_server_must_be_table(self, server):
        with pytest.raises(config.ConfigError, match=r"\[server\] 必须是 TOML table"):
            config.resolve_server_config({"server": server})

    @pytest.mark.parametrize("host", ["", "   ", 123, True, ["x"]])
    def test_host_must_be_nonempty_string(self, host):
        with pytest.raises(config.ConfigError, match="host 必须是非空字符串"):
            config.resolve_server_config({"server": {"host": host}})

    @pytest.mark.parametrize("port", ["5000", True, False, 0, -1, 65536, 1.5])
    def test_port_must_be_int_in_range(self, port):
        with pytest.raises(config.ConfigError, match="port 必须是 1 到 65535"):
            config.resolve_server_config({"server": {"port": port}})

    @pytest.mark.parametrize("port", [1, 5000, 65535])
    def test_port_boundaries_accepted(self, port):
        assert config.resolve_server_config({"server": {"port": port}}).port == port

    @pytest.mark.parametrize("debug", ["false", "true", 0, 1, "False"])
    def test_debug_must_be_real_bool(self, debug):
        with pytest.raises(config.ConfigError, match="debug 必须是布尔值"):
            config.resolve_server_config({"server": {"debug": debug}})


class TestDebugPriority:
    def test_cli_debug_overrides_env_false_and_config_false(self, monkeypatch):
        monkeypatch.setenv("PDF_READER_DEBUG", "false")
        assert config.resolve_server_config({"server": {"debug": False}}, cli_debug=True).debug is True

    def test_cli_debug_overrides_env_true_and_config_false(self, monkeypatch):
        monkeypatch.setenv("PDF_READER_DEBUG", "true")
        assert config.resolve_server_config({"server": {"debug": False}}, cli_debug=True).debug is True

    def test_cli_no_debug_overrides_env_true_and_config_true(self, monkeypatch):
        monkeypatch.setenv("PDF_READER_DEBUG", "true")
        assert config.resolve_server_config({"server": {"debug": True}}, cli_debug=False).debug is False

    def test_env_true_overrides_config_false(self, monkeypatch):
        monkeypatch.setenv("PDF_READER_DEBUG", "yes")
        assert config.resolve_server_config({"server": {"debug": False}}).debug is True

    def test_env_false_overrides_config_true(self, monkeypatch):
        monkeypatch.setenv("PDF_READER_DEBUG", "off")
        assert config.resolve_server_config({"server": {"debug": True}}).debug is False

    def test_config_true_without_env_or_cli(self):
        assert config.resolve_server_config({"server": {"debug": True}}).debug is True

    def test_default_false(self):
        assert config.resolve_server_config({}).debug is False

    def test_legacy_debug_enabled_section_is_ignored(self):
        assert config.resolve_server_config({"debug": {"enabled": True}}).debug is False
        assert config.resolve_server_config({"debug": {"enabled": True}, "server": {"debug": False}}).debug is False

    def test_invalid_env_raises_even_with_cli_override(self, monkeypatch):
        monkeypatch.setenv("PDF_READER_DEBUG", "banana")
        with pytest.raises(config.ConfigError, match="PDF_READER_DEBUG 非法值"):
            config.resolve_server_config({}, cli_debug=True)


class TestDebugEnvParsing:
    @pytest.mark.parametrize("value", ["true", "TRUE", " True ", "1", "on", "yes", "YES"])
    def test_truthy_values(self, value):
        assert config.parse_debug_env(value) is True

    @pytest.mark.parametrize("value", ["false", "FALSE", " False ", "0", "off", "no", "No"])
    def test_falsy_values(self, value):
        assert config.parse_debug_env(value) is False

    def test_unset(self):
        assert config.parse_debug_env(None) is None

    @pytest.mark.parametrize("value", ["", "  ", "banana", "2", "yes please"])
    def test_invalid_values_raise(self, value):
        with pytest.raises(config.ConfigError, match="PDF_READER_DEBUG 非法值"):
            config.parse_debug_env(value)


class TestConfigFileLoading:
    def test_missing_file_loads_empty(self, tmp_path):
        assert config._load_config(tmp_path / "missing.toml") == {}

    def test_toml_syntax_error_raises_config_error(self, tmp_path):
        bad = tmp_path / "bad.toml"
        bad.write_bytes(b"not = = valid [[")
        with pytest.raises(config.ConfigError, match="TOML 语法错误"):
            config._load_config(bad)


class TestLoopbackHost:
    @pytest.mark.parametrize(
        "host",
        ["127.0.0.1", "127.1.2.3", "localhost", "LOCALHOST", "::1", "0:0:0:0:0:0:0:1"],
    )
    def test_loopback_hosts(self, host):
        assert config.is_loopback_host(host) is True

    @pytest.mark.parametrize(
        "host",
        ["0.0.0.0", "::", "192.168.1.5", "example.com", "", "localhost.localdomain"],
    )
    def test_non_loopback_hosts(self, host):
        assert config.is_loopback_host(host) is False


class TestStartupValidationSections:
    @staticmethod
    def _base() -> dict:
        return {
            "model": {"provider": "deepseek", "model": "deepseek-chat", "api_key": "sk-test"},
            "pdf_reader": {"dpi": 200, "cache_dir": "cache"},
            "translation": {"lang_in": "en", "lang_out": "zh"},
        }

    def test_valid_config_passes(self):
        config.validate_startup_requirements(
            {
                **self._base(),
                "model": {
                    "provider": "deepseek",
                    "model": "deepseek-chat",
                    "api_key": "sk-test",
                    "base_url": "https://api.example.com/v1",
                },
                "pdf_reader": {"dpi": 300, "cache_dir": "cache"},
            }
        )

    @pytest.mark.parametrize("section", ["model", "pdf_reader", "translation"])
    def test_sections_must_be_tables(self, section):
        cfg = self._base()
        cfg[section] = "bad"
        with pytest.raises(config.ConfigError, match=rf"\[{section}\] 必须是 TOML table"):
            config.validate_startup_requirements(cfg)

    @pytest.mark.parametrize(
        ("fields", "message"),
        [
            ({"model": {"provider": 123}}, r"\[model\]\.provider 必须是非空字符串"),
            ({"model": {"provider": "   "}}, r"\[model\]\.provider 必须是非空字符串"),
            ({"model": {"model": 123}}, r"\[model\]\.model 必须是非空字符串"),
            ({"model": {"model": True}}, r"\[model\]\.model 必须是非空字符串"),
            ({"model": {"model": ["m"]}}, r"\[model\]\.model 必须是非空字符串"),
            ({"model": {"model": ""}}, r"\[model\]\.model 必须是非空字符串"),
            ({"model": {"api_key": 123}}, "请设置 model.api_key 或环境变量 MODEL_API_KEY"),
            ({"model": {"api_key": True}}, "请设置 model.api_key 或环境变量 MODEL_API_KEY"),
            ({"model": {"api_key": ["sk-x"]}}, "请设置 model.api_key 或环境变量 MODEL_API_KEY"),
            ({"model": {"api_key": "sk-your-api-key"}}, "示例占位值"),
            ({"model": {"base_url": 123}}, r"\[model\]\.base_url 若设置必须是非空字符串"),
            ({"model": {"base_url": ""}}, r"\[model\]\.base_url 若设置必须是非空字符串"),
            ({"pdf_reader": {"dpi": "200"}}, r"\[pdf_reader\]\.dpi 必须是正整数"),
            ({"pdf_reader": {"dpi": True}}, r"\[pdf_reader\]\.dpi 必须是正整数"),
            ({"pdf_reader": {"dpi": 0}}, r"\[pdf_reader\]\.dpi 必须是正整数"),
            ({"pdf_reader": {"cache_dir": 123}}, r"\[pdf_reader\]\.cache_dir 必须是非空字符串"),
            ({"pdf_reader": {"cache_dir": ""}}, r"\[pdf_reader\]\.cache_dir 必须是非空字符串"),
            ({"translation": {"lang_in": 123}}, r"\[translation\]\.lang_in 必须是非空字符串"),
            ({"translation": {"lang_out": ""}}, r"\[translation\]\.lang_out 必须是非空字符串"),
        ],
    )
    def test_invalid_fields_rejected(self, fields, message):
        cfg = self._base()
        for section, values in fields.items():
            cfg[section].update(values)
        with pytest.raises(config.ConfigError, match=message):
            config.validate_startup_requirements(cfg)

    @pytest.mark.parametrize("dpi", [1, 200, 10000])
    def test_positive_dpi_accepted(self, dpi):
        cfg = self._base()
        cfg["pdf_reader"] = {"dpi": dpi, "cache_dir": "cache"}
        config.validate_startup_requirements(cfg)


class TestEnvApiKeyOverride:
    def _base(self) -> dict:
        return {
            "model": {"provider": "deepseek", "model": "deepseek-chat", "api_key": "sk-file"},
            "pdf_reader": {},
            "translation": {},
        }

    def test_env_valid_overrides_invalid_file_api_key_type(self, monkeypatch):
        monkeypatch.setenv("MODEL_API_KEY", "sk-env-key")
        cfg = self._base()
        cfg["model"]["api_key"] = 123
        config.validate_startup_requirements(cfg)

    def test_env_valid_overrides_placeholder_file_api_key(self, monkeypatch):
        monkeypatch.setenv("MODEL_API_KEY", "sk-env-key")
        cfg = self._base()
        cfg["model"]["api_key"] = "sk-your-api-key"
        config.validate_startup_requirements(cfg)

    def test_env_cannot_fix_non_table_model_section(self, monkeypatch):
        monkeypatch.setenv("MODEL_API_KEY", "sk-env-key")
        with pytest.raises(config.ConfigError, match=r"\[model\] 必须是 TOML table"):
            config.validate_startup_requirements({"model": "bad"})

    def test_empty_env_key_rejected(self, monkeypatch):
        monkeypatch.setenv("MODEL_API_KEY", "")
        with pytest.raises(config.ConfigError, match="请设置 model.api_key 或环境变量 MODEL_API_KEY"):
            config.validate_startup_requirements(self._base())

    def test_env_placeholder_rejected(self, monkeypatch):
        monkeypatch.setenv("MODEL_API_KEY", "sk-your-api-key")
        with pytest.raises(config.ConfigError, match="示例占位值"):
            config.validate_startup_requirements(self._base())


class TestBuildAppSettingsSingleParse:
    def test_build_app_settings_reuses_pre_resolved_run_config(self):
        """传入 run_cfg 时不再调用 resolve_server_config，debug 以已解析结果为准。"""
        run_cfg = config.ServerConfig(host="0.0.0.0", port=9000, debug=True)
        snapshot = {
            "pdf_reader": {"dpi": 150, "cache_dir": "cache"},
            "translation": {"lang_in": "ja", "lang_out": "ko"},
            "model": {"provider": "zhipu", "model": "zhipu-ai", "api_key": "sk-test"},
        }
        with patch.object(config, "resolve_server_config", wraps=config.resolve_server_config) as spy:
            settings = config.build_app_settings(snapshot, cli_debug=False, run_cfg=run_cfg)

        spy.assert_not_called()
        assert settings.debug is True
        assert settings.dpi == 150
        assert settings.model_provider == "zhipu"
        assert settings.model == "zhipu-ai"
        assert settings.lang_in == "ja"
        assert settings.lang_out == "ko"

    def test_build_app_settings_resolves_when_no_run_cfg(self, monkeypatch):
        monkeypatch.delenv("PDF_READER_DEBUG", raising=False)
        snapshot = {
            "server": {"debug": True},
            "pdf_reader": {},
            "translation": {},
            "model": {"provider": "deepseek", "model": "deepseek-chat", "api_key": "sk-test"},
        }

        settings = config.build_app_settings(snapshot)

        assert settings.debug is True


class TestImportTypeSafety:
    def _reimport(self, toml_bytes: bytes, monkeypatch) -> types.ModuleType:
        monkeypatch.delenv("MODEL_API_KEY", raising=False)
        monkeypatch.delenv("PDF_READER_DEBUG", raising=False)
        original_config = pdf_reader.__dict__.get("config")
        with patch.dict(sys.modules):
            sys.modules.pop("pdf_reader.config", None)
            pdf_reader.__dict__.pop("config", None)
            with patch("builtins.open", return_value=io.BytesIO(toml_bytes)):
                from pdf_reader import config as fresh_config
        pdf_reader.__dict__["config"] = original_config
        return fresh_config

    def test_import_survives_non_table_and_bad_field_types(self, monkeypatch):
        fresh = self._reimport(
            b"model = 'bad'\n"
            b"[pdf_reader]\n"
            b"dpi = 'high'\n"
            b"cache_dir = 123\n"
            b"[translation]\n"
            b"lang_in = 123\n"
            b"lang_out = true\n",
            monkeypatch,
        )

        assert fresh.MODEL == ""
        assert fresh.MODEL_PROVIDER == "openai_compatible"
        assert fresh.MODEL_API_KEY == ""
        assert fresh.MODEL_BASE_URL is None
        assert fresh.CACHE_DIR == paths.resolve_cache_dir("cache")
        assert fresh.TRANSLATION_LANG_IN == "en"
        assert fresh.TRANSLATION_LANG_OUT == "zh"

        with pytest.raises(fresh.ConfigError, match=r"\[model\] 必须是 TOML table"):
            fresh.validate_startup_requirements()

    def test_import_keeps_absolute_cache_dir(self, monkeypatch, tmp_path):
        abs_cache = tmp_path / "abs-cache"
        toml = (
            b"[model]\n"
            b"provider = 'deepseek'\n"
            b"model = 'deepseek-chat'\n"
            b"api_key = 'sk-test'\n"
            b"[pdf_reader]\n"
            b"dpi = 200\n"
            b"cache_dir = " + json.dumps(str(abs_cache)).encode() + b"\n"
            b"[translation]\n"
            b"lang_in = 'en'\n"
            b"lang_out = 'zh'\n"
        )
        fresh = self._reimport(toml, monkeypatch)
        assert fresh.CACHE_DIR == abs_cache.resolve()

    def test_import_survives_invalid_model_field_types(self, monkeypatch):
        fresh = self._reimport(
            b"[model]\n"
            b"provider = 'deepseek'\n"
            b"model = 123\n"
            b"api_key = 456\n"
            b"[pdf_reader]\n"
            b"dpi = 200\n"
            b"cache_dir = 'cache'\n"
            b"[translation]\n"
            b"lang_in = 'en'\n"
            b"lang_out = 'zh'\n",
            monkeypatch,
        )

        assert fresh.MODEL == ""
        assert fresh.MODEL_API_KEY == ""
        with pytest.raises(fresh.ConfigError, match=r"\[model\]\.model 必须是非空字符串"):
            fresh.validate_startup_requirements()
