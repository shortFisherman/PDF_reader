"""P1-02 控制入口：令牌认证控制通道、三个固定命令与窗口关闭语义。

固定语义（需求 4）：

* 三个入口是唯一控制面：打开阅读器 / 打开日志 / 退出程序，走同一条 dispatch；
* 关闭浏览器标签页不等于退出服务；
* 关闭控制窗口等于请求退出程序，而且只请求协作退出，不直接结束进程。

控制通道的令牌不出现在请求路径、响应体或日志里；未认证请求一律 404，
与路径不存在不可区分。
"""

from __future__ import annotations

import http.client
import json
import logging
import threading
import types
from pathlib import Path
from typing import Any

import pytest

from pdf_reader import portable_launcher, portable_runtime

CONTROL_TOKEN = "launcher-token-" + "c" * 32
CONTROL_PATH = portable_runtime.CONTROL_PATH
TOKEN_HEADER = portable_runtime.CONTROL_TOKEN_HEADER


def _call(
    server: portable_launcher.LauncherControlServer,
    method: str,
    path: str,
    *,
    payload: Any = None,
    token: str | None = None,
    raw_body: bytes | None = None,
    declared_length: int | None = None,
) -> tuple[int, dict[str, Any]]:
    """按真实 HTTP 协议调用控制通道：令牌走包头，命令走 JSON 体。"""

    connection = http.client.HTTPConnection(portable_launcher.CONTROL_SERVER_HOST, server.server_port, timeout=5.0)
    try:
        headers: dict[str, str] = {}
        if token is not None:
            headers[TOKEN_HEADER] = token
        if declared_length is not None:
            headers["Content-Length"] = str(declared_length)
        if raw_body is not None:
            body: bytes | None = raw_body
        else:
            body = None if payload is None else json.dumps(payload).encode("utf-8")
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        status = response.status
        content = response.read()
    finally:
        connection.close()
    return status, json.loads(content.decode("utf-8"))


class RecordingDispatch:
    """记录控制命令并返回可断言的 detail：模拟启动器主流程里的 dispatcher。"""

    def __init__(self) -> None:
        self.commands: list[str] = []

    def __call__(self, command: str) -> str:
        self.commands.append(command)
        return f"accepted:{command}"


@pytest.fixture
def control_channel():
    dispatch = RecordingDispatch()
    server = portable_launcher.LauncherControlServer(dispatch=dispatch, control_token=CONTROL_TOKEN)
    server.start()
    try:
        yield server, dispatch
    finally:
        server.stop()


