"""Shared, stdlib-only contracts for the Windows portable process boundary.

This module is safe to import in the top-level launcher and service bootstrap.  It
must not import Flask, pdf2zh-next, BabelDOC, or any module that imports them.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import sys
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from pdf_reader import paths

PORTABLE_SERVICE_ENV = "PDF_READER_PORTABLE_SERVICE"
READY_FILE_ENV = "PDF_READER_READY_FILE"
HEALTH_TOKEN_ENV = "PDF_READER_HEALTH_TOKEN"
SERVICE_TEMP_PREFIX = "pdf-reader-service-"
SERVICE_TEMP_MARKER_NAME = ".pdf-reader-service-temp"
SERVICE_TEMP_MARKER_KIND = "pdf-reader-service-temp"

_HOST_PYTHON_ENV = frozenset(
    {
        "PYTHONHOME",
        "PYTHONPATH",
        "PYTHONUSERBASE",
        "PYTHONSTARTUP",
        "PYTHONBREAKPOINT",
        "PYTHONINSPECT",
        "PYTHONEXECUTABLE",
        "PYTHONPLATLIBDIR",
    }
)


def service_directories(layout: paths.RuntimeLayout) -> tuple[Path, ...]:
    """Directories referenced by the service environment before third-party import."""

    data = layout.data_root
    return (
        data / "home",
        data / "home" / ".cache",
        data / "temp",
        data / "pycache",
        data / "upstream-cache" / "huggingface",
        data / "upstream-cache" / "huggingface" / "hub",
        data / "upstream-cache" / "huggingface" / "assets",
        data / "home" / ".cache" / "babeldoc" / "tiktoken",
    )


def prepare_service_directories(layout: paths.RuntimeLayout) -> None:
    for directory in service_directories(layout):
        safe_directory = layout.require_data_path(directory, label="服务数据目录")
        safe_directory.mkdir(parents=True, exist_ok=True)
        layout.require_data_path(safe_directory, label="服务数据目录")


def _is_linkish(path: Path) -> bool:
    if path.is_symlink():
        return True
    if os.name == "nt":
        try:
            return path.is_junction()
        except AttributeError:
            return False
    return False


def _service_temp_marker(directory: Path) -> dict[str, object]:
    try:
        payload = json.loads((directory / SERVICE_TEMP_MARKER_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    pid = payload.get("pid")
    if payload.get("kind") != SERVICE_TEMP_MARKER_KIND or not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return {}
    return payload


def _validate_service_temp_directory(layout: paths.RuntimeLayout, value: str | Path) -> Path:
    directory = layout.require_data_path(value, label="服务临时目录")
    if (
        directory.parent != layout.temp_dir.resolve(strict=False)
        or not directory.name.startswith(SERVICE_TEMP_PREFIX)
        or _is_linkish(directory)
        or not _service_temp_marker(directory)
    ):
        raise PortableEnvironmentError(
            "便携服务临时目录缺少有效归属标记或不在 data/temp 直接子目录",
            code="portable_service_temp_invalid",
        )
    return directory


def recover_orphan_service_temp_directories(layout: paths.RuntimeLayout) -> tuple[Path, ...]:
    """Remove only marked service sessions whose launcher process is confirmed dead."""

    from pdf_reader import cache_ops

    temp_root = layout.require_data_path(layout.temp_dir, label="服务临时目录根")
    removed: list[Path] = []
    try:
        children = tuple(temp_root.iterdir())
    except FileNotFoundError:
        return ()
    for child in children:
        if not child.name.startswith(SERVICE_TEMP_PREFIX) or not child.is_dir() or _is_linkish(child):
            continue
        marker = _service_temp_marker(child)
        pid = marker.get("pid")
        if not marker or not isinstance(pid, int) or cache_ops.is_process_alive(pid):
            continue
        safe_child = layout.require_data_path(child, label="孤儿服务临时目录")
        try:
            shutil.rmtree(safe_child)
        except OSError:
            continue
        if not safe_child.exists():
            removed.append(safe_child)
    return tuple(removed)


def create_service_temp_directory(layout: paths.RuntimeLayout) -> Path:
    """Create one marked TEMP root owned by the current top-level launcher."""

    prepare_service_directories(layout)
    recover_orphan_service_temp_directories(layout)
    directory = Path(tempfile.mkdtemp(prefix=SERVICE_TEMP_PREFIX, dir=str(layout.temp_dir)))
    directory = layout.require_data_path(directory, label="服务临时目录")
    marker = directory / SERVICE_TEMP_MARKER_NAME
    try:
        marker.write_text(
            json.dumps(
                {
                    "kind": SERVICE_TEMP_MARKER_KIND,
                    "pid": os.getpid(),
                    "created_at": datetime.now(UTC).isoformat(),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        return _validate_service_temp_directory(layout, directory)
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise


def remove_service_temp_directory(layout: paths.RuntimeLayout, value: str | Path) -> None:
    """Remove the current service TEMP only when its path and marker are valid."""

    directory = _validate_service_temp_directory(layout, value)
    shutil.rmtree(directory)


def _service_environment_values(layout: paths.RuntimeLayout, service_temp: Path) -> dict[str, str]:
    data = layout.data_root
    home = data / "home"
    cache = data / "upstream-cache"
    huggingface = cache / "huggingface"
    return {
        PORTABLE_SERVICE_ENV: "1",
        "HOME": str(home),
        "USERPROFILE": str(home),
        "TEMP": str(service_temp),
        "TMP": str(service_temp),
        "TMPDIR": str(service_temp),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "PYTHONNOUSERSITE": "1",
        "PYTHONSAFEPATH": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPYCACHEPREFIX": str(data / "pycache"),
        "HF_HOME": str(huggingface),
        "HUGGINGFACE_HUB_CACHE": str(huggingface / "hub"),
        "HF_HUB_CACHE": str(huggingface / "hub"),
        "HF_ASSETS_CACHE": str(huggingface / "assets"),
        "TIKTOKEN_CACHE_DIR": str(home / ".cache" / "babeldoc" / "tiktoken"),
    }


def build_service_environment(
    layout: paths.RuntimeLayout,
    base_environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return a child-only environment without mutating the launcher's environment."""

    if layout.mode is not paths.RuntimeMode.PORTABLE:
        raise paths.PathStrategyError(
            "服务受控环境只能用于便携运行布局",
            code="portable_service_layout_required",
        )
    prepare_service_directories(layout)
    service_temp = create_service_temp_directory(layout)
    environment = dict(os.environ if base_environment is None else base_environment)
    for name in _HOST_PYTHON_ENV:
        environment.pop(name, None)
    for name in ("TRANSFORMERS_CACHE", "MODELSCOPE_CACHE", "TORCH_HOME"):
        environment.pop(name, None)
    environment.update(_service_environment_values(layout, service_temp))
    return environment


