import contextlib
import logging
import os
import re
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pymupdf
import pytest
from _pytest.logging import LogCaptureHandler

# P2-07：在任何应用模块导入前，把运行数据根重定向到 pytest 专用临时目录，
# 使日志、相对缓存与临时文件不会写入或增长仓库 logs/ 与 cache/。
_TEST_DATA_ROOT = tempfile.TemporaryDirectory(prefix="pdf-reader-test-data-")
os.environ["PDF_READER_DATA_ROOT"] = _TEST_DATA_ROOT.name

from pdf_reader import config, logging_config, paths  # noqa: E402
from pdf_reader.app import create_app  # noqa: E402
from pdf_reader.state import AppState  # noqa: E402

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
    app = create_app(config.build_app_settings())
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


class _ManagedLogCapture:
    """caplog 等价捕获器，但 handler 挂在受管 pdf_reader logger 上，不依赖 root propagation。

    setup_logging() 会摘掉托管 logger 上的全部 handler，因此每次使用前重新挂载；
    close()（fixture teardown）摘除 handler 并恢复 logger level / logging.disable 状态。
    """

    def __init__(self) -> None:
        self._logger = logging.getLogger("pdf_reader")
        self._handler = LogCaptureHandler()
        self._logger_levels: list[tuple[logging.Logger, int]] = []
        self._handler_levels: list[int] = []
        self._disable_levels: list[int] = []

    def _ensure_attached(self) -> None:
        if self._handler not in self._logger.handlers:
            self._logger.addHandler(self._handler)

    @property
    def records(self) -> list[logging.LogRecord]:
        self._ensure_attached()
        return self._handler.records

    @property
    def text(self) -> str:
        self._ensure_attached()
        return re.sub(r"\x1b\[[0-9;]*m", "", self._handler.stream.getvalue())

    def clear(self) -> None:
        self._handler.clear()

    def set_level(self, level: int | str, logger: str | None = None) -> None:
        """等价 caplog.set_level：设置目标 logger 与捕获 handler 级别，teardown 恢复。"""
        self._ensure_attached()
        # caplog 的 logger=None 指 root；此处收窄为受管 pdf_reader logger，避免碰 root。
        target = logging.getLogger(logger) if logger else self._logger
        self._logger_levels.append((target, target.level))
        target.setLevel(level)
        self._handler_levels.append(self._handler.level)
        self._handler.setLevel(level)
        self._disable_levels.append(target.manager.disable)
        if isinstance(level, str):
            level = logging.getLevelName(level)
        if not isinstance(level, int):
            logging.disable(logging.NOTSET)
        elif not target.isEnabledFor(level):
            logging.disable(max(level - 10, logging.NOTSET))

    @contextlib.contextmanager
    def at_level(self, level: int | str, logger: str | None = None) -> Iterator[None]:
        self.set_level(level, logger)
        try:
            yield
        finally:
            self._restore_last_level_change()

    def _restore_last_level_change(self) -> None:
        if self._logger_levels:
            target, old = self._logger_levels.pop()
            target.setLevel(old)
        if self._handler_levels:
            self._handler.setLevel(self._handler_levels.pop())
        if self._disable_levels:
            logging.disable(self._disable_levels.pop())

    def close(self) -> None:
        if self._handler in self._logger.handlers:
            self._logger.removeHandler(self._handler)
        self._handler.close()
        while self._logger_levels:
            target, old = self._logger_levels.pop()
            target.setLevel(old)
        while self._handler_levels:
            self._handler.setLevel(self._handler_levels.pop())
        while self._disable_levels:
            logging.disable(self._disable_levels.pop())


@pytest.fixture
def managed_caplog():
    """把日志捕获 handler 挂到受管 pdf_reader logger；teardown 清理并恢复级别。"""
    capture = _ManagedLogCapture()
    capture._ensure_attached()
    try:
        yield capture
    finally:
        capture.close()


@pytest.fixture(autouse=True)
def _reset_pdf_reader_logging() -> Iterator[None]:
    """每个测试后关闭并移除 pdf_reader 日志 handler，避免跨测试句柄泄漏与顺序依赖。"""
    yield
    logging_config.reset_logging()


def pytest_sessionfinish(session, exitstatus):
    logging_config.reset_logging()
    _TEST_DATA_ROOT.cleanup()
