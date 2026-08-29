import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import pdf_reader
from pdf_reader import app as app_module
from pdf_reader import config

REPO_ROOT = Path(__file__).resolve().parents[1]


def _valid_config(server: dict | None = None) -> dict:
    cfg = {
        "model": {"provider": "deepseek", "model": "deepseek-chat", "api_key": "sk-test"},
        "pdf_reader": {"dpi": 200, "cache_dir": "cache"},
        "translation": {"lang_in": "en", "lang_out": "zh"},
    }
    if server is not None:
        cfg["server"] = server
    return cfg


@pytest.fixture
def valid_model_config(monkeypatch):
    """让 main() 通过必填模型校验；CI 无 config.toml 时也稳定。"""
    monkeypatch.setattr(config, "MODEL", "deepseek-chat")
    monkeypatch.setattr(config, "MODEL_API_KEY", "sk-test-key")


@pytest.fixture
def main_entry(monkeypatch, valid_model_config):
    """用 mock create_app/app.run 调用真实 main(argv) 入口，不启动服务器。"""
    mock_app = MagicMock()
    monkeypatch.setattr(app_module, "create_app", lambda run_cfg=None: mock_app)
    monkeypatch.setattr(config, "DEBUG", False)
    return mock_app, lambda argv=None: app_module.main(argv)


class TestMainDebugPriority:
    def test_default_debug_false_and_reloader_false(self, monkeypatch, main_entry):
        monkeypatch.delenv("PDF_READER_DEBUG", raising=False)
        monkeypatch.setattr(config, "CONFIG", _valid_config())
        mock_app, run = main_entry

        assert run([]) == 0

        mock_app.run.assert_called_once_with(host="127.0.0.1", port=5000, debug=False, use_reloader=False)
        assert config.DEBUG is False

    def test_cli_debug_overrides_env_and_config(self, monkeypatch, main_entry):
        monkeypatch.setenv("PDF_READER_DEBUG", "false")
        monkeypatch.setattr(config, "CONFIG", _valid_config({"debug": False}))
        mock_app, run = main_entry

        assert run(["--debug"]) == 0

        mock_app.run.assert_called_once_with(host="127.0.0.1", port=5000, debug=True, use_reloader=True)
        assert config.DEBUG is True

    def test_cli_no_debug_overrides_env_and_config(self, monkeypatch, main_entry):
        monkeypatch.setenv("PDF_READER_DEBUG", "true")
        monkeypatch.setattr(config, "CONFIG", _valid_config({"host": "0.0.0.0", "port": 8000, "debug": True}))
        mock_app, run = main_entry

        assert run(["--no-debug"]) == 0

        mock_app.run.assert_called_once_with(host="0.0.0.0", port=8000, debug=False, use_reloader=False)
        assert config.DEBUG is False

    def test_env_true_overrides_config_false(self, monkeypatch, main_entry):
        monkeypatch.setenv("PDF_READER_DEBUG", "true")
        monkeypatch.setattr(config, "CONFIG", _valid_config({"debug": False}))
        mock_app, run = main_entry

        assert run([]) == 0

        mock_app.run.assert_called_once_with(host="127.0.0.1", port=5000, debug=True, use_reloader=True)

    def test_env_false_overrides_config_true(self, monkeypatch, main_entry):
        monkeypatch.setenv("PDF_READER_DEBUG", "0")
        monkeypatch.setattr(config, "CONFIG", _valid_config({"debug": True}))
        mock_app, run = main_entry

        assert run([]) == 0

        mock_app.run.assert_called_once_with(host="127.0.0.1", port=5000, debug=False, use_reloader=False)

    def test_config_true_when_no_env_or_cli(self, monkeypatch, main_entry):
        monkeypatch.delenv("PDF_READER_DEBUG", raising=False)
        monkeypatch.setattr(config, "CONFIG", _valid_config({"debug": True}))
        mock_app, run = main_entry

        assert run([]) == 0

        mock_app.run.assert_called_once_with(host="127.0.0.1", port=5000, debug=True, use_reloader=True)


