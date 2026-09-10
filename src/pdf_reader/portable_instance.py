"""Single-instance ownership and instance activation for the portable launcher.

Stdlib-only: the top-level launcher imports this module before any application
code, so it must never import Flask, pdf2zh-next, BabelDOC, or ``pdf_reader.app``.

Two mechanisms are intentionally combined:

* A kernel-owned lock (named Windows mutex, or ``flock`` on POSIX) is the only
  authority for "an instance is running".  The kernel releases it when the
  owning process dies, so a crash or forced kill can never leave a stale lock.
* A record inside ``DATA_ROOT/runtime`` carries the loopback endpoints and the
  per-launch tokens that a second launch needs to verify and activate the
  running instance.  The record is *advisory*: it is only trusted after a
  token-authenticated health probe and it is always removed on clean shutdown.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from pdf_reader import paths
from pdf_reader.portable_runtime import (
    CONTROL_COMMANDS,
    CONTROL_PATH,
    CONTROL_TOKEN_HEADER,
    MINIMUM_TOKEN_LENGTH,
    SHUTDOWN_PATH,
    PortableEnvironmentError,
    instance_lock_name,
    instance_lock_path,
    instance_record_path,
    loopback_base_url,
    probe_loopback_health,
    read_json_descriptor,
    write_json_descriptor,
)

INSTANCE_RECORD_SCHEMA = 1
DEFAULT_PROBE_TIMEOUT = 2.0


class PortableInstanceError(RuntimeError):
    """Single-instance coordination failure with a stable ``code`` for the user."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class InstanceLock(Protocol):
    """Kernel-lifetime lock: ``acquire`` is atomic and ``release`` is idempotent."""

    def acquire(self) -> bool: ...

    def release(self) -> None: ...


class KernelApi(Protocol):
    """Minimal Windows kernel surface used by :class:`WindowsMutexLock` (injectable in tests)."""

    def create_mutex(self, name: str) -> tuple[int, bool]: ...

    def close_handle(self, handle: int) -> None: ...


def _load_kernel_api() -> KernelApi:
    """加载只读 Windows 命名互斥体 API；非 Windows 或加载失败时给出稳定错误码。"""

    if sys.platform != "win32":
        raise PortableEnvironmentError(
            "当前平台没有可用的命名互斥体实现",
            code="instance_lock_unavailable",
        )
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel32.CloseHandle.restype = ctypes.c_bool
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

    class _Kernel32Api:
        def create_mutex(self, name: str) -> tuple[int, bool]:
            handle = kernel32.CreateMutexW(None, False, name)
            already_exists = ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS
            return int(handle or 0), already_exists

        def close_handle(self, handle: int) -> None:
            kernel32.CloseHandle(ctypes.c_void_p(handle))

    return _Kernel32Api()


class WindowsMutexLock:
    """Named-mutex ownership; the kernel drops it when the owning process dies."""

    def __init__(self, name: str, *, kernel_api: KernelApi | None = None) -> None:
        self._name = name
        self._kernel_api = kernel_api
        self._handle: int | None = None

    @property
    def name(self) -> str:
        return self._name

    def acquire(self) -> bool:
        api = self._kernel_api if self._kernel_api is not None else _load_kernel_api()
        handle, already_exists = api.create_mutex(self._name)
        if not handle:
            raise PortableEnvironmentError(
                "无法创建 PDF Reader 单实例互斥体",
                code="instance_lock_unavailable",
            )
        if already_exists:
            api.close_handle(handle)
            return False
        self._handle = handle
        return True

    def release(self) -> None:
        handle = self._handle
        if handle is None:
            return
        self._handle = None
        api = self._kernel_api if self._kernel_api is not None else _load_kernel_api()
        api.close_handle(handle)


