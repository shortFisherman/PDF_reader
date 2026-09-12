"""Prove which locked distributions really landed inside the frozen onedir tree.

PyInstaller reports warnings but still exits successfully when an optional import
disappears, so the packager needs its own evidence.  This module indexes the build
venv's installed distributions (``RECORD`` files and ``top_level.txt``) and then
checks the assembled ``app/_internal`` tree for the top-level modules those
distributions provide.  A distribution whose modules are missing in the artifact and
was not deliberately excluded is a build failure, not a warning.
"""

from __future__ import annotations

import importlib.metadata as importlib_metadata
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from .lock import LockError, normalize_distribution

INDEX_SCHEMA = 1
_MODULE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(slots=True)
class DistributionInfo:
    """One installed distribution as the build venv sees it."""

    name: str
    version: str
    top_level: tuple[str, ...] = ()
    file_count: int = 0
    byte_count: int = 0

    def as_payload(self) -> dict[str, object]:
        return {
            "name": self.name,
            "version": self.version,
            "top_level": list(self.top_level),
            "file_count": self.file_count,
            "byte_count": self.byte_count,
        }


@dataclass(slots=True)
class CoverageResult:
    """Outcome of checking one distribution against the frozen artifact tree."""

    name: str
    top_level: tuple[str, ...]
    present: tuple[str, ...] = ()
    absent: tuple[str, ...] = ()
    files: int = 0
    bytes: int = 0
    metadata: tuple[str, ...] = ()


def metadata_directories(internal_root: Path, name: str) -> tuple[str, ...]:
    """Locate a distribution's ``*.dist-info`` directory inside the frozen tree."""

    root = Path(internal_root)
    candidates = {
        normalize_distribution(path.name[: -len(".dist-info")].rsplit("-", 1)[0]) for path in root.glob("*.dist-info")
    }
    return (f"{name}.dist-info",) if name in candidates else ()


def _site_packages() -> Path:
    for entry in sys.path:
        candidate = Path(entry) / "site-packages"
        if candidate.is_dir():
            return candidate
    raise LockError("cannot locate the build venv site-packages directory")


def _top_level_from_record(dist: importlib_metadata.Distribution) -> tuple[str, ...]:
    names: set[str] = set()
    try:
        files = dist.files or []
    except Exception:  # noqa: BLE001 - a damaged RECORD must not abort the whole build
        files = []
    for entry in files:
        first = str(entry).replace("\\", "/").split("/", 1)[0]
        if first.endswith(".dist-info") or first.endswith(".data"):
            continue
        stem = first.rsplit(".", 1)[0] if "." in first else first
        if _MODULE_NAME.fullmatch(stem) and not first.endswith((".pth", ".txt", ".md")):
            names.add(stem)
    return tuple(sorted(names))


def collect_installed_distributions() -> dict[str, DistributionInfo]:
    """Index every installed distribution in the running build environment.

    Top-level names come from ``top_level.txt`` when present and from the wheel
    ``RECORD`` otherwise; the file/byte totals describe the source footprint so the
    manifest can record what was considered, not only what was copied.
    """

    site = _site_packages()
    index: dict[str, DistributionInfo] = {}
    for dist in importlib_metadata.distributions():
        raw_name = dist.metadata["Name"]
        if not raw_name:
            continue
        name = normalize_distribution(raw_name)
        info = DistributionInfo(name=name, version=dist.version)
        files = []
        try:
            files = list(dist.files or [])
        except Exception:  # noqa: BLE001
            files = []
        total_bytes = 0
        for entry in files:
            candidate = site / str(entry)
            try:
                if candidate.is_file():
                    total_bytes += candidate.stat().st_size
            except OSError:
                continue
        info.file_count = len(files)
        info.byte_count = total_bytes
        top_level = dist.read_text("top_level.txt")
        if top_level:
            info.top_level = tuple(sorted({line.strip() for line in top_level.splitlines() if line.strip()}))
        else:
            info.top_level = _top_level_from_record(dist)
        index[name] = info
    if not index:
        raise LockError("no installed distributions found in the build environment")
    return index


