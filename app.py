import logging
import os
import sys

from flask import Flask

import config
from state import AppState

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pdf_reader")

# Check debug flag at module level so it survives Werkzeug reloader restarts
if "--debug" in sys.argv:
    os.environ["PDF_READER_DEBUG"] = "1"

if os.environ.get("PDF_READER_DEBUG") == "1":
    config.DEBUG = True
    logger.info("Debug tracing enabled")

def create_app() -> Flask:
    app = Flask(__name__)
    app.config["app_state"] = AppState(config.CACHE_DIR)

    if config.DEBUG:
        from debug_patches import apply_patches
        apply_patches()

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
