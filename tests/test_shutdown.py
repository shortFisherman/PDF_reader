"""P3-05 优雅关闭与缓存生命周期：coordinator shutdown、AppState.close、main 装配。"""

import logging
import time
from pathlib import Path
from unittest.mock import MagicMock

import pymupdf
import pytest

from pdf_reader import app as app_module
from pdf_reader import cache_ops, config
from pdf_reader.state import AppState
from pdf_reader.translation_coordinator import (
    CoordinatorShutdownError,
    TranslationCoordinator,
)


def _valid_config(cache_dir: Path) -> dict:
    return {
        "model": {"provider": "deepseek", "model": "deepseek-chat", "api_key": "sk-test"},
        "pdf_reader": {"dpi": 200, "cache_dir": str(cache_dir)},
        "translation": {"lang_in": "en", "lang_out": "zh"},
    }


class _FakeStream:
    def __init__(self, release=None, *, alive_after_join: bool = False, join_sleep: float = 0.0) -> None:
        self._release = release
        self._alive_after_join = alive_after_join
        self._join_sleep = join_sleep
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True
        if self._release is not None:
            self._release()

    def join(self, timeout=None) -> None:
        if self._join_sleep:
            time.sleep(self._join_sleep)

    @property
    def is_alive(self) -> bool:
        return self._alive_after_join


class TestCoordinatorShutdown:
    def test_no_active_job(self):
        coordinator = TranslationCoordinator()
        report = coordinator.shutdown(timeout=0.01)

        assert report.outcome == "no_active_job"
        assert report.active_job_id is None
        assert coordinator.closed is True
        with pytest.raises(CoordinatorShutdownError):
            coordinator.start("doc", [0])

    def test_active_job_completes_within_timeout(self):
        coordinator = TranslationCoordinator()
        job = coordinator.start("doc", [0], pdf_hash="h")
        stream = _FakeStream(release=lambda: coordinator.finish(job.job_id))
        coordinator.register_stream(job.job_id, stream)

        report = coordinator.shutdown(timeout=2.0)

        assert report.outcome == "completed"
        assert report.active_job_id == job.job_id
        assert report.worker_joined is True
        assert coordinator.active_job is None
        assert stream.cancelled is True

    def test_non_cooperative_worker_times_out_without_kill(self):
        coordinator = TranslationCoordinator()
        job = coordinator.start("doc", [0], pdf_hash="h")
        stream = _FakeStream(alive_after_join=True, join_sleep=0.05)
        coordinator.register_stream(job.job_id, stream)

        report = coordinator.shutdown(timeout=0.01)

        assert report.outcome == "timeout"
        assert report.worker_joined is False
        assert coordinator.active_job is not None
        assert coordinator.active_job.job_id == job.job_id
        assert stream.cancelled is True

    def test_shutdown_idempotent(self):
        coordinator = TranslationCoordinator()
        first = coordinator.shutdown(timeout=0.01)
        second = coordinator.shutdown(timeout=0.01)

        assert second.outcome == first.outcome
        assert second.active_job_id == first.active_job_id

    def test_register_stream_after_shutdown_is_noop(self):
        coordinator = TranslationCoordinator()
        coordinator.shutdown(timeout=0)
        coordinator.register_stream("late", _FakeStream())
        assert coordinator._streams == {}


class TestAppStateClose:
    def test_close_releases_handles_and_is_idempotent(self, tmp_path):
        pdf_path = tmp_path / "sample.pdf"
        doc = pymupdf.open()
        doc.new_page(width=612, height=792)
        doc.save(str(pdf_path))
        doc.close()

        cache_dir = tmp_path / "cache"
        state = AppState(cache_dir)
        opened = state.open_pdf(str(pdf_path), lambda p: "hash")
        assert opened["page_count"] == 1
        assert state.is_closed() is False
        right_pdf = cache_dir / "hash" / "right.pdf"
        assert right_pdf.exists()

        state.close()
        state.close()
        assert state.is_closed() is True
        assert state.left_doc is None
        assert state.right_doc is None
        assert state.pdf_path is None
        assert state.page_count == 0
        assert state.translated_pages == frozenset()
        assert state.is_doc_open() is False

        # Windows 句柄回归：close 后文件可删除，不再被 PyMuPDF 占用。
        right_pdf.unlink()
        pdf_path.unlink()
        assert not right_pdf.exists()
        assert not pdf_path.exists()

        with pytest.raises(RuntimeError, match="AppState closed"):
            state.open_pdf(str(pdf_path), lambda p: "hash")
        with pytest.raises(ValueError):
            state.save_reading_progress(0)
        with pytest.raises(ValueError):
            state.render_page("left", 0, lambda *args: b"", 200)