class PosixFileLock:
    """``flock`` ownership; the kernel drops it when the owning process dies."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._handle: int | None = None

    @property
    def path(self) -> Path:
        return self._path

    def acquire(self) -> bool:
        import fcntl

        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            handle = os.open(self._path, os.O_CREAT | os.O_RDWR, 0o600)
        except OSError as exc:
            raise PortableEnvironmentError(
                f"无法创建单实例锁文件：{self._path}",
                code="instance_lock_unavailable",
            ) from exc
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(handle)
            return False
        self._handle = handle
        return True

    def release(self) -> None:
        handle = self._handle
        if handle is None:
            return
        self._handle = None
        try:
            import fcntl

            fcntl.flock(handle, fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            os.close(handle)


def create_instance_lock(
    layout: paths.RuntimeLayout,
    *,
    kernel_api: KernelApi | None = None,
    platform: str | None = None,
) -> InstanceLock:
    """Return the kernel-owned single-instance lock for one portable root."""

    selected_platform = sys.platform if platform is None else platform
    if selected_platform == "win32":
        return WindowsMutexLock(instance_lock_name(layout), kernel_api=kernel_api)
    return PosixFileLock(instance_lock_path(layout))


def _require_positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"实例记录 {field} 必须是正整数")
    return value


def _require_port(value: object, field: str) -> int:
    port = _require_positive_int(value, field)
    if port > 65535:
        raise ValueError(f"实例记录 {field} 超出端口范围")
    return port


def _require_token(value: object, field: str) -> str:
    if not isinstance(value, str) or len(value) < MINIMUM_TOKEN_LENGTH:
        raise ValueError(f"实例记录 {field} 不是有效令牌")
    return value


def _require_loopback_host(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"实例记录 {field} 不是字符串")
    loopback_base_url(value, 1)
    return value


@dataclass(frozen=True)
class InstanceRecord:
    """Advisory metadata published by the launcher that currently owns the lock."""

    pid: int
    created_at: str
    launcher_host: str
    launcher_port: int
    control_token: str = field(repr=False)
    service_host: str
    service_port: int
    health_token: str = field(repr=False)
    service_control_token: str = field(repr=False)

    def __post_init__(self) -> None:
        _require_positive_int(self.pid, "pid")
        if not isinstance(self.created_at, str) or not self.created_at:
            raise ValueError("实例记录 created_at 不能为空")
        _require_loopback_host(self.launcher_host, "launcher_host")
        _require_port(self.launcher_port, "launcher_port")
        _require_token(self.control_token, "control_token")
        _require_loopback_host(self.service_host, "service_host")
        _require_port(self.service_port, "service_port")
        _require_token(self.health_token, "health_token")
        _require_token(self.service_control_token, "service_control_token")

    @property
    def service_url(self) -> str:
        return loopback_base_url(self.service_host, self.service_port)

    def to_payload(self) -> dict[str, object]:
        return {
            "schema": INSTANCE_RECORD_SCHEMA,
            "pid": self.pid,
            "created_at": self.created_at,
            "launcher": {
                "host": self.launcher_host,
                "port": self.launcher_port,
                "control_token": self.control_token,
            },
            "service": {
                "host": self.service_host,
                "port": self.service_port,
                "health_token": self.health_token,
                "control_token": self.service_control_token,
            },
        }

    @classmethod
    def from_payload(cls, payload: object) -> InstanceRecord:
        if not isinstance(payload, dict) or payload.get("schema") != INSTANCE_RECORD_SCHEMA:
            raise ValueError("实例记录 schema 不匹配")
        launcher = payload.get("launcher")
        service = payload.get("service")
        if not isinstance(launcher, dict) or not isinstance(service, dict):
            raise ValueError("实例记录缺少 launcher/service 段")
        return cls(
            pid=_require_positive_int(payload.get("pid"), "pid"),
            created_at=str(payload.get("created_at", "")),
            launcher_host=_require_loopback_host(launcher.get("host"), "launcher_host"),
            launcher_port=_require_port(launcher.get("port"), "launcher_port"),
            control_token=_require_token(launcher.get("control_token"), "control_token"),
            service_host=_require_loopback_host(service.get("host"), "service_host"),
            service_port=_require_port(service.get("port"), "service_port"),
            health_token=_require_token(service.get("health_token"), "health_token"),
            service_control_token=_require_token(service.get("control_token"), "service_control_token"),
        )


def write_instance_record(layout: paths.RuntimeLayout, record: InstanceRecord) -> Path:
    return write_json_descriptor(layout, instance_record_path(layout), record.to_payload())


def read_instance_record(layout: paths.RuntimeLayout) -> InstanceRecord | None:
    """Return the published record, ``None`` when absent, or raise on corrupt metadata."""

    try:
        payload = read_json_descriptor(layout, instance_record_path(layout))
    except (OSError, ValueError, paths.PathStrategyError) as exc:
        # 崩溃或强制结束可能留下半截文件；陈旧状态必须是可判定的失败码，
        # 而不是让启动器在无法归类的异常里终止。
        raise PortableInstanceError(
            f"实例状态文件不可用：{exc}",
            code="instance_record_invalid",
        ) from exc
    if payload is None:
        return None
    try:
        return InstanceRecord.from_payload(payload)
    except ValueError as exc:
        raise PortableInstanceError(
            f"实例状态文件不可用：{exc}",
            code="instance_record_invalid",
        ) from exc


def remove_instance_record(layout: paths.RuntimeLayout) -> None:
    record_path = instance_record_path(layout)
    try:
        record_path.unlink()
    except FileNotFoundError:
        pass


def probe_service_health(record: InstanceRecord, *, timeout: float = DEFAULT_PROBE_TIMEOUT) -> bool:
    """Token-authenticated readiness probe of the running instance's service."""

    return probe_loopback_health(record.service_host, record.service_port, record.health_token, timeout=timeout)


