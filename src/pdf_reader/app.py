import argparse
import io
import logging
import sys

from flask import Flask

from pdf_reader import cache_ops, config, logging_config, paths
from pdf_reader.candidate_service import CandidateExtractionService
from pdf_reader.state import AppState
from pdf_reader.translation_coordinator import TranslationCoordinator

logger = logging.getLogger("pdf_reader.app")

SHUTDOWN_JOIN_TIMEOUT = 10.0


def _ensure_utf8_stdio() -> None:
    """真实入口统一把 stdout/stderr 重配置为 UTF-8（仅当前编码不是 UTF-8 时生效）。

    英文 Windows 的运行器控制台编码是 cp1252（charmap），向 stdout/stderr
    写中文会抛 UnicodeEncodeError；本函数在 argparse 解析之前调用，确保
    --help、错误消息与日志在任何控制台编码下都能输出。正常 UTF-8 环境
    （含 PYTHONUTF8=1 / PYTHONIOENCODING=utf-8）行为不变。
    """
    for stream in (sys.stdout, sys.stderr):
        if not isinstance(stream, io.TextIOWrapper):
            # 非 TextIOWrapper（如测试注入的 StringIO）时静默降级
            continue
        encoding = stream.encoding or ""
        if encoding.lower().replace("-", "").replace("_", "") == "utf8":
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (OSError, ValueError):
            # 已关闭或不可重配置的流静默降级
            continue


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m pdf_reader", description="PDF Reader 本地双语 PDF 阅读服务")
    debug_group = parser.add_mutually_exclusive_group()
    debug_group.add_argument(
        "--debug",
        dest="debug",
        action="store_true",
        default=None,
        help=(
            "开启详细诊断日志模式（日志 DEBUG + debug_trace），"
            "不启用 Flask debugger/reloader；覆盖环境变量与 config.toml"
        ),
    )
    debug_group.add_argument(
        "--no-debug",
        dest="debug",
        action="store_false",
        help="关闭详细诊断日志模式（保持常规 INFO 日志），覆盖环境变量与 config.toml",
    )
    return parser


def create_app(settings: config.AppSettings) -> Flask:
    """用显式、不可变的 ``AppSettings`` 装配 Flask 应用（不读可变模块全局）。

    ``settings.debug`` 只作为详细诊断日志模式传给 ``setup_logging``；
    应用永远不启用 Flask debugger/reloader。
    """
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
    app.config["candidate_extraction_service"] = CandidateExtractionService(
        settings.term_extraction,
        settings.upstream.model,
    )
    from pdf_reader.routes import register_routes

    register_routes(app)
    return app


def main(argv: list[str] | None = None) -> int:
    """真实启动入口：解析 CLI、合并 debug 优先级、校验配置，然后启动 Flask。

    ``debug`` 仅表示“详细诊断日志模式”（日志 DEBUG + debug_trace）；
    Flask 始终以 ``debug=False, use_reloader=False`` 运行。日志初始化之后的
    致命异常统一经 ``logger.exception`` 记录并返回非零；正常
    ``KeyboardInterrupt`` 只记录 INFO，不当成 ERROR。
    """
    _ensure_utf8_stdio()
    args = _build_parser().parse_args(argv)
    try:
        run_cfg = config.resolve_server_config(cli_debug=args.debug)
        upstream = config.validate_startup_requirements()
    except config.ConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    app = None
    try:
        settings = config.build_app_settings(cli_debug=args.debug, run_cfg=run_cfg, upstream=upstream)
        app = create_app(settings)
        recovered = cache_ops.recover_orphan_temp_workspaces(settings.cache_dir)
        if recovered.removed:
            logger.info(
                "startup temp workspace recovery: removed=%d kept_unknown=%d kept_live_pid=%d errors=%d",
                len(recovered.removed),
                len(recovered.kept_unknown),
                len(recovered.kept_live_pid),
                len(recovered.errors),
            )
        elif recovered.kept_unknown or recovered.kept_live_pid or recovered.errors:
            logger.warning(
                "startup temp workspace recovery: nothing removed; kept_unknown=%d kept_live_pid=%d errors=%d",
                len(recovered.kept_unknown),
                len(recovered.kept_live_pid),
                len(recovered.errors),
            )
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
                debug=False,
                use_reloader=False,
            )
        except KeyboardInterrupt:
            logger.info("server stopped by KeyboardInterrupt")
            return 130
        except Exception:
            logger.exception("fatal error while running server")
            return 1
        return 0
    except KeyboardInterrupt:
        logger.info("startup interrupted by KeyboardInterrupt")
        return 130
    except Exception:
        logger.exception("fatal startup error")
        return 1
    finally:
        if app is not None:
            try:
                report = app.config["translation_coordinator"].shutdown(timeout=SHUTDOWN_JOIN_TIMEOUT)
                if report.outcome == "timeout":
                    logger.warning(
                        "shutdown timed out: active job %s kept; its temp dirs are preserved for startup recovery",
                        report.active_job_id,
                    )
                elif report.outcome == "completed":
                    logger.info("shutdown completed: active job %s finished within timeout", report.active_job_id)
                else:
                    logger.info("shutdown: no active translation job")
                if not report.worker_joined:
                    logger.warning(
                        "shutdown: one or more workers still running after join timeout; temp dirs preserved"
                    )
            finally:
                app.config["app_state"].close()
                logger.info("app state closed")


if __name__ == "__main__":
    sys.exit(main())
