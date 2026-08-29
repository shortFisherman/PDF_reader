"""P0-01 regression tests: translation results must bind to an immutable document identity.

A task started on document A must never write into a different document (or a
newer session of the same path) after the user switches documents. These tests
exercise the identity-guarded AppState API surface directly and never call the
translation network.
"""

import csv
import threading
from dataclasses import FrozenInstanceError, is_dataclass
from pathlib import Path

import pymupdf
import pytest

from file_hash import sha256


def _identity_api() -> tuple[type, type]:
    from state import DocumentSnapshot, StaleDocumentError

    return DocumentSnapshot, StaleDocumentError


def _make_pdf(path: Path, page_count: int = 2, label: str = "DOC") -> Path:
    doc = pymupdf.open()
    try:
        for i in range(page_count):
            page = doc.new_page(width=612, height=792)
            page.insert_text((50, 100), f"{label}_{i}", fontsize=24)
        doc.save(str(path))
    finally:
        doc.close()
    return path


def _make_translated_pdf(path: Path, labels: list[str]) -> Path:
    doc = pymupdf.open()
    try:
        for label in labels:
            page = doc.new_page(width=612, height=792)
            page.insert_text((50, 100), label, fontsize=24)
        doc.save(str(path))
    finally:
        doc.close()
    return path


