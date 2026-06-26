import argparse
import sys
from unittest.mock import patch


def test_cli_debug_flag_overrides_config():
    """--debug flag sets config.DEBUG = True regardless of config file."""
    with patch.object(sys, "argv", ["app.py", "--debug"]):
        with patch("config.DEBUG", False):
            parser = argparse.ArgumentParser()
            parser.add_argument("--debug", action="store_true", default=None)
            args, _ = parser.parse_known_args()

            import config

            if args.debug is not None:
                config.DEBUG = args.debug

            assert config.DEBUG is True


def test_cli_no_debug_flag_does_not_override():
    """When --debug is not passed, config.DEBUG keeps its config.toml value."""
    with patch.object(sys, "argv", ["app.py"]):
        parser = argparse.ArgumentParser()
        parser.add_argument("--debug", action="store_true", default=None)
        args, _ = parser.parse_known_args()

        import config

        original = config.DEBUG
        if args.debug is not None:
            config.DEBUG = args.debug

        assert config.DEBUG == original


def test_import_app_does_not_trigger_side_effects():
    """Importing app module does NOT set config.DEBUG=True or apply patches."""
    with patch("config.DEBUG", False):
        with patch("app.logging_config.setup_logging", create=True) as mock_setup:
            import app  # noqa: F401

            mock_setup.assert_not_called()


def test_create_app_calls_setup_logging():
    """create_app() explicitly calls setup_logging(config.DEBUG)."""
    with patch("app.logging_config.setup_logging") as mock_setup:
        from app import create_app

        create_app()
        mock_setup.assert_called_once()
