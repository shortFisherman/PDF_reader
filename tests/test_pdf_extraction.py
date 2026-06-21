import tempfile
from pathlib import Path

import pymupdf

from pdf_extraction import extract_single_page


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