def validate_service_environment(
    layout: paths.RuntimeLayout,
    environment: Mapping[str, str] | None = None,
) -> None:
    """Fail before application/upstream import unless the child boundary is complete."""

    current = os.environ if environment is None else environment
    raw_temp = current.get("TEMP", "")
    try:
        service_temp = _validate_service_temp_directory(layout, raw_temp)
    except (paths.PathStrategyError, PortableEnvironmentError):
        service_temp = layout.temp_dir / "invalid"
    expected = _service_environment_values(layout, service_temp)
    required_names = tuple(expected)
    invalid = [name for name in required_names if current.get(name) != expected[name]]
    invalid.extend(name for name in _HOST_PYTHON_ENV if name in current)
    invalid.extend(name for name in ("TRANSFORMERS_CACHE", "MODELSCOPE_CACHE", "TORCH_HOME") if name in current)
    if service_temp.name == "invalid":
        invalid.append("TEMP")
    if invalid:
        names = ", ".join(sorted(set(invalid)))
        raise PortableEnvironmentError(
            f"便携服务缺少或包含不安全的进程环境变量：{names}",
            code="portable_service_environment_missing",
        )


def validate_private_frozen_runtime(
    layout: paths.RuntimeLayout,
    *,
    frozen: bool | None = None,
    executable: str | Path | None = None,
    no_user_site: bool | None = None,
    safe_path: bool | None = None,
    module_search_paths: tuple[str, ...] | None = None,
) -> None:
    """Reject a frozen service that can escape to a host Python installation.

    Source-mode calls are intentionally a no-op so unit tests and the existing
    developer entry remain usable.  The PyInstaller service always has
    ``sys.frozen`` and is checked before importing the application or upstream.
    """

    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    if not is_frozen:
        return
    if layout.mode is not paths.RuntimeMode.PORTABLE:
        raise PortableEnvironmentError(
            "冻结服务必须使用便携运行布局",
            code="private_runtime_layout_required",
        )
    actual_executable = Path(sys.executable if executable is None else executable).resolve(strict=False)
    expected_executable = (layout.resource_root / "PDF Reader Service.exe").resolve(strict=False)
    if actual_executable != expected_executable:
        raise PortableEnvironmentError(
            "便携服务没有从 app 内的私有可执行文件启动",
            code="private_runtime_executable_invalid",
        )
    user_site_disabled = bool(sys.flags.no_user_site) if no_user_site is None else no_user_site
    if not user_site_disabled:
        raise PortableEnvironmentError(
            "便携服务未禁用用户 site-packages",
            code="private_runtime_user_site_enabled",
        )
    isolated_search_path = bool(sys.flags.safe_path) if safe_path is None else safe_path
    if not isolated_search_path:
        raise PortableEnvironmentError(
            "便携服务未禁用当前目录导入注入",
            code="private_runtime_safe_path_disabled",
        )
    search_paths = tuple(getattr(sys, "path")) if module_search_paths is None else module_search_paths
    resource_root = layout.resource_root.resolve(strict=False)
    escaped: list[str] = []
    for value in search_paths:
        if not value:
            escaped.append("<empty>")
            continue
        candidate = Path(value).resolve(strict=False)
        try:
            candidate.relative_to(resource_root)
        except ValueError:
            escaped.append(str(candidate))
    if escaped:
        raise PortableEnvironmentError(
            "便携服务模块搜索路径逃逸 app 私有运行时",
            code="private_runtime_search_path_invalid",
        )


