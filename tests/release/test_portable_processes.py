from __future__ import annotations

import json
import os
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from pdf_reader import paths

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_portable_write_contract_dependency_versions_are_pinned():
    assert {
        "pdf2zh-next": version("pdf2zh-next"),
        "babeldoc": version("babeldoc"),
        "huggingface-hub": version("huggingface-hub"),
        "tiktoken": version("tiktoken"),
    } == {
        "pdf2zh-next": "2.9.0",
        "babeldoc": "0.6.2",
        "huggingface-hub": "1.29.0",
        "tiktoken": "0.14.0",
    }


def _layout(tmp_path: Path) -> paths.RuntimeLayout:
    root = tmp_path / "PDF Reader 中文 portable"
    (root / "app").mkdir(parents=True)
    launcher = root / "PDF Reader.exe"
    launcher.write_bytes(b"")
    layout = paths.RuntimeLayout.portable_from_executable(launcher)
    paths.prepare_runtime_layout(layout)
    return layout


def _service_environment(layout: paths.RuntimeLayout, base: dict[str, str] | None = None) -> dict[str, str]:
    """Build a bootstrap-only env with a valid per-launch liveness descriptor."""

    from pdf_reader.portable_runtime import POSIX_LIVENESS_DESCRIPTOR, build_service_environment

    liveness_path = layout.runtime_dir / "launcher-liveness-bootstrap.lock"
    return build_service_environment(
        layout,
        base,
        launcher_liveness=f"{POSIX_LIVENESS_DESCRIPTOR}{liveness_path}",
    )


def test_service_environment_is_child_only_and_scrubs_python_overrides(monkeypatch, tmp_path):
    layout = _layout(tmp_path)
    parent_before = os.environ.copy()
    base = parent_before | {
        "HOME": r"C:\real-home",
        "USERPROFILE": r"C:\real-profile",
        "TEMP": r"C:\real-temp",
        "TMP": r"C:\real-temp",
        "PYTHONHOME": r"C:\host-python",
        "PYTHONPATH": r"C:\host-packages",
        "PYTHONUSERBASE": r"C:\host-user-site",
    }

    child = _service_environment(layout, base)

    assert os.environ == parent_before
    assert "PYTHONHOME" not in child
    assert "PYTHONPATH" not in child
    assert "PYTHONUSERBASE" not in child
    assert child["PYTHONNOUSERSITE"] == "1"
    assert child["PYTHONSAFEPATH"] == "1"
    assert child["PYTHONDONTWRITEBYTECODE"] == "1"
    assert child["HOME"] == str(layout.data_root / "home")
    assert child["USERPROFILE"] == str(layout.data_root / "home")
    service_temp = Path(child["TEMP"])
    assert service_temp.parent == layout.temp_dir
    assert service_temp.name.startswith("pdf-reader-service-")
    assert (service_temp / ".pdf-reader-service-temp").is_file()
    assert child["TMP"] == str(service_temp)
    assert child["TMPDIR"] == str(service_temp)
    assert child["XDG_CACHE_HOME"] == str(layout.data_root / "home" / ".cache")
    assert child["HF_HOME"] == str(layout.data_root / "upstream-cache" / "huggingface")
    assert child["HF_HUB_CACHE"] == str(layout.data_root / "upstream-cache" / "huggingface" / "hub")
    assert child["HF_ASSETS_CACHE"] == str(layout.data_root / "upstream-cache" / "huggingface" / "assets")
    assert child["TIKTOKEN_CACHE_DIR"] == str(layout.data_root / "home" / ".cache" / "babeldoc" / "tiktoken")
    assert "MODELSCOPE_CACHE" not in child
    assert "TORCH_HOME" not in child
    assert "TRANSFORMERS_CACHE" not in child
    assert child["PDF_READER_PORTABLE_SERVICE"] == "1"
    assert child["PDF_READER_LAUNCHER_LIVENESS"].startswith("posix-flock:")
    assert "PDF_READER_LAUNCHER_PID" not in child


