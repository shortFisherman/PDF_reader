"""Write the generated dependency/license inventory shipped inside ``app/licenses``.

The file is factual build output, not legal text: for every bundled distribution it
records the version, the license expression the installed metadata declares and the
SHA-256 of the wheel it came from, and it lists the deliberately excluded
distributions with their reasons.  P2-04 owns the fuller third-party notice work; this
inventory is what makes that review mechanical instead of manual archaeology.
"""

from __future__ import annotations

import importlib.metadata as importlib_metadata
from dataclasses import dataclass
from pathlib import Path

from .lock import WheelRecord, normalize_distribution

DEPENDENCIES_NAME = "DEPENDENCIES.txt"
UNKNOWN_LICENSE = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class DependencyRow:
    name: str
    version: str
    license_expression: str
    wheel_sha256: str


def _license_expression(dist: importlib_metadata.Distribution) -> str:
    """Read the declared license from PEP 639 metadata with classic fallbacks."""

    metadata = dist.metadata
    expression = metadata.get("License-Expression")
    if expression:
        return str(expression).strip()
    classifiers = metadata.get_all("Classifier") or []
    for classifier in classifiers:
        text = str(classifier)
        if text.startswith("License ::"):
            return text.split("::")[-1].strip()
    raw = metadata.get("License")
    if raw:
        collapsed = " ".join(str(raw).split())
        if collapsed:
            return collapsed[:120]
    return UNKNOWN_LICENSE


def collect_dependency_rows(wheels: dict[str, WheelRecord]) -> tuple[list[DependencyRow], list[str]]:
    """Build one row per distribution that has a locked wheel, plus any problems."""

    installed = {
        normalize_distribution(dist.metadata["Name"]): dist
        for dist in importlib_metadata.distributions()
        if dist.metadata["Name"]
    }
    rows: list[DependencyRow] = []
    problems: list[str] = []
    for name in sorted(wheels):
        record = wheels[name]
        dist = installed.get(name)
        if dist is None:
            problems.append(f"bundled distribution is not installed in the build venv: {name}")
            continue
        if str(dist.version) != record.version:
            problems.append(
                "bundled distribution version differs from its wheel: "
                f"{name} installed={dist.version} wheel={record.version}"
            )
        rows.append(
            DependencyRow(
                name=name,
                version=record.version,
                license_expression=_license_expression(dist),
                wheel_sha256=record.wheel_sha256,
            )
        )
    return rows, problems


def render_dependencies(
    rows: list[DependencyRow],
    *,
    version: str,
    source_commit: str,
    python_version: str,
    lock_relative_path: str,
    lock_sha256: str,
    exclusions: dict[str, str],
    generated_at: str,
) -> str:
    lines = [
        "PDF Reader 便携发行版 依赖与许可证来源清单",
        "=" * 46,
        "",
        "本文档由 `packaging/windows/build.ps1` 在构建期生成，记录发行物内每个第三方",
        "Python 发行版的版本、其元数据声明的许可证以及对应 wheel 的 SHA-256。它不是",
        "法律意见，也不替代完整许可证文本；完整第三方声明与许可证正文按 P2-04 补入。",
        "",
        f"产品版本：{version}",
        f"源码提交：{source_commit}",
        f"私有 Python 运行时：{python_version}（随发行物提供，不使用系统 Python）",
        f"依赖锁文件：{lock_relative_path}",
        f"依赖锁 SHA-256：{lock_sha256}",
        f"生成时间（UTC）：{generated_at}",
        "",
        f"打包的发行版（{len(rows)}）",
        "-" * 46,
        f"{'发行版':<34}{'版本':<14}{'许可证（元数据声明）'}",
    ]
    for row in rows:
        lines.append(f"{row.name:<34}{row.version:<14}{row.license_expression}")
    lines.extend(
        [
            "",
            "wheel SHA-256（可逐条核对到依赖锁）",
            "-" * 46,
        ]
    )
    for row in rows:
        lines.append(f"{row.wheel_sha256}  {row.name}=={row.version}")
    lines.extend(
        [
            "",
            f"静态排除的锁定发行版（{len(exclusions)}）",
            "-" * 46,
        ]
    )
    for name in sorted(exclusions):
        lines.append(f"{name}: {exclusions[name]}")
    lines.extend(
        [
            "",
            "说明",
            "-" * 46,
            "1. 发行物不包含 pip / setuptools / wheel / pytest / mypy / ruff 等安装与开发工具，",
            "   运行期也不会调用系统 Python 或 pip。",
            "2. 本项目的自有代码与前端资源按仓库 LICENSE（AGPL-3.0-only）发布。",
            "3. 模型、字体等运行资源不在发行物内，首次使用时按需下载到便携目录 data/ 下，",
            "   其许可证随下载来源另行说明。",
            "",
        ]
    )
    return "\n".join(lines)


def write_dependencies(path: Path, body: str) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(body, encoding="utf-8", newline="\n")
    return destination
