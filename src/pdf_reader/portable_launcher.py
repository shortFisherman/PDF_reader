"""Top-level Windows portable launcher; keeps the real user environment intact.

P1-02 的四条边界都在这里落地：

* 单实例：内核生命周期锁（Windows 命名互斥体 / POSIX flock）是唯一所有权权威。
  第二次启动只“验证并激活”已运行实例，既不启动第二个服务，也不终止任何进程。
* 就绪：data 内原子就绪描述符 + 带令牌的真实 loopback 健康探测；不使用固定 sleep
  猜测就绪，失败上报稳定错误码并写入 data/logs/launcher.log。
* 控制入口：固定三按钮控制窗口（打开阅读器 / 打开日志 / 退出程序），由 127.0.0.1
  上令牌认证的控制通道实现；关闭浏览器标签页不会退出服务，关闭控制窗口等于退出程序。
* 退出：先请服务协作退出（停止接受新任务 → 取消/等待当前任务 → 关闭 AppState），
  只有超时才由启动器兜底结束进程。
"""

from __future__ import annotations

import argparse
import hmac
import json
import logging
import os
import socketserver
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from collections.abc import Callable
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Protocol

from pdf_reader import paths
from pdf_reader.portable_instance import (
    InstanceLock,
    InstanceRecord,
    PortableInstanceError,
    create_instance_lock,
    probe_service_health,
    read_instance_record,
    remove_instance_record,
    send_launcher_command,
    send_service_shutdown,
    write_instance_record,
)
from pdf_reader.portable_runtime import (
    CONTROL_COMMANDS,
    CONTROL_PATH,
    CONTROL_TOKEN_HEADER,
    HEALTH_TOKEN_ENV,
    MINIMUM_TOKEN_LENGTH,
    PORT_RELEASE_TIMEOUT,
    READINESS_SCHEMA,
    READINESS_STATUS_ERROR,
    READY_FILE_ENV,
    SERVICE_EXIT_PORT_IN_USE,
    SERVICE_PORT_IN_USE_CODE,
    LauncherLivenessOwner,
    PortableEnvironmentError,
    build_service_environment,
    create_launcher_liveness_owner,
    loopback_base_url,
    loopback_port_in_use,
    new_control_token,
    new_health_token,
    new_readiness_file,
    probe_loopback_health,
    remove_descriptor,
    remove_service_temp_directory,
    remove_stale_liveness_files,
    remove_stale_readiness_files,
    wait_for_port_release,
)

EXIT_LAUNCHER_ERROR = 2
EXIT_SERVICE_START_FAILED = 3
EXIT_PORT_IN_USE = 4
EXIT_INSTANCE_UNAVAILABLE = 5
EXIT_SERVICE_EXITED = 6
EXIT_UI_UNAVAILABLE = 7
EXIT_INTERRUPTED = 130

PORT_IN_USE_CODE = SERVICE_PORT_IN_USE_CODE

LOGGER_NAME = "pdf_reader.launcher"
LAUNCHER_LOG_NAME = "launcher.log"
LAUNCHER_LOG_MAX_BYTES = 512 * 1024
LAUNCHER_LOG_BACKUP_COUNT = 2

CONTROL_SERVER_HOST = "127.0.0.1"
CONTROL_SERVER_JOIN_TIMEOUT = 5.0
MAXIMUM_CONTROL_BODY_BYTES = 4096

DEFAULT_ACTIVATION_TIMEOUT = 20.0
DEFAULT_ACTIVATION_INTERVAL = 0.25
DEFAULT_STARTUP_TIMEOUT = 30.0
DEFAULT_SHUTDOWN_TIMEOUT = 15.0
DEFAULT_FORCE_TIMEOUT = 10.0
SHUTDOWN_REQUEST_TIMEOUT = 2.0
READINESS_POLL_INTERVAL = 0.05
SERVICE_LOOP_POLL_INTERVAL = 0.2
WINDOW_POLL_INTERVAL_MS = 200
WINDOW_TITLE = "PDF Reader 便携版"
WINDOW_HINT = "关闭浏览器标签不会退出服务；关闭本窗口即退出程序。"

# 第二次启动无法激活已运行实例时的稳定失败码：每一种都有明确的用户可读说明。
ACTIVATION_FAILURE_CODES = frozenset(
    {
        "instance_record_missing",
        "instance_record_invalid",
        "existing_instance_unhealthy",
        "existing_instance_unreachable",
        "launcher_control_rejected",
        "launcher_control_unreachable",
    }
)

HealthProbe = Callable[[str, int, str], bool]
PortProbe = Callable[[str, int], bool]
ControlDispatch = Callable[[str], str]
InstanceHealthProbe = Callable[[InstanceRecord], bool]
WindowFactory = Callable[..., "LauncherWindow"]

logger = logging.getLogger(LOGGER_NAME)


class PortableLaunchError(RuntimeError):
    """启动器失败时携带稳定错误码，调用方据此决定退出码与用户提示。"""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class LauncherWindow(Protocol):
    """控制窗口最小契约：run 阻塞到窗口关闭为止。"""

    def run(self) -> None: ...

    def close(self) -> None: ...