class TestControlChannelContract:
    @pytest.mark.parametrize("command", sorted(portable_runtime.CONTROL_COMMANDS))
    def test_every_documented_command_is_accepted_with_the_control_token(self, control_channel, command):
        server, dispatch = control_channel

        status, body = _call(server, "POST", CONTROL_PATH, payload={"command": command}, token=CONTROL_TOKEN)

        assert status == 200
        assert body == {"status": "accepted", "detail": f"accepted:{command}"}
        assert dispatch.commands == [command]

    def test_missing_or_foreign_token_is_an_indistinguishable_404(self, control_channel):
        server, dispatch = control_channel
        foreign = CONTROL_TOKEN[:-1] + "d"

        unauthenticated = _call(server, "POST", CONTROL_PATH, payload={"command": "quit"})
        forged = _call(server, "POST", CONTROL_PATH, payload={"command": "quit"}, token=foreign)

        assert unauthenticated == (404, {"status": "not_found"})
        assert forged == (404, {"status": "not_found"})
        assert dispatch.commands == []

    def test_unknown_command_is_rejected_without_side_effects(self, control_channel):
        server, dispatch = control_channel

        status, body = _call(server, "POST", CONTROL_PATH, payload={"command": "reboot"}, token=CONTROL_TOKEN)

        assert (status, body) == (400, {"status": "invalid_command"})
        assert dispatch.commands == []

    def test_malformed_and_oversized_bodies_are_rejected(self, control_channel):
        server, dispatch = control_channel

        malformed = _call(server, "POST", CONTROL_PATH, raw_body=b"{ not json", token=CONTROL_TOKEN)
        not_an_object = _call(server, "POST", CONTROL_PATH, raw_body=b"[]", token=CONTROL_TOKEN)
        oversized = _call(
            server,
            "POST",
            CONTROL_PATH,
            raw_body=b"",
            token=CONTROL_TOKEN,
            declared_length=portable_launcher.MAXIMUM_CONTROL_BODY_BYTES + 1,
        )

        assert malformed == (400, {"status": "invalid_request"})
        assert not_an_object == (400, {"status": "invalid_command"})
        assert oversized == (400, {"status": "invalid_request"})
        assert dispatch.commands == []

    def test_get_and_foreign_paths_are_not_found(self, control_channel):
        server, dispatch = control_channel

        get_control = _call(server, "GET", CONTROL_PATH, token=CONTROL_TOKEN)
        post_shutdown = _call(server, "POST", portable_runtime.SHUTDOWN_PATH, payload={}, token=CONTROL_TOKEN)
        trailing_slash = _call(server, "POST", CONTROL_PATH + "/", payload={"command": "quit"}, token=CONTROL_TOKEN)

        assert get_control == (404, {"status": "not_found"})
        assert post_shutdown == (404, {"status": "not_found"})
        assert trailing_slash == (404, {"status": "not_found"})
        assert dispatch.commands == []

    @pytest.mark.parametrize("weak_token", ["", "short", "launcher-token-" + "c" * 10])
    def test_weak_control_tokens_are_refused_at_construction(self, weak_token):
        with pytest.raises(portable_launcher.PortableLaunchError) as excinfo:
            portable_launcher.LauncherControlServer(dispatch=RecordingDispatch(), control_token=weak_token)

        assert excinfo.value.code == "launcher_control_token_invalid"

    def test_control_channel_binds_loopback_on_an_ephemeral_port(self, control_channel):
        server, _dispatch = control_channel

        host, port = server.server_address[0], server.server_port

        assert host == portable_launcher.CONTROL_SERVER_HOST
        assert port > 0
        assert server.base_url == portable_runtime.loopback_base_url(host, port)
        assert CONTROL_TOKEN not in server.base_url

    def test_control_requests_never_leak_the_path_or_token_into_logs(self, control_channel, caplog):
        server, _dispatch = control_channel

        with caplog.at_level(logging.DEBUG, logger=portable_launcher.LOGGER_NAME):
            _call(server, "POST", CONTROL_PATH, payload={"command": "open_logs"}, token=CONTROL_TOKEN)
            _call(server, "POST", CONTROL_PATH, payload={"command": "quit"})

        rendered = [record.getMessage() for record in caplog.records]
        assert not any(CONTROL_PATH in message or CONTROL_TOKEN in message for message in rendered)


SERVICE_URL = "http://127.0.0.1:5100/"


def _dispatcher(
    tmp_path: Path,
    *,
    opener: Any = None,
    logs_opener: Any = None,
) -> portable_launcher.LauncherCommandDispatcher:
    """构造注入全部外部动作的分发器：测试绝不真的打开浏览器或文件管理器。"""

    return portable_launcher.LauncherCommandDispatcher(
        service_url=SERVICE_URL,
        logs_path=tmp_path / "logs",
        opener=opener,
        logs_opener=logs_opener,
    )


