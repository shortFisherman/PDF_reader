"""Shared, stdlib-only contracts for the Windows portable process boundary.

This module is safe to import in the top-level launcher and service bootstrap.  It
must not import Flask, pdf2zh-next, BabelDOC, or any module that imports them.
"""

from __future__ import annotations

import errno
import hashlib
import ipaddress
import json
import os
import secrets
import shutil
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from pdf_reader import paths

PORTABLE_SERVICE_ENV = "PDF_READER_PORTABLE_SERVICE"
READY_FILE_ENV = "PDF_READER_READY_FILE"
HEALTH_TOKEN_ENV = "PDF_READER_HEALTH_TOKEN"
CONTROL_TOKEN_ENV = "PDF_READER_CONTROL_TOKEN"
LAUNCHER_LIVENESS_ENV = "PDF_READER_LAUNCHER_LIVENESS"
HEALTH_TOKEN_HEADER = "X-PDF-Reader-Health-Token"
CONTROL_TOKEN_HEADER = "X-PDF-Reader-Control-Token"
CONTROL_PATH = "/api/control"
SHUTDOWN_PATH = "/api/shutdown"
CONTROL_COMMANDS = frozenset({"open_reader", "open_logs", "quit"})
SERVICE_TEMP_PREFIX = "pdf-reader-service-"
SERVICE_TEMP_MARKER_NAME = ".pdf-reader-service-temp"
SERVICE_TEMP_MARKER_KIND = "pdf-reader-service-temp"
INSTANCE_RECORD_NAME = "instance.json"
INSTANCE_LOCK_NAME = "instance.lock"
LIVENESS_FILE_PREFIX = "launcher-liveness-"
LIVENESS_FILE_SUFFIX = ".lock"
WINDOWS_LIVENESS_PREFIX = "Local\\PDFReader.Liveness."
WINDOWS_LIVENESS_DESCRIPTOR = "windows-mutex:"
POSIX_LIVENESS_DESCRIPTOR = "posix-flock:"
READINESS_SCHEMA = 1
READINESS_STATUS_READY = "ready"
READINESS_STATUS_ERROR = "error"
READINESS_FILE_PREFIX = "service-ready-"
MINIMUM_TOKEN_LENGTH = 32
MAXIMUM_DESCRIPTOR_MESSAGE_LENGTH = 400
SERVICE_EXIT_PORT_IN_USE = 3
# 端口冲突的稳定错误码：服务写进就绪描述符，启动器读出来直接作为诊断码。
SERVICE_PORT_IN_USE_CODE = "service_port_in_use"
LOOPBACK_PROBE_TIMEOUT = 0.5
LOCK_FILE_MODE = 0o600
PORT_RELEASE_TIMEOUT = 5.0
PORT_RELEASE_POLL_INTERVAL = 0.1
MAX_LIVENESS_QUERY_FAILURES = 3

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


