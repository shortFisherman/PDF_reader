"""P0-04 policy checks for the Windows portable Python runtime.

This module deliberately uses only the standard library so the build and CI can
run the source check before installing release dependencies.  P2-01 will call the
artifact check after PyInstaller has assembled the final onedir tree.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

PYTHON_MINOR = "3.12"
RUNTIME_LOCK = Path("packaging/windows/runtime-requirements.lock")
RUNTIME_MANIFEST = Path("app/runtime-manifest.json")
LOCK_COMMAND = (
    "python -m piptools compile --resolver=backtracking --strip-extras "
    "--constraint=requirements.lock "
    "--output-file=packaging/windows/runtime-requirements.lock pyproject.toml"
)

# ruff is a declared runtime dependency of the locked gradio/xsdata graph.  It is
# therefore retained in the runtime lock, despite also being a project dev tool.
DEV_ONLY_DISTRIBUTIONS = frozenset({"coverage", "mypy", "pip-tools", "pytest"})
INSTALLER_DISTRIBUTIONS = frozenset({"ensurepip", "pip", "setuptools", "venv", "wheel"})
FORBIDDEN_IMPORT_ROOTS = INSTALLER_DISTRIBUTIONS
FORBIDDEN_EXECUTABLES = frozenset(
    {
        "node.exe",
        "npm.cmd",
        "npx.cmd",
        "pip.exe",
        "pip3.exe",
        "py.exe",
        "python.exe",
        "pythonw.exe",
    }
)
_NAME_NORMALIZER = re.compile(r"[-_.]+")
_PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")


def normalize_distribution(name: str) -> str:
    return _NAME_NORMALIZER.sub("-", name).lower()


def parse_lock(path: Path) -> dict[str, str]:
    packages: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _PIN.match(line)
        if not match:
            continue
        name = normalize_distribution(match.group(1))
        if name in packages:
            raise ValueError(f"duplicate distribution in {path}: {name}")
        packages[name] = match.group(2)
    if not packages:
        raise ValueError(f"no exact package pins in {path}")
    return packages


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audit_lock(repo_root: Path) -> list[str]:
    runtime_path = repo_root / RUNTIME_LOCK
    aggregate_path = repo_root / "requirements.lock"
    violations: list[str] = []
    try:
        runtime = parse_lock(runtime_path)
        aggregate = parse_lock(aggregate_path)
    except (OSError, ValueError) as exc:
        return [str(exc)]

    header = "\n".join(runtime_path.read_text(encoding="utf-8").splitlines()[:8])
    if f"pip-compile with Python {PYTHON_MINOR}" not in header:
        violations.append(f"{RUNTIME_LOCK} must record Python {PYTHON_MINOR}")
    if LOCK_COMMAND not in header:
        violations.append(f"{RUNTIME_LOCK} must record the canonical compile command")

    for name, version in runtime.items():
        if aggregate.get(name) != version:
            violations.append(f"runtime pin differs from requirements.lock: {name}=={version}")
    try:
        with (repo_root / "pyproject.toml").open("rb") as handle:
            direct_dependencies = tomllib.load(handle)["project"]["dependencies"]
        direct_pins = {
            normalize_distribution(match.group(1)): match.group(2)
            for dependency in direct_dependencies
            if (match := _PIN.fullmatch(dependency))
        }
    except (OSError, KeyError, TypeError, ValueError) as exc:
        violations.append(f"cannot read exact runtime declarations from pyproject.toml: {exc}")
        direct_pins = {}
    for name, version in direct_pins.items():
        if runtime.get(name) != version:
            violations.append(f"direct runtime dependency missing or changed: {name}=={version}")
    for name in sorted(DEV_ONLY_DISTRIBUTIONS | INSTALLER_DISTRIBUTIONS):
        if name in runtime:
            violations.append(f"forbidden release distribution is runtime-locked: {name}")
    return violations


def _call_name(node: ast.Call) -> tuple[str, str] | None:
    if not isinstance(node.func, ast.Attribute) or not isinstance(node.func.value, ast.Name):
        return None
    return node.func.value.id, node.func.attr


def _literal_command_tokens(node: ast.AST) -> tuple[str, ...] | None:
    values: list[str] = []
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        values = re.split(r"\s+", node.value.strip())
    elif isinstance(node, (ast.List, ast.Tuple)):
        for item in node.elts:
            if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
                return None
            values.append(item.value)
    else:
        return None
    return tuple(value.lower() for value in values)


class _ProductionVisitor(ast.NodeVisitor):
    def __init__(self, relative_path: Path) -> None:
        self.relative_path = relative_path
        self.functions: list[str] = []
        self.violations: list[str] = []

    def _add(self, node: ast.AST, message: str) -> None:
        self.violations.append(f"{self.relative_path}:{getattr(node, 'lineno', 0)}: {message}")

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.functions.append(node.name)
        self.generic_visit(node)
        self.functions.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if normalize_distribution(alias.name.split(".", 1)[0]) in FORBIDDEN_IMPORT_ROOTS:
                self._add(node, f"forbidden runtime installer import: {alias.name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        root = (node.module or "").split(".", 1)[0]
        if normalize_distribution(root) in FORBIDDEN_IMPORT_ROOTS:
            self._add(node, f"forbidden runtime installer import: {node.module}")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        call_name = _call_name(node)
        if call_name == ("importlib", "import_module") and node.args:
            argument = node.args[0]
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                root = normalize_distribution(argument.value.split(".", 1)[0])
                if root in FORBIDDEN_IMPORT_ROOTS:
                    self._add(node, f"forbidden dynamic installer import: {argument.value}")

        process_call = call_name and (
            (call_name[0] == "subprocess" and call_name[1] in {"Popen", "call", "check_call", "check_output", "run"})
            or (call_name[0] == "os" and (call_name[1] in {"popen", "system"} or call_name[1].startswith("spawn")))
        )
        if process_call:
            launcher_exception = (
                self.relative_path.as_posix() == "src/pdf_reader/portable_launcher.py"
                and self.functions[-1:] == ["run_portable_launcher"]
                and call_name == ("subprocess", "Popen")
            )
            if launcher_exception:
                self.generic_visit(node)
                return
            tokens = _literal_command_tokens(node.args[0]) if node.args else None
            forbidden = bool(
                tokens
                and (
                    Path(tokens[0].replace("\\", "/")).name in FORBIDDEN_EXECUTABLES
                    or any(tokens[index : index + 2] == ("-m", "pip") for index in range(len(tokens) - 1))
                )
            )
            detail = (
                "forbidden interpreter/installer process launch"
                if forbidden
                else "unapproved production process launch"
            )
            self._add(node, detail)
        self.generic_visit(node)


def audit_source_tree(repo_root: Path) -> list[str]:
    source_root = repo_root / "src" / "pdf_reader"
    violations: list[str] = []
    for source in sorted(source_root.rglob("*.py")):
        relative = source.relative_to(repo_root)
        try:
            tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(relative))
        except (OSError, SyntaxError) as exc:
            violations.append(f"{relative}: cannot scan: {exc}")
            continue
        visitor = _ProductionVisitor(relative)
        visitor.visit(tree)
        violations.extend(visitor.violations)
    return violations


def _manifest_packages(payload: dict[str, Any]) -> tuple[dict[str, str], list[str]]:
    packages: dict[str, str] = {}
    violations: list[str] = []
    raw_packages = payload.get("packages")
    if not isinstance(raw_packages, list):
        return {}, ["runtime manifest packages must be a list"]
    for item in raw_packages:
        if not isinstance(item, dict):
            violations.append("runtime manifest package entry must be an object")
            continue
        name = item.get("name")
        version = item.get("version")
        wheel_sha256 = item.get("wheel_sha256")
        if not isinstance(name, str) or not isinstance(version, str):
            violations.append("runtime manifest package name/version must be strings")
            continue
        normalized = normalize_distribution(name)
        if normalized in packages:
            violations.append(f"runtime manifest contains duplicate package: {normalized}")
        packages[normalized] = version
        if not isinstance(wheel_sha256, str) or not _HEX_64.fullmatch(wheel_sha256):
            violations.append(f"runtime manifest has invalid wheel hash: {normalized}")
    return packages, violations


def audit_runtime_manifest(repo_root: Path, artifact_root: Path) -> list[str]:
    manifest_path = artifact_root / RUNTIME_MANIFEST
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        locked = parse_lock(repo_root / RUNTIME_LOCK)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [f"cannot read runtime manifest contract: {exc}"]
    if not isinstance(payload, dict):
        return ["runtime manifest root must be an object"]

    violations: list[str] = []
    if payload.get("schema_version") != 1:
        violations.append("runtime manifest schema_version must be 1")
    if payload.get("source_lock") != RUNTIME_LOCK.as_posix():
        violations.append("runtime manifest source_lock is not the canonical runtime lock")
    expected_lock_hash = sha256_file(repo_root / RUNTIME_LOCK)
    if payload.get("source_lock_sha256") != expected_lock_hash:
        violations.append("runtime manifest source lock hash does not match")
    source_commit = payload.get("source_commit")
    if not isinstance(source_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        violations.append("runtime manifest source_commit must be a full lowercase Git commit")

    python = payload.get("python")
    if not isinstance(python, dict):
        violations.append("runtime manifest python entry must be an object")
    else:
        version = python.get("version")
        if not isinstance(version, str) or not version.startswith(f"{PYTHON_MINOR}."):
            violations.append(f"runtime manifest Python must be {PYTHON_MINOR}.x")
        if python.get("executable") != "app/PDF Reader Service.exe":
            violations.append("runtime manifest Python executable must be the private service")
        executable_sha256 = python.get("executable_sha256")
        if not isinstance(executable_sha256, str) or not _HEX_64.fullmatch(executable_sha256):
            violations.append("runtime manifest private service hash is invalid")
        else:
            service_path = artifact_root / "app" / "PDF Reader Service.exe"
            if service_path.is_file() and sha256_file(service_path) != executable_sha256:
                violations.append("runtime manifest private service hash does not match")

    packages, package_violations = _manifest_packages(payload)
    violations.extend(package_violations)
    if packages != locked:
        missing = sorted(set(locked) - set(packages))
        extra = sorted(set(packages) - set(locked))
        changed = sorted(name for name in set(locked) & set(packages) if locked[name] != packages[name])
        violations.append(f"runtime manifest differs from lock: missing={missing}, extra={extra}, changed={changed}")
    return violations


def audit_artifact_tree(repo_root: Path, artifact_root: Path) -> list[str]:
    violations: list[str] = []
    required = (Path("PDF Reader.exe"), Path("app/PDF Reader Service.exe"), RUNTIME_MANIFEST)
    for relative in required:
        if not (artifact_root / relative).is_file():
            violations.append(f"release artifact missing required file: {relative.as_posix()}")

    try:
        aggregate = parse_lock(repo_root / "requirements.lock")
        runtime = parse_lock(repo_root / RUNTIME_LOCK)
        lock_dev_only = set(aggregate) - set(runtime)
    except (OSError, ValueError) as exc:
        violations.append(f"cannot derive dev-only artifact denylist: {exc}")
        lock_dev_only = set()
    forbidden_components = DEV_ONLY_DISTRIBUTIONS | INSTALLER_DISTRIBUTIONS | lock_dev_only | {"-pytest"}
    for path in sorted(artifact_root.rglob("*")):
        relative = path.relative_to(artifact_root)
        if path.is_file() and path.name.lower() in FORBIDDEN_EXECUTABLES:
            violations.append(f"release artifact contains external runtime executable: {relative.as_posix()}")
        for part in relative.parts:
            component = normalize_distribution(part)
            if any(component == name or component.startswith(f"{name}-") for name in forbidden_components):
                violations.append(f"release artifact contains installer/dev component: {relative.as_posix()}")
                break
    if not violations:
        violations.extend(audit_runtime_manifest(repo_root, artifact_root))
    return violations


def _print_result(label: str, violations: list[str]) -> bool:
    if violations:
        for violation in violations:
            print(f"ERROR [{label}]: {violation}", file=sys.stderr)
        return False
    print(f"{label}: ok")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the Windows portable private-runtime policy")
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--artifact", type=Path)
    args = parser.parse_args(argv)
    repo_root = args.source_root.resolve()
    ok = _print_result("runtime-lock", audit_lock(repo_root))
    ok = _print_result("production-source", audit_source_tree(repo_root)) and ok
    if args.artifact is not None:
        ok = _print_result("release-artifact", audit_artifact_tree(repo_root, args.artifact.resolve())) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
