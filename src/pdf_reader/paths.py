"""开发运行与 Windows 便携发行共享的统一路径策略。

默认不安装任何运行布局，所有 getter 都即时构造开发布局，因而保持现有
``python -m pdf_reader``、``PDF_READER_ROOT`` 与 ``PDF_READER_DATA_ROOT`` 语义。
便携入口必须在导入 ``config``、日志及翻译依赖之前，显式构造并安装
``RuntimeLayout.portable_from_executable(...)``；业务模块不自行判断
``sys.frozen``，也不根据当前工作目录推导路径。
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

PROJECT_ROOT_ENV = "PDF_READER_ROOT"
DATA_ROOT_ENV = "PDF_READER_DATA_ROOT"
_PROJECT_MARKER = "config.example.toml"


class RuntimeMode(StrEnum):
    DEVELOPMENT = "development"
    PORTABLE = "portable"


class PathStrategyError(RuntimeError):
    """带稳定错误码的路径策略错误。"""

    def __init__(self, message: str, *, code: str = "path_strategy_error") -> None:
        super().__init__(message)
        self.code = code


def _absolute_path(value: str | Path, *, label: str) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        raise PathStrategyError(
            f"{label} 必须是绝对路径（absolute path），拒绝相对值：{str(value)!r}",
            code="path_not_absolute",
        )
    return candidate.resolve(strict=False)


def _env_path(name: str) -> Path | None:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return None
    return _absolute_path(raw.strip(), label=f"环境变量 {name}")


def _find_project_root(start: Path | None = None) -> Path:
    env_root = _env_path(PROJECT_ROOT_ENV)
    if env_root is not None:
        return env_root
    current = start or Path(__file__).resolve().parent
    for candidate in (current, *current.parents):
        if (candidate / _PROJECT_MARKER).is_file():
            return candidate.resolve(strict=False)
    raise PathStrategyError(
        f"未找到项目根标记 {_PROJECT_MARKER}（从 {current} 向上查找）；请通过环境变量 PDF_READER_ROOT 显式提供绝对路径",
        code="project_root_not_found",
    )


def _is_within(candidate: Path, root: Path, *, allow_root: bool = True) -> bool:
    """比较解析后的物理路径；Windows 上同时按大小写不敏感规则比较。"""

    resolved_candidate = candidate.resolve(strict=False)
    resolved_root = root.resolve(strict=False)
    candidate_text = os.path.normcase(os.path.abspath(resolved_candidate))
    root_text = os.path.normcase(os.path.abspath(resolved_root))
    try:
        common = os.path.commonpath((candidate_text, root_text))
    except ValueError:
        return False
    if common != root_text:
        return False
    return allow_root or candidate_text != root_text


@dataclass(frozen=True, slots=True)
class RuntimeLayout:
    """一次进程生命周期内不可变的资源、便携根和数据根契约。"""

    mode: RuntimeMode
    resource_root: Path
    data_root: Path
    portable_root: Path | None = None

    def __post_init__(self) -> None:
        try:
            mode = RuntimeMode(self.mode)
        except ValueError as exc:
            raise PathStrategyError(
                f"未知运行模式：{self.mode!s}",
                code="runtime_mode_invalid",
            ) from exc
        resource_root = _absolute_path(self.resource_root, label="RESOURCE_ROOT")
        data_root = _absolute_path(self.data_root, label="DATA_ROOT")
        portable_root = (
            _absolute_path(self.portable_root, label="PORTABLE_ROOT") if self.portable_root is not None else None
        )
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "resource_root", resource_root)
        object.__setattr__(self, "data_root", data_root)
        object.__setattr__(self, "portable_root", portable_root)

        if mode is RuntimeMode.PORTABLE:
            if portable_root is None:
                raise PathStrategyError(
                    "便携运行模式缺少 PORTABLE_ROOT",
                    code="portable_root_missing",
                )
            if not _is_within(resource_root, portable_root, allow_root=False):
                raise PathStrategyError(
                    "便携 RESOURCE_ROOT 必须位于 PORTABLE_ROOT 内",
                    code="portable_resource_outside_root",
                )
            if not _is_within(data_root, portable_root, allow_root=False):
                raise PathStrategyError(
                    "便携 DATA_ROOT 必须是 PORTABLE_ROOT 内的真实目录；检测到目录链接、junction 或路径逃逸",
                    code="portable_data_outside_root",
                )
        elif portable_root is not None:
            raise PathStrategyError(
                "开发运行模式不得设置 PORTABLE_ROOT",
                code="development_portable_root_set",
            )

    @classmethod
    def development(
        cls,
        *,
        resource_root: str | Path | None = None,
        data_root: str | Path | None = None,
    ) -> RuntimeLayout:
        resources = (
            _absolute_path(resource_root, label="RESOURCE_ROOT") if resource_root is not None else _find_project_root()
        )
        data = (
            _absolute_path(data_root, label="DATA_ROOT")
            if data_root is not None
            else _env_path(DATA_ROOT_ENV) or resources
        )
        return cls(RuntimeMode.DEVELOPMENT, resources, data)

    @classmethod
    def portable_from_executable(
        cls,
        executable: str | Path,
        *,
        resource_dirname: str = "app",
    ) -> RuntimeLayout:
        """从面向用户的顶层 EXE 解析便携根，不读取 CWD 或开发环境覆盖。"""

        executable_path = _absolute_path(executable, label="便携入口 EXE")
        portable_root = executable_path.parent
        return cls(
            RuntimeMode.PORTABLE,
            portable_root / resource_dirname,
            portable_root / "data",
            portable_root,
        )

    @property
    def config_path(self) -> Path:
        if self.mode is RuntimeMode.PORTABLE:
            return self.data_root / "config" / "config.toml"
        return self.resource_root / "config.toml"

    @property
    def glossary_path(self) -> Path:
        if self.mode is RuntimeMode.PORTABLE:
            return self.data_root / "glossary" / "glossary.csv"
        return self.resource_root / "docs" / "glossary.csv"

    @property
    def log_dir(self) -> Path:
        return self.data_root / "logs"

    @property
    def temp_dir(self) -> Path:
        return self.data_root / "temp"

    @property
    def runtime_dir(self) -> Path:
        """单实例锁与实例记录的协调目录（便携态固定在 data/runtime）。"""

        return self.data_root / "runtime"

    @property
    def default_cache_dirname(self) -> str:
        return "documents" if self.mode is RuntimeMode.PORTABLE else "cache"

    @property
    def managed_directories(self) -> tuple[Path, ...]:
        """按父目录优先顺序返回首版便携数据目录契约。"""

        return (
            self.data_root,
            self.data_root / "config",
            self.data_root / "documents",
            self.data_root / "glossary",
            self.data_root / "models",
            self.data_root / "fonts",
            self.data_root / "upstream-cache",
            self.data_root / "temp",
            self.data_root / "pycache",
            self.data_root / "logs",
            self.data_root / "runtime",
            self.data_root / "home",
            self.data_root / "home" / ".cache",
        )

    def require_data_path(self, value: str | Path, *, label: str = "写入路径") -> Path:
        """解析并验证便携写入路径，阻止 ``..``、链接和 junction 逃逸。"""

        raw_path = Path(value).expanduser()
        if self.mode is RuntimeMode.DEVELOPMENT:
            # 写入守卫是便携态强制边界；开发态保留调用方传入相对 Path 的既有语义。
            return raw_path.resolve(strict=False) if raw_path.is_absolute() else raw_path
        candidate = raw_path if raw_path.is_absolute() else self.data_root / raw_path
        candidate = candidate.resolve(strict=False)
        if not _is_within(candidate, self.data_root):
            raise PathStrategyError(
                f"{label} 必须位于便携 DATA_ROOT 内，拒绝路径：{value!s}",
                code="path_outside_data_root",
            )
        return candidate

    def resolve_cache_dir(self, value: str) -> Path:
        path = Path(value).expanduser()
        if self.mode is RuntimeMode.DEVELOPMENT:
            if path.is_absolute():
                return path.resolve(strict=False)
            return (self.data_root / path).resolve(strict=False)
        return self.require_data_path(path, label="cache_dir")


_configured_layout: RuntimeLayout | None = None


def install_runtime_layout(layout: RuntimeLayout) -> None:
    """由进程入口在导入配置/日志/翻译模块前安装一次显式运行布局。"""

    global _configured_layout
    if _configured_layout is not None and _configured_layout != layout:
        raise PathStrategyError(
            "运行布局已经安装，拒绝在同一进程内切换路径边界",
            code="runtime_layout_already_installed",
        )
    _configured_layout = layout


def get_runtime_layout() -> RuntimeLayout:
    # 未显式安装时不缓存，以保留测试与既有开发环境变量的动态语义。
    return _configured_layout or RuntimeLayout.development()


def prepare_runtime_layout(layout: RuntimeLayout | None = None) -> RuntimeLayout:
    """创建便携数据目录并验证可写；失败时绝不回退到其他目录。"""

    selected = layout or get_runtime_layout()
    if selected.mode is RuntimeMode.DEVELOPMENT:
        return selected

    for directory in selected.managed_directories:
        safe_directory = selected.require_data_path(directory, label="便携数据目录")
        try:
            safe_directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise PathStrategyError(
                f"PDF Reader 便携数据目录不可创建：{safe_directory}",
                code="portable_data_directory_unavailable",
            ) from exc
        # mkdir 之后再次解析，捕获并拒绝已经存在的目录链接/junction。
        selected.require_data_path(safe_directory, label="便携数据目录")

    probe_path = selected.data_root / f".pdf-reader-write-test-{secrets.token_hex(8)}.tmp"
    fd: int | None = None
    try:
        selected.require_data_path(probe_path, label="便携写入探针")
        fd = os.open(probe_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.write(fd, b"portable-write-check")
    except OSError as exc:
        raise PathStrategyError(
            f"PDF Reader 便携目录不可写：{selected.portable_root}；请将程序解压到当前用户可写目录后重试",
            code="portable_data_not_writable",
        ) from exc
    finally:
        if fd is not None:
            os.close(fd)
        try:
            probe_path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise PathStrategyError(
                f"PDF Reader 无法清理便携目录写入探针：{probe_path}",
                code="portable_write_probe_cleanup_failed",
            ) from exc
    return selected


def get_project_root() -> Path:
    """兼容名称：开发态为仓库根，便携态为只读资源根。"""

    return get_runtime_layout().resource_root


def get_resource_root() -> Path:
    return get_runtime_layout().resource_root


def get_portable_root() -> Path | None:
    return get_runtime_layout().portable_root


def get_data_root() -> Path:
    return get_runtime_layout().data_root


def get_config_path() -> Path:
    return get_runtime_layout().config_path


def get_glossary_path() -> Path:
    return get_runtime_layout().glossary_path


def get_log_dir() -> Path:
    return get_runtime_layout().log_dir


def get_temp_dir() -> Path:
    return get_runtime_layout().temp_dir


def get_default_cache_dirname() -> str:
    return get_runtime_layout().default_cache_dirname


def require_data_path(value: str | Path, *, label: str = "写入路径") -> Path:
    return get_runtime_layout().require_data_path(value, label=label)


def resolve_cache_dir(value: str) -> Path:
    return get_runtime_layout().resolve_cache_dir(value)