class TestLauncherCommandDispatcher:
    def test_open_reader_opens_the_service_url_and_never_quits(self, tmp_path):
        opened: list[str] = []
        dispatcher = _dispatcher(tmp_path, opener=opened.append)

        assert dispatcher.dispatch("open_reader") == "opened"

        assert opened == [SERVICE_URL]
        assert dispatcher.quit_requested is False
        assert dispatcher.wait_for_quit(0.0) is False

    def test_open_reader_failure_degrades_to_unavailable_without_quitting(self, tmp_path):
        def refusing(_url: str) -> bool:
            return False

        def exploding(_url: str) -> bool:
            raise RuntimeError("没有可用的浏览器")

        refusing_dispatcher = _dispatcher(tmp_path, opener=refusing)
        exploding_dispatcher = _dispatcher(tmp_path, opener=exploding)

        assert refusing_dispatcher.dispatch("open_reader") == "unavailable"
        assert exploding_dispatcher.dispatch("open_reader") == "unavailable"
        assert refusing_dispatcher.quit_requested is False
        assert exploding_dispatcher.quit_requested is False

    def test_open_logs_prepares_the_directory_and_uses_the_injected_opener(self, tmp_path):
        seen: list[Path] = []
        dispatcher = _dispatcher(tmp_path, logs_opener=lambda path: (seen.append(path), True)[1])

        assert dispatcher.dispatch("open_logs") == "opened"

        assert seen == [tmp_path / "logs"]
        assert (tmp_path / "logs").is_dir()
        assert dispatcher.quit_requested is False

    def test_open_logs_failure_degrades_to_unavailable(self, tmp_path):
        def refusing(_path: Path) -> bool:
            return False

        def exploding(_path: Path) -> bool:
            raise OSError("没有文件管理器")

        refusing_dispatcher = _dispatcher(tmp_path, logs_opener=refusing)
        exploding_dispatcher = _dispatcher(tmp_path, logs_opener=exploding)

        assert refusing_dispatcher.dispatch("open_logs") == "unavailable"
        assert exploding_dispatcher.dispatch("open_logs") == "unavailable"
        assert refusing_dispatcher.quit_requested is False
        assert exploding_dispatcher.quit_requested is False

    def test_quit_only_raises_a_cooperative_request(self, tmp_path):
        opened: list[str] = []
        dispatcher = _dispatcher(tmp_path, opener=opened.append)

        assert dispatcher.dispatch("quit") == "quitting"

        assert dispatcher.quit_requested is True
        assert dispatcher.wait_for_quit(0.5) is True
        # 退出请求只置位：真正的收敛（停止接收 → 等待任务 → 关闭 AppState）由主流程负责。
        assert opened == []
        assert dispatcher.dispatch("quit") == "quitting"

    def test_unknown_command_is_a_programming_error(self, tmp_path):
        dispatcher = _dispatcher(tmp_path, opener=lambda _url: True)

        with pytest.raises(ValueError, match="未知控制命令"):
            dispatcher.dispatch("reboot")


