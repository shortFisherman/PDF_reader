"""P1-02 便携服务生命周期：绑定冲突分类、协作退出通道与收尾顺序。

需求 5 的收敛顺序在服务侧固定为：停止接受新任务 → 等待当前任务 → 由
``main`` 的既有收尾路径关闭 AppState。因此这里的断言是：

* 绑定失败只发布稳定失败码，占用端口的进程必须原样活着；
* 受认证的退出请求只置位控制器，真正的 shutdown/server_close 由服务循环完成；
* watchdog 与 WSGI server 在任何退出路径上都会被收尾，不留后台线程。
"""

from __future__ import annotations

import contextlib
import io
import json
import socket
import sys
import threading
from collections.abc import Iterator
from dataclasses import replace
from typing import Any

import pytest
from flask import Flask

from pdf_reader import app as app_module
from pdf_reader import config, logging_config, portable_runtime
from tests.release import portable_harness as h

HEALTH_TOKEN = "health-token-" + "h" * 32
CONTROL_TOKEN = "service-token-" + "s" * 32
HEALTH_HEADER = portable_runtime.HEALTH_TOKEN_HEADER
CONTROL_HEADER = portable_runtime.CONTROL_TOKEN_HEADER


class FakeWsgiServer:
    """最小 WSGI server：记录 serve_forever/shutdown/server_close 的真实顺序。"""

    def __init__(self, *, interrupt: bool = False, explode: bool = False) -> None:
        self.interrupt = interrupt
        self.explode = explode
        self.events: list[str] = []
        self.poll_interval: float | None = None
        self._stopped = threading.Event()

    def serve_forever(self, poll_interval: float = 0.5) -> None:
        self.poll_interval = poll_interval
        self.events.append("serve")
        if self.explode:
            raise RuntimeError("serving exploded")
        if self.interrupt:
            raise KeyboardInterrupt
        self._stopped.wait(10.0)

    def shutdown(self) -> None:
        self.events.append("shutdown")
        self._stopped.set()

    def server_close(self) -> None:
        self.events.append("close")


class FakeWatchdog:
    def __init__(self) -> None:
        self.stop_calls = 0

    def stop(self) -> None:
        self.stop_calls += 1


def _serve(
    layout: Any,
    *,
    server: FakeWsgiServer,
    controller: Any,
    readiness_file: Any,
    watchdog: FakeWatchdog | None = None,
) -> int:
    """用注入的假 server/watchdog 跑服务循环；真实 app 对象不参与该路径。"""

    watchdogs: list[FakeWatchdog] = []

    def watchdog_factory(_controller: Any) -> FakeWatchdog | None:
        if watchdog is None:
            return None
        watchdogs.append(watchdog)
        return watchdog

    return app_module._serve_portable_service(
        Flask(__name__),
        config.ServerConfig(host="127.0.0.1", port=5100),
        layout=layout,
        readiness_file=readiness_file,
        controller=controller,
        server_factory=lambda _host, _port, _app: server,
        watchdog_factory=watchdog_factory,
    )


