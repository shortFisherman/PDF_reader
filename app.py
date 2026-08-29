import argparse
import logging

from flask import Flask

import config
import logging_config
from state import AppState
from translation_coordinator import TranslationCoordinator

logger = logging.getLogger("pdf_reader.app")

_parser = argparse.ArgumentParser()
_parser.add_argument("--debug", action="store_true", default=None, help="Enable debug tracing")
_cli_args, _ = _parser.parse_known_args()
if _cli_args.debug is not None:
    config.DEBUG = _cli_args.debug


def create_app() -> Flask:
    logging_config.setup_logging(config.DEBUG)

    logger.info(
        "Starting PDF Reader provider=%s model=%s lang=%s->%s cache_dir=%s dpi=%d debug=%s",
        config.MODEL_PROVIDER,
        config.MODEL,
        config.TRANSLATION_LANG_IN,
        config.TRANSLATION_LANG_OUT,
        config.CACHE_DIR,
        config.DPI,
        config.DEBUG,
    )

    app = Flask(__name__)
    app.config["app_state"] = AppState(config.CACHE_DIR)
    app.config["translation_coordinator"] = TranslationCoordinator()
    from routes import register_routes

    register_routes(app)
    return app


if __name__ == "__main__":
    app = create_app()
    coordinator = app.config["translation_coordinator"]
    server_debug = config.CONFIG.get("server", {}).get("debug", True)
    host = config.CONFIG.get("server", {}).get("host", "127.0.0.1")
    port = config.CONFIG.get("server", {}).get("port", 5000)
    logger.info(f"Starting PDF Reader on http://{host}:{port}")
    try:
        app.run(host=host, port=port, debug=server_debug)
    finally:
        active_job = coordinator.active_job
        if active_job is not None:
            logger.warning(
                "[job=%s] server shutting down with active translation job; worker may be orphaned",
                active_job.job_id,
            )
