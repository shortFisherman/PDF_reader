"""P1-04 发行态错误展示与安全诊断的契约测试。

固定语义（需求 2/3/4/6）：

* 每个发行态稳定错误码都有用户可读标题/说明/建议；未知码也必须落到安全兜底；
* 不可写目录、配置错误、端口冲突、资源缺失、模型下载失败与服务异常退出六类各自
  有定义好的安全文案与（可恢复时）恢复入口；
* 错误窗口固定提供复制安全诊断信息 / 打开日志目录 / 退出，可恢复错误额外给出入口；
* 诊断文本在生成前脱敏，绝不包含 API Key、Bearer token、控制/健康令牌、Prompt、
  PDF 正文或用户名绝对路径；
* 文案目录是可稳定核对的白名单：新增错误码必须同时补文案，避免发行态与 CLI 语义漂移。
"""

from __future__ import annotations

import re
import types
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from pdf_reader import portable_data, portable_errors, portable_runtime

REPO_SRC = Path(portable_errors.__file__).resolve().parent
PORTABLE_MODULES = (
    "portable_launcher.py",
    "portable_runtime.py",
    "portable_instance.py",
    "portable_service.py",
    "portable_data.py",
)
CODE_ASSIGNMENT = re.compile(r'code\s*=\s*"([a-z0-9_]+)"')
FAIL_CALL = re.compile(r'fail\(\s*"([a-z0-9_]+)"')
BRACKETED_CODE = re.compile(r"ERROR \[([a-z0-9_]+)\]")


def _fixed_clock() -> datetime:
    return datetime(2026, 9, 11, 12, 0, 0, tzinfo=UTC)


def _emitted_codes() -> set[str]:
    found: set[str] = set()
    for name in PORTABLE_MODULES:
        text = (REPO_SRC / name).read_text(encoding="utf-8")
        found.update(CODE_ASSIGNMENT.findall(text))
        found.update(FAIL_CALL.findall(text))
        found.update(BRACKETED_CODE.findall(text))
    return found


class TestErrorCatalog:
    def test_every_required_error_class_has_a_safe_presentation(self):
        for class_name, codes in portable_errors.REQUIRED_ERROR_CLASSES.items():
            assert codes, f"{class_name} 必须至少有一个代表错误码"
            for code in codes:
                presentation = portable_errors.describe_error(code)
                assert presentation.code == code
                assert presentation.title and "\n" not in presentation.title
                assert presentation.summary
                assert presentation.guidance

    def test_unwritable_directory_offers_a_program_directory_entry(self):
        presentation = portable_errors.describe_error("portable_data_not_writable")

        assert presentation.recovery == portable_errors.ACTION_OPEN_PROGRAM_DIR
        assert presentation.recoverable is True

    def test_config_error_is_recoverable_through_the_config_directory(self):
        presentation = portable_errors.describe_error("config_invalid")

        assert presentation.recovery == portable_errors.ACTION_OPEN_CONFIG_DIR
        assert "配置" in presentation.summary

    def test_port_conflict_is_recoverable_by_retrying(self):
        presentation = portable_errors.describe_error("service_port_in_use")

        assert presentation.recovery == portable_errors.ACTION_RETRY
        assert "端口" in presentation.summary
        assert "不会终止" in presentation.guidance

    def test_missing_resource_points_at_the_program_directory(self):
        for code in ("portable_resource_missing", "service_executable_missing"):
            assert portable_errors.describe_error(code).recovery == portable_errors.ACTION_OPEN_PROGRAM_DIR

    def test_model_download_failure_message_is_safe_and_actionable(self):
        presentation = portable_errors.describe_error("model_download_failed")

        assert "下载" in presentation.summary
        assert "网络" in presentation.guidance

    def test_abnormal_service_exit_is_recoverable(self):
        for code in ("service_exited_while_running", "service_exited_before_ready"):
            assert portable_errors.describe_error(code).recovery == portable_errors.ACTION_RETRY

    def test_unknown_code_falls_back_to_a_safe_generic_presentation(self):
        presentation = portable_errors.describe_error("brand_new_unmapped_code")

        assert presentation.code == "brand_new_unmapped_code"
        assert presentation.title and presentation.summary and presentation.guidance

    def test_unknown_code_never_leaks_into_the_presentation(self):
        weird = "sk-exampleexampleexample123456"

        presentation = portable_errors.describe_error(weird)

        assert "sk-exampleexampleexample123456" not in presentation.guidance
        assert weird in presentation.code

    def test_catalog_covers_every_code_emitted_by_the_portable_layer(self):
        emitted = _emitted_codes()

        missing = sorted(emitted - set(portable_errors.ERROR_CATALOG))
        assert not missing, f"以下发行态错误码还没有用户可读文案：{missing}"

    def test_catalog_covers_every_portable_data_code_constant(self):
        constants = {
            value for name, value in vars(portable_data).items() if name.startswith("CODE_") and isinstance(value, str)
        }

        missing = sorted(constants - set(portable_errors.ERROR_CATALOG))
        assert not missing, f"以下便携数据错误码还没有用户可读文案：{missing}"

    def test_catalog_covers_every_service_published_code(self):
        published = {portable_runtime.SERVICE_PORT_IN_USE_CODE}

        missing = sorted(published - set(portable_errors.ERROR_CATALOG))
        assert not missing, f"以下服务就绪失败码还没有用户可读文案：{missing}"

    def test_catalog_exposes_the_stable_launcher_exit_codes(self):
        for code in ("service_port_in_use", "service_start_timeout", "launcher_ui_unavailable"):
            assert code in portable_errors.ERROR_CATALOG

    def test_catalog_entries_are_stable_single_line_text(self):
        for code, presentation in portable_errors.ERROR_CATALOG.items():
            assert code == presentation.code
            assert code == code.strip()
            assert presentation.summary.strip() == presentation.summary
            assert presentation.guidance.strip() == presentation.guidance


