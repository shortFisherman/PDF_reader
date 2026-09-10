"""P3-07 仓库治理契约：工具目录说明、退役工具回归与依赖升级入口。"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

CURRENT_TOOL_DIRS = (
    ".codex",
    ".opencode",
    ".codegraph",
    ".firecrawl",
    ".worktrees",
    ".git-rewrite",
)
RETIRED_TOOL_DIRS = (".agents", ".comet")
RETIRED_COMET_PATHS = (
    ".agents/skills/comet",
    ".agents/skills/comet-any",
    ".agents/skills/comet-native",
    ".agents/skills/comet-review",
    ".opencode/skills/comet",
    ".opencode/skills/comet-any",
    ".opencode/skills/comet-native",
    ".opencode/skills/comet-review",
    ".opencode/commands/comet.md",
    ".opencode/commands/comet-any.md",
    ".opencode/commands/comet-native.md",
    ".opencode/commands/comet-review.md",
    ".opencode/rules/comet-workflow-guard.md",
    ".codex/rules/comet-workflow-guard.md",
    ".comet/config.yaml",
)


def test_tool_directory_governance_doc_covers_required_dirs():
    doc = (REPO_ROOT / "docs" / "governance" / "tool-directories.md").read_text(encoding="utf-8")
    for name in CURRENT_TOOL_DIRS:
        assert name in doc, f"governance doc missing {name}"
    assert "重建" in doc
    assert "事实来源" in doc
    assert "独立变更" in doc
    assert "退役工具" in doc


def test_codegraph_is_entirely_local_and_ignored_from_repo_root():
    """CodeGraph 数据和目录规则都属于各 clone 的本机可重建状态。"""
    ignore_lines = {
        line.strip()
        for line in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert ".codegraph/" in ignore_lines
    assert not (REPO_ROOT / ".codegraph" / ".gitignore").exists()


def test_retired_comet_dirs_are_not_current_tool_listing():
    """Comet 项目集成已退役：在用目录清单不得再把 .agents/.comet 写成在用/跟踪目录。"""
    doc = (REPO_ROOT / "docs" / "governance" / "tool-directories.md").read_text(encoding="utf-8")
    current_listing = doc.split("## 退役工具", 1)[0]
    for name in RETIRED_TOOL_DIRS:
        assert f"`{name}/`" not in current_listing, (
            f"retired tool dir {name}/ still listed as current in governance doc"
        )
    assert "2026-09-08" in doc, "governance doc missing Comet retirement date"


def test_retired_comet_project_integration_does_not_resurface():
    """有效 Comet 项目集成不得重新出现；历史文档仍可提及 Comet。"""
    ignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "Comet managed project state" not in ignore, "Comet managed-state ignore block returned"
    for name in RETIRED_TOOL_DIRS:
        root = REPO_ROOT / name
        assert not any(p.is_file() for p in root.rglob("*")), f"retired tool dir resurfaced with files: {name}/"
    for relative in RETIRED_COMET_PATHS:
        assert not (REPO_ROOT / relative).exists(), f"retired Comet installation path returned: {relative}"


def test_dependabot_covers_pip_and_npm():
    dependabot = (REPO_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    assert "package-ecosystem: pip" in dependabot
    assert "package-ecosystem: npm" in dependabot
