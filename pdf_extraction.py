from pathlib import Path

import pymupdf


def extract_single_page(src_doc: pymupdf.Document, page_num: int, tmpdir: Path) -> Path:
    single_page_pdf = tmpdir / "page.pdf"
    single_doc = pymupdf.open()
    single_doc.insert_pdf(src_doc, from_page=page_num, to_page=page_num)
    single_doc.save(str(single_page_pdf))
    single_doc.close()
    return single_page_pdf
