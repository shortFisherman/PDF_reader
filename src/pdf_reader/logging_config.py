"""核心日志管线：统一 SafeFormatter、共享控制台/RotatingFileHandler、第三方托管与异常钩子。

设计约定：

- ``setup_logging`` 把同一对 handler（控制台 + ``logs/pdf_reader.log`` 轮转文件）
  挂到 ``pdf_reader``、``werkzeug``、``pdf2zh_next``、``babeldoc`` 四个 logger；
  默认第三方 WARNING，debug 模式第三方 DEBUG。四个托管 logger 均
  ``propagate=False`` 且 ``disabled=False``，避免经 root/lastResort/旧 handler
  绕过脱敏或重复输出；``reset_logging`` 精确恢复快照。
- 所有主日志行带 ISO 风格时间、level、run_id、pid、thread、logger，保持人类可读。
- 主日志按 128 KiB × 5 轮转（常规上限约 768 KiB），并在 setup 启动与每次轮转后
  清理本日志自身 mtime 超过 14 天的编号备份；清理失败仅记 warning，不影响写入/启动，
  且不会递归记录。
- 安装安全的 ``sys.excepthook`` 与 ``threading.excepthook``，把未捕获异常写入统一
  日志；普通异常记录成功后不再调用原 hook（避免 secret 原样打印 stderr），
  KeyboardInterrupt/SystemExit 与记录失败时回退原 hook。
- ``run_id`` 每个 setup 生命周期唯一（reset 后重新生成）。
- 全局状态变更（setup/reset/attach/detach）由 RLock 串行化，避免并发竞态；
  锁内不进行任何日志 emit，避免死锁。
"""

import logging
import re
import secrets
import sys
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType
from typing import Any

from pdf_reader import paths
from pdf_reader.task_logging import SafeFormatter

LOG_DIR = paths.get_log_dir()

MANAGED_LOGGER_NAMES: tuple[str, ...] = ("pdf_reader", "werkzeug", "pdf2zh_next", "babeldoc")
THIRD_PARTY_LOGGER_NAMES: tuple[str, ...] = MANAGED_LOGGER_NAMES[1:]

MAIN_LOG_FORMAT = (
    "%(asctime)s %(levelname)s run_id=%(run_id)s pid=%(process)d thread=%(threadName)s logger=%(name)s [%(message)s]"
)
MAIN_LOG_MAX_BYTES = 128 * 1024
MAIN_LOG_BACKUP_COUNT = 5
MAIN_LOG_BACKUP_MAX_AGE_SECONDS = 14 * 24 * 60 * 60
_BACKUP_SUFFIX_RE = re.compile(r"[1-9]\d*")


class PipelineSafeFormatter(SafeFormatter):
    """统一管线 formatter：ISO 风格时间 + run_id 注入，脱敏契约不变。"""

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        ct = self.converter(record.created)
        if datefmt is not None:
            return time.strftime(datefmt, ct)
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S%z", ct)
        msecs = f"{int(record.msecs):03d}"
        if len(stamp) > 19 and stamp[19] in "+-":
            return f"{stamp[:19]}.{msecs}{stamp[19:]}"
        return f"{stamp}.{msecs}"

    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, "run_id") or record.run_id is None:
            record.run_id = get_run_id() or "-"
        return super().format(record)


_PIPELINE_FORMATTER = PipelineSafeFormatter(MAIN_LOG_FORMAT)


def make_safe_formatter() -> SafeFormatter:
    """返回统一管线共享的 SafeFormatter（主日志与 debug trace 同一格式）。"""
    return _PIPELINE_FORMATTER


_run_id: str | None = None


def get_run_id() -> str | None:
    """当前 setup 生命周期的 run_id；未 setup 时为 None。"""
    return _run_id


@dataclass
class _LoggerState:
    level: int
    propagate: bool
    disabled: bool
    handlers: list[logging.Handler]


_state: dict[str, _LoggerState] = {}
_managed_handlers: list[logging.Handler] = []
_LOCK = threading.RLock()


