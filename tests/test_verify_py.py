"""P2-04 scripts/verify.py 公共验证入口契约测试（跨平台，桩工具驱动，不运行真实工具）。

用真实的 ``sys.executable`` 运行 ``scripts/verify.py``，但把 ``--python`` 指向一个
桩解释器，并在 PATH 前置桩 node/npm：这样步骤行为与退出码完全受控，测试在
Windows 与 Linux（WSL）都能运行，验证：

- 版本门槛（Python >= 3.12 / Node >= 22）在第一步就拦截；
- 16 项公共验证按固定顺序执行、任一失败立即短路的确定性；
- coverage 数据落在临时目录或 PDF_READER_COVERAGE_ARTIFACT_DIR 产物目录，
  绝不在仓库根残留 .coverage / coverage.json / coverage.xml，退出时清理临时目录；
- 实际使用的 Python/Node 版本会打印到 stdout。
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VERIFY = REPO_ROOT / "scripts" / "verify.py"

# 桩工具分派脚本：verify.py 把它当作 Python 解释器 / node / npm 的子进程，按
# sys.argv 与 FAKE_FAIL_STEP 环境变量决定退出码，并把每次调用记入日志文件。
DISPATCHER = r"""import os
import sys


def _log(path, line):
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def main() -> int:
    role = sys.argv[1]
    args = sys.argv[2:]
    joined = " ".join(args)
    py_log = os.environ.get("FAKE_PY_LOG", "")
    npm_log = os.environ.get("FAKE_NPM_LOG", "")
    fail = os.environ.get("FAKE_FAIL_STEP", "")

    if role == "python":
        if args and args[0] == "-c":
            code = args[1] if len(args) > 1 else ""
            if "version_info" in code and "import flask" not in code:
                print(os.environ.get("FAKE_PY_EXE", "stub-python"))
                print(os.environ.get("FAKE_PY_VER", "3.12.14"))
                return 0
            if "import flask" in code:
                _log(py_log, "python: " + joined)
                return int(fail == "dependency-import")
        markers = (
            ("scripts/secret_scan.py", "secret-scan"),
            ("scripts/upgrade_governance_gate.py", "upgrade-gate"),
            ("packaging/windows/runtime_policy.py", "runtime-policy"),
            ("-m pip check", "pip-check"),
            ("-m ruff format", "ruff-format"),
            ("-m ruff check", "ruff-lint"),
            ("-m coverage json", "coverage-json"),
            ("-m coverage xml", "coverage-xml"),
            ("-m coverage report", "coverage-report"),
            ("-m coverage run", "coverage-run"),
            ("scripts/check_coverage_policy.py", "coverage-policy"),
            ("scripts/term_quality_gate.py", "term-quality"),
            ("-m mypy", "mypy"),
        )
        key = None
        for marker, name in markers:
            if marker in joined:
                key = name
                break
        _log(py_log, "python: " + joined)
        if key in ("coverage-json", "coverage-xml") and "-o" in args:
            with open(args[args.index("-o") + 1], "w", encoding="utf-8") as handle:
                handle.write("{}")
        if key and key.startswith("coverage-"):
            _log(py_log, "COVERAGE_FILE=" + os.environ.get("COVERAGE_FILE", ""))
        return int(fail == (key or ""))

    if role == "node":
        if args == ["--version"]:
            print("v" + os.environ.get("FAKE_NODE_VER", "26.8.1"))
            return 0
        return 0

    if role == "npm":
        _log(npm_log, "npm: " + joined)
        key = None
        if args and args[0] == "audit":
            key = "npm-audit"
        elif args[:2] == ["run", "lint:js"]:
            key = "js-lint"
        elif args and args[0] == "test":
            key = "npm-test"
        return int(fail == (key or ""))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
