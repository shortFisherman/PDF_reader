"""P1-03 便携数据治理：版本检测、备份式原子迁移、受控导入与分类清理。

本模块只依赖标准库、``paths`` 与 ``portable_runtime``，因此顶层启动器可以在导入任何
应用/上游代码之前调用它。调用位置由 P1-03 边界固定：``portable_launcher`` 取得内核
单实例锁之后、启动 ``app/PDF Reader Service.exe`` 之前完成 ``prepare_portable_data()``，
于是第二次启动只会走激活路径，不会重复迁移，也不会并发改写同一个数据根。

四条不变量：

* 数据格式版本只由 ``DATA_ROOT/portable-data.json`` 决定；缺字段、未知字段、类型错误
  一律 fail closed，绝不按猜测继续。
* 迁移先备份旧字节、再写同目录临时文件、最后 ``os.replace`` 原子提交；失败保留旧字节，
  回滚是显式命令而不是隐式副作用。
* 清理只作用于规范化 data root 的直接子项；分类根是 link/junction 时拒绝执行，子项是
  链接时只删除链接本身，绝不跟随链接递归删除用户 data 之外的 PDF。
* 受控导入只从用户显式给出的外部 data 根复制，源必须在目标数据根之外且非链接；
  ``config/`` 永不导入（保留目标自己的配置）。
"""

from __future__ import annotations

import json
import os
import secrets
import stat
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pdf_reader import paths
from pdf_reader.portable_runtime import INSTANCE_RECORD_NAME

PRODUCT = "pdf-reader-portable"
SCHEMA_VERSION = 1
LEDGER_ADOPT = "adopt-pre-versioned-data"
MANIFEST_NAME = "portable-data.json"
BACKUP_DIR_NAME = "backups"
BACKUP_STATE_NAME = "state.json"
BACKUP_FILES_NAME = "files"
MIGRATION_LOG_NAME = "migrations.log"
TEMP_SUFFIX = ".tmp"

CODE_SCHEMA_NEWER = "portable_data_schema_newer"
CODE_MANIFEST_INVALID = "portable_data_manifest_invalid"
CODE_BACKUP_MISSING = "portable_data_backup_missing"
CODE_BACKUP_INCOMPLETE = "portable_data_backup_incomplete"
CODE_WRITE_FAILED = "portable_data_write_failed"
CODE_TARGET_IS_LINK = "portable_data_target_is_link"
CODE_CLEANUP_CATEGORY_REQUIRED = "portable_data_cleanup_category_required"
CODE_CLEANUP_CATEGORY_UNKNOWN = "portable_data_cleanup_category_unknown"
CODE_CLEANUP_ROOT_IS_LINK = "portable_data_cleanup_root_is_link"
CODE_INSTANCE_RUNNING = "portable_instance_running"
CODE_IMPORT_SOURCE_MISSING = "portable_data_import_source_missing"
CODE_IMPORT_SOURCE_UNSAFE = "portable_data_import_source_unsafe"
CODE_IMPORT_TARGET_UNSAFE = "portable_data_import_target_unsafe"
CODE_IMPORT_SOURCE_UNREADABLE = "portable_data_import_source_unreadable"

_MANIFEST_FIELDS = frozenset(
    {"schema_version", "product", "app_version", "created_at", "updated_at", "applied_migrations"}
)
_CHUNK_SIZE = 1024 * 1024


class PortableDataError(RuntimeError):
    """带稳定错误码的便携数据治理错误。"""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _timestamp(clock: Callable[[], datetime]) -> str:
    return clock().astimezone(UTC).isoformat()


def _stamp(clock: Callable[[], datetime]) -> str:
    return clock().astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _is_link(path: Path) -> bool:
    """symlink 与 Windows junction 都算链接；junction 不是 symlink。"""

    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction()) if callable(is_junction) else False


def _guard_in_data_root(layout: paths.RuntimeLayout, value: str | Path, *, label: str) -> Path:
    """把候选路径规范化到 data root 内；开发布局同样强制边界，避免清理逃逸。"""

    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = layout.data_root / candidate
    resolved = candidate.resolve(strict=False)
    if not paths._is_within(resolved, layout.data_root):  # noqa: SLF001 - 复用唯一一份物理边界判定
        raise paths.PathStrategyError(
            f"{label} 必须位于便携数据根内，拒绝路径：{value!s}",
            code="path_outside_data_root",
        )
    return resolved


