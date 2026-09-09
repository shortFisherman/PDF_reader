"""P2-04 verify.ps1 委托包装器行为测试（Windows + fake 命令，不污染环境）。

verify.ps1 现在只做三件事：解析 Python 解释器、把 ``PDF_READER_COVERAGE_ARTIFACT_DIR``
等环境变量透传、以 ``python scripts/verify.py`` 委托公共验证并传播退出码。
完整验证步骤与版本门槛由 scripts/verify.py 承担，其契约由 tests/test_verify_py.py
覆盖（跨平台运行）；本文件只固定 verify.ps1 在 Windows 侧的包装行为。
"""

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

    def write(name: str, body: str) -> None:
        _write_cmd(fake / name, body)

    # 默认成功桩：echo 解释器路径、伪版本、并回显调用参数与透传的产物目录 env。
    write(
        "python.cmd",
        "@echo off\n"
        "@echo %~f0\n"
        "@echo 3.12.0\n"
        "@echo ARGS: %*\n"
        "if defined PDF_READER_COVERAGE_ARTIFACT_DIR echo ARTIFACT_DIR=%PDF_READER_COVERAGE_ARTIFACT_DIR%\n"
        "exit /b 0\n",
    )
    write("npm.cmd", "@echo off\necho fake npm %*\nexit /b 0\n")
    return fake


def _fake_failing_python(tmp_path: Path) -> Path:
    fake = tmp_path / "fake-bin"
    _write_cmd(
        fake / "python.cmd",
        "@echo off\n@echo %~f0\n@echo 3.12.0\nexit /b 1\n",
    )
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


def test_full_script_invalid_explicit_fails_fast(tmp_path):
    fake = _fake_bin(tmp_path)
    marker = tmp_path / "npm-invoked.txt"
    _write_cmd(fake / "npm.cmd", f'@echo off\necho x > "{marker}"\nexit /b 0\n')
    missing = tmp_path / "missing" / "python.exe"
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


def test_full_script_delegates_to_verify_py(tmp_path):
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
    assert "==> Common verification (scripts/verify.py)" in result.stdout
    assert "scripts/verify.py" in result.stdout
    assert "All verification checks passed." in result.stdout
    assert "WARNING" not in result.stdout + result.stderr


def test_full_script_verify_py_failure_fails_fast(tmp_path):
    fake = _fake_failing_python(tmp_path)
    marker = tmp_path / "npm-invoked.txt"
    _write_cmd(fake / "npm.cmd", f'@echo off\necho x > "{marker}"\nexit /b 0\n')
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
    assert result.returncode != 0
    assert "Verification failed with exit code 1" in result.stderr
    assert not marker.exists(), "npm orchestration lives in verify.py; wrapper must not invoke npm"


def test_full_script_does_not_mutate_coverage_env(tmp_path):
    fake = _fake_bin(tmp_path)
    python = fake / "python.cmd"
    env = os.environ.copy()
    env["PATH"] = str(fake) + os.pathsep + env["PATH"]
    env.pop("PYTHONPATH", None)
    command = (
        "$env:COVERAGE_FILE = 'should-not-leak';"
        f"& '{VERIFY}' -PythonExecutable '{python}';"
        "$code = $LASTEXITCODE;"
        "Write-Output ('VERIFY_EXIT=' + $code);"
        "Write-Output ('COVERAGE_FILE_LEAK=' + ($env:COVERAGE_FILE -ne 'should-not-leak'));"
        "Remove-Item Env:COVERAGE_FILE -ErrorAction SilentlyContinue;"
        "exit $code"
    )
    result = _run_powershell(command, env)
    assert result.returncode == 0, result.stderr
    assert "VERIFY_EXIT=0" in result.stdout
    assert "COVERAGE_FILE_LEAK=False" in result.stdout


def test_full_script_forwards_artifact_dir_env(tmp_path):
    fake = _fake_bin(tmp_path)
    python = fake / "python.cmd"
    artifacts = tmp_path / "artifacts"
    env = os.environ.copy()
    env["PATH"] = str(fake) + os.pathsep + env["PATH"]
    env.pop("PYTHONPATH", None)
    command = (
        f"$env:PDF_READER_COVERAGE_ARTIFACT_DIR = '{artifacts}';"
        f"& '{VERIFY}' -PythonExecutable '{python}';"
        "$code = $LASTEXITCODE;"
        "Remove-Item Env:PDF_READER_COVERAGE_ARTIFACT_DIR -ErrorAction SilentlyContinue;"
        "Write-Output ('VERIFY_EXIT=' + $code);"
        "exit $code"
    )
    result = _run_powershell(command, env)
    assert result.returncode == 0, result.stderr
    assert "VERIFY_EXIT=0" in result.stdout
    assert f"ARTIFACT_DIR={artifacts}" in result.stdout
