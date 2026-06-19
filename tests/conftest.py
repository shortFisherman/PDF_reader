import shutil
import tempfile
from pathlib import Path

import pymupdf
import pytest

import config
from app import create_app
from state import AppState


@pytest.fixture
def sample_pdf():
    """Create a temp 2-page PDF for testing"""
    tmpdir = Path(tempfile.mkdtemp())
    pdf_path = tmpdir / "test.pdf"
    doc = pymupdf.open()
    doc.new_page(width=612, height=792)
    doc.new_page(width=612, height=792)
    doc.save(str(pdf_path))
    doc.close()
    yield pdf_path
    shutil.rmtree(tmpdir, ignore_errors=True)

@pytest.fixture
def app_state(tmp_path):
    """Create AppState with temp cache dir"""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    state = AppState(cache_dir)
    yield state
    state._close_docs()

@pytest.fixture
def test_client():
    """Flask test client"""
    app = create_app()
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def mock_config(monkeypatch):
    monkeypatch.setattr(config, "MODEL_PROVIDER", "deepseek")
    monkeypatch.setattr(config, "MODEL_API_KEY", "sk-test-key")
    monkeypatch.setattr(config, "MODEL", "deepseek-v4-flash")
    monkeypatch.setattr(config, "MODEL_BASE_URL", None)
    monkeypatch.setattr(config, "MODEL_THINKING_MODE", None)
    monkeypatch.setattr(config, "MODEL_REASONING_EFFORT", None)
    monkeypatch.setattr(config, "MODEL_ENABLE_JSON_MODE", None)
    monkeypatch.setattr(config, "MODEL_TEMPERATURE", None)
    monkeypatch.setattr(config, "MODEL_TIMEOUT", None)
    yield
