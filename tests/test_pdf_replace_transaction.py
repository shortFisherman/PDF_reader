"""P1-02 regression tests: PDF replacement must be transactional.

Every page mutation happens on an independent work copy opened from the last
committed right.pdf; the temp file is fully closed before the atomic rename;
the live document handle and _translated_pages are swapped only after the
disk commit succeeds. Injecting failures into open/delete/insert/save/close/
os.replace must leave the committed right.pdf and the AppState usable, and
later replacements must still work. These tests never call the translation
network.
"""

import os
from pathlib import Path

import pymupdf
import pytest

from pdf_reader.file_hash import sha256
from pdf_reader.pdf_renderer import render_page

pytestmark = pytest.mark.integration


def _make_translated_pdf(path: Path, pages: int = 1, label: str = "TRANS") -> Path:
    doc = pymupdf.open()
    try:
        for i in range(pages):
            page = doc.new_page(width=612, height=792)
            page.insert_text((50, 100), f"{label}_{i}", fontsize=24)
        doc.save(str(path))
    finally:
        doc.close()
    return path


def _committed_marker(app_state) -> tuple[str, int, frozenset[int]]:
    return sha256(app_state._right_pdf_path), app_state.page_count, app_state.translated_pages


def _assert_renderable(app_state) -> None:
    png = app_state.render_page("right", 0, render_page, 72)
    assert png[:4] == b"\x89PNG"


def _assert_no_tmp_left(app_state) -> None:
    assert not Path(app_state._right_pdf_path + ".tmp").exists()


def _track_docs(monkeypatch) -> list:
    """Track every pymupdf.Document opened after installation."""
    opened = []
    real_open = pymupdf.open

    def tracking_open(*args: object, **kwargs: object) -> pymupdf.Document:
        doc = real_open(*args, **kwargs)
        opened.append(doc)
        return doc

    monkeypatch.setattr(pymupdf, "open", tracking_open)
    return opened


def _assert_no_leaked_docs(opened, app_state) -> None:
    live = {app_state._right_doc, app_state._left_doc}
    for doc in opened:
        if doc in live:
            continue
        assert doc.is_closed, f"leaked open document: {doc!r}"


def _fail_open_at(monkeypatch, call_number: int) -> list:
    """pymupdf.open fails on the call_number-th invocation; track successful opens."""
    opened = []
    real_open = pymupdf.open
    counter = {"n": 0}

    def tracking_open(*args: object, **kwargs: object) -> pymupdf.Document:
        counter["n"] += 1
        if counter["n"] == call_number:
            raise RuntimeError(f"injected open failure at call {call_number}")
        doc = real_open(*args, **kwargs)
        opened.append(doc)
        return doc

    monkeypatch.setattr(pymupdf, "open", tracking_open)
    return opened


def _fail_method_once(monkeypatch, method_name: str, call_number: int = 1) -> None:
    real = getattr(pymupdf.Document, method_name)
    counter = {"n": 0}

    def failing(self, *args: object, **kwargs: object) -> object:
        counter["n"] += 1
        if counter["n"] == call_number:
            raise RuntimeError(f"injected {method_name} failure")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(pymupdf.Document, method_name, failing)


def _fail_os_replace_once(monkeypatch) -> None:
    real_replace = os.replace
    counter = {"n": 0}

    def failing_replace(src: object, dst: object) -> object:
        counter["n"] += 1
        if counter["n"] == 1:
            raise OSError("injected os.replace failure")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", failing_replace)


def _assert_failure_recovery(app_state, marker, opened) -> None:
    _assert_no_leaked_docs(opened, app_state)
    assert sha256(app_state._right_pdf_path) == marker[0]
    assert app_state.page_count == marker[1]
    assert app_state.translated_pages == marker[2]
    _assert_no_tmp_left(app_state)
    _assert_renderable(app_state)


def _assert_followup_replace_works(app_state, tmp_path, document_id) -> None:
    marker_before = _committed_marker(app_state)
    second = _make_translated_pdf(tmp_path / "second.pdf", label="SECOND")
    app_state.replace_page(str(second), 1, document_id)
    assert 1 in app_state.translated_pages
    assert sha256(app_state._right_pdf_path) != marker_before[0]
    with pymupdf.open(app_state._right_pdf_path) as doc:
        assert doc.page_count == 2
        assert "SECOND_0" in doc[1].get_text()
    _assert_renderable(app_state)