class FakeWidget:
    """最小 tkinter 控件替身：只记录构造参数与 grid 调用。"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs
        self.grid_calls: list[dict[str, Any]] = []

    def grid(self, **kwargs: Any) -> None:
        self.grid_calls.append(kwargs)


class FakeButton(FakeWidget):
    """可点击按钮：invoke 等价于用户点击。"""

    def invoke(self) -> Any:
        return self.kwargs["command"]()


class FakeTtkModule:
    """按类型记录创建出的控件，供窗口结构断言使用。"""

    def __init__(self) -> None:
        self.frames: list[FakeWidget] = []
        self.labels: list[FakeWidget] = []
        self.buttons: list[FakeButton] = []

    def Frame(self, *args: Any, **kwargs: Any) -> FakeWidget:
        widget = FakeWidget(*args, **kwargs)
        self.frames.append(widget)
        return widget

    def Label(self, *args: Any, **kwargs: Any) -> FakeWidget:
        widget = FakeWidget(*args, **kwargs)
        self.labels.append(widget)
        return widget

    def Button(self, *args: Any, **kwargs: Any) -> FakeButton:
        widget = FakeButton(*args, **kwargs)
        self.buttons.append(widget)
        return widget


class FakeTkRoot:
    """最小 Tk 根窗口替身：记录标题、协议、定时回调与销毁次数。"""

    def __init__(self) -> None:
        self.title_text: str | None = None
        self.resizable_calls: list[tuple[bool, bool]] = []
        self.protocols: dict[str, Any] = {}
        self.after_calls: list[tuple[int, Any]] = []
        self.destroy_calls = 0
        self.mainloop_calls = 0

    def title(self, text: str) -> None:
        self.title_text = text

    def resizable(self, width: bool, height: bool) -> None:
        self.resizable_calls.append((width, height))

    def protocol(self, name: str, callback: Any) -> None:
        self.protocols[name] = callback

    def after(self, delay: int, callback: Any) -> str:
        self.after_calls.append((delay, callback))
        return f"after#{len(self.after_calls)}"

    def destroy(self) -> None:
        self.destroy_calls += 1

    def mainloop(self) -> None:
        self.mainloop_calls += 1


class StubWatcher:
    """最小服务进程监督器：主循环只读取 finished 一个状态。"""

    def __init__(self, *, finished: bool = False) -> None:
        self._finished = threading.Event()
        if finished:
            self._finished.set()

    @property
    def finished(self) -> bool:
        return self._finished.is_set()

    def finish(self) -> None:
        self._finished.set()


def _build_window(
    dispatch: Any,
    *,
    should_stop: Any = None,
    interval_ms: int = portable_launcher.WINDOW_POLL_INTERVAL_MS,
) -> tuple[portable_launcher._TkinterLauncherWindow, FakeTkRoot, FakeTtkModule]:
    root = FakeTkRoot()
    ttk_module = FakeTtkModule()
    window = portable_launcher._TkinterLauncherWindow(
        root=root,
        ttk_module=ttk_module,
        dispatch=dispatch,
        should_stop=should_stop if should_stop is not None else (lambda: False),
        interval_ms=interval_ms,
    )
    return window, root, ttk_module


class TestControlWindowSemantics:
    def test_window_exposes_exactly_the_three_documented_commands(self):
        dispatch = RecordingDispatch()
        _window, root, ttk_module = _build_window(dispatch)

        assert [button.kwargs["text"] for button in ttk_module.buttons] == ["打开阅读器", "打开日志", "退出程序"]
        assert root.title_text == portable_launcher.WINDOW_TITLE

        for button in ttk_module.buttons:
            button.invoke()

        assert dispatch.commands == ["open_reader", "open_logs", "quit"]

    def test_window_hint_documents_the_fixed_exit_semantics(self):
        dispatch = RecordingDispatch()
        _window, _root, ttk_module = _build_window(dispatch)

        hints = [label.kwargs["text"] for label in ttk_module.labels]

        assert portable_launcher.WINDOW_HINT in hints
        assert "关闭浏览器标签" in portable_launcher.WINDOW_HINT
        assert "关闭本窗口即退出程序" in portable_launcher.WINDOW_HINT

    def test_window_close_is_bound_to_wm_delete_and_is_idempotent(self):
        dispatch = RecordingDispatch()
        window, root, _ttk_module = _build_window(dispatch)

        assert root.protocols["WM_DELETE_WINDOW"] == window.close

        window.close()
        window.close()

        assert root.destroy_calls == 1
        assert dispatch.commands == []

    def test_window_closes_itself_without_rescheduling_when_the_service_is_gone(self):
        stopped = threading.Event()
        stopped.set()
        _window, root, _ttk_module = _build_window(RecordingDispatch(), should_stop=stopped.is_set)

        root.after_calls[0][1]()

        assert root.destroy_calls == 1
        assert len(root.after_calls) == 1

    def test_window_keeps_polling_with_a_floor_interval_while_the_service_runs(self):
        _window, root, _ttk_module = _build_window(RecordingDispatch(), interval_ms=1)

        delay, poll = root.after_calls[0]
        poll()

        assert delay == 50
        assert len(root.after_calls) == 2
        assert root.destroy_calls == 0

    def test_window_run_enters_the_tk_main_loop(self):
        _window, root, _ttk_module = _build_window(RecordingDispatch())

        _window.run()

        assert root.mainloop_calls == 1

    def test_missing_tkinter_degrades_to_no_window(self, monkeypatch):
        monkeypatch.setattr(portable_launcher, "_import_tkinter", lambda: None)

        window = portable_launcher.create_tkinter_window(
            dispatch=RecordingDispatch(),
            should_stop=lambda: False,
        )

        assert window is None

    def test_window_creation_reports_unavailable_when_tk_cannot_open_a_display(self, monkeypatch, caplog):
        def failing_tk() -> Any:
            raise RuntimeError("no display name and no $DISPLAY environment variable")

        monkeypatch.setattr(
            portable_launcher,
            "_import_tkinter",
            lambda: (types.SimpleNamespace(Tk=failing_tk), FakeTtkModule()),
        )

        with caplog.at_level(logging.WARNING, logger=portable_launcher.LOGGER_NAME):
            window = portable_launcher.create_tkinter_window(
                dispatch=RecordingDispatch(),
                should_stop=lambda: False,
            )

        assert window is None
        assert any("无法创建必需的控制窗口" in record.getMessage() for record in caplog.records)

    def test_window_creation_builds_the_real_dialog_when_tk_is_available(self, monkeypatch):
        dispatch = RecordingDispatch()
        root = FakeTkRoot()
        ttk_module = FakeTtkModule()
        monkeypatch.setattr(
            portable_launcher,
            "_import_tkinter",
            lambda: (types.SimpleNamespace(Tk=lambda: root), ttk_module),
        )

        window = portable_launcher.create_tkinter_window(dispatch=dispatch, should_stop=lambda: False)

        assert isinstance(window, portable_launcher._TkinterLauncherWindow)
        assert len(ttk_module.buttons) == 3
        assert root.protocols["WM_DELETE_WINDOW"] == window.close

        window.close()
        assert root.destroy_calls == 1

    def test_loop_requests_quit_when_the_control_window_closes(self, tmp_path):
        opened: list[str] = []
        dispatcher = _dispatcher(tmp_path, opener=opened.append)
        created: list[Any] = []

        class ClosingWindow:
            def __init__(self, **_kwargs: Any) -> None:
                self.closed = False
                created.append(self)

            def run(self) -> None:
                self.close()

            def close(self) -> None:
                self.closed = True

        quit_requested = portable_launcher._run_launcher_loop(
            dispatcher,
            watcher=StubWatcher(finished=False),
            window_factory=ClosingWindow,
        )

        assert quit_requested is True
        assert dispatcher.quit_requested is True
        assert len(created) == 1
        assert created[0].closed is True
        # 关窗口只请求退出程序，绝不顺手打开浏览器。
        assert opened == []

    def test_loop_returns_only_after_a_window_button_asks_for_quit(self, tmp_path):
        dispatcher = _dispatcher(tmp_path, opener=lambda _url: True)
        dispatched: list[str] = []

        class QuittingWindow:
            def __init__(self, *, dispatch: Any, should_stop: Any) -> None:
                self._dispatch = dispatch
                self._should_stop = should_stop

            def run(self) -> None:
                dispatched.append(self._dispatch("quit"))

            def close(self) -> None:
                pass

        quit_requested = portable_launcher._run_launcher_loop(
            dispatcher,
            watcher=StubWatcher(finished=False),
            window_factory=QuittingWindow,
        )

        assert dispatched == ["quitting"]
        assert quit_requested is True

    def test_loop_without_ui_waits_for_the_service_to_stop_itself(self, tmp_path):
        dispatcher = _dispatcher(tmp_path, opener=lambda _url: True)
        watcher = StubWatcher(finished=False)
        threading.Timer(0.05, watcher.finish).start()

        quit_requested = portable_launcher._run_launcher_loop(
            dispatcher,
            watcher=watcher,
            no_ui=True,
            poll_interval=0.01,
        )

        assert quit_requested is False
        assert dispatcher.quit_requested is False

    @pytest.mark.parametrize("factory_result", [None, "raises"])
    def test_loop_reports_stable_error_when_required_window_is_unavailable(self, tmp_path, factory_result):
        dispatcher = _dispatcher(tmp_path, opener=lambda _url: True)
        watcher = StubWatcher(finished=False)

        def unavailable_factory(**_kwargs: Any) -> Any:
            if factory_result == "raises":
                raise RuntimeError("窗口不可用")
            return None

        with pytest.raises(portable_launcher.PortableLaunchError) as error:
            portable_launcher._run_launcher_loop(
                dispatcher,
                watcher=watcher,
                window_factory=unavailable_factory,
                poll_interval=0.01,
            )

        assert error.value.code == "launcher_ui_unavailable"
        assert dispatcher.quit_requested is False

    def test_service_finishing_first_does_not_become_a_user_quit(self, tmp_path):
        dispatcher = _dispatcher(tmp_path, opener=lambda _url: True)
        watcher = StubWatcher(finished=True)

        class ServiceStoppedWindow:
            def __init__(self, **_kwargs: Any) -> None:
                pass

            def run(self) -> None:
                pass

            def close(self) -> None:
                pass

        assert (
            portable_launcher._run_launcher_loop(
                dispatcher,
                watcher=watcher,
                window_factory=ServiceStoppedWindow,
            )
            is False
        )
        assert dispatcher.quit_requested is False
