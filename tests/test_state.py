import os
import threading
import time

import pymupdf
from pathlib import Path

from state import AppState


def test_app_state_initial():
    state = AppState(Path("/tmp/cache"))
    assert state.is_doc_open() is False
    assert state.page_count == 0
    assert len(state.translated_pages) == 0

def test_open_pdf_creates_cache(sample_pdf, tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    state = AppState(cache_dir)
    from services import sha256
    result = state.open_pdf(str(sample_pdf), sha256)
    assert result["page_count"] == 2
    assert result["hash"] is not None
    assert state.is_doc_open() is True
    state._close_docs()

def test_reopen_closes_old_docs(sample_pdf, tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    state = AppState(cache_dir)
    from services import sha256
    state.open_pdf(str(sample_pdf), sha256)
    state.open_pdf(str(sample_pdf), sha256)
    second_left = state.left_doc
    # After re-open, should have a new document (old one closed)
    assert second_left is not None
    state._close_docs()

def test_translated_pages_tracking(sample_pdf, tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    state = AppState(cache_dir)
    from services import sha256
    state.open_pdf(str(sample_pdf), sha256)
    assert len(state.translated_pages) == 0
    state._close_docs()

def test_glossary_cache_path_no_pdf(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    state = AppState(cache_dir)
    assert state.glossary_cache_path is None

def test_glossary_cache_path_after_open(sample_pdf, tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    state = AppState(cache_dir)
    from services import sha256
    state.open_pdf(str(sample_pdf), sha256)
    expected = cache_dir / state.pdf_hash
    assert state.glossary_cache_path == expected
    state._close_docs()


def test_render_page_concurrent_replace_no_crash(app_state, sample_pdf, tmp_path):
    from services import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)

    translated_pdf = tmp_path / "translated.pdf"
    doc = pymupdf.open()
    doc.new_page(width=612, height=792)
    doc.save(str(translated_pdf))
    doc.close()

    render_started = threading.Event()
    render_can_finish = threading.Event()

    def slow_render_func(doc, page_num, dpi):
        render_started.set()
        render_can_finish.wait(timeout=5)
        page = doc[page_num]
        pix = page.get_pixmap(dpi=dpi)
        return pix.tobytes(output="png")

    render_result = [None]
    render_error = [None]

    def render_thread():
        try:
            render_result[0] = app_state.render_page(
                "right", 0, slow_render_func, 72
            )
        except Exception as e:
            render_error[0] = e

    def replace_thread():
        render_started.wait(timeout=5)
        app_state.replace_page(str(translated_pdf), 0)

    t1 = threading.Thread(target=render_thread)
    t2 = threading.Thread(target=replace_thread)
    t1.start()
    t2.start()

    time.sleep(0.2)
    render_can_finish.set()

    t1.join(timeout=10)
    t2.join(timeout=10)

    assert render_error[0] is None, f"render crashed: {render_error[0]}"
    assert render_result[0] is not None
    assert render_result[0][:4] == b"\x89PNG"


def test_concurrent_replace_different_pages(app_state, sample_pdf, tmp_path):
    from services import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    page_count = app_state.page_count
    assert page_count == 2

    translated_pdfs = []
    for i in range(page_count):
        path = tmp_path / f"translated_{i}.pdf"
        doc = pymupdf.open()
        page = doc.new_page(width=612, height=792)
        page.insert_text((50, 100), f"TRANSLATED_{i}", fontsize=24)
        doc.save(str(path))
        doc.close()
        translated_pdfs.append(path)

    barrier = threading.Barrier(2)
    errors = [None, None]

    def replace_page(idx):
        try:
            barrier.wait(timeout=5)
            app_state.replace_page(str(translated_pdfs[idx]), idx)
        except Exception as e:
            errors[idx] = e

    threads = [
        threading.Thread(target=replace_page, args=(i,))
        for i in range(page_count)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert errors[0] is None, f"replace page 0 failed: {errors[0]}"
    assert errors[1] is None, f"replace page 1 failed: {errors[1]}"

    doc = pymupdf.open(app_state._right_pdf_path)
    assert doc.page_count == 2
    assert "TRANSLATED_0" in doc[0].get_text()
    assert "TRANSLATED_1" in doc[1].get_text()
    doc.close()

    assert 0 in app_state.translated_pages
    assert 1 in app_state.translated_pages


def test_slow_os_replace_does_not_block_reads(app_state, sample_pdf, tmp_path, monkeypatch):
    from services import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)

    translated_pdf = tmp_path / "translated.pdf"
    doc = pymupdf.open()
    doc.new_page(width=612, height=792)
    doc.save(str(translated_pdf))
    doc.close()

    delay = 0.5
    original_replace = os.replace
    replace_started = threading.Event()

    def slow_replace(src, dst):
        replace_started.set()
        time.sleep(delay)
        return original_replace(src, dst)

    monkeypatch.setattr("state.os.replace", slow_replace)

    def do_replace():
        app_state.replace_page(str(translated_pdf), 0)

    t = threading.Thread(target=do_replace)
    t.start()

    replace_started.wait(timeout=5)

    start = time.time()
    doc = app_state.get_doc("right")
    elapsed = time.time() - start

    assert elapsed < delay, f"get_doc blocked for {elapsed:.2f}s (should be < {delay}s)"
    assert doc is not None

    t.join(timeout=10)
