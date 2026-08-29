"""P1-05 regression tests for start.bat process-kill safety.

The real ``start.bat`` is copied into a pytest temp directory and executed
under ``cmd.exe`` on Windows with fake ``netstat``/``taskkill``/``python``
commands and a fake venv placed on PATH.  No real server is started, no real
port is bound, and no real process is killed.  These tests pin:

1. start.bat source contains no process-termination commands.
2. When port 5000 appears occupied, start.bat reports the listener and exits
   non-zero without invoking python/app or taskkill.
3. When port 5000 is free, start.bat activates the venv and invokes
   ``python -m pdf_reader``.
4. When the venv is missing, start.bat explains how to create it and exits
   non-zero.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
START_BAT = REPO_ROOT / "start.bat"

pytestmark = pytest.mark.skipif(os.name != "nt", reason="start.bat is Windows-only")

KILL_TOKENS = ("taskkill", "tskill", "stop-process", "wmic", "kill")


def _write_script(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\r\n".join(["@echo off", *lines]) + "\r\n", encoding="ascii")


def _install_fake_netstat(fake_bin: Path, *, occupied: bool) -> None:
    if occupied:
        line = "echo TCP    127.0.0.1:5000    0.0.0.0:0    LISTENING    4242"
    else:
        line = "echo TCP    127.0.0.1:4999    0.0.0.0:0    LISTENING    4242"
    _write_script(fake_bin / "netstat.cmd", [line])


def _install_app(tmp_path: Path) -> dict[str, str]:
    root = tmp_path / "app"
    root.mkdir()
    shutil.copy2(START_BAT, root / "start.bat")

    fake_bin = root / "fake-bin"
    fake_bin.mkdir()
    logs = root / "logs"
    logs.mkdir()

    scripts_dir = root / "venv" / "Scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "python.exe").write_bytes(b"")  # existence probe only
    _write_script(
        scripts_dir / "activate.bat",
        [
            'echo activated >> "%ACTIVATE_LOG%"',
            'set "PATH=%FAKE_BIN%;%PATH%"',
        ],
    )
    _write_script(fake_bin / "python.cmd", ['echo %* >> "%PYTHON_LOG%"', "exit /b 0"])
    _write_script(fake_bin / "taskkill.cmd", ['echo %* >> "%TASKKILL_LOG%"', "exit /b 0"])

    env = os.environ.copy()
    env["PATH"] = str(fake_bin) + os.pathsep + env["PATH"]
    env["FAKE_BIN"] = str(fake_bin)
    env["ACTIVATE_LOG"] = str(logs / "activate.log")
    env["PYTHON_LOG"] = str(logs / "python.log")
    env["TASKKILL_LOG"] = str(logs / "taskkill.log")
    return {"root": root, "fake_bin": fake_bin, "logs": logs, "env": env}


def _run_start_bat(root: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["cmd", "/c", "start.bat"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        input="\n",
        timeout=60,
    )


def test_start_bat_source_contains_no_process_kill_commands() -> None:
    text = START_BAT.read_text(encoding="utf-8", errors="replace").lower()
    for token in KILL_TOKENS:
        assert token not in text, f"start.bat must not contain kill command token: {token}"


def test_start_bat_refuses_occupied_port_without_python_or_kill(tmp_path: Path) -> None:
    ctx = _install_app(tmp_path)
    _install_fake_netstat(ctx["fake_bin"], occupied=True)

    result = _run_start_bat(ctx["root"], ctx["env"])

    assert result.returncode != 0
    assert "5000" in result.stdout
    assert "4242" in result.stdout
    assert not (ctx["logs"] / "python.log").exists(), "python must not be invoked"
    assert not (ctx["logs"] / "taskkill.log").exists(), "taskkill must not be invoked"


def test_start_bat_activates_venv_and_runs_python_app_when_port_free(tmp_path: Path) -> None:
    ctx = _install_app(tmp_path)
    _install_fake_netstat(ctx["fake_bin"], occupied=False)

    result = _run_start_bat(ctx["root"], ctx["env"])

    assert result.returncode == 0
    assert (ctx["logs"] / "activate.log").read_text(encoding="ascii").strip() == "activated"
    assert (ctx["logs"] / "python.log").read_text(encoding="ascii").strip() == "-m pdf_reader"
    assert not (ctx["logs"] / "taskkill.log").exists()


def test_start_bat_reports_missing_venv_and_exits_nonzero(tmp_path: Path) -> None:
    root = tmp_path / "app"
    root.mkdir()
    shutil.copy2(START_BAT, root / "start.bat")
    fake_bin = root / "fake-bin"
    fake_bin.mkdir()
    logs = root / "logs"
    logs.mkdir()
    _install_fake_netstat(fake_bin, occupied=False)
    _write_script(fake_bin / "python.cmd", ['echo %* >> "%PYTHON_LOG%"', "exit /b 0"])

    env = os.environ.copy()
    env["PATH"] = str(fake_bin) + os.pathsep + env["PATH"]
    env["PYTHON_LOG"] = str(logs / "python.log")

    result = _run_start_bat(root, env)

    assert result.returncode != 0
    assert "venv" in result.stdout.lower()
    assert "python.exe" in result.stdout.lower()
    assert not (logs / "python.log").exists()
