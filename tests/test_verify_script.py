"""P2-04 verify.ps1 行为测试（Windows + fake 命令 + 受控临时目录，不污染环境）。"""

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
VERIFY = REPO_ROOT / "scripts" / "verify.ps1"

pytestmark = pytest.mark.skipif(os.name != "nt", reason="verify.ps1 is Windows/PowerShell-only")


def _write_cmd(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body.replace("\n", "\r\n"), encoding="ascii")


def _fake_bin(tmp_path: Path) -> Path:
    fake = tmp_path / "fake-bin"
    _write_cmd(
        fake / "python.cmd",
        "@echo off\n@echo %~f0\n@echo 3.12.0\nexit /b 0\n",
    )
    _write_cmd(fake / "npm.cmd", "@echo off\necho fake npm %*\nexit /b 0\n")
    return fake


def _run_powershell(command: str, env: dict, cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_explicit_interpreter_resolution(tmp_path):
    fake = _fake_bin(tmp_path)
    python = fake / "python.cmd"
    env = os.environ.copy()
    env["PATH"] = str(fake) + os.pathsep + env["PATH"]
    command = f". '{VERIFY}'; Write-Output (Resolve-VerifyPython -PythonExecutable '{python}')"
    result = _run_powershell(command, env)
    assert result.returncode == 0, result.stderr
    assert str(python) in result.stdout
    assert "WARNING" not in result.stdout + result.stderr


def test_invalid_explicit_interpreter_fails(tmp_path):
    fake = _fake_bin(tmp_path)
    missing = tmp_path / "missing" / "python.exe"
    env = os.environ.copy()
    env["PATH"] = str(fake) + os.pathsep + env["PATH"]
    command = f". '{VERIFY}'; Resolve-VerifyPython -PythonExecutable '{missing}'"
    result = _run_powershell(command, env)
    assert result.returncode != 0
    assert "Python executable not found" in result.stderr


def test_venv_priority(tmp_path):
    root = tmp_path / "repo"
    (root / "venv" / "Scripts").mkdir(parents=True)
    (root / "venv" / "Scripts" / "python.exe").write_bytes(b"")
    env = os.environ.copy()
    command = f". '{VERIFY}'; Write-Output (Resolve-VerifyPython -RepoRoot '{root}')"
    result = _run_powershell(command, env)
    assert result.returncode == 0, result.stderr
    assert str(root / "venv" / "Scripts" / "python.exe") in result.stdout
    assert "WARNING" not in result.stdout + result.stderr


def test_system_fallback_warns(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    fake = _fake_bin(tmp_path)
    env = os.environ.copy()
    env["PATH"] = str(fake) + os.pathsep + env["PATH"]
    command = f". '{VERIFY}'; Write-Output (Resolve-VerifyPython -RepoRoot '{root}')"
    result = _run_powershell(command, env)
    assert result.returncode == 0, result.stderr
    assert "python" in result.stdout
    assert "WARNING" in result.stdout + result.stderr
    assert "falling back" in result.stdout + result.stderr


def test_full_script_explicit_fake_commands(tmp_path):
    fake = _fake_bin(tmp_path)
    python = fake / "python.cmd"
    env = os.environ.copy()
    env["PATH"] = str(fake) + os.pathsep + env["PATH"]
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(VERIFY),
            "-PythonExecutable",
            str(python),
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert f"Resolved Python: {python}" in result.stdout
    assert "Python version: 3.12.0" in result.stdout
    assert "All verification checks passed." in result.stdout
    assert "WARNING" not in result.stdout + result.stderr


def test_full_script_invalid_explicit_fails_fast(tmp_path):
    fake = _fake_bin(tmp_path)
    marker = tmp_path / "npm-invoked.txt"
    _write_cmd(fake / "npm.cmd", f'@echo off\necho x > "{marker}"\nexit /b 0\n')
    missing = tmp_path / "missing" / "python.exe"
    env = os.environ.copy()
    env["PATH"] = str(fake) + os.pathsep + env["PATH"]
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(VERIFY),
            "-PythonExecutable",
            str(missing),
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode != 0
    assert "Python executable not found" in result.stderr
    assert not marker.exists(), "npm must not be invoked when explicit interpreter is invalid"