def _report_error(message: str) -> None:
    """把稳定错误码同时写入启动器日志与 stderr；stderr 失败不能掩盖原始错误。"""

    logger.error("%s", message)
    try:
        print(message, file=sys.stderr)
    except (OSError, ValueError):
        pass


def reset_launcher_logging() -> None:
    """关闭并移除启动器自己的日志处理器，保证重复启动与测试环境干净。"""

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        try:
            handler.close()
        except OSError:
            pass


def _install_launcher_logging(layout: paths.RuntimeLayout) -> Path | None:
    """建立 data/logs/launcher.log；日志不可用时降级为仅 stderr 并继续启动。"""

    reset_launcher_logging()
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        log_path = layout.require_data_path(layout.log_dir / LAUNCHER_LOG_NAME, label="启动器日志")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = RotatingFileHandler(
            log_path,
            maxBytes=LAUNCHER_LOG_MAX_BYTES,
            backupCount=LAUNCHER_LOG_BACKUP_COUNT,
            encoding="utf-8",
            delay=True,
        )
    except (OSError, ValueError, paths.PathStrategyError) as exc:
        logger.warning("启动器日志不可用，仅输出到 stderr：%s", exc)
        return None
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(handler)
    return log_path


def open_log_directory(path: Path) -> bool:
    """用系统文件管理器打开日志目录；不可用时退化到默认浏览器的 file:// 视图。"""

    startfile = getattr(os, "startfile", None)
    if startfile is not None:
        try:
            startfile(str(path))
            return True
        except OSError as exc:
            logger.warning("无法用文件管理器打开日志目录：%s", exc)
    try:
        return bool(webbrowser.open(path.as_uri()))
    except Exception:  # noqa: BLE001 - 打开日志失败不影响服务本身
        logger.exception("打开日志目录失败")
        return False


def _open_target(target: str, *, opener: Callable[[str], Any] | None) -> bool:
    """用默认浏览器打开 URL；调用方决定失败时的用户可见结果。"""

    selected = webbrowser.open if opener is None else opener
    try:
        result = selected(target)
    except Exception:  # noqa: BLE001 - 没有可用浏览器时不允许终止服务
        logger.exception("打开 %s 失败", target)
        return False
    return True if result is None else bool(result)


def _service_executable(layout: paths.RuntimeLayout) -> Path:
    candidate = layout.resource_root / "PDF Reader Service.exe"
    resolved = candidate.resolve(strict=False)
    if resolved.parent != layout.resource_root.resolve(strict=False):
        raise PortableLaunchError("服务程序路径逃逸 app 目录", code="service_path_invalid")
    return resolved


def _readiness_probe_target(payload: Any) -> tuple[str, int, str]:
    """校验就绪描述符并返回真实的探测目标 (loopback 主机, 端口, 健康令牌)。"""

    if not isinstance(payload, dict) or payload.get("schema") != READINESS_SCHEMA:
        raise ValueError("invalid readiness schema")
    host = payload.get("host")
    port = payload.get("port")
    if not isinstance(host, str):
        raise ValueError("invalid readiness host")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("invalid readiness endpoint")
    token = payload.get("health_token")
    if not isinstance(token, str) or len(token) < MINIMUM_TOKEN_LENGTH:
        raise ValueError("invalid readiness health token")
    loopback_base_url(host, port)
    return host, port, token


def _readiness_endpoint(payload: Any) -> tuple[str, str]:
    """把就绪描述符规范化为 (loopback 基地址, 健康令牌)；非法内容抛 ValueError。"""

    host, port, token = _readiness_probe_target(payload)
    return loopback_base_url(host, port), token


def _read_readiness_descriptor(readiness_file: Path) -> tuple[dict[str, Any] | None, str | None]:
    """读取就绪描述符；返回 (payload, 错误说明)，两者互斥。"""

    try:
        payload = json.loads(readiness_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, "服务尚未发布就绪状态"
    except (OSError, ValueError) as exc:
        return None, f"就绪状态不可读：{exc}"
    if not isinstance(payload, dict):
        return None, "就绪状态不是 JSON 对象"
    return payload, None


def wait_until_ready(
    process: subprocess.Popen[Any],
    readiness_file: Path,
    *,
    timeout: float,
    interval: float = READINESS_POLL_INTERVAL,
    probe: HealthProbe = probe_loopback_health,
) -> str:
    """等待服务真实就绪：只有带令牌的健康探测确认通过才算 ready。

    判定顺序固定：描述符里的失败状态优先（携带服务自报错误码）→ 就绪状态做真实
    探测 → 进程提前退出 → 整体超时。任何一步都不使用固定 sleep 猜测。
    """

    deadline = time.monotonic() + max(0.0, timeout)
    last_error = "服务尚未发布就绪状态"
    while True:
        payload, read_error = _read_readiness_descriptor(readiness_file)
        if read_error is not None:
            last_error = read_error
        if payload is not None and payload.get("status") == READINESS_STATUS_ERROR:
            code = payload.get("code")
            message = payload.get("message")
            raise PortableLaunchError(
                f"服务启动失败：{message if isinstance(message, str) and message else '未提供原因'}",
                code=code if isinstance(code, str) and code else "service_start_failed",
            )
        if payload is not None:
            try:
                host, port, token = _readiness_probe_target(payload)
            except ValueError as exc:
                last_error = str(exc)
            else:
                if probe(host, port, token):
                    return loopback_base_url(host, port)
                last_error = "服务健康探测尚未通过"
        return_code = process.poll()
        if return_code is not None:
            if return_code == SERVICE_EXIT_PORT_IN_USE:
                raise PortableLaunchError(
                    "默认端口已被其他程序占用；PDF Reader 不会终止占用端口的程序",
                    code=PORT_IN_USE_CODE,
                )
            raise PortableLaunchError(
                f"服务在就绪前退出（exit={return_code}）",
                code="service_exited_before_ready",
            )
        if time.monotonic() >= deadline:
            break
        time.sleep(max(0.01, interval))
    raise PortableLaunchError(f"等待本地服务就绪超时：{last_error}", code="service_start_timeout")


def _stop_process(process: subprocess.Popen[Any], *, timeout: float = DEFAULT_FORCE_TIMEOUT) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=timeout)