def _write_csv(path: Path, rows: list[tuple[str, str]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["source", "target"])
        writer.writerows(rows)


def _read_csv(path: Path) -> list[tuple[str, str]]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [(row["source"], row["target"]) for row in csv.DictReader(f)]


def _assert_right_doc_unchanged(
    app_state,
    right_hash_before: str,
    page_count_before: int,
    translated_before: frozenset[int],
) -> None:
    right_path = app_state._right_pdf_path
    assert sha256(right_path) == right_hash_before
    with pymupdf.open(right_path) as doc:
        assert doc.page_count == page_count_before
    assert app_state.page_count == page_count_before
    assert app_state.translated_pages == translated_before


def test_document_snapshot_is_frozen_and_carries_identity_fields(app_state, sample_pdf):
    DocumentSnapshot, _ = _identity_api()
    app_state.open_pdf(str(sample_pdf), sha256)
    snapshot = app_state.translation_snapshot()

    assert is_dataclass(snapshot)
    assert isinstance(snapshot, DocumentSnapshot)
    assert isinstance(snapshot.document_id, str)
    assert len(snapshot.document_id) > 0
    assert snapshot.pdf_hash == app_state.pdf_hash
    assert snapshot.page_count == app_state.page_count
    assert snapshot.glossary_cache_path == app_state.glossary_cache_path

    with pytest.raises(FrozenInstanceError):
        snapshot.document_id = "mutated"


def test_document_id_stable_until_next_open(app_state, sample_pdf):
    DocumentSnapshot, _ = _identity_api()
    app_state.open_pdf(str(sample_pdf), sha256)
    first = app_state.translation_snapshot()
    second = app_state.translation_snapshot()

    assert first.document_id == second.document_id


def test_reopen_same_pdf_creates_new_document_id(app_state, sample_pdf):
    DocumentSnapshot, _ = _identity_api()
    app_state.open_pdf(str(sample_pdf), sha256)
    first = app_state.translation_snapshot()

    app_state.open_pdf(str(sample_pdf), sha256)
    second = app_state.translation_snapshot()

    assert second.document_id != first.document_id
    assert second.pdf_hash == first.pdf_hash
    assert second.page_count == first.page_count
    assert second.glossary_cache_path == first.glossary_cache_path


def test_translation_snapshot_is_taken_under_state_lock(app_state, sample_pdf):
    DocumentSnapshot, _ = _identity_api()
    app_state.open_pdf(str(sample_pdf), sha256)

    started = threading.Event()
    finished = threading.Event()
    snapshots: list[object] = []

    def worker() -> None:
        started.set()
        snapshots.append(app_state.translation_snapshot())
        finished.set()

    app_state._lock.acquire()
    try:
        worker_thread = threading.Thread(target=worker)
        worker_thread.start()
        assert started.wait(timeout=5)
        worker_thread.join(timeout=0.2)
        assert worker_thread.is_alive(), "translation_snapshot must acquire the state lock"
    finally:
        app_state._lock.release()

    assert finished.wait(timeout=5)
    assert len(snapshots) == 1
    assert isinstance(snapshots[0], DocumentSnapshot)


def test_stale_single_page_replace_rejected_and_current_document_untouched(app_state, sample_pdf, tmp_path):
    _, StaleDocumentError = _identity_api()
    pdf_b = _make_pdf(tmp_path / "b.pdf", label="B")
    translated_b_1 = _make_translated_pdf(tmp_path / "translated_b_1.pdf", ["VALID_B_1"])
    translated_a_0 = _make_translated_pdf(tmp_path / "translated_a_0.pdf", ["STALE_A_0"])

    app_state.open_pdf(str(sample_pdf), sha256)
    snapshot_a = app_state.translation_snapshot()

    app_state.open_pdf(str(pdf_b), sha256)
    snapshot_b = app_state.translation_snapshot()
    app_state.replace_page(str(translated_b_1), 1, snapshot_b.document_id)

    right_path_b = app_state._right_pdf_path
    right_hash_before = sha256(right_path_b)
    page_count_before = app_state.page_count
    translated_before = app_state.translated_pages
    assert translated_before == frozenset({1})

    with pytest.raises(StaleDocumentError):
        app_state.replace_page(str(translated_a_0), 0, snapshot_a.document_id)

    _assert_right_doc_unchanged(app_state, right_hash_before, page_count_before, translated_before)
    assert 0 not in app_state.translated_pages


def test_matching_single_page_replace_still_applies(app_state, sample_pdf, tmp_path):
    DocumentSnapshot, _ = _identity_api()
    translated = _make_translated_pdf(tmp_path / "translated.pdf", ["MATCHED_PAGE_0"])

    app_state.open_pdf(str(sample_pdf), sha256)
    snapshot = app_state.translation_snapshot()

    app_state.replace_page(str(translated), 0, snapshot.document_id)

    with pymupdf.open(app_state._right_pdf_path) as doc:
        assert doc.page_count == 2
        assert "MATCHED_PAGE_0" in doc[0].get_text()
    assert 0 in app_state.translated_pages


def test_stale_batch_replace_rejected_and_current_document_untouched(app_state, sample_pdf, tmp_path):
    _, StaleDocumentError = _identity_api()
    pdf_b = _make_pdf(tmp_path / "b.pdf", label="B")
    translated_b_0 = _make_translated_pdf(tmp_path / "translated_b_0.pdf", ["VALID_B_0"])
    translated_a = _make_translated_pdf(tmp_path / "translated_a.pdf", ["STALE_A_0", "STALE_A_1"])

    app_state.open_pdf(str(sample_pdf), sha256)
    snapshot_a = app_state.translation_snapshot()

    app_state.open_pdf(str(pdf_b), sha256)
    snapshot_b = app_state.translation_snapshot()
    app_state.replace_page(str(translated_b_0), 0, snapshot_b.document_id)

    right_path_b = app_state._right_pdf_path
    right_hash_before = sha256(right_path_b)
    page_count_before = app_state.page_count
    translated_before = app_state.translated_pages
    assert translated_before == frozenset({0})

    with pytest.raises(StaleDocumentError):
        app_state.replace_pages(str(translated_a), [0, 1], snapshot_a.document_id)

    _assert_right_doc_unchanged(app_state, right_hash_before, page_count_before, translated_before)
    assert translated_before == frozenset({0})


def test_matching_batch_replace_still_applies(app_state, sample_pdf, tmp_path):
    DocumentSnapshot, _ = _identity_api()
    translated = _make_translated_pdf(
        tmp_path / "translated.pdf",
        ["MATCHED_BATCH_0", "MATCHED_BATCH_1"],
    )

    app_state.open_pdf(str(sample_pdf), sha256)
    snapshot = app_state.translation_snapshot()

    app_state.replace_pages(str(translated), [0, 1], snapshot.document_id)

    with pymupdf.open(app_state._right_pdf_path) as doc:
        assert doc.page_count == 2
        assert "MATCHED_BATCH_0" in doc[0].get_text()
        assert "MATCHED_BATCH_1" in doc[1].get_text()
    assert app_state.translated_pages == frozenset({0, 1})


def test_stale_extract_page_rejected_before_extract_func_runs(app_state, sample_pdf, tmp_path):
    _, StaleDocumentError = _identity_api()
    pdf_b = _make_pdf(tmp_path / "b.pdf", label="B")

    app_state.open_pdf(str(sample_pdf), sha256)
    snapshot_a = app_state.translation_snapshot()

    app_state.open_pdf(str(pdf_b), sha256)
    extract_calls: list[object] = []

    def extract_func(doc, page, tmpdir) -> Path:
        extract_calls.append((doc, page, tmpdir))
        out = Path(tmpdir) / "page.pdf"
        out.write_bytes(b"must-not-be-written")
        return out

    with pytest.raises(StaleDocumentError):
        app_state.extract_page(0, tmp_path, extract_func, snapshot_a.document_id)

    assert extract_calls == []


def test_matching_extract_page_still_extracts(app_state, sample_pdf, tmp_path):
    DocumentSnapshot, _ = _identity_api()
    app_state.open_pdf(str(sample_pdf), sha256)
    snapshot = app_state.translation_snapshot()

    def extract_func(doc, page, tmpdir) -> Path:
        out = Path(tmpdir) / "page.pdf"
        out.write_bytes(b"fake-page")
        return out

    result = app_state.extract_page(0, tmp_path, extract_func, snapshot.document_id)
    assert result == tmp_path / "page.pdf"
    assert result.read_bytes() == b"fake-page"


def test_stale_extract_pages_rejected_before_extract_func_runs(app_state, sample_pdf, tmp_path):
    _, StaleDocumentError = _identity_api()
    pdf_b = _make_pdf(tmp_path / "b.pdf", label="B")

    app_state.open_pdf(str(sample_pdf), sha256)
    snapshot_a = app_state.translation_snapshot()

    app_state.open_pdf(str(pdf_b), sha256)
    extract_calls: list[object] = []

    def extract_func(doc, page_indices, tmpdir) -> Path:
        extract_calls.append((doc, page_indices, tmpdir))
        out = Path(tmpdir) / "pages.pdf"
        out.write_bytes(b"must-not-be-written")
        return out

    with pytest.raises(StaleDocumentError):
        app_state.extract_pages([0, 1], tmp_path, extract_func, snapshot_a.document_id)

    assert extract_calls == []


def test_matching_extract_pages_still_extracts(app_state, sample_pdf, tmp_path):
    DocumentSnapshot, _ = _identity_api()
    app_state.open_pdf(str(sample_pdf), sha256)
    snapshot = app_state.translation_snapshot()

    def extract_func(doc, page_indices, tmpdir) -> Path:
        out = Path(tmpdir) / "pages.pdf"
        out.write_bytes(b"fake-pages")
        return out

    result = app_state.extract_pages([0, 1], tmp_path, extract_func, snapshot.document_id)
    assert result == tmp_path / "pages.pdf"
    assert result.read_bytes() == b"fake-pages"


def test_stale_glossary_merge_skips_callback_and_keeps_current_glossary(app_state, sample_pdf, tmp_path):
    _, StaleDocumentError = _identity_api()
    pdf_b = _make_pdf(tmp_path / "b.pdf", label="B")
    extracted_glossary = tmp_path / "a_auto_glossary.csv"
    _write_csv(extracted_glossary, [("beta", "贝塔")])

    app_state.open_pdf(str(sample_pdf), sha256)
    snapshot_a = app_state.translation_snapshot()

    app_state.open_pdf(str(pdf_b), sha256)
    b_glossary = app_state.glossary_cache_path / "cumulative_glossary.csv"
    _write_csv(b_glossary, [("alpha", "阿尔法")])
    glossary_bytes_before = b_glossary.read_bytes()

    merge_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def merge_cb(*args: object, **kwargs: object) -> None:
        merge_calls.append((args, kwargs))

    with pytest.raises(StaleDocumentError):
        app_state.merge_glossary(str(extracted_glossary), snapshot_a.document_id, merge_cb)

    assert merge_calls == []
    assert b_glossary.read_bytes() == glossary_bytes_before
    assert _read_csv(b_glossary) == [("alpha", "阿尔法")]


def test_matching_glossary_merge_invokes_callback(app_state, sample_pdf, tmp_path):
    DocumentSnapshot, _ = _identity_api()
    extracted_glossary = tmp_path / "auto_glossary.csv"
    _write_csv(extracted_glossary, [("beta", "贝塔")])

    app_state.open_pdf(str(sample_pdf), sha256)
    snapshot = app_state.translation_snapshot()
    glossary = app_state.glossary_cache_path / "cumulative_glossary.csv"
    _write_csv(glossary, [("alpha", "阿尔法")])

    merge_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def merge_cb(*args: object, **kwargs: object) -> None:
        merge_calls.append((args, kwargs))
        rows = _read_csv(glossary)
        rows.append(("beta", "贝塔"))
        _write_csv(glossary, rows)

    app_state.merge_glossary(str(extracted_glossary), snapshot.document_id, merge_cb)

    assert len(merge_calls) == 1
    assert ("alpha", "阿尔法") in _read_csv(glossary)
    assert ("beta", "贝塔") in _read_csv(glossary)
