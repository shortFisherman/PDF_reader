import argparse
import hmac
import io
import logging
import os
import sys
import threading
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Protocol, cast

from flask import Flask, Response, jsonify, request

from pdf_reader import cache_ops, config, logging_config, paths
from pdf_reader.candidate_service import CandidateExtractionService
from pdf_reader.state import AppState
from pdf_reader.translation_coordinator import TranslationCoordinator

logger = logging.getLogger("pdf_reader.app")

SHUTDOWN_JOIN_TIMEOUT = 10.0

# 便携服务控制通道轮询间隔；只影响发现退出请求的延迟，不影响请求处理。
PORTABLE_SHUTDOWN_POLL_INTERVAL = 0.2

# 停止后等待监督线程收尾的上限；它是守护线程，超时不会阻止进程退出。
PORTABLE_MONITOR_JOIN_TIMEOUT = 1.0


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
    app.config["setup_mode"] = settings.setup_mode
    app.config["setup_reason"] = settings.setup_reason
    app.config["portable_service"] = os.environ.get("PDF_READER_PORTABLE_SERVICE") == "1"
    app.config["app_state"] = AppState(settings.cache_dir)
    app.config["translation_coordinator"] = TranslationCoordinator()
    app.config["candidate_extraction_service"] = (
        None
        if settings.setup_mode
        else CandidateExtractionService(
            settings.term_extraction,
            settings.upstream.model,
        )
    )
    if app.config["portable_service"]:
        from pdf_reader.portable_runtime import (
            CONTROL_TOKEN_ENV,
            CONTROL_TOKEN_HEADER,
            HEALTH_TOKEN_ENV,
            HEALTH_TOKEN_HEADER,
            MINIMUM_TOKEN_LENGTH,
            SHUTDOWN_PATH,
            PortableShutdownController,
        )

        health_token = os.environ.get(HEALTH_TOKEN_ENV, "")
        control_token = os.environ.get(CONTROL_TOKEN_ENV, "")
        shutdown_controller = PortableShutdownController()
        app.config["portable_shutdown_controller"] = shutdown_controller

        @app.get("/api/health")
        def portable_health() -> Response | tuple[Response, int]:
            supplied = request.headers.get(HEALTH_TOKEN_HEADER, "")
            if len(health_token) < MINIMUM_TOKEN_LENGTH or not hmac.compare_digest(supplied, health_token):
                return jsonify({"status": "not_found"}), 404
            return jsonify({"status": "ok"})

        @app.post(SHUTDOWN_PATH)
        def portable_shutdown() -> Response | tuple[Response, int]:
            """认证后的协作式退出入口：只提出退出请求，不直接结束进程。

            控制令牌仅通过进程私有环境变量传入，未认证请求一律返回 404，
            不泄露端点是否存在；真正的收敛（停止接受新任务 → 等待当前任务 →
            关闭 AppState）由 main 的既有收尾路径完成。
            """

            supplied = request.headers.get(CONTROL_TOKEN_HEADER, "")
            if len(control_token) < MINIMUM_TOKEN_LENGTH or not hmac.compare_digest(supplied, control_token):
                return jsonify({"status": "not_found"}), 404
            shutdown_controller.request("launcher_request")
            return jsonify({"status": "shutting_down"}), 202

    from pdf_reader.routes import register_routes

    register_routes(app)
    return app


class _ShutdownControlChannel(Protocol):
    """协作退出信号的最小接口；服务只依赖它，便于测试注入替代实现。"""

    @property
    def reason(self) -> str | None: ...

    def request(self, reason: str) -> bool: ...

    def wait(self, timeout: float = 0.1) -> bool: ...


class _PortableWsgiServer(Protocol):
    """真实 WSGI server 的最小接口（werkzeug make_server 的返回值满足）。"""

    def serve_forever(self, poll_interval: float = 0.5) -> None: ...

    def shutdown(self) -> None: ...

    def server_close(self) -> None: ...


class _LauncherWatchdog(Protocol):
    def stop(self) -> None: ...