def send_launcher_command(
    record: InstanceRecord,
    command: str,
    *,
    timeout: float = DEFAULT_PROBE_TIMEOUT,
) -> str:
    """Ask the running launcher to execute one control command; raises with stable codes.

    返回启动器给出的处置说明（如 opened/unavailable），调用方据此决定退出码；
    令牌不匹配的请求在服务端表现为 404，这里统一转成 launcher_control_rejected。
    """

    if command not in CONTROL_COMMANDS:
        raise ValueError(f"未知控制命令：{command}")
    request = urllib.request.Request(
        f"{loopback_base_url(record.launcher_host, record.launcher_port)}{CONTROL_PATH.lstrip('/')}",
        data=json.dumps({"command": command}).encode("utf-8"),
        headers={CONTROL_TOKEN_HEADER: record.control_token, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=max(0.1, timeout)) as response:  # noqa: S310 - fixed loopback http URL
            payload = json.loads(response.read().decode("utf-8"))
            status = response.status
    except urllib.error.HTTPError as exc:
        raise PortableInstanceError(
            f"已运行的 PDF Reader 实例拒绝了控制请求（HTTP {exc.code}）",
            code="launcher_control_rejected",
        ) from exc
    except (OSError, ValueError, urllib.error.URLError) as exc:
        raise PortableInstanceError(
            f"无法连接已运行的 PDF Reader 实例：{exc}",
            code="launcher_control_unreachable",
        ) from exc
    if status != 200 or not isinstance(payload, dict) or payload.get("status") != "accepted":
        raise PortableInstanceError(
            "已运行的 PDF Reader 实例返回了意外的控制响应",
            code="launcher_control_rejected",
        )
    detail = payload.get("detail")
    return detail if isinstance(detail, str) else ""


def send_service_shutdown(
    record: InstanceRecord,
    *,
    timeout: float = DEFAULT_PROBE_TIMEOUT,
) -> None:
    """请求运行中的服务协作退出；失败时抛出稳定的 PortableInstanceError。

    只有拿到实例记录里令牌的调用方才能触发；服务端拒绝或不可达都不会终止任何进程，
    调用方据此决定是重试、报告还是走最后的兜底路径。
    """

    request = urllib.request.Request(
        f"{record.service_url}{SHUTDOWN_PATH.lstrip('/')}",
        data=b"{}",
        headers={CONTROL_TOKEN_HEADER: record.service_control_token, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=max(0.1, timeout)) as response:  # noqa: S310 - fixed loopback http URL
            payload = json.loads(response.read().decode("utf-8"))
            status = response.status
    except urllib.error.HTTPError as exc:
        raise PortableInstanceError(
            f"运行中的 PDF Reader 服务拒绝了退出请求（HTTP {exc.code}）",
            code="service_shutdown_rejected",
        ) from exc
    except (OSError, ValueError, urllib.error.URLError) as exc:
        raise PortableInstanceError(
            f"无法连接运行中的 PDF Reader 服务：{exc}",
            code="service_shutdown_unreachable",
        ) from exc
    if status != 202 or not isinstance(payload, dict) or payload.get("status") != "shutting_down":
        raise PortableInstanceError(
            "运行中的 PDF Reader 服务返回了意外的退出响应",
            code="service_shutdown_rejected",
        )
