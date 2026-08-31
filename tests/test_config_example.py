"""P4-01 配置示例与文档契约。

锁定 config.example.toml 与当前代码支持面一致：可解析、活跃键在白名单内、
全部 48 个支持键都有文档赋值行、无真实密钥；README 链接有效（含 URL 编码路径）。
roadmap 的链接可解析性由 test_documentation_governance 的常青文档链接检查覆盖。
"""

import re
import tomllib
from pathlib import Path
from urllib.parse import unquote

from pdf_reader import config

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_ROOT / "config.example.toml"
README = REPO_ROOT / "README.md"

_SECTION_HEADER = re.compile(r"^\[([a-zA-Z0-9_]+)\]\s*$")
_COMMENT_ASSIGNMENT = re.compile(r"^\s*#\s*([A-Za-z_][A-Za-z0-9_]*)\s*=")
_SECRET_LIKE = re.compile(r"sk-[A-Za-z0-9]{16,}")


def test_supported_key_count_is_48():
    supported = config._KNOWN_SECTION_KEYS
    assert sum(len(keys) for keys in supported.values()) == 48
    assert len(supported["pdf_reader"]) == 2
    assert len(supported["model"]) == 11
    assert len(supported["translation"]) == 10
    assert len(supported["server"]) == 3
    assert len(supported["term_extraction"]) == 7
    assert len(supported["pdf2zh"]) == 15


def test_example_is_toml_parseable():
    with open(EXAMPLE, "rb") as fh:
        data = tomllib.load(fh)
    assert isinstance(data, dict)


def test_active_keys_are_in_code_whitelist():
    with open(EXAMPLE, "rb") as fh:
        data = tomllib.load(fh)
    whitelist = config._KNOWN_SECTION_KEYS
    for section, keys in data.items():
        assert section in whitelist, f"未知 section [{section}] 出现在示例中"
        for key in keys:
            assert key in whitelist[section], f"[{section}].{key} 不在代码白名单中"


def test_all_supported_keys_have_example_assignments_in_their_section():
    """每个支持键必须在对应 section 有活跃或注释形式的赋值行（允许 recipes 重复）。"""
    with open(EXAMPLE, "rb") as fh:
        data = tomllib.load(fh)
    supported = config._KNOWN_SECTION_KEYS
    section_keys = {section: set(data.get(section, {})) for section in supported}
    current: str | None = None
    for line in EXAMPLE.read_text(encoding="utf-8").splitlines():
        header = _SECTION_HEADER.match(line)
        if header:
            current = header.group(1)
            continue
        assignment = _COMMENT_ASSIGNMENT.match(line)
        if assignment and current in section_keys:
            section_keys[current].add(assignment.group(1))

    for section, keys in supported.items():
        missing = sorted(keys - section_keys[section])
        assert not missing, f"[{section}] 缺少示例赋值行: {missing}"


def test_example_contains_no_real_api_key():
    text = EXAMPLE.read_text(encoding="utf-8")
    for line in text.splitlines():
        assert not _SECRET_LIKE.search(line), f"疑似真实 API Key: {line.strip()}"


def test_example_marks_legacy_translation_keys_as_1x_compat_aliases():
    text = EXAMPLE.read_text(encoding="utf-8")
    translation_section = text.split("[translation]", 1)[1].split("[term_extraction]", 1)[0]
    for key in ("term_qps", "term_pool_max_workers", "auto_extract_glossary"):
        assert key in translation_section
    assert "1.x 兼容" in text
    assert "2.0.0" in text
    assert "配置中心不再展示" in text
    assert "[term_extraction].qps" in text and "[term_extraction].max_workers" in text


def test_example_describes_cumulative_as_history_not_authoritative():
    text = EXAMPLE.read_text(encoding="utf-8")
    assert "cumulative_glossary.csv" in text
    assert "cumulative_glossary.csv.bak" in text
    assert "历史输入而非权威" in text
    assert "effective_glossary.csv" in text and "可重建产物" in text


def test_readme_links_to_example_and_design_doc():
    text = README.read_text(encoding="utf-8")
    assert "config.example.toml" in text
    assert "docs/pdf2zh-configuration-expansion-design.md" in text
    broken = []
    for target in re.findall(r"\]\(([^)]+)\)", text):
        link = target.strip()
        if link.startswith(("#", "http://", "https://", "mailto:")):
            continue
        if link.startswith("<") and link.endswith(">"):
            link = link[1:-1]
        path_part = unquote(link.split("#", 1)[0])
        if not (README.parent / path_part).resolve().exists():
            broken.append(target)
    assert not broken, f"README 链接无法解析: {broken}"