class TestSafeDiagnostics:
    def test_diagnostics_never_leak_secrets_prompts_or_document_body(self, tmp_path):
        portable_root = tmp_path / "PDF Reader 便携目录"
        home = tmp_path / "home" / "exampleuser"
        detail = "\n".join(
            (
                'api_key="sk-exampleexampleexample123456"',
                "Authorization: Bearer exampleBearerTokenValue1234567890",
                "X-PDF-Reader-Control-Token: launcher-token-exampleexampleexample",
                "X-PDF-Reader-Health-Token: health-token-exampleexampleexample",
                "health_token=health-token-exampleexampleexample",
                "prompt=请把这段用户机密正文翻译成中文",
                "pdf_text=CONFIDENTIAL PDF BODY TEXT",
                f"log={portable_root}/data/logs/launcher.log",
                f"document={home}/Documents/我的机密资料.pdf",
            )
        )
        presentation = portable_errors.describe_error("service_start_timeout")

        diagnostics = portable_errors.build_diagnostics(
            presentation=presentation,
            detail=detail,
            app_version="9.9.9",
            exit_code=3,
            portable_root=portable_root,
            home=home,
            platform_label="TestOS-1.0",
            clock=_fixed_clock,
        )

        for leak in (
            "sk-exampleexampleexample123456",
            "exampleBearerTokenValue1234567890",
            "launcher-token-exampleexampleexample",
            "health-token-exampleexampleexample",
            "用户机密正文",
            "CONFIDENTIAL PDF BODY TEXT",
            "exampleuser",
            str(portable_root),
        ):
            assert leak not in diagnostics, f"诊断文本泄露了敏感内容：{leak}"

    def test_diagnostics_keep_relative_log_location_and_version(self, tmp_path):
        presentation = portable_errors.describe_error("service_port_in_use")

        diagnostics = portable_errors.build_diagnostics(
            presentation=presentation,
            detail="端口被占用",
            app_version="1.2.3",
            exit_code=4,
            portable_root=tmp_path / "PDF Reader",
            platform_label="TestOS-1.0",
            clock=_fixed_clock,
        )

        assert "1.2.3" in diagnostics
        assert "service_port_in_use" in diagnostics
        assert "data/logs/launcher.log" in diagnostics
        assert str(tmp_path) not in diagnostics

    def test_diagnostics_do_not_leak_the_portable_root(self, tmp_path):
        root = tmp_path / "用户名目录" / "PDF Reader"
        presentation = portable_errors.describe_error("portable_data_not_writable")

        diagnostics = portable_errors.build_diagnostics(
            presentation=presentation,
            detail=f"无法写入 {root}/data",
            app_version="1.0.0",
            exit_code=2,
            portable_root=root,
            home=tmp_path / "用户名目录",
            platform_label="TestOS-1.0",
            clock=_fixed_clock,
        )

        assert "用户名目录" not in diagnostics
        assert "<portable-root>" in diagnostics

    def test_sanitizer_redacts_windows_and_posix_user_paths(self):
        text = r"C:\Users\alice\AppData\Local\Temp\x and /home/bob/PDF Reader/data"

        safe = portable_errors.sanitize_diagnostic_text(text, home=Path("/nonexistent-home"))

        assert "alice" not in safe
        assert "bob" not in safe

    def test_sanitizer_bounds_length_and_strips_control_characters(self):
        # 用空格分隔的长文本：既验证长度收敛，又不至于整段命中不透明令牌脱敏。
        text = "ab\x00cd\x07 " + " ".join(["word"] * 400)

        safe = portable_errors.sanitize_diagnostic_text(text, limit=40)

        assert "\x00" not in safe
        assert "\x07" not in safe
        assert len(safe) <= 41
        assert safe.endswith("…")

    def test_sanitizer_is_total_for_non_string_input(self):
        assert isinstance(portable_errors.sanitize_diagnostic_text(ValueError("boom")), str)