def _module_aliases(name: str) -> tuple[str, ...]:
    """Known import aliases whose directory name differs from the distribution name."""

    aliases = {
        "pymupdf": ("pymupdf", "fitz"),
        "opencv-python-headless": ("cv2",),
        "pillow": ("PIL",),
        "scikit-learn": ("sklearn",),
        "pdfminer-six": ("pdfminer",),
        "beautifulsoup4": ("bs4",),
        "pyyaml": ("yaml",),
        "msgpack": ("msgpack",),
        "babeldoc": ("babeldoc",),
        "pdf2zh-next": ("pdf2zh_next",),
        "onnxruntime": ("onnxruntime",),
        "opencv-python": ("cv2",),
        "huggingface-hub": ("huggingface_hub",),
        "tiktoken": ("tiktoken", "tiktoken_ext"),
        "python-dateutil": ("dateutil",),
        "pycryptodome": ("Crypto",),
    }
    return aliases.get(name, ())


def _present_in_internal(internal_root: Path, module: str) -> tuple[bool, int, int]:
    """Report whether a top-level module exists in ``app/_internal`` plus its size."""

    candidates = (
        internal_root / f"{module}.py",
        internal_root / module,
        internal_root / f"{module}.pyd",
        internal_root / f"{module}.so",
    )
    for candidate in candidates:
        if candidate.is_file():
            return True, 1, candidate.stat().st_size
        if candidate.is_dir():
            files = 0
            total = 0
            for child in candidate.rglob("*"):
                if child.is_file():
                    files += 1
                    try:
                        total += child.stat().st_size
                    except OSError:
                        continue
            return True, files, total
    return False, 0, 0


def coverage_report(
    internal_root: Path,
    expected: dict[str, str],
    installed: dict[str, DistributionInfo],
    excluded: dict[str, str] | None = None,
) -> tuple[list[CoverageResult], list[str]]:
    """Check every locked distribution against the frozen tree.

    Returns the per-distribution results and the violations.  Deliberate exclusions
    are recorded with their reason and skipped; everything else must be present.
    """

    excluded = {} if excluded is None else dict(excluded)
    root = Path(internal_root)
    results: list[CoverageResult] = []
    violations: list[str] = []
    for name in sorted(expected):
        info = installed.get(name)
        if info is None:
            violations.append(f"locked distribution is not installed in the build venv: {name}")
            continue
        if info.version != expected[name]:
            violations.append(
                f"build venv version differs from the lock: {name} lock={expected[name]} installed={info.version}"
            )
            continue
        if name in excluded:
            results.append(CoverageResult(name=name, top_level=info.top_level))
            continue
        modules = info.top_level or _module_aliases(name)
        present: list[str] = []
        absent: list[str] = []
        files = 0
        total = 0
        for module in modules:
            found, module_files, module_bytes = _present_in_internal(root, module)
            if found:
                present.append(module)
                files += module_files
                total += module_bytes
            else:
                absent.append(module)
        metadata = metadata_directories(root, name)
        if not modules:
            # Metadata-only distributions (for example typing shims) have no import
            # surface; only their wheel identity can be checked.
            if not metadata:
                violations.append(f"locked distribution has no trace in the artifact: {name}")
            results.append(CoverageResult(name=name, top_level=(), files=files, bytes=total, metadata=metadata))
            continue
        if not present:
            # 只有元数据（``*.dist-info``）而没有模块目录，说明该发行版实际上没有被复制进
            # 私有运行时；这种失败只会在干净机第一次翻译时暴露，必须在构建期拦下。
            violations.append(
                "locked distribution is missing from the frozen runtime: "
                f"{name} (expected one of: {', '.join(modules)})"
            )
        # 多顶层名的发行版允许部分收集（可选子包常在运行期按需导入）；缺失项保留在
        # manifest 的 coverage 条目里，供发布前人工核对。
        results.append(
            CoverageResult(
                name=name,
                top_level=tuple(modules),
                present=tuple(present),
                absent=tuple(absent),
                files=files,
                bytes=total,
                metadata=metadata,
            )
        )
    unknown = sorted(set(excluded) - set(expected))
    if unknown:
        violations.append(f"exclusions name unlocked distributions: {', '.join(unknown)}")
    return results, violations
