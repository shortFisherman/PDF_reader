"""P3-06 文档治理的可执行检查。

只检查常青文档的职责边界、链接可解析性、上游契约命令一致性与易腐数字基线；
不使用脆弱的全文关键词禁令，不触碰 docs/archive/ 与 openspec/ 历史内容。
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

README = REPO_ROOT / "README.md"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
ARCHITECTURE = REPO_ROOT / "docs" / "architecture.md"
PROJECT = REPO_ROOT / "docs" / "project.md"
ROADMAP = REPO_ROOT / "docs" / "roadmap.md"
DEP_UPGRADE = REPO_ROOT / "docs" / "governance" / "dependency-upgrade.md"
DOCUMENTATION = REPO_ROOT / "docs" / "governance" / "documentation.md"
LICENSE_DOC = REPO_ROOT / "docs" / "governance" / "license.md"
TOOL_DIRS_DOC = REPO_ROOT / "docs" / "governance" / "tool-directories.md"

LINK_CHECKED_DOCS = (
    README,
    CHANGELOG,
    ARCHITECTURE,
    PROJECT,
    ROADMAP,
    DEP_UPGRADE,
    DOCUMENTATION,
    LICENSE_DOC,
    TOOL_DIRS_DOC,
)

CONTRACT_COMMAND = "python -m pytest tests/test_upstream_contract.py tests/test_dependency_contract.py"

NUMBER_PATTERNS = (
    re.compile(r"\d+\s*个\s*(?:Python\s+)?测试"),
    re.compile(r"\d+\s*个\s*pytest\s*文件"),
    re.compile(r"pytest\s+\d+"),
    re.compile(r"\d+\s*个\s*用例"),
    re.compile(r"\d+\s*行"),
)


def test_architecture_records_current_head_facts_only():
    text = ARCHITECTURE.read_text(encoding="utf-8")
    assert "当前 HEAD" in text
    assert "pdf2zh-next" in text and "2.9.0" in text
    assert "babeldoc" in text and "0.6.2" in text
    assert "tests/test_upstream_contract.py" in text
    assert "python -m pdf_reader" in text
    assert "settings.translation.output" in text
    assert "AGPL-3.0" in text and "LICENSE" in text
    assert "核验日期" in text and "commit" in text
    for word in ("验收标准", "建议实施步骤", "目标状态"):
        assert word not in text, f"architecture.md 不应出现台账/计划措辞：{word}"
    assert not re.search(r"状态[：:]\s*`(待处理|进行中|已改进)", text), "architecture.md 不应出现台账状态标记"


def test_project_doc_keeps_long_term_scope():
    text = PROJECT.read_text(encoding="utf-8")
    for marker in ("长期意图", "产品边界", "常青原则", "路线图不授权实施"):
        assert marker in text
    assert not re.search(r"\b[0-9a-f]{7,40}\b", text), "project.md 不应携带 commit 哈希等当前事实"
    assert not re.search(r"\d+\s*个\s*(?:Python\s+)?测试", text), "project.md 不应携带测试数量"
    assert "pytest" not in text and "覆盖率" not in text
    assert "已完成" not in text


def test_roadmap_keeps_candidates_and_open_decisions():
    text = ROADMAP.read_text(encoding="utf-8")
    assert "不是实施授权" in text
    assert "engineering-improvement-plan-829.md" in text
    assert "已完成" in text  # 状态定义表保留“已完成”语义
    assert "待讨论" in text
    assert not re.search(r"P3.{0,60}已完成", text), "P3 尚未全部收口，roadmap 不得宣称 P3 已完成"


def test_evergreen_doc_links_resolve():
    broken = []
    for doc in LINK_CHECKED_DOCS:
        text = doc.read_text(encoding="utf-8")
        for target in re.findall(r"\]\(([^)]+)\)", text):
            link = target.strip()
            if link.startswith(("#", "http://", "https://", "mailto:")):
                continue
            path_part = link.split("#", 1)[0]
            if not (doc.parent / path_part).resolve().exists():
                broken.append(f"{doc.relative_to(REPO_ROOT)} -> {link}")
    assert not broken, "以下文档链接无法解析：\n" + "\n".join(broken)


def test_upstream_contract_command_consistent_across_docs():
    assert CONTRACT_COMMAND in DEP_UPGRADE.read_text(encoding="utf-8")
    assert CONTRACT_COMMAND in README.read_text(encoding="utf-8")
    assert "tests/test_upstream_contract.py" in ARCHITECTURE.read_text(encoding="utf-8")
    assert (REPO_ROOT / "tests" / "test_upstream_contract.py").is_file()
    assert "docs/governance/documentation.md" in README.read_text(encoding="utf-8")


def test_perishable_numbers_have_baselines():
    for doc in (PROJECT, ROADMAP, README, DEP_UPGRADE, DOCUMENTATION):
        text = doc.read_text(encoding="utf-8")
        for pattern in NUMBER_PATTERNS:
            assert not pattern.search(text), f"{doc.name} 不应包含无基线易腐数字：{pattern.pattern}"

    architecture_text = ARCHITECTURE.read_text(encoding="utf-8")
    assert "核验基线" in architecture_text and "核验日期" in architecture_text
    for line in architecture_text.splitlines():
        if any(pattern.search(line) for pattern in NUMBER_PATTERNS):
            assert any(token in line for token in ("核验", "基线", "commit", "P3-0")), (
                f"architecture.md 中易腐数字缺少核验基线：{line.strip()}"
            )

    changelog_text = CHANGELOG.read_text(encoding="utf-8")
    dated_heading = None
    for line in changelog_text.splitlines():
        heading = re.match(r"^##\s+(\d{4}-\d{2}-\d{2})", line)
        if heading:
            dated_heading = heading.group(1)
            continue
        if any(pattern.search(line) for pattern in NUMBER_PATTERNS):
            assert dated_heading is not None, f"CHANGELOG 中存在无日期基线的易腐数字：{line.strip()}"


def test_documentation_governance_doc_covers_triggers_and_policy():
    text = DOCUMENTATION.read_text(encoding="utf-8")
    for fragment in (
        "architecture.md",
        "project.md",
        "roadmap.md",
        "依赖升级",
        "易腐数字",
        "冲突优先级",
        "tests/test_upstream_contract.py",
    ):
        assert fragment in text