class FakeWidget:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs
        self.grid_calls: list[dict[str, Any]] = []

    def grid(self, **kwargs: Any) -> None:
        self.grid_calls.append(kwargs)


class FakeButton(FakeWidget):
    def invoke(self) -> Any:
        return self.kwargs["command"]()


class FakeTtkModule:
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
    def __init__(self) -> None:
        self.title_text: str | None = None
        self.resizable_calls: list[tuple[bool, bool]] = []
        self.protocols: dict[str, Any] = {}
        self.destroy_calls = 0
        self.mainloop_calls = 0
        self.clipboard: list[str] = []
        self.update_calls = 0

    def title(self, text: str) -> None:
        self.title_text = text

    def resizable(self, width: bool, height: bool) -> None:
        self.resizable_calls.append((width, height))

    def protocol(self, name: str, callback: Any) -> None:
        self.protocols[name] = callback

    def destroy(self) -> None:
        self.destroy_calls += 1

    def mainloop(self) -> None:
        self.mainloop_calls += 1

    def clipboard_clear(self) -> None:
        self.clipboard = []

    def clipboard_append(self, text: str) -> None:
        self.clipboard.append(text)

    def update(self) -> None:
        self.update_calls += 1


def _build_window(
    code: str = "service_port_in_use",
    *,
    diagnostics: str = "diag-text",
    clipboard: Any = None,
    open_logs: Any = None,
    recovery_dispatch: Any = None,
) -> tuple[portable_errors._TkinterErrorWindow, FakeTkRoot, FakeTtkModule]:
    root = FakeTkRoot()
    ttk_module = FakeTtkModule()
    clipboard_writer = (lambda _text: None) if clipboard is None else clipboard
    window = portable_errors._TkinterErrorWindow(
        root=root,
        ttk_module=ttk_module,
        presentation=portable_errors.describe_error(code),
        diagnostics=diagnostics,
        clipboard_writer=clipboard_writer,
        open_logs=open_logs,
        recovery_dispatch=recovery_dispatch,
    )
    return window, root, ttk_module