def managed_logger_names() -> tuple[str, ...]:
    return MANAGED_LOGGER_NAMES


def managed_loggers() -> list[logging.Logger]:
    return [logging.getLogger(name) for name in MANAGED_LOGGER_NAMES]


def attach_handler(handler: logging.Handler, logger_names: Iterable[str] | None = None) -> None:
    """把 handler 挂到指定（默认全部托管）logger；同一实例不重复挂载。"""
    with _LOCK:
        names = tuple(logger_names) if logger_names is not None else MANAGED_LOGGER_NAMES
        for name in names:
            logger = logging.getLogger(name)
            if handler not in logger.handlers:
                logger.addHandler(handler)


def detach_handler(handler: logging.Handler, logger_names: Iterable[str] | None = None) -> None:
    """从指定（默认全部托管）logger 摘掉 handler。"""
    with _LOCK:
        names = tuple(logger_names) if logger_names is not None else MANAGED_LOGGER_NAMES
        for name in names:
            logger = logging.getLogger(name)
            while handler in logger.handlers:
                logger.removeHandler(handler)


def _add_handler_once(logger: logging.Logger, handler: logging.Handler) -> None:
    if handler not in logger.handlers:
        logger.addHandler(handler)


def _close_handler(handler: logging.Handler) -> None:
    try:
        handler.close()
    except Exception:
        pass


def _cleanup_expired_backups(log_path: Path, max_age_seconds: int) -> list[str]:
    """删除 ``log_path`` 自身 mtime 超过 ``max_age_seconds`` 的编号轮转备份。

    只匹配 ``<name>.<正整数>``（例如 ``pdf_reader.log.1``）；主日志本身、
    debug_trace 文件、非编号后缀与目录一律不触碰。任何失败只以字符串返回，
    调用方负责安全降级（记录 warning），本函数绝不抛出。
    """
    errors: list[str] = []
    cutoff = time.time() - max_age_seconds
    prefix = log_path.name + "."
    try:
        entries = list(log_path.parent.iterdir())
    except OSError as exc:
        return [f"cannot list {log_path.parent}: {exc}"]
    for entry in entries:
        name = entry.name
        if not name.startswith(prefix):
            continue
        if not _BACKUP_SUFFIX_RE.fullmatch(name[len(prefix) :]):
            continue
        try:
            if not entry.is_file():
                continue
            mtime = entry.stat().st_mtime
        except OSError as exc:
            errors.append(f"cannot stat backup {name}: {exc}")
            continue
        if mtime >= cutoff:
            continue
        try:
            entry.unlink()
        except OSError as exc:
            errors.append(f"cannot remove expired backup {name}: {exc}")
    return errors


def _log_main_backup_cleanup_warning(errors: Iterable[str]) -> None:
    """清理失败仅记 warning；任何日志异常都不向上抛，避免影响启动/写入。"""
    try:
        logging.getLogger("pdf_reader").warning("Failed to clean expired pdf_reader.log backups: %s", "; ".join(errors))
    except Exception:
        pass


def _capture_logger_state() -> None:
    for name in MANAGED_LOGGER_NAMES:
        logger = logging.getLogger(name)
        _state[name] = _LoggerState(
            level=logger.level,
            propagate=logger.propagate,
            disabled=logger.disabled,
            handlers=list(logger.handlers),
        )


def _new_run_id() -> str:
    return secrets.token_hex(6)


class RetentionRotatingFileHandler(RotatingFileHandler):
    """主日志轮转 handler：标准追加/轮转顺序 + 过期备份清理。

    - 保持 RotatingFileHandler 原样的追加与 ``base -> .1 -> ...`` 轮转顺序。
    - 每次 ``doRollover`` 后清理一次本日志自身的过期编号备份；setup 启动时的
      首次清理由 ``setup_logging`` 显式调用同一清理函数完成。
    - 清理失败只记 warning，不抛出，不影响写入与启动。
    - ``_in_rollover`` 守卫避免清理告警自身再次触发轮转/清理（递归日志）。
    """

    _in_rollover = False

    def doRollover(self) -> None:
        if self._in_rollover:
            return
        self._in_rollover = True
        try:
            super().doRollover()
            errors = _cleanup_expired_backups(Path(self.baseFilename), MAIN_LOG_BACKUP_MAX_AGE_SECONDS)
            if errors:
                _log_main_backup_cleanup_warning(errors)
        finally:
            self._in_rollover = False


