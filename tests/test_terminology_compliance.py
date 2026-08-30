"""P0-05 术语合规验证模块：纯文本判定核心、PDF 提取包装、unknown 语义与有界纠错块。"""

from __future__ import annotations

import re
from pathlib import Path

import pymupdf

from pdf_reader.terminology_compliance import (
    MAX_RETRY_CORRECTION_BLOCK_UTF8_BYTES,
    ComplianceStatus,
    compose_retry_correction_prompt,
    normalize_text,
    verify_translated_pdf,
    verify_translated_text,
)

_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]")


def _pdf(tmp_path: Path, texts: list[str], name: str = "doc.pdf") -> Path:
    """逐页插入文本；含 CJK 时使用 PyMuPDF 内置中文字体保证可提取。"""
    pdf_path = tmp_path / name
    doc = pymupdf.open()
    for text in texts:
        page = doc.new_page()
        if _CJK.search(text):
            page.insert_font(fontname="china-s")
        page.insert_text((72, 72), text, fontname="china-s" if _CJK.search(text) else "helv")
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def _pdf_lines(tmp_path: Path, lines: list[str], name: str = "lines.pdf") -> Path:
    """把多行文本插入同一页，用于断行/空白边界 fixture。"""
    pdf_path = tmp_path / name
    doc = pymupdf.open()
    page = doc.new_page()
    y = 72
    for text in lines:
        font = "china-s" if _CJK.search(text) else "helv"
        if font == "china-s":
            page.insert_font(fontname="china-s")
        page.insert_text((72, y), text, fontname=font)
        y += 30
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def test_normalize_text_collapses_whitespace_and_cjk_adjacent_spaces():
    assert normalize_text("A\n B\t  C") == "A B C"
    assert normalize_text("阿尔茨海\n默病") == "阿尔茨海默病"
    assert normalize_text("阿尔茨海 默病") == "阿尔茨海默病"
    assert normalize_text("外用 糖皮质激素 和 获得控制") == "外用糖皮质激素和获得控制"
    assert normalize_text("  ") == ""


def test_verify_pass_chinese_target_with_line_break_inside_term(tmp_path):
    pdf_path = _pdf_lines(tmp_path, ["阿尔茨海", "默病 appears"])
    verdict = verify_translated_pdf(pdf_path, [("AD", "阿尔茨海默病")], expected_pages=1)
    assert verdict.status is ComplianceStatus.PASS
    assert len(verdict.checks) == 1
    assert verdict.checks[0].status is ComplianceStatus.PASS


def test_verify_translated_text_chinese_line_break_and_whitespace():
    verdict = verify_translated_text(
        "阿尔茨海\n默病 是 诊断结果",
        [("AD", "阿尔茨海默病")],
    )
    assert verdict.status is ComplianceStatus.PASS
    assert verdict.checks[0].status is ComplianceStatus.PASS


def test_verify_translated_text_ascii_word_boundary():
    hit = verify_translated_text("REST API 接口", [("API", "API")])
    assert hit.status is ComplianceStatus.PASS
    miss = verify_translated_text("REST APIs 接口", [("API", "API")])
    assert miss.status is ComplianceStatus.FAIL
    assert miss.checks[0].reason == "target_not_found"


def test_verify_translated_text_missing_target_fail():
    verdict = verify_translated_text("AD 出现了，但译法错误", [("AD", "阿尔茨海默病")])
    assert verdict.status is ComplianceStatus.FAIL
    assert verdict.failed_terms == (("AD", "阿尔茨海默病"),)


def test_verify_translated_text_empty_text_unknown():
    verdict = verify_translated_text(" \n\t ", [("AD", "阿尔茨海默病")])
    assert verdict.status is ComplianceStatus.UNKNOWN
    assert verdict.reason == "empty_text"


def test_verify_translated_text_empty_terms_pass():
    assert verify_translated_text("", []).status is ComplianceStatus.PASS


def test_verify_translated_text_partial_failure_dominates():
    verdict = verify_translated_text(
        "阿尔茨海默病 出现了",
        [("AD", "阿尔茨海默病"), ("TCS", "外用糖皮质激素")],
    )
    assert verdict.status is ComplianceStatus.FAIL
    assert verdict.failed_terms == (("TCS", "外用糖皮质激素"),)


def test_verify_pass_multiple_terms_and_whitespace(tmp_path):
    pdf_path = _pdf(tmp_path, ["不良事件 和 获得 控制"])
    verdict = verify_translated_pdf(
        pdf_path,
        [("Adverse Event", "不良事件"), ("gaining control", "获得控制")],
        expected_pages=1,
    )
    assert verdict.status is ComplianceStatus.PASS