class TestErrorWindow:
    def test_window_always_offers_copy_logs_and_quit(self):
        _window, root, ttk_module = _build_window("service_executable_missing")

        texts = [button.kwargs["text"] for button in ttk_module.buttons]

        assert texts[0] == portable_errors.COPY_DIAGNOSTICS_LABEL
        assert texts[1] == portable_errors.OPEN_LOGS_LABEL
        assert texts[-1] == portable_errors.QUIT_LABEL
        assert root.title_text == portable_errors.ERROR_WINDOW_TITLE

    def test_window_shows_the_title_summary_guidance_and_code(self):
        _window, _root, ttk_module = _build_window("service_port_in_use")
        presentation = portable_errors.describe_error("service_port_in_use")

        rendered = "\n".join(label.kwargs["text"] for label in ttk_module.labels)

        assert presentation.title in rendered
        assert presentation.summary in rendered
        assert presentation.guidance in rendered
        assert presentation.code in rendered

    def test_non_recoverable_error_has_no_recovery_button(self):
        _window, _root, ttk_module = _build_window("launcher_interrupted")

        texts = [button.kwargs["text"] for button in ttk_module.buttons]

        assert portable_errors.RETRY_LABEL not in texts
        assert len(texts) == 3

    def test_copy_button_writes_the_sanitized_diagnostics_without_closing(self):
        copied: list[str] = []
        _window, root, ttk_module = _build_window(diagnostics="sanitized", clipboard=copied.append)

        ttk_module.buttons[0].invoke()

        assert copied == ["sanitized"]
        assert root.destroy_calls == 0

    def test_open_logs_button_uses_the_injected_opener_without_closing(self):
        opened: list[str] = []
        _window, root, ttk_module = _build_window(open_logs=lambda: opened.append("logs"))

        ttk_module.buttons[1].invoke()

        assert opened == ["logs"]
        assert root.destroy_calls == 0

    def test_config_recovery_button_dispatches_the_config_directory_action(self):
        dispatched: list[str] = []
        _window, root, ttk_module = _build_window("config_invalid", recovery_dispatch=dispatched.append)

        recovery = next(
            button for button in ttk_module.buttons if button.kwargs["text"] == portable_errors.OPEN_CONFIG_LABEL
        )
        recovery.invoke()

        assert dispatched == [portable_errors.ACTION_OPEN_CONFIG_DIR]
        assert root.destroy_calls == 0

    def test_retry_recovery_button_closes_the_window_and_reports_retry(self):
        dispatched: list[str] = []
        window, root, ttk_module = _build_window("service_port_in_use", recovery_dispatch=dispatched.append)

        retry = next(button for button in ttk_module.buttons if button.kwargs["text"] == portable_errors.RETRY_LABEL)
        retry.invoke()

        assert root.destroy_calls == 1
        assert dispatched == []
        assert window.selected_action == portable_errors.ACTION_RETRY

    def test_quit_button_closes_the_window_with_the_quit_action(self):
        window, root, ttk_module = _build_window("service_port_in_use")

        ttk_module.buttons[-1].invoke()

        assert root.destroy_calls == 1
        assert window.selected_action == portable_errors.ACTION_QUIT

    def test_window_close_is_wm_delete_and_idempotent(self):
        window, root, _ttk_module = _build_window()

        assert root.protocols["WM_DELETE_WINDOW"] == window.close

        window.close()
        window.close()

        assert root.destroy_calls == 1

    def test_window_run_returns_the_selected_action(self):
        window, root, _ttk_module = _build_window()

        assert window.run() == portable_errors.ACTION_QUIT
        assert root.mainloop_calls == 1

    def test_recovery_labels_cover_every_recovery_action(self):
        for action in portable_errors.RECOVERY_ACTIONS:
            assert action in portable_errors.RECOVERY_LABELS

    def test_missing_tkinter_degrades_to_no_window(self, monkeypatch):
        monkeypatch.setattr(portable_errors, "_import_tkinter", lambda: None)

        window = portable_errors.create_error_window(
            presentation=portable_errors.describe_error("service_port_in_use"),
            diagnostics="diag",
        )

        assert window is None

    def test_real_dialog_is_built_when_tk_is_available(self, monkeypatch):
        root = FakeTkRoot()
        ttk_module = FakeTtkModule()
        monkeypatch.setattr(
            portable_errors,
            "_import_tkinter",
            lambda: (types.SimpleNamespace(Tk=lambda: root), ttk_module),
        )

        window = portable_errors.create_error_window(
            presentation=portable_errors.describe_error("service_port_in_use"),
            diagnostics="diag",
        )

        assert isinstance(window, portable_errors._TkinterErrorWindow)
        assert root.protocols["WM_DELETE_WINDOW"] == window.close
        window.close()

    def test_tk_creation_failure_never_raises(self, monkeypatch):
        def failing_tk() -> Any:
            raise RuntimeError("no display")

        monkeypatch.setattr(
            portable_errors,
            "_import_tkinter",
            lambda: (types.SimpleNamespace(Tk=failing_tk), FakeTtkModule()),
        )

        window = portable_errors.create_error_window(
            presentation=portable_errors.describe_error("service_port_in_use"),
            diagnostics="diag",
        )

        assert window is None