class TestPortableServiceLoop:
    @pytest.mark.parametrize("factory_error", [SystemExit(1), OSError(98, "Address already in use")])
    def test_bind_failure_publishes_port_in_use_and_never_touches_the_occupier(self, tmp_path, factory_error):
        layout = h.make_portable_layout(tmp_path)
        readiness = portable_runtime.new_readiness_file(layout)
        controller = portable_runtime.PortableShutdownController()

        def failing_factory(_host: str, _port: int, _app: Any) -> Any:
            raise factory_error

        code = app_module._serve_portable_service(
            Flask(__name__),
            config.ServerConfig(host="127.0.0.1", port=5100),
            layout=layout,
            readiness_file=readiness,
            controller=controller,
            server_factory=failing_factory,
            watchdog_factory=lambda _controller: pytest.fail("绑定失败时不该启动 watchdog"),
        )

        payload = json.loads(readiness.read_text(encoding="utf-8"))
        assert code == portable_runtime.SERVICE_EXIT_PORT_IN_USE
        assert payload["status"] == "error"
        assert payload["code"] == portable_runtime.SERVICE_PORT_IN_USE_CODE
        assert "不会终止占用端口的程序" in payload["message"]
        assert portable_runtime.read_json_descriptor(layout, readiness) is not None
        # 绑定失败不是退出请求：控制器保持未触发状态。
        assert controller.requested is False
        assert controller.reason is None

    def test_real_port_conflict_keeps_the_occupier_listening(self, tmp_path):
        layout = h.make_portable_layout(tmp_path)
        readiness = portable_runtime.new_readiness_file(layout)
        controller = portable_runtime.PortableShutdownController()

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupier:
            occupier.bind(("127.0.0.1", 0))
            occupier.listen(1)
            port = int(occupier.getsockname()[1])
            with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                code = app_module._serve_portable_service(
                    Flask(__name__),
                    config.ServerConfig(host="127.0.0.1", port=port),
                    layout=layout,
                    readiness_file=readiness,
                    controller=controller,
                )
            # 占用者仍然在监听：PDF Reader 从不终止不是自己启动的进程。
            with socket.create_connection(("127.0.0.1", port), timeout=5.0):
                pass

        payload = json.loads(readiness.read_text(encoding="utf-8"))
        assert code == portable_runtime.SERVICE_EXIT_PORT_IN_USE
        assert payload["code"] == portable_runtime.SERVICE_PORT_IN_USE_CODE

    def test_authenticated_shutdown_request_stops_the_server_then_closes_it(self, tmp_path):
        layout = h.make_portable_layout(tmp_path)
        controller = portable_runtime.PortableShutdownController()
        server = FakeWsgiServer()
        watchdog = FakeWatchdog()
        threading.Timer(0.05, lambda: controller.request("launcher_request")).start()

        code = _serve(layout, server=server, controller=controller, readiness_file=None, watchdog=watchdog)

        assert code == 0
        assert server.events == ["serve", "shutdown", "close"]
        assert watchdog.stop_calls == 1
        assert controller.reason == "launcher_request"

    def test_keyboard_interrupt_requests_shutdown_and_closes_everything(self, tmp_path):
        layout = h.make_portable_layout(tmp_path)
        controller = portable_runtime.PortableShutdownController()
        server = FakeWsgiServer(interrupt=True)
        watchdog = FakeWatchdog()

        code = _serve(layout, server=server, controller=controller, readiness_file=None, watchdog=watchdog)

        assert code == 130
        assert controller.requested is True
        assert controller.reason == "keyboard_interrupt"
        assert watchdog.stop_calls == 1
        assert server.events[-1] == "close"

    def test_serving_failure_still_stops_the_watchdog_and_closes_the_server(self, tmp_path):
        layout = h.make_portable_layout(tmp_path)
        controller = portable_runtime.PortableShutdownController()
        server = FakeWsgiServer(explode=True)
        watchdog = FakeWatchdog()

        with pytest.raises(RuntimeError, match="serving exploded"):
            _serve(layout, server=server, controller=controller, readiness_file=None, watchdog=watchdog)

        assert watchdog.stop_calls == 1
        assert server.events[-1] == "close"

    def test_missing_readiness_file_is_not_a_shutdown_reason(self, tmp_path):
        layout = h.make_portable_layout(tmp_path)
        controller = portable_runtime.PortableShutdownController()
        server = FakeWsgiServer(interrupt=True)

        # readiness_file=None 只表示“没有启动器在等就绪”，退出仍然必须收敛。
        code = _serve(layout, server=server, controller=controller, readiness_file=None)

        assert code == 130
        assert h.readiness_files(layout) == ()


@contextlib.contextmanager
def _portable_app(
    monkeypatch: pytest.MonkeyPatch,
    *,
    health_token: str | None = HEALTH_TOKEN,
    control_token: str | None = CONTROL_TOKEN,
    setup_mode: bool = False,
) -> Iterator[Any]:
    """真实 create_app 的便携模式实例；退出时按 main 的收尾语义关闭 AppState。"""

    monkeypatch.setenv("PDF_READER_PORTABLE_SERVICE", "1")
    monkeypatch.delenv(portable_runtime.HEALTH_TOKEN_ENV, raising=False)
    monkeypatch.delenv(portable_runtime.CONTROL_TOKEN_ENV, raising=False)
    if health_token is not None:
        monkeypatch.setenv(portable_runtime.HEALTH_TOKEN_ENV, health_token)
    if control_token is not None:
        monkeypatch.setenv(portable_runtime.CONTROL_TOKEN_ENV, control_token)
    settings = config.build_app_settings()
    if setup_mode:
        settings = replace(settings, setup_mode=True, setup_reason="首次配置尚未完成")
    application = app_module.create_app(settings)
    application.config["TESTING"] = True
    try:
        yield application
    finally:
        application.config["app_state"].close()
        logging_config.reset_logging()


