import argparse
import logging
import sys

from flask import Flask

from pdf_reader import config, logging_config, paths
from pdf_reader.state import AppState
from pdf_reader.translation_coordinator import TranslationCoordinator

logger = logging.getLogger("pdf_reader.app")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m pdf_reader", description="PDF Reader 本地双语 PDF 阅读服务")
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


def create_app(settings: config.AppSettings) -> Flask:
    """用显式、不可变的 ``AppSettings`` 装配 Flask 应用（不读可变模块全局）。"""
    logging_config.setup_logging(settings.debug)

    logger.info(
        "Starting PDF Reader provider=%s model=%s lang=%s->%s cache_dir=%s dpi=%d debug=%s",
        settings.model_provider,
        settings.model,
        settings.lang_in,
        settings.lang_out,
        settings.cache_dir,
        settings.dpi,
        settings.debug,
    )

    app = Flask(
        __name__,
        template_folder=str(paths.get_resource_root() / "templates"),
        static_folder=str(paths.get_resource_root() / "static"),
    )
    app.config["app_settings"] = settings
    app.config["app_state"] = AppState(settings.cache_dir)
    app.config["translation_coordinator"] = TranslationCoordinator()
    from pdf_reader.routes import register_routes

    register_routes(app)
    return app


def main(argv: list[str] | None = None) -> int:
    """真实启动入口：解析 CLI、合并 debug 优先级、校验配置，然后启动 Flask。"""
    args = _build_parser().parse_args(argv)
    try:
        run_cfg = config.resolve_server_config(cli_debug=args.debug)
        config.validate_startup_requirements()
    except config.ConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    settings = config.build_app_settings(cli_debug=args.debug)
    app = create_app(settings)
    coordinator = app.config["translation_coordinator"]
    logger.info(
        "Starting PDF Reader on http://%s:%d (debug=%s, reloader=%s)",
        run_cfg.host,
        run_cfg.port,
        settings.debug,
        run_cfg.use_reloader,
    )
    if not config.is_loopback_host(run_cfg.host):
        logger.warning(
            "服务绑定在非 loopback 地址 host=%s；本服务无认证，可能暴露本地 PDF 与 API Key 配置，"
            "请确认仅限可信内网使用",
            run_cfg.host,
        )
    try:
        app.run(
            host=run_cfg.host,
            port=run_cfg.port,
            debug=settings.debug,
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