def setup_logging(debug: bool = False) -> None:
    """统一配置核心日志管线；重复调用不叠加 handler，但会更新级别。

    debug off 时主级别 INFO、第三方 WARNING；debug on 时主级别与第三方均为 DEBUG。
    每次 setup 启动时清理本日志超过 14 天的轮转备份；清理失败仅记 warning。
    """
    global _run_id
    init_cleanup_errors: list[str] = []
    with _LOCK:
        if not _state:
            _capture_logger_state()
            _run_id = _new_run_id()
            _install_excepthooks()

        # 先摘掉当前挂载的 handler：只关闭我们此前创建的 handler；外部既有 handler
        # 仅摘除（避免其绕过脱敏），reset 时原样恢复。
        for name in MANAGED_LOGGER_NAMES:
            logger = logging.getLogger(name)
            for handler in list(logger.handlers):
                logger.removeHandler(handler)
                if handler in _managed_handlers:
                    _close_handler(handler)
        _managed_handlers.clear()

        LOG_DIR.mkdir(parents=True, exist_ok=True)
        init_cleanup_errors = _cleanup_expired_backups(LOG_DIR / "pdf_reader.log", MAIN_LOG_BACKUP_MAX_AGE_SECONDS)

        formatter = make_safe_formatter()
        level = logging.DEBUG if debug else logging.INFO

        console = logging.StreamHandler(sys.stdout)
        console.setLevel(level)
        console.setFormatter(formatter)

        file_handler = RetentionRotatingFileHandler(
            str(LOG_DIR / "pdf_reader.log"),
            maxBytes=MAIN_LOG_MAX_BYTES,
            backupCount=MAIN_LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)

        for logger in managed_loggers():
            _add_handler_once(logger, console)
            _add_handler_once(logger, file_handler)
        _managed_handlers.extend((console, file_handler))

        logging.getLogger("pdf_reader").setLevel(level)

        third_party_level = logging.DEBUG if debug else logging.WARNING
        for name in THIRD_PARTY_LOGGER_NAMES:
            logging.getLogger(name).setLevel(third_party_level)
        for name in MANAGED_LOGGER_NAMES:
            logger = logging.getLogger(name)
            logger.propagate = False
            logger.disabled = False

    if init_cleanup_errors:
        _log_main_backup_cleanup_warning(init_cleanup_errors)


def reset_logging() -> None:
    """恢复被托管 logger 的既有状态并移除本管线创建/会话期挂载的 handler。"""
    global _run_id
    with _LOCK:
        _restore_excepthooks()

        if _state:
            for name in MANAGED_LOGGER_NAMES:
                snapshot = _state[name]
                logger = logging.getLogger(name)
                for handler in list(logger.handlers):
                    logger.removeHandler(handler)
                    if handler not in snapshot.handlers:
                        _close_handler(handler)
            for name in MANAGED_LOGGER_NAMES:
                snapshot = _state.pop(name)
                logger = logging.getLogger(name)
                logger.setLevel(snapshot.level)
                logger.propagate = snapshot.propagate
                logger.disabled = snapshot.disabled
                for handler in snapshot.handlers:
                    if handler not in logger.handlers:
                        logger.addHandler(handler)
        else:
            # 无托管快照时的兼容清理：仅移除并关闭全部 handler（保持旧 reset 语义，
            # 不动外部设置的 level/propagate/disabled）。
            for name in MANAGED_LOGGER_NAMES:
                logger = logging.getLogger(name)
                for handler in list(logger.handlers):
                    logger.removeHandler(handler)
                    _close_handler(handler)

        for handler in _managed_handlers:
            _close_handler(handler)
        _managed_handlers.clear()
        _run_id = None


