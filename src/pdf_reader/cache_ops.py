"""缓存分类、只读统计与孤儿翻译临时工作区清理（P3-05）。

安全边界：

- 用户有价值数据（``right.pdf``、``cumulative_glossary.csv``、``reading_progress.json``、
  手动术语表）永不作为临时文件处理；本模块只识别**直接位于 cache_dir 下**、
  名称带固定前缀**且**含标记文件的翻译输出工作区。
- 清理默认 dry-run；真正删除前逐项核验标记与 PID 存活状态；未知/无标记目录一律保留。
- 统计与清理都只读遍历，不读取文件内容。
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

TEMP_WORKSPACE_PREFIX = "pdf-reader-translation-"
TEMP_MARKER_NAME = ".pdf-reader-temp-workspace"


@dataclass(frozen=True)
class DocumentCacheStats:
    """单个文档缓存目录（cache/<hash>/）的组成统计。"""

    hash_dir: Path
    right_pdf_bytes: int = 0
    glossary_bytes: int = 0
    reading_progress_present: bool = False
    debug_trace_bytes: int = 0


@dataclass(frozen=True)
class CacheStats:
    cache_dir: Path
    documents: tuple[DocumentCacheStats, ...] = ()
    temp_workspaces: tuple[Path, ...] = ()
    temp_workspace_bytes: int = 0


@dataclass(frozen=True)
class CleanupReport:
    scanned: int = 0
    removed: tuple[Path, ...] = ()
    kept_unknown: tuple[Path, ...] = ()
    kept_live_pid: tuple[Path, ...] = ()
    kept_recent: tuple[Path, ...] = ()
    errors: tuple[str, ...] = ()
    dry_run: bool = True


@dataclass
class TempWorkspace:
    path: Path
    marked: bool
    marker_pid: int | None = None
    marker_age_seconds: float | None = None


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _is_linkish(path: Path) -> bool:
    """目录链接/连接点检测：符号链接或 Windows junction 一律按链接处理。"""
    if path.is_symlink():
        return True
    if os.name == "nt":
        try:
            return path.is_junction()
        except AttributeError:
            return False
    return False


def _dir_size(path: Path) -> int:
    total = 0
    try:
        for child in path.rglob("*"):
            if _is_linkish(child):
                continue
            if child.is_file():
                total += _file_size(child)
    except OSError:
        pass
    return total


def _read_marker(dir_path: Path) -> dict:
    marker = dir_path / TEMP_MARKER_NAME
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_temp_marker(dir_path: Path, *, job_id: str, pid: int | None = None) -> None:
    """写入翻译临时工作区标记（由 sse_stream 在创建输出目录后调用）。"""
    marker = {
        "kind": "pdf-reader-translation-temp",
        "job_id": job_id,
        "pid": pid if pid is not None else os.getpid(),
        "created_at": datetime.now(UTC).isoformat(),
    }
    (dir_path / TEMP_MARKER_NAME).write_text(
        json.dumps(marker, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _is_live_pid(pid: int | None) -> bool:
    if pid is None or pid <= 0:
        return False
    if os.name == "nt":
        return _windows_pid_alive(pid)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    except Exception:
        return True
    return True


def _windows_pid_alive(pid: int) -> bool:
    """Windows 安全存活探测：OpenProcess + GetExitCodeProcess。

    Windows 上不能使用 ``os.kill(pid, 0)``（会 TerminateProcess 直接杀死目标
    进程），因此用只读查询权限打开进程并读取退出码判断是否仍在运行；查询失败
    时按“可能存活”保守处理，宁保留不误删。
    """
    import ctypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        exit_code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return True
        return exit_code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def list_temp_workspaces(cache_dir: Path) -> list[TempWorkspace]:
    """只读列出 cache_dir 直接子项中名称带前缀的目录（含未标记项，供保守报告）。"""
    if not cache_dir.is_dir():
        return []
    result: list[TempWorkspace] = []
    try:
        entries = sorted(cache_dir.iterdir(), key=lambda p: p.name)
    except OSError:
        return result
    for entry in entries:
        if not entry.name.startswith(TEMP_WORKSPACE_PREFIX):
            continue
        if not (entry.is_dir() or entry.is_symlink()):
            continue
        marker = _read_marker(entry)
        pid = marker.get("pid")
        pid_ok = isinstance(pid, int) and not isinstance(pid, bool) and pid > 0
        kind_ok = marker.get("kind") == "pdf-reader-translation-temp"
        # 只把“前缀 + 有效标记 + 非符号链接”的目录视为可验证归属的临时工作区；
        # 符号链接可能指向文档缓存或其他外部目录，一律按未知保守保留。
        marked = bool(kind_ok and pid_ok and not _is_linkish(entry))
        created_at = marker.get("created_at")
        age = None
        if isinstance(created_at, str):
            try:
                parsed = datetime.fromisoformat(created_at)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=UTC)
                age = max(0.0, (datetime.now(UTC) - parsed).total_seconds())
            except ValueError:
                age = None
        result.append(
            TempWorkspace(
                path=entry,
                marked=marked,
                marker_pid=pid if pid_ok else None,
                marker_age_seconds=age,
            )
        )
    return result


def stats(cache_dir: Path) -> CacheStats:
    """只读缓存统计：文档缓存目录组成 + 临时工作区数量/大小。"""
    if not cache_dir.is_dir():
        return CacheStats(cache_dir=cache_dir)
    documents: list[DocumentCacheStats] = []
    try:
        entries = sorted(cache_dir.iterdir(), key=lambda p: p.name)
    except OSError:
        return CacheStats(cache_dir=cache_dir)
    for entry in entries:
        if (
            not entry.is_dir()
            or _is_linkish(entry)
            or entry.name.startswith(TEMP_WORKSPACE_PREFIX)
            or not (entry / "right.pdf").is_file()
        ):
            continue
        documents.append(
            DocumentCacheStats(
                hash_dir=entry,
                right_pdf_bytes=_file_size(entry / "right.pdf"),
                glossary_bytes=_file_size(entry / "cumulative_glossary.csv"),
                reading_progress_present=(entry / "reading_progress.json").is_file(),
                debug_trace_bytes=_file_size(entry / "debug_trace.log"),
            )
        )
    workspaces = list_temp_workspaces(cache_dir)
    total_temp = sum(_dir_size(item.path) for item in workspaces)
    return CacheStats(
        cache_dir=cache_dir,
        documents=tuple(documents),
        temp_workspaces=tuple(item.path for item in workspaces),
        temp_workspace_bytes=total_temp,
    )


def cleanup_orphan_temp_workspaces(
    cache_dir: Path,
    *,
    dry_run: bool = True,
    min_age_seconds: float | None = None,
    skip_live_pid: bool = True,
) -> CleanupReport:
    """清理可识别的孤儿翻译临时工作区。

    只删除：cache_dir 直接子目录 + 名称带固定前缀 + 含有效标记。未知/无标记、
    PID 仍存活（skip_live_pid=True 时）或未达到 min_age_seconds 的目录保留。
    绝不删除 ``right.pdf``、术语表、阅读进度或任何文档缓存目录。
    """
    workspaces = list_temp_workspaces(cache_dir)
    removed: list[Path] = []
    kept_unknown: list[Path] = []
    kept_live: list[Path] = []
    kept_recent: list[Path] = []
    errors: list[str] = []

    for item in workspaces:
        if not item.marked or _is_linkish(item.path):
            kept_unknown.append(item.path)
            continue
        if skip_live_pid and _is_live_pid(item.marker_pid):
            kept_live.append(item.path)
            continue
        if min_age_seconds is not None and (
            item.marker_age_seconds is None or item.marker_age_seconds < min_age_seconds
        ):
            kept_recent.append(item.path)
            continue
        if dry_run:
            removed.append(item.path)
            continue
        try:
            shutil.rmtree(item.path)
        except OSError as exc:
            errors.append(f"{item.path}: {exc}")
            continue
        if item.path.exists():
            errors.append(f"{item.path}: still exists after cleanup")
        else:
            removed.append(item.path)

    return CleanupReport(
        scanned=len(workspaces),
        removed=tuple(removed),
        kept_unknown=tuple(kept_unknown),
        kept_live_pid=tuple(kept_live),
        kept_recent=tuple(kept_recent),
        errors=tuple(errors),
        dry_run=dry_run,
    )


def recover_orphan_temp_workspaces(cache_dir: Path, *, dry_run: bool = False) -> CleanupReport:
    """启动恢复：安全处理上次崩溃遗留的已标记临时工作区（默认真实清理，跳过存活 PID）。"""
    return cleanup_orphan_temp_workspaces(cache_dir, dry_run=dry_run, skip_live_pid=True)
