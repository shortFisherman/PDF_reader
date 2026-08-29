import logging
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from pdf_reader.file_hash import sha256
from pdf_reader.routes import register_routes
from pdf_reader.translation_coordinator import TranslationCoordinator

pytestmark = pytest.mark.integration


def _make_app(app_state, sample_pdf) -> Flask:
    app_state.open_pdf(str(sample_pdf), sha256)
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        app_state=app_state,
        translation_coordinator=TranslationCoordinator(),
    )
    register_routes(app)
    return app


def test_overlapping_single_and_batch_requests_accept_only_one(app_state, sample_pdf):
    app = _make_app(app_state, sample_pdf)
    coordinator = app.config["translation_coordinator"]

    with (
        patch("pdf_reader.routes.build_settings", return_value=MagicMock()),
        patch("pdf_reader.routes.sse_stream.generate", return_value=iter([""])) as generate_single,
        patch("pdf_reader.routes.sse_stream.generate_batch") as generate_batch,
    ):
        first_client = app.test_client()
        second_client = app.test_client()
        first = first_client.post("/api/translate/0", json={}, buffered=False)
        assert first.status_code == 200
        assert coordinator.is_busy is True

        rejected = second_client.post("/api/translate-batch", json={"from": 1, "to": 2})
        assert rejected.status_code == 409
        assert rejected.get_json()["code"] == "translation_busy"
        assert "已有翻译任务" in rejected.get_json()["error"]
        assert generate_single.call_count == 1
        generate_batch.assert_not_called()

        first.close()

    assert coordinator.is_busy is False


def test_busy_request_does_not_create_stream_or_temp_workspace(app_state, sample_pdf):
    app = _make_app(app_state, sample_pdf)
    coordinator = app.config["translation_coordinator"]
    snapshot = app_state.translation_snapshot()
    active_job = coordinator.start(snapshot.document_id, [0])

    with (
        patch("pdf_reader.routes.build_settings", return_value=MagicMock()),
        patch("pdf_reader.routes.sse_stream.generate") as generate_single,
        patch("pdf_reader.cache_ops.create_temp_workspace") as create_workspace,
    ):
        with app.test_client() as client:
            response = client.post("/api/translate/0", json={})

    assert response.status_code == 409
    assert response.get_json() == {
        "active_job_id": active_job.job_id,
        "code": "translation_busy",
        "error": "已有翻译任务正在进行，请稍后再试",
    }
    generate_single.assert_not_called()
    create_workspace.assert_not_called()
    assert coordinator.active_job == active_job
    coordinator.fail(active_job.job_id)


def test_open_is_rejected_while_translation_is_active(app_state, sample_pdf):
    app = _make_app(app_state, sample_pdf)
    coordinator = app.config["translation_coordinator"]
    snapshot_before = app_state.translation_snapshot()
    active_job = coordinator.start(snapshot_before.document_id, [0])

    with app.test_client() as client:
        response = client.post("/api/open", json={"path": str(sample_pdf)})

    assert response.status_code == 409
    assert response.get_json()["code"] == "translation_busy"
    assert app_state.translation_snapshot() == snapshot_before
    coordinator.fail(active_job.job_id)


def _assert_coordinator_start_logs(snapshot, caplog, page_label) -> None:
    messages = [r.message for r in caplog.records if "translation job" in r.message]
    created = [m for m in messages if "status=created" in m]
    started = [m for m in messages if "translation job started" in m]
    assert len(created) == 1, f"expected one created log, got: {created}"
    assert len(started) == 1, f"expected one started log, got: {started}"
    for msg in created + started:
        assert "job=" in msg
        assert f"doc={snapshot.document_id[:8]}" in msg
        assert f"hash={snapshot.pdf_hash[:12]}" in msg
        assert page_label in msg
        assert snapshot.document_id not in msg
        assert snapshot.pdf_hash not in msg
    assert "status=created" in created[0]
    assert "status=started" in started[0]


def test_single_route_coordinator_start_logs_truncated_context(app_state, sample_pdf, caplog):
    """真实单页路由经真实 coordinator.start 的 created/started 日志必须带 hash 等完整截断上下文。"""
    app = _make_app(app_state, sample_pdf)
    snapshot = app_state.translation_snapshot()

    with patch("pdf_reader.routes.build_settings", return_value=MagicMock()):
        with patch("pdf_reader.routes.sse_stream.generate", return_value=iter([""])):
            with app.test_client() as client:
                with caplog.at_level(logging.INFO, logger="pdf_reader.translate"):
                    resp = client.post("/api/translate/0", json={}, buffered=False)
                    resp.close()

    assert resp.status_code == 200
    _assert_coordinator_start_logs(snapshot, caplog, "page=1")


def test_batch_route_coordinator_start_logs_truncated_context(app_state, sample_pdf, caplog):
    """真实批量路由经真实 coordinator.start 的 created/started 日志必须带 hash 与 pages 范围。"""
    app = _make_app(app_state, sample_pdf)
    snapshot = app_state.translation_snapshot()

    with patch("pdf_reader.routes.build_settings", return_value=MagicMock()):
        with patch("pdf_reader.routes.sse_stream.generate_batch", return_value=iter([""])):
            with app.test_client() as client:
                with caplog.at_level(logging.INFO, logger="pdf_reader.translate"):
                    resp = client.post("/api/translate-batch", json={"from": 1, "to": 2}, buffered=False)
                    resp.close()

    assert resp.status_code == 200
    _assert_coordinator_start_logs(snapshot, caplog, "pages=1-2")
