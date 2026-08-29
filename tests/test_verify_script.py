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


def _write_coverage_fake_python(fake: Path, *, fail_policy: bool = False) -> Path:
    python = fake / "python.cmd"
    fail_line = "if defined FAKE_FAIL_POLICY exit /b 1" if fail_policy else "exit /b 0"
    body = (
        "@echo off\n"
        "echo %~f0\n"
        "echo 3.12.0\n"
        'set "ARGS=%*"\n'
        'echo %ARGS% | findstr /C:"coverage run" >nul\n'
        "if not errorlevel 1 (\n"
        '  if defined COVERAGE_FILE (echo data > "%COVERAGE_FILE%")\n'
        "  exit /b 0\n"
        ")\n"
        'echo %ARGS% | findstr /C:"coverage json" >nul\n'
        "if not errorlevel 1 (\n"
        '  if defined COVERAGE_FILE (for %%F in ("%COVERAGE_FILE%") do echo data > "%%~dpFcoverage.json")\n'
        "  exit /b 0\n"
        ")\n"
        'echo %ARGS% | findstr /C:"coverage xml" >nul\n'
        "if not errorlevel 1 (\n"
        '  if defined COVERAGE_FILE (for %%F in ("%COVERAGE_FILE%") do echo data > "%%~dpFcoverage.xml")\n'
        "  exit /b 0\n"
        ")\n"
        'echo %ARGS% | findstr /C:"check_coverage_policy" >nul\n'
        f"if not errorlevel 1 (\n  {fail_line}\n)\n"
        "exit /b 0\n"
    )
    _write_cmd(python, body)
    return python


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
    assert "Coverage + Python tests" in result.stdout
    assert "Coverage policy" in result.stdout
    assert "Mypy" in result.stdout
    assert "JS lint" in result.stdout
    assert "Frontend tests" in result.stdout
    assert "All verification checks passed." in result.stdout
    assert "WARNING" not in result.stdout + result.stderr


def test_full_script_coverage_policy_failure_short_circuits(tmp_path):
    fake = _fake_bin(tmp_path)
    _write_cmd(
        fake / "python.cmd",
        "@echo off\n"
        "echo %~f0\n"
        "echo 3.12.0\n"
        'echo %* | findstr /C:"check_coverage_policy" >nul\n'
        "if not errorlevel 1 exit /b 1\n"
        "exit /b 0\n",
    )
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
    assert "Coverage policy failed" in result.stderr
    assert not marker.exists(), "npm must not run when coverage policy fails"


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


def test_full_script_unsupported_python_fails_before_npm(tmp_path):
    fake = tmp_path / "fake-bin"
    _write_cmd(
        fake / "python.cmd",
        "@echo off\n@echo %~f0\n@echo 3.11.9\nexit /b 0\n",
    )
    marker = tmp_path / "npm-invoked.txt"
    _write_cmd(fake / "npm.cmd", f'@echo off\necho x > "{marker}"\nexit /b 0\n')
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
            str(fake / "python.cmd"),
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode != 0
    assert "Unsupported Python version 3.11.9" in result.stderr
    assert not marker.exists(), "npm must not run on unsupported Python"


def test_full_script_unsupported_node_fails_before_npm(tmp_path):
    fake = tmp_path / "fake-bin"
    _write_cmd(
        fake / "python.cmd",
        "@echo off\n@echo %~f0\n@echo 3.12.0\nexit /b 0\n",
    )
    _write_cmd(fake / "node.cmd", "@echo off\necho v21.7.3\nexit /b 0\n")
    marker = tmp_path / "npm-invoked.txt"
    _write_cmd(fake / "npm.cmd", f'@echo off\necho x > "{marker}"\nexit /b 0\n')
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
            str(fake / "python.cmd"),
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode != 0
    assert "Unsupported Node.js version v21.7.3" in result.stderr
    assert not marker.exists(), "npm must not run on unsupported Node"


def test_full_script_local_coverage_temp_cleaned(tmp_path):
    fake = _fake_bin(tmp_path)
    python = _write_coverage_fake_python(fake)
    env = os.environ.copy()
    env["PATH"] = str(fake) + os.pathsep + env["PATH"]
    env.pop("PYTHONPATH", None)
    temp_root = os.environ["TEMP"]
    before = set(Path(temp_root).glob("pdf-reader-coverage-*"))
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
        timeout=180,
    )
    assert result.returncode == 0, result.stderr
    after = set(Path(temp_root).glob("pdf-reader-coverage-*"))
    assert after == before, "local coverage temp directory must be cleaned"
    assert not (REPO_ROOT / ".coverage").exists()
    assert not (REPO_ROOT / "coverage-artifacts").exists()


def test_full_script_coverage_policy_failure_cleans_temp_and_short_circuits(tmp_path):
    fake = _fake_bin(tmp_path)
    python = _write_coverage_fake_python(fake, fail_policy=True)
    marker = tmp_path / "npm-invoked.txt"
    _write_cmd(fake / "npm.cmd", f'@echo off\necho x > "{marker}"\nexit /b 0\n')
    env = os.environ.copy()
    env["PATH"] = str(fake) + os.pathsep + env["PATH"]
    env["FAKE_FAIL_POLICY"] = "1"
    env.pop("PYTHONPATH", None)
    temp_root = os.environ["TEMP"]
    before = set(Path(temp_root).glob("pdf-reader-coverage-*"))
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
        timeout=180,
    )
    assert result.returncode != 0
    assert "Coverage policy failed" in result.stderr
    after = set(Path(temp_root).glob("pdf-reader-coverage-*"))
    assert after == before, "failed coverage policy must still clean temp coverage dir"
    assert not marker.exists(), "npm must not run when coverage policy fails"


def test_full_script_artifact_dir_keeps_coverage_and_env_not_leaked(tmp_path):
    fake = _fake_bin(tmp_path)
    python = _write_coverage_fake_python(fake)
    artifacts = tmp_path / "artifacts"
    env = os.environ.copy()
    env["PATH"] = str(fake) + os.pathsep + env["PATH"]
    env.pop("PYTHONPATH", None)
    command = (
        "$env:COVERAGE_FILE = 'should-not-leak';"
        f"$env:PDF_READER_COVERAGE_ARTIFACT_DIR = '{artifacts}';"
        f"& '{VERIFY}' -PythonExecutable '{python}';"
        "$code = $LASTEXITCODE;"
        "Write-Output ('VERIFY_EXIT=' + $code);"
        "Write-Output ('COVERAGE_FILE_LEAK=' + ($null -ne $env:COVERAGE_FILE));"
        f"Write-Output ('JSON=' + (Test-Path -LiteralPath '{artifacts}\\coverage.json'));"
        f"Write-Output ('XML=' + (Test-Path -LiteralPath '{artifacts}\\coverage.xml'));"
        "Remove-Item Env:PDF_READER_COVERAGE_ARTIFACT_DIR -ErrorAction SilentlyContinue;"
        "exit $code"
    )
    result = _run_powershell(command, env)
    assert result.returncode == 0, result.stderr
    assert "VERIFY_EXIT=0" in result.stdout
    assert "COVERAGE_FILE_LEAK=False" in result.stdout
    assert "JSON=True" in result.stdout
    assert "XML=True" in result.stdout
    assert (artifacts / "coverage.json").is_file()
    assert (artifacts / "coverage.xml").is_file()