def _publish_readiness_failure(
    layout: paths.RuntimeLayout,
    readiness_file: Path | None,
    *,
    code: str,
    message: str,
) -> None:
    """尽力把稳定失败码写进就绪文件；失败路径上的失败不能掩盖原始退出原因。"""

    if readiness_file is None:
        return
    from pdf_reader.portable_runtime import write_readiness_failure

    try:
        write_readiness_failure(layout, readiness_file, code=code, message=message)
    except Exception:  # noqa: BLE001 - 只记录；退出码与 stderr 仍是主要诊断
        logger.warning("cannot publish portable readiness failure code=%s", code, exc_info=True)


def _make_wsgi_server(host: str, port: int, app: Flask) -> _PortableWsgiServer:
    """构造真实 WSGI server；端口被占用时 werkzeug 直接 SystemExit，由调用方归类。"""

    from werkzeug.serving import make_server

    return make_server(host, port, app, threaded=True)


def _default_launcher_watchdog(controller: _ShutdownControlChannel) -> _LauncherWatchdog | None:
    """监督每次启动专属的内核对象；PID 复用不能伪造启动器仍存活。"""

    from pdf_reader.portable_runtime import (
        LAUNCHER_LIVENESS_ENV,
        LauncherLivenessWatchdog,
        PortableEnvironmentError,
        PortableShutdownController,
        open_launcher_liveness_monitor,
    )

    try:
        monitor = open_launcher_liveness_monitor(
            paths.get_runtime_layout(),
            os.environ.get(LAUNCHER_LIVENESS_ENV, ""),
        )
    except (OSError, ValueError, paths.PathStrategyError, PortableEnvironmentError):
        logger.error("portable service cannot open the launcher kernel-liveness object", exc_info=True)
        controller.request("launcher_liveness_unavailable")
        return None
    watchdog = LauncherLivenessWatchdog(cast(PortableShutdownController, controller), monitor=monitor)
    watchdog.start()
    return watchdog


def _monitor_shutdown_channel(server: _PortableWsgiServer, controller: _ShutdownControlChannel) -> None:
    """后台等待协作退出请求，再让 server 停止接受新任务。"""

    while not controller.wait(PORTABLE_SHUTDOWN_POLL_INTERVAL):
        continue
    logger.info("portable shutdown requested: reason=%s", controller.reason)
    server.shutdown()


def _serve_portable_service(
    app: Flask,
    run_cfg: config.ServerConfig,
    *,
    layout: paths.RuntimeLayout,
    readiness_file: Path | None,
    controller: _ShutdownControlChannel,
    server_factory: Callable[[str, int, Flask], _PortableWsgiServer] | None = None,
    watchdog_factory: Callable[[_ShutdownControlChannel], _LauncherWatchdog | None] | None = None,
) -> int:
    """受认证的便携服务循环：真实绑定 → 监督启动器 → 可协作停止。

    与开发入口的 app.run 不同，这里必须持有真实 WSGI server，才能在任意时刻
    响应控制通道的退出请求；端口被其他进程占用时只发布稳定失败码，绝不终止
    占用进程。收敛顺序固定为：停止接受新任务 → 等待当前任务 → 关闭 AppState
    （由 main 既有收尾路径完成）。
    """

    from pdf_reader.portable_runtime import SERVICE_EXIT_PORT_IN_USE, SERVICE_PORT_IN_USE_CODE

    create_server = server_factory if server_factory is not None else _make_wsgi_server
    try:
        server = create_server(run_cfg.host, run_cfg.port, app)
    except (OSError, SystemExit):
        logger.error(
            "portable service cannot bind http://%s:%d: the port is owned by another process; "
            "PDF Reader never terminates a process it does not own",
            run_cfg.host,
            run_cfg.port,
        )
        _publish_readiness_failure(
            layout,
            readiness_file,
            code=SERVICE_PORT_IN_USE_CODE,
            message=(
                f"本地端口 {run_cfg.port} 已被其他程序占用；请关闭占用该端口的程序后重新启动 PDF Reader，"
                "PDF Reader 不会终止占用端口的程序"
            ),
        )
        return SERVICE_EXIT_PORT_IN_USE

    watchdog = watchdog_factory(controller) if watchdog_factory is not None else _default_launcher_watchdog(controller)
    monitor = threading.Thread(
        target=_monitor_shutdown_channel,
        args=(server, controller),
        name="pdf-reader-shutdown-monitor",
        daemon=True,
    )
    monitor.start()
    logger.info(
        "portable service listening on http://%s:%d (authenticated loopback control channel)",
        run_cfg.host,
        run_cfg.port,
    )
    try:
        server.serve_forever(poll_interval=PORTABLE_SHUTDOWN_POLL_INTERVAL)
    except KeyboardInterrupt:
        controller.request("keyboard_interrupt")
        logger.info("portable service stopped by KeyboardInterrupt")
        return 130
    finally:
        if watchdog is not None:
            watchdog.stop()
        monitor.join(timeout=PORTABLE_MONITOR_JOIN_TIMEOUT)
        try:
            server.server_close()
        except OSError:
            logger.warning("closing the portable WSGI server reported an error", exc_info=True)
    logger.info("portable service stopped: reason=%s", controller.reason)
    return 0


