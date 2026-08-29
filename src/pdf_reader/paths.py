"""统一路径策略：项目资源根与运行数据根。

设计目标（P2-07）：

- 所有资源/数据位置由这一个模块集中解析，业务模块不得再各自按 ``__file__``
  或当前工作目录（CWD）推导。
- ``PROJECT_ROOT``（项目资源根）＝仓库根。默认从本模块位置向上查找
  ``config.example.toml`` 标记；P2-01 把模块迁入 ``src/pdf_reader`` 后，
  标记查找仍能自动回到仓库根。也可用环境变量 ``PDF_READER_ROOT`` 显式覆盖。
- ``DATA_ROOT``（运行数据根）默认等于 ``PROJECT_ROOT``，保持现有本地运行语义
  （日志在仓库 ``logs/``、相对缓存相对仓库根）；环境变量
  ``PDF_READER_DATA_ROOT`` 可覆盖（测试隔离等场景）。
- ``PDF_READER_ROOT`` / ``PDF_READER_DATA_ROOT`` 覆盖值必须是绝对路径；
  相对值抛 ``PathStrategyError``，绝不按当前工作目录（CWD）静默解析。
- 相对 ``cache_dir`` 相对 ``DATA_ROOT`` 解析；绝对 ``cache_dir`` 保持绝对。
"""

import os
from pathlib import Path

PROJECT_ROOT_ENV = "PDF_READER_ROOT"
DATA_ROOT_ENV = "PDF_READER_DATA_ROOT"
_PROJECT_MARKER = "config.example.toml"


class PathStrategyError(RuntimeError):
    """路径策略配置错误：显式、可测试的失败。"""


def _env_path(name: str) -> Path | None:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return None
    candidate = Path(raw.strip()).expanduser()
    if not candidate.is_absolute():
        raise PathStrategyError(f"环境变量 {name} 必须是绝对路径（absolute path），拒绝相对值：{raw.strip()!r}")
    return candidate.resolve()


def _find_project_root(start: Path | None = None) -> Path:
    env_root = _env_path(PROJECT_ROOT_ENV)
    if env_root is not None:
        return env_root
    current = start or Path(__file__).resolve().parent
    for candidate in (current, *current.parents):
        if (candidate / _PROJECT_MARKER).is_file():
            return candidate
    raise PathStrategyError(
        f"未找到项目根标记 {_PROJECT_MARKER}（从 {current} 向上查找）；请通过环境变量 PDF_READER_ROOT 显式提供绝对路径"
    )


def get_project_root() -> Path:
    """项目资源根：仓库根目录。"""
    return _find_project_root()


def get_resource_root() -> Path:
    """项目资源根别名：config/glossary/templates/static 所在目录。"""
    return get_project_root()


def get_data_root() -> Path:
    """运行数据根：logs 与相对缓存目录的基准，默认等于项目资源根。"""
    return _env_path(DATA_ROOT_ENV) or get_project_root()


def get_config_path() -> Path:
    return get_resource_root() / "config.toml"


def get_glossary_path() -> Path:
    return get_resource_root() / "docs" / "glossary.csv"


def get_log_dir() -> Path:
    return get_data_root() / "logs"


def resolve_cache_dir(value: str) -> Path:
    """解析 cache_dir：相对路径以 DATA_ROOT 为基准，绝对路径保持绝对。"""
    path = Path(value).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (get_data_root() / path).resolve()
