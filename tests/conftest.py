import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pymupdf
import pytest

# P2-07：在任何应用模块导入前，把运行数据根重定向到 pytest 专用临时目录，
# 使日志、相对缓存与临时文件不会写入或增长仓库 logs/ 与 cache/。
_TEST_DATA_ROOT = tempfile.TemporaryDirectory(prefix="pdf-reader-test-data-")
os.environ["PDF_READER_DATA_ROOT"] = _TEST_DATA_ROOT.name

import config  # noqa: E402
import logging_config  # noqa: E402
import paths  # noqa: E402
from app import create_app  # noqa: E402
from state import AppState  # noqa: E402

# 镜像生产前置条件：文档打开后缓存根目录已存在（AppState.open_pdf 会创建
# cache/<hash>）；路由的翻译输出目录（tempfile.mkdtemp(dir=cache_dir)）依赖它。
config.CACHE_DIR.mkdir(parents=True, exist_ok=True)


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
    app.config["TESTING"] = True
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
    monkeypatch.setattr(config, "DPI", 200)
    monkeypatch.setattr(config, "CACHE_DIR", paths.get_data_root() / "cache")
    monkeypatch.setattr(config, "TRANSLATION_LANG_IN", "en")
    monkeypatch.setattr(config, "TRANSLATION_LANG_OUT", "zh")
    yield


@pytest.fixture(autouse=True)
def _reset_pdf_reader_logging() -> Iterator[None]:
    """每个测试后关闭并移除 pdf_reader 日志 handler，避免跨测试句柄泄漏与顺序依赖。"""
    yield
    logging_config.reset_logging()


def pytest_sessionfinish(session, exitstatus):
    logging_config.reset_logging()
    _TEST_DATA_ROOT.cleanup()