def test_verify_fail_when_target_missing(tmp_path):
    pdf_path = _pdf(tmp_path, ["AD 出现了，但译法错误"])
    verdict = verify_translated_pdf(pdf_path, [("AD", "阿尔茨海默病")], expected_pages=1)
    assert verdict.status is ComplianceStatus.FAIL
    assert verdict.checks[0].reason == "target_not_found"
    assert verdict.failed_terms == (("AD", "阿尔茨海默病"),)


def test_verify_fail_any_failure_dominates_unknown(tmp_path):
    ok_path = _pdf(tmp_path, ["阿尔茨海默病"])
    verdict = verify_translated_pdf(
        ok_path,
        [("AD", "阿尔茨海默病"), ("TCS", "外用糖皮质激素")],
        expected_pages=1,
    )
    assert verdict.status is ComplianceStatus.FAIL
    assert verdict.failed_terms == (("TCS", "外用糖皮质激素"),)


def test_verify_unknown_missing_file(tmp_path):
    verdict = verify_translated_pdf(tmp_path / "missing.pdf", [("AD", "阿尔茨海默病")], expected_pages=1)
    assert verdict.status is ComplianceStatus.UNKNOWN
    assert verdict.reason == "extraction_failed"
    assert verdict.checks == ()


def test_verify_unknown_corrupt_file(tmp_path):
    pdf_path = tmp_path / "corrupt.pdf"
    pdf_path.write_bytes(b"not a pdf at all")
    verdict = verify_translated_pdf(pdf_path, [("AD", "阿尔茨海默病")], expected_pages=1)
    assert verdict.status is ComplianceStatus.UNKNOWN
    assert verdict.reason == "extraction_failed"


def test_verify_unknown_empty_text(tmp_path):
    pdf_path = tmp_path / "blank.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(str(pdf_path))
    doc.close()
    verdict = verify_translated_pdf(pdf_path, [("AD", "阿尔茨海默病")], expected_pages=1)
    assert verdict.status is ComplianceStatus.UNKNOWN
    assert verdict.reason == "empty_text"


def test_verify_unknown_page_count_mismatch(tmp_path):
    pdf_path = _pdf(tmp_path, ["阿尔茨海默病", "第二页"])
    verdict = verify_translated_pdf(pdf_path, [("AD", "阿尔茨海默病")], expected_pages=1)
    assert verdict.status is ComplianceStatus.UNKNOWN
    assert verdict.reason == "page_count_mismatch"


def test_verify_ascii_target_respects_word_boundaries(tmp_path):
    hit_path = _pdf(tmp_path, ["REST API 接口"])
    assert verify_translated_pdf(hit_path, [("API", "API")], expected_pages=1).status is ComplianceStatus.PASS
    miss_path = _pdf(tmp_path, ["REST APIs 接口"])
    assert verify_translated_pdf(miss_path, [("API", "API")], expected_pages=1).status is ComplianceStatus.FAIL


def test_verify_empty_active_terms_returns_pass_without_opening(tmp_path):
    verdict = verify_translated_pdf(tmp_path / "missing.pdf", [])
    assert verdict.status is ComplianceStatus.PASS


def test_compose_retry_correction_prompt_preserves_base_and_appends_complete_pairs():
    base = 'page prompt\n\n[权威术语约束]\n- "AD" -> "阿尔茨海默病"'
    prompt = compose_retry_correction_prompt(
        base,
        [("AD", "阿尔茨海默病"), ('TCS, "top"', "外用糖皮质激素")],
    )
    assert prompt is not None
    assert prompt.startswith(base)
    assert prompt.index("[术语合规纠错]") > prompt.index("[权威术语约束]")
    assert '"AD"' in prompt and '"阿尔茨海默病"' in prompt
    assert '"TCS, \\"top\\""' in prompt
    assert prompt == compose_retry_correction_prompt(
        base,
        [("AD", "阿尔茨海默病"), ('TCS, "top"', "外用糖皮质激素")],
    )


def test_compose_retry_correction_prompt_bounded_and_never_truncates_half_line():
    oversized = ("H" * 50_000, "T" * 50_000)
    small = ("AD", "阿尔茨海默病")
    base = "base [权威术语约束]"
    prompt = compose_retry_correction_prompt(base, [oversized, small])
    assert prompt is not None
    block = prompt[len(base) :]
    assert len(block.encode("utf-8")) <= MAX_RETRY_CORRECTION_BLOCK_UTF8_BYTES
    assert '"AD"' in prompt
    assert '"HHH' not in prompt
    assert "省略 1 条" in prompt
    lines = [line for line in prompt.splitlines() if line.startswith("- ")]
    assert lines == ['- "AD" -> "阿尔茨海默病"']


def test_compose_retry_correction_prompt_no_failed_terms_returns_base():
    assert compose_retry_correction_prompt("base", []) == "base"
    assert compose_retry_correction_prompt(None, []) is None
