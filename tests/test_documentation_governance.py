"""P3-06 文档治理的可执行检查。

只检查常青文档的职责边界、链接可解析性、上游契约命令一致性与易腐数字基线；
不使用脆弱的全文关键词禁令，不触碰 docs/archive/ 与 openspec/ 历史内容。
"""

import re
from pathlib import Path
from urllib.parse import unquote

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

BASELINE_CONTEXT = re.compile(r"核验|基线|commit|日期|\d{4}-\d{2}-\d{2}")
BASELINE_SECTION = re.compile(r"^#{1,6}\s+.*(?:核验基线|核验日期|本次基线)", re.MULTILINE)
HEADING = re.compile(r"^#{1,6}\s+")


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
    assert not re.search(r"\bP[0-3](?:-\d{2})?\b", text), "project.md 不应携带 P0–P3 台账编号等短期实施状态"
    assert not re.search(r"状态\s*[：:]\s*[`]*(?:待处理|进行中)", text), "project.md 不应出现台账状态标记"
    assert not re.search(r"\b[0-9a-f]{7,40}\b", text), "project.md 不应携带 commit 哈希等短期提交事实"
    assert not re.search(r"\d+\s*个\s*(?:Python\s+)?测试", text), "project.md 不应携带测试数量"
    assert "pytest" not in text, "project.md 不应出现测试命令"
    assert "覆盖率" not in text, "project.md 不应携带覆盖率等实施状态"


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
            if link.startswith("<") and link.endswith(">"):
                link = link[1:-1]
            path_part = unquote(link.split("#", 1)[0])
            if not (doc.parent / path_part).resolve().exists():
                broken.append(f"{doc.relative_to(REPO_ROOT)} -> {link}")
    assert not broken, "以下文档链接无法解析：\n" + "\n".join(broken)


def test_upstream_contract_command_consistent_across_docs():
    assert CONTRACT_COMMAND in DEP_UPGRADE.read_text(encoding="utf-8")
    assert CONTRACT_COMMAND in README.read_text(encoding="utf-8")
    assert "tests/test_upstream_contract.py" in ARCHITECTURE.read_text(encoding="utf-8")
    assert (REPO_ROOT / "tests" / "test_upstream_contract.py").is_file()
    assert "docs/governance/documentation.md" in README.read_text(encoding="utf-8")


def _line_has_baseline_context(line: str) -> bool:
    return bool(BASELINE_CONTEXT.search(line))


def _nearby_heading_has_baseline_context(lines: list[str], index: int, window: int = 12) -> bool:
    for previous in reversed(lines[max(0, index - window) : index]):
        if HEADING.match(previous):
            return bool(BASELINE_CONTEXT.search(previous))
    return False


def _perishable_number_violations(text: str) -> list[str]:
    """返回缺少日期/commit/核验基线上下文的易腐数字所在行。

    - 同行出现 核验/基线/commit/日期（含 YYYY-MM-DD）视为明确基线上下文；
    - 最近的前置 Markdown 标题（≤12 行内）含同样上下文视为邻近标题基线；
    - 文档存在“核验基线”小节时整份文档以该节为基线（如 docs/architecture.md）。
    普通版本号、页码、协议编号等不属于易腐数字模式，不参与判定。
    """
    if BASELINE_SECTION.search(text):
        return []
    violations = []
    for index, line in enumerate(text.splitlines()):
        if any(pattern.search(line) for pattern in NUMBER_PATTERNS):
            if not (_line_has_baseline_context(line) or _nearby_heading_has_baseline_context(text.splitlines(), index)):
                violations.append(line.strip())
    return violations


def test_perishable_numbers_have_baselines():
    for doc in (PROJECT, ROADMAP, README, DEP_UPGRADE, DOCUMENTATION, ARCHITECTURE):
        violations = _perishable_number_violations(doc.read_text(encoding="utf-8"))
        assert not violations, f"{doc.name} 中存在缺少核验基线的易腐数字：{violations}"

    changelog_text = CHANGELOG.read_text(encoding="utf-8")
    dated_heading = None
    for line in changelog_text.splitlines():
        heading = re.match(r"^##\s+(\d{4}-\d{2}-\d{2})", line)
        if heading:
            dated_heading = heading.group(1)
            continue
        if any(pattern.search(line) for pattern in NUMBER_PATTERNS):
            assert dated_heading is not None, f"CHANGELOG 中存在无日期基线的易腐数字：{line.strip()}"


def test_perishable_number_policy_rejects_bare_test_count():
    assert _perishable_number_violations("本次收集到 594 个测试") == ["本次收集到 594 个测试"]


def test_perishable_number_policy_allows_baselined_test_count():
    assert _perishable_number_violations("核验日期 2026-08-30；本次基线 594 个测试") == []
    assert _perishable_number_violations("commit 6cf2af2 基线：594 个测试") == []
    assert _perishable_number_violations("## 2026-08-30 测试基线\n\n594 个测试") == []


def test_perishable_number_policy_ignores_versions_pages_and_protocols():
    text = "\n".join(
        (
            "pdf2zh-next 2.9.0 / babeldoc 0.6.2、Python 3.12.8",
            "第 42 页，共 320 页",
            "HTTP/1.1 与 RFC 9110，服务端口 5000",
            "coverage 全局 line 94.8%、branch 88.3%",
        )
    )
    assert _perishable_number_violations(text) == []


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