class TestMainLifecycle:
    def test_main_recovers_orphans_and_closes_state(self, monkeypatch, tmp_path, caplog):
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        orphan = cache_dir / (cache_ops.TEMP_WORKSPACE_PREFIX + "crash")
        orphan.mkdir()
        cache_ops.write_temp_marker(orphan, job_id="crash", pid=999_999_999)

        state = AppState(cache_dir)
        coordinator = TranslationCoordinator()
        captured = {}

        def fake_create(settings) -> MagicMock:
            captured["settings"] = settings
            app = MagicMock()
            app.config = {"translation_coordinator": coordinator, "app_state": state}
            return app

        monkeypatch.setattr(app_module, "create_app", fake_create)
        monkeypatch.setattr(config, "CONFIG", _valid_config(cache_dir))
        monkeypatch.setattr(config, "MODEL", "deepseek-chat")
        monkeypatch.setattr(config, "MODEL_API_KEY", "sk-test-key")
        monkeypatch.delenv("PDF_READER_DEBUG", raising=False)
        with caplog.at_level(logging.INFO, logger="pdf_reader.app"):
            assert app_module.main([]) == 0

        assert not orphan.exists()
        assert captured["settings"].cache_dir == cache_dir
        assert state.is_closed() is True
        assert coordinator.closed is True
        assert any("startup temp workspace recovery" in r.message for r in caplog.records)
        assert any("app state closed" in r.message for r in caplog.records)

    def test_main_shutdown_waits_active_job(self, monkeypatch, tmp_path, caplog):
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        state = AppState(cache_dir)
        coordinator = TranslationCoordinator()
        job = coordinator.start("doc", [0], pdf_hash="h")
        stream = _FakeStream(release=lambda: coordinator.finish(job.job_id))
        coordinator.register_stream(job.job_id, stream)

        def fake_create(settings) -> MagicMock:
            app = MagicMock()
            app.config = {"translation_coordinator": coordinator, "app_state": state}
            return app

        monkeypatch.setattr(app_module, "create_app", fake_create)
        monkeypatch.setattr(config, "CONFIG", _valid_config(cache_dir))
        monkeypatch.setattr(config, "MODEL", "deepseek-chat")
        monkeypatch.setattr(config, "MODEL_API_KEY", "sk-test-key")
        monkeypatch.delenv("PDF_READER_DEBUG", raising=False)
        with caplog.at_level(logging.INFO, logger="pdf_reader.app"):
            assert app_module.main([]) == 0

        assert coordinator.active_job is None
        assert stream.cancelled is True
        assert state.is_closed() is True
        assert any("shutdown completed" in r.message for r in caplog.records)

    def test_main_shutdown_timeout_logs_kept_and_still_closes_state(self, monkeypatch, tmp_path, caplog):
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        state = AppState(cache_dir)
        coordinator = TranslationCoordinator()
        job = coordinator.start("doc", [0], pdf_hash="h")
        stream = _FakeStream(alive_after_join=True, join_sleep=0.02)
        coordinator.register_stream(job.job_id, stream)

        def fake_create(settings) -> MagicMock:
            app = MagicMock()
            app.config = {"translation_coordinator": coordinator, "app_state": state}
            return app

        monkeypatch.setattr(app_module, "create_app", fake_create)
        monkeypatch.setattr(app_module, "SHUTDOWN_JOIN_TIMEOUT", 0.05)
        monkeypatch.setattr(config, "CONFIG", _valid_config(cache_dir))
        monkeypatch.setattr(config, "MODEL", "deepseek-chat")
        monkeypatch.setattr(config, "MODEL_API_KEY", "sk-test-key")
        monkeypatch.delenv("PDF_READER_DEBUG", raising=False)
        with caplog.at_level(logging.WARNING, logger="pdf_reader.app"):
            assert app_module.main([]) == 0

        assert coordinator.active_job is not None
        assert any("shutdown timed out" in r.message for r in caplog.records)
        assert any("workers still running" in r.message for r in caplog.records)
        assert state.is_closed() is True

    def test_main_logs_fatal_run_exception_and_still_closes_state(self, monkeypatch, tmp_path, caplog):
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        state = AppState(cache_dir)
        coordinator = TranslationCoordinator()

        def fake_create(settings) -> MagicMock:
            app = MagicMock()
            app.run.side_effect = RuntimeError("run boom")
            app.config = {"translation_coordinator": coordinator, "app_state": state}
            return app

        monkeypatch.setattr(app_module, "create_app", fake_create)
        monkeypatch.setattr(config, "CONFIG", _valid_config(cache_dir))
        monkeypatch.setattr(config, "MODEL", "deepseek-chat")
        monkeypatch.setattr(config, "MODEL_API_KEY", "sk-test-key")
        monkeypatch.delenv("PDF_READER_DEBUG", raising=False)
        with caplog.at_level(logging.ERROR, logger="pdf_reader.app"):
            result = app_module.main([])

        assert result != 0
        assert "fatal error while running server" in caplog.text
        assert "run boom" in caplog.text
        assert any(r.exc_info is not None for r in caplog.records if "fatal error while running server" in r.message)
        assert coordinator.closed is True
        assert state.is_closed() is True

    def test_main_keyboard_interrupt_not_logged_as_error(self, monkeypatch, tmp_path, caplog):
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        state = AppState(cache_dir)
        coordinator = TranslationCoordinator()

        def fake_create(settings) -> MagicMock:
            app = MagicMock()
            app.run.side_effect = KeyboardInterrupt
            app.config = {"translation_coordinator": coordinator, "app_state": state}
            return app

        monkeypatch.setattr(app_module, "create_app", fake_create)
        monkeypatch.setattr(config, "CONFIG", _valid_config(cache_dir))
        monkeypatch.setattr(config, "MODEL", "deepseek-chat")
        monkeypatch.setattr(config, "MODEL_API_KEY", "sk-test-key")
        monkeypatch.delenv("PDF_READER_DEBUG", raising=False)
        with caplog.at_level(logging.INFO, logger="pdf_reader.app"):
            result = app_module.main([])

        assert result == 130
        assert any("KeyboardInterrupt" in r.message for r in caplog.records)
        assert not any(r.levelno >= logging.ERROR for r in caplog.records if r.name == "pdf_reader.app")
        assert coordinator.closed is True
        assert state.is_closed() is True

    def test_main_logs_startup_recovery_failure_and_still_closes_state(self, monkeypatch, tmp_path, caplog):
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        state = AppState(cache_dir)
        coordinator = TranslationCoordinator()

        def fake_create(settings) -> MagicMock:
            app = MagicMock()
            app.config = {"translation_coordinator": coordinator, "app_state": state}
            return app

        monkeypatch.setattr(app_module, "create_app", fake_create)
        monkeypatch.setattr(
            app_module.cache_ops,
            "recover_orphan_temp_workspaces",
            MagicMock(side_effect=RuntimeError("recovery boom")),
        )
        monkeypatch.setattr(config, "CONFIG", _valid_config(cache_dir))
        monkeypatch.setattr(config, "MODEL", "deepseek-chat")
        monkeypatch.setattr(config, "MODEL_API_KEY", "sk-test-key")
        monkeypatch.delenv("PDF_READER_DEBUG", raising=False)
        with caplog.at_level(logging.ERROR, logger="pdf_reader.app"):
            result = app_module.main([])

        assert result != 0
        assert "fatal startup error" in caplog.text
        assert "recovery boom" in caplog.text
        assert coordinator.closed is True
        assert state.is_closed() is True

    def test_coordinator_shutdown_tolerates_stream_exceptions(self):
        class _BadStream:
            def cancel(self) -> None:
                raise RuntimeError("cancel boom")

            def join(self, timeout=None) -> None:
                raise RuntimeError("join boom")

            @property
            def is_alive(self) -> bool:
                return True

        coordinator = TranslationCoordinator()
        job = coordinator.start("doc", [0], pdf_hash="h")
        coordinator.register_stream(job.job_id, _BadStream())

        report = coordinator.shutdown(timeout=0.01)

        assert report.outcome == "timeout"
        assert report.worker_joined is False
        assert coordinator.active_job is not None


def test_translate_rejected_during_shutdown(test_client, sample_pdf):
    opened = test_client.post("/api/open", json={"path": str(sample_pdf)})
    assert opened.status_code == 200
    coordinator = test_client.application.config["translation_coordinator"]
    coordinator.shutdown(timeout=0)

    resp = test_client.post("/api/translate/0", json={})

    assert resp.status_code == 409
    assert resp.get_json()["code"] == "translation_busy"


def test_batch_rejected_during_shutdown(test_client, sample_pdf):
    opened = test_client.post("/api/open", json={"path": str(sample_pdf)})
    assert opened.status_code == 200
    coordinator = test_client.application.config["translation_coordinator"]
    coordinator.shutdown(timeout=0)

    resp = test_client.post("/api/translate-batch", json={"from": 1, "to": 2})

    assert resp.status_code == 409
    assert resp.get_json()["code"] == "translation_busy"
