"""P3-07 仓库治理契约：工具目录说明与依赖升级入口。"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_tool_directory_governance_doc_covers_required_dirs():
    doc = (REPO_ROOT / "docs" / "governance" / "tool-directories.md").read_text(encoding="utf-8")
    for name in (".agents", ".codex", ".comet", ".opencode", "openspec"):
        assert name in doc, f"governance doc missing {name}"
    assert "重建" in doc
    assert "事实来源" in doc
    assert "独立变更" in doc


def test_dependabot_covers_pip_and_npm():
    dependabot = (REPO_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    assert "package-ecosystem: pip" in dependabot
    assert "package-ecosystem: npm" in dependabot