class _ServiceProcessWatcher:
    """后台等待服务退出，把退出码暴露给控制窗口和收尾逻辑。"""

    def __init__(self, process: subprocess.Popen[Any]) -> None:
        self._process = process
        self._finished = threading.Event()
        self._exit_code: int | None = None
        self._thread = threading.Thread(target=self._run, name="pdf-reader-service-watch", daemon=True)

    @property
    def finished(self) -> bool:
        return self._finished.is_set()

    @property
    def exit_code(self) -> int | None:
        return self._exit_code

    def _run(self) -> None:
        try:
            code = self._process.wait()
        except Exception:  # noqa: BLE001 - 等待失败按“退出码未知”处理
            logger.warning("无法获取服务退出码", exc_info=True)
            code = None
        self._exit_code = code if isinstance(code, int) else None
        self._finished.set()

    def start(self) -> None:
        self._thread.start()

    def wait(self, timeout: float) -> bool:
        return self._finished.wait(max(0.0, timeout))


class _ControlRequestHandler(BaseHTTPRequestHandler):
    """控制通道处理器：只认令牌 + 固定命令；未知路径、无令牌一律 404。"""

    server: LauncherControlServer

    def log_message(self, format: str, *args: Any) -> None:
        """抑制默认访问日志：控制请求路径与请求头都不允许进入日志。"""

    def do_GET(self) -> None:
        self._respond(404, {"status": "not_found"})

    def do_POST(self) -> None:
        if urllib.parse.urlsplit(self.path).path != CONTROL_PATH:
            self._respond(404, {"status": "not_found"})
            return
        if not self._authorized():
            self._respond(404, {"status": "not_found"})
            return
        raw = self._read_body()
        if raw is None:
            self._respond(400, {"status": "invalid_request"})
            return
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, ValueError):
            self._respond(400, {"status": "invalid_request"})
            return
        command = payload.get("command") if isinstance(payload, dict) else None
        if not isinstance(command, str) or command not in CONTROL_COMMANDS:
            self._respond(400, {"status": "invalid_command"})
            return
        try:
            detail = self.server.dispatch_command(command)
        except Exception:  # noqa: BLE001 - 单条命令失败不能让控制通道整体不可用
            logger.exception("控制命令执行失败 command=%s", command)
            self._respond(500, {"status": "command_failed"})
            return
        self._respond(200, {"status": "accepted", "detail": detail})

    def _authorized(self) -> bool:
        supplied = self.headers.get(CONTROL_TOKEN_HEADER, "")
        token = self.server.control_token
        if not supplied or not token:
            return False
        try:
            return hmac.compare_digest(supplied, token)
        except TypeError:
            return False

    def _read_body(self) -> bytes | None:
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            return None
        if length <= 0:
            return b""
        if length > MAXIMUM_CONTROL_BODY_BYTES:
            return None
        return self.rfile.read(length)

    def _respond(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except OSError:
            logger.warning("控制通道响应写入失败（对端可能已断开）")


class LauncherControlServer(ThreadingHTTPServer):
    """只监听 127.0.0.1 的令牌认证控制通道；端口由内核分配，仅本机实例记录可见。"""

    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, *, dispatch: ControlDispatch, control_token: str) -> None:
        if not isinstance(control_token, str) or len(control_token) < MINIMUM_TOKEN_LENGTH:
            raise PortableLaunchError("启动器控制令牌无效", code="launcher_control_token_invalid")
        self.dispatch_command = dispatch
        self.control_token = control_token
        self._thread: threading.Thread | None = None
        super().__init__((CONTROL_SERVER_HOST, 0), _ControlRequestHandler)

    @property
    def base_url(self) -> str:
        return loopback_base_url(CONTROL_SERVER_HOST, int(self.server_address[1]))

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self.serve_forever, name="pdf-reader-launcher-control", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        thread = self._thread
        self._thread = None
        try:
            self.shutdown()
        except Exception:  # noqa: BLE001 - 关停失败不能覆盖真正的退出原因
            logger.warning("控制通道关停失败", exc_info=True)
        if thread is not None:
            thread.join(timeout=CONTROL_SERVER_JOIN_TIMEOUT)
        try:
            self.server_close()
        except OSError:
            logger.warning("控制通道套接字关闭失败")

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = int(port)

    def handle_error(self, request: Any, client_address: Any) -> None:
        logger.warning("控制通道请求处理失败（异常细节已省略）")


