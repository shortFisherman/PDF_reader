"""TDD tests for INFO/ERROR logging in state.py: open_pdf, replace_page, replace_pages."""

import logging
from pathlib import Path

import pytest

from logging_config import setup_logging
from state import AppState


def test_open_pdf_logs_info_with_hash_and_pages(sample_pdf, tmp_path, caplog):
    """open_pdf 成功后产生 INFO 记录，包含 hash+pages+dim+cache 标记."""
    setup_logging(False)
    caplog.set_level(logging.INFO, logger="pdf_reader.state")

    from file_hash import sha256

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    state = AppState(cache_dir)
    result = state.open_pdf(str(sample_pdf), sha256)

    records = [r for r in caplog.records if r.name == "pdf_reader.state"]
    assert len(records) >= 1, "expected at least one INFO from open_pdf"
    msg = records[0].message
    assert "hash=" in msg
    assert "pages=" in msg
    assert "dim=" in msg
    assert "cache=" in msg
    assert result["page_count"] == 2


def test_replace_page_logs_info_on_success(app_state, sample_pdf, caplog):
    """replace_page 成功后产生 INFO，含 page 索引与 right.pdf 路径."""
    setup_logging(False)
    caplog.set_level(logging.INFO, logger="pdf_reader.state")

    from file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)

    # 构建单页译文 PDF
    import pymupdf
    translated_pdf = Path(sample_pdf).parent / "translated.pdf"
    doc = pymupdf.open()
    doc.new_page(width=612, height=792)
    doc.save(str(translated_pdf))
    doc.close()

    app_state.replace_page(str(translated_pdf), 0)

    records = [r for r in caplog.records if r.name == "pdf_reader.state" and r.levelno == logging.INFO]
    replace_msgs = [r.message for r in records if "replace" in r.message]
    assert len(replace_msgs) >= 1, f"expected replace INFO, got: {replace_msgs}"
    msg = replace_msgs[0]
    assert "page=" in msg
    assert "0" in msg
    assert "right.pdf" in msg


def test_replace_page_logs_error_and_reraises_on_failure(app_state, sample_pdf, caplog):
    """replace_page 失败时记录 ERROR+exc_info，然后重新抛出异常."""
    setup_logging(False)
    caplog.set_level(logging.INFO, logger="pdf_reader.state")

    from file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)

    with pytest.raises(Exception):
        app_state.replace_page("/nonexistent/path/translated.pdf", 0)

    records = [r for r in caplog.records if r.name == "pdf_reader.state" and r.levelno == logging.ERROR]
    assert len(records) >= 1, f"expected ERROR log, got: {[r.message for r in caplog.records]}"
    assert "page=" in records[0].message
    assert "replace failed" in records[0].message
    assert records[0].exc_info is not None


def test_replace_pages_logs_info_on_success(app_state, sample_pdf, caplog):
    """replace_pages 成功后产生 INFO，含 batch 标记、page_indices 与路径."""
    setup_logging(False)
    caplog.set_level(logging.INFO, logger="pdf_reader.state")

    from file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)

    import pymupdf
    translated_pdf = Path(sample_pdf).parent / "translated.pdf"
    doc = pymupdf.open()
    for _ in range(2):
        doc.new_page(width=612, height=792)
    doc.save(str(translated_pdf))
    doc.close()

    app_state.replace_pages(str(translated_pdf), [0, 1])

    records = [r for r in caplog.records if r.name == "pdf_reader.state" and r.levelno == logging.INFO]
    batch_msgs = [r.message for r in records if "[batch]" in r.message]
    assert len(batch_msgs) >= 1, f"expected batch INFO, got: {batch_msgs}"
    msg = batch_msgs[0]
    assert "[batch]" in msg
    assert "0" in msg
    assert "right.pdf" in msg


def test_render_page_debug_off_no_output(app_state, sample_pdf, caplog):
    """debug off 时 render_page 不产生 INFO 级别记录."""
    from file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    caplog.set_level(logging.INFO, logger="pdf_reader.render")

    app_state.render_page("left", 0, lambda doc, pn, dpi: __import__("pdf_renderer").render_page(doc, pn, dpi), 200)

    records = [r for r in caplog.records if r.name == "pdf_reader.render"]
    assert len(records) == 0, f"expected no INFO from render_page, got: {[r.message for r in records]}"


def test_render_page_debug_on_logs_debug(app_state, sample_pdf, caplog):
    """debug on 时 render_page 产生 DEBUG 记录含 [render] page=N."""
    from file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    caplog.set_level(logging.DEBUG, logger="pdf_reader.render")

    app_state.render_page("left", 0, lambda doc, pn, dpi: __import__("pdf_renderer").render_page(doc, pn, dpi), 200)

    records = [r for r in caplog.records if r.name == "pdf_reader.render" and r.levelno == logging.DEBUG]
    assert len(records) >= 1, f"expected DEBUG from render_page, got: {[r.message for r in caplog.records]}"
    msg = records[0].message
    assert "[render]" in msg
    assert "page=0" in msg


def test_replace_pages_logs_error_and_reraises_on_failure(app_state, sample_pdf, caplog):
    """replace_pages 失败时记录 ERROR+exc_info，然后重新抛出异常."""
    setup_logging(False)
    caplog.set_level(logging.INFO, logger="pdf_reader.state")

    from file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)

    with pytest.raises(Exception):
        app_state.replace_pages("/nonexistent/path/translated.pdf", [0])

    records = [r for r in caplog.records if r.name == "pdf_reader.state" and r.levelno == logging.ERROR]
    assert len(records) >= 1, f"expected ERROR log, got: {[r.message for r in caplog.records]}"
    assert "[batch]" in records[0].message
    assert "replace pages failed" in records[0].message
    assert records[0].exc_info is not None
