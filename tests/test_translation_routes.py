from unittest.mock import MagicMock, patch

from flask import Flask

from file_hash import sha256
from routes import register_routes
from translation_coordinator import TranslationCoordinator


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
        patch("routes.build_settings", return_value=MagicMock()),
        patch("routes.sse_stream.generate", return_value=iter([""])) as generate_single,
        patch("routes.sse_stream.generate_batch") as generate_batch,
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


def test_busy_request_does_not_create_stream_or_temp_directory(app_state, sample_pdf):
    app = _make_app(app_state, sample_pdf)
    coordinator = app.config["translation_coordinator"]
    snapshot = app_state.translation_snapshot()
    active_job = coordinator.start(snapshot.document_id, [0])

    with (
        patch("routes.build_settings", return_value=MagicMock()),
        patch("routes.sse_stream.generate") as generate_single,
        patch("sse_stream.tempfile.mkdtemp") as make_temp_dir,
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
    make_temp_dir.assert_not_called()
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