def _valid_liveness_descriptor(layout: paths.RuntimeLayout, value: object) -> bool:
    """Validate the opaque kernel-liveness descriptor without opening its object."""

    if not isinstance(value, str):
        return False
    if value.startswith(WINDOWS_LIVENESS_DESCRIPTOR):
        name = value.removeprefix(WINDOWS_LIVENESS_DESCRIPTOR)
        suffix = name.removeprefix(WINDOWS_LIVENESS_PREFIX)
        return (
            name.startswith(WINDOWS_LIVENESS_PREFIX)
            and len(suffix) == 32
            and all(c in "0123456789abcdef" for c in suffix)
        )
    if value.startswith(POSIX_LIVENESS_DESCRIPTOR):
        raw_path = value.removeprefix(POSIX_LIVENESS_DESCRIPTOR)
        try:
            candidate = layout.require_data_path(raw_path, label="启动器存活锁")
        except (OSError, ValueError, paths.PathStrategyError):
            return False
        return (
            candidate.parent == layout.runtime_dir.resolve(strict=False)
            and candidate.name.startswith(LIVENESS_FILE_PREFIX)
            and candidate.name.endswith(LIVENESS_FILE_SUFFIX)
        )
    return False


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
    *,
    control_token: str | None = None,
    launcher_liveness: str,
) -> dict[str, str]:
    """Return a child-only environment without mutating the launcher's environment.

    control_token 与 launcher_liveness 承载受认证控制通道和内核存活归属；两者都在
    子进程启动前校验，服务不可能在没有可认证通道或没有存活监督者的情况下运行。
    """

    if layout.mode is not paths.RuntimeMode.PORTABLE:
        raise paths.PathStrategyError(
            "服务受控环境只能用于便携运行布局",
            code="portable_service_layout_required",
        )
    selected_control_token = new_control_token() if control_token is None else control_token
    if not isinstance(selected_control_token, str) or len(selected_control_token) < MINIMUM_TOKEN_LENGTH:
        raise PortableEnvironmentError(
            "便携服务控制令牌无效",
            code="portable_service_control_token_invalid",
        )
    if not _valid_liveness_descriptor(layout, launcher_liveness):
        raise PortableEnvironmentError(
            "便携服务缺少有效的顶层启动器内核存活标识",
            code="portable_service_launcher_liveness_invalid",
        )
    prepare_service_directories(layout)
    service_temp = create_service_temp_directory(layout)
    environment = dict(os.environ if base_environment is None else base_environment)
    for name in _HOST_PYTHON_ENV:
        environment.pop(name, None)
    for name in ("TRANSFORMERS_CACHE", "MODELSCOPE_CACHE", "TORCH_HOME"):
        environment.pop(name, None)
    environment.update(_service_environment_values(layout, service_temp))
    environment[CONTROL_TOKEN_ENV] = selected_control_token
    environment[LAUNCHER_LIVENESS_ENV] = launcher_liveness
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
    control_token = current.get(CONTROL_TOKEN_ENV, "")
    if not isinstance(control_token, str) or len(control_token) < MINIMUM_TOKEN_LENGTH:
        invalid.append(CONTROL_TOKEN_ENV)
    if not _valid_liveness_descriptor(layout, current.get(LAUNCHER_LIVENESS_ENV, "")):
        invalid.append(LAUNCHER_LIVENESS_ENV)
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


