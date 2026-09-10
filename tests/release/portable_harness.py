"""P1-02 测试夹具：真实 loopback stub、假服务进程与便携布局辅助。

这里只放跨文件复用的测试工具，不含断言。所有 stub 都是进程内真实 HTTP 服务，
因此单实例、就绪探测、控制命令与协作退出都可以在不启动真实便携服务的前提下，
按真实协议（令牌头 + 状态码 + JSON 契约）验证。
"""

from __future__ import annotations

import hmac
import json
import os
import socket
import subprocess
import threading
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from pdf_reader import paths, portable_instance, portable_runtime

LOOPBACK_HOST = "127.0.0.1"
DEFAULT_LAUNCHER_TOKEN = "launcher-token-" + "l" * 32
DEFAULT_HEALTH_TOKEN = "health-token-" + "h" * 32
DEFAULT_SERVICE_CONTROL_TOKEN = "service-token-" + "s" * 32


def make_portable_layout(tmp_path: Path, *, name: str = "PDF Reader 中文 portable") -> paths.RuntimeLayout:
    """构造完整便携布局（含 app/ 与顶层启动器），并创建全部受管目录。"""

    root = tmp_path / name
    (root / "app").mkdir(parents=True, exist_ok=True)
    launcher = root / "PDF Reader.exe"
    launcher.write_bytes(b"")
    layout = paths.RuntimeLayout.portable_from_executable(launcher)
    paths.prepare_runtime_layout(layout)
    return layout


def launcher_executable(layout: paths.RuntimeLayout) -> Path:
    assert layout.portable_root is not None
    return layout.portable_root / "PDF Reader.exe"


def service_executable(layout: paths.RuntimeLayout) -> Path:
    return layout.resource_root / "PDF Reader Service.exe"


def create_service_executable(layout: paths.RuntimeLayout) -> Path:
    target = service_executable(layout)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"")
    return target


def instance_record_path(layout: paths.RuntimeLayout) -> Path:
    return portable_runtime.instance_record_path(layout)


def readiness_files(layout: paths.RuntimeLayout) -> tuple[Path, ...]:
    if not layout.temp_dir.is_dir():
        return ()
    return tuple(sorted(layout.temp_dir.glob(f"{portable_runtime.READINESS_FILE_PREFIX}*.json")))


def service_temp_directories(layout: paths.RuntimeLayout) -> tuple[Path, ...]:
    if not layout.temp_dir.is_dir():
        return ()
    return tuple(sorted(path for path in layout.temp_dir.iterdir() if path.is_dir()))


def free_loopback_port() -> int:
    """返回一个刚刚释放的 loopback 端口，用于模拟“没有服务在监听”。"""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((LOOPBACK_HOST, 0))
        return int(probe.getsockname()[1])


def make_instance_record(
    *,
    service_port: int,
    launcher_port: int,
    health_token: str = DEFAULT_HEALTH_TOKEN,
    service_control_token: str = DEFAULT_SERVICE_CONTROL_TOKEN,
    control_token: str = DEFAULT_LAUNCHER_TOKEN,
    service_host: str = LOOPBACK_HOST,
    launcher_host: str = LOOPBACK_HOST,
    pid: int | None = None,
) -> portable_instance.InstanceRecord:
    """构造一条合法的实例记录；默认令牌与 stub 端点默认令牌一致。"""

    return portable_instance.InstanceRecord(
        pid=os.getpid() if pid is None else pid,
        created_at=datetime.now(UTC).isoformat(),
        launcher_host=launcher_host,
        launcher_port=launcher_port,
        control_token=control_token,
        service_host=service_host,
        service_port=service_port,
        health_token=health_token,
        service_control_token=service_control_token,
    )


class _StubHttpServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    endpoint: StubLoopbackEndpoint


