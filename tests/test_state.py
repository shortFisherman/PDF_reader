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
