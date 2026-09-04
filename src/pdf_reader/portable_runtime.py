"""Shared, stdlib-only contracts for the Windows portable process boundary.

This module is safe to import in the top-level launcher and service bootstrap.  It
must not import Flask, pdf2zh-next, BabelDOC, or any module that imports them.
"""

from __future__ import annotations

import json
import os
import secrets
from collections.abc import Mapping
from pathlib import Path

from pdf_reader import paths

PORTABLE_SERVICE_ENV = "PDF_READER_PORTABLE_SERVICE"
READY_FILE_ENV = "PDF_READER_READY_FILE"
HEALTH_TOKEN_ENV = "PDF_READER_HEALTH_TOKEN"

_HOST_PYTHON_ENV = frozenset(
    {
        "PYTHONHOME",
        "PYTHONPATH",
        "PYTHONUSERBASE",
        "PYTHONSTARTUP",
        "PYTHONBREAKPOINT",
        "PYTHONINSPECT",
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
        data / "upstream-cache" / "modelscope",
        data / "upstream-cache" / "torch",
        data / "upstream-cache" / "babeldoc",
        data / "upstream-cache" / "pdf2zh-next",
    )


def prepare_service_directories(layout: paths.RuntimeLayout) -> None:
    for directory in service_directories(layout):
        safe_directory = layout.require_data_path(directory, label="服务数据目录")
        safe_directory.mkdir(parents=True, exist_ok=True)
        layout.require_data_path(safe_directory, label="服务数据目录")


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
    environment = dict(os.environ if base_environment is None else base_environment)
    for name in _HOST_PYTHON_ENV:
        environment.pop(name, None)

    data = layout.data_root
    home = data / "home"
    cache = data / "upstream-cache"
    environment.update(
        {
            PORTABLE_SERVICE_ENV: "1",
            "HOME": str(home),
            "USERPROFILE": str(home),
            "TEMP": str(layout.temp_dir),
            "TMP": str(layout.temp_dir),
            "TMPDIR": str(layout.temp_dir),
            "XDG_CACHE_HOME": str(home / ".cache"),
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPYCACHEPREFIX": str(data / "pycache"),
            "HF_HOME": str(cache / "huggingface"),
            "HUGGINGFACE_HUB_CACHE": str(cache / "huggingface" / "hub"),
            "TRANSFORMERS_CACHE": str(cache / "huggingface" / "transformers"),
            "MODELSCOPE_CACHE": str(cache / "modelscope"),
            "TORCH_HOME": str(cache / "torch"),
        }
    )
    return environment


def validate_service_environment(
    layout: paths.RuntimeLayout,
    environment: Mapping[str, str] | None = None,
) -> None:
    """Fail before application/upstream import unless the child boundary is complete."""

    current = os.environ if environment is None else environment
    expected = build_service_environment(layout, current)
    required_names = (
        PORTABLE_SERVICE_ENV,
        "HOME",
        "USERPROFILE",
        "TEMP",
        "TMP",
        "TMPDIR",
        "XDG_CACHE_HOME",
        "PYTHONNOUSERSITE",
        "PYTHONDONTWRITEBYTECODE",
        "PYTHONPYCACHEPREFIX",
        "HF_HOME",
        "HUGGINGFACE_HUB_CACHE",
        "TRANSFORMERS_CACHE",
        "MODELSCOPE_CACHE",
        "TORCH_HOME",
    )
    invalid = [name for name in required_names if current.get(name) != expected[name]]
    invalid.extend(name for name in _HOST_PYTHON_ENV if name in current)
    if invalid:
        names = ", ".join(sorted(set(invalid)))
        raise PortableEnvironmentError(
            f"便携服务缺少或包含不安全的进程环境变量：{names}",
            code="portable_service_environment_missing",
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
