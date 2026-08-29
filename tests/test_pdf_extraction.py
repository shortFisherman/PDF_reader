import logging
import tempfile
from pathlib import Path

import pymupdf

from pdf_extraction import extract_pages, extract_single_page


def test_extract_single_page_produces_one_page_pdf():
    src_doc = pymupdf.open()
    src_doc.new_page(width=612, height=792)
    src_doc.new_page(width=612, height=792)
    src_doc.new_page(width=612, height=792)

    tmpdir = Path(tempfile.mkdtemp())
    result_path = extract_single_page(src_doc, 1, tmpdir)

    assert result_path.exists()
    assert result_path.name == "page.pdf"
    out_doc = pymupdf.open(str(result_path))
    assert out_doc.page_count == 1
    out_doc.close()
    src_doc.close()


def test_extract_single_page_correct_content():
    src_doc = pymupdf.open()
    page0 = src_doc.new_page(width=612, height=792)
    page0.insert_text((72, 72), "Page Zero")
    page1 = src_doc.new_page(width=612, height=792)
    page1.insert_text((72, 72), "Page One")
    page2 = src_doc.new_page(width=612, height=792)
    page2.insert_text((72, 72), "Page Two")

    tmpdir = Path(tempfile.mkdtemp())
    result_path = extract_single_page(src_doc, 1, tmpdir)

    out_doc = pymupdf.open(str(result_path))
    text = out_doc[0].get_text()
    assert "Page One" in text
    assert "Page Zero" not in text
    assert "Page Two" not in text
    out_doc.close()
    src_doc.close()


def test_extract_pages_produces_multi_page_pdf_in_order():
    src_doc = pymupdf.open()
    for i in range(4):
        p = src_doc.new_page(width=612, height=792)
        p.insert_text((72, 72), f"Page{i}", fontsize=24)

    tmpdir = Path(tempfile.mkdtemp())
    result_path = extract_pages(src_doc, [0, 1, 2], tmpdir)

    assert result_path.exists()
    assert result_path.name == "pages.pdf"
    out_doc = pymupdf.open(str(result_path))
    assert out_doc.page_count == 3
    assert "Page0" in out_doc[0].get_text()
    assert "Page1" in out_doc[1].get_text()
    assert "Page2" in out_doc[2].get_text()
    out_doc.close()
    src_doc.close()


def test_extract_pages_non_contiguous_indices():
    src_doc = pymupdf.open()
    for i in range(5):
        p = src_doc.new_page(width=612, height=792)
        p.insert_text((72, 72), f"P{i}", fontsize=24)

    tmpdir = Path(tempfile.mkdtemp())
    result_path = extract_pages(src_doc, [0, 2, 4], tmpdir)

    out_doc = pymupdf.open(str(result_path))
    assert out_doc.page_count == 3
    assert "P0" in out_doc[0].get_text()
    assert "P2" in out_doc[1].get_text()
    assert "P4" in out_doc[2].get_text()
    out_doc.close()
    src_doc.close()


def test_extract_single_page_debug_off_no_output(caplog):
    caplog.set_level(logging.INFO, logger="pdf_reader.extract")

    src_doc = pymupdf.open()
    src_doc.new_page(width=612, height=792)
    src_doc.new_page(width=612, height=792)
    tmpdir = Path(tempfile.mkdtemp())
    extract_single_page(src_doc, 0, tmpdir)
    src_doc.close()

    records = [r for r in caplog.records if r.name == "pdf_reader.extract"]
    assert len(records) == 0, f"expected no DEBUG from extract_single_page, got: {[r.message for r in records]}"


def test_extract_single_page_debug_on_logs_debug(caplog):
    caplog.set_level(logging.DEBUG, logger="pdf_reader.extract")

    src_doc = pymupdf.open()
    src_doc.new_page(width=612, height=792)
    src_doc.new_page(width=612, height=792)
    tmpdir = Path(tempfile.mkdtemp())
    extract_single_page(src_doc, 1, tmpdir)
    src_doc.close()

    records = [r for r in caplog.records if r.name == "pdf_reader.extract" and r.levelno == logging.DEBUG]
    assert len(records) >= 1, f"expected DEBUG from extract_single_page, got: {[r.message for r in caplog.records]}"
    msg = records[0].message
    assert "extract page 2" in msg
    assert str(tmpdir / "page.pdf") in msg


def test_extract_pages_debug_off_no_output(caplog):
    caplog.set_level(logging.INFO, logger="pdf_reader.extract")

    src_doc = pymupdf.open()
    for i in range(4):
        src_doc.new_page(width=612, height=792)
    tmpdir = Path(tempfile.mkdtemp())
    extract_pages(src_doc, [0, 1, 2], tmpdir)
    src_doc.close()

    records = [r for r in caplog.records if r.name == "pdf_reader.extract"]
    assert len(records) == 0, f"expected no DEBUG from extract_pages, got: {[r.message for r in records]}"


def test_extract_pages_debug_on_logs_debug(caplog):
    caplog.set_level(logging.DEBUG, logger="pdf_reader.extract")

    src_doc = pymupdf.open()
    for i in range(4):
        src_doc.new_page(width=612, height=792)
    tmpdir = Path(tempfile.mkdtemp())
    extract_pages(src_doc, [0, 1, 2], tmpdir)
    src_doc.close()

    records = [r for r in caplog.records if r.name == "pdf_reader.extract" and r.levelno == logging.DEBUG]
    assert len(records) >= 1, f"expected DEBUG from extract_pages, got: {[r.message for r in caplog.records]}"
    msg = records[0].message
    assert "extract pages 1-3" in msg
    assert str(tmpdir / "pages.pdf") in msg