class TestMainErrorPaths:
    def test_cli_debug_and_no_debug_are_mutually_exclusive(self, main_entry):
        mock_app, run = main_entry

        with pytest.raises(SystemExit) as excinfo:
            run(["--debug", "--no-debug"])

        assert excinfo.value.code == 2
        mock_app.run.assert_not_called()

    def test_invalid_env_value_returns_2(self, monkeypatch, main_entry, capsys):
        monkeypatch.setenv("PDF_READER_DEBUG", "banana")
        monkeypatch.setattr(config, "CONFIG", {})
        mock_app, run = main_entry

        assert run([]) == 2

        stderr = capsys.readouterr().err
        assert "ERROR:" in stderr
        assert "PDF_READER_DEBUG 非法值" in stderr
        assert "true/false/1/0/on/off/yes/no" in stderr
        mock_app.run.assert_not_called()

    @pytest.mark.parametrize(
        ("server", "message"),
        [
            ("not-a-table", "[server] 必须是 TOML table"),
            ({"host": ""}, "host 必须是非空字符串"),
            ({"host": 123}, "host 必须是非空字符串"),
            ({"port": "5000"}, "port 必须是 1 到 65535"),
            ({"port": True}, "port 必须是 1 到 65535"),
            ({"port": 0}, "port 必须是 1 到 65535"),
            ({"port": 65536}, "port 必须是 1 到 65535"),
            ({"debug": "false"}, "debug 必须是布尔值"),
            ({"debug": 0}, "debug 必须是布尔值"),
        ],
    )
    def test_invalid_server_config_returns_2(self, monkeypatch, main_entry, capsys, server, message):
        monkeypatch.delenv("PDF_READER_DEBUG", raising=False)
        monkeypatch.setattr(config, "CONFIG", {"server": server})
        mock_app, run = main_entry

        assert run([]) == 2

        stderr = capsys.readouterr().err
        assert "ERROR:" in stderr
        assert message in stderr
        mock_app.run.assert_not_called()

    def test_missing_model_name_blocks_startup(self, monkeypatch, main_entry, capsys):
        monkeypatch.setattr(config, "MODEL", "")
        monkeypatch.setattr(config, "MODEL_API_KEY", "sk-test-key")
        monkeypatch.delenv("PDF_READER_DEBUG", raising=False)
        monkeypatch.delenv("MODEL_API_KEY", raising=False)
        monkeypatch.setattr(config, "CONFIG", {})
        mock_app, run = main_entry

        assert run([]) == 2

        assert "[model].model 必须是非空字符串" in capsys.readouterr().err
        mock_app.run.assert_not_called()

    def test_missing_api_key_blocks_startup(self, monkeypatch, main_entry, capsys):
        monkeypatch.setattr(config, "MODEL", "deepseek-chat")
        monkeypatch.setattr(config, "MODEL_API_KEY", "")
        monkeypatch.delenv("PDF_READER_DEBUG", raising=False)
        monkeypatch.delenv("MODEL_API_KEY", raising=False)
        monkeypatch.setattr(config, "CONFIG", {"model": {"model": "deepseek-chat"}})
        mock_app, run = main_entry

        assert run([]) == 2

        assert "model.api_key 或环境变量 MODEL_API_KEY" in capsys.readouterr().err
        mock_app.run.assert_not_called()

    def test_toml_syntax_error_surfaces_as_startup_error(self, monkeypatch, main_entry, capsys):
        monkeypatch.setattr(
            config,
            "_CONFIG_LOAD_ERROR",
            "TOML 语法错误（C:/bad/config.toml）：Invalid statement",
        )
        monkeypatch.delenv("PDF_READER_DEBUG", raising=False)
        mock_app, run = main_entry

        assert run([]) == 2

        assert "TOML 语法错误" in capsys.readouterr().err
        mock_app.run.assert_not_called()

    def test_errors_never_include_api_key(self, monkeypatch, main_entry, capsys):
        monkeypatch.setattr(config, "MODEL", "")
        monkeypatch.setattr(config, "MODEL_API_KEY", "sk-super-secret-value")
        monkeypatch.delenv("PDF_READER_DEBUG", raising=False)
        monkeypatch.delenv("MODEL_API_KEY", raising=False)
        monkeypatch.setattr(config, "CONFIG", {})
        mock_app, run = main_entry

        assert run([]) == 2

        assert "sk-super-secret-value" not in capsys.readouterr().err

    @pytest.mark.parametrize(
        ("bad_config", "message"),
        [
            ({"model": "bad", "pdf_reader": {}, "translation": {}}, "[model] 必须是 TOML table"),
            (
                {"model": {"model": 123, "api_key": "sk-x"}, "pdf_reader": {}, "translation": {}},
                "[model].model 必须是非空字符串",
            ),
            (
                {"model": {"model": "m", "api_key": "sk-x"}, "pdf_reader": {"dpi": "200"}, "translation": {}},
                "[pdf_reader].dpi 必须是正整数",
            ),
            (
                {"model": {"model": "m", "api_key": "sk-x"}, "pdf_reader": {}, "translation": {"lang_in": 123}},
                "[translation].lang_in 必须是非空字符串",
            ),
        ],
    )
    def test_invalid_startup_sections_return_2(self, monkeypatch, main_entry, capsys, bad_config, message):
        monkeypatch.delenv("PDF_READER_DEBUG", raising=False)
        monkeypatch.delenv("MODEL_API_KEY", raising=False)
        monkeypatch.setattr(config, "CONFIG", bad_config)
        mock_app, run = main_entry

        assert run([]) == 2

        stderr = capsys.readouterr().err
        assert "ERROR:" in stderr
        assert message in stderr
        mock_app.run.assert_not_called()