_original_sys_excepthook: Callable[[type[BaseException], BaseException, TracebackType | None], Any] | None = None
_original_threading_excepthook: Callable[[threading.ExceptHookArgs], Any] | None = None
_hooks_installed = False
_hook_guard_depth = threading.local()


class _HookGuard:
    """嵌套调用时保持“已在 hook 中”标记，避免 sys/threading hook 互调重复记录。"""

    def __enter__(self) -> None:
        _hook_guard_depth.depth = getattr(_hook_guard_depth, "depth", 0) + 1

    def __exit__(self, *_exc: object) -> None:
        depth = getattr(_hook_guard_depth, "depth", 1) - 1
        if depth <= 0:
            try:
                del _hook_guard_depth.depth
            except AttributeError:
                pass
        else:
            _hook_guard_depth.depth = depth


def _in_hook() -> bool:
    return getattr(_hook_guard_depth, "depth", 0) > 0


def _install_excepthooks() -> None:
    global _original_sys_excepthook, _original_threading_excepthook, _hooks_installed
    if _hooks_installed:
        return
    _original_sys_excepthook = sys.excepthook
    _original_threading_excepthook = threading.excepthook
    sys.excepthook = _sys_excepthook
    threading.excepthook = _threading_excepthook
    _hooks_installed = True


def _restore_excepthooks() -> None:
    global _original_sys_excepthook, _original_threading_excepthook, _hooks_installed
    if not _hooks_installed:
        return
    if sys.excepthook is _sys_excepthook and _original_sys_excepthook is not None:
        sys.excepthook = _original_sys_excepthook
    if threading.excepthook is _threading_excepthook and _original_threading_excepthook is not None:
        threading.excepthook = _original_threading_excepthook
    _original_sys_excepthook = None
    _original_threading_excepthook = None
    _hooks_installed = False


def _log_uncaught_exception(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_tb: TracebackType | None,
    thread_name: str | None = None,
) -> bool:
    """把未捕获异常写入统一日志；成功返回 True，失败返回 False（供回退原 hook）。"""
    try:
        label = thread_name or threading.current_thread().name
        logging.getLogger("pdf_reader").error(
            "unhandled exception thread=%s type=%s",
            label,
            getattr(exc_type, "__name__", str(exc_type)),
            exc_info=(exc_type, exc_value, exc_tb),
        )
        return True
    except Exception:
        return False


def _call_original_sys_hook(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_tb: TracebackType | None,
) -> None:
    original = _original_sys_excepthook
    if original is not None:
        with _HookGuard():
            original(exc_type, exc_value, exc_tb)


def _call_original_threading_hook(args: threading.ExceptHookArgs) -> None:
    original = _original_threading_excepthook
    if original is not None:
        with _HookGuard():
            original(args)


def _sys_excepthook(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_tb: TracebackType | None,
) -> None:
    if exc_type is KeyboardInterrupt or exc_type is SystemExit or _in_hook():
        _call_original_sys_hook(exc_type, exc_value, exc_tb)
        return
    if not _log_uncaught_exception(exc_type, exc_value, exc_tb):
        # 统一记录失败时回退原 hook，避免完全静默。
        _call_original_sys_hook(exc_type, exc_value, exc_tb)


def _threading_excepthook(args: threading.ExceptHookArgs) -> None:
    if args.exc_type is KeyboardInterrupt or args.exc_type is SystemExit or _in_hook():
        _call_original_threading_hook(args)
        return
    if args.exc_value is None:
        _call_original_threading_hook(args)
        return
    thread_name = args.thread.name if args.thread is not None else None
    if not _log_uncaught_exception(args.exc_type, args.exc_value, args.exc_traceback, thread_name=thread_name):
        # 统一记录失败时回退原 hook，避免完全静默。
        _call_original_threading_hook(args)