# === launcher companion ===


class LauncherCommandDispatcher:
    """三个固定控制命令的唯一实现：控制窗口与 loopback 控制通道共用同一 dispatch。"""

    def __init__(
        self,
        *,
        service_url: str,
        logs_path: Path,
        opener: Callable[[str], Any] | None = None,
        logs_opener: Callable[[Path], bool] | None = None,
    ) -> None:
        self._service_url = service_url
        self._logs_path = logs_path
        self._opener = opener
        self._logs_opener = open_log_directory if logs_opener is None else logs_opener
        self._quit = threading.Event()

    @property
    def service_url(self) -> str:
        return self._service_url

    @property
    def quit_requested(self) -> bool:
        return self._quit.is_set()

    def request_quit(self) -> None:
        """请求退出程序；只置位，收尾工作全部由启动器主流程负责。"""

        self._quit.set()

    def wait_for_quit(self, timeout: float) -> bool:
        """有界等待退出请求；无窗口模式用它代替窗口消息循环。"""

        return self._quit.wait(max(0.0, timeout))

    def dispatch(self, command: str) -> str:
        if command == "open_reader":
            # 打开阅读器只影响浏览器：关闭标签页不等于退出服务。
            return "opened" if _open_target(self._service_url, opener=self._opener) else "unavailable"
        if command == "open_logs":
            return "opened" if self._open_logs() else "unavailable"
        if command == "quit":
            self.request_quit()
            return "quitting"
        raise ValueError(f"未知控制命令：{command}")

    def _open_logs(self) -> bool:
        try:
            self._logs_path.mkdir(parents=True, exist_ok=True)
        except OSError:
            logger.warning("日志目录不可创建：%s", self._logs_path)
        try:
            return bool(self._logs_opener(self._logs_path))
        except Exception:  # noqa: BLE001 - 打开日志失败不影响服务本身
            logger.warning("打开日志目录失败", exc_info=True)
            return False