class TestImportHasNoCliSideEffects:
    def test_import_app_does_not_parse_cli_or_modify_config_debug(self):
        original_debug = config.DEBUG
        with patch.object(sys, "argv", ["python", "-m", "pdf_reader", "--debug"]):
            with patch("pdf_reader.logging_config.setup_logging") as mock_setup:
                with patch.dict(sys.modules):
                    sys.modules.pop("pdf_reader.app", None)
                    pdf_reader.__dict__.pop("app", None)
                    from pdf_reader import app as fresh_app  # noqa: F401

                    assert config.DEBUG == original_debug
                    assert not hasattr(fresh_app, "_parser")
                    assert callable(fresh_app.main)
                    mock_setup.assert_not_called()


class TestCreateAppLogging:
    def test_create_app_uses_resolved_debug(self, monkeypatch):
        monkeypatch.setattr(config, "DEBUG", False)
        with patch("pdf_reader.app.logging_config.setup_logging") as mock_setup:
            app_module.create_app(config.ServerConfig(host="127.0.0.1", port=5000, debug=True))
            mock_setup.assert_called_once_with(True)

    def test_create_app_default_uses_config_debug(self, monkeypatch):
        monkeypatch.setattr(config, "DEBUG", True)
        with patch("pdf_reader.app.logging_config.setup_logging") as mock_setup:
            app_module.create_app()
            mock_setup.assert_called_once_with(True)

    def test_main_logging_and_run_share_one_debug(self, monkeypatch):
        """真实 create_app：setup_logging 与 app.run 收到同一个解析后的 debug。"""
        from flask import Flask

        monkeypatch.delenv("PDF_READER_DEBUG", raising=False)
        monkeypatch.setattr(config, "CONFIG", _valid_config())
        monkeypatch.setattr(config, "MODEL", "deepseek-chat")
        monkeypatch.setattr(config, "MODEL_API_KEY", "sk-test-key")
        monkeypatch.setattr(config, "DEBUG", False)
        with patch("pdf_reader.app.logging_config.setup_logging") as mock_setup:
            with patch.object(Flask, "run") as mock_run:
                assert app_module.main(["--debug"]) == 0

        mock_setup.assert_called_once_with(True)
        mock_run.assert_called_once_with(host="127.0.0.1", port=5000, debug=True, use_reloader=True)
        assert config.DEBUG is True

    def test_main_default_logging_and_run_share_false(self, monkeypatch):
        from flask import Flask

        monkeypatch.delenv("PDF_READER_DEBUG", raising=False)
        monkeypatch.setattr(config, "CONFIG", _valid_config())
        monkeypatch.setattr(config, "MODEL", "deepseek-chat")
        monkeypatch.setattr(config, "MODEL_API_KEY", "sk-test-key")
        monkeypatch.setattr(config, "DEBUG", False)
        with patch("pdf_reader.app.logging_config.setup_logging") as mock_setup:
            with patch.object(Flask, "run") as mock_run:
                assert app_module.main([]) == 0

        mock_setup.assert_called_once_with(False)
        mock_run.assert_called_once_with(host="127.0.0.1", port=5000, debug=False, use_reloader=False)
        assert config.DEBUG is False


