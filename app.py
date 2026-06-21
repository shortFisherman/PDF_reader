import argparse
import logging

from flask import Flask

import config
import debug_trace
from state import AppState

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pdf_reader")

_parser = argparse.ArgumentParser()
_parser.add_argument("--debug", action="store_true", default=None,
                     help="Enable debug tracing")
_cli_args, _ = _parser.parse_known_args()
if _cli_args.debug is not None:
    config.DEBUG = _cli_args.debug


def create_app() -> Flask:
    debug_trace.init_debug(config.DEBUG)
    app = Flask(__name__)
    app.config["app_state"] = AppState(config.CACHE_DIR)
    from routes import register_routes
    register_routes(app)
    return app


app = create_app()

if __name__ == "__main__":
    server_debug = config.CONFIG.get("server", {}).get("debug", True)
    host = config.CONFIG.get("server", {}).get("host", "127.0.0.1")
    port = config.CONFIG.get("server", {}).get("port", 5000)
    logger.info(f"Starting PDF Reader on http://{host}:{port}")
    app.run(host=host, port=port, debug=server_debug)
