"""P2-01 发行构建层契约测试的公共工具。

本模块只读取工作区，不运行真实 Windows 构建、不安装 PyInstaller：它在桩 PyInstaller API
下执行受版本控制的 ``*.spec``，从而在 Linux 上检查 onedir 结构、显式资源收集与动态导入
声明；对 PowerShell 构建脚本则用字符窗口 + 变量作用域分析检查发行边界。

真实 onedir 目录、ZIP 与干净机验证属于 P2-01 构建执行与 P2-02/P3-01，本模块不伪造它们。
"""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import types
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASE_LAYER = REPO_ROOT / "packaging" / "windows"

BUILD_DIRECTORY = "build/release-windows"
DIST_DIRECTORY = "dist/release-windows"
ARTIFACT_DIRNAME = "PDF Reader"
APP_DIRECTORY = "app"
LAUNCHER_EXE = "PDF Reader.exe"
LAUNCHER_STEM = "PDF Reader"
SERVICE_EXE = "PDF Reader Service.exe"
SERVICE_STEM = "PDF Reader Service"
RUNTIME_MANIFEST_RELATIVE_PATH = "app/runtime-manifest.json"
RUNTIME_LOCK_RELATIVE_PATH = "packaging/windows/runtime-requirements.lock"

TEXT_SUFFIXES = frozenset(
    {
        ".bat",
        ".cfg",
        ".cmd",
        ".ini",
        ".json",
        ".lock",
        ".md",
        ".ps1",
        ".psm1",
        ".py",
        ".spec",
        ".toml",
        ".txt",
        ".yaml",
        ".yml",
    }
)
SCRIPT_SUFFIXES = frozenset({".bat", ".cmd", ".ps1", ".psm1", ".py", ".spec"})

WRITE_COMMANDS = (
    "Add-Content",
    "Clear-Content",
    "Copy-Item",
    "Move-Item",
    "New-Item",
    "Out-File",
    "Rename-Item",
    "Set-Content",
)
REMOVAL_COMMANDS = ("Remove-Item", "ri", "rm", "rd", "rmdir", "del", "erase")

_BLOCK_COMMENT = re.compile(r"<#.*?#>", re.DOTALL)
_TRIPLE_QUOTED = re.compile(r'""".*?"""|\'\'\'.*?\'\'\'', re.DOTALL)
_POWERSHELL_VARIABLE_ASSIGNMENT = re.compile(r"^\s*(?:\[[^\]]*\]\s*)*\$([A-Za-z_][A-Za-z0-9_]*)\s*=")
_PYTHON_ASSIGNMENT = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")
_RELEASE_ROOT_NAMES = re.compile(
    r"\b(?:dist_root|build_root|staging_root|generated_root|spec_scratch|wheel_root|artifact_root|venv_root|work_root)\b"
    r"|ensure_release_root|require_inside"
)
_FUNCTION_DEFINITION = re.compile(r"^\s*function\s+([A-Za-z_][\w-]*)", re.IGNORECASE)
_CONTAINMENT_PREDICATE = re.compile(r"StartsWith|IsPathRooted|relative_to|is_relative_to", re.IGNORECASE)


# --------------------------------------------------------------------------- 工作区发现


def layer_files() -> list[Path]:
    """发行层内的受版本控制候选文件（跳过 ``__pycache__`` 等本机状态）。"""

    if not RELEASE_LAYER.is_dir():
        return []
    return [path for path in sorted(RELEASE_LAYER.rglob("*")) if path.is_file() and "__pycache__" not in path.parts]


def layer_text_files() -> list[Path]:
    return [path for path in layer_files() if path.suffix.lower() in TEXT_SUFFIXES]


def layer_documents() -> list[tuple[Path, str]]:
    return [(path, path.read_text(encoding="utf-8", errors="replace")) for path in layer_text_files()]


def script_documents() -> list[tuple[Path, str]]:
    """只含可执行/构建定义文件：文档里的示例命令不算构建行为。"""

    return [(path, text) for path, text in layer_documents() if path.suffix.lower() in SCRIPT_SUFFIXES]


