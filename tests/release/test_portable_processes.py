from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from pdf_reader import paths

REPO_ROOT = Path(__file__).resolve().parents[2]


def _layout(tmp_path: Path) -> paths.RuntimeLayout:
    root = tmp_path / "PDF Reader 中文 portable"
    (root / "app").mkdir(parents=True)
    launcher = root / "PDF Reader.exe"
    launcher.write_bytes(b"")
    layout = paths.RuntimeLayout.portable_from_executable(launcher)
    paths.prepare_runtime_layout(layout)
    return layout


def test_service_environment_is_child_only_and_scrubs_python_overrides(monkeypatch, tmp_path):
    from pdf_reader.portable_runtime import build_service_environment

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

    child = build_service_environment(layout, base)

    assert os.environ == parent_before
    assert "PYTHONHOME" not in child
    assert "PYTHONPATH" not in child
    assert "PYTHONUSERBASE" not in child
    assert child["PYTHONNOUSERSITE"] == "1"
    assert child["PYTHONDONTWRITEBYTECODE"] == "1"
    assert child["HOME"] == str(layout.data_root / "home")
    assert child["USERPROFILE"] == str(layout.data_root / "home")
    assert child["TEMP"] == str(layout.temp_dir)
    assert child["TMP"] == str(layout.temp_dir)
    assert child["TMPDIR"] == str(layout.temp_dir)
    assert child["XDG_CACHE_HOME"] == str(layout.data_root / "home" / ".cache")
    assert child["HF_HOME"] == str(layout.data_root / "upstream-cache" / "huggingface")
    assert child["MODELSCOPE_CACHE"] == str(layout.data_root / "upstream-cache" / "modelscope")
    assert child["TORCH_HOME"] == str(layout.data_root / "upstream-cache" / "torch")
    assert child["PDF_READER_PORTABLE_SERVICE"] == "1"


def test_service_bootstrap_precedes_pdf_reader_and_upstream_imports(tmp_path):
    from pdf_reader.portable_runtime import build_service_environment

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
    env = build_service_environment(layout)
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
    assert payload["temp"] == str(layout.temp_dir)
    assert payload["data_root"] == str(layout.data_root)


def test_upstream_home_and_temp_are_bound_before_first_import(tmp_path):
    from pdf_reader.portable_runtime import build_service_environment

    layout = _layout(tmp_path)
    assert layout.portable_root is not None
    launcher = layout.portable_root / "PDF Reader.exe"
    probe = r"""
import json
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
        env=build_service_environment(layout),
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    home = layout.data_root / "home"
    assert payload["babeldoc_cache"] == str(home / ".cache" / "babeldoc")
    assert payload["pdf2zh_config"] == str(home / ".config" / "pdf2zh")
    assert payload["temp"] == str(layout.temp_dir)


def test_service_rejects_direct_start_without_controlled_environment(tmp_path):
    from pdf_reader import portable_service

    layout = _layout(tmp_path)
    assert layout.portable_root is not None
    launcher = layout.portable_root / "PDF Reader.exe"

    with pytest.raises(portable_service.PortableServiceError) as exc_info:
        portable_service.bootstrap_portable_service(launcher, environment={})

    assert exc_info.value.code == "portable_service_environment_missing"


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

    monkeypatch.setattr(portable_launcher.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(portable_launcher, "wait_until_ready", lambda *_args, **_kwargs: "http://127.0.0.1:5000/")
    monkeypatch.setattr(portable_launcher.webbrowser, "open", fake_browser)

    result = portable_launcher.run_portable_launcher(launcher, startup_timeout=0.01)

    assert result == 0
    assert captured["command"] == [str(service_exe), "--launcher-executable", str(launcher)]
    assert captured["child_env"]["HOME"] == str(layout.data_root / "home")
    assert captured["browser_env"] == parent_before
    assert captured["browser_url"] == "http://127.0.0.1:5000/"
    assert os.environ == parent_before


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