class PortableShutdownController:
    """One-shot cooperative shutdown signal shared by the HTTP route and the server loop."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._reason: str | None = None

    @property
    def requested(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str | None:
        with self._lock:
            return self._reason

    def request(self, reason: str) -> bool:
        """Set the shutdown request; only the first reason is kept for diagnostics."""

        with self._lock:
            if self._event.is_set():
                return False
            self._reason = reason
            self._event.set()
            return True

    def wait(self, timeout: float = 0.1) -> bool:
        return self._event.wait(max(0.0, timeout))

    def clear(self) -> None:
        with self._lock:
            self._reason = None
            self._event.clear()


class LauncherLivenessOwner(Protocol):
    """Launcher-side ownership of one per-launch kernel lifetime object."""

    @property
    def descriptor(self) -> str: ...

    def close(self) -> None: ...


class LauncherLivenessMonitor(Protocol):
    """Service-side view of the exact object owned by its launcher."""

    def launcher_gone(self) -> bool: ...

    def close(self) -> None: ...


class WindowsLivenessApi(Protocol):
    def create_owned_mutex(self, name: str) -> tuple[int, bool]: ...

    def open_mutex(self, name: str) -> int: ...

    def wait_mutex(self, handle: int) -> int: ...

    def release_mutex(self, handle: int) -> None: ...

    def close_handle(self, handle: int) -> None: ...


WINDOWS_WAIT_OBJECT = 0
WINDOWS_WAIT_ABANDONED = 128
WINDOWS_WAIT_TIMEOUT = 258


def _load_windows_liveness_api() -> WindowsLivenessApi:
    if sys.platform != "win32":
        raise PortableEnvironmentError(
            "当前平台没有可用的 Windows 启动器存活对象实现",
            code="launcher_liveness_unavailable",
        )
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel32.OpenMutexW.restype = ctypes.c_void_p
    kernel32.OpenMutexW.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_wchar_p]
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.ReleaseMutex.restype = ctypes.c_bool
    kernel32.ReleaseMutex.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_bool
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

    class _Kernel32LivenessApi:
        def create_owned_mutex(self, name: str) -> tuple[int, bool]:
            handle = kernel32.CreateMutexW(None, True, name)
            return int(handle or 0), ctypes.get_last_error() == 183

        def open_mutex(self, name: str) -> int:
            synchronize_and_modify = 0x00100001
            return int(kernel32.OpenMutexW(synchronize_and_modify, False, name) or 0)

        def wait_mutex(self, handle: int) -> int:
            return int(kernel32.WaitForSingleObject(ctypes.c_void_p(handle), 0))

        def release_mutex(self, handle: int) -> None:
            kernel32.ReleaseMutex(ctypes.c_void_p(handle))

        def close_handle(self, handle: int) -> None:
            kernel32.CloseHandle(ctypes.c_void_p(handle))

    return _Kernel32LivenessApi()


class _WindowsLauncherLivenessOwner:
    def __init__(self, *, api: WindowsLivenessApi, name: str) -> None:
        self._api = api
        self._name = name
        handle, existed = api.create_owned_mutex(name)
        if not handle or existed:
            if handle:
                api.close_handle(handle)
            raise PortableEnvironmentError(
                "无法创建唯一的启动器内核存活对象",
                code="launcher_liveness_unavailable",
            )
        self._handle: int | None = handle

    @property
    def descriptor(self) -> str:
        return f"{WINDOWS_LIVENESS_DESCRIPTOR}{self._name}"

    def close(self) -> None:
        handle = self._handle
        self._handle = None
        if handle is not None:
            self._api.close_handle(handle)


class _WindowsLauncherLivenessMonitor:
    def __init__(self, *, api: WindowsLivenessApi, name: str) -> None:
        self._api = api
        handle = api.open_mutex(name)
        if not handle:
            raise PortableEnvironmentError(
                "启动器内核存活对象不存在",
                code="launcher_liveness_unavailable",
            )
        self._handle: int | None = handle

    def launcher_gone(self) -> bool:
        handle = self._handle
        if handle is None:
            return True
        result = self._api.wait_mutex(handle)
        if result == WINDOWS_WAIT_TIMEOUT:
            return False
        if result in (WINDOWS_WAIT_OBJECT, WINDOWS_WAIT_ABANDONED):
            self._api.release_mutex(handle)
            return True
        raise OSError("等待启动器内核存活对象失败")

    def close(self) -> None:
        handle = self._handle
        self._handle = None
        if handle is not None:
            self._api.close_handle(handle)


class _PosixLauncherLivenessOwner:
    def __init__(self, layout: paths.RuntimeLayout) -> None:
        import fcntl

        runtime_dir = layout.require_data_path(layout.runtime_dir, label="启动器存活目录")
        runtime_dir.mkdir(parents=True, exist_ok=True)
        path = runtime_dir / f"{LIVENESS_FILE_PREFIX}{secrets.token_hex(16)}{LIVENESS_FILE_SUFFIX}"
        self._path = layout.require_data_path(path, label="启动器存活锁")
        handle: int | None = None
        try:
            handle = os.open(self._path, os.O_CREAT | os.O_EXCL | os.O_RDWR, LOCK_FILE_MODE)
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if handle is not None:
                os.close(handle)
            raise PortableEnvironmentError(
                "无法创建启动器内核存活锁",
                code="launcher_liveness_unavailable",
            ) from exc
        assert handle is not None
        self._handle: int | None = handle

    @property
    def descriptor(self) -> str:
        return f"{POSIX_LIVENESS_DESCRIPTOR}{self._path}"

    def close(self) -> None:
        handle = self._handle
        self._handle = None
        if handle is not None:
            os.close(handle)
        try:
            self._path.unlink()
        except FileNotFoundError:
            pass


class _PosixLauncherLivenessMonitor:
    def __init__(self, layout: paths.RuntimeLayout, path: Path) -> None:
        self._path = layout.require_data_path(path, label="启动器存活锁")
        try:
            self._handle: int | None = os.open(self._path, os.O_RDWR)
        except OSError as exc:
            raise PortableEnvironmentError(
                "启动器内核存活锁不存在",
                code="launcher_liveness_unavailable",
            ) from exc

    def launcher_gone(self) -> bool:
        import fcntl

        handle = self._handle
        if handle is None:
            return True
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN):
                return False
            raise
        fcntl.flock(handle, fcntl.LOCK_UN)
        return True

    def close(self) -> None:
        handle = self._handle
        self._handle = None
        if handle is not None:
            os.close(handle)


def create_launcher_liveness_owner(
    layout: paths.RuntimeLayout,
    *,
    platform: str | None = None,
    windows_api: WindowsLivenessApi | None = None,
) -> LauncherLivenessOwner:
    """Create one random, kernel-owned identity for this exact launcher lifetime."""

    if (sys.platform if platform is None else platform) == "win32":
        api = _load_windows_liveness_api() if windows_api is None else windows_api
        name = f"{WINDOWS_LIVENESS_PREFIX}{secrets.token_hex(16)}"
        return _WindowsLauncherLivenessOwner(api=api, name=name)
    return _PosixLauncherLivenessOwner(layout)


def open_launcher_liveness_monitor(
    layout: paths.RuntimeLayout,
    descriptor: str,
    *,
    platform: str | None = None,
    windows_api: WindowsLivenessApi | None = None,
) -> LauncherLivenessMonitor:
    """Open the exact per-launch object; PID reuse and stale files cannot satisfy it."""

    if not _valid_liveness_descriptor(layout, descriptor):
        raise PortableEnvironmentError(
            "启动器内核存活标识无效",
            code="launcher_liveness_unavailable",
        )
    if descriptor.startswith(WINDOWS_LIVENESS_DESCRIPTOR):
        if (sys.platform if platform is None else platform) != "win32":
            raise PortableEnvironmentError(
                "启动器存活对象与当前平台不匹配",
                code="launcher_liveness_unavailable",
            )
        api = _load_windows_liveness_api() if windows_api is None else windows_api
        name = descriptor.removeprefix(WINDOWS_LIVENESS_DESCRIPTOR)
        return _WindowsLauncherLivenessMonitor(api=api, name=name)
    path = Path(descriptor.removeprefix(POSIX_LIVENESS_DESCRIPTOR))
    return _PosixLauncherLivenessMonitor(layout, path)


def remove_stale_liveness_files(layout: paths.RuntimeLayout) -> tuple[Path, ...]:
    """Remove old POSIX name carriers after global instance ownership is acquired."""

    runtime_dir = layout.require_data_path(layout.runtime_dir, label="启动器存活目录")
    removed: list[Path] = []
    for candidate in runtime_dir.glob(f"{LIVENESS_FILE_PREFIX}*{LIVENESS_FILE_SUFFIX}"):
        safe = layout.require_data_path(candidate, label="陈旧启动器存活锁")
        try:
            safe.unlink()
        except FileNotFoundError:
            continue
        except OSError:
            continue
        removed.append(safe)
    return tuple(removed)


class LauncherLivenessWatchdog:
    """Monitor an exact per-launch kernel object; never infer identity from a PID."""

    def __init__(
        self,
        controller: PortableShutdownController,
        *,
        monitor: LauncherLivenessMonitor,
        interval: float = 2.0,
    ) -> None:
        self._controller = controller
        self._monitor = monitor
        self._interval = max(0.01, interval)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def run(self) -> None:
        failures = 0
        while not self._stop.wait(self._interval):
            try:
                gone = self._monitor.launcher_gone()
            except Exception:  # noqa: BLE001 - transient kernel query failure must not kill the service
                failures += 1
                if failures >= MAX_LIVENESS_QUERY_FAILURES:
                    self._controller.request("launcher_liveness_failed")
                    return
                continue
            failures = 0
            if gone:
                self._controller.request("launcher_exited")
                return

    def start(self) -> threading.Thread:
        if self._thread is not None:
            return self._thread
        self._thread = threading.Thread(target=self.run, name="pdf-reader-launcher-watchdog", daemon=True)
        self._thread.start()
        return self._thread

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.join(timeout=max(0.1, self._interval * 2))
        self._monitor.close()


def new_readiness_file(layout: paths.RuntimeLayout) -> Path:
    candidate = layout.temp_dir / f"{READINESS_FILE_PREFIX}{secrets.token_hex(12)}.json"
    return layout.require_data_path(candidate, label="服务就绪文件")


def remove_stale_readiness_files(layout: paths.RuntimeLayout) -> tuple[Path, ...]:
    """删除上一次异常退出留下的就绪文件；只允许持有单实例锁的启动器调用。"""

    temp_dir = layout.require_data_path(layout.temp_dir, label="服务临时目录根")
    if not temp_dir.is_dir():
        return ()
    removed: list[Path] = []
    for candidate in sorted(temp_dir.glob(f"{READINESS_FILE_PREFIX}*.json")):
        safe_candidate = layout.require_data_path(candidate, label="陈旧服务就绪文件")
        try:
            safe_candidate.unlink()
        except FileNotFoundError:
            continue
        except OSError:
            continue
        removed.append(safe_candidate)
    return tuple(removed)


def instance_record_path(layout: paths.RuntimeLayout) -> Path:
    return layout.require_data_path(layout.runtime_dir / INSTANCE_RECORD_NAME, label="实例记录")


def instance_lock_path(layout: paths.RuntimeLayout) -> Path:
    return layout.require_data_path(layout.runtime_dir / INSTANCE_LOCK_NAME, label="单实例锁")


def new_health_token() -> str:
    return secrets.token_urlsafe(32)


def new_control_token() -> str:
    return secrets.token_urlsafe(32)


def instance_lock_name(layout: paths.RuntimeLayout) -> str:
    """Resolved portable root 派生的稳定内核对象名（不泄漏用户名与绝对路径）。"""

    material = str(layout.portable_root or layout.data_root).replace("\\", "/").casefold().encode("utf-8")
    return f"Local\\pdf-reader-portable-{hashlib.sha256(material).hexdigest()[:24]}"


def loopback_base_url(host: str, port: int) -> str:
    """把已验证的 loopback 主机与端口规范化为 http://host:port/ 形式。

    非 loopback 主机、非法端口一律抛出 ValueError：调用方只能用它拼接受信任的本地
    地址，避免把状态文件里的任意字符串当成可连接目标。
    """

    if not isinstance(host, str):
        raise ValueError("loopback 主机必须是字符串")
    normalized = host.strip().lower()
    if not normalized:
        raise ValueError("loopback 主机不能为空")
    if normalized == "localhost":
        display_host = "localhost"
    else:
        try:
            address = ipaddress.ip_address(normalized)
        except ValueError as exc:
            raise ValueError(f"地址不是 loopback：{host}") from exc
        if not address.is_loopback:
            raise ValueError(f"地址不是 loopback：{host}")
        display_host = f"[{normalized}]" if address.version == 6 else normalized
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError(f"端口无效：{port}")
    return f"http://{display_host}:{port}/"


def loopback_port_in_use(host: str, port: int, *, timeout: float = LOOPBACK_PROBE_TIMEOUT) -> bool:
    """探测 loopback 端口是否已被监听；只发起只读连接，绝不终止或干扰占用者。

    - 连接被明确拒绝：端口空闲，可以安全绑定。
    - 连接成功：已有进程在监听，服务必须放弃启动并交给用户决定。
    - 其他不确定结果：保守判定为被占用；宁可给出可恢复提示，也不覆盖现有监听者。
    """

    loopback_base_url(host, port)
    try:
        with socket.create_connection((host, port), timeout=max(0.05, timeout)):
            return True
    except ConnectionRefusedError:
        return False
    except OSError:
        return True


def probe_loopback_health(
    host: str,
    port: int,
    token: str,
    *,
    timeout: float = LOOPBACK_PROBE_TIMEOUT,
) -> bool:
    """带令牌的真实健康探测：只有 200 与精确 payload 组合才算 ready。

    这是启动器判断“服务已经可以打开页面”的唯一依据；任何网络错误、非 200 状态、
    非 JSON 响应或令牌不匹配都返回 False，绝不猜测就绪。
    """

    if not isinstance(token, str) or len(token) < MINIMUM_TOKEN_LENGTH:
        return False
    url = f"{loopback_base_url(host, port)}api/health"
    request = urllib.request.Request(url, headers={HEALTH_TOKEN_HEADER: token})
    try:
        with urllib.request.urlopen(request, timeout=max(0.05, timeout)) as response:  # noqa: S310 - 固定 loopback
            payload = json.loads(response.read().decode("utf-8"))
            status = response.status
    except (OSError, ValueError, urllib.error.URLError):
        return False
    return bool(status == 200 and payload == {"status": "ok"})


def wait_for_port_release(
    host: str,
    port: int,
    *,
    timeout: float = PORT_RELEASE_TIMEOUT,
    interval: float = PORT_RELEASE_POLL_INTERVAL,
    probe: Callable[[str, int], bool] = loopback_port_in_use,
) -> bool:
    """有界等待一个仍在关闭中的旧服务释放端口；从不触碰占用者。

    只用于启动器确认“上一次异常退出的服务正在收尾”，避免把正常的重启延迟报告成
    端口冲突。超时返回 False，由调用方给出可恢复的说明。
    """

    loopback_base_url(host, port)
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        if not probe(host, port):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(max(0.01, interval))


def write_json_descriptor(
    layout: paths.RuntimeLayout,
    destination: str | Path,
    payload: dict[str, object],
) -> Path:
    """Atomically publish one JSON descriptor inside portable data."""

    return _write_descriptor(layout, destination, payload)


def read_json_descriptor(layout: paths.RuntimeLayout, destination: str | Path) -> dict[str, object] | None:
    """Read one owned JSON descriptor; None when absent, ValueError when corrupt."""

    target = layout.require_data_path(destination, label="服务状态文件")
    try:
        raw = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ValueError(f"服务状态文件不可读：{target}") from exc
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError(f"服务状态文件不是 JSON 对象：{target}")
    return payload


def _write_descriptor(layout: paths.RuntimeLayout, destination: str | Path, payload: dict[str, object]) -> Path:
    target = layout.require_data_path(destination, label="服务状态文件")
    temporary = layout.require_data_path(
        target.with_name(f".{target.name}.{secrets.token_hex(8)}.tmp"),
        label="服务状态临时文件",
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    try:
        temporary.write_text(body, encoding="utf-8")
        if os.name != "nt":
            # 便携状态与令牌只允许落在 data/ 内安全路径，POSIX 下再收紧为属主可读写。
            os.chmod(temporary, LOCK_FILE_MODE)
        os.replace(temporary, target)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return target


def write_readiness_descriptor(
    layout: paths.RuntimeLayout,
    destination: str | Path,
    *,
    host: str,
    port: int,
    health_token: str,
) -> Path:
    """Atomically publish loopback endpoint metadata inside portable data."""

    if len(health_token) < MINIMUM_TOKEN_LENGTH:
        raise PortableEnvironmentError(
            "便携服务健康检查令牌无效",
            code="portable_service_health_token_invalid",
        )
    return _write_descriptor(
        layout,
        destination,
        {
            "schema": READINESS_SCHEMA,
            "status": READINESS_STATUS_READY,
            "host": host,
            "port": port,
            "health_token": health_token,
        },
    )


def write_readiness_failure(
    layout: paths.RuntimeLayout,
    destination: str | Path,
    *,
    code: str,
    message: str,
) -> Path:
    """Publish a stable failure reason so the launcher never guesses from exit codes alone."""

    return _write_descriptor(
        layout,
        destination,
        {
            "schema": READINESS_SCHEMA,
            "status": READINESS_STATUS_ERROR,
            "code": code,
            "message": message[:MAXIMUM_DESCRIPTOR_MESSAGE_LENGTH],
        },
    )


def remove_descriptor(layout: paths.RuntimeLayout, destination: str | Path) -> None:
    """Remove one owned descriptor path inside portable data; missing files are ignored."""

    target = layout.require_data_path(destination, label="服务状态文件")
    try:
        target.unlink()
    except FileNotFoundError:
        pass


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