def test_service_bootstrap_precedes_pdf_reader_and_upstream_imports(tmp_path):
    layout = _layout(tmp_path)
    assert layout.portable_root is not None
    launcher = layout.portable_root / "PDF Reader.exe"
    probe = r"""
import json
import os
import sys
from pathlib import Path

from pdf_reader import portable_service

before = sorted(
    name
    for name in sys.modules
    if name == "pdf_reader.app" or name.startswith(("pdf2zh_next", "babeldoc"))
)
layout = portable_service.bootstrap_portable_service(Path(sys.argv[1]))
after_bootstrap = sorted(
    name
    for name in sys.modules
    if name == "pdf_reader.app" or name.startswith(("pdf2zh_next", "babeldoc"))
)
snapshot = {
    "before": before,
    "after_bootstrap": after_bootstrap,
    "home": os.environ["HOME"],
    "temp": os.environ["TEMP"],
    "data_root": str(layout.data_root),
}
print(json.dumps(snapshot))
"""
    env = _service_environment(layout)
    result = subprocess.run(
        [sys.executable, "-c", probe, str(launcher)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["before"] == []
    assert payload["after_bootstrap"] == []
    assert payload["home"] == str(layout.data_root / "home")
    assert Path(payload["temp"]).parent == layout.temp_dir
    assert payload["data_root"] == str(layout.data_root)


def test_upstream_home_and_temp_are_bound_before_first_import(tmp_path):
    layout = _layout(tmp_path)
    assert layout.portable_root is not None
    launcher = layout.portable_root / "PDF Reader.exe"
    probe = r"""
import json
import os
import sys
import tempfile
from pathlib import Path

from pdf_reader import portable_service

layout = portable_service.bootstrap_portable_service(Path(sys.argv[1]))
portable_service._load_app_main()
from babeldoc.const import CACHE_FOLDER
from pdf2zh_next.const import DEFAULT_CONFIG_DIR

print(json.dumps({
    "babeldoc_cache": str(CACHE_FOLDER),
    "pdf2zh_config": str(DEFAULT_CONFIG_DIR),
    "temp": tempfile.gettempdir(),
    "data_root": str(layout.data_root),
}))
"""
    result = subprocess.run(
        [sys.executable, "-c", probe, str(launcher)],
        cwd=tmp_path,
        env=_service_environment(layout),
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    home = layout.data_root / "home"
    assert payload["babeldoc_cache"] == str(home / ".cache" / "babeldoc")
    assert payload["pdf2zh_config"] == str(home / ".config" / "pdf2zh")
    service_temp = Path(payload["temp"])
    assert service_temp.parent == layout.temp_dir
    assert service_temp.name.startswith("pdf-reader-service-")


def test_pinned_upstream_write_paths_stay_inside_portable_data(tmp_path):
    layout = _layout(tmp_path)
    assert layout.portable_root is not None
    launcher = layout.portable_root / "PDF Reader.exe"
    probe = r"""
import asyncio
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

from pdf_reader import portable_service

layout = portable_service.bootstrap_portable_service(Path(sys.argv[1]))
from babeldoc.assets.assets import download_file, get_cache_file_path
from babeldoc.const import CACHE_FOLDER, TIKTOKEN_CACHE_FOLDER
from pdf2zh_next.const import DEFAULT_CONFIG_DIR
from pdf2zh_next.translator.cache import db

handle, temporary_name = tempfile.mkstemp(prefix="upstream-contract-")
os.close(handle)
Path(temporary_name).unlink()

class FakeResponse:
    def __init__(self, content):
        self.content = content
    def raise_for_status(self):
        return None

class FakeClient:
    def __init__(self, content):
        self.content = content
    async def get(self, *_args, **_kwargs):
        return FakeResponse(self.content)

class CancelClient:
    async def get(self, *_args, **_kwargs):
        raise asyncio.CancelledError()

download_target = get_cache_file_path("contract-download.bin", "models")
download_bytes = b"portable-model-fixture"
asyncio.run(download_file(
    FakeClient(download_bytes),
    "https://invalid.test",
    download_target,
    hashlib.sha3_256(download_bytes).hexdigest(),
))
download_recovered = download_target.read_bytes() == download_bytes
download_target.unlink()

failed_target = get_cache_file_path("contract-failed.bin", "fonts")
try:
    asyncio.run(download_file(FakeClient(b"corrupt"), "https://invalid.test", failed_target, "0" * 64))
except Exception:
    pass
failure_clean = not failed_target.exists()

cancelled_target = get_cache_file_path("contract-cancelled.bin", "fonts")
try:
    asyncio.run(download_file(CancelClient(), "https://invalid.test", cancelled_target, "0" * 64))
except asyncio.CancelledError:
    pass
cancel_clean = not cancelled_target.exists()

print(json.dumps({
    "babeldoc_cache": str(CACHE_FOLDER),
    "font": str(get_cache_file_path("contract-font.ttf", "fonts")),
    "model": str(get_cache_file_path("contract-model.onnx", "models")),
    "cmap": str(get_cache_file_path("contract-cmap.json", "cmap")),
    "tiktoken": str(TIKTOKEN_CACHE_FOLDER),
    "pdf2zh_config": str(DEFAULT_CONFIG_DIR),
    "pdf2zh_cache_db": str(db.database),
    "tempfile": temporary_name,
    "download_recovered": download_recovered,
    "failure_clean": failure_clean,
    "cancel_clean": cancel_clean,
    "data_root": str(layout.data_root),
}))
"""
    result = subprocess.run(
        [sys.executable, "-c", probe, str(launcher)],
        cwd=tmp_path,
        env=_service_environment(layout),
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    data_root = layout.data_root.resolve()
    expected = {
        "babeldoc_cache": data_root / "home" / ".cache" / "babeldoc",
        "font": data_root / "home" / ".cache" / "babeldoc" / "fonts" / "contract-font.ttf",
        "model": data_root / "home" / ".cache" / "babeldoc" / "models" / "contract-model.onnx",
        "cmap": data_root / "home" / ".cache" / "babeldoc" / "cmap" / "contract-cmap.json",
        "tiktoken": data_root / "home" / ".cache" / "babeldoc" / "tiktoken",
        "pdf2zh_config": data_root / "home" / ".config" / "pdf2zh",
        "pdf2zh_cache_db": data_root / "home" / ".cache" / "pdf2zh_next" / "cache.v1.db",
    }
    for key, expected_path in expected.items():
        assert Path(payload[key]).resolve() == expected_path
    assert Path(payload["tempfile"]).resolve().parent.parent == layout.temp_dir
    assert payload["download_recovered"] is True
    assert payload["failure_clean"] is True
    assert payload["cancel_clean"] is True


def test_service_temp_recovery_only_removes_marked_dead_sessions(monkeypatch, tmp_path):
    from pdf_reader import cache_ops
    from pdf_reader.portable_runtime import (
        SERVICE_TEMP_MARKER_NAME,
        recover_orphan_service_temp_directories,
    )

    layout = _layout(tmp_path)
    dead = layout.temp_dir / "pdf-reader-service-dead"
    unknown = layout.temp_dir / "pdf-reader-service-unknown"
    unrelated = layout.temp_dir / "other"
    for directory in (dead, unknown, unrelated):
        directory.mkdir()
        (directory / "payload.tmp").write_text("x", encoding="utf-8")
    (dead / SERVICE_TEMP_MARKER_NAME).write_text(
        json.dumps({"kind": "pdf-reader-service-temp", "pid": 12345}),
        encoding="utf-8",
    )
    monkeypatch.setattr(cache_ops, "is_process_alive", lambda _pid: False)

    removed = recover_orphan_service_temp_directories(layout)

    assert removed == (dead,)
    assert not dead.exists()
    assert unknown.is_dir()
    assert unrelated.is_dir()


def test_service_rejects_direct_start_without_controlled_environment(tmp_path):
    from pdf_reader import portable_service

    layout = _layout(tmp_path)
    assert layout.portable_root is not None
    launcher = layout.portable_root / "PDF Reader.exe"

    with pytest.raises(portable_service.PortableServiceError) as exc_info:
        portable_service.bootstrap_portable_service(launcher, environment={})

    assert exc_info.value.code == "portable_service_environment_missing"


def test_launcher_liveness_descriptor_is_required_and_must_stay_in_data(tmp_path):
    from pdf_reader.portable_runtime import (
        LAUNCHER_LIVENESS_ENV,
        POSIX_LIVENESS_DESCRIPTOR,
        WINDOWS_LIVENESS_DESCRIPTOR,
        WINDOWS_LIVENESS_PREFIX,
        PortableEnvironmentError,
        build_service_environment,
        validate_service_environment,
    )

    layout = _layout(tmp_path)
    outside = tmp_path / "outside" / "launcher-liveness-escape.lock"
    # 服务只有在存在“本次启动专属、内核可判定”的存活归属时才允许启动；
    # PID 形状或 data 之外的标识都不是可接受的替代品。
    cases = {
        "缺失": "",
        "未知格式": "launcher-pid:4321",
        "data 之外的路径": f"{POSIX_LIVENESS_DESCRIPTOR}{outside}",
        "非存活文件名": f"{POSIX_LIVENESS_DESCRIPTOR}{layout.runtime_dir / 'instance.lock'}",
        "Windows 名称不是随机十六进制": f"{WINDOWS_LIVENESS_DESCRIPTOR}{WINDOWS_LIVENESS_PREFIX}pid-4321",
    }
    for label, descriptor in cases.items():
        with pytest.raises(PortableEnvironmentError) as exc_info:
            build_service_environment(layout, {}, launcher_liveness=descriptor)
        assert exc_info.value.code == "portable_service_launcher_liveness_invalid", label

    valid = _service_environment(layout)
    validate_service_environment(layout, valid)
    for tampered in ("", f"{POSIX_LIVENESS_DESCRIPTOR}{outside}"):
        rejected = valid | {LAUNCHER_LIVENESS_ENV: tampered}
        with pytest.raises(PortableEnvironmentError) as exc_info:
            validate_service_environment(layout, rejected)
        assert exc_info.value.code == "portable_service_environment_missing"


def test_frozen_service_rejects_host_interpreter_user_site_and_search_paths(tmp_path):
    from pdf_reader.portable_runtime import PortableEnvironmentError, validate_private_frozen_runtime

    layout = _layout(tmp_path)
    private_service = layout.resource_root / "PDF Reader Service.exe"
    private_paths = (str(layout.resource_root / "_internal"),)

    validate_private_frozen_runtime(
        layout,
        frozen=True,
        executable=private_service,
        no_user_site=True,
        safe_path=True,
        module_search_paths=private_paths,
    )

    cases = (
        ({"executable": tmp_path / "host" / "python.exe"}, "private_runtime_executable_invalid"),
        ({"no_user_site": False}, "private_runtime_user_site_enabled"),
        ({"safe_path": False}, "private_runtime_safe_path_disabled"),
        ({"module_search_paths": (str(tmp_path / "host-site-packages"),)}, "private_runtime_search_path_invalid"),
        ({"module_search_paths": ("",)}, "private_runtime_search_path_invalid"),
    )
    for overrides, expected_code in cases:
        arguments = {
            "frozen": True,
            "executable": private_service,
            "no_user_site": True,
            "safe_path": True,
            "module_search_paths": private_paths,
        }
        arguments.update(overrides)
        with pytest.raises(PortableEnvironmentError) as exc_info:
            validate_private_frozen_runtime(layout, **arguments)
        assert exc_info.value.code == expected_code


def test_launcher_uses_private_service_executable_and_real_browser_environment(monkeypatch, tmp_path):
    from pdf_reader import portable_launcher

    layout = _layout(tmp_path)
    assert layout.portable_root is not None
    launcher = layout.portable_root / "PDF Reader.exe"
    service_exe = layout.resource_root / "PDF Reader Service.exe"
    service_exe.write_bytes(b"")
    parent_before = os.environ.copy()
    process = MagicMock()
    process.poll.side_effect = [None, None]
    process.wait.return_value = 0
    captured: dict[str, object] = {}

    def fake_popen(command: list[str], **kwargs: Any) -> MagicMock:
        captured["command"] = command
        captured["child_env"] = cast(dict[str, str], kwargs["env"]).copy()
        return process

    def fake_browser(url: str) -> bool:
        captured["browser_url"] = url
        captured["browser_env"] = os.environ.copy()
        return True

    class QuittingWindow:
        def __init__(self, *, dispatch: Any, should_stop: Any) -> None:
            self._dispatch = dispatch

        def run(self) -> None:
            self._dispatch("quit")

        def close(self) -> None:
            pass

    monkeypatch.setattr(portable_launcher.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(portable_launcher, "wait_until_ready", lambda *_args, **_kwargs: "http://127.0.0.1:5000/")
    monkeypatch.setattr(portable_launcher.webbrowser, "open", fake_browser)

    result = portable_launcher.run_portable_launcher(
        launcher,
        startup_timeout=0.01,
        window_factory=QuittingWindow,
    )

    assert result == 0
    assert captured["command"] == [str(service_exe), "--launcher-executable", str(launcher)]
    assert captured["child_env"]["HOME"] == str(layout.data_root / "home")
    assert captured["browser_env"] == parent_before
    assert captured["browser_url"] == "http://127.0.0.1:5000/"
    assert os.environ == parent_before
    assert not Path(cast(dict[str, str], captured["child_env"])["TEMP"]).exists()


def test_launcher_startup_failure_terminates_service_and_removes_readiness_file(monkeypatch, tmp_path):
    from pdf_reader import portable_launcher

    layout = _layout(tmp_path)
    assert layout.portable_root is not None
    launcher = layout.portable_root / "PDF Reader.exe"
    (layout.resource_root / "PDF Reader Service.exe").write_bytes(b"")
    process = MagicMock()
    process.poll.return_value = None
    process.wait.return_value = 0
    captured: dict[str, Path] = {}

    def fake_popen(_command: list[str], **kwargs: Any) -> MagicMock:
        child_env = cast(dict[str, str], kwargs["env"])
        ready_file = Path(child_env["PDF_READER_READY_FILE"])
        ready_file.write_text("partial", encoding="utf-8")
        captured["ready_file"] = ready_file
        captured["service_temp"] = Path(child_env["TEMP"])
        return process

    monkeypatch.setattr(portable_launcher.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        portable_launcher,
        "wait_until_ready",
        MagicMock(side_effect=portable_launcher.PortableLaunchError("not ready", code="service_start_timeout")),
    )

    result = portable_launcher.run_portable_launcher(launcher, startup_timeout=0.01)

    assert result == portable_launcher.EXIT_SERVICE_START_FAILED
    process.terminate.assert_called_once_with()
    process.wait.assert_called()
    assert not captured["ready_file"].exists()
    assert captured["ready_file"].parent == layout.temp_dir
    assert not captured["service_temp"].exists()


def test_pinned_upstream_does_not_call_windows_font_installation_apis():
    import babeldoc

    babeldoc_root = Path(next(iter(babeldoc.__path__)))
    roots = (REPO_ROOT / "src" / "pdf_reader", babeldoc_root)
    forbidden = (
        "AddFontResource",
        "RemoveFontResource",
        r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts",
    )
    violations: list[str] = []
    for root in roots:
        for source in root.rglob("*.py"):
            text = source.read_text(encoding="utf-8", errors="replace")
            if any(token in text for token in forbidden):
                violations.append(str(source))

    assert violations == []


def test_readiness_descriptor_must_stay_in_data_root(tmp_path):
    from pdf_reader.portable_runtime import write_readiness_descriptor

    layout = _layout(tmp_path)
    outside = tmp_path / "outside-ready.json"

    with pytest.raises(paths.PathStrategyError) as exc_info:
        write_readiness_descriptor(
            layout,
            outside,
            host="127.0.0.1",
            port=5000,
            health_token="x" * 32,
        )

    assert exc_info.value.code == "path_outside_data_root"
    assert not outside.exists()


def test_readiness_endpoint_rejects_non_loopback_and_short_token():
    from pdf_reader.portable_launcher import _readiness_endpoint

    with pytest.raises(ValueError, match="loopback"):
        _readiness_endpoint({"schema": 1, "host": "0.0.0.0", "port": 5000, "health_token": "x" * 32})
    with pytest.raises(ValueError, match="token"):
        _readiness_endpoint({"schema": 1, "host": "127.0.0.1", "port": 5000, "health_token": "short"})


def test_portable_health_endpoint_requires_process_private_header(monkeypatch):
    from pdf_reader import config, logging_config
    from pdf_reader.app import create_app

    token = "health-token-" + "x" * 32
    monkeypatch.setenv("PDF_READER_PORTABLE_SERVICE", "1")
    monkeypatch.setenv("PDF_READER_HEALTH_TOKEN", token)
    app = create_app(config.build_app_settings())
    app.config["TESTING"] = True
    try:
        with app.test_client() as client:
            assert client.get("/api/health").status_code == 404
            assert (
                client.get(
                    "/api/health",
                    headers={"X-PDF-Reader-Health-Token": "wrong"},
                ).status_code
                == 404
            )
            response = client.get(
                "/api/health",
                headers={"X-PDF-Reader-Health-Token": token},
            )
            assert response.status_code == 200
            assert response.get_json() == {"status": "ok"}
    finally:
        app.config["app_state"].close()
        logging_config.reset_logging()