class TestRealEntry:
    def test_mutually_exclusive_flags_exit_nonzero(self):
        result = subprocess.run(
            [sys.executable, "-m", "pdf_reader", "--debug", "--no-debug"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=15,
        )

        assert result.returncode != 0
        assert "usage: python -m pdf_reader" in result.stderr
        assert "not allowed with argument --debug" in result.stderr

    def test_invalid_env_exits_nonzero_with_clear_error(self):
        import os

        env = os.environ.copy()
        env["PDF_READER_DEBUG"] = "banana"
        result = subprocess.run(
            [sys.executable, "-m", "pdf_reader"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            env=env,
            timeout=15,
        )

        assert result.returncode != 0
        assert "PDF_READER_DEBUG 非法值" in result.stderr

    def test_real_entry_injected_bad_config_exits_2(self):
        script = (
            "import sys; from pdf_reader import app, config;"
            "config.CONFIG = {'model': {'model': 123, 'api_key': 'sk-x'}, 'pdf_reader': {}, 'translation': {}};"
            "sys.exit(app.main([]))"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=15,
        )

        assert result.returncode == 2
        assert "[model].model 必须是非空字符串" in result.stderr


class TestNonLoopbackHostWarning:
    def test_loopback_host_no_warning(self, monkeypatch, main_entry, caplog):
        import logging

        monkeypatch.delenv("PDF_READER_DEBUG", raising=False)
        monkeypatch.setattr(config, "CONFIG", _valid_config({"host": "127.0.0.1", "debug": False}))
        mock_app, run = main_entry

        with caplog.at_level(logging.WARNING, logger="pdf_reader.app"):
            assert run([]) == 0

        warnings = [r.message for r in caplog.records if r.name == "pdf_reader.app" and r.levelno == logging.WARNING]
        assert not any("loopback" in w for w in warnings)

    def test_non_loopback_host_logs_warning(self, monkeypatch, main_entry, caplog):
        import logging

        monkeypatch.delenv("PDF_READER_DEBUG", raising=False)
        monkeypatch.setattr(config, "CONFIG", _valid_config({"host": "0.0.0.0", "debug": False}))
        mock_app, run = main_entry

        with caplog.at_level(logging.WARNING, logger="pdf_reader.app"):
            assert run([]) == 0

        warnings = [r.message for r in caplog.records if r.name == "pdf_reader.app" and r.levelno == logging.WARNING]
        assert any("0.0.0.0" in w and "loopback" in w for w in warnings)
        assert all("sk-test-key" not in w for w in warnings)
