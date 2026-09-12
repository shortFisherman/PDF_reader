"""Build ``app/runtime-manifest.json`` exactly as ``runtime_policy.py`` schema 1 expects.

The manifest is the only place where the release ties a bundled byte range to a
locked dependency: the full Git commit, the Python patch version, the private service
SHA-256, the lock SHA-256, and one name/version/wheel-SHA-256 entry per locked
distribution.  Every value is derived from the build venv and the assembled tree, so
the file cannot drift from the artifact it describes.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .artifacts import sha256_file
from .layout import APP_DIRECTORY, INTERNAL_DIRECTORY, LAUNCHER_EXECUTABLE, SERVICE_EXECUTABLE
from .lock import LockError, WheelRecord, normalize_distribution
from .modules import CoverageResult, DistributionInfo, coverage_report

RUNTIME_MANIFEST_NAME = "runtime-manifest.json"
# 名称刻意避开 ``build-`` 前缀：runtime_policy 把开发/构建类发行版（``build`` 等）作为
# 目录与文件名前缀拒绝，发行物里的自有清单不能撞上这条规则。
BUILD_MANIFEST_NAME = "release-manifest.json"
INDEX_NAME = "distribution-index.json"
SCHEMA_VERSION = 1
SOURCE_LOCK = "packaging/windows/runtime-requirements.lock"
PYTHON_MINOR = "3.12"
_COMMIT = re.compile(r"^[0-9a-f]{40}$")

# 已被静态排除、不进入发行物的锁定发行版及其原因。runtime-manifest.json 仍逐条记录它们的
# wheel 哈希，发布者因此能核对“锁里有什么、发行物里为什么没有”。
DEFAULT_EXCLUSIONS: dict[str, str] = {
    "onnx": (
        "只提供模型转换/校验工具，不被 pdf2zh-next 或 BabelDOC 的翻译路径导入；"
        "其附带 .onnx 测试模型属于数据策略禁止的模型权重文件"
    ),
    "gradio": "上游 GUI 依赖；本发行物使用自有前端，服务端不导入 gradio",
    "gradio-client": "上游 GUI 依赖；随 gradio 一起排除",
    "gradio-i18n": "上游 GUI 依赖；随 gradio 一起排除",
    "gradio-pdf": "上游 GUI 依赖；随 gradio 一起排除",
    "ruff": "gradio/xsdata 声明的工具依赖；发行物不提供命令行开发工具",
}


class ManifestError(RuntimeError):
    """The manifest cannot be produced from the given inputs."""


@dataclass(frozen=True, slots=True)
class PythonRuntimeInfo:
    version: str
    implementation: str
    executable: str
    executable_sha256: str

    def as_payload(self) -> dict[str, str]:
        return {
            "version": self.version,
            "implementation": self.implementation,
            "executable": self.executable,
            "executable_sha256": self.executable_sha256,
        }


def validate_commit(source_commit: str) -> str:
    if not _COMMIT.fullmatch(source_commit):
        raise ManifestError(f"source commit must be a full lowercase Git commit: {source_commit!r}")
    return source_commit


def _coverage_payload(result: CoverageResult, exclusions: dict[str, str]) -> dict[str, object]:
    status = "excluded" if result.name in exclusions else "collected"
    payload: dict[str, object] = {
        "name": result.name,
        "status": status,
        "top_level": list(result.top_level),
        "present": list(result.present),
        "files": result.files,
        "bytes": result.bytes,
    }
    if status == "excluded":
        payload["reason"] = exclusions[result.name]
    return payload


def build_manifest(
    *,
    artifact_root: Path,
    version: str,
    source_commit: str,
    python_version: str,
    python_implementation: str,
    expected_lock: dict[str, str],
    wheels: dict[str, WheelRecord],
    installed: dict[str, DistributionInfo],
    lock_sha256: str,
    created_at: str | None = None,
    exclusions: dict[str, str] | None = None,
) -> tuple[dict[str, object], list[str]]:
    """Assemble the runtime manifest payload plus any contract violations."""

    artifact = Path(artifact_root)
    selected_exclusions = dict(DEFAULT_EXCLUSIONS if exclusions is None else exclusions)
    violations: list[str] = []
    try:
        validate_commit(source_commit)
    except ManifestError as exc:
        violations.append(str(exc))
    if not python_version.startswith(f"{PYTHON_MINOR}."):
        violations.append(f"build interpreter must be Python {PYTHON_MINOR}.x, got {python_version}")
    if not re.fullmatch(r"[0-9a-f]{64}", lock_sha256):
        violations.append("runtime lock SHA-256 is invalid")

    service_path = artifact / APP_DIRECTORY / SERVICE_EXECUTABLE
    if not service_path.is_file():
        violations.append(f"private service executable is missing: {APP_DIRECTORY}/{SERVICE_EXECUTABLE}")
        service_sha = ""
    else:
        service_sha = sha256_file(service_path)

    missing_wheels = sorted(set(expected_lock) - set(wheels))
    if missing_wheels:
        violations.append(f"no wheel SHA-256 recorded for: {', '.join(missing_wheels)}")
    extra_wheels = sorted(set(wheels) - set(expected_lock))
    if extra_wheels:
        violations.append(f"wheel SHA-256 recorded for unpacked distributions: {', '.join(extra_wheels)}")

    unknown_exclusions = sorted(set(selected_exclusions) - set(expected_lock))
    if unknown_exclusions:
        violations.append(f"exclusions name distributions outside the runtime lock: {', '.join(unknown_exclusions)}")

    coverage, coverage_violations = coverage_report(
        artifact / APP_DIRECTORY / INTERNAL_DIRECTORY,
        expected_lock,
        installed,
        excluded=selected_exclusions,
    )
    violations.extend(coverage_violations)

    packages: list[dict[str, object]] = []
    for name in sorted(expected_lock):
        record = wheels.get(name)
        if record is None:
            continue
        packages.append(
            {
                "name": record.name,
                "version": record.version,
                "wheel_sha256": record.wheel_sha256,
                "wheel_file": record.wheel_file,
                "collected": name not in selected_exclusions,
            }
        )

    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "product": "PDF Reader",
        "app_version": version,
        "source_commit": source_commit,
        "source_lock": SOURCE_LOCK,
        "source_lock_sha256": lock_sha256,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds") if created_at is None else created_at,
        "python": PythonRuntimeInfo(
            version=python_version,
            implementation=python_implementation,
            executable=f"{APP_DIRECTORY}/{SERVICE_EXECUTABLE}",
            executable_sha256=service_sha,
        ).as_payload(),
        "launcher": {
            "executable": LAUNCHER_EXECUTABLE,
            "sha256": sha256_file(artifact / LAUNCHER_EXECUTABLE) if (artifact / LAUNCHER_EXECUTABLE).is_file() else "",
        },
        "packages": packages,
        "coverage": [_coverage_payload(result, selected_exclusions) for result in coverage],
    }
    return payload, violations


def load_wheel_records(path: Path) -> dict[str, WheelRecord]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ManifestError(f"cannot read the wheel hash report {path}: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("packages"), list):
        raise ManifestError(f"wheel hash report has no packages list: {path}")
    records: dict[str, WheelRecord] = {}
    for item in payload["packages"]:
        if not isinstance(item, dict):
            raise ManifestError(f"wheel hash report entry is not an object: {path}")
        name = item.get("name")
        version = item.get("version")
        digest = item.get("wheel_sha256")
        wheel_file = item.get("wheel_file", "")
        if not all(isinstance(value, str) for value in (name, version, digest, wheel_file)):
            raise ManifestError(f"wheel hash report entry is incomplete: {path}")
        normalized = normalize_distribution(name)
        if normalized in records:
            raise ManifestError(f"wheel hash report repeats distribution: {normalized}")
        records[normalized] = WheelRecord(
            name=normalized,
            version=version,
            wheel_sha256=digest,
            wheel_file=wheel_file,
        )
    if not records:
        raise ManifestError(f"wheel hash report contains no distributions: {path}")
    return records


def load_distribution_index(path: Path) -> dict[str, DistributionInfo]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LockError(f"cannot read the distribution index {path}: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("distributions"), list):
        raise LockError(f"distribution index has no distributions list: {path}")
    index: dict[str, DistributionInfo] = {}
    for item in payload["distributions"]:
        if not isinstance(item, dict):
            raise LockError(f"distribution index entry is not an object: {path}")
        name = item.get("name")
        version = item.get("version")
        top_level = item.get("top_level", [])
        if not isinstance(name, str) or not isinstance(version, str) or not isinstance(top_level, list):
            raise LockError(f"distribution index entry is incomplete: {path}")
        index[normalize_distribution(name)] = DistributionInfo(
            name=normalize_distribution(name),
            version=version,
            top_level=tuple(str(entry) for entry in top_level),
            file_count=int(item.get("file_count", 0) or 0),
            byte_count=int(item.get("byte_count", 0) or 0),
        )
    if not index:
        raise LockError(f"distribution index contains no distributions: {path}")
    return index


def write_runtime_manifest(path: Path, payload: dict[str, object]) -> Path:
    """Write ``app/runtime-manifest.json`` (runtime policy schema 1) as UTF-8 JSON."""

    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ManifestError(f"runtime manifest schema_version must be {SCHEMA_VERSION}")
    destination = Path(path)
    if destination.name != RUNTIME_MANIFEST_NAME:
        raise ManifestError(f"runtime manifest must be written as {RUNTIME_MANIFEST_NAME}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return destination
