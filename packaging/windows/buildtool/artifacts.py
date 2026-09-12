"""The onedir artifact contract: tree shape, file inventory, SHA-256 and ZIP output.

Nothing here trusts the packager: the expected tree is verified after PyInstaller
runs, the inventory hashes every shipped file, and the ZIP is written with fixed
timestamps so the same inputs produce the same entry metadata.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .layout import APP_DIRECTORY, INTERNAL_DIRECTORY, LAUNCHER_EXECUTABLE, SERVICE_EXECUTABLE

REQUIRED_APP_FILES: tuple[str, ...] = (
    f"{APP_DIRECTORY}/{INTERNAL_DIRECTORY}",
    f"{APP_DIRECTORY}/static/app.js",
    f"{APP_DIRECTORY}/static/style.css",
    f"{APP_DIRECTORY}/static/modules",
    f"{APP_DIRECTORY}/templates/index.html",
    f"{APP_DIRECTORY}/config.example.toml",
    f"{APP_DIRECTORY}/licenses/LICENSE",
    f"{APP_DIRECTORY}/licenses/DEPENDENCIES.txt",
    f"{APP_DIRECTORY}/runtime-manifest.json",
    f"{APP_DIRECTORY}/release-manifest.json",
)
# 顶层启动器的私有运行时目录；服务自己的 _internal 由上面的 app/_internal 覆盖。
REQUIRED_ROOT_DIRECTORIES: tuple[str, ...] = (INTERNAL_DIRECTORY,)
# 两类校验产物只写入 dist/release-windows：filelist（sha256sum 格式，逐文件清单）与 ZIP
# 校验和。名称集中在这里，构建脚本不再各自拼字符串。
FILELIST_SUFFIX = ".files.sha256"  # dist/release-windows/<artifact>.files.sha256（发行文件清单）
CHECKSUM_SUFFIX = ".sha256"  # dist/release-windows/<zip>.sha256（便携 ZIP 校验和）
FORBIDDEN_TOP_LEVEL_NAMES: tuple[str, ...] = (
    ".git",
    ".venv",
    "__pycache__",
    "node_modules",
    "venv",
)
FORBIDDEN_ANYWHERE_NAMES: tuple[str, ...] = (
    "config.toml",
    "portable-data.json",
    "instance.json",
    "launcher.log",
    "migrations.log",
    ".coverage",
)
FORBIDDEN_SUFFIXES: tuple[str, ...] = (".pyc", ".pyo", ".pdb", ".log")
FORBIDDEN_DEVELOPER_MARKERS: tuple[str, ...] = ("\\projects\\PDF_reader", "\\venv\\", "/venv/bin/")
# 构建机路径与密钥材料都必须能在发行物里被扫出来。模式写成字符类而不是字面量，避免发行层
# 自身携带“看起来像本机路径”的样例字符串。
DEVELOPER_PATH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"[A-Za-z]:[\\/]{1,2}Users[\\/]", re.IGNORECASE),
    re.compile(r"/(?:home|Users)/[A-Za-z0-9_.-]+/"),
    re.compile(r"[\\/]PDF_reader[\\/]venv[\\/]", re.IGNORECASE),
)
# 只匹配“像真实凭据”的字面量：前端配置面板里会出现 api_key 字段名，而字段名不是秘密，
# 只有形如 sk-… / Bearer … 的取值才是发行物绝不允许携带的内容。规则与
# ``scripts/secret_scan.py`` 保持一致，并同样放行占位示例值，避免把
# ``config.example.toml`` 里的说明书样例误判成泄露。
PLACEHOLDER_TOKENS: tuple[str, ...] = (
    "your",
    "example",
    "placeholder",
    "xxx",
    "demo",
    "dummy",
    "test",
    "redacted",
    "replace",
    "todo",
    "…",
    "<",
    ">",
    "此处",
    "密钥",
)
SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openai_style_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("bearer_token", re.compile(r"\bbearer\s+[A-Za-z0-9._~+/=-]{20,}", re.IGNORECASE)),
    (
        "api_key_assignment",
        re.compile(
            r"\b(?:api[_-]?key|apikey|secret|access[_-]?token)\b\s*[:=]\s*[\"']?[A-Za-z0-9_./+=-]{24,}",
            re.IGNORECASE,
        ),
    ),
)
# 只扫描本仓库自有文本；第三方包自带的文档/测试数据可能出现任意字符串，逐字节扫描既不
# 必要也会产生误报。本程序自有文本泄露构建机路径才是 P2-01 要拦住的失败。
LEAK_SCAN_PREFIXES: tuple[str, ...] = (f"{APP_DIRECTORY}/",)
LEAK_SCAN_EXCLUDED_DIRECTORIES: tuple[str, ...] = (
    f"{APP_DIRECTORY}/{INTERNAL_DIRECTORY}",
    f"{APP_DIRECTORY}/licenses",
)
TEXT_SUFFIXES: tuple[str, ...] = (
    ".py",
    ".txt",
    ".md",
    ".json",
    ".toml",
    ".cfg",
    ".ini",
    ".yml",
    ".yaml",
    ".html",
    ".js",
    ".css",
    ".map",
)


class ArtifactError(RuntimeError):
    """The assembled artifact violates the release contract."""


@dataclass(frozen=True, slots=True)
class InventoryEntry:
    path: str
    size: int
    sha256: str


def iter_files(root: Path) -> list[Path]:
    return sorted((path for path in Path(root).rglob("*") if path.is_file()), key=lambda p: p.as_posix())


def inventory(root: Path) -> tuple[list[InventoryEntry], int]:
    """Hash every shipped file; returns the entries and the total byte count."""

    base = Path(root)
    entries: list[InventoryEntry] = []
    total = 0
    for path in iter_files(base):
        digest = hashlib.new("sha256")
        size = 0
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
        entries.append(InventoryEntry(path=path.relative_to(base).as_posix(), size=size, sha256=digest.hexdigest()))
        total += size
    return entries, total


def write_inventory(path: Path, entries: list[InventoryEntry]) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        "".join(f"{entry.sha256}  {entry.path}\n" for entry in entries),
        encoding="utf-8",
        newline="\n",
    )
    return destination


def inventory_payload(entries: list[InventoryEntry], total_bytes: int, *, hash_prefix: int = 16) -> dict[str, object]:
    return {
        "file_count": len(entries),
        "total_bytes": total_bytes,
        "files": [{"path": entry.path, "size": entry.size, "sha256": entry.sha256[:hash_prefix]} for entry in entries],
    }


def verify_tree(root: Path) -> list[str]:
    """Verify the required artifact shape and the forbidden-content denylist."""

    base = Path(root)
    violations: list[str] = []
    if not base.is_dir():
        return [f"artifact root is not a directory: {base}"]
    if not (base / LAUNCHER_EXECUTABLE).is_file():
        violations.append(f"artifact is missing the top-level launcher: {LAUNCHER_EXECUTABLE}")
    if not (base / APP_DIRECTORY / SERVICE_EXECUTABLE).is_file():
        violations.append(f"artifact is missing the private service: {APP_DIRECTORY}/{SERVICE_EXECUTABLE}")
    extra_executables = [
        path.relative_to(base).as_posix() for path in base.glob("*.exe") if path.name != LAUNCHER_EXECUTABLE
    ]
    if extra_executables:
        violations.append(f"artifact exposes additional top-level executables: {', '.join(extra_executables)}")
    for relative in REQUIRED_ROOT_DIRECTORIES:
        if not (base / relative).is_dir():
            violations.append(f"artifact is missing the launcher runtime directory: {relative}")
    for relative in REQUIRED_APP_FILES:
        candidate = base / relative
        if candidate.is_dir():
            continue
        if candidate.is_file():
            continue
        violations.append(f"artifact is missing a required entry: {relative}")
    for entry in sorted(base.iterdir()):
        if entry.name in FORBIDDEN_TOP_LEVEL_NAMES:
            violations.append(f"artifact contains a development directory: {entry.name}")
    for path in sorted(base.rglob("*")):
        relative = path.relative_to(base).as_posix()
        if path.is_dir():
            if _is_linky(path):
                violations.append(f"artifact directory must not be a link: {relative}")
            continue
        if _is_linky(path):
            violations.append(f"artifact file must not be a link: {relative}")
            continue
        if path.name in FORBIDDEN_ANYWHERE_NAMES:
            violations.append(f"artifact ships user or development data: {relative}")
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            violations.append(f"artifact ships a non-release file type: {relative}")
    violations.extend(_scan_text_leaks(base))
    return violations


def _is_linky(path: Path) -> bool:
    if path.is_symlink():
        return True
    if os.name == "nt":
        try:
            return path.is_junction()
        except AttributeError:  # pragma: no cover - only older interpreters
            return False
    return False


def _scan_text_leaks(base: Path) -> list[str]:
    """Fail when a shipped text asset still names the build machine or the dev repo."""

    violations: list[str] = []
    for path in iter_files(base):
        relative = path.relative_to(base).as_posix()
        if not relative.startswith(LEAK_SCAN_PREFIXES):
            continue
        if any(relative == prefix or relative.startswith(f"{prefix}/") for prefix in LEAK_SCAN_EXCLUDED_DIRECTORIES):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for marker in FORBIDDEN_DEVELOPER_MARKERS:
            if marker in text:
                violations.append(f"artifact leaks a build-machine path marker {marker!r}: {relative}")
        for pattern in DEVELOPER_PATH_PATTERNS:
            match = pattern.search(text)
            if match:
                violations.append(f"artifact leaks a developer path {match.group(0)!r}: {relative}")
        for rule, pattern in SECRET_PATTERNS:
            match = pattern.search(text)
            if match and not _is_placeholder(match.group(0)):
                # 只报告文件与规则名：命中的内容本身可能是凭据，不能进日志或报告。
                violations.append(f"artifact contains credential-like material ({rule}): {relative}")
    return violations


def _is_placeholder(value: str) -> bool:
    """说明书里的示例值不是密钥；判定口径与 ``scripts/secret_scan.py`` 相同。"""

    lowered = value.lower()
    return any(token in lowered for token in PLACEHOLDER_TOKENS)


def write_zip(artifact_root: Path, zip_path: Path, folder_name: str) -> Path:
    """Write the release ZIP with a single versioned root folder and fixed metadata."""

    base = Path(artifact_root)
    destination = Path(zip_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    files = iter_files(base)
    if not files:
        raise ArtifactError(f"refusing to write an empty release ZIP from {base}")
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            relative = path.relative_to(base).as_posix()
            info = zipfile.ZipInfo(filename=f"{folder_name}/{relative}", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())
    return destination


def sha256_file(path: Path) -> str:
    digest = hashlib.new("sha256")
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_zip_checksum(zip_path: Path, checksum_path: Path) -> tuple[str, Path]:
    digest = sha256_file(zip_path)
    destination = Path(checksum_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(f"{digest}  {Path(zip_path).name}\n", encoding="utf-8", newline="\n")
    return digest, destination


def write_json(path: Path, payload: dict[str, object]) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return destination
