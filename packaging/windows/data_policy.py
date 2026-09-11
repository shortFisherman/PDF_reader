"""P1-03 build-contract checks for portable data in the Windows release artifact.

The real onedir ZIP only exists after P2-01.  This module locks the contract now:
it audits any staged artifact tree and the user-facing release notes, so the packager
can fail the build before shipping real ``data/``, a user ``config.toml``, model
weights or the document cache, and before shipping notes that hide the fact that
deleting the portable directory deletes configuration and caches.

Deliberately standard-library only, mirroring ``runtime_policy.py``.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

APP_DIRECTORY = "app"
DATA_DIRECTORY = "data"
LAUNCHER_EXECUTABLE = "PDF Reader.exe"
DEFAULT_RELEASE_NOTES = Path("README.md")

# 开发态/便携态目录若出现在发行包顶层，说明打包时误收了工作区，而不是干净的 staging 树。
LEAKED_TOP_LEVEL_NAMES = frozenset(
    {
        ".git",
        ".venv",
        "backups",
        "cache",
        "config",
        "docs",
        "documents",
        "fonts",
        "logs",
        "models",
        "node_modules",
        "runtime",
        "scripts",
        "src",
        "temp",
        "tests",
        "upstream-cache",
        "venv",
    }
)
USER_DATA_FILE_NAMES = frozenset(
    {"config.toml", "portable-data.json", "launcher.log", "instance.json", "migrations.log"}
)
MODEL_SUFFIXES = frozenset({".safetensors", ".gguf", ".onnx", ".ckpt", ".pt"})

# 每条 =（发行说明必须覆盖的事实，同一段内必须同时出现的关键词）。
REQUIRED_RELEASE_NOTES_FACTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("删除整个便携目录会删除配置和缓存", ("删除", "便携目录", "配置", "缓存")),
    ("旧安装的 data 可以复制或受控导入到新目录", ("导入", "data")),
)


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def audit_artifact_tree(artifact_root: Path) -> list[str]:
    """审计发行 staging 树或解包后的 ZIP 根目录，返回违反数据契约的条目。"""

    root = Path(artifact_root)
    if not root.is_dir():
        return [f"release artifact root is not a directory: {root}"]

    violations: list[str] = []
    for entry in sorted(root.iterdir()):
        if entry.name == DATA_DIRECTORY:
            if entry.is_symlink():
                violations.append(f"release artifact data path must not be a link: {entry.name}")
            elif not entry.is_dir():
                violations.append(f"release artifact data path must be a directory: {entry.name}")
            continue
        if entry.name.lower() in LEAKED_TOP_LEVEL_NAMES:
            violations.append(f"release artifact contains leaked development directory: {entry.name}/")

    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if DATA_DIRECTORY in relative.parts:
            if path.is_file() or path.is_symlink():
                violations.append(f"release artifact ships real portable data: {_relative(path, root)}")
            continue
        if not (path.is_file() or path.is_symlink()):
            continue
        if path.name.lower() in USER_DATA_FILE_NAMES:
            violations.append(f"release artifact ships user data file: {_relative(path, root)}")
        elif path.suffix.lower() in MODEL_SUFFIXES:
            violations.append(f"release artifact ships model weights: {_relative(path, root)}")
    return violations


def audit_release_notes(text: str) -> list[str]:
    """审计用户可见发行说明是否明确告知数据删除后果与迁移方式。"""

    paragraphs = [block for block in re.split(r"\n\s*\n", text) if block.strip()]
    violations: list[str] = []
    for label, keywords in REQUIRED_RELEASE_NOTES_FACTS:
        if not any(all(keyword in block for keyword in keywords) for block in paragraphs):
            violations.append(f"发行说明必须明确告知：{label}")
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the Windows portable data policy")
    parser.add_argument("--artifact", type=Path, required=True, help="发行 staging 树或解包后的 ZIP 根目录")
    parser.add_argument(
        "--release-notes",
        type=Path,
        default=Path(__file__).resolve().parents[2] / DEFAULT_RELEASE_NOTES,
        help="用户可见发行说明（默认仓库根 README.md）",
    )
    args = parser.parse_args(argv)

    violations = audit_artifact_tree(args.artifact)
    try:
        violations += audit_release_notes(args.release_notes.read_text(encoding="utf-8"))
    except OSError as exc:
        violations.append(f"cannot read release notes: {exc}")
    if violations:
        for violation in violations:
            print(f"ERROR [portable-data]: {violation}", file=sys.stderr)
        return 1
    print("portable-data: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
