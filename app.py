import logging

from flask import Flask

import config
from state import AppState

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pdf_reader")


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["app_state"] = AppState(config.CACHE_DIR)
    from routes import register_routes
    register_routes(app)
    return app


app = create_app()

if __name__ == "__main__":
    import sys

    if "--debug" in sys.argv:
        config.DEBUG = True
        logger.info("Debug tracing enabled")
        from debug_patches import apply_patches
        apply_patches()

    server_debug = config.CONFIG.get("server", {}).get("debug", True)
    host = config.CONFIG.get("server", {}).get("host", "127.0.0.1")
    port = config.CONFIG.get("server", {}).get("port", 5000)
    logger.info(f"Starting PDF Reader on http://{host}:{port}")
    app.run(host=host, port=port, debug=server_debug)