class PortableEnvironmentError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def new_readiness_file(layout: paths.RuntimeLayout) -> Path:
    candidate = layout.temp_dir / f"service-ready-{secrets.token_hex(12)}.json"
    return layout.require_data_path(candidate, label="服务就绪文件")


def new_health_token() -> str:
    return secrets.token_urlsafe(32)


def write_readiness_descriptor(
    layout: paths.RuntimeLayout,
    destination: str | Path,
    *,
    host: str,
    port: int,
    health_token: str,
) -> Path:
    """Atomically publish loopback endpoint metadata inside portable data."""

    target = layout.require_data_path(destination, label="服务就绪文件")
    temporary = layout.require_data_path(
        target.with_name(f".{target.name}.{secrets.token_hex(8)}.tmp"),
        label="服务就绪临时文件",
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    if len(health_token) < 32:
        raise PortableEnvironmentError(
            "便携服务健康检查令牌无效",
            code="portable_service_health_token_invalid",
        )
    payload = json.dumps(
        {"schema": 1, "host": host, "port": port, "health_token": health_token},
        separators=(",", ":"),
    )
    try:
        temporary.write_text(payload, encoding="utf-8")
        os.replace(temporary, target)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return target


def readiness_file_from_environment(layout: paths.RuntimeLayout) -> Path | None:
    if os.environ.get(PORTABLE_SERVICE_ENV) != "1":
        return None
    raw = os.environ.get(READY_FILE_ENV)
    if not raw:
        raise PortableEnvironmentError(
            "便携服务缺少就绪文件路径",
            code="portable_service_ready_file_missing",
        )
    return layout.require_data_path(raw, label="服务就绪文件")