def layer_corpus() -> str:
    return "\n".join(text for _, text in layer_documents())


def document(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def all_specs() -> list[Path]:
    """发行层内全部 PyInstaller spec（P2-01 约定为 ``packaging/windows/pdf_reader.spec``）。"""

    return [path for path in sorted(RELEASE_LAYER.rglob("*.spec")) if path.is_file()]


def resolve_build_script() -> Path:
    """唯一正式本地构建入口，优先 ``packaging/windows/build.ps1``。"""

    preferred = RELEASE_LAYER / "build.ps1"
    if preferred.is_file():
        return preferred
    return _resolve_single(
        [path for path in RELEASE_LAYER.rglob("*.ps1") if path.is_file()],
        label="Windows 构建脚本",
        expected="packaging/windows/build.ps1",
    )


def _resolve_single(candidates: list[Path], *, label: str, expected: str) -> Path:
    if len(candidates) == 1:
        return candidates[0]
    found = ", ".join(path.relative_to(REPO_ROOT).as_posix() for path in candidates) or "<无>"
    raise AssertionError(f"P2-01 需要唯一的{label}（期望 {expected}）；当前发现：{found}")


def policy_module_paths() -> set[Path]:
    """已有策略门模块：检查“构建脚本做了什么”时不应把它们算成构建动作。"""

    return {RELEASE_LAYER / "runtime_policy.py", RELEASE_LAYER / "data_policy.py"}


def collect_spec_recordings(workdir: Path) -> list[SpecRecording]:
    return [run_spec(spec, workdir) for spec in all_specs()]


def merge_recordings(recordings: list[SpecRecording]) -> SpecRecording:
    """把多个 spec 的记录合并成一个视图（发行物是多个 spec 的并集）。"""

    if not recordings:
        raise AssertionError("发行层没有任何 spec 可执行")
    calls = [call for recording in recordings for call in recording.calls]
    return SpecRecording(recordings[0].path, calls, {})


def load_release_module(filename: str, module_name: str) -> types.ModuleType:
    """按文件路径加载发行层里的纯标准库辅助模块（policy/构建助手）。"""

    path = RELEASE_LAYER / filename
    assert path.is_file(), f"缺少发行层模块：{path.relative_to(REPO_ROOT).as_posix()}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None, f"无法加载 {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_STDLIB_OR_TOOL_MODULES = frozenset(
    {"pip", "pyinstaller", "pytest", "coverage", "mypy", "ruff", "venv", "build", "wheel", "setuptools"}
)
_helper_module_name: str | None = None


def build_helper_module_name() -> str:
    """build.ps1 调用的发行构建助手模块名（从构建脚本读取，而不是写死内部包名）。

    发行层可以用任何包名实现助手；这里以 ``build.ps1``/``build.sh`` 里的 ``-m <模块>``
    调用为唯一契约来源。若找不到任何可导入候选，直接失败——构建助手是 P2-01 的必需
    组成部分，不能以“模块可能改名”为由跳过行为验证。
    """

    global _helper_module_name
    if _helper_module_name is not None:
        return _helper_module_name
    candidates: list[str] = []
    for _, text in script_documents():
        for pattern in (r"['\"]-m['\"]\s*,\s*['\"]([A-Za-z_][\w.]*)['\"]", r"(?<![\w-])-m\s+([A-Za-z_][\w.]*)"):
            candidates.extend(re.findall(pattern, strip_comments(text)))
    ordered = [name for name in candidates if name.split(".")[0].lower() not in _STDLIB_OR_TOOL_MODULES]
    ordered += [path.name for path in sorted(RELEASE_LAYER.glob("*/__init__.py")) if path.parent.name not in candidates]
    for name in ordered:
        package = RELEASE_LAYER / name.split(".")[0]
        if (package / "__init__.py").is_file():
            _helper_module_name = name
            return name
    available = sorted(path.name for path in RELEASE_LAYER.iterdir() if path.is_dir())
    raise AssertionError(
        "构建脚本必须通过 -m 调用 packaging/windows 内的发行构建助手包；"
        f"当前候选：{sorted(set(candidates)) or '<无>'}，可用目录：{available}"
    )


def run_build_helper(
    *arguments: str,
    repo_root: Path | None = None,
    cwd: Path | None = None,
    timeout: int = 600,
) -> subprocess.CompletedProcess[str]:
    """按 build.ps1 的方式调用构建助手 CLI：``PYTHONPATH=packaging/windows python -m <helper> ...``。"""

    command = [sys.executable, "-m", build_helper_module_name()]
    if repo_root is not None:
        command += ["--repo-root", str(repo_root)]
    command += list(arguments)
    environment = {**os.environ, "PYTHONPATH": str(RELEASE_LAYER), "PYTHONIOENCODING": "utf-8"}
    environment.pop("PDF_READER_SELF_CHECK_DIR", None)
    return subprocess.run(
        command,
        cwd=str(cwd or REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        check=False,
        timeout=timeout,
    )


def tracked_layer_paths() -> set[str]:
    """``packaging/windows`` 下受 Git 跟踪的相对路径；无 Git 时跳过调用方断言。"""

    tracked = git_lines("ls-files", "packaging/windows")
    if tracked is None:
        pytest.skip("需要可用的 git 工作区")
    return set(tracked)


def tracked_repository_paths() -> list[str]:
    tracked = git_lines("ls-files")
    if tracked is None:
        pytest.skip("需要可用的 git 工作区")
    return tracked


def git_ignored(relative_path: str) -> bool | None:
    """``git check-ignore -q`` 的布尔结果；无 Git 时返回 ``None``。"""

    try:
        result = subprocess.run(
            ["git", "check-ignore", "-q", relative_path],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode not in (0, 1):
        return None
    return result.returncode == 0


def git_lines(*arguments: str) -> list[str] | None:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return [line for line in result.stdout.splitlines() if line.strip()]


# --------------------------------------------------------------------------- 文本与作用域


def normalize_separators(text: str) -> str:
    return text.replace("\\", "/")


def strip_comments(text: str) -> str:
    """移除注释与 Python 文档字符串，避免说明文字里的命令被当成构建行为。"""

    without_blocks = _BLOCK_COMMENT.sub("", text)
    without_strings = _TRIPLE_QUOTED.sub("", without_blocks)
    return "\n".join("" if line.lstrip().startswith("#") else line for line in without_strings.splitlines())


def _logical_lines(text: str) -> list[str]:
    """把 PowerShell 反引号续行合并成逻辑行，供变量赋值分析使用。"""

    logical: list[str] = []
    pending = ""
    for line in text.splitlines():
        current = f"{pending}\n{line}" if pending else line
        if line.rstrip().endswith("`"):
            pending = current
            continue
        logical.append(current)
        pending = ""
    if pending:
        logical.append(pending)
    return logical


def release_scoped_variables(text: str) -> frozenset[str]:
    """以 ``release-windows`` 字面量为根、沿赋值关系传播的“位于发行边界内”变量集合。

    传播有三条边：赋值表达式引用已判定变量；赋值的来源是层内定义的“验证型函数”
    （函数体自带 StartsWith/IsPathRooted 之类的发行目录包含性检查）；或 Python 侧赋值自
    build/dist/staging/artifact 等构建计划根（含 ensure_release_root/require_inside）。
    """

    assignments: list[tuple[str, str]] = []
    for line in _logical_lines(strip_comments(text)):
        match = _POWERSHELL_VARIABLE_ASSIGNMENT.match(line)
        if match:
            assignments.append((match.group(1), line))
        python = _PYTHON_ASSIGNMENT.match(line)
        if python:
            assignments.append((python.group(1), python.group(2)))
    scoped = {
        name
        for name, expression in assignments
        if "release-windows" in expression or _RELEASE_ROOT_NAMES.search(expression)
    }
    validating = _validating_functions(text)
    changed = True
    while changed:
        changed = False
        for name, expression in assignments:
            if name in scoped:
                continue
            references_scoped = any(
                re.search(rf"\${re.escape(other)}\b", expression, flags=re.IGNORECASE) for other in scoped
            )
            if references_scoped or (_assignment_call_names(expression) & validating):
                scoped.add(name)
                changed = True
    return frozenset(scoped)


def _validating_functions(text: str) -> frozenset[str]:
    """层内定义的验证型函数名（函数体包含发行目录包含性检查）。"""

    lines = strip_comments(text).splitlines()
    validating: set[str] = set()
    index = 0
    while index < len(lines):
        match = _FUNCTION_DEFINITION.match(lines[index])
        index += 1
        if not match:
            continue
        body: list[str] = []
        while index < len(lines) and not lines[index].startswith("}"):
            body.append(lines[index])
            index += 1
        if _CONTAINMENT_PREDICATE.search("\n".join(body)):
            validating.add(match.group(1).lower())
    return frozenset(validating)


def _assignment_call_names(expression: str) -> set[str]:
    """赋值表达式里出现的调用名（``Cmdlet (...)`` 与 ``Cmdlet 参数`` 两种写法）。"""

    names = {name.lower() for name in re.findall(r"([A-Za-z_][\w-]*)\s*\(", expression)}
    head = re.search(r"=\s*([A-Za-z_][\w-]*)", expression)
    if head:
        names.add(head.group(1).lower())
    return names


def layer_scoped_variables() -> frozenset[str]:
    """整层语料的发行边界变量：容忍被 dot-source 的 .psm1 与主脚本之间的变量传递。"""

    return release_scoped_variables(layer_corpus())


def release_scoped_window(window: str, *scopes: frozenset[str]) -> bool:
    """窗口是否指向发行构建目录：出现字面量或出现发行边界内的变量。"""

    if "release-windows" in normalize_separators(window):
        return True
    return any(
        re.search(rf"\$?\b{re.escape(name)}\b", window, flags=re.IGNORECASE) for scope in scopes for name in scope
    )


def command_windows(text: str, commands: tuple[str, ...], *, lookback: int = 4) -> list[tuple[str, str, str]]:
    """（命令, 命令行, 语句上下文）列表；命令匹配大小写不敏感，且不匹配更长标识符的一部分。

    上下文 = 命令所在逻辑行 + 之前 ``lookback`` 行：既要看命令自己的目标表达式，也要
    容忍紧邻的包含性守卫（``if (-not ($resolved.StartsWith($DistRoot))) { throw }``）。
    文档/注释/字符串里的命令不算构建行为。
    """

    pattern = re.compile(
        r"(?<![\w$-])(?:" + "|".join(re.escape(command) for command in commands) + r")\b", re.IGNORECASE
    )
    lines = _logical_lines(strip_comments(text))
    results: list[tuple[str, str, str]] = []
    for index, line in enumerate(lines):
        for match in pattern.finditer(line):
            start = max(0, index - lookback)
            context = "\n".join(lines[start : index + 1])
            results.append((match.group(0), line, context))
    return results


def guarded_command_ok(path: Path, line: str, context: str, corpus_scope: frozenset[str] | None = None) -> bool:
    """命令的目标要么本身在发行边界内，要么紧邻的包含性守卫证明它被验证过。

    守卫必须针对命令真正操作的那个变量（``$resolved`` 的检查不能替 ``$safe`` 背书），
    且守卫自身必须引用发行边界内的根，否则删除范围可能被悄悄扩大。
    """

    if window_scope_ok(path, line, corpus_scope):
        return True
    layer_scope = layer_scoped_variables() if corpus_scope is None else corpus_scope
    scopes = (release_scoped_variables(document(path)), layer_scope)
    command_variables = set(re.findall(r"\$([A-Za-z_][A-Za-z0-9_]*)", line))
    if not command_variables:
        return False
    for predicate in context.splitlines():
        if not _CONTAINMENT_PREDICATE.search(predicate) or not _scope_evidence(predicate, scopes):
            continue
        if any(re.search(rf"\${re.escape(name)}\b", predicate) for name in command_variables):
            return True
    return False


def logical_lines_containing(token: str, *, build_only: bool = False) -> list[tuple[Path, str]]:
    """包含 token 的逻辑行（反引号续行合并、注释移除），返回（文件, 行文本）。"""

    documents = build_documents() if build_only else script_documents()
    results: list[tuple[Path, str]] = []
    for path, text in documents:
        for line in _logical_lines(strip_comments(text)):
            if re.search(re.escape(token), line, flags=re.IGNORECASE):
                results.append((path, line))
    return results


def logical_line_contexts(token: str, *, build_only: bool = False, lookback: int = 4) -> list[tuple[Path, str, str]]:
    """包含 token 的逻辑行及其前 ``lookback`` 行（容忍 PowerShell 续行/参数换行）。"""

    documents = build_documents() if build_only else script_documents()
    results: list[tuple[Path, str, str]] = []
    for path, text in documents:
        lines = _logical_lines(strip_comments(text))
        for index, line in enumerate(lines):
            if not re.search(re.escape(token), line, flags=re.IGNORECASE):
                continue
            results.append((path, line, "\n".join(lines[max(0, index - lookback) : index + 1])))
    return results


def powershell_functions() -> dict[str, str]:
    """PowerShell 函数名（小写）→ 函数体，用于分析失败传播与路径验证结构。"""

    functions: dict[str, str] = {}
    for _, text in script_documents():
        lines = strip_comments(text).splitlines()
        index = 0
        while index < len(lines):
            match = _FUNCTION_DEFINITION.match(lines[index])
            index += 1
            if not match:
                continue
            body: list[str] = []
            while index < len(lines) and not lines[index].startswith("}"):
                body.append(lines[index])
                index += 1
            functions[match.group(1).lower()] = "\n".join(body)
    return functions


def checked_invokers() -> frozenset[str]:
    """失败会让构建中止的调用入口（检查子进程退出码并抛错，或被这样的入口调用）。"""

    functions = powershell_functions()
    invokers = {name for name, body in functions.items() if "LASTEXITCODE" in body and re.search(r"\bthrow\b", body)}
    changed = True
    while changed:
        changed = False
        for name, body in functions.items():
            if name in invokers:
                continue
            if any(re.search(rf"(?i)(?<![\w-]){re.escape(other)}\b", body) for other in invokers):
                invokers.add(name)
                changed = True
    return frozenset(invokers)


def argument_lines_containing(token: str, *, build_only: bool = True) -> list[tuple[Path, str]]:
    """命令行开关 token 之后到逻辑行结束的实参文本，用于判断该参数指向哪里。"""

    results: list[tuple[Path, str]] = []
    for path, line in logical_lines_containing(token, build_only=build_only):
        results.append((path, re.split(re.escape(token), line, flags=re.IGNORECASE)[-1]))
    return results


def build_documents() -> list[tuple[Path, str]]:
    """构建定义文件：排除既有策略门模块（它们不是构建动作，只是被调用的门）。"""

    policy = policy_module_paths()
    return [(path, text) for path, text in script_documents() if path not in policy]


def orchestration_documents() -> list[tuple[Path, str]]:
    """构建编排脚本（``build.ps1``/``build.sh``）：不含被它调用的助手包与策略门实现。"""

    helper_root = RELEASE_LAYER / build_helper_module_name().split(".")[0]
    policy = policy_module_paths()
    return [(path, text) for path, text in script_documents() if path not in policy and helper_root not in path.parents]


def window_scope_ok(path: Path, window: str, corpus_scope: frozenset[str] | None = None) -> bool:
    """窗口是否只作用于发行构建目录。

    接受两类证据：目标由发行边界内的变量表达；或目标由包含性检查守卫
    （``if (-not ($resolved.Path.StartsWith($DistRoot))) { throw }``），且窗口同时引用
    发行边界内的变量。变量/命名参数会做一层数据流追踪，因此 ``--workpath $WorkPath``
    只要调用点传入的是发行目录，也算有证据。
    """

    layer_scope = layer_scoped_variables() if corpus_scope is None else corpus_scope
    text = document(path)
    scopes = (release_scoped_variables(text), layer_scope)
    if _scope_evidence(window, scopes):
        return True
    for name in set(re.findall(r"\$([A-Za-z_][A-Za-z0-9_]*)", window)):
        if any(_scope_evidence(binding, scopes) for binding in variable_bindings(text, name)):
            return True
    return False


def _scope_evidence(text: str, scopes: tuple[frozenset[str], ...]) -> bool:
    if release_scoped_window(text, *scopes):
        return True
    references_scoped = any(
        re.search(rf"\$?\b{re.escape(name)}\b", text, flags=re.IGNORECASE) for scope in scopes for name in scope
    )
    return bool(references_scoped and _CONTAINMENT_PREDICATE.search(text))


def variable_bindings(text: str, name: str) -> list[str]:
    """变量名的赋值右侧与命名参数绑定右侧（用于一层数据流追踪）。"""

    cleaned = strip_comments(text)
    bindings = re.findall(
        rf"^\s*(?:\[[^\]]*\]\s*)*\${re.escape(name)}\s*=\s*(.*)$", cleaned, flags=re.MULTILINE | re.IGNORECASE
    )
    bindings += re.findall(rf"(?i)(?<![\w-])-{re.escape(name)}\s+([^\r\n]*)", cleaned)
    return bindings


def write_command_windows(text: str) -> list[tuple[str, str]]:
    return command_windows(text, WRITE_COMMANDS + REMOVAL_COMMANDS)


def removal_command_windows(text: str) -> list[tuple[str, str]]:
    return command_windows(text, REMOVAL_COMMANDS)


def path_parts(path_text: str) -> tuple[str, ...]:
    return tuple(part for part in normalize_separators(path_text).split("/") if part)


def has_path_component(path_text: str, name: str) -> bool:
    return name in path_parts(path_text)


def mentions_app_directory(text: str) -> bool:
    """文本是否把服务 EXE 指向 app/ 私有运行时目录。"""

    normalized = normalize_separators(text)
    return bool(re.search(r"(?:['\"]app['\"]|app/|APP_DIRECTORY)", normalized))


def string_items(value: Any) -> list[str]:
    """把（可能嵌套的）字符串序列扁平化为字符串列表。"""

    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set, frozenset)):
        items: list[str] = []
        for entry in value:
            items.extend(string_items(entry))
        return items
    return []


# --------------------------------------------------------------------------- spec 桩执行


@dataclass
class StubCall:
    """一次桩 PyInstaller 调用。"""

    target: str
    args: tuple[Any, ...]
    kwargs: dict[str, Any]


@dataclass
class SpecRecording:
    """在桩 PyInstaller 下执行 spec 的完整记录。"""

    path: Path
    calls: list[StubCall]
    namespace: dict[str, Any]

    def calls_named(self, leaf: str) -> list[StubCall]:
        return [call for call in self.calls if call.target.rsplit(".", 1)[-1] == leaf]


class _StubAnything:
    """未知 PyInstaller 对象/函数的占位：记录调用并返回最小可用结果。"""

    def __init__(self, target: str, log: list[StubCall]) -> None:
        self.target = target
        self.log = log

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.log.append(StubCall(self.target, args, kwargs))
        return _stub_return(self.target, args, self.log)

    def __getattr__(self, item: str) -> Any:
        if item.startswith("_"):
            raise AttributeError(item)
        return _StubAnything(f"{self.target}.{item}", self.log)

    def __bool__(self) -> bool:
        return True

    def __iter__(self) -> Iterator[Any]:
        return iter(())

    def __len__(self) -> int:
        return 0

    def __repr__(self) -> str:
        return f"<PyInstaller stub {self.target}>"


class _StubPayload:
    """Analysis/EXE/COLLECT 结果的占位：序列属性为空，其余属性继续是桩。"""

    SEQUENCE_ATTRIBUTES = frozenset(
        {"pure", "zipped_data", "zipfiles", "datas", "binaries", "scripts", "toc", "pure_module_names"}
    )

    def __init__(self, target: str, log: list[StubCall]) -> None:
        self.target = target
        self.log = log

    def __getattr__(self, item: str) -> Any:
        if item.startswith("_"):
            raise AttributeError(item)
        if item in _StubPayload.SEQUENCE_ATTRIBUTES:
            return []
        return _StubAnything(f"{self.target}.{item}", self.log)

    def __repr__(self) -> str:
        return f"<PyInstaller stub payload {self.target}>"


class _StubModule(types.ModuleType):
    def __init__(self, name: str, log: list[StubCall]) -> None:
        super().__init__(name)
        self.stub_log = log

    def __getattr__(self, item: str) -> Any:
        if item.startswith("_"):
            raise AttributeError(item)
        return _StubAnything(f"{self.__name__}.{item}", self.stub_log)


_STUB_MODULE_NAMES = (
    "PyInstaller",
    "PyInstaller.building",
    "PyInstaller.building.api",
    "PyInstaller.building.build_main",
    "PyInstaller.building.datastruct",
    "PyInstaller.building.toc_conversion",
    "PyInstaller.compat",
    "PyInstaller.config",
    "PyInstaller.utils",
    "PyInstaller.utils.hooks",
    "PyInstaller.utils.misc",
)

_SPEC_INJECTED_NAMES = (
    "Analysis",
    "BUNDLE",
    "COLLECT",
    "EXE",
    "MERGE",
    "PYZ",
    "Splash",
    "TOC",
    "Tree",
    "add_data",
)


def _stub_modules(log: list[StubCall]) -> dict[str, types.ModuleType]:
    modules: dict[str, types.ModuleType] = {}
    for name in _STUB_MODULE_NAMES:
        module = _StubModule(name, log)
        if "." in name:
            parent_name, child_name = name.rsplit(".", 1)
            setattr(modules[parent_name], child_name, module)
        modules[name] = module
    return modules


def _stub_return(target: str, args: tuple[Any, ...], log: list[StubCall]) -> Any:
    leaf = target.rsplit(".", 1)[-1]
    package = next((argument for argument in args if isinstance(argument, str)), "")
    if leaf == "collect_data_files":
        return [(f"__stub__/{package}/data.bin", package or ".")]
    if leaf == "collect_submodules":
        return [f"{package}.__stub__"] if package else []
    if leaf == "collect_dynamic_libs":
        return [(f"__stub__/{package}/native.dll", ".")]
    if leaf == "collect_all":
        return (
            [(f"__stub__/{package}/data.bin", package or ".")],
            [(f"__stub__/{package}/native.dll", ".")],
            [f"{package}.__stub__"] if package else [],
        )
    if leaf == "Analysis":
        return _StubPayload(target, log)
    if leaf in {"COLLECT", "EXE", "PYZ", "BUNDLE", "MERGE", "TOC", "Tree"}:
        return _StubPayload(target, log)
    return []


def _module_in_release_layer(module: Any) -> bool:
    filename = getattr(module, "__file__", None)
    if not isinstance(filename, str) or not filename:
        return False
    try:
        return Path(filename).resolve().is_relative_to(RELEASE_LAYER.resolve())
    except (OSError, ValueError):
        return False


def run_spec(spec_path: Path, workdir: Path | None = None) -> SpecRecording:
    """在桩 PyInstaller API 下执行 spec；不安装、不运行真实 PyInstaller。"""

    log: list[StubCall] = []
    stubs = _stub_modules(log)
    saved_modules: dict[str, types.ModuleType | None] = {name: sys.modules.get(name) for name in stubs}
    saved_release_modules = {name for name, module in sys.modules.items() if _module_in_release_layer(module)}
    saved_path = list(sys.path)
    temporary = tempfile.TemporaryDirectory(prefix="pdf-reader-spec-") if workdir is None else None
    working_directory = Path(temporary.name) if temporary is not None else Path(workdir)
    working_directory.mkdir(parents=True, exist_ok=True)
    previous_cwd = Path.cwd()
    namespace: dict[str, Any] = {
        "__file__": str(spec_path),
        "__name__": "pdf_reader_onedir_spec",
        "SPEC": str(spec_path),
        "SPECPATH": str(spec_path.parent),
        "DISTPATH": str(working_directory / "dist"),
        "WORKPATH": str(working_directory / "build"),
        "HOMEPATH": str(working_directory / "home"),
        "WARNFILE": str(working_directory / "warn.txt"),
    }
    for name in _SPEC_INJECTED_NAMES:
        namespace[name] = _StubAnything(f"PyInstaller.building.api.{name}", log)
    for name, module in stubs.items():
        sys.modules[name] = module
    try:
        sys.path.insert(0, str(spec_path.parent))
        sys.path.insert(0, str(REPO_ROOT))
        os.chdir(working_directory)
        code = compile(spec_path.read_text(encoding="utf-8"), str(spec_path), "exec")
        exec(code, namespace)  # noqa: S102 - 只执行受版本控制的 spec，且 PyInstaller API 全部是桩
    except Exception as exc:  # noqa: BLE001 - 统一转成契约失败信息，保留原始 traceback
        raise AssertionError(f"spec 无法在桩 PyInstaller 下执行：{exc!r}") from exc
    finally:
        os.chdir(previous_cwd)
        sys.path[:] = saved_path
        for name, module in saved_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
        for name in [name for name, module in sys.modules.items() if _module_in_release_layer(module)]:
            if name not in saved_release_modules:
                sys.modules.pop(name, None)
        if temporary is not None:
            temporary.cleanup()
    return SpecRecording(spec_path, log, namespace)


def analysis_options(recording: SpecRecording, option: str, positional_index: int | None = None) -> list[Any]:
    values: list[Any] = []
    for call in recording.calls_named("Analysis"):
        if option in call.kwargs:
            values.append(call.kwargs[option])
        elif positional_index is not None and len(call.args) > positional_index:
            values.append(call.args[positional_index])
    return values


def _pair_items(value: Any) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    if isinstance(value, (list, tuple)):
        for entry in value:
            if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                source, destination = entry[0], entry[1]
                if isinstance(source, str) and isinstance(destination, str):
                    pairs.append((source, destination))
    return pairs


def analysis_datas(recording: SpecRecording) -> list[tuple[str, str]]:
    return [pair for value in analysis_options(recording, "datas", 3) for pair in _pair_items(value)]


def analysis_binaries(recording: SpecRecording) -> list[tuple[str, str]]:
    return [pair for value in analysis_options(recording, "binaries", 2) for pair in _pair_items(value)]


def analysis_hiddenimports(recording: SpecRecording) -> set[str]:
    return {item for value in analysis_options(recording, "hiddenimports", 4) for item in string_items(value)}


def analysis_scripts(recording: SpecRecording) -> list[str]:
    scripts: list[str] = []
    for call in recording.calls_named("Analysis"):
        if call.args:
            scripts.extend(string_items(call.args[0]))
        else:
            scripts.extend(string_items(call.kwargs.get("scripts")))
    return scripts


def collected_targets(recording: SpecRecording) -> dict[str, set[str]]:
    """``collect_*`` 调用 → 目标包/模块名。"""

    targets: dict[str, set[str]] = {}
    for call in recording.calls:
        leaf = call.target.rsplit(".", 1)[-1]
        if not leaf.startswith("collect_"):
            continue
        targets.setdefault(leaf, set()).update(argument for argument in call.args if isinstance(argument, str))
    return targets


def collected_package_names(recording: SpecRecording) -> set[str]:
    return {name for names in collected_targets(recording).values() for name in names}


def tree_sources(recording: SpecRecording) -> set[str]:
    sources: set[str] = set()
    for call in recording.calls_named("Tree"):
        if call.args and isinstance(call.args[0], str):
            sources.add(call.args[0])
    return sources


def exe_excludes_binaries(call: StubCall) -> bool:
    """onedir 判定：EXE 必须 ``exclude_binaries=True``，由 COLLECT 汇总目录内容。"""

    if "exclude_binaries" in call.kwargs:
        return bool(call.kwargs["exclude_binaries"])
    binaries = call.kwargs.get("binaries")
    if binaries is None and len(call.args) > 2:
        binaries = call.args[2]
    return not binaries


def executable_stem(name: Any) -> str:
    if not isinstance(name, str):
        return ""
    return name[:-4] if name.lower().endswith(".exe") else name
