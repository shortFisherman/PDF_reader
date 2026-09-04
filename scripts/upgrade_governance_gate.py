"""P2-04 上游升级与无补丁治理门（离线、确定性）。

一键命令：
    python scripts/upgrade_governance_gate.py

覆盖范围（与 docs/governance/dependency-upgrade.md 同步，升级前后都必须通过）：

1. 依赖来源治理：pyproject.toml 与 requirements.lock 不允许 VCS URL、分支/commit
   引用、个人 fork、editable/path/file/URL 直接引用或未锁定版本；运行时直接依赖
   必须精确 ``==`` 固定；pdf2zh-next / babeldoc 固定版本在 pyproject 与锁文件间一致。
2. 仓库治理：任意位置的 pdf2zh_next / babeldoc 影子包或影子模块文件、vendor/fork
   目录变体、上游源码副本与生产（src/pdf_reader）Monkey-patch 都能被发现；
   排除 venv/node_modules/缓存/构建目录，不扫描 tests 中的合法 mock patch。
3. 契约测试：术语选择（auto-on/off）、严格正文 Settings 路径（自动提取恒关闭、
   只传有效词表）、候选隔离（未接受候选不进入有效词表/正文权威）、合规验证/重试
   与 right.pdf 提交门回归。

``--static-only`` 只执行静态治理检查，不重复运行契约 pytest；
scripts/verify.ps1 使用该模式，CI 通过同一 verify.ps1 持续执行。完整模式（默认）
在静态检查通过后运行固定的契约测试文件。本脚本不联网、不修改任何文件。
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tomllib
from collections.abc import Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

PYPROJECT = "pyproject.toml"
LOCK_FILE = "requirements.lock"

LOCK_HEADER_COMMAND = (
    "pip-compile --resolver=backtracking --strip-extras --extra=dev --output-file=requirements.lock pyproject.toml"
)

UPSTREAM_PINS = {"pdf2zh-next": "2.9.0", "babeldoc": "0.6.2"}

# 契约测试选择：覆盖依赖契约、上游术语选择、仓库守卫、严格正文路径、候选隔离、
# 合规验证/重试/提交门。删除或改名任何文件都必须先同步本清单与文档。
CONTRACT_TEST_FILES = [
    "tests/test_dependency_contract.py",
    "tests/test_upstream_contract.py",
    "tests/test_upstream_boundary_governance.py",
    "tests/test_strict_glossary.py",
    "tests/test_glossary_compliance_flow.py",
    "tests/test_terminology_compliance.py",
    "tests/test_glossary_compiler.py",
]

# 本地状态/工具/构建目录，永不扫描：venv 与 node_modules 中安装的是真实上游包，
# 不是仓库影子包；缓存与工作流状态目录不进入治理范围。
EXCLUDED_DIR_NAMES = frozenset(
    {
        ".git",
        ".git-rewrite",
        ".codegraph",
        ".firecrawl",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        ".worktrees",
        "__pycache__",
        "build",
        "cache",
        "coverage-artifacts",
        "dist",
        "htmlcov",
        "logs",
        "node_modules",
        "venv",
        "worktrees",
    }
)

SHADOW_PACKAGE_DIRS = frozenset({"pdf2zh_next", "babeldoc"})
SHADOW_MODULE_STEMS = frozenset({"pdf2zh_next", "babeldoc"})
FORK_NAME_MARKERS = ("pdf2zh", "pdfmath", "babeldoc")
VENDOR_DIR_NAMES = frozenset(
    {
        "vendor",
        "third_party",
        "thirdparty",
        "forks",
        "patches",
        "local_packages",
        "upstream_src",
        "vendored",
    }
)

# 上游独有定义标记：以组合片段书写，保证本文件与测试文件不出现完整 marker 字面量，
# 否则守卫会把自身误判为源码副本；运行时值与真实标记逐字节一致。
_MARKER_PARTS: tuple[tuple[str, ...], ...] = (
    ("class ", "SharedContext", "CrossSplitPart", ":"),
    ("class ", "Automatic", "TermExtractor", ":"),
    ("class ", "Translation", "Config", ":"),
    ("class ", "Glossary", ":"),
    ("class ", "Glossary", "Entry", ":"),
    ("def ", "get_glossaries", "_for_translation", "("),
    ("def ", "finalize_auto", "_extracted_glossary", "("),
)
UPSTREAM_DEFINITION_MARKERS = tuple("".join(parts) for parts in _MARKER_PARTS)

MONKEY_PATCH_PATTERNS = (
    re.compile(
        r"\b(?:AutomaticTermExtractor|get_glossaries_for_translation|"
        r"finalize_auto_extracted_glossary)\s*=(?!=)"
    ),
    re.compile(
        r"\b(?:pdf2zh_next|babeldoc)(?:\.[A-Za-z_][A-Za-z0-9_]*)+"
        r"\s*=(?!=)"
    ),
    re.compile(
        r"\bsetattr\s*\([^)]*(?:get_glossaries_for_translation|"
        r"AutomaticTermExtractor|finalize_auto_extracted_glossary)"
    ),
    re.compile(r"\bsys\.modules\s*\[\s*(['\"])pdf2zh_next\1\s*\]\s*=(?!=)"),
    re.compile(r"\bsys\.modules\s*\[\s*(['\"])babeldoc\1\s*\]\s*=(?!=)"),
    re.compile(
        r"\b(?:from\s+unittest\.mock|from\s+mock|import\s+mock|"
        r"import\s+monkeypatch|monkeypatch|patch\s*\()"
    ),
)


def _walk_repo(root: Path) -> Iterator[tuple[Path, list[str], list[str]]]:
    for current, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            name for name in dirnames if name not in EXCLUDED_DIR_NAMES and not name.endswith(".egg-info")
        )
        yield Path(current), dirnames, filenames


def _forbidden_source_reason(spec: str) -> str | None:
    s = spec.strip()
    if re.match(r"^\s*(?:-e\s+|--editable\s+)", s):
        return "editable dependency is forbidden"
    # fail-closed：VCS/direct URL/file URL 无论出现在标准 PEP 508 位置还是伪装在
    # ``==`` 之后（如 ``evil==git+https://...``、``evil==file:///...``、
    # ``evil==https://...``）都必须拒绝，不依赖其出现位置。
    if re.search(r"(?:git|hg|svn|bzr)\+", s, re.IGNORECASE):
        return "VCS dependency URL is forbidden"
    if re.search(r"[a-zA-Z][a-zA-Z0-9+.\-]*://", s):
        return "direct URL dependency is forbidden"
    if re.match(r"^[A-Za-z0-9._-]+\s*@\s*[^\s;]+", s):
        return "PEP 508 direct reference (name @ ...) is forbidden"
    if re.match(r"^[./\\]", s) or re.match(r"^[A-Za-z]:[\\/]", s):
        return "local path dependency is forbidden"
    return None


def check_dependency_sources(root: Path) -> list[str]:
    """检查 pyproject.toml / requirements.lock 的依赖来源与上游固定版本一致性。"""
    violations: list[str] = []
    pyproject_path = root / PYPROJECT
    lock_path = root / LOCK_FILE
    if not pyproject_path.is_file() or not lock_path.is_file():
        return ["missing dependency manifests: pyproject.toml / requirements.lock"]

    try:
        pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        return [f"{PYPROJECT} unparseable: {exc}"]

    project = pyproject.get("project", {})
    runtime = [str(item) for item in project.get("dependencies", [])]
    optional: list[str] = []
    for group in project.get("optional-dependencies", {}).values():
        optional.extend(str(item) for item in group)

    for spec in runtime + optional:
        reason = _forbidden_source_reason(spec)
        if reason is not None:
            violations.append(f"{PYPROJECT}: {spec!r}: {reason}")
    for spec in runtime:
        if not re.fullmatch(r"[A-Za-z0-9._-]+==[^=;\s]+", spec.strip()):
            violations.append(f"{PYPROJECT}: {spec!r}: runtime dependency must be exact-pinned (==)")

    pyproject_pins = {name: version for spec in runtime for name, sep, version in (spec.partition("=="),) if sep}
    for name, expected in UPSTREAM_PINS.items():
        if name == "pdf2zh-next":
            if pyproject_pins.get(name) != expected:
                violations.append(f"{PYPROJECT} must pin {name}=={expected}, got {pyproject_pins.get(name)!r}")
        elif name in pyproject_pins:
            violations.append(
                f"{PYPROJECT} must not declare transitive dependency {name} (only requirements.lock pins it)"
            )

    lock_lines = [line.strip() for line in lock_path.read_text(encoding="utf-8", errors="replace").splitlines()]
    if LOCK_HEADER_COMMAND not in "\n".join(lock_lines[:8]):
        violations.append(f"{LOCK_FILE} header must record the pip-compile command")

    lock_pins: dict[str, str] = {}
    for raw_line in lock_lines:
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        reason = _forbidden_source_reason(line)
        if reason is not None:
            violations.append(f"{LOCK_FILE}: {raw_line!r}: {reason}")
            continue
        match = re.fullmatch(r"([A-Za-z0-9._-]+)==([^#\s;]+)(.*)", line)
        if match is None:
            violations.append(f"{LOCK_FILE}: {raw_line!r}: unsupported or unpinned requirement line")
            continue
        lock_pins[match.group(1)] = match.group(2)

    for name, expected in UPSTREAM_PINS.items():
        if lock_pins.get(name) != expected:
            violations.append(f"{LOCK_FILE} must pin {name}=={expected}, got {lock_pins.get(name)!r}")
    return violations


def _vendor_contains_upstream(vendor_dir: Path) -> bool:
    for path in vendor_dir.rglob("*"):
        if path.is_dir():
            if path.name.lower() in SHADOW_PACKAGE_DIRS:
                return True
            continue
        if path.suffix == ".py":
            if path.stem.lower() in SHADOW_MODULE_STEMS:
                return True
            text = path.read_text(encoding="utf-8", errors="replace")
            if any(marker in text for marker in UPSTREAM_DEFINITION_MARKERS):
                return True
    return False


def check_repo_governance(root: Path) -> list[str]:
    """全工作树扫描：影子包/影子模块、fork/vendor 变体、上游源码副本与补丁目录。"""
    violations: list[str] = []
    vendor_dirs: list[Path] = []
    for current, dirnames, filenames in _walk_repo(root):
        current_path = Path(current)
        for name in sorted(dirnames):
            lowered = name.lower()
            rel = (current_path / name).relative_to(root)
            if lowered in SHADOW_PACKAGE_DIRS:
                violations.append(f"{rel.as_posix()}: shadow package directory")
            elif lowered == "patches":
                violations.append(f"{rel.as_posix()}: upstream patch directory")
            elif any(marker in lowered for marker in FORK_NAME_MARKERS):
                violations.append(f"{rel.as_posix()}: fork-like upstream directory")
            elif lowered in VENDOR_DIR_NAMES:
                vendor_dirs.append(current_path / name)
        for name in sorted(filenames):
            path = current_path / name
            if path.suffix != ".py":
                continue
            rel = path.relative_to(root)
            if path.stem.lower() in SHADOW_MODULE_STEMS:
                violations.append(f"{rel.as_posix()}: shadow module file")
            text = path.read_text(encoding="utf-8", errors="replace")
            if any(marker in text for marker in UPSTREAM_DEFINITION_MARKERS):
                violations.append(f"{rel.as_posix()}: upstream source copy")

    for vendor_dir in vendor_dirs:
        if _vendor_contains_upstream(vendor_dir):
            violations.append(f"{vendor_dir.relative_to(root).as_posix()}: vendored upstream source directory")
    return violations


def check_monkey_patch(root: Path) -> list[str]:
    """递归扫描生产包 src/pdf_reader（含嵌套包）；tests/ 的合法 mock patch 不扫描不误报。"""
    violations: list[str] = []
    production = root / "src" / "pdf_reader"
    if not production.is_dir():
        return violations
    for py in sorted(production.rglob("*.py")):
        if "__pycache__" in py.parts:
            continue
        text = py.read_text(encoding="utf-8", errors="replace")
        for pattern in MONKEY_PATCH_PATTERNS:
            if pattern.search(text):
                violations.append(f"{py.relative_to(root).as_posix()}: {pattern.pattern}")
    return violations


def check_all_static(root: Path) -> list[str]:
    return check_dependency_sources(root) + check_repo_governance(root) + check_monkey_patch(root)


def run_contract_tests(root: Path, python: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [python or sys.executable, "-m", "pytest", "-q", *CONTRACT_TEST_FILES],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=1800,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P2-04 上游升级与无补丁治理门")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--static-only",
        action="store_true",
        help="只运行静态治理检查，不重复运行契约 pytest（scripts/verify.ps1 使用）",
    )
    args = parser.parse_args(argv)
    root = args.repo_root.resolve()
    if not (root / PYPROJECT).is_file() or not (root / LOCK_FILE).is_file():
        parser.error(f"not a PDF_reader repo root: {root}")

    violations = check_all_static(root)
    if violations:
        for violation in violations:
            print(f"FAIL: {violation}")
        print("UPGRADE GOVERNANCE GATE FAILED")
        return 1

    print("Static governance checks PASSED")
    if args.static_only:
        print("Upgrade governance gate PASSED")
        return 0

    print(f"==> Contract tests ({len(CONTRACT_TEST_FILES)} files)")
    result = run_contract_tests(root)
    if result.stdout:
        print(result.stdout)
    if result.returncode != 0:
        print(result.stderr)
        print("UPGRADE GOVERNANCE GATE FAILED (contract tests)")
        return 1
    print("Upgrade governance gate PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
