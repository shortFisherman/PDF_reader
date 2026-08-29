import logging
from pathlib import Path

import pymupdf

from pdf_reader.task_logging import task_log

logger = logging.getLogger("pdf_reader.extract")


def extract_single_page(src_doc: pymupdf.Document, page_num: int, tmpdir: Path) -> Path:
    single_page_pdf = tmpdir / "page.pdf"
    task_log(logger, logging.DEBUG, "extract page %d to %s", page_num + 1, single_page_pdf)
    single_doc = pymupdf.open()
    single_doc.insert_pdf(src_doc, from_page=page_num, to_page=page_num)
    single_doc.save(str(single_page_pdf))
    single_doc.close()
    return single_page_pdf


def extract_pages(src_doc: pymupdf.Document, page_indices: list[int], tmpdir: Path) -> Path:
    multi_page_pdf = tmpdir / "pages.pdf"
    task_log(
        logger,
        logging.DEBUG,
        "extract pages %d-%d to %s",
        page_indices[0] + 1,
        page_indices[-1] + 1,
        multi_page_pdf,
    )
    out_doc = pymupdf.open()
    for idx in page_indices:
        out_doc.insert_pdf(src_doc, from_page=idx, to_page=idx)
    out_doc.save(str(multi_page_pdf))
    out_doc.close()
    return multi_page_pdf