def test_single_replace_open_failure_keeps_committed_state(app_state, sample_pdf, tmp_path, monkeypatch):
    from pdf_reader.file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    document_id = app_state.translation_snapshot().document_id
    translated = _make_translated_pdf(tmp_path / "translated.pdf", label="FIRST")
    marker = _committed_marker(app_state)

    opened = _fail_open_at(monkeypatch, 1)
    with pytest.raises(RuntimeError, match="injected open failure"):
        app_state.replace_page(str(translated), 0, document_id)

    _assert_failure_recovery(app_state, marker, opened)
    _assert_followup_replace_works(app_state, tmp_path, document_id)


def test_single_replace_workcopy_open_failure_keeps_committed_state(app_state, sample_pdf, tmp_path, monkeypatch):
    from pdf_reader.file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    document_id = app_state.translation_snapshot().document_id
    translated = _make_translated_pdf(tmp_path / "translated.pdf", label="FIRST")
    marker = _committed_marker(app_state)

    opened = _fail_open_at(monkeypatch, 2)
    with pytest.raises(RuntimeError, match="injected open failure"):
        app_state.replace_page(str(translated), 0, document_id)

    _assert_failure_recovery(app_state, marker, opened)
    _assert_followup_replace_works(app_state, tmp_path, document_id)


def test_single_replace_delete_failure_keeps_committed_state(app_state, sample_pdf, tmp_path, monkeypatch):
    from pdf_reader.file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    document_id = app_state.translation_snapshot().document_id
    translated = _make_translated_pdf(tmp_path / "translated.pdf", label="FIRST")
    marker = _committed_marker(app_state)

    opened = _track_docs(monkeypatch)
    _fail_method_once(monkeypatch, "delete_page")
    with pytest.raises(RuntimeError, match="injected delete_page failure"):
        app_state.replace_page(str(translated), 0, document_id)

    _assert_failure_recovery(app_state, marker, opened)
    _assert_followup_replace_works(app_state, tmp_path, document_id)


def test_single_replace_insert_failure_keeps_committed_state(app_state, sample_pdf, tmp_path, monkeypatch):
    from pdf_reader.file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    document_id = app_state.translation_snapshot().document_id
    translated = _make_translated_pdf(tmp_path / "translated.pdf", label="FIRST")
    marker = _committed_marker(app_state)

    opened = _track_docs(monkeypatch)
    _fail_method_once(monkeypatch, "insert_pdf")
    with pytest.raises(RuntimeError, match="injected insert_pdf failure"):
        app_state.replace_page(str(translated), 0, document_id)

    _assert_failure_recovery(app_state, marker, opened)
    _assert_followup_replace_works(app_state, tmp_path, document_id)


def test_single_replace_save_failure_keeps_committed_state(app_state, sample_pdf, tmp_path, monkeypatch):
    from pdf_reader.file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    document_id = app_state.translation_snapshot().document_id
    translated = _make_translated_pdf(tmp_path / "translated.pdf", label="FIRST")
    marker = _committed_marker(app_state)

    opened = _track_docs(monkeypatch)
    _fail_method_once(monkeypatch, "save")
    with pytest.raises(RuntimeError, match="injected save failure"):
        app_state.replace_page(str(translated), 0, document_id)

    _assert_failure_recovery(app_state, marker, opened)
    _assert_followup_replace_works(app_state, tmp_path, document_id)


def test_single_replace_src_close_failure_keeps_committed_state(app_state, sample_pdf, tmp_path, monkeypatch):
    from pdf_reader.file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    document_id = app_state.translation_snapshot().document_id
    translated = _make_translated_pdf(tmp_path / "translated.pdf", label="FIRST")
    marker = _committed_marker(app_state)

    opened = _track_docs(monkeypatch)
    _fail_method_once(monkeypatch, "close")
    with pytest.raises(RuntimeError, match="injected close failure"):
        app_state.replace_page(str(translated), 0, document_id)

    _assert_failure_recovery(app_state, marker, opened)
    _assert_followup_replace_works(app_state, tmp_path, document_id)


