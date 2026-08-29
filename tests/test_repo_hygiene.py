"""P3-01 仓库卫生契约：忽略规则与跟踪边界。"""

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _tracked() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return result.stdout.splitlines()


def test_never_tracked_paths():
    tracked = set(_tracked())
    forbidden_prefixes = (
        "config.toml",
        ".env",
        ".git-rewrite/",
        "cache/",
        "venv/",
        "node_modules/",
        ".pytest_cache/",
        ".ruff_cache/",
        ".mypy_cache/",
        "__pycache__/",
        "coverage-artifacts/",
    )
    for name in tracked:
        if name == "logs/.gitkeep":
            continue  # 唯一允许的日志目录占位文件，用于保留 logs/ 目录结构
        assert not name.startswith(forbidden_prefixes), f"forbidden tracked path: {name}"


def test_gitignore_covers_known_local_state():
    ignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    for entry in (
        "venv/",
        "node_modules/",
        "cache/",
        "logs/",
        ".env",
        "config.toml",
        ".pytest_cache/",
        ".ruff_cache/",
        ".mypy_cache/",
        ".git-rewrite/",
        ".worktrees/",
        ".superpowers/",
        ".firecrawl/",
    ):
        assert entry in ignore, f".gitignore missing {entry!r}"


def test_user_pdf_paths_are_outside_repo():
    """用户 PDF 由绝对路径打开且位于仓库外，仓库内不应有 page.*.pdf/page.*.csv。"""
    assert "page.pdf" not in _tracked()
    assert "page.0.pdf" not in _tracked()
    assert "page.0.csv" not in _tracked()
