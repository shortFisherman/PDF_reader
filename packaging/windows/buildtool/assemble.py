"""Assemble the final onedir tree from the two PyInstaller bundles.

Layout produced (the contract ``portable_launcher``/``paths.py`` already implement):

``PDF Reader/``
    ``PDF Reader.exe`` -- the only user-facing entry point, with its own private runtime
    ``_internal/``
    ``app/`` -- private service root (``RESOURCE_ROOT``): ``PDF Reader Service.exe``,
    the service's own ``_internal/``, ``static/``, ``templates/``,
    ``config.example.toml``, ``licenses/`` and the build manifests
    ``data/`` -- empty scaffold; every mutable file is created at first start

The service must sit directly under ``app/`` because ``portable_launcher`` and
``validate_private_frozen_runtime`` both derive that exact path, and its module search
paths must stay inside ``app/``.  Frontend assets, the config example and the license
material go to ``app/`` as well, since ``paths.get_resource_root()`` is ``app/`` in
portable mode.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .layout import (
    APP_DIRECTORY,
    INTERNAL_DIRECTORY,
    LAUNCHER_EXECUTABLE,
    SERVICE_EXECUTABLE,
    BuildLayoutError,
)

SERVICE_BUNDLE_DIRECTORY = "service"
LAUNCHER_BUNDLE_DIRECTORY = "launcher"
APP_RESOURCE_DIRECTORIES: tuple[str, ...] = ("static", "templates")
APP_RESOURCE_FILES: tuple[str, ...] = ("config.example.toml", "LICENSE")
LICENSE_DIRECTORY = "licenses"
DATA_DIRECTORY = "data"


class AssemblyError(RuntimeError):
    """The staging bundles cannot produce a valid artifact tree."""


def _copy_tree(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise AssemblyError(f"bundle directory is missing: {source}")
    destination.mkdir(parents=True, exist_ok=True)
    for entry in sorted(source.iterdir()):
        target = destination / entry.name
        if entry.is_dir():
            shutil.copytree(entry, target, dirs_exist_ok=True, symlinks=False)
        elif entry.is_file():
            shutil.copy2(entry, target)
        else:
            raise AssemblyError(f"unsupported bundle entry: {entry}")


def _require_bundle_executable(bundle: Path, name: str) -> Path:
    executable = bundle / name
    if not executable.is_file():
        raise AssemblyError(f"PyInstaller bundle {bundle} does not contain {name}")
    return executable


def assemble(staging_root: Path, artifact_root: Path, repo_root: Path) -> list[str]:
    """Build the artifact tree in place; returns a short list of copy summaries."""

    staging = Path(staging_root)
    artifact = Path(artifact_root)
    repo = Path(repo_root)
    launcher_bundle = staging / LAUNCHER_BUNDLE_DIRECTORY
    service_bundle = staging / SERVICE_BUNDLE_DIRECTORY
    notes: list[str] = []

    _require_bundle_executable(launcher_bundle, LAUNCHER_EXECUTABLE)
    _require_bundle_executable(service_bundle, SERVICE_EXECUTABLE)

    if artifact.exists():
        shutil.rmtree(artifact)
    artifact.mkdir(parents=True)
    app = artifact / APP_DIRECTORY
    app.mkdir(parents=True)

    # 顶层启动器：EXE 与其私有 _internal 必须保持同级，PyInstaller 才能解析自身运行时。
    shutil.copy2(launcher_bundle / LAUNCHER_EXECUTABLE, artifact / LAUNCHER_EXECUTABLE)
    launcher_internal = launcher_bundle / INTERNAL_DIRECTORY
    if not launcher_internal.is_dir():
        raise AssemblyError(f"launcher bundle has no {INTERNAL_DIRECTORY} directory: {launcher_bundle}")
    _copy_tree(launcher_internal, artifact / INTERNAL_DIRECTORY)
    notes.append(f"launcher: {LAUNCHER_EXECUTABLE} + {INTERNAL_DIRECTORY}/")

    # 私有服务：同样保持 EXE 与 _internal 同级，但整体位于 app/ 内。
    shutil.copy2(service_bundle / SERVICE_EXECUTABLE, app / SERVICE_EXECUTABLE)
    service_internal = service_bundle / INTERNAL_DIRECTORY
    if not service_internal.is_dir():
        raise AssemblyError(f"service bundle has no {INTERNAL_DIRECTORY} directory: {service_bundle}")
    _copy_tree(service_internal, app / INTERNAL_DIRECTORY)
    notes.append(f"service: {APP_DIRECTORY}/{SERVICE_EXECUTABLE} + {APP_DIRECTORY}/{INTERNAL_DIRECTORY}/")

    # 前端资源、配置示例与许可证由服务 spec 声明收集；PyInstaller 先把它们放进
    # ``_internal``，这里再移动到便携服务真正解析的位置（RESOURCE_ROOT = app/），
    # 因此发行树里只有一份副本。仓库副本只在 bundle 缺失该资源时作为回退来源。
    for name in APP_RESOURCE_DIRECTORIES:
        notes.append(_relocate_resource(service_internal, app / name, repo / name, artifact=artifact, label=name))
    for name in APP_RESOURCE_FILES:
        notes.append(_relocate_resource(service_internal, app / name, repo / name, artifact=artifact, label=name))

    licenses = app / LICENSE_DIRECTORY
    licenses.mkdir(parents=True, exist_ok=True)
    notes.append(
        _relocate_resource(service_internal, licenses / "LICENSE", repo / "LICENSE", artifact=artifact, label="LICENSE")
    )

    (artifact / DATA_DIRECTORY).mkdir(parents=True, exist_ok=True)
    notes.append(f"scaffold: {DATA_DIRECTORY}/")
    return notes


def _relocate_resource(
    bundle_internal: Path, destination: Path, repository_source: Path, *, artifact: Path, label: str
) -> str:
    """Move a collected resource out of ``_internal``, or copy it from the repository."""

    relative = destination.relative_to(artifact).as_posix()
    bundled = bundle_internal / label
    if bundled.is_dir():
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            shutil.rmtree(destination)
        shutil.move(str(bundled), str(destination))
        return f"resource: {relative}/"
    if bundled.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(bundled), str(destination))
        return f"resource: {relative}"
    if repository_source.is_dir():
        _copy_tree(repository_source, destination)
        return f"resource: {relative}/ (repository fallback)"
    if repository_source.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(repository_source, destination)
        return f"resource: {relative} (repository fallback)"
    raise AssemblyError(f"resource is neither bundled nor present in the repository: {label}")


def verify_bundles(staging_root: Path) -> list[str]:
    """Check the two PyInstaller outputs before assembly; returns violations."""

    staging = Path(staging_root)
    violations: list[str] = []
    for bundle_name, executable in (
        (LAUNCHER_BUNDLE_DIRECTORY, LAUNCHER_EXECUTABLE),
        (SERVICE_BUNDLE_DIRECTORY, SERVICE_EXECUTABLE),
    ):
        bundle = staging / bundle_name
        if not (bundle / executable).is_file():
            violations.append(f"staging/{bundle_name} is missing {executable}")
        if not (bundle / INTERNAL_DIRECTORY).is_dir():
            violations.append(f"staging/{bundle_name} is missing {INTERNAL_DIRECTORY}/")
        python_dlls = [path.name for path in (bundle / INTERNAL_DIRECTORY).glob("python3*.dll")]
        if not python_dlls:
            violations.append(f"staging/{bundle_name} has no private Python DLL inside {INTERNAL_DIRECTORY}/")
    launcher_internal = staging / LAUNCHER_BUNDLE_DIRECTORY / INTERNAL_DIRECTORY
    for forbidden in ("pdf2zh_next", "babeldoc", "cv2", "onnxruntime"):
        if (launcher_internal / forbidden).exists():
            violations.append(
                "the user-facing launcher bundle must not carry the translation runtime: "
                f"{LAUNCHER_BUNDLE_DIRECTORY}/{INTERNAL_DIRECTORY}/{forbidden}"
            )
    service_internal = staging / SERVICE_BUNDLE_DIRECTORY / INTERNAL_DIRECTORY
    for required in ("pdf2zh_next", "babeldoc", "pymupdf", "onnxruntime", "cv2", "tiktoken_ext"):
        if not (service_internal / required).exists():
            violations.append(f"service bundle is missing upstream runtime: {required}")
    if (service_internal / "gradio").exists():
        violations.append("service bundle contains the excluded upstream GUI stack: gradio")
    return violations


def ensure_within(path: Path, root: Path, *, label: str) -> Path:
    """Thin wrapper kept here so callers assemble inside a validated output root."""

    resolved_root = Path(root).resolve(strict=False)
    resolved = Path(path).resolve(strict=False)
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise BuildLayoutError(f"{label} escapes {resolved_root}: {resolved}") from exc
    return resolved
