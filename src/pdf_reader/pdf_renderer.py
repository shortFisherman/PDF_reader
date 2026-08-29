import logging
from typing import cast

import pymupdf

logger = logging.getLogger("pdf_reader.render")


def render_page(doc: pymupdf.Document, page_num: int, dpi: int) -> bytes:
    if page_num < 0 or page_num >= doc.page_count:
        raise ValueError("page out of range")
    page = doc[page_num]
    pix = page.get_pixmap(dpi=dpi)
    logger.debug("[render] page=%d dpi=%d", page_num, dpi)
    return cast(bytes, pix.tobytes(output="png"))
