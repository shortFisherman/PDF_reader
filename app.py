import argparse
import logging
import sys

from flask import Flask

import config
import logging_config
from state import AppState
from translation_coordinator import TranslationCoordinator

logger = logging.getLogger("pdf_reader.app")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="app.py", description="PDF Reader 本地双语 PDF 阅读服务")
    debug_group = parser.add_mutually_exclusive_group()
    debug_group.add_argument(
        "--debug",
        dest="debug",
        action="store_true",
        default=None,
        help="开启调试模式（日志 DEBUG + Flask debugger/reloader），覆盖环境变量与 config.toml",
    )
    debug_group.add_argument(
        "--no-debug",
        dest="debug",
        action="store_false",
        help="关闭调试模式，覆盖环境变量与 config.toml",
    )
    return parser


def create_app(run_cfg: config.ServerConfig | None = None) -> Flask:
    debug = config.DEBUG if run_cfg is None else run_cfg.debug
    logging_config.setup_logging(debug)

    logger.info(
        "Starting PDF Reader provider=%s model=%s lang=%s->%s cache_dir=%s dpi=%d debug=%s",
        config.MODEL_PROVIDER,
        config.MODEL,
        config.TRANSLATION_LANG_IN,
        config.TRANSLATION_LANG_OUT,
        config.CACHE_DIR,
        config.DPI,
        debug,
    )

    app = Flask(__name__)
    app.config["app_state"] = AppState(config.CACHE_DIR)
    app.config["translation_coordinator"] = TranslationCoordinator()
    from routes import register_routes

    register_routes(app)
    return app


def main(argv: list[str] | None = None) -> int:
    """真实启动入口：解析 CLI、合并 debug 优先级、校验配置，然后启动 Flask。"""
    args = _build_parser().parse_args(argv)
    try:
        run_cfg = config.resolve_server_config(cli_debug=args.debug)
        config.DEBUG = run_cfg.debug
        config.validate_startup_requirements()
    except config.ConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    app = create_app(run_cfg)
    coordinator = app.config["translation_coordinator"]
    logger.info(
        "Starting PDF Reader on http://%s:%d (debug=%s, reloader=%s)",
        run_cfg.host,
        run_cfg.port,
        run_cfg.debug,
        run_cfg.use_reloader,
    )
    try:
        app.run(
            host=run_cfg.host,
            port=run_cfg.port,
            debug=run_cfg.debug,
            use_reloader=run_cfg.use_reloader,
        )
    finally:
        active_job = coordinator.active_job
        if active_job is not None:
            logger.warning(
                "[job=%s] server shutting down with active translation job; worker may be orphaned",
                active_job.job_id,
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