def main(argv: list[str] | None = None) -> int:
    """真实启动入口：解析 CLI、合并 debug 优先级、校验配置，然后启动 Flask。

    ``debug`` 仅表示“详细诊断日志模式”（日志 DEBUG + debug_trace）；
    Flask 始终以 ``debug=False, use_reloader=False`` 运行。日志初始化之后的
    致命异常统一经 ``logger.exception`` 记录并返回非零；正常
    ``KeyboardInterrupt`` 只记录 INFO，不当成 ERROR。
    """
    _ensure_utf8_stdio()
    args = _build_parser().parse_args(argv)
    portable_service = os.environ.get("PDF_READER_PORTABLE_SERVICE") == "1"
    setup_reason: str | None = None
    try:
        run_cfg = config.resolve_server_config(cli_debug=args.debug)
    except config.ConfigError as exc:
        if not portable_service:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        setup_reason = str(exc)
        run_cfg = config.ServerConfig(
            host=config.DEFAULT_HOST,
            port=config.DEFAULT_PORT,
            debug=bool(args.debug),
        )

    if portable_service and not config.is_loopback_host(run_cfg.host):
        setup_reason = "便携发行服务只允许绑定 loopback 地址"
        run_cfg = config.ServerConfig(
            host=config.DEFAULT_HOST,
            port=run_cfg.port,
            debug=run_cfg.debug,
        )

    try:
        upstream = config.validate_startup_requirements()
    except config.ConfigError as exc:
        if not portable_service:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        setup_reason = str(exc)
        upstream = config.build_upstream_runtime_config({}, strict=False)

    app = None
    try:
        settings_data: dict | None = {} if setup_reason is not None else None
        settings = config.build_app_settings(
            settings_data,
            cli_debug=args.debug,
            run_cfg=run_cfg,
            upstream=upstream,
        )
        if setup_reason is not None:
            settings = replace(settings, setup_mode=True, setup_reason=setup_reason)
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
        readiness_file = None
        layout: paths.RuntimeLayout | None = None
        try:
            shutdown_controller = app.config.get("portable_shutdown_controller")
            if portable_service:
                from pdf_reader.portable_runtime import (
                    readiness_file_from_environment,
                    write_readiness_descriptor,
                )

                layout = paths.get_runtime_layout()
                readiness_file = readiness_file_from_environment(layout)
                if readiness_file is not None:
                    health_token = os.environ.get("PDF_READER_HEALTH_TOKEN", "")
                    write_readiness_descriptor(
                        layout,
                        readiness_file,
                        host=run_cfg.host,
                        port=run_cfg.port,
                        health_token=health_token,
                    )
            if layout is not None and readiness_file is not None and shutdown_controller is not None:
                # 便携服务必须能被受认证控制通道协作关闭，因此这里持有真实 WSGI server；
                # 开发入口（python -m pdf_reader）继续使用 app.run。
                return _serve_portable_service(
                    app,
                    run_cfg,
                    layout=layout,
                    readiness_file=readiness_file,
                    controller=shutdown_controller,
                )
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
        finally:
            if readiness_file is not None:
                try:
                    readiness_file.unlink()
                except FileNotFoundError:
                    pass
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
