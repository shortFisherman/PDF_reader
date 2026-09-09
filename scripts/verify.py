#!/usr/bin/env python3
"""P2-04 跨平台公共验证入口（单份验证逻辑，Windows verify.ps1 与 WSL 共用）。

用法：
    python scripts/verify.py [--python PATH] [--coverage-artifact-dir DIR]

设计契约：

- 本脚本是唯一完整验证编排：``scripts/verify.ps1`` 只负责解析解释器并委托给本脚本；
  WSL 直接用 ``venv/bin/python scripts/verify.py`` 执行同一验证，避免两套逻辑漂移。
- 全部子进程在仓库根以当前解释器（默认 ``sys.executable``）运行；Node/npm 取自 PATH。
- 输出实际使用的 Python 与 Node 版本，版本低于门槛（Python >= 3.12、Node >= 22）即失败。
- 任何一步失败立即以非零退出，不继续后续步骤。
- coverage 数据（.coverage / coverage.json / coverage.xml）写入临时目录（默认）或
  ``PDF_READER_COVERAGE_ARTIFACT_DIR`` 指定目录（CI 保留产物），绝不在仓库根残留；
  退出前清理自建的临时目录。
- 本脚本不读取 config.toml、不启动翻译、不调用任何模型 API、不修改
  config/cache/logs/docs/glossary.csv，也不降低任何质量门。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
COVERAGE_ARTIFACT_ENV = "PDF_READER_COVERAGE_ARTIFACT_DIR"

PYTHON_REQUIRED_MAJOR = 3
PYTHON_REQUIRED_MINOR = 12
NODE_REQUIRED_MAJOR = 22

IMPORT_SMOKE_CODE = "import flask, pymupdf, pdf2zh_next, pdf_reader"
VERSION_PROBE_CODE = "import sys; print(sys.executable); print('.'.join(str(p) for p in sys.version_info[:3]))"


class VerificationError(RuntimeError):
    """某一步验证失败；消息只含标签与退出码等稳定信息。"""


def _tool_argv(name: str, args: Sequence[str]) -> list[str]:
    """构造 node/npm 之类 PATH 工具的 argv。

    Windows 上 npm 是 ``npm.cmd`` 批处理，不能直接被 CreateProcess 执行
    （WinError 193），须交给 ``cmd.exe /c``；POSIX 直接执行。把参数作为独立列表
    元素跟在 ``/c`` 之后，由 subprocess 的 list2cmdline 负责双引号转发（避免把整条
    命令拼成单字符串时被 cmd 的引号剥离规则误拆）。
    """
    if os.name == "nt":
        return ["cmd", "/d", "/c", name, *args]
    return [name, *args]


class Verifier:
    """按固定顺序执行公共验证步骤；失败即抛 VerificationError。"""

    def __init__(
        self,
        *,
        python: str,
        coverage_dir: Path,
        keep_coverage: bool,
    ) -> None:
        self.python = python
        self.coverage_dir = coverage_dir
        self.keep_coverage = keep_coverage

    # -- 子进程执行 -------------------------------------------------------

    def run(self, label: str, argv: Sequence[str], *, coverage: bool = False) -> None:
        print(f"==> {label}")
        env = dict(os.environ)
        env["PYTHONUTF8"] = "1"
        if coverage:
            env["COVERAGE_FILE"] = str(self.coverage_dir / ".coverage")
        result = subprocess.run(argv, cwd=str(REPO_ROOT), env=env)
        if result.returncode != 0:
            raise VerificationError(f"{label} failed with exit code {result.returncode}")

    def python_run(self, label: str, args: Sequence[str], *, coverage: bool = False) -> None:
        self.run(label, self._python_argv(args), coverage=coverage)

    def _python_argv(self, args: Sequence[str]) -> list[str]:
        """构造 Python 子进程 argv；Windows 测试用 .cmd 桩解释器同样经 cmd 执行。"""
        if os.name == "nt" and self.python.lower().endswith((".cmd", ".bat")):
            return ["cmd", "/d", "/c", self.python, *args]
        return [self.python, *args]

    # -- 版本门槛 ---------------------------------------------------------

    def _require_python_version(self) -> None:
        probe = subprocess.run(
            self._python_argv(["-c", VERSION_PROBE_CODE]),
            cwd=str(REPO_ROOT),
            env={**os.environ, "PYTHONUTF8": "1"},
            capture_output=True,
            text=True,
            timeout=120,
        )
        if probe.returncode != 0 or not probe.stdout.strip():
            print(f"Failed to query Python interpreter: {self.python}", file=sys.stderr)
            raise VerificationError("Python interpreter probe failed")
        lines = [line.strip() for line in probe.stdout.splitlines() if line.strip()]
        executable = lines[0]
        version = lines[1] if len(lines) > 1 else "unknown"
        print(f"Resolved Python: {executable}")
        print(f"Python version: {version}")
        parts = version.split(".")
        if len(parts) < 2 or not parts[0].isdigit() or not parts[1].isdigit():
            raise VerificationError(f"could not parse Python version {version!r}")
        if (int(parts[0]), int(parts[1])) < (
            PYTHON_REQUIRED_MAJOR,
            PYTHON_REQUIRED_MINOR,
        ):
            raise VerificationError(
                f"Unsupported Python version {version} "
                f"(>= {PYTHON_REQUIRED_MAJOR}.{PYTHON_REQUIRED_MINOR} required). "
                "Fix the interpreter or pass --python."
            )

    def _require_node_version(self) -> str:
        if shutil.which("node") is None:
            raise VerificationError("Node.js not found on PATH; Node.js >= 22 is required for frontend checks.")
        result = subprocess.run(
            _tool_argv("node", ["--version"]),
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )
        raw = result.stdout.strip() or result.stderr.strip()
        if result.returncode != 0 or not raw:
            raise VerificationError("Node.js failed to report its version; >= 22 required")
        print(f"Node version: {raw}")
        major_text = raw.lstrip("v")
        major = int(major_text.split(".")[0]) if major_text.split(".")[0].isdigit() else 0
        if major < NODE_REQUIRED_MAJOR:
            raise VerificationError(f"Unsupported Node.js version {raw} (>= {NODE_REQUIRED_MAJOR} required).")
        return raw

    # -- 步骤 -------------------------------------------------------------

    def check_python_dependencies(self) -> None:
        self.python_run("Python dependency import", ["-c", IMPORT_SMOKE_CODE])

    def check_pip(self) -> None:
        self.python_run("pip check", ["-m", "pip", "check"])

    def run_secret_scan(self) -> None:
        self.python_run("Secret scan", ["scripts/secret_scan.py"])

    def run_upgrade_gate(self) -> None:
        self.python_run(
            "Upgrade governance gate (static)",
            ["scripts/upgrade_governance_gate.py", "--static-only"],
        )

    def run_runtime_policy(self) -> None:
        self.python_run(
            "Portable runtime policy",
            ["packaging/windows/runtime_policy.py", "--source-root", "."],
        )

    def run_ruff_lint(self) -> None:
        self.python_run("Ruff lint", ["-m", "ruff", "check", "."])

    def run_ruff_format(self) -> None:
        self.python_run("Ruff format check", ["-m", "ruff", "format", "--check", "."])

    def run_pytest(self) -> None:
        self.python_run(
            "Coverage + Python tests",
            ["-m", "coverage", "run", "--branch", "-m", "pytest", "-q"],
            coverage=True,
        )

    def run_coverage_report(self) -> None:
        self.python_run("Coverage report", ["-m", "coverage", "report"], coverage=True)

    def run_coverage_json(self) -> None:
        self.python_run(
            "Coverage JSON",
            ["-m", "coverage", "json", "-o", str(self.coverage_dir / "coverage.json")],
            coverage=True,
        )

    def run_coverage_xml(self) -> None:
        self.python_run(
            "Coverage XML artifact",
            ["-m", "coverage", "xml", "-o", str(self.coverage_dir / "coverage.xml")],
            coverage=True,
        )

    def run_coverage_policy(self) -> None:
        self.python_run(
            "Coverage policy",
            ["scripts/check_coverage_policy.py", str(self.coverage_dir / "coverage.json")],
        )

    def run_term_quality_gate(self) -> None:
        self.python_run("Term quality gate", ["scripts/term_quality_gate.py"])

    def run_mypy(self) -> None:
        self.python_run("Mypy", ["-m", "mypy"])

    def _require_npm(self) -> None:
        if shutil.which("npm") is None:
            raise VerificationError("npm not found on PATH; frontend checks cannot run")

    def run_npm_audit(self) -> None:
        self._require_npm()
        self.run("npm audit", _tool_argv("npm", ["audit"]))

    def run_js_lint(self) -> None:
        self._require_npm()
        self.run("JS lint", _tool_argv("npm", ["run", "lint:js"]))

    def run_frontend_tests(self) -> None:
        self._require_npm()
        self.run("Frontend tests", _tool_argv("npm", ["test"]))

    # -- 编排 -------------------------------------------------------------

    def verify(self) -> None:
        self._require_python_version()
        self._require_node_version()
        self.check_python_dependencies()
        self.check_pip()
        self.run_secret_scan()
        self.run_upgrade_gate()
        self.run_runtime_policy()
        self.run_ruff_lint()
        self.run_ruff_format()
        self.run_pytest()
        self.run_coverage_report()
        self.run_coverage_json()
        if self.keep_coverage:
            self.run_coverage_xml()
        self.run_coverage_policy()
        self.run_term_quality_gate()
        self.run_mypy()
        self.run_npm_audit()
        self.run_js_lint()
        self.run_frontend_tests()
        print("All verification checks passed.")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="跨平台公共验证入口")
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python 解释器（默认当前解释器 sys.executable）",
    )
    parser.add_argument(
        "--coverage-artifact-dir",
        default=None,
        help="coverage 产物目录（默认取环境变量 PDF_READER_COVERAGE_ARTIFACT_DIR；"
        "两者都未设置时用临时目录并在退出时清理）",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    artifact_env = os.environ.get(COVERAGE_ARTIFACT_ENV)
    artifact_dir_value = args.coverage_artifact_dir if args.coverage_artifact_dir else artifact_env
    keep_coverage = artifact_dir_value is not None
    if artifact_dir_value is not None:
        coverage_dir = Path(artifact_dir_value)
        coverage_dir.mkdir(parents=True, exist_ok=True)
    else:
        coverage_dir = Path(tempfile.mkdtemp(prefix="pdf-reader-verify-"))
    own_temp = not keep_coverage

    try:
        verifier = Verifier(
            python=args.python,
            coverage_dir=coverage_dir,
            keep_coverage=keep_coverage,
        )
        verifier.verify()
    except VerificationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        if own_temp:
            shutil.rmtree(coverage_dir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