class _StubHandler(BaseHTTPRequestHandler):
    """按真实协议回答 /api/health、/api/control、/api/shutdown 的最小处理器。"""

    server: _StubHttpServer

    def log_message(self, format: str, *args: Any) -> None:
        """静默 stub 访问日志：测试输出不打印每条请求。"""

    def do_GET(self) -> None:
        endpoint = self.server.endpoint
        path = urllib.parse.urlsplit(self.path).path
        endpoint.requests.append(("GET", path))
        if path != "/api/health":
            self._respond(404, {"status": "not_found"})
            return
        token = self.headers.get(portable_runtime.HEALTH_TOKEN_HEADER, "")
        if not _token_matches(token, endpoint.health_token):
            self._respond(404, {"status": "not_found"})
            return
        endpoint.health_hits += 1
        self._respond(endpoint.health_status, endpoint.health_payload)

    def do_POST(self) -> None:
        endpoint = self.server.endpoint
        path = urllib.parse.urlsplit(self.path).path
        endpoint.requests.append(("POST", path))
        body = self._read_body()
        if path == portable_runtime.SHUTDOWN_PATH:
            self._handle_shutdown(endpoint, body)
            return
        if path == portable_runtime.CONTROL_PATH:
            self._handle_control(endpoint, body)
            return
        self._respond(404, {"status": "not_found"})

    def _handle_shutdown(self, endpoint: StubLoopbackEndpoint, body: bytes) -> None:
        token = self.headers.get(portable_runtime.CONTROL_TOKEN_HEADER, "")
        if not _token_matches(token, endpoint.service_control_token):
            self._respond(404, {"status": "not_found"})
            return
        endpoint.shutdown_requests += 1
        endpoint.shutdown_bodies.append(body)
        if endpoint.on_shutdown is not None:
            endpoint.on_shutdown()
        self._respond(endpoint.shutdown_status, endpoint.shutdown_payload)

    def _handle_control(self, endpoint: StubLoopbackEndpoint, body: bytes) -> None:
        token = self.headers.get(portable_runtime.CONTROL_TOKEN_HEADER, "")
        if not _token_matches(token, endpoint.launcher_control_token):
            self._respond(404, {"status": "not_found"})
            return
        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except (UnicodeDecodeError, ValueError):
            self._respond(400, {"status": "invalid_command"})
            return
        command = payload.get("command") if isinstance(payload, dict) else None
        if not isinstance(command, str) or command not in portable_runtime.CONTROL_COMMANDS:
            self._respond(400, {"status": "invalid_command"})
            return
        endpoint.control_commands.append(command)
        if endpoint.on_control is not None:
            endpoint.on_control(command)
        self._respond(endpoint.control_status, endpoint.control_payload)

    def _read_body(self) -> bytes:
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            return b""
        if length <= 0:
            return b""
        return self.rfile.read(length)

    def _respond(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _token_matches(supplied: str, expected: str | None) -> bool:
    if expected is None or not supplied:
        return False
    try:
        return hmac.compare_digest(supplied, expected)
    except TypeError:
        return False


class StubLoopbackEndpoint:
    """进程内真实 HTTP 服务：健康 / 控制 / 退出三个端点都按真实契约响应。"""

    def __init__(
        self,
        *,
        health_token: str = DEFAULT_HEALTH_TOKEN,
        service_control_token: str = DEFAULT_SERVICE_CONTROL_TOKEN,
        launcher_control_token: str | None = DEFAULT_LAUNCHER_TOKEN,
    ) -> None:
        self.health_token = health_token
        self.service_control_token = service_control_token
        self.launcher_control_token = launcher_control_token
        self.health_status = 200
        self.health_payload: dict[str, Any] = {"status": "ok"}
        self.shutdown_status = 202
        self.shutdown_payload: dict[str, Any] = {"status": "shutting_down"}
        self.control_status = 200
        self.control_payload: dict[str, Any] = {"status": "accepted", "detail": "opened"}
        self.health_hits = 0
        self.shutdown_requests = 0
        self.shutdown_bodies: list[bytes] = []
        self.control_commands: list[str] = []
        self.requests: list[tuple[str, str]] = []
        self.on_shutdown: Callable[[], None] | None = None
        self.on_control: Callable[[str], None] | None = None
        self._server = _StubHttpServer((LOOPBACK_HOST, 0), _StubHandler)
        self._server.endpoint = self
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    @property
    def base_url(self) -> str:
        return portable_runtime.loopback_base_url(LOOPBACK_HOST, self.port)

    def start(self) -> StubLoopbackEndpoint:
        if self._thread is None:
            self._thread = threading.Thread(
                target=self._server.serve_forever,
                kwargs={"poll_interval": 0.02},
                name="pdf-reader-test-stub",
                daemon=True,
            )
            self._thread.start()
        return self

    def stop(self) -> None:
        thread = self._thread
        self._thread = None
        try:
            self._server.shutdown()
        except Exception:  # noqa: BLE001 - 夹具关停失败不能掩盖真正的断言失败
            pass
        if thread is not None:
            thread.join(timeout=5.0)
        try:
            self._server.server_close()
        except OSError:
            pass

    def __enter__(self) -> StubLoopbackEndpoint:
        return self.start()

    def __exit__(self, *_exc: object) -> None:
        self.stop()


class FakeServiceProcess:
    """假服务进程：实现启动器真正用到的那部分 Popen 接口。"""

    def __init__(self, *, stubborn: bool = False) -> None:
        self.stubborn = stubborn
        self.returncode: int | None = None
        self.terminate_calls = 0
        self.kill_calls = 0
        self._exited = threading.Event()

    def finish(self, code: int = 0) -> None:
        self.returncode = code
        self._exited.set()

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        wait_for = 30.0 if timeout is None else max(0.0, float(timeout))
        if not self._exited.wait(wait_for):
            raise subprocess.TimeoutExpired(cmd="PDF Reader Service.exe", timeout=wait_for)
        return self.returncode if isinstance(self.returncode, int) else 0

    def terminate(self) -> None:
        self.terminate_calls += 1
        if not self.stubborn:
            self.finish(1)

    def kill(self) -> None:
        self.kill_calls += 1
        self.finish(-9)


class FakePortableService:
    """替代 subprocess.Popen 的假服务：像真实服务一样发布就绪状态并回答控制请求。"""

    def __init__(
        self,
        layout: paths.RuntimeLayout,
        *,
        publish: str = "ready",
        failure_code: str = "portable_service_environment_missing",
        failure_message: str = "便携服务缺少受控环境",
        publish_delay: float = 0.0,
        exit_before_ready: int | None = None,
        self_stop_after: float | None = None,
        cooperative: bool = True,
        stubborn: bool = False,
        configure_endpoint: Callable[[StubLoopbackEndpoint], None] | None = None,
    ) -> None:
        self.layout = layout
        self.publish = publish
        self.failure_code = failure_code
        self.failure_message = failure_message
        self.publish_delay = publish_delay
        self.exit_before_ready = exit_before_ready
        self.self_stop_after = self_stop_after
        self.cooperative = cooperative
        self.stubborn = stubborn
        self.configure_endpoint = configure_endpoint
        self.child_commands: list[list[str]] = []
        self.child_env: dict[str, str] = {}
        self.child_cwd: str | None = None
        self.process: FakeServiceProcess | None = None
        self.endpoint: StubLoopbackEndpoint | None = None

    @property
    def spawn_count(self) -> int:
        return len(self.child_commands)

    @property
    def readiness_file(self) -> Path:
        return Path(self.child_env[portable_runtime.READY_FILE_ENV])

    def __call__(self, command: list[str], **kwargs: Any) -> FakeServiceProcess:
        self.child_commands.append(list(command))
        self.child_env = dict(kwargs.get("env") or {})
        cwd = kwargs.get("cwd")
        self.child_cwd = None if cwd is None else str(cwd)
        process = FakeServiceProcess(stubborn=self.stubborn)
        self.process = process
        if self.self_stop_after is not None:
            threading.Timer(self.self_stop_after, process.finish, args=(0,)).start()
        if self.publish_delay > 0:
            threading.Thread(
                target=self._publish,
                args=(process,),
                name="fake-service-ready",
                daemon=True,
            ).start()
        else:
            self._publish(process)
        return process

    def _publish(self, process: FakeServiceProcess) -> None:
        if self.publish == "none":
            pass
        elif self.publish == "error":
            portable_runtime.write_readiness_failure(
                self.layout,
                self.readiness_file,
                code=self.failure_code,
                message=self.failure_message,
            )
        else:
            endpoint = StubLoopbackEndpoint(
                health_token=self.child_env[portable_runtime.HEALTH_TOKEN_ENV],
                service_control_token=self.child_env[portable_runtime.CONTROL_TOKEN_ENV],
            )
            if self.cooperative:
                endpoint.on_shutdown = lambda: process.finish(0)
            if self.configure_endpoint is not None:
                self.configure_endpoint(endpoint)
            endpoint.start()
            self.endpoint = endpoint
            portable_runtime.write_readiness_descriptor(
                self.layout,
                self.readiness_file,
                host=LOOPBACK_HOST,
                port=endpoint.port,
                health_token=self.child_env[portable_runtime.HEALTH_TOKEN_ENV],
            )
        if self.exit_before_ready is not None:
            process.finish(self.exit_before_ready)

    def cleanup(self) -> None:
        endpoint = self.endpoint
        self.endpoint = None
        if endpoint is not None:
            endpoint.stop()


@dataclass
class LauncherRun:
    """在后台线程里执行启动器主流程，用于断言并发双击一类的竞争路径。"""

    results: list[int] = field(default_factory=list)
    errors: list[BaseException] = field(default_factory=list)
    thread: threading.Thread | None = None

    def join(self, timeout: float = 30.0) -> int:
        thread = self.thread
        assert thread is not None, "启动器线程未启动"
        thread.join(timeout)
        assert not thread.is_alive(), "启动器线程未在超时内结束"
        assert self.errors == [], f"启动器线程抛出异常：{self.errors!r}"
        assert len(self.results) == 1, f"启动器没有返回唯一退出码：{self.results!r}"
        return self.results[0]


def start_launcher(callable_: Callable[[], int]) -> LauncherRun:
    """在守护线程里跑启动器主流程；异常被收集起来在 join 时暴露。"""

    run = LauncherRun()

    def _target() -> None:
        try:
            run.results.append(callable_())
        except BaseException as exc:  # noqa: BLE001 - 线程内异常必须回传给测试断言
            run.errors.append(exc)

    run.thread = threading.Thread(target=_target, name="pdf-reader-test-launcher", daemon=True)
    run.thread.start()
    return run


def wait_for(predicate: Callable[[], bool], *, timeout: float = 10.0, interval: float = 0.02) -> bool:
    """有界轮询等待条件成立；超时后再判定一次，避免末尾竞态。"""

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def wait_for_instance_record(
    layout: paths.RuntimeLayout,
    *,
    timeout: float = 30.0,
    interval: float = 0.02,
) -> portable_instance.InstanceRecord:
    """等待启动器发布实例记录（第二次启动的激活前提）。"""

    deadline = time.monotonic() + timeout
    while True:
        try:
            record = portable_instance.read_instance_record(layout)
        except portable_instance.PortableInstanceError:
            record = None
        if record is not None:
            return record
        assert time.monotonic() < deadline, "启动器未在超时内发布实例记录"
        time.sleep(interval)
