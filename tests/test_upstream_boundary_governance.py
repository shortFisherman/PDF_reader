"""P0-01 上游边界治理守卫：影子包、上游源码副本与生产 Monkey-patch。

守卫只检查 Git 跟踪内容与 src/pdf_reader 生产模块；tests/ 使用 mock patch /
monkeypatch 是合法测试替身，不在扫描范围内，避免误报。
"""

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PACKAGE = REPO_ROOT / "src" / "pdf_reader"

SHADOW_PREFIXES = (
    "pdf2zh_next/",
    "babeldoc/",
    "src/pdf2zh_next/",
    "src/babeldoc/",
)

# BabelDOC/pdf2zh-next 独有定义标记：真源码副本必然包含这些行。
UPSTREAM_DEFINITION_MARKERS = (
    "class SharedContextCrossSplitPart:",
    "class AutomaticTermExtractor:",
    "class TranslationConfig:",
    "class Glossary:",
    "class GlossaryEntry:",
    "def get_glossaries_for_translation(",
    "def finalize_auto_extracted_glossary(",
)

MONKEY_PATCH_PATTERNS = (
    # 直接给上游术语函数/类赋新值（含链式模块属性赋值）。
    re.compile(
        r"\b(?:AutomaticTermExtractor|get_glossaries_for_translation|"
        r"finalize_auto_extracted_glossary)\s*=(?!=)"
    ),
    re.compile(
        r"\b(?:pdf2zh_next|babeldoc)(?:\.[A-Za-z_][A-Za-z0-9_]*)+"
        r"\s*=(?!=)"
    ),
    re.compile(
        r"\bsetattr\s*\([^)]*(?:get_glossaries_for_translation|"
        r"AutomaticTermExtractor|finalize_auto_extracted_glossary)"
    ),
    re.compile(r"\bsys\.modules\s*\[\s*(['\"])pdf2zh_next\1\s*\]\s*=(?!=)"),
    re.compile(r"\bsys\.modules\s*\[\s*(['\"])babeldoc\1\s*\]\s*=(?!=)"),
    # 生产模块不得引入 mock / monkeypatch / patch 测试替身。
    re.compile(
        r"\b(?:from\s+unittest\.mock|from\s+mock|import\s+mock|"
        r"import\s+monkeypatch|monkeypatch|patch\s*\()"
    ),
)


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


def _monkey_patch_violations(root: Path) -> list[str]:
    violations: list[str] = []
    for py in sorted(root.rglob("*.py")):
        text = py.read_text(encoding="utf-8", errors="replace")
        for pattern in MONKEY_PATCH_PATTERNS:
            if pattern.search(text):
                try:
                    label = py.relative_to(REPO_ROOT)
                except ValueError:
                    label = py
                violations.append(f"{label}: {pattern.pattern}")
    return violations


def test_no_tracked_shadow_packages_or_upstream_source_copies():
    tracked = _tracked()
    assert tracked, "git ls-files 返回空，治理守卫无法运行"

    shadows: list[str] = []
    copies: list[str] = []
    for rel in tracked:
        normalized = rel.replace("\\", "/")
        if any(normalized.startswith(prefix) for prefix in SHADOW_PREFIXES):
            shadows.append(rel)
        if normalized.endswith(".py"):
            text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")
            for marker in UPSTREAM_DEFINITION_MARKERS:
                if marker in text:
                    copies.append(f"{rel}: {marker}")

    assert not shadows, f"发现被 Git 跟踪的 pdf2zh_next/babeldoc 影子包：{shadows}"
    assert not copies, f"发现疑似上游源码副本的 Git 跟踪文件：{copies}"


def test_no_production_monkey_patch_of_upstream_terminology():
    violations = _monkey_patch_violations(SRC_PACKAGE)
    assert not violations, "生产模块不得显式 Monkey-patch 上游术语功能、替换上游模块或引入测试替身：\n" + "\n".join(
        violations
    )


def test_guard_scope_excludes_test_patches(tmp_path):
    """守卫有检测能力，但只扫描 src/pdf_reader；tests/ 的合法 patch 不误报。"""
    fake_test = tmp_path / "test_like_fixture.py"
    fake_test.write_text(
        "from unittest.mock import patch\n"
        "\n"
        "def test_x():\n"
        "    with patch(\n"
        "        'babeldoc.format.pdf.translation_config."
        "SharedContextCrossSplitPart.get_glossaries_for_translation',\n"
        "        return_value=[],\n"
        "    ):\n"
        "        pass\n",
        encoding="utf-8",
    )

    assert _monkey_patch_violations(tmp_path), "守卫应能识别测试替身模式（有检测能力）"
    assert _monkey_patch_violations(SRC_PACKAGE) == [], "守卫只扫描 src/pdf_reader，不扫描 tests/"