class TestPortableControlRoutes:
    def test_health_requires_the_exact_health_token(self, monkeypatch):
        with _portable_app(monkeypatch) as application:
            client = application.test_client()

            assert client.get("/api/health").status_code == 404
            assert client.get("/api/health", headers={HEALTH_HEADER: "wrong-token"}).status_code == 404
            # 令牌不可互换：控制令牌不能冒充健康令牌。
            assert client.get("/api/health", headers={HEALTH_HEADER: CONTROL_TOKEN}).status_code == 404

            healthy = client.get("/api/health", headers={HEALTH_HEADER: HEALTH_TOKEN})

            assert healthy.status_code == 200
            assert healthy.get_json() == {"status": "ok"}

    def test_shutdown_requires_the_exact_control_token_and_only_requests_shutdown(self, monkeypatch):
        with _portable_app(monkeypatch) as application:
            controller = application.config["portable_shutdown_controller"]
            client = application.test_client()

            assert client.post(portable_runtime.SHUTDOWN_PATH).status_code == 404
            assert (
                client.post(portable_runtime.SHUTDOWN_PATH, headers={CONTROL_HEADER: HEALTH_TOKEN}).status_code == 404
            )
            assert controller.requested is False

            accepted = client.post(portable_runtime.SHUTDOWN_PATH, headers={CONTROL_HEADER: CONTROL_TOKEN})

            assert accepted.status_code == 202
            assert accepted.get_json() == {"status": "shutting_down"}
            # 路由只提出请求；停止接收新任务与关闭 AppState 由服务主流程负责。
            assert controller.reason == "launcher_request"
            assert (
                client.post(portable_runtime.SHUTDOWN_PATH, headers={CONTROL_HEADER: CONTROL_TOKEN}).status_code == 202
            )
            assert controller.reason == "launcher_request"


class FakeLivenessMonitor:
    def __init__(self, *, gone: bool = False, failures: int = 0) -> None:
        self.gone = gone
        self.failures = failures
        self.close_calls = 0

    def launcher_gone(self) -> bool:
        if self.failures:
            self.failures -= 1
            raise OSError("内核查询暂时失败")
        return self.gone

    def close(self) -> None:
        self.close_calls += 1


class FakeWindowsLivenessApi:
    def __init__(self) -> None:
        self.name = ""
        self.existed = False
        self.wait_result = portable_runtime.WINDOWS_WAIT_TIMEOUT
        self.closed: list[int] = []
        self.released: list[int] = []

    def create_owned_mutex(self, name: str) -> tuple[int, bool]:
        self.name = name
        return 101, self.existed

    def open_mutex(self, name: str) -> int:
        assert name == self.name
        return 202

    def wait_mutex(self, handle: int) -> int:
        assert handle == 202
        return self.wait_result

    def release_mutex(self, handle: int) -> None:
        self.released.append(handle)

    def close_handle(self, handle: int) -> None:
        self.closed.append(handle)