def test_single_replace_old_doc_close_failure_recovers_handle(app_state, sample_pdf, tmp_path, monkeypatch):
    from pdf_reader.file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    document_id = app_state.translation_snapshot().document_id
    translated = _make_translated_pdf(tmp_path / "translated.pdf", label="FIRST")
    marker = _committed_marker(app_state)

    opened = _track_docs(monkeypatch)
    _fail_method_once(monkeypatch, "close", call_number=3)
    with pytest.raises(RuntimeError, match="injected close failure"):
        app_state.replace_page(str(translated), 0, document_id)

    _assert_failure_recovery(app_state, marker, opened)
    _assert_followup_replace_works(app_state, tmp_path, document_id)


def test_single_replace_os_replace_failure_keeps_committed_state(app_state, sample_pdf, tmp_path, monkeypatch):
    from pdf_reader.file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    document_id = app_state.translation_snapshot().document_id
    translated = _make_translated_pdf(tmp_path / "translated.pdf", label="FIRST")
    marker = _committed_marker(app_state)

    opened = _track_docs(monkeypatch)
    _fail_os_replace_once(monkeypatch)
    with pytest.raises(OSError, match="injected os.replace failure"):
        app_state.replace_page(str(translated), 0, document_id)

    _assert_failure_recovery(app_state, marker, opened)
    _assert_followup_replace_works(app_state, tmp_path, document_id)


def test_single_replace_final_reopen_failure_recovers_from_disk(app_state, sample_pdf, tmp_path, monkeypatch):
    from pdf_reader.file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    document_id = app_state.translation_snapshot().document_id
    translated = _make_translated_pdf(tmp_path / "translated.pdf", label="FIRST")
    marker = _committed_marker(app_state)

    opened = _fail_open_at(monkeypatch, 3)
    with pytest.raises(RuntimeError, match="injected open failure"):
        app_state.replace_page(str(translated), 0, document_id)

    _assert_no_leaked_docs(opened, app_state)
    assert sha256(app_state._right_pdf_path) != marker[0]
    assert app_state.page_count == marker[1]
    assert 0 in app_state.translated_pages
    _assert_no_tmp_left(app_state)
    _assert_renderable(app_state)
    _assert_followup_replace_works(app_state, tmp_path, document_id)


def test_batch_replace_save_failure_keeps_committed_state(app_state, sample_pdf, tmp_path, monkeypatch):
    from pdf_reader.file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    document_id = app_state.translation_snapshot().document_id
    translated = _make_translated_pdf(tmp_path / "translated.pdf", pages=2, label="FIRST")
    marker = _committed_marker(app_state)

    opened = _track_docs(monkeypatch)
    _fail_method_once(monkeypatch, "save")
    with pytest.raises(RuntimeError, match="injected save failure"):
        app_state.replace_pages(str(translated), [0, 1], document_id)

    _assert_failure_recovery(app_state, marker, opened)
    marker_after = _committed_marker(app_state)
    second = _make_translated_pdf(tmp_path / "second.pdf", pages=2, label="SECOND")
    app_state.replace_pages(str(second), [0, 1], document_id)
    assert app_state.translated_pages == frozenset({0, 1})
    assert sha256(app_state._right_pdf_path) != marker_after[0]
    with pymupdf.open(app_state._right_pdf_path) as doc:
        assert doc.page_count == 2
        assert "SECOND_0" in doc[0].get_text()
        assert "SECOND_1" in doc[1].get_text()
    _assert_renderable(app_state)


def test_batch_replace_os_replace_failure_keeps_committed_state(app_state, sample_pdf, tmp_path, monkeypatch):
    from pdf_reader.file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    document_id = app_state.translation_snapshot().document_id
    translated = _make_translated_pdf(tmp_path / "translated.pdf", pages=2, label="FIRST")
    marker = _committed_marker(app_state)

    opened = _track_docs(monkeypatch)
    _fail_os_replace_once(monkeypatch)
    with pytest.raises(OSError, match="injected os.replace failure"):
        app_state.replace_pages(str(translated), [0, 1], document_id)

    _assert_failure_recovery(app_state, marker, opened)
    _assert_followup_replace_works(app_state, tmp_path, document_id)