class _TkinterLauncherWindow:
    """固定三按钮控制窗口；关闭控制窗口等于退出程序。"""

    def __init__(
        self,
        *,
        root: Any,
        ttk_module: Any,
        dispatch: ControlDispatch,
        should_stop: Callable[[], bool],
        interval_ms: int = WINDOW_POLL_INTERVAL_MS,
    ) -> None:
        self._root = root
        self._dispatch = dispatch
        self._should_stop = should_stop
        self._interval_ms = max(50, int(interval_ms))
        self._closed = False
        root.title(WINDOW_TITLE)
        root.resizable(False, False)
        frame = ttk_module.Frame(root, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")
        ttk_module.Label(frame, text=WINDOW_TITLE).grid(row=0, column=0, sticky="w")
        self._add_button(ttk_module, frame, row=1, text="打开阅读器", command="open_reader")
        self._add_button(ttk_module, frame, row=2, text="打开日志", command="open_logs")
        self._add_button(ttk_module, frame, row=3, text="退出程序", command="quit")
        ttk_module.Label(frame, text=WINDOW_HINT, wraplength=320, justify="left").grid(
            row=4, column=0, sticky="w", pady=(12, 0)
        )
        root.protocol("WM_DELETE_WINDOW", self.close)
        self._schedule()

    def _add_button(self, ttk_module: Any, frame: Any, *, row: int, text: str, command: str) -> None:
        ttk_module.Button(
            frame,
            text=text,
            width=18,
            command=lambda selected=command: self._dispatch(selected),
        ).grid(row=row, column=0, sticky="ew", pady=2)

    def _schedule(self) -> None:
        if self._closed:
            return
        self._root.after(self._interval_ms, self._poll)

    def _poll(self) -> None:
        if self._should_stop():
            self.close()
            return
        self._schedule()

    def run(self) -> None:
        self._root.mainloop()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._root.destroy()
        except Exception:  # noqa: BLE001 - 关闭窗口失败不能阻止启动器收尾
            logger.warning("控制窗口关闭失败", exc_info=True)


def _import_tkinter() -> tuple[Any, Any] | None:
    """按需导入 tkinter/ttk；缺少 Tcl/Tk 或 GUI 依赖时返回 None。"""

    try:
        import tkinter
        from tkinter import ttk
    except Exception:  # noqa: BLE001 - 缺少 GUI 依赖不是启动失败
        logger.error("当前环境没有可用的 tkinter，无法创建必需的控制窗口")
        return None
    return tkinter, ttk


def create_tkinter_window(*, dispatch: ControlDispatch, should_stop: Callable[[], bool]) -> LauncherWindow | None:
    """创建固定三按钮控制窗口；没有图形会话或控件失败时返回 None。"""

    modules = _import_tkinter()
    if modules is None:
        return None
    tkinter_module, ttk_module = modules
    try:
        root = tkinter_module.Tk()
    except Exception:  # noqa: BLE001 - caller turns this into a stable launcher error
        logger.error("无法创建必需的控制窗口（没有图形会话）", exc_info=True)
        return None
    try:
        return _TkinterLauncherWindow(
            root=root,
            ttk_module=ttk_module,
            dispatch=dispatch,
            should_stop=should_stop,
        )
    except Exception:  # noqa: BLE001 - caller turns this into a stable launcher error
        logger.error("必需的控制窗口初始化失败", exc_info=True)
        try:
            root.destroy()
        except Exception:  # noqa: BLE001 - 清理失败无需上报
            pass
        return None


def _create_launcher_window(
    factory: WindowFactory | None,
    *,
    dispatch: ControlDispatch,
    should_stop: Callable[[], bool],
) -> LauncherWindow | None:
    """按注入的工厂创建控制窗口；异常统一返回 None，由主状态机稳定失败。"""

    selected = create_tkinter_window if factory is None else factory
    try:
        return selected(dispatch=dispatch, should_stop=should_stop)
    except Exception:  # noqa: BLE001 - 窗口不可用不允许影响服务
        logger.error("必需的控制窗口不可用", exc_info=True)
        return None


def _run_launcher_loop(
    dispatcher: LauncherCommandDispatcher,
    *,
    watcher: _ServiceProcessWatcher,
    window_factory: WindowFactory | None = None,
    no_ui: bool = False,
    poll_interval: float = SERVICE_LOOP_POLL_INTERVAL,
    on_ready: Callable[[], None] | None = None,
) -> bool:
    """阻塞到用户退出或服务结束；返回是否收到退出请求。

    语义固定：关闭控制窗口等于请求退出程序；关闭浏览器标签页只影响浏览器，不会
    退出服务。默认模式没有可用 UI 时抛出稳定错误，由主状态机协作关闭服务；只有
    显式 ``--no-ui`` 测试/诊断模式允许无窗口等待。
    """

    def should_stop() -> bool:
        return dispatcher.quit_requested or watcher.finished

    window = (
        None
        if no_ui
        else _create_launcher_window(
            window_factory,
            dispatch=dispatcher.dispatch,
            should_stop=should_stop,
        )
    )
    if window is None and not no_ui:
        raise PortableLaunchError(
            "无法创建必需的启动器控制窗口；服务将协作退出，请检查发行包中的 Tk/Tcl 运行时",
            code="launcher_ui_unavailable",
        )
    if on_ready is not None:
        on_ready()
    if no_ui:
        while not should_stop():
            dispatcher.wait_for_quit(poll_interval)
    else:
        assert window is not None
        try:
            window.run()
        except Exception as exc:
            raise PortableLaunchError(
                f"启动器控制窗口运行失败：{exc}",
                code="launcher_ui_unavailable",
            ) from exc
        if not dispatcher.quit_requested and not watcher.finished:
            dispatcher.request_quit()
    return dispatcher.quit_requested


def _endpoint_from_url(url: str) -> tuple[str, int]:
    """把服务基地址解析为已验证的 (loopback 主机, 端口)；非 loopback 一律拒绝。"""

    parsed = urllib.parse.urlsplit(url)
    try:
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise PortableLaunchError(f"服务地址无效：{url}", code="service_url_invalid") from exc
    if parsed.scheme != "http" or not host or port is None:
        raise PortableLaunchError(f"服务地址无效：{url}", code="service_url_invalid")
    loopback_base_url(host, port)
    return host, port


def _probe_instance_health(
    record: InstanceRecord,
    *,
    probe: InstanceHealthProbe = probe_service_health,
) -> bool:
    """带令牌探测已运行实例；任何异常都等价于“实例不可用”。"""

    try:
        return bool(probe(record))
    except Exception:  # noqa: BLE001 - 探测失败不允许影响判断之外的行为
        logger.warning("探测已运行实例的健康状态失败", exc_info=True)
        return False


def _clear_stale_instance_state(
    layout: paths.RuntimeLayout,
    *,
    port_probe: PortProbe = loopback_port_in_use,
    timeout: float = PORT_RELEASE_TIMEOUT,
) -> tuple[tuple[str, int], ...]:
    """清理上一次异常退出留下的元数据；只做有界等待，绝不终止任何进程。

    只有已经持有内核实例锁的启动器才允许调用：拿到锁就证明上一个启动器进程已经
    消失（正常退出、崩溃或强制结束都会由内核释放锁），因此残留服务收到的是受认证
    的协作退出请求，而不是强杀。返回超时后仍被占用的端点，供日志与测试断言使用。
    """

    endpoints: list[tuple[str, int]] = []
    try:
        stale_record = read_instance_record(layout)
    except PortableInstanceError as exc:
        stale_record = None
        logger.info("实例记录不可用，按陈旧状态清理：%s", exc)
    if stale_record is not None:
        endpoints.append((stale_record.service_host, stale_record.service_port))
        try:
            send_service_shutdown(stale_record, timeout=SHUTDOWN_REQUEST_TIMEOUT)
            logger.info("已请求上一次遗留的服务进程协作退出")
        except PortableInstanceError as exc:
            logger.info("没有需要回收的遗留服务：%s", exc)
    for removed in remove_stale_readiness_files(layout):
        logger.info("已清理陈旧就绪文件：%s", removed.name)
    for removed in remove_stale_liveness_files(layout):
        logger.info("已清理陈旧启动器存活锁名称：%s", removed.name)
    try:
        remove_instance_record(layout)
    except (OSError, paths.PathStrategyError) as exc:
        logger.warning("清理陈旧实例记录失败：%s", exc)
    still_occupied: list[tuple[str, int]] = []
    for host, port in endpoints:
        if wait_for_port_release(host, port, timeout=timeout, probe=port_probe):
            logger.info("上一次的服务端口已经释放：%s:%d", host, port)
        else:
            still_occupied.append((host, port))
            logger.warning("上一次的服务端口仍未释放：%s:%d（不终止任何进程，交由服务自报端口冲突）", host, port)
    return tuple(still_occupied)


def _activate_existing_instance(
    layout: paths.RuntimeLayout,
    *,
    timeout: float = DEFAULT_ACTIVATION_TIMEOUT,
    interval: float = DEFAULT_ACTIVATION_INTERVAL,
    health_probe: InstanceHealthProbe = probe_service_health,
    acquire_ownership: Callable[[], bool] | None = None,
) -> int | None:
    """验证并激活已运行实例：绝不启动第二个服务，也绝不终止任何进程。

    返回 0 表示已成功激活并请求打开阅读器；返回 None 表示 acquire_ownership
    成功——原实例已退出，调用方接管单实例所有权并继续启动服务；返回
    EXIT_INSTANCE_UNAVAILABLE 表示超时内无法确认现有实例可用，此时上报的错误码
    始终落在 ACTIVATION_FAILURE_CODES 内。
    """

    deadline = time.monotonic() + max(0.0, timeout)
    code = "instance_record_missing"
    detail = "已运行的 PDF Reader 实例还没有发布可用的实例状态"
    while True:
        try:
            record = read_instance_record(layout)
        except PortableInstanceError as exc:
            record = None
            code, detail = exc.code, str(exc)
        if record is not None:
            if _probe_instance_health(record, probe=health_probe):
                try:
                    outcome = send_launcher_command(record, "open_reader")
                except PortableInstanceError as exc:
                    code, detail = exc.code, str(exc)
                else:
                    if outcome == "opened":
                        logger.info("已激活运行中的 PDF Reader 实例并打开阅读器")
                        return 0
                    code = "launcher_control_rejected"
                    detail = f"已运行的 PDF Reader 实例无法打开阅读器（detail={outcome}）"
            else:
                code = "existing_instance_unhealthy"
                detail = "已运行的 PDF Reader 实例尚未通过令牌健康探测"
        if acquire_ownership is not None and acquire_ownership():
            logger.info("原实例已经退出，当前进程接管单实例所有权")
            return None
        if time.monotonic() >= deadline:
            break
        time.sleep(max(0.01, interval))
    if code not in ACTIVATION_FAILURE_CODES:
        code = "instance_record_invalid"
    _report_error(f"ERROR [{code}]: {detail}")
    return EXIT_INSTANCE_UNAVAILABLE


def _acquire_or_activate(
    layout: paths.RuntimeLayout,
    lock: InstanceLock,
    *,
    activation_timeout: float = DEFAULT_ACTIVATION_TIMEOUT,
    activation_interval: float = DEFAULT_ACTIVATION_INTERVAL,
    health_probe: InstanceHealthProbe = probe_service_health,
) -> int | None:
    """取得单实例所有权，或验证并激活已运行实例。

    返回 None 表示当前进程持有内核锁，调用方必须继续启动服务；其他返回值是调用方
    应当直接使用的启动器退出码。
    """

    if lock.acquire():
        return None
    logger.info("另一个 PDF Reader 实例持有单实例锁，改为验证并激活现有实例")
    return _activate_existing_instance(
        layout,
        timeout=activation_timeout,
        interval=activation_interval,
        health_probe=health_probe,
        acquire_ownership=lock.acquire,
    )


def _service_exit_code(process: subprocess.Popen[Any], watcher: _ServiceProcessWatcher) -> int | None:
    """读取服务退出码；后台等待线程未就绪时做有界等待，绝不无限阻塞。"""

    if watcher.finished:
        return watcher.exit_code
    code = process.returncode
    if isinstance(code, int):
        return code
    if watcher.wait(DEFAULT_FORCE_TIMEOUT):
        return watcher.exit_code
    code = process.returncode
    return code if isinstance(code, int) else None


def _exit_code_for(service_code: int | None) -> int:
    """把服务退出码映射为启动器退出码；端口冲突与运行期崩溃各自稳定可识别。"""

    if service_code is None or service_code == 0:
        return 0
    if service_code == SERVICE_EXIT_PORT_IN_USE:
        return EXIT_PORT_IN_USE
    return EXIT_SERVICE_EXITED


def run_portable_launcher(
    launcher_executable: str | Path,
    *,
    startup_timeout: float = DEFAULT_STARTUP_TIMEOUT,
    activation_timeout: float = DEFAULT_ACTIVATION_TIMEOUT,
    activation_interval: float = DEFAULT_ACTIVATION_INTERVAL,
    shutdown_timeout: float = DEFAULT_SHUTDOWN_TIMEOUT,
    force_timeout: float = DEFAULT_FORCE_TIMEOUT,
    window_factory: WindowFactory | None = None,
    browser: Callable[[str], Any] | None = None,
    logs_opener: Callable[[Path], bool] | None = None,
    lock_factory: Callable[[paths.RuntimeLayout], InstanceLock] | None = None,
    health_probe: HealthProbe | None = None,
    port_probe: PortProbe | None = None,
    no_ui: bool = False,
    no_browser: bool = False,
) -> int:
    """便携启动器主流程：单实例 → 启动服务 → 真实健康探测 → 打开阅读器 → 协作退出。

    完整边界：

    * 单实例：内核锁是唯一所有权权威；第二次启动只验证并激活现有实例，既不启动
      第二个服务，也不终止任何进程。
    * 就绪：不使用固定 sleep 猜测，只相信带令牌的真实 loopback 健康探测。
    * 退出：先请求服务协作退出（停止接受新任务 → 取消/等待当前任务 → 关闭
      AppState），只有超时才由启动器兜底结束自己启动的进程。
    """

    selected_lock_factory = create_instance_lock if lock_factory is None else lock_factory
    selected_health_probe = probe_loopback_health if health_probe is None else health_probe
    selected_port_probe = loopback_port_in_use if port_probe is None else port_probe

    def instance_health_probe(record: InstanceRecord) -> bool:
        """把 loopback 健康探测适配到实例记录；注入的探针贯穿就绪与激活两条路径。"""

        return bool(selected_health_probe(record.service_host, record.service_port, record.health_token))

    try:
        layout = paths.RuntimeLayout.portable_from_executable(launcher_executable)
        paths.prepare_runtime_layout(layout)
    except (OSError, ValueError, paths.PathStrategyError) as exc:
        _report_error(f"ERROR [portable_layout_unavailable]: {exc}")
        return EXIT_LAUNCHER_ERROR
    _install_launcher_logging(layout)
    logger.info("便携启动器启动：launcher=%s", launcher_executable)

    lock: InstanceLock | None = None
    readiness_file: Path | None = None
    service_temp: Path | None = None
    process: subprocess.Popen[Any] | None = None
    watcher: _ServiceProcessWatcher | None = None
    control_server: LauncherControlServer | None = None
    liveness_owner: LauncherLivenessOwner | None = None
    record_written = False
    service_stopped = False

    def ensure_service_stopped() -> None:
        """只结束本启动器自己启动的服务进程；幂等，绝不影响其他进程。"""

        nonlocal service_stopped
        if service_stopped or process is None:
            return
        service_stopped = True
        if watcher is not None and watcher.finished:
            return
        _stop_process(process, timeout=force_timeout)

    try:
        try:
            lock = selected_lock_factory(layout)
        except (OSError, paths.PathStrategyError) as exc:
            _report_error(f"ERROR [instance_lock_unavailable]: 无法创建单实例锁：{exc}")
            return EXIT_LAUNCHER_ERROR
        try:
            ownership = _acquire_or_activate(
                layout,
                lock,
                activation_timeout=activation_timeout,
                activation_interval=activation_interval,
                health_probe=instance_health_probe,
            )
        except (OSError, PortableEnvironmentError, paths.PathStrategyError) as exc:
            # 内核锁不可用时必须是稳定错误码：绝不在异常里继续启动第二个服务。
            _report_error(f"ERROR [instance_lock_unavailable]: 无法使用单实例锁：{exc}")
            return EXIT_LAUNCHER_ERROR
        if ownership is not None:
            return ownership

        logger.info("已取得单实例所有权：data=%s", layout.data_root)
        _clear_stale_instance_state(layout, port_probe=selected_port_probe)

        service_exe = _service_executable(layout)
        if not service_exe.is_file():
            _report_error("ERROR [service_executable_missing]: 缺少 app/PDF Reader Service.exe，无法启动便携服务")
            return EXIT_LAUNCHER_ERROR

        health_token = new_health_token()
        service_control_token = new_control_token()
        readiness_file = new_readiness_file(layout)
        try:
            liveness_owner = create_launcher_liveness_owner(layout)
            child_environment = build_service_environment(
                layout,
                control_token=service_control_token,
                launcher_liveness=liveness_owner.descriptor,
            )
        except (OSError, ValueError, paths.PathStrategyError, PortableEnvironmentError) as exc:
            _report_error(f"ERROR [launcher_liveness_unavailable]: 无法建立启动器存活监督：{exc}")
            return EXIT_LAUNCHER_ERROR
        child_environment[READY_FILE_ENV] = str(readiness_file)
        child_environment[HEALTH_TOKEN_ENV] = health_token
        service_temp = Path(child_environment["TEMP"])
        command = [str(service_exe), "--launcher-executable", str(launcher_executable)]
        logger.info("启动便携服务：%s", service_exe.name)
        try:
            process = subprocess.Popen(command, cwd=str(layout.portable_root), env=child_environment)
        except OSError as exc:
            _report_error(f"ERROR [service_spawn_failed]: 无法启动便携服务：{exc}")
            return EXIT_SERVICE_START_FAILED

        try:
            service_url = wait_until_ready(
                process,
                readiness_file,
                timeout=startup_timeout,
                probe=selected_health_probe,
            )
        except PortableLaunchError as exc:
            _report_error(f"ERROR [{exc.code}]: {exc}")
            ensure_service_stopped()
            return EXIT_PORT_IN_USE if exc.code == PORT_IN_USE_CODE else EXIT_SERVICE_START_FAILED
        logger.info("服务已经通过令牌健康探测：%s", service_url)

        watcher = _ServiceProcessWatcher(process)
        watcher.start()
        dispatcher = LauncherCommandDispatcher(
            service_url=service_url,
            logs_path=layout.log_dir,
            opener=browser,
            logs_opener=logs_opener,
        )
        launcher_control_token = new_control_token()
        host, port = _endpoint_from_url(service_url)
        try:
            control_server = LauncherControlServer(dispatch=dispatcher.dispatch, control_token=launcher_control_token)
            control_server.start()
            record = InstanceRecord(
                pid=os.getpid(),
                created_at=datetime.now(UTC).isoformat(),
                launcher_host=CONTROL_SERVER_HOST,
                launcher_port=int(control_server.server_address[1]),
                control_token=launcher_control_token,
                service_host=host,
                service_port=port,
                health_token=health_token,
                service_control_token=service_control_token,
            )
            write_instance_record(layout, record)
        except (OSError, ValueError, paths.PathStrategyError, PortableLaunchError) as exc:
            _report_error(f"ERROR [instance_record_unwritable]: 无法发布实例状态：{exc}")
            ensure_service_stopped()
            return EXIT_LAUNCHER_ERROR
        record_written = True
        logger.info("控制通道已就绪：%s", control_server.base_url)

        def open_reader_when_control_is_ready() -> None:
            if no_browser:
                return
            outcome = dispatcher.dispatch("open_reader")
            if outcome != "opened":
                logger.warning("自动打开阅读器失败（detail=%s）", outcome)

        def request_cooperative_stop() -> None:
            if watcher is None or watcher.finished:
                return
            logger.info("退出程序：请求服务协作退出")
            try:
                send_service_shutdown(record, timeout=SHUTDOWN_REQUEST_TIMEOUT)
            except PortableInstanceError as exc:
                logger.warning("协作退出请求失败：%s", exc)
            if not watcher.wait(shutdown_timeout):
                logger.warning("服务未在 %.1f 秒内协作退出，启动器兜底结束该进程", shutdown_timeout)
                ensure_service_stopped()

        try:
            quit_requested = _run_launcher_loop(
                dispatcher,
                watcher=watcher,
                window_factory=window_factory,
                no_ui=no_ui,
                on_ready=open_reader_when_control_is_ready,
            )
        except PortableLaunchError as exc:
            if watcher.finished:
                _report_error("ERROR [service_exited_while_running]: 服务在控制窗口建立期间自行退出")
                return EXIT_SERVICE_EXITED
            _report_error(f"ERROR [{exc.code}]: {exc}")
            request_cooperative_stop()
            return EXIT_UI_UNAVAILABLE

        if watcher.finished and not quit_requested:
            service_code = _service_exit_code(process, watcher)
            _report_error(f"ERROR [service_exited_while_running]: 服务在用户请求退出前结束（exit={service_code}）")
            return EXIT_SERVICE_EXITED

        request_cooperative_stop()
        return _exit_code_for(_service_exit_code(process, watcher))
    except KeyboardInterrupt:
        _report_error("ERROR [launcher_interrupted]: 启动器被中断，正在关闭便携服务")
        ensure_service_stopped()
        return EXIT_INTERRUPTED
    finally:
        if control_server is not None:
            control_server.stop()
        ensure_service_stopped()
        if liveness_owner is not None:
            try:
                liveness_owner.close()
            except OSError:
                logger.warning("释放启动器存活对象失败", exc_info=True)
        if record_written:
            try:
                remove_instance_record(layout)
            except (OSError, paths.PathStrategyError):
                logger.warning("清理实例记录失败", exc_info=True)
        if readiness_file is not None:
            try:
                remove_descriptor(layout, readiness_file)
            except (OSError, paths.PathStrategyError):
                logger.warning("清理就绪文件失败", exc_info=True)
        if service_temp is not None:
            try:
                remove_service_temp_directory(layout, service_temp)
            except (OSError, paths.PathStrategyError, PortableEnvironmentError):
                logger.warning("清理服务临时目录失败", exc_info=True)
        if lock is not None:
            try:
                lock.release()
            except OSError:
                logger.warning("释放单实例锁失败", exc_info=True)
        logger.info("便携启动器已退出")


def _build_parser() -> argparse.ArgumentParser:
    """便携启动器的隐藏参数：双击入口不暴露 CLI 契约，参数只服务于诊断与测试。"""

    parser = argparse.ArgumentParser(prog="PDF Reader.exe", add_help=False)
    parser.add_argument("--launcher-executable", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--startup-timeout", type=float, default=DEFAULT_STARTUP_TIMEOUT, help=argparse.SUPPRESS)
    parser.add_argument("--no-browser", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--no-ui", action="store_true", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    """冻结入口：以自身 EXE 为便携根启动；启动器从不改写自身环境。"""

    args = _build_parser().parse_args(argv)
    launcher_executable = args.launcher_executable or sys.executable
    return run_portable_launcher(
        launcher_executable,
        startup_timeout=args.startup_timeout,
        no_browser=args.no_browser,
        no_ui=args.no_ui,
    )


if __name__ == "__main__":
    raise SystemExit(main())
