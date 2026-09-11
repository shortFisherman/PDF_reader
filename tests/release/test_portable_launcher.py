"""P1-02 便携启动器主流程：就绪探测、自动开页、单实例激活与可靠退出。"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

import pytest

from pdf_reader import paths, portable_data, portable_instance, portable_launcher, portable_runtime
from tests.release import portable_harness as h


class DeniedLock:
    """acquire 永远失败：等价于另一个实例稳定持有内核锁。"""

    def __init__(self) -> None:
        self.attempts = 0

    def acquire(self) -> bool:
        self.attempts += 1
        return False

    def release(self) -> None:
        pass


class ExplodingLock:
    """锁原语本身不可用：必须是稳定错误码，而不是未捕获异常。"""

    def acquire(self) -> bool:
        raise portable_runtime.PortableEnvironmentError("内核锁不可用", code="instance_lock_unavailable")

    def release(self) -> None:
        pass


class FakeLauncherWindow:
    """假控制窗口：按配置模拟点按钮、关窗口或一直开着。"""

    def __init__(
        self,
        dispatch: portable_launcher.ControlDispatch,
        should_stop: Any,
        *,
        action: str = "quit",
        hold: threading.Event | None = None,
        poll: float = 0.02,
    ) -> None:
        self._dispatch = dispatch
        self._should_stop = should_stop
        self._action = action
        self._hold = hold
        self._poll = poll
        self.dispatched: list[str] = []
        self.closed = False

    def run(self) -> None:
        if self._hold is not None:
            while not self._hold.wait(self._poll):
                if self._should_stop():
                    return
            return
        if self._action == "quit":
            self.dispatched.append(self._dispatch("quit"))
            return
        if self._action == "open_reader":
            self.dispatched.append(self._dispatch("open_reader"))
            return
        if self._action == "close":
            self.close()
            return
        assert self._action == "silent", f"未知的窗口动作：{self._action}"

    def close(self) -> None:
        self.closed = True


def window_factory(
    action: str = "quit",
    *,
    hold: threading.Event | None = None,
    created: list[FakeLauncherWindow] | None = None,
) -> portable_launcher.WindowFactory:
    """构造注入启动器的窗口工厂；created 记录真正被创建的窗口。"""

    def _factory(*, dispatch: portable_launcher.ControlDispatch, should_stop: Any) -> FakeLauncherWindow:
        window = FakeLauncherWindow(dispatch, should_stop, action=action, hold=hold)
        if created is not None:
            created.append(window)
        return window

    return _factory


def _read_launcher_log(layout: paths.RuntimeLayout) -> str:
    return (layout.log_dir / portable_launcher.LAUNCHER_LOG_NAME).read_text(encoding="utf-8")


class TestReadinessProbe:
    def test_ready_requires_a_successful_token_probe_not_a_descriptor_alone(self, tmp_path):
        layout = h.make_portable_layout(tmp_path)
        readiness = portable_runtime.new_readiness_file(layout)
        token = "health-token-" + "k" * 32
        portable_runtime.write_readiness_descriptor(layout, readiness, host="127.0.0.1", port=5100, health_token=token)
        process = h.FakeServiceProcess()
        probed: list[tuple[str, int, str]] = []

        def probe(host: str, port: int, supplied: str) -> bool:
            probed.append((host, port, supplied))
            return len(probed) >= 2

        url = portable_launcher.wait_until_ready(process, readiness, timeout=5.0, interval=0.01, probe=probe)

        assert url == "http://127.0.0.1:5100/"
        assert len(probed) >= 2
        assert set(probed) == {("127.0.0.1", 5100, token)}

    def test_ready_is_never_guessed_without_a_descriptor(self, tmp_path):
        layout = h.make_portable_layout(tmp_path)
        readiness = portable_runtime.new_readiness_file(layout)
        process = h.FakeServiceProcess()

        with pytest.raises(portable_launcher.PortableLaunchError) as exc_info:
            portable_launcher.wait_until_ready(
                process,
                readiness,
                timeout=0.05,
                interval=0.005,
                probe=lambda *_args: True,
            )

        assert exc_info.value.code == "service_start_timeout"
        assert "尚未发布就绪状态" in str(exc_info.value)

    def test_descriptor_failure_code_short_circuits_the_wait(self, tmp_path):
        layout = h.make_portable_layout(tmp_path)
        readiness = portable_runtime.new_readiness_file(layout)
        portable_runtime.write_readiness_failure(
            layout,
            readiness,
            code="portable_service_environment_missing",
            message="便携服务缺少受控环境",
        )
        started = time.monotonic()

        with pytest.raises(portable_launcher.PortableLaunchError) as exc_info:
            portable_launcher.wait_until_ready(
                h.FakeServiceProcess(),
                readiness,
                timeout=5.0,
                probe=lambda *_args: True,
            )

        assert exc_info.value.code == "portable_service_environment_missing"
        assert "便携服务缺少受控环境" in str(exc_info.value)
        assert time.monotonic() - started < 1.0

    @pytest.mark.parametrize(
        ("exit_code", "expected_code"),
        [
            (portable_runtime.SERVICE_EXIT_PORT_IN_USE, portable_runtime.SERVICE_PORT_IN_USE_CODE),
            (9, "service_exited_before_ready"),
        ],
    )
    def test_service_exit_before_ready_is_reported_with_its_own_code(self, tmp_path, exit_code, expected_code):
        layout = h.make_portable_layout(tmp_path)
        readiness = portable_runtime.new_readiness_file(layout)
        process = h.FakeServiceProcess()
        process.finish(exit_code)

        with pytest.raises(portable_launcher.PortableLaunchError) as exc_info:
            portable_launcher.wait_until_ready(process, readiness, timeout=1.0, probe=lambda *_args: True)

        assert exc_info.value.code == expected_code

    def test_invalid_descriptor_endpoint_is_never_probed(self, tmp_path):
        layout = h.make_portable_layout(tmp_path)
        readiness = portable_runtime.new_readiness_file(layout)
        portable_runtime.write_json_descriptor(
            layout,
            readiness,
            {"schema": portable_runtime.READINESS_SCHEMA, "host": "0.0.0.0", "port": 5100, "health_token": "x" * 32},
        )
        probed: list[tuple[str, int, str]] = []

        def probe(host: str, port: int, token: str) -> bool:
            probed.append((host, port, token))
            return True

        with pytest.raises(portable_launcher.PortableLaunchError) as exc_info:
            portable_launcher.wait_until_ready(
                h.FakeServiceProcess(), readiness, timeout=0.05, interval=0.005, probe=probe
            )

        assert exc_info.value.code == "service_start_timeout"
        assert probed == []


class TestExitCodes:
    def test_launcher_exit_codes_are_a_stable_contract(self):
        assert portable_launcher.EXIT_LAUNCHER_ERROR == 2
        assert portable_launcher.EXIT_SERVICE_START_FAILED == 3
        assert portable_launcher.EXIT_PORT_IN_USE == 4
        assert portable_launcher.EXIT_INSTANCE_UNAVAILABLE == 5
        assert portable_launcher.EXIT_SERVICE_EXITED == 6
        assert portable_launcher.EXIT_INTERRUPTED == 130

    @pytest.mark.parametrize(
        ("service_code", "expected"),
        [
            (None, 0),
            # 协作退出的正常路径：服务干净退出（0）等于启动器干净退出（0）。
            (0, 0),
            (portable_runtime.SERVICE_EXIT_PORT_IN_USE, portable_launcher.EXIT_PORT_IN_USE),
            (7, portable_launcher.EXIT_SERVICE_EXITED),
            (-9, portable_launcher.EXIT_SERVICE_EXITED),
        ],
    )
    def test_service_exit_codes_map_to_launcher_exit_codes(self, service_code, expected):
        assert portable_launcher._exit_code_for(service_code) == expected

    def test_stop_process_never_signals_an_already_finished_process(self):
        process = h.FakeServiceProcess()
        process.finish(0)

        portable_launcher._stop_process(process, timeout=0.1)

        assert process.terminate_calls == 0
        assert process.kill_calls == 0

    def test_port_release_wait_is_bounded_and_never_touches_the_occupier(self):
        probed: list[tuple[str, int]] = []

        def probe(host: str, port: int) -> bool:
            probed.append((host, port))
            return True

        started = time.monotonic()
        released = portable_runtime.wait_for_port_release("127.0.0.1", 5100, timeout=0.2, interval=0.05, probe=probe)
        elapsed = time.monotonic() - started

        assert released is False
        assert 0.2 <= elapsed < 5.0
        assert set(probed) == {("127.0.0.1", 5100)}


class TestLaunchFlow:
    def test_successful_launch_probes_health_before_opening_the_reader(self, monkeypatch, tmp_path):
        layout = h.make_portable_layout(tmp_path)
        h.create_service_executable(layout)
        service = h.FakePortableService(layout)
        monkeypatch.setattr(portable_launcher.subprocess, "Popen", service)
        observed: dict[str, Any] = {}

        def fake_browser(url: str) -> bool:
            endpoint = service.endpoint
            observed["url"] = url
            observed["base_url"] = None if endpoint is None else endpoint.base_url
            observed["health_hits"] = 0 if endpoint is None else endpoint.health_hits
            return True

        try:
            result = portable_launcher.run_portable_launcher(
                h.launcher_executable(layout),
                startup_timeout=10.0,
                window_factory=window_factory("quit"),
                browser=fake_browser,
            )
            assert result == 0
            assert observed["url"] == observed["base_url"]
            assert observed["health_hits"] == 1
            assert service.child_commands == [
                [str(h.service_executable(layout)), "--launcher-executable", str(h.launcher_executable(layout))]
            ]
            assert service.child_cwd == str(layout.portable_root)
            log_text = _read_launcher_log(layout)
            assert service.child_env[portable_runtime.HEALTH_TOKEN_ENV] not in log_text
            assert service.child_env[portable_runtime.CONTROL_TOKEN_ENV] not in log_text
        finally:
            service.cleanup()

        assert service.process is not None
        assert service.process.terminate_calls == 0
        assert service.process.kill_calls == 0
        assert not h.instance_record_path(layout).exists()
        assert h.readiness_files(layout) == ()
        assert h.service_temp_directories(layout) == ()

    def test_startup_timeout_reports_stable_code_and_terminates_only_its_own_child(self, monkeypatch, tmp_path, capsys):
        layout = h.make_portable_layout(tmp_path)
        h.create_service_executable(layout)
        service = h.FakePortableService(layout, publish="none")
        monkeypatch.setattr(portable_launcher.subprocess, "Popen", service)
        try:
            result = portable_launcher.run_portable_launcher(
                h.launcher_executable(layout),
                startup_timeout=0.2,
                force_timeout=1.0,
                no_browser=True,
                no_ui=True,
            )
        finally:
            service.cleanup()

        assert result == portable_launcher.EXIT_SERVICE_START_FAILED
        assert service.process is not None
        assert service.process.terminate_calls == 1
        assert service.process.kill_calls == 0
        assert "ERROR [service_start_timeout]" in capsys.readouterr().err
        assert "ERROR [service_start_timeout]" in _read_launcher_log(layout)

    def test_readiness_failure_descriptor_is_reported_without_waiting_for_the_timeout(
        self, monkeypatch, tmp_path, capsys
    ):
        layout = h.make_portable_layout(tmp_path)
        h.create_service_executable(layout)
        service = h.FakePortableService(
            layout,
            publish="error",
            failure_code="portable_service_environment_missing",
            failure_message="便携服务缺少受控环境",
        )
        monkeypatch.setattr(portable_launcher.subprocess, "Popen", service)
        started = time.monotonic()
        try:
            result = portable_launcher.run_portable_launcher(
                h.launcher_executable(layout),
                startup_timeout=30.0,
                force_timeout=1.0,
                no_browser=True,
                no_ui=True,
            )
        finally:
            service.cleanup()

        assert result == portable_launcher.EXIT_SERVICE_START_FAILED
        assert time.monotonic() - started < 5.0
        assert service.process is not None
        assert service.process.terminate_calls == 1
        stderr = capsys.readouterr().err
        assert "ERROR [portable_service_environment_missing]" in stderr
        assert "便携服务缺少受控环境" in stderr

    def test_missing_service_executable_reports_stable_code(self, monkeypatch, tmp_path, capsys):
        layout = h.make_portable_layout(tmp_path)
        spawned: list[str] = []

        def forbidden_popen(command: list[str], **_kwargs: Any) -> Any:
            spawned.append(command[0])
            raise AssertionError("缺少服务程序时不允许启动任何进程")

        monkeypatch.setattr(portable_launcher.subprocess, "Popen", forbidden_popen)

        result = portable_launcher.run_portable_launcher(h.launcher_executable(layout), no_ui=True, no_browser=True)

        assert result == portable_launcher.EXIT_LAUNCHER_ERROR
        assert spawned == []
        assert "ERROR [service_executable_missing]" in capsys.readouterr().err

    def test_lock_unavailable_is_a_stable_code_not_an_exception(self, tmp_path, capsys):
        layout = h.make_portable_layout(tmp_path)

        blocked = portable_launcher.run_portable_launcher(
            h.launcher_executable(layout), lock_factory=lambda _layout: ExplodingLock()
        )
        assert blocked == portable_launcher.EXIT_LAUNCHER_ERROR
        assert "ERROR [instance_lock_unavailable]" in capsys.readouterr().err

        def failing_factory(_layout: paths.RuntimeLayout) -> Any:
            raise OSError("无法创建锁文件")

        missing = portable_launcher.run_portable_launcher(h.launcher_executable(layout), lock_factory=failing_factory)
        assert missing == portable_launcher.EXIT_LAUNCHER_ERROR
        assert "ERROR [instance_lock_unavailable]" in capsys.readouterr().err

    def test_missing_launcher_liveness_identity_prevents_spawning_any_service(self, monkeypatch, tmp_path, capsys):
        """拿不到本次启动专属的存活身份时必须 fail closed：不许启动会变成孤儿的服务。"""

        layout = h.make_portable_layout(tmp_path)
        h.create_service_executable(layout)
        spawned: list[str] = []

        def forbidden_popen(command: list[str], **_kwargs: Any) -> Any:
            spawned.append(command[0])
            raise AssertionError("无法建立启动器存活监督时不允许启动任何服务")

        def failing_owner(_layout: paths.RuntimeLayout, **_kwargs: Any) -> Any:
            raise portable_runtime.PortableEnvironmentError(
                "无法创建唯一的启动器内核存活对象",
                code="launcher_liveness_unavailable",
            )

        monkeypatch.setattr(portable_launcher.subprocess, "Popen", forbidden_popen)
        monkeypatch.setattr(portable_launcher, "create_launcher_liveness_owner", failing_owner)

        result = portable_launcher.run_portable_launcher(
            h.launcher_executable(layout),
            no_ui=True,
            no_browser=True,
        )

        assert result == portable_launcher.EXIT_LAUNCHER_ERROR
        assert spawned == []
        assert "ERROR [launcher_liveness_unavailable]" in capsys.readouterr().err
        assert "ERROR [launcher_liveness_unavailable]" in _read_launcher_log(layout)
        assert not h.instance_record_path(layout).exists()
        assert h.readiness_files(layout) == ()
        assert h.service_temp_directories(layout) == ()


class TestPortConflict:
    @pytest.mark.parametrize("service_exit_code", [portable_runtime.SERVICE_EXIT_PORT_IN_USE])
    def test_service_reported_port_conflict_never_touches_the_occupier(
        self, monkeypatch, tmp_path, capsys, service_exit_code
    ):
        layout = h.make_portable_layout(tmp_path)
        h.create_service_executable(layout)
        occupier = h.StubLoopbackEndpoint().start()
        service = h.FakePortableService(layout, publish="none", exit_before_ready=service_exit_code)
        monkeypatch.setattr(portable_launcher.subprocess, "Popen", service)
        try:
            result = portable_launcher.run_portable_launcher(
                h.launcher_executable(layout),
                startup_timeout=2.0,
                no_browser=True,
                no_ui=True,
            )
            still_serving = portable_runtime.probe_loopback_health("127.0.0.1", occupier.port, h.DEFAULT_HEALTH_TOKEN)
        finally:
            service.cleanup()
            occupier.stop()

        assert result == portable_launcher.EXIT_PORT_IN_USE
        assert still_serving is True
        assert occupier.shutdown_requests == 0
        assert occupier.requests == [("GET", "/api/health")]
        assert service.process is not None
        assert service.process.terminate_calls == 0
        assert "ERROR [service_port_in_use]" in capsys.readouterr().err

    def test_service_published_port_conflict_descriptor_keeps_the_occupier_alive(self, monkeypatch, tmp_path, capsys):
        layout = h.make_portable_layout(tmp_path)
        h.create_service_executable(layout)
        occupier = h.StubLoopbackEndpoint().start()
        service = h.FakePortableService(
            layout,
            publish="error",
            failure_code=portable_runtime.SERVICE_PORT_IN_USE_CODE,
            failure_message="端口被占用",
        )
        monkeypatch.setattr(portable_launcher.subprocess, "Popen", service)
        try:
            result = portable_launcher.run_portable_launcher(
                h.launcher_executable(layout),
                startup_timeout=2.0,
                force_timeout=1.0,
                no_browser=True,
                no_ui=True,
            )
            still_serving = portable_runtime.probe_loopback_health("127.0.0.1", occupier.port, h.DEFAULT_HEALTH_TOKEN)
        finally:
            service.cleanup()
            occupier.stop()

        assert result == portable_launcher.EXIT_PORT_IN_USE
        assert still_serving is True
        assert occupier.shutdown_requests == 0
        assert "ERROR [service_port_in_use]" in capsys.readouterr().err


class TestSingleInstanceActivation:
    def test_second_launch_activates_the_running_instance_without_spawning_a_service(self, tmp_path, monkeypatch):
        layout = h.make_portable_layout(tmp_path)
        endpoint = h.StubLoopbackEndpoint().start()
        record = h.make_instance_record(service_port=endpoint.port, launcher_port=endpoint.port)
        portable_instance.write_instance_record(layout, record)
        spawned: list[str] = []

        def forbidden_popen(command: list[str], **_kwargs: Any) -> Any:
            spawned.append(command[0])
            raise AssertionError("第二次启动不允许拉起第二个服务")

        monkeypatch.setattr(portable_launcher.subprocess, "Popen", forbidden_popen)
        opened: list[str] = []
        try:
            result = portable_launcher.run_portable_launcher(
                h.launcher_executable(layout),
                activation_timeout=5.0,
                activation_interval=0.02,
                lock_factory=lambda _layout: DeniedLock(),
                browser=opened.append,
                port_probe=lambda _host, _port: False,
            )
            assert result == 0
            assert spawned == []
            assert endpoint.control_commands == ["open_reader"]
            # 第二次启动不自己开浏览器：开页由现有实例的控制通道完成，避免双开。
            assert opened == []
            assert endpoint.shutdown_requests == 0
            assert portable_instance.read_instance_record(layout) == record
        finally:
            endpoint.stop()

    def test_second_launch_reports_stable_code_when_the_instance_rejects_the_token(self, tmp_path, capsys):
        layout = h.make_portable_layout(tmp_path)
        endpoint = h.StubLoopbackEndpoint(launcher_control_token="launcher-token-" + "z" * 32).start()
        record = h.make_instance_record(service_port=endpoint.port, launcher_port=endpoint.port)
        portable_instance.write_instance_record(layout, record)
        try:
            result = portable_launcher.run_portable_launcher(
                h.launcher_executable(layout),
                activation_timeout=0.3,
                activation_interval=0.05,
                lock_factory=lambda _layout: DeniedLock(),
                browser=lambda _url: True,
            )
            assert result == portable_launcher.EXIT_INSTANCE_UNAVAILABLE
            assert endpoint.control_commands == []
            assert portable_instance.read_instance_record(layout) == record
        finally:
            endpoint.stop()

        stderr = capsys.readouterr().err
        assert "ERROR [launcher_control_rejected]" in stderr
        for line in stderr.splitlines():
            if line.startswith("ERROR ["):
                assert line.split("]")[0][7:] in portable_launcher.ACTIVATION_FAILURE_CODES

    def test_second_launch_reports_corrupt_instance_record_without_crashing(self, tmp_path, capsys):
        layout = h.make_portable_layout(tmp_path)
        target = h.instance_record_path(layout)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{ half written", encoding="utf-8")

        result = portable_launcher.run_portable_launcher(
            h.launcher_executable(layout),
            activation_timeout=0.2,
            activation_interval=0.05,
            lock_factory=lambda _layout: DeniedLock(),
            browser=lambda _url: True,
        )

        assert result == portable_launcher.EXIT_INSTANCE_UNAVAILABLE
        assert "ERROR [instance_record_invalid]" in capsys.readouterr().err

    def test_concurrent_double_click_starts_exactly_one_service(self, monkeypatch, tmp_path):
        layout = h.make_portable_layout(tmp_path)
        h.create_service_executable(layout)
        service = h.FakePortableService(layout)
        monkeypatch.setattr(portable_launcher.subprocess, "Popen", service)
        release = threading.Event()
        windows: list[FakeLauncherWindow] = []
        opened: list[str] = []

        def launch() -> int:
            return portable_launcher.run_portable_launcher(
                h.launcher_executable(layout),
                startup_timeout=20.0,
                activation_timeout=20.0,
                activation_interval=0.02,
                window_factory=window_factory("hold", hold=release, created=windows),
                browser=opened.append,
                no_browser=True,
            )

        first = h.start_launcher(launch)
        try:
            assert h.wait_for(lambda: h.instance_record_path(layout).exists(), timeout=20.0)
            second = h.start_launcher(launch)
            assert h.wait_for(lambda: opened != [], timeout=20.0)
            assert service.spawn_count == 1
        finally:
            release.set()
            assert first.join(30.0) == 0

        assert second.join(30.0) == 0
        assert len(windows) == 1
        assert len(opened) == 1
        assert opened[0].startswith("http://127.0.0.1:")
        assert service.process is not None
        assert service.process.terminate_calls == 0
        assert not h.instance_record_path(layout).exists()
        assert h.readiness_files(layout) == ()
        service.cleanup()

    def test_two_simultaneous_launches_still_start_exactly_one_service(self, monkeypatch, tmp_path):
        layout = h.make_portable_layout(tmp_path)
        h.create_service_executable(layout)
        service = h.FakePortableService(layout)
        monkeypatch.setattr(portable_launcher.subprocess, "Popen", service)
        release = threading.Event()
        windows: list[FakeLauncherWindow] = []
        opened: list[str] = []

        def launch() -> int:
            return portable_launcher.run_portable_launcher(
                h.launcher_executable(layout),
                startup_timeout=20.0,
                activation_timeout=20.0,
                activation_interval=0.02,
                shutdown_timeout=5.0,
                window_factory=window_factory("hold", hold=release, created=windows),
                browser=opened.append,
                no_browser=True,
            )

        first = h.start_launcher(launch)
        second = h.start_launcher(launch)
        try:
            assert h.wait_for(lambda: len(windows) == 1, timeout=20.0)
            assert h.wait_for(lambda: opened != [], timeout=20.0)
            assert service.spawn_count == 1
        finally:
            release.set()
            assert first.join(30.0) == 0
            assert second.join(30.0) == 0

        assert len(windows) == 1
        assert len(opened) == 1
        assert service.process is not None
        assert service.process.terminate_calls == 0
        service.cleanup()


class TestStaleStateRecovery:
    def test_stale_metadata_is_recovered_by_cooperative_shutdown_not_by_killing(self, monkeypatch, tmp_path):
        layout = h.make_portable_layout(tmp_path)
        h.create_service_executable(layout)
        stale = h.StubLoopbackEndpoint().start()
        stale_readiness = portable_runtime.new_readiness_file(layout)
        portable_runtime.write_readiness_descriptor(
            layout,
            stale_readiness,
            host="127.0.0.1",
            port=stale.port,
            health_token=h.DEFAULT_HEALTH_TOKEN,
        )
        portable_instance.write_instance_record(
            layout,
            h.make_instance_record(service_port=stale.port, launcher_port=stale.port),
        )
        service = h.FakePortableService(layout)
        monkeypatch.setattr(portable_launcher.subprocess, "Popen", service)
        try:
            result = portable_launcher.run_portable_launcher(
                h.launcher_executable(layout),
                startup_timeout=10.0,
                window_factory=window_factory("quit"),
                browser=lambda _url: True,
                port_probe=lambda _host, _port: False,
            )
            requests = list(stale.requests)
            shutdown_requests = stale.shutdown_requests
            still_serving = portable_runtime.probe_loopback_health("127.0.0.1", stale.port, h.DEFAULT_HEALTH_TOKEN)
        finally:
            service.cleanup()
            stale.stop()

        assert result == 0
        assert still_serving is True
        assert shutdown_requests == 1
        assert requests == [("POST", "/api/shutdown")]
        assert not stale_readiness.exists()
        assert h.readiness_files(layout) == ()
        assert not h.instance_record_path(layout).exists()

    def test_dead_stale_record_does_not_block_a_restart(self, monkeypatch, tmp_path, capsys):
        layout = h.make_portable_layout(tmp_path)
        h.create_service_executable(layout)
        dead_port = h.free_loopback_port()
        stale_readiness = portable_runtime.new_readiness_file(layout)
        portable_runtime.write_json_descriptor(layout, stale_readiness, {"status": "ready"})
        portable_instance.write_instance_record(
            layout,
            h.make_instance_record(service_port=dead_port, launcher_port=dead_port),
        )
        service = h.FakePortableService(layout)
        monkeypatch.setattr(portable_launcher.subprocess, "Popen", service)
        try:
            result = portable_launcher.run_portable_launcher(
                h.launcher_executable(layout),
                startup_timeout=10.0,
                window_factory=window_factory("quit"),
                browser=lambda _url: True,
            )
        finally:
            service.cleanup()

        assert result == 0
        assert service.spawn_count == 1
        assert capsys.readouterr().err == ""
        assert h.readiness_files(layout) == ()

    def test_corrupt_stale_record_does_not_block_a_restart(self, monkeypatch, tmp_path):
        layout = h.make_portable_layout(tmp_path)
        h.create_service_executable(layout)
        target = h.instance_record_path(layout)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{ truncated", encoding="utf-8")
        service = h.FakePortableService(layout)
        monkeypatch.setattr(portable_launcher.subprocess, "Popen", service)
        try:
            result = portable_launcher.run_portable_launcher(
                h.launcher_executable(layout),
                startup_timeout=10.0,
                window_factory=window_factory("quit"),
                browser=lambda _url: True,
            )
        finally:
            service.cleanup()

        assert result == 0
        assert service.spawn_count == 1
        assert not target.exists()


class TestShutdownBehaviour:
    def test_cleanup_removes_record_and_stops_service_before_releasing_instance_lock(self, monkeypatch, tmp_path):
        layout = h.make_portable_layout(tmp_path)
        h.create_service_executable(layout)
        service = h.FakePortableService(layout)
        monkeypatch.setattr(portable_launcher.subprocess, "Popen", service)
        observed: dict[str, Any] = {}

        class ObservingLock:
            def acquire(self) -> bool:
                return True

            def release(self) -> None:
                observed["record_exists"] = h.instance_record_path(layout).exists()
                observed["service_code"] = None if service.process is None else service.process.poll()
                observed["liveness_files"] = tuple(layout.runtime_dir.glob("launcher-liveness-*.lock"))

        result = portable_launcher.run_portable_launcher(
            h.launcher_executable(layout),
            startup_timeout=10.0,
            window_factory=window_factory("quit"),
            browser=lambda _url: True,
            lock_factory=lambda _layout: ObservingLock(),
        )
        service.cleanup()

        assert result == 0
        assert observed == {"record_exists": False, "service_code": 0, "liveness_files": ()}

    def test_normal_exit_is_cooperative_and_never_force_stops_the_service(self, monkeypatch, tmp_path):
        layout = h.make_portable_layout(tmp_path)
        h.create_service_executable(layout)
        service = h.FakePortableService(layout, cooperative=True, stubborn=True)
        monkeypatch.setattr(portable_launcher.subprocess, "Popen", service)
        try:
            result = portable_launcher.run_portable_launcher(
                h.launcher_executable(layout),
                startup_timeout=10.0,
                shutdown_timeout=5.0,
                force_timeout=1.0,
                window_factory=window_factory("quit"),
                browser=lambda _url: True,
            )
            shutdown_requests = 0 if service.endpoint is None else service.endpoint.shutdown_requests
            log_text = _read_launcher_log(layout)
        finally:
            service.cleanup()

        assert result == 0
        assert shutdown_requests == 1
        assert service.process is not None
        assert service.process.terminate_calls == 0
        assert service.process.kill_calls == 0
        assert "请求服务协作退出" in log_text

    def test_closing_the_control_window_quits_the_program_cooperatively(self, monkeypatch, tmp_path):
        layout = h.make_portable_layout(tmp_path)
        h.create_service_executable(layout)
        service = h.FakePortableService(layout)
        monkeypatch.setattr(portable_launcher.subprocess, "Popen", service)
        created: list[FakeLauncherWindow] = []
        try:
            result = portable_launcher.run_portable_launcher(
                h.launcher_executable(layout),
                startup_timeout=10.0,
                shutdown_timeout=5.0,
                window_factory=window_factory("close", created=created),
                browser=lambda _url: True,
            )
            shutdown_requests = 0 if service.endpoint is None else service.endpoint.shutdown_requests
        finally:
            service.cleanup()

        # 关闭控制窗口等于退出程序：不是因为服务崩了，也不是强杀。
        assert result == 0
        assert len(created) == 1
        assert created[0].closed is True
        assert shutdown_requests == 1
        assert service.process is not None
        assert service.process.terminate_calls == 0
        assert service.process.kill_calls == 0

    def test_quit_timeout_falls_back_to_terminate_then_kill(self, monkeypatch, tmp_path):
        layout = h.make_portable_layout(tmp_path)
        h.create_service_executable(layout)
        service = h.FakePortableService(layout, cooperative=False, stubborn=True)
        monkeypatch.setattr(portable_launcher.subprocess, "Popen", service)
        try:
            result = portable_launcher.run_portable_launcher(
                h.launcher_executable(layout),
                startup_timeout=10.0,
                shutdown_timeout=0.2,
                force_timeout=0.2,
                window_factory=window_factory("quit"),
                browser=lambda _url: True,
            )
            shutdown_requests = 0 if service.endpoint is None else service.endpoint.shutdown_requests
            log_text = _read_launcher_log(layout)
        finally:
            service.cleanup()

        assert result == portable_launcher.EXIT_SERVICE_EXITED
        # 先尝试协作退出；服务不应答才由启动器兜底 terminate → kill。
        assert shutdown_requests == 1
        assert service.process is not None
        assert service.process.terminate_calls == 1
        assert service.process.kill_calls == 1
        assert "启动器兜底结束该进程" in log_text

    def test_keyboard_interrupt_stops_the_owned_service_and_reports_130(self, monkeypatch, tmp_path, capsys):
        layout = h.make_portable_layout(tmp_path)
        h.create_service_executable(layout)
        service = h.FakePortableService(layout)
        monkeypatch.setattr(portable_launcher.subprocess, "Popen", service)

        def interrupting_factory(**_kwargs: Any) -> Any:
            raise KeyboardInterrupt

        try:
            result = portable_launcher.run_portable_launcher(
                h.launcher_executable(layout),
                startup_timeout=10.0,
                force_timeout=1.0,
                window_factory=interrupting_factory,
                browser=lambda _url: True,
            )
        finally:
            service.cleanup()

        assert result == portable_launcher.EXIT_INTERRUPTED
        assert service.process is not None
        assert service.process.terminate_calls == 1
        assert "ERROR [launcher_interrupted]" in capsys.readouterr().err
        assert not h.instance_record_path(layout).exists()
        assert h.readiness_files(layout) == ()

    def test_launcher_without_ui_exits_when_the_service_stops_itself(self, monkeypatch, tmp_path):
        layout = h.make_portable_layout(tmp_path)
        h.create_service_executable(layout)
        service = h.FakePortableService(layout, self_stop_after=0.2)
        monkeypatch.setattr(portable_launcher.subprocess, "Popen", service)
        try:
            result = portable_launcher.run_portable_launcher(
                h.launcher_executable(layout),
                startup_timeout=10.0,
                no_browser=True,
                no_ui=True,
            )
            shutdown_requests = 0 if service.endpoint is None else service.endpoint.shutdown_requests
        finally:
            service.cleanup()

        assert result == portable_launcher.EXIT_SERVICE_EXITED
        assert service.process is not None
        assert service.process.terminate_calls == 0
        # 服务先自行退出不是用户正常退出：不补强杀，但必须返回异常服务退出码。
        assert shutdown_requests == 0

    @pytest.mark.parametrize("failure_mode", ["missing", "factory_error", "runtime_error"])
    def test_required_control_window_failure_cooperatively_stops_service(
        self,
        monkeypatch,
        tmp_path,
        capsys,
        failure_mode,
    ):
        layout = h.make_portable_layout(tmp_path)
        h.create_service_executable(layout)
        service = h.FakePortableService(layout, cooperative=True, stubborn=True)
        monkeypatch.setattr(portable_launcher.subprocess, "Popen", service)

        def failing_window_factory(**_kwargs: Any) -> Any:
            if failure_mode == "missing":
                return None
            if failure_mode == "factory_error":
                raise RuntimeError("窗口创建失败")

            class BrokenWindow:
                def run(self) -> None:
                    raise RuntimeError("窗口消息循环失败")

                def close(self) -> None:
                    pass

            return BrokenWindow()

        try:
            result = portable_launcher.run_portable_launcher(
                h.launcher_executable(layout),
                startup_timeout=10.0,
                window_factory=failing_window_factory,
                no_browser=True,
            )
            shutdown_requests = 0 if service.endpoint is None else service.endpoint.shutdown_requests
        finally:
            service.cleanup()

        assert result == portable_launcher.EXIT_UI_UNAVAILABLE
        assert "ERROR [launcher_ui_unavailable]" in capsys.readouterr().err
        assert "ERROR [launcher_ui_unavailable]" in _read_launcher_log(layout)
        assert shutdown_requests == 1
        assert service.process is not None
        assert service.process.terminate_calls == 0
        assert service.process.kill_calls == 0
        assert service.process.poll() == 0
        assert not h.instance_record_path(layout).exists()

    def test_required_window_failure_happens_before_automatic_browser_open(self, monkeypatch, tmp_path):
        layout = h.make_portable_layout(tmp_path)
        h.create_service_executable(layout)
        service = h.FakePortableService(layout)
        monkeypatch.setattr(portable_launcher.subprocess, "Popen", service)
        opened: list[str] = []
        try:
            result = portable_launcher.run_portable_launcher(
                h.launcher_executable(layout),
                startup_timeout=10.0,
                window_factory=lambda **_kwargs: None,
                browser=opened.append,
            )
        finally:
            service.cleanup()

        assert result == portable_launcher.EXIT_UI_UNAVAILABLE
        assert opened == []


class TestBrowserSemantics:
    def test_no_browser_flag_skips_auto_open_but_keeps_the_control_window_working(self, monkeypatch, tmp_path):
        layout = h.make_portable_layout(tmp_path)
        h.create_service_executable(layout)
        service = h.FakePortableService(layout)
        monkeypatch.setattr(portable_launcher.subprocess, "Popen", service)
        created: list[FakeLauncherWindow] = []
        opened: list[str] = []
        try:
            result = portable_launcher.run_portable_launcher(
                h.launcher_executable(layout),
                startup_timeout=10.0,
                window_factory=window_factory("open_reader", created=created),
                browser=opened.append,
                no_browser=True,
            )
        finally:
            service.cleanup()

        assert result == 0
        assert len(created) == 1
        assert len(opened) == 1
        assert opened[0].startswith("http://127.0.0.1:")
        assert service.process is not None
        assert service.process.terminate_calls == 0

    def test_browser_failure_keeps_the_service_running(self, monkeypatch, tmp_path):
        layout = h.make_portable_layout(tmp_path)
        h.create_service_executable(layout)
        service = h.FakePortableService(layout)
        monkeypatch.setattr(portable_launcher.subprocess, "Popen", service)
        created: list[FakeLauncherWindow] = []
        attempts: list[str] = []

        def failing_browser(url: str) -> bool:
            attempts.append(url)
            return False

        try:
            result = portable_launcher.run_portable_launcher(
                h.launcher_executable(layout),
                startup_timeout=10.0,
                window_factory=window_factory("quit", created=created),
                browser=failing_browser,
            )
        finally:
            service.cleanup()

        assert result == 0
        assert attempts == [service.endpoint.base_url] if service.endpoint is not None else True
        assert len(created) == 1
        assert service.process is not None
        assert service.process.kill_calls == 0


class TestPortableDataGovernance:
    """P1-03：数据格式治理在单实例锁之后、服务启动之前完成，失败不启动服务。"""

    def _guard_spawn(self, monkeypatch: Any) -> list[Any]:
        """把 Popen 换成探针：本组用例里任何服务启动都是缺陷。"""

        spawns: list[Any] = []

        def spy(command: list[str], **kwargs: Any) -> Any:
            spawns.append(command)
            raise AssertionError("数据命令路径不得启动服务进程")

        monkeypatch.setattr(portable_launcher.subprocess, "Popen", spy)
        return spawns

    def test_prepare_runs_after_lock_and_before_service_spawn(self, monkeypatch, tmp_path):
        layout = h.make_portable_layout(tmp_path)
        h.create_service_executable(layout)
        service = h.FakePortableService(layout)
        observed: dict[str, Any] = {}
        lock_events: list[bool] = []
        real_lock_factory = portable_launcher.create_instance_lock

        class NotingLock:
            def __init__(self, inner: Any) -> None:
                self._inner = inner

            def acquire(self) -> bool:
                held = bool(self._inner.acquire())
                lock_events.append(held)
                return held

            def release(self) -> None:
                self._inner.release()

        def lock_factory(selected: paths.RuntimeLayout) -> Any:
            return NotingLock(real_lock_factory(selected))

        def spy_popen(command: list[str], **kwargs: Any) -> Any:
            observed["lock_acquired_before_spawn"] = lock_events == [True]
            observed["schema_state_at_spawn"] = portable_data.detect_schema(layout).state
            observed["manifest_at_spawn"] = portable_data.manifest_path(layout).is_file()
            return service(command, **kwargs)

        monkeypatch.setattr(portable_launcher.subprocess, "Popen", spy_popen)
        try:
            result = portable_launcher.run_portable_launcher(
                h.launcher_executable(layout),
                startup_timeout=10.0,
                lock_factory=lock_factory,
                window_factory=window_factory("quit"),
                browser=lambda url: True,
            )
        finally:
            service.cleanup()

        assert result == 0
        assert observed == {
            "lock_acquired_before_spawn": True,
            "schema_state_at_spawn": "current",
            "manifest_at_spawn": True,
        }
        assert portable_data.detect_schema(layout).state == "current"
        assert len(list(portable_data.backup_root(layout).iterdir())) == 2  # 备份目录 + 迁移账本

    def test_newer_data_schema_refuses_to_start_the_service(self, monkeypatch, tmp_path, capsys):
        layout = h.make_portable_layout(tmp_path)
        h.create_service_executable(layout)
        payload = {
            "schema_version": portable_data.SCHEMA_VERSION + 1,
            "product": portable_data.PRODUCT,
            "app_version": "9.9.9",
            "created_at": "2026-09-11T08:00:00+00:00",
            "updated_at": "2026-09-11T08:00:00+00:00",
            "applied_migrations": [],
        }
        manifest = portable_data.manifest_path(layout)
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        original = manifest.read_bytes()
        spawns = self._guard_spawn(monkeypatch)

        result = portable_launcher.run_portable_launcher(
            h.launcher_executable(layout),
            startup_timeout=1.0,
            no_browser=True,
            no_ui=True,
        )

        assert result == portable_launcher.EXIT_LAUNCHER_ERROR
        assert spawns == []
        assert manifest.read_bytes() == original
        assert "ERROR [portable_data_schema_newer]" in capsys.readouterr().err
        assert "ERROR [portable_data_schema_newer]" in _read_launcher_log(layout)

    def test_data_report_command_never_spawns_the_service(self, monkeypatch, tmp_path, capsys):
        layout = h.make_portable_layout(tmp_path)
        h.create_service_executable(layout)
        model = layout.data_root / "models" / "layout.onnx"
        model.write_bytes(b"model-bytes")
        spawns = self._guard_spawn(monkeypatch)

        result = portable_launcher.run_portable_launcher(
            h.launcher_executable(layout),
            no_browser=True,
            no_ui=True,
            data_command=portable_launcher.DataCommand(kind="report"),
        )

        assert result == 0
        assert spawns == []
        stdout = capsys.readouterr().out
        assert "文档缓存" in stdout
        assert "重新下载" in stdout
        assert model.is_file()

    def test_clean_command_previews_by_default_and_deletes_only_the_selected_category(
        self, monkeypatch, tmp_path, capsys
    ):
        layout = h.make_portable_layout(tmp_path)
        h.create_service_executable(layout)
        right_pdf = layout.data_root / "documents" / "hash" / "right.pdf"
        right_pdf.parent.mkdir(parents=True, exist_ok=True)
        right_pdf.write_bytes(b"%PDF-1.4 cached")
        model = layout.data_root / "models" / "layout.onnx"
        model.write_bytes(b"model")
        spawns = self._guard_spawn(monkeypatch)

        preview = portable_launcher.run_portable_launcher(
            h.launcher_executable(layout),
            no_browser=True,
            no_ui=True,
            data_command=portable_launcher.DataCommand(kind="clean", categories=("documents",)),
        )

        assert preview == 0
        assert right_pdf.is_file()
        assert "预览" in capsys.readouterr().out

        confirmed = portable_launcher.run_portable_launcher(
            h.launcher_executable(layout),
            no_browser=True,
            no_ui=True,
            data_command=portable_launcher.DataCommand(kind="clean", categories=("documents",), confirmed=True),
        )

        assert confirmed == 0
        assert spawns == []
        assert not right_pdf.exists()
        assert not right_pdf.parent.exists()
        assert model.read_bytes() == b"model"
        assert "已删除" in capsys.readouterr().out

    def test_import_data_command_copies_models_and_never_imports_config(self, monkeypatch, tmp_path, capsys):
        layout = h.make_portable_layout(tmp_path)
        h.create_service_executable(layout)
        old = h.make_portable_layout(tmp_path / "old", name="旧安装")
        (old.data_root / "models").mkdir(parents=True, exist_ok=True)
        (old.data_root / "models" / "layout.onnx").write_bytes(b"model-bytes")
        (old.data_root / "config").mkdir(parents=True, exist_ok=True)
        (old.data_root / "config" / "config.toml").write_bytes(b"from-old-install")
        spawns = self._guard_spawn(monkeypatch)

        result = portable_launcher.run_portable_launcher(
            h.launcher_executable(layout),
            no_browser=True,
            no_ui=True,
            data_command=portable_launcher.DataCommand(kind="import", source=old.data_root, confirmed=True),
        )

        assert result == 0
        assert spawns == []
        assert (layout.data_root / "models" / "layout.onnx").read_bytes() == b"model-bytes"
        assert not (layout.data_root / "config" / "config.toml").exists()
        assert "config/config.toml" in capsys.readouterr().out