class RecordingSink:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def __call__(self, message: str) -> None:
        self.messages.append(message)


class FakeErrorWindow:
    def __init__(self, *, action: str = portable_errors.ACTION_QUIT, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.action = action
        self.closed = False

    def run(self) -> str:
        return self.action

    def close(self) -> None:
        self.closed = True


def _capturing_factory(action: str, created: list[FakeErrorWindow]) -> Any:
    def factory(**kwargs: Any) -> FakeErrorWindow:
        window = FakeErrorWindow(action=action, **kwargs)
        created.append(window)
        return window

    return factory


class TestFailureReporter:
    def test_record_keeps_the_stable_error_line_format(self):
        sink = RecordingSink()
        reporter = portable_errors.FailureReporter(show_ui=True, report=sink)

        reporter.record("service_port_in_use", "端口被占用", exit_code=4)

        assert sink.messages == ["ERROR [service_port_in_use]: 端口被占用"]
        assert reporter.failure is not None
        assert reporter.failure.code == "service_port_in_use"
        assert reporter.failure.exit_code == 4

    def test_present_is_a_noop_without_ui_or_failure(self):
        created: list[FakeErrorWindow] = []
        factory = _capturing_factory(portable_errors.ACTION_QUIT, created)
        without_failure = portable_errors.FailureReporter(show_ui=True, report=lambda _m: None)
        without_ui = portable_errors.FailureReporter(show_ui=False, report=lambda _m: None)
        without_ui.record("service_port_in_use", "端口被占用")

        assert without_failure.present(window_factory=factory) is None
        assert without_ui.present(window_factory=factory) is None
        assert created == []

    def test_present_shows_a_sanitized_window_after_a_failure(self, tmp_path, monkeypatch):
        created: list[FakeErrorWindow] = []
        monkeypatch.setattr(portable_errors, "open_directory", lambda _path: True)
        reporter = portable_errors.FailureReporter(
            show_ui=True,
            report=lambda _m: None,
            app_version="1.0.0",
            launcher_executable=tmp_path / "PDF Reader.exe",
        )
        reporter.record("service_start_timeout", "等待本地服务就绪超时")

        action = reporter.present(
            window_factory=_capturing_factory(portable_errors.ACTION_RETRY, created),
            platform_label="TestOS-1.0",
            clock=_fixed_clock,
        )

        assert action == portable_errors.ACTION_RETRY
        assert len(created) == 1
        window = created[0]
        assert window.kwargs["presentation"].code == "service_start_timeout"
        assert "data/logs/launcher.log" in window.kwargs["diagnostics"]
        assert window.closed is True

    def test_present_never_shows_raw_exception_detail_in_the_window(self, tmp_path):
        created: list[FakeErrorWindow] = []
        reporter = portable_errors.FailureReporter(
            show_ui=True,
            report=lambda _m: None,
            launcher_executable=tmp_path / "PDF Reader.exe",
        )
        reporter.record(
            "service_start_timeout",
            "api_key=sk-exampleexampleexample123456 prompt=用户机密正文",
        )

        reporter.present(window_factory=_capturing_factory(portable_errors.ACTION_QUIT, created))

        diagnostics = created[0].kwargs["diagnostics"]
        assert "sk-exampleexampleexample123456" not in diagnostics
        assert "用户机密正文" not in diagnostics

    def test_present_degrades_safely_when_the_window_is_unavailable(self, tmp_path):
        sink = RecordingSink()
        reporter = portable_errors.FailureReporter(show_ui=True, report=sink, launcher_executable=tmp_path / "x.exe")
        reporter.record("launcher_ui_unavailable", "无法创建控制窗口")

        action = reporter.present(window_factory=lambda **_kwargs: None, platform_label="TestOS")

        assert action is None
        assert any("launcher_error_window_unavailable" in message for message in sink.messages)

    def test_present_survives_a_factory_that_raises(self, tmp_path):
        def exploding_factory(**_kwargs: Any) -> Any:
            raise RuntimeError("窗口构造失败")

        reporter = portable_errors.FailureReporter(
            show_ui=True, report=lambda _m: None, launcher_executable=tmp_path / "x.exe"
        )
        reporter.record("service_port_in_use", "端口被占用")

        assert reporter.present(window_factory=exploding_factory) is None

    def test_clear_drops_the_recorded_failure(self):
        reporter = portable_errors.FailureReporter(show_ui=True, report=lambda _m: None)
        reporter.record("service_port_in_use", "端口被占用")

        reporter.clear()

        assert reporter.failure is None

    def test_default_dispatch_opens_only_known_directories(self, tmp_path, monkeypatch):
        opened: list[Path] = []
        monkeypatch.setattr(portable_errors, "open_directory", lambda path: opened.append(path) or True)
        reporter = portable_errors.FailureReporter(
            show_ui=True, report=lambda _m: None, launcher_executable=tmp_path / "PDF Reader.exe"
        )

        dispatch = reporter.default_recovery_dispatch()

        assert dispatch(portable_errors.ACTION_OPEN_CONFIG_DIR) is True
        assert opened == [tmp_path / "data" / "config"]
        assert dispatch(portable_errors.ACTION_OPEN_LOGS) is True
        assert opened[-1] == tmp_path / "data" / "logs"
        assert dispatch(portable_errors.ACTION_OPEN_PROGRAM_DIR) is True
        assert opened[-1] == tmp_path
        assert dispatch("unknown_action") is False

    def test_default_open_logs_creates_the_directory_then_opens_it(self, tmp_path, monkeypatch):
        opened: list[Path] = []
        monkeypatch.setattr(portable_errors, "open_directory", lambda path: opened.append(path) or True)
        reporter = portable_errors.FailureReporter(
            show_ui=True, report=lambda _m: None, launcher_executable=tmp_path / "PDF Reader.exe"
        )

        assert reporter.default_open_logs()() is True
        assert (tmp_path / "data" / "logs").is_dir()


def test_format_failure_message_is_the_single_source_of_the_stable_line():
    assert portable_errors.format_failure_message("x_code", "细节") == "ERROR [x_code]: 细节"


@pytest.mark.parametrize("code", sorted(portable_errors.ERROR_CATALOG))
def test_every_catalogued_code_has_no_raw_placeholder(code):
    assert "{code}" not in portable_errors.ERROR_CATALOG[code].summary


def test_empty_code_falls_back_to_the_generic_presentation():
    presentation = portable_errors.describe_error("")

    assert presentation.code == "unknown"
    assert presentation.summary


class DestroyFailingRoot(FakeTkRoot):
    """destroy 失败的根窗口：验证关闭失败不会向上抛出。"""

    def destroy(self) -> None:
        self.destroy_calls += 1
        raise RuntimeError("无法销毁窗口")


class ExplodingTtk:
    """控件创建即失败的 ttk 替身：验证窗口初始化失败会释放根窗口。"""

    def Frame(self, *_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("控件创建失败")


class TestErrorWindowRobustness:
    def test_default_clipboard_writer_copies_into_the_tk_root(self):
        root = FakeTkRoot()
        ttk_module = FakeTtkModule()
        portable_errors._TkinterErrorWindow(
            root=root,
            ttk_module=ttk_module,
            presentation=portable_errors.describe_error("service_port_in_use"),
            diagnostics="safe-diagnostics",
        )

        ttk_module.buttons[0].invoke()

        assert root.clipboard == ["safe-diagnostics"]
        # Windows：append 后必须让 Tk 处理一次事件循环，否则窗口关闭后剪贴板内容会丢失。
        assert root.update_calls == 1

    def test_default_clipboard_writer_falls_back_to_update_idletasks(self):
        updated: list[str] = []

        class IdleOnlyRoot:
            def __init__(self) -> None:
                self.clipboard: list[str] = []

            def clipboard_clear(self) -> None:
                self.clipboard = []

            def clipboard_append(self, text: str) -> None:
                self.clipboard.append(text)

            def update_idletasks(self) -> None:
                updated.append("idle")

        root = IdleOnlyRoot()
        writer = portable_errors._tk_clipboard_writer(root)

        writer("safe")

        assert root.clipboard == ["safe"]
        assert updated == ["idle"]

    def test_copy_failure_is_swallowed_and_keeps_the_window_open(self):
        def exploding(_text: str) -> None:
            raise RuntimeError("剪贴板不可用")

        _window, root, ttk_module = _build_window(clipboard=exploding)

        ttk_module.buttons[0].invoke()

        assert root.destroy_calls == 0

    def test_open_logs_failure_is_swallowed(self):
        def exploding() -> bool:
            raise OSError("没有文件管理器")

        _window, root, ttk_module = _build_window(open_logs=exploding)

        ttk_module.buttons[1].invoke()

        assert root.destroy_calls == 0

    def test_recovery_dispatch_failure_is_swallowed(self):
        def exploding(_action: str) -> bool:
            raise OSError("没有文件管理器")

        _window, root, ttk_module = _build_window("config_invalid", recovery_dispatch=exploding)

        recovery = next(
            button for button in ttk_module.buttons if button.kwargs["text"] == portable_errors.OPEN_CONFIG_LABEL
        )
        recovery.invoke()

        assert root.destroy_calls == 0

    def test_close_failure_never_raises(self):
        root = DestroyFailingRoot()
        window = portable_errors._TkinterErrorWindow(
            root=root,
            ttk_module=FakeTtkModule(),
            presentation=portable_errors.describe_error("service_port_in_use"),
            diagnostics="diag",
        )

        window.close()

        assert root.destroy_calls == 1

    def test_dialog_init_failure_closes_the_root_and_degrades_to_none(self, monkeypatch):
        root = FakeTkRoot()
        monkeypatch.setattr(
            portable_errors,
            "_import_tkinter",
            lambda: (types.SimpleNamespace(Tk=lambda: root), ExplodingTtk()),
        )

        window = portable_errors.create_error_window(
            presentation=portable_errors.describe_error("service_port_in_use"),
            diagnostics="diag",
        )

        assert window is None
        assert root.destroy_calls == 1


def test_import_tkinter_is_total():
    modules = portable_errors._import_tkinter()

    assert modules is None or (isinstance(modules, tuple) and len(modules) == 2)


class TestOpenDirectory:
    def test_startfile_success_is_used_first(self, tmp_path, monkeypatch):
        opened: list[str] = []
        monkeypatch.setattr(portable_errors.os, "startfile", lambda path: opened.append(path), raising=False)

        assert portable_errors.open_directory(tmp_path) is True
        assert opened == [str(tmp_path)]

    def test_startfile_failure_falls_back_to_the_browser(self, tmp_path, monkeypatch):
        def failing(_path: str) -> None:
            raise OSError("没有资源管理器")

        monkeypatch.setattr(portable_errors.os, "startfile", failing, raising=False)
        monkeypatch.setattr(portable_errors.webbrowser, "open", lambda _url: True)

        assert portable_errors.open_directory(tmp_path) is True

    def test_browser_failure_returns_false(self, tmp_path, monkeypatch):
        def failing(_url: str) -> bool:
            raise RuntimeError("没有浏览器")

        monkeypatch.delattr(portable_errors.os, "startfile", raising=False)
        monkeypatch.setattr(portable_errors.webbrowser, "open", failing)

        assert portable_errors.open_directory(tmp_path) is False


def test_present_survives_a_window_whose_run_raises(tmp_path):
    created: list[ExplodingRunWindow] = []

    def factory(**kwargs: Any) -> ExplodingRunWindow:
        window = ExplodingRunWindow(**kwargs)
        created.append(window)
        return window

    reporter = portable_errors.FailureReporter(
        show_ui=True, report=lambda _m: None, launcher_executable=tmp_path / "x.exe"
    )
    reporter.record("service_port_in_use", "端口被占用")

    assert reporter.present(window_factory=factory) is None
    assert created[0].closed is True


class ExplodingRunWindow:
    def __init__(self, **_kwargs: Any) -> None:
        self.closed = False

    def run(self) -> str:
        raise RuntimeError("窗口循环失败")

    def close(self) -> None:
        self.closed = True