"""


def _path_for_shim(bin_dir: Path, name: str) -> Path:
    return bin_dir / (name if os.name != "nt" else f"{name}.cmd")


def _write_shim(bin_dir: Path, name: str, role: str, dispatch: Path) -> Path:
    path = _path_for_shim(bin_dir, name)
    if os.name == "nt":
        path.write_text(f'@"{sys.executable}" "{dispatch}" {role} %*\r\n', encoding="utf-8")
    else:
        path.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{dispatch}" {role} "$@"\n',
            encoding="utf-8",
        )
        path.chmod(0o755)
    return path


class StubEnv:
    """在 tmp 目录生成桩解释器/node/npm 与调用日志路径。"""

    def __init__(self, tmp_path: Path) -> None:
        self.bin_dir = tmp_path / "bin"
        self.bin_dir.mkdir()
        self.dispatch = tmp_path / "tool_stub.py"
        self.dispatch.write_text(DISPATCHER, encoding="utf-8")
        self.python = _write_shim(self.bin_dir, "stub-python", "python", self.dispatch)
        _write_shim(self.bin_dir, "node", "node", self.dispatch)
        _write_shim(self.bin_dir, "npm", "npm", self.dispatch)
        self.py_log = tmp_path / "py.log"
        self.npm_log = tmp_path / "npm.log"

    def env(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        env = os.environ.copy()
        env.pop("PDF_READER_COVERAGE_ARTIFACT_DIR", None)
        env["PATH"] = str(self.bin_dir) + os.pathsep + env.get("PATH", "")
        env["FAKE_PY_LOG"] = str(self.py_log)
        env["FAKE_NPM_LOG"] = str(self.npm_log)
        if extra:
            env.update(extra)
        return env

    def py_lines(self) -> list[str]:
        return self.py_log.read_text(encoding="utf-8").splitlines() if self.py_log.exists() else []

    def npm_lines(self) -> list[str]:
        return self.npm_log.read_text(encoding="utf-8").splitlines() if self.npm_log.exists() else []


def _run_verify(stub: StubEnv, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VERIFY), "--python", str(stub.python)],
        cwd=REPO_ROOT,
        env=stub.env(env_extra),
        capture_output=True,
        text=True,
        timeout=300,
    )


def _temp_leftovers() -> set[str]:
    return {path.name for path in Path(tempfile.gettempdir()).glob("pdf-reader-verify-*")}


def test_reports_python_and_node_versions(tmp_path):
    stub = StubEnv(tmp_path)
    result = _run_verify(stub)
    assert result.returncode == 0, result.stderr
    assert "Resolved Python: stub-python" in result.stdout
    assert "Python version: 3.12.14" in result.stdout
    assert "Node version: v26.8.1" in result.stdout


def test_all_steps_run_in_order(tmp_path):
    stub = StubEnv(tmp_path)
    result = _run_verify(stub)
    assert result.returncode == 0, result.stderr
    for label in (
        "==> Python dependency import",
        "==> pip check",
        "==> Secret scan",
        "==> Upgrade governance gate (static)",
        "==> Portable runtime policy",
        "==> Ruff lint",
        "==> Ruff format check",
        "==> Coverage + Python tests",
        "==> Coverage report",
        "==> Coverage JSON",
        "==> Coverage policy",
        "==> Term quality gate",
        "==> Mypy",
        "==> npm audit",
        "==> JS lint",
        "==> Frontend tests",
    ):
        assert label in result.stdout, f"missing step label: {label!r}"
    assert "All verification checks passed." in result.stdout

    # Python 步骤顺序：依赖导入最前，coverage policy 在 coverage json 之后、
    # term quality / mypy 在 policy 之前，且先于任何 npm 步骤。
    py = stub.py_lines()
    assert any(line.startswith("python: -c import flask") for line in py)
    assert py.index("python: -c import flask, pymupdf, pdf2zh_next, pdf_reader") < py.index("python: -m pip check")
    index_json = next(i for i, line in enumerate(py) if "coverage json" in line)
    index_policy = next(i for i, line in enumerate(py) if "check_coverage_policy" in line)
    index_term = next(i for i, line in enumerate(py) if "term_quality_gate" in line)
    index_mypy = next(i for i, line in enumerate(py) if "-m mypy" in line)
    assert index_json < index_policy < index_term < index_mypy

    npm = stub.npm_lines()
    assert [line.split(": ", 1)[1] for line in npm] == ["audit", "run lint:js", "test"]


def test_upgrade_gate_runs_in_static_only_mode(tmp_path):
    stub = StubEnv(tmp_path)
    result = _run_verify(stub)
    assert result.returncode == 0, result.stderr
    assert any("upgrade_governance_gate.py" in line and "--static-only" in line for line in stub.py_lines())


def test_unsupported_python_version_fails_fast(tmp_path):
    stub = StubEnv(tmp_path)
    result = _run_verify(stub, {"FAKE_PY_VER": "3.11.9"})
    assert result.returncode != 0
    assert "Unsupported Python version 3.11.9" in result.stderr
    assert stub.py_lines() == [] and stub.npm_lines() == []


def test_unsupported_node_version_fails_fast(tmp_path):
    stub = StubEnv(tmp_path)
    result = _run_verify(stub, {"FAKE_NODE_VER": "21.7.3"})
    assert result.returncode != 0
    assert "Unsupported Node.js version v21.7.3" in result.stderr
    assert stub.py_lines() == [] and stub.npm_lines() == []


def test_coverage_policy_failure_short_circuits_before_npm(tmp_path):
    stub = StubEnv(tmp_path)
    result = _run_verify(stub, {"FAKE_FAIL_STEP": "coverage-policy"})
    assert result.returncode != 0
    assert "Coverage policy failed" in result.stderr
    assert stub.npm_lines() == [], "npm must not run when coverage policy fails"


def test_term_quality_failure_short_circuits_before_npm(tmp_path):
    stub = StubEnv(tmp_path)
    result = _run_verify(stub, {"FAKE_FAIL_STEP": "term-quality"})
    assert result.returncode != 0
    assert "Term quality gate failed" in result.stderr
    assert stub.npm_lines() == [], "npm must not run when term quality gate fails"


def test_mypy_failure_short_circuits_before_npm(tmp_path):
    stub = StubEnv(tmp_path)
    result = _run_verify(stub, {"FAKE_FAIL_STEP": "mypy"})
    assert result.returncode != 0
    assert "Mypy failed" in result.stderr
    assert stub.npm_lines() == [], "npm must not run when mypy fails"


def test_npm_audit_failure_fails_verification(tmp_path):
    stub = StubEnv(tmp_path)
    result = _run_verify(stub, {"FAKE_FAIL_STEP": "npm-audit"})
    assert result.returncode != 0
    assert "npm audit failed" in result.stderr
    assert len(stub.npm_lines()) == 1
    assert "Frontend tests" not in result.stdout


def _assert_repo_root_clean() -> None:
    assert not (REPO_ROOT / ".coverage").exists()
    assert not (REPO_ROOT / "coverage.json").exists()
    assert not (REPO_ROOT / "coverage.xml").exists()


def test_local_mode_uses_temp_dir_and_cleans_up(tmp_path):
    stub = StubEnv(tmp_path)
    before = _temp_leftovers()
    result = _run_verify(stub)
    assert result.returncode == 0, result.stderr
    _assert_repo_root_clean()
    assert _temp_leftovers() == before, "local coverage temp dir must be cleaned"


def test_artifact_mode_keeps_coverage_json_and_xml_out_of_repo_root(tmp_path):
    stub = StubEnv(tmp_path)
    artifacts = tmp_path / "artifacts"
    result = _run_verify(stub, {"PDF_READER_COVERAGE_ARTIFACT_DIR": str(artifacts)})
    assert result.returncode == 0, result.stderr
    _assert_repo_root_clean()
    assert (artifacts / "coverage.json").is_file()
    assert (artifacts / "coverage.xml").is_file()
    coverage_lines = [line for line in stub.py_lines() if line.startswith("COVERAGE_FILE=")]
    assert coverage_lines
    assert coverage_lines[0] == f"COVERAGE_FILE={artifacts / '.coverage'}"


def test_failure_still_cleans_local_temp_and_repo_root(tmp_path):
    stub = StubEnv(tmp_path)
    before = _temp_leftovers()
    result = _run_verify(stub, {"FAKE_FAIL_STEP": "term-quality"})
    assert result.returncode != 0
    _assert_repo_root_clean()
    assert _temp_leftovers() == before, "failed verification must still clean coverage temp dir"