class TestLauncherLivenessWatchdog:
    def test_windows_mutex_abandonment_tracks_exact_launcher_lifetime(self, tmp_path):
        layout = h.make_portable_layout(tmp_path)
        api = FakeWindowsLivenessApi()
        owner = portable_runtime.create_launcher_liveness_owner(layout, platform="win32", windows_api=api)
        monitor = portable_runtime.open_launcher_liveness_monitor(
            layout,
            owner.descriptor,
            platform="win32",
            windows_api=api,
        )

        assert monitor.launcher_gone() is False
        api.wait_result = portable_runtime.WINDOWS_WAIT_ABANDONED
        assert monitor.launcher_gone() is True
        assert api.released == [202]

        monitor.close()
        owner.close()
        assert api.closed == [202, 101]

    def test_windows_owner_refuses_to_adopt_an_existing_kernel_object(self, tmp_path):
        """随机名称已被占用时必须 fail closed，绝不把别人的内核对象当成自己的身份。"""

        layout = h.make_portable_layout(tmp_path)
        api = FakeWindowsLivenessApi()
        api.existed = True

        with pytest.raises(portable_runtime.PortableEnvironmentError) as exc_info:
            portable_runtime.create_launcher_liveness_owner(layout, platform="win32", windows_api=api)

        assert exc_info.value.code == "launcher_liveness_unavailable"
        assert api.closed == [101]

    def test_windows_identity_name_is_random_for_every_launch(self, tmp_path):
        layout = h.make_portable_layout(tmp_path)
        first_api = FakeWindowsLivenessApi()
        second_api = FakeWindowsLivenessApi()
        first = portable_runtime.create_launcher_liveness_owner(layout, platform="win32", windows_api=first_api)
        second = portable_runtime.create_launcher_liveness_owner(layout, platform="win32", windows_api=second_api)
        try:
            assert first_api.name != second_api.name
            for name in (first_api.name, second_api.name):
                assert name.startswith(portable_runtime.WINDOWS_LIVENESS_PREFIX)
                suffix = name.removeprefix(portable_runtime.WINDOWS_LIVENESS_PREFIX)
                assert len(suffix) == 32
                assert all(character in "0123456789abcdef" for character in suffix)
            # 旧服务只认识原启动器的随机对象：新启动器的名称不可能满足旧描述符。
            monitor = portable_runtime.open_launcher_liveness_monitor(
                layout,
                first.descriptor,
                platform="win32",
                windows_api=first_api,
            )
            try:
                assert monitor.launcher_gone() is False
            finally:
                monitor.close()
        finally:
            first.close()
            second.close()

    def test_watchdog_requests_a_cooperative_exit_when_exact_launcher_object_disappears(self):
        controller = portable_runtime.PortableShutdownController()
        monitor = FakeLivenessMonitor()
        watchdog = portable_runtime.LauncherLivenessWatchdog(controller, monitor=monitor, interval=0.02)

        thread = watchdog.start()
        monitor.gone = True
        thread.join(timeout=5.0)

        assert thread.is_alive() is False
        assert controller.requested is True
        assert controller.reason == "launcher_exited"
        watchdog.stop()
        assert monitor.close_calls == 1

    def test_watchdog_stays_quiet_and_closes_monitor_on_normal_stop(self):
        controller = portable_runtime.PortableShutdownController()
        monitor = FakeLivenessMonitor()
        watchdog = portable_runtime.LauncherLivenessWatchdog(controller, monitor=monitor, interval=0.02)

        thread = watchdog.start()
        assert watchdog.start() is thread
        watchdog.stop()

        assert controller.requested is False
        assert thread.is_alive() is False
        assert monitor.close_calls == 1

    def test_pid_reuse_cannot_hide_loss_of_the_original_launcher(self, monkeypatch):
        from pdf_reader import cache_ops

        monkeypatch.setattr(cache_ops, "is_process_alive", lambda _pid: True)
        controller = portable_runtime.PortableShutdownController()
        monitor = FakeLivenessMonitor(gone=True)
        watchdog = portable_runtime.LauncherLivenessWatchdog(controller, monitor=monitor, interval=0.01)

        thread = watchdog.start()
        thread.join(timeout=5.0)
        watchdog.stop()

        assert controller.reason == "launcher_exited"

    def test_watchdog_ignores_transient_kernel_query_failures(self):
        controller = portable_runtime.PortableShutdownController()
        monitor = FakeLivenessMonitor(failures=2)
        watchdog = portable_runtime.LauncherLivenessWatchdog(controller, monitor=monitor, interval=0.02)
        thread = watchdog.start()
        thread.join(timeout=0.1)

        assert thread.is_alive() is True
        assert controller.requested is False

        monitor.gone = True
        thread.join(timeout=5.0)
        watchdog.stop()
        assert controller.reason == "launcher_exited"

    def test_persistent_kernel_query_failure_fails_safe_instead_of_orphaning_service(self):
        controller = portable_runtime.PortableShutdownController()
        monitor = FakeLivenessMonitor(failures=portable_runtime.MAX_LIVENESS_QUERY_FAILURES)
        watchdog = portable_runtime.LauncherLivenessWatchdog(controller, monitor=monitor, interval=0.01)

        thread = watchdog.start()
        thread.join(timeout=5.0)
        watchdog.stop()

        assert thread.is_alive() is False
        assert controller.reason == "launcher_liveness_failed"

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX flock lifecycle")
    def test_random_posix_identity_is_not_reused_by_a_new_launcher(self, tmp_path):
        layout = h.make_portable_layout(tmp_path)
        old_owner = portable_runtime.create_launcher_liveness_owner(layout, platform="linux")
        old_monitor = portable_runtime.open_launcher_liveness_monitor(
            layout,
            old_owner.descriptor,
            platform="linux",
        )
        assert old_monitor.launcher_gone() is False

        old_owner.close()
        new_owner = portable_runtime.create_launcher_liveness_owner(layout, platform="linux")
        try:
            assert new_owner.descriptor != old_owner.descriptor
            assert old_monitor.launcher_gone() is True
        finally:
            old_monitor.close()
            new_owner.close()

    def test_default_watchdog_opens_descriptor_from_environment(self, tmp_path, monkeypatch, caplog):
        layout = h.make_portable_layout(tmp_path)
        owner = portable_runtime.create_launcher_liveness_owner(layout, platform="linux")
        monkeypatch.setattr(app_module.paths, "get_runtime_layout", lambda: layout)
        monkeypatch.setenv(portable_runtime.LAUNCHER_LIVENESS_ENV, owner.descriptor)
        controller = portable_runtime.PortableShutdownController()

        watchdog = app_module._default_launcher_watchdog(controller)
        assert isinstance(watchdog, portable_runtime.LauncherLivenessWatchdog)
        watchdog.stop()
        owner.close()
        assert controller.requested is False

        monkeypatch.delenv(portable_runtime.LAUNCHER_LIVENESS_ENV, raising=False)
        missing_controller = portable_runtime.PortableShutdownController()
        with caplog.at_level("ERROR", logger="pdf_reader.app"):
            assert app_module._default_launcher_watchdog(missing_controller) is None
        assert missing_controller.reason == "launcher_liveness_unavailable"

    def test_weak_or_missing_tokens_fail_closed(self, monkeypatch):
        with _portable_app(monkeypatch, health_token=None, control_token=None) as application:
            client = application.test_client()
            assert client.get("/api/health", headers={HEALTH_HEADER: HEALTH_TOKEN}).status_code == 404
            assert (
                client.post(portable_runtime.SHUTDOWN_PATH, headers={CONTROL_HEADER: CONTROL_TOKEN}).status_code == 404
            )

        with _portable_app(monkeypatch, health_token="short", control_token="short") as application:
            client = application.test_client()
            assert client.get("/api/health", headers={HEALTH_HEADER: "short"}).status_code == 404
            assert client.post(portable_runtime.SHUTDOWN_PATH, headers={CONTROL_HEADER: "short"}).status_code == 404

    def test_tokens_are_never_echoed_or_routed(self, monkeypatch):
        with _portable_app(monkeypatch) as application:
            client = application.test_client()

            responses = [
                client.get("/api/health", headers={HEALTH_HEADER: HEALTH_TOKEN}),
                client.get("/"),
                client.post(portable_runtime.SHUTDOWN_PATH, headers={CONTROL_HEADER: CONTROL_TOKEN}),
            ]
            rules = [rule.rule for rule in application.url_map.iter_rules()]

        for response in responses:
            body = response.data.decode("utf-8")
            assert HEALTH_TOKEN not in body
            assert CONTROL_TOKEN not in body
        assert not any(HEALTH_TOKEN in rule or CONTROL_TOKEN in rule for rule in rules)
        assert "/api/health" in rules
        assert portable_runtime.SHUTDOWN_PATH in rules

    def test_control_channel_stays_available_during_first_run_setup(self, monkeypatch):
        with _portable_app(monkeypatch, setup_mode=True) as application:
            controller = application.config["portable_shutdown_controller"]
            client = application.test_client()

            gated = client.post("/api/open", json={})

            assert gated.status_code == 503
            assert gated.get_json()["code"] == "setup_required"
            assert client.get("/api/health", headers={HEALTH_HEADER: HEALTH_TOKEN}).status_code == 200
            assert client.post(portable_runtime.SHUTDOWN_PATH).status_code == 404
            assert (
                client.post(portable_runtime.SHUTDOWN_PATH, headers={CONTROL_HEADER: CONTROL_TOKEN}).status_code == 202
            )
            assert controller.reason == "launcher_request"
