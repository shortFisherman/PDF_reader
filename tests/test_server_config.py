import pytest

import config


@pytest.fixture(autouse=True)
def _no_pdf_reader_debug(monkeypatch) -> None:
    """每个用例默认不读真实环境变量，需要时再显式 setenv。"""
    monkeypatch.delenv("PDF_READER_DEBUG", raising=False)


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