def _write_atomic(target: Path, payload: bytes) -> None:
    """同目录临时文件 + fsync + ``os.replace`` 原子替换；失败清理临时文件。"""

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.{secrets.token_hex(4)}{TEMP_SUFFIX}")
    try:
        with temporary.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except OSError as exc:
        _discard(temporary)
        raise PortableDataError(f"写入失败，已保留原有字节：{target}：{exc}", code=CODE_WRITE_FAILED) from exc


def _copy_atomic(source: Path, target: Path) -> int:
    """流式复制到同目录临时文件后原子替换，返回复制字节数。"""

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.{secrets.token_hex(4)}{TEMP_SUFFIX}")
    copied = 0
    try:
        with source.open("rb") as reader, temporary.open("wb") as writer:
            while True:
                chunk = reader.read(_CHUNK_SIZE)
                if not chunk:
                    break
                writer.write(chunk)
                copied += len(chunk)
            writer.flush()
            os.fsync(writer.fileno())
        os.replace(temporary, target)
    except OSError as exc:
        _discard(temporary)
        raise PortableDataError(f"复制失败，已保留目标原状：{target}：{exc}", code=CODE_WRITE_FAILED) from exc
    return copied


def _discard(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _measure(path: Path) -> tuple[int, int]:
    """返回 (字节数, 文件数)；不跟随链接，目录本身不计大小。"""

    try:
        info = path.lstat()
    except OSError:
        return (0, 0)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        return (info.st_size, 1)
    total = 0
    count = 0
    for child in _children(path):
        child_bytes, child_count = _measure(child)
        total += child_bytes
        count += child_count
    return (total, count)


def _children(directory: Path) -> list[Path]:
    """按名称排序返回直接子项；不可读目录返回空列表。"""

    try:
        with os.scandir(directory) as entries:
            names = sorted(entry.name for entry in entries)
    except OSError:
        return []
    return [directory / name for name in names]


def _remove_entry(path: Path) -> None:
    """安全删除：链接只删除链接本身，目录递归删除但不跟随链接。"""

    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if _is_link(path):
        if stat.S_ISDIR(info.st_mode):
            path.rmdir()  # junction：只移除链接本身
        else:
            path.unlink()
        return
    if not stat.S_ISDIR(info.st_mode):
        path.unlink()
        return
    for child in _children(path):
        _remove_entry(child)
    path.rmdir()


def _walk_source(root: Path) -> Iterator[tuple[str, Path, bool, bool]]:
    """按字典序产出 (相对 posix 路径, 路径, 是否链接, 是否目录)，不跟随链接。"""

    def _walk(directory: Path, prefix: str) -> Iterator[tuple[str, Path, bool, bool]]:
        for child in _children(directory):
            relative = f"{prefix}/{child.name}" if prefix else child.name
            link = _is_link(child)
            is_directory = not link and child.is_dir()
            yield (relative, child, link, is_directory)
            if is_directory:
                yield from _walk(child, relative)

    return _walk(root, "")


# -- manifest 与版本检测 ---------------------------------------------------


@dataclass(frozen=True, slots=True)
class DataManifest:
    """``DATA_ROOT/portable-data.json`` 的严格解析结果。"""

    schema_version: int
    product: str
    app_version: str
    created_at: str
    updated_at: str
    applied_migrations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DataSchemaStatus:
    """数据格式版本状态：absent / current / outdated / newer / invalid。"""

    state: str
    version: int | None
    manifest: DataManifest | None
    detail: str = ""


def manifest_path(layout: paths.RuntimeLayout) -> Path:
    return layout.data_root / MANIFEST_NAME


def backup_root(layout: paths.RuntimeLayout) -> Path:
    return layout.data_root / BACKUP_DIR_NAME


def migration_log_path(layout: paths.RuntimeLayout) -> Path:
    return backup_root(layout) / MIGRATION_LOG_NAME


def _parse_manifest(path: Path) -> DataManifest | None:
    """返回 None 表示没有清单；任何不可信内容都抛 ``portable_data_manifest_invalid``。"""

    if _is_link(path):
        raise PortableDataError(f"数据格式清单是链接，拒绝信任：{path}", code=CODE_MANIFEST_INVALID)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise PortableDataError(f"无法读取数据格式清单：{exc}", code=CODE_MANIFEST_INVALID) from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PortableDataError(f"数据格式清单不是合法 JSON：{exc}", code=CODE_MANIFEST_INVALID) from exc
    if not isinstance(payload, dict) or set(payload) != set(_MANIFEST_FIELDS):
        raise PortableDataError(
            "数据格式清单字段不符合契约（缺失或未知字段一律拒绝）",
            code=CODE_MANIFEST_INVALID,
        )
    version = payload["schema_version"]
    if isinstance(version, bool) or not isinstance(version, int) or version < 0:
        raise PortableDataError("数据格式清单的 schema_version 不是非负整数", code=CODE_MANIFEST_INVALID)
    product = payload["product"]
    if not isinstance(product, str) or product != PRODUCT:
        raise PortableDataError(f"数据格式清单 product 不匹配：{product!r}", code=CODE_MANIFEST_INVALID)
    app_version = payload["app_version"]
    created_at = payload["created_at"]
    updated_at = payload["updated_at"]
    if not all(isinstance(item, str) for item in (app_version, created_at, updated_at)):
        raise PortableDataError("数据格式清单的版本/时间字段必须是字符串", code=CODE_MANIFEST_INVALID)
    migrations = payload["applied_migrations"]
    if not isinstance(migrations, list) or not all(isinstance(item, str) for item in migrations):
        raise PortableDataError("数据格式清单的 applied_migrations 必须是字符串列表", code=CODE_MANIFEST_INVALID)
    return DataManifest(
        schema_version=version,
        product=product,
        app_version=app_version,
        created_at=created_at,
        updated_at=updated_at,
        applied_migrations=tuple(migrations),
    )


def detect_schema(layout: paths.RuntimeLayout) -> DataSchemaStatus:
    """只读检测数据格式版本；绝不改写任何字节。"""

    try:
        manifest = _parse_manifest(manifest_path(layout))
    except PortableDataError as exc:
        return DataSchemaStatus(state="invalid", version=None, manifest=None, detail=str(exc))
    if manifest is None:
        return DataSchemaStatus(state="absent", version=None, manifest=None, detail="没有数据格式清单")
    if manifest.schema_version > SCHEMA_VERSION:
        return DataSchemaStatus(
            state="newer",
            version=manifest.schema_version,
            manifest=manifest,
            detail=f"数据格式版本 {manifest.schema_version} 高于本程序支持的 {SCHEMA_VERSION}",
        )
    if manifest.schema_version < SCHEMA_VERSION:
        return DataSchemaStatus(
            state="outdated",
            version=manifest.schema_version,
            manifest=manifest,
            detail=f"数据格式版本 {manifest.schema_version} 需要升级到 {SCHEMA_VERSION}",
        )
    return DataSchemaStatus(state="current", version=manifest.schema_version, manifest=manifest)


# -- 备份事务 -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _BackupEntry:
    relative: str
    label: str
    existed_before: bool


@dataclass(frozen=True, slots=True)
class _BackupState:
    schema_version_from: int
    schema_version_to: int
    app_version: str
    created_at: str
    committed_at: str
    entries: tuple[_BackupEntry, ...]


class DataMigrationTxn:
    """一次数据迁移的“备份 + 临时文件 + 原子提交”事务。

    备份目录在构造时创建且名字唯一（时间戳 + 随机后缀），绝不覆盖既有备份；
    ``replace_file()`` 先保存旧字节，再原子替换；``commit()`` 写出 ``state.json``，
    只有带 ``state.json`` 的备份目录才会被回滚采用。
    """

    def __init__(
        self,
        layout: paths.RuntimeLayout,
        *,
        from_version: int,
        to_version: int,
        app_version: str,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._layout = layout
        self._from_version = from_version
        self._to_version = to_version
        self._app_version = app_version
        self._clock = clock
        self._entries: dict[str, _BackupEntry] = {}
        self._committed = False
        self.backup_dir = self._create_backup_directory()

    @property
    def committed(self) -> bool:
        return self._committed

    def _create_backup_directory(self) -> Path:
        root = backup_root(self._layout)
        name = f"{_stamp(self._clock)}-v{self._from_version}-to-v{self._to_version}-{secrets.token_hex(3)}"
        directory = root / name
        directory.mkdir(parents=True, exist_ok=False)
        return directory

    def replace_file(self, target: str | Path, new_bytes: bytes, *, label: str = "数据文件") -> Path:
        """备份旧字节后原子替换目标文件；目标必须在 data root 内且不是链接。"""

        resolved = _guard_in_data_root(self._layout, target, label=label)
        if resolved == self._layout.data_root:
            raise PortableDataError(f"拒绝把数据根目录当作文件写入：{resolved}", code=CODE_WRITE_FAILED)
        if _is_link(resolved):
            raise PortableDataError(f"拒绝通过链接写入数据文件：{resolved}", code=CODE_TARGET_IS_LINK)
        relative = resolved.relative_to(self._layout.data_root).as_posix()
        if relative not in self._entries:
            existed_before = resolved.is_file()
            if existed_before:
                backup_file = self.backup_dir / BACKUP_FILES_NAME / relative
                backup_file.parent.mkdir(parents=True, exist_ok=True)
                try:
                    with resolved.open("rb") as reader, backup_file.open("wb") as writer:
                        writer.write(reader.read())
                except OSError as exc:
                    raise PortableDataError(
                        f"无法备份 {relative}，迁移中止：{exc}",
                        code=CODE_WRITE_FAILED,
                    ) from exc
            self._entries[relative] = _BackupEntry(
                relative=relative,
                label=label,
                existed_before=existed_before,
            )
        _write_atomic(resolved, new_bytes)
        return resolved

    def commit(self) -> None:
        """写出备份状态；没有状态文件的备份目录不会被回滚采用。"""

        now = _timestamp(self._clock)
        payload = {
            "schema_version_from": self._from_version,
            "schema_version_to": self._to_version,
            "app_version": self._app_version,
            "product": PRODUCT,
            "created_at": now,
            "committed_at": now,
            "entries": [
                {
                    "path": entry.relative,
                    "label": entry.label,
                    "existed_before": entry.existed_before,
                }
                for entry in self._entries.values()
            ],
        }
        _write_atomic(
            self.backup_dir / BACKUP_STATE_NAME,
            json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8") + b"\n",
        )
        self._committed = True


def _read_backup_state(directory: Path) -> _BackupState:
    state_path = directory / BACKUP_STATE_NAME
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PortableDataError(f"迁移备份状态不可用：{state_path}：{exc}", code=CODE_BACKUP_INCOMPLETE) from exc
    if not isinstance(payload, dict):
        raise PortableDataError(f"迁移备份状态格式错误：{state_path}", code=CODE_BACKUP_INCOMPLETE)
    entries: list[_BackupEntry] = []
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list):
        raise PortableDataError(f"迁移备份状态缺少 entries：{state_path}", code=CODE_BACKUP_INCOMPLETE)
    for raw in raw_entries:
        if not isinstance(raw, dict):
            raise PortableDataError(f"迁移备份条目格式错误：{state_path}", code=CODE_BACKUP_INCOMPLETE)
        relative = raw.get("path")
        existed_before = raw.get("existed_before")
        label = raw.get("label")
        if not isinstance(relative, str) or not _is_safe_relative(relative) or not isinstance(existed_before, bool):
            raise PortableDataError(f"迁移备份条目字段错误：{state_path}", code=CODE_BACKUP_INCOMPLETE)
        entries.append(
            _BackupEntry(
                relative=relative,
                label=label if isinstance(label, str) else relative,
                existed_before=existed_before,
            )
        )
    return _BackupState(
        schema_version_from=_as_int(payload.get("schema_version_from")),
        schema_version_to=_as_int(payload.get("schema_version_to")),
        app_version=str(payload.get("app_version", "")),
        created_at=str(payload.get("created_at", "")),
        committed_at=str(payload.get("committed_at", "")),
        entries=tuple(entries),
    )


def _as_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PortableDataError("迁移备份状态的版本字段不是整数", code=CODE_BACKUP_INCOMPLETE)
    return value


def _is_safe_relative(value: str) -> bool:
    if not value or value.startswith(("/", "\\")):
        return False
    parts = value.replace("\\", "/").split("/")
    return all(part not in ("", ".", "..") for part in parts)


def _backup_directories(layout: paths.RuntimeLayout) -> list[Path]:
    root = backup_root(layout)
    if not root.is_dir() or _is_link(root):
        return []
    return sorted((entry for entry in _children(root) if entry.is_dir() and not _is_link(entry)), key=str)


def restore_backup_directory(layout: paths.RuntimeLayout, backup_dir: str | Path) -> bool:
    """按备份状态恢复；返回是否删除了迁移新建的清单文件。"""

    directory = _guard_in_data_root(layout, backup_dir, label="迁移备份目录")
    if _is_link(directory) or not directory.is_dir():
        raise PortableDataError(f"迁移备份目录不可用：{directory}", code=CODE_BACKUP_MISSING)
    state = _read_backup_state(directory)
    removed_manifest = False
    for entry in state.entries:
        target = _guard_in_data_root(layout, layout.data_root / entry.relative, label="回滚目标")
        if entry.existed_before:
            source = directory / BACKUP_FILES_NAME / entry.relative
            if not source.is_file():
                raise PortableDataError(
                    f"备份缺少 {entry.relative} 的旧字节，拒绝部分回滚",
                    code=CODE_BACKUP_INCOMPLETE,
                )
            try:
                payload = source.read_bytes()
            except OSError as exc:
                raise PortableDataError(f"读取备份失败：{source}：{exc}", code=CODE_BACKUP_INCOMPLETE) from exc
            _write_atomic(target, payload)
            continue
        if _is_link(target):
            raise PortableDataError(f"拒绝删除链接目标：{target}", code=CODE_TARGET_IS_LINK)
        if target.exists():
            _remove_entry(target)
            removed_manifest = removed_manifest or entry.relative == MANIFEST_NAME
    return removed_manifest


# -- 迁移与回滚入口 -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MigrationReport:
    performed: bool
    from_version: int
    to_version: int
    backup_dir: Path | None


@dataclass(frozen=True, slots=True)
class RollbackReport:
    performed: bool
    backup_dir: Path | None
    removed_manifest: bool


def _append_migration_log(layout: paths.RuntimeLayout, message: str) -> None:
    """追加一行迁移账本；日志在 backups/ 内，不参与分类清理。"""

    path = migration_log_path(layout)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(message + "\n")
    except OSError:
        # 账本写失败不能掩盖已经原子提交的迁移结果。
        return


def _manifest_payload(
    *,
    schema_version: int,
    app_version: str,
    created_at: str,
    updated_at: str,
    applied: Iterable[str],
) -> bytes:
    payload = {
        "schema_version": schema_version,
        "product": PRODUCT,
        "app_version": app_version,
        "created_at": created_at,
        "updated_at": updated_at,
        "applied_migrations": list(applied),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"


def prepare_portable_data(
    layout: paths.RuntimeLayout,
    *,
    app_version: str,
    clock: Callable[[], datetime] = _utc_now,
) -> MigrationReport:
    """在启动服务之前完成数据格式检测与迁移；已是最新则完全不动字节。

    * 无清单的既有/全新 data root 记为 ``absent``，执行一次采纳迁移并写入 v1 清单。
    * 旧清单执行升级迁移，旧清单原字节进备份目录，可 ``rollback_last_migration()``。
    * 清单损坏或版本高于本程序时抛稳定错误码，绝不猜测、绝不改写。
    """

    layout.data_root.mkdir(parents=True, exist_ok=True)
    status = detect_schema(layout)
    if status.state == "invalid":
        raise PortableDataError(
            f"数据格式清单不可信，拒绝启动：{status.detail}",
            code=CODE_MANIFEST_INVALID,
        )
    if status.state == "newer":
        raise PortableDataError(
            f"{status.detail}；请使用更新的 PDF Reader，或先备份 data 目录后自行处理",
            code=CODE_SCHEMA_NEWER,
        )
    if status.state == "current":
        assert status.version is not None
        return MigrationReport(
            performed=False,
            from_version=status.version,
            to_version=status.version,
            backup_dir=None,
        )

    previous = status.manifest
    from_version = 0 if previous is None else previous.schema_version
    now = _timestamp(clock)
    adopted = previous is None
    applied: tuple[str, ...]
    if previous is None:
        applied = (LEDGER_ADOPT,)
    else:
        applied = (*previous.applied_migrations, f"schema-v{from_version}-to-v{SCHEMA_VERSION}")
    txn = DataMigrationTxn(
        layout,
        from_version=from_version,
        to_version=SCHEMA_VERSION,
        app_version=app_version,
        clock=clock,
    )
    txn.replace_file(
        manifest_path(layout),
        _manifest_payload(
            schema_version=SCHEMA_VERSION,
            app_version=app_version,
            created_at=now if previous is None else previous.created_at,
            updated_at=now,
            applied=applied,
        ),
        label="数据格式清单",
    )
    txn.commit()
    event = "portable-data-adopted" if adopted else "portable-data-migrated"
    _append_migration_log(
        layout,
        f"{now} {event} product={PRODUCT} from=v{from_version} to=v{SCHEMA_VERSION} "
        f"app={app_version} backup={txn.backup_dir.name}",
    )
    return MigrationReport(
        performed=True,
        from_version=from_version,
        to_version=SCHEMA_VERSION,
        backup_dir=txn.backup_dir,
    )


def rollback_last_migration(layout: paths.RuntimeLayout) -> RollbackReport:
    """恢复最近一次已提交迁移；没有备份时给出稳定错误码而不是静默成功。"""

    candidates = [directory for directory in _backup_directories(layout) if (directory / BACKUP_STATE_NAME).is_file()]
    if not candidates:
        raise PortableDataError(
            f"没有可回滚的迁移备份：{backup_root(layout)}",
            code=CODE_BACKUP_MISSING,
        )
    backup_dir = candidates[-1]
    removed_manifest = restore_backup_directory(layout, backup_dir)
    _append_migration_log(
        layout,
        f"{_utc_now().isoformat()} portable-data-rolled-back backup={backup_dir.name} "
        f"removed_manifest={removed_manifest}",
    )
    return RollbackReport(performed=True, backup_dir=backup_dir, removed_manifest=removed_manifest)


# -- 分类统计与安全清理 ---------------------------------------------------


@dataclass(frozen=True, slots=True)
class CategorySpec:
    key: str
    label: str
    roots: tuple[str, ...]
    consequence: str
    regenerable: bool


CATEGORY_SPECS: tuple[CategorySpec, ...] = (
    CategorySpec(
        key="documents",
        label="文档缓存",
        roots=("documents",),
        consequence="删除后已翻译页面与阅读进度一并丢失，需要重新上传原文并重新翻译，程序无法自行重建。",
        regenerable=False,
    ),
    CategorySpec(
        key="models",
        label="模型与上游缓存",
        roots=("models", "upstream-cache"),
        consequence="删除后模型与上游缓存需要重新下载（需联网，耗时且占用带宽），不会自动保留离线可用性。",
        regenerable=True,
    ),
    CategorySpec(
        key="fonts",
        label="字体",
        roots=("fonts",),
        consequence="删除后自有字体会在下次翻译时重新获取，期间个别排版可能回退到替代字体。",
        regenerable=True,
    ),
    CategorySpec(
        key="logs",
        label="日志",
        roots=("logs",),
        consequence="删除后历史日志无法恢复，故障排查只能依赖之后的运行记录。",
        regenerable=False,
    ),
    CategorySpec(
        key="temp",
        label="临时文件",
        roots=("temp",),
        consequence="临时工作文件可安全删除，程序会在需要时重建。",
        regenerable=True,
    ),
)
_CATEGORY_INDEX = {spec.key: spec for spec in CATEGORY_SPECS}


@dataclass(frozen=True, slots=True)
class CategoryStat:
    key: str
    label: str
    roots: tuple[Path, ...]
    bytes: int
    file_count: int
    consequence: str
    regenerable: bool


@dataclass(frozen=True, slots=True)
class CleanupCategoryReport:
    key: str
    dry_run: bool
    removed: tuple[Path, ...]
    bytes_reclaimed: int
    consequence: str = ""


def category_stats(layout: paths.RuntimeLayout) -> tuple[CategoryStat, ...]:
    """按固定顺序返回分类统计；只读，不创建或删除任何路径。"""

    stats: list[CategoryStat] = []
    for spec in CATEGORY_SPECS:
        roots = tuple(layout.data_root / name for name in spec.roots)
        total = 0
        count = 0
        for root in roots:
            root_bytes, root_count = _measure(root)
            total += root_bytes
            count += root_count
        stats.append(
            CategoryStat(
                key=spec.key,
                label=spec.label,
                roots=roots,
                bytes=total,
                file_count=count,
                consequence=spec.consequence,
                regenerable=spec.regenerable,
            )
        )
    return tuple(stats)


def _ensure_no_running_instance(layout: paths.RuntimeLayout) -> None:
    record = layout.runtime_dir / INSTANCE_RECORD_NAME
    if record.is_symlink() or record.exists():
        raise PortableDataError(
            f"检测到正在运行的便携实例记录（{record}），拒绝清理数据",
            code=CODE_INSTANCE_RUNNING,
        )


def run_cleanup(
    layout: paths.RuntimeLayout,
    categories: Sequence[str],
    *,
    dry_run: bool,
) -> tuple[CleanupCategoryReport, ...]:
    """按分类清理 data root 内的直接子项；dry-run 只报告不删除。

    删除目标只能是普通 data 子项：分类根本身是链接时整体拒绝，子项是链接时只删除
    链接本身（绝不跟随），因此用户放在 data 之外的原 PDF 永远不会被递归删除。
    """

    requested = [str(item) for item in categories]
    if not requested:
        raise PortableDataError(
            f"清理必须显式指定分类：{', '.join(_CATEGORY_INDEX)}",
            code=CODE_CLEANUP_CATEGORY_REQUIRED,
        )
    unknown = sorted({key for key in requested if key not in _CATEGORY_INDEX})
    if unknown:
        raise PortableDataError(
            f"未知清理分类：{', '.join(unknown)}；可用分类：{', '.join(_CATEGORY_INDEX)}",
            code=CODE_CLEANUP_CATEGORY_UNKNOWN,
        )
    _ensure_no_running_instance(layout)

    roots: dict[str, tuple[Path, ...]] = {}
    for spec in CATEGORY_SPECS:
        if spec.key not in requested:
            continue
        guarded: list[Path] = []
        for name in spec.roots:
            root = layout.data_root / name
            if _is_link(root):
                raise PortableDataError(
                    f"清理分类根目录是链接，拒绝执行：{root}",
                    code=CODE_CLEANUP_ROOT_IS_LINK,
                )
            guarded.append(_guard_in_data_root(layout, root, label="清理根目录"))
        roots[spec.key] = tuple(guarded)

    reports: list[CleanupCategoryReport] = []
    for spec in CATEGORY_SPECS:
        if spec.key not in requested:
            continue
        removed: list[Path] = []
        reclaimed = 0
        for root in roots[spec.key]:
            children = _children(root) if root.is_dir() else []
            for child in children:
                child_bytes, _child_count = _measure(child)
                removed.append(child)
                reclaimed += child_bytes
                if not dry_run:
                    _remove_entry(child)
        reports.append(
            CleanupCategoryReport(
                key=spec.key,
                dry_run=dry_run,
                removed=tuple(removed),
                bytes_reclaimed=reclaimed,
                consequence=spec.consequence,
            )
        )
    return tuple(reports)


# -- 受控导入 -------------------------------------------------------------


IMPORT_EXCLUSIONS: dict[str, str] = {
    "config": "existing-config-preserved",
    "runtime": "volatile-state-not-imported",
    "logs": "volatile-state-not-imported",
    "temp": "volatile-state-not-imported",
    "pycache": "volatile-state-not-imported",
    "home": "volatile-state-not-imported",
    BACKUP_DIR_NAME: "migration-backups-not-imported",
}
REASON_CONFIG_PRESERVED = "existing-config-preserved"
REASON_ALREADY_EXISTS = "already-exists"
REASON_SOURCE_LINK = "source-entry-is-link"
REASON_MANIFEST = "target-manifest-preserved"


@dataclass(frozen=True, slots=True)
class ImportReport:
    dry_run: bool
    source: Path
    copied: tuple[str, ...]
    skipped: tuple[tuple[str, str], ...]
    bytes_copied: int


def import_portable_data(
    layout: paths.RuntimeLayout,
    source_data_root: str | Path,
    *,
    dry_run: bool,
    overwrite: bool = False,
) -> ImportReport:
    """把旧安装的 data 内容受控导入新安装；``config/`` 与易变状态永不导入。

    导入只读取用户显式给出的外部目录，且该目录必须与目标数据根互不包含、本身不是
    链接；单个源条目是链接时只记录跳过，绝不把链接或其目标复制进新安装。
    """

    source = Path(source_data_root).expanduser()
    if not source.exists():
        raise PortableDataError(f"导入源不存在：{source}", code=CODE_IMPORT_SOURCE_MISSING)
    if _is_link(source) or not source.is_dir():
        raise PortableDataError(f"导入源必须是真实目录且不是链接：{source}", code=CODE_IMPORT_SOURCE_UNSAFE)
    resolved_source = source.resolve(strict=False)
    target_root = layout.data_root.resolve(strict=False)
    if paths._is_within(resolved_source, target_root) or paths._is_within(target_root, resolved_source):  # noqa: SLF001
        raise PortableDataError(
            f"导入源不能位于目标数据根内，也不能包含目标数据根：{resolved_source}",
            code=CODE_IMPORT_SOURCE_UNSAFE,
        )
    if not dry_run:
        layout.data_root.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []
    skipped: list[tuple[str, str]] = []
    total = 0
    for relative, path, link, is_directory in _walk_source(resolved_source):
        if is_directory:
            continue
        exclusion = IMPORT_EXCLUSIONS.get(relative.split("/", 1)[0])
        if exclusion is not None:
            skipped.append((relative, exclusion))
            continue
        if relative == MANIFEST_NAME:
            skipped.append((relative, REASON_MANIFEST))
            continue
        if link:
            skipped.append((relative, REASON_SOURCE_LINK))
            continue
        target_path = _guard_in_data_root(layout, target_root / relative, label="导入目标")
        if _is_link(target_path):
            raise PortableDataError(
                f"导入目标已存在链接，拒绝写入：{target_path}",
                code=CODE_IMPORT_TARGET_UNSAFE,
            )
        if target_path.exists() and not overwrite:
            skipped.append((relative, REASON_ALREADY_EXISTS))
            continue
        if dry_run:
            total += _measure(path)[0]
            copied.append(relative)
            continue
        total += _copy_atomic(path, target_path)
        copied.append(relative)
    return ImportReport(
        dry_run=dry_run,
        source=resolved_source,
        copied=tuple(copied),
        skipped=tuple(skipped),
        bytes_copied=total,
    )


# -- 面向用户/命令行的纯文本渲染 -----------------------------------------


def format_bytes(size: int) -> str:
    """人类可读大小；用 1024 进制，保留一位小数。"""

    if size < 1024:
        return f"{size} B"
    value = float(size)
    for unit in ("KiB", "MiB", "GiB", "TiB"):
        value /= 1024.0
        if value < 1024.0:
            return f"{value:.1f} {unit}"
    return f"{value:.1f} PiB"


def describe_schema(status: DataSchemaStatus) -> str:
    if status.state == "absent":
        return f"未记录（首次启动会写入 v{SCHEMA_VERSION} 并建立备份）"
    if status.state == "current":
        return f"当前 v{status.version}（本程序支持 v{SCHEMA_VERSION}）"
    if status.state == "outdated":
        return f"旧版本 v{status.version}，启动时升级到 v{SCHEMA_VERSION} 并备份旧清单"
    if status.state == "newer":
        return f"v{status.version} 高于本程序支持的 v{SCHEMA_VERSION}，拒绝启动（请勿降级覆盖）"
    return f"清单损坏，拒绝启动：{status.detail}"


def render_data_report(layout: paths.RuntimeLayout) -> str:
    """状态 + 分类大小/后果报告；清理界面与命令共用同一份文本。"""

    status = detect_schema(layout)
    backups = _backup_directories(layout)
    lines = [
        f"便携数据根：{layout.data_root}",
        f"数据格式版本：{describe_schema(status)}",
    ]
    if status.manifest is not None:
        lines.append(f"清单最近更新：{status.manifest.updated_at}（app {status.manifest.app_version}）")
    lines.append(f"迁移备份：{len(backups)} 个（目录 {backup_root(layout)}）")
    lines.append("")
    lines.append(f"{'分类':<24}{'大小':>12}{'文件数':>8}  删除后果")
    for entry in category_stats(layout):
        column = f"{entry.key}（{entry.label}）"
        lines.append(f"{column:<24}{format_bytes(entry.bytes):>12}{entry.file_count:>8}  {entry.consequence}")
    lines.append("")
    lines.append("清理默认只预览；真正删除必须显式指定分类并加 --yes：--clean documents --yes")
    lines.append("清理只作用于 data 根内的分类目录，拒绝 link/junction，绝不递归删除 data 之外的用户 PDF。")
    return "\n".join(lines)


def render_cleanup_report(reports: Sequence[CleanupCategoryReport]) -> str:
    if not reports:
        return "没有需要清理的分类。"
    mode = "预览（未删除任何文件）" if reports[0].dry_run else "已删除"
    lines = [f"清理结果：{mode}"]
    for report in reports:
        lines.append(
            f"{report.key}：{len(report.removed)} 项，回收 {format_bytes(report.bytes_reclaimed)}；{report.consequence}"
        )
        for path in report.removed:
            lines.append(f"  - {path}")
    if reports[0].dry_run:
        lines.append("确认执行：在命令后加 --yes")
    return "\n".join(lines)


def render_import_report(report: ImportReport) -> str:
    mode = "预览（未写入任何文件）" if report.dry_run else "已复制"
    lines = [
        f"受控导入：{mode}",
        f"源目录：{report.source}",
        f"复制 {len(report.copied)} 项，{format_bytes(report.bytes_copied)}",
    ]
    for relative in report.copied:
        lines.append(f"  + {relative}")
    if report.skipped:
        lines.append(f"跳过 {len(report.skipped)} 项：")
        for relative, reason in report.skipped:
            lines.append(f"  - {relative}（{reason}）")
    lines.append("配置永不自动导入；需要沿用旧配置时请手动复制旧 data/config/config.toml。")
    if report.dry_run:
        lines.append("确认执行：在命令后加 --yes")
    return "\n".join(lines)
