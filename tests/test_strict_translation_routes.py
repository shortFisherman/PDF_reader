"""P0-04 路由级严格正文路径：fake 上游捕获最终 SettingsModel/Prompt 与 fail-closed。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Never
from unittest.mock import MagicMock

import pymupdf

from pdf_reader import config
from pdf_reader.strict_glossary import StrictGlossaryError
from pdf_reader.user_glossary import UserGlossaryStore


def _pdf_with_text(tmp_path: Path, text: str, name: str = "source.pdf") -> Path:
    pdf_path = tmp_path / name
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), text)
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def _finish_events(pdf_path: Path) -> list[dict]:
    result = MagicMock()
    result.mono_pdf_path = str(pdf_path)
    result.dual_pdf_path = None
    result.auto_extracted_glossary_path = None
    return [{"type": "finish", "stage": "generating_pdf", "translate_result": result, "token_usage": {}}]


def _open_pdf(client, pdf_path: Path) -> dict:
    resp = client.post("/api/open", json={"path": str(pdf_path)})
    assert resp.status_code == 200
    return json.loads(resp.data)


def _consume(response) -> str:
    body = "".join(chunk.decode("utf-8") for chunk in response.response)
    response.close()
    return body


def test_single_page_fake_upstream_captures_strict_settings_and_final_prompt(
    mock_config,
    test_client,
    tmp_path,
    monkeypatch,
):
    pdf_path = _pdf_with_text(tmp_path, "AD appears in adherence, adverse and shadow.")
    try:
        opened = _open_pdf(test_client, pdf_path)
        document_dir = config.CACHE_DIR / opened["hash"]
        UserGlossaryStore(document_dir).add("AD", "阿尔茨海默病")

        captured = {}

        def fake_run(settings, file, flow_label="", task_ctx=None):  # noqa: ANN202
            captured["settings"] = settings
            return iter(_finish_events(pdf_path))

        monkeypatch.setattr("pdf_reader.sse_stream.run_translation", fake_run)
        resp = test_client.post("/api/translate/0", json={"prompt": "page prompt"}, buffered=False)
        body = _consume(resp)
        assert resp.status_code == 200
        assert '"type": "finish"' in body

        settings = captured["settings"]
        effective_csv = document_dir / "effective_glossary.csv"
        assert settings.translation.glossaries == str(effective_csv)
        assert settings.translation.no_auto_extract_glossary is True
        assert settings.translation.save_auto_extracted_glossary is False
        assert settings.translation.custom_system_prompt.startswith("page prompt")
        assert '"AD"' in settings.translation.custom_system_prompt
        assert '"阿尔茨海默病"' in settings.translation.custom_system_prompt
    finally:
        test_client.application.config["app_state"].close()


def test_batch_fake_upstream_uses_same_strict_builder(
    mock_config,
    test_client,
    tmp_path,
    monkeypatch,
):
    pdf_path = _pdf_with_text(tmp_path, "TCS is on the page; AD is not.")
    try:
        opened = _open_pdf(test_client, pdf_path)
        document_dir = config.CACHE_DIR / opened["hash"]
        UserGlossaryStore(document_dir).add("TCS", "外用糖皮质激素")

        captured = {}

        def fake_run(settings, file, flow_label="", task_ctx=None):  # noqa: ANN202
            captured["settings"] = settings
            return iter(_finish_events(pdf_path))

        monkeypatch.setattr("pdf_reader.sse_stream.run_translation", fake_run)
        resp = test_client.post(
            "/api/translate-batch",
            json={"from": 1, "to": 1, "prompt": "batch prompt"},
            buffered=False,
        )
        body = _consume(resp)
        assert resp.status_code == 200
        assert '"type": "finish"' in body

        settings = captured["settings"]
        effective_csv = document_dir / "effective_glossary.csv"
        assert settings.translation.glossaries == str(effective_csv)
        assert settings.translation.no_auto_extract_glossary is True
        assert settings.translation.save_auto_extracted_glossary is False
        assert settings.pdf.pages == "1"
        assert settings.translation.custom_system_prompt.startswith("batch prompt")
        assert '"TCS"' in settings.translation.custom_system_prompt
        assert '"外用糖皮质激素"' in settings.translation.custom_system_prompt
    finally:
        test_client.application.config["app_state"].close()


def test_strict_prepare_failure_blocks_upstream_for_single_and_batch(
    mock_config,
    test_client,
    tmp_path,
    monkeypatch,
):
    pdf_path = _pdf_with_text(tmp_path, "plain text")
    try:
        _open_pdf(test_client, pdf_path)

        def boom(*args: object, **kwargs: object) -> Never:
            raise StrictGlossaryError("boom")

        monkeypatch.setattr("pdf_reader.routes.strict_glossary.prepare_strict_translation_context", boom)
        fake_run = MagicMock()
        monkeypatch.setattr("pdf_reader.sse_stream.run_translation", fake_run)
        coordinator = test_client.application.config["translation_coordinator"]

        resp = test_client.post("/api/translate/0", json={})
        assert resp.status_code == 500
        assert json.loads(resp.data)["code"] == "glossary_prepare_failed"
        assert coordinator.active_job is None

        resp = test_client.post("/api/translate-batch", json={"from": 1, "to": 1})
        assert resp.status_code == 500
        assert json.loads(resp.data)["code"] == "glossary_prepare_failed"
        assert coordinator.active_job is None

        fake_run.assert_not_called()
    finally:
        test_client.application.config["app_state"].close()


def test_strict_prepare_failure_logs_only_stable_fields(
    mock_config,
    test_client,
    tmp_path,
    monkeypatch,
    managed_caplog,
):
    import logging

    pdf_path = _pdf_with_text(tmp_path, "plain text")
    try:
        _open_pdf(test_client, pdf_path)

        def boom(*args: object, **kwargs: object) -> Never:
            raise StrictGlossaryError(
                "SECRET-C:\\Users\\secret\\term",
                stage="compile",
                cause_type="GlossaryCompileError",
            )

        monkeypatch.setattr("pdf_reader.routes.strict_glossary.prepare_strict_translation_context", boom)
        fake_run = MagicMock()
        monkeypatch.setattr("pdf_reader.sse_stream.run_translation", fake_run)

        with managed_caplog.at_level(logging.ERROR, logger="pdf_reader.routes"):
            resp = test_client.post("/api/translate/0", json={})

        assert resp.status_code == 500
        assert json.loads(resp.data)["code"] == "glossary_prepare_failed"
        fake_run.assert_not_called()
        assert "stage=compile" in managed_caplog.text
        assert "cause=GlossaryCompileError" in managed_caplog.text
        assert "SECRET" not in managed_caplog.text
        assert "C:\\Users\\secret" not in managed_caplog.text
        assert "Traceback" not in managed_caplog.text
    finally:
        test_client.application.config["app_state"].close()


def test_busy_request_returns_before_strict_preparation_and_open_cannot_switch_document(
    mock_config,
    test_client,
    tmp_path,
    monkeypatch,
):
    pdf_path = _pdf_with_text(tmp_path, "plain text")
    other_pdf = _pdf_with_text(tmp_path, "other document", name="other.pdf")
    active_job = None
    try:
        opened = _open_pdf(test_client, pdf_path)
        state = test_client.application.config["app_state"]
        coordinator = test_client.application.config["translation_coordinator"]
        snapshot = state.translation_snapshot()
        active_job = coordinator.start(snapshot.document_id, [0], pdf_hash=snapshot.pdf_hash)
        effective = snapshot.glossary_cache_path / "effective_glossary.csv"
        effective_before = effective.read_bytes() if effective.exists() else None

        prepare = MagicMock()
        compile_fn = MagicMock()
        migrate = MagicMock()
        monkeypatch.setattr("pdf_reader.routes.strict_glossary.prepare_strict_translation_context", prepare)
        monkeypatch.setattr("pdf_reader.strict_glossary.compile_effective_glossary", compile_fn)
        monkeypatch.setattr("pdf_reader.strict_glossary.migrate_legacy_cumulative", migrate)

        resp = test_client.post("/api/translate/0", json={})
        assert resp.status_code == 409
        assert resp.get_json()["code"] == "translation_busy"

        resp = test_client.post("/api/open", json={"path": str(other_pdf)})
        assert resp.status_code == 409
        assert resp.get_json()["code"] == "translation_busy"

        prepare.assert_not_called()
        compile_fn.assert_not_called()
        migrate.assert_not_called()
        if effective_before is None:
            assert not effective.exists()
        else:
            assert effective.read_bytes() == effective_before
        assert coordinator.active_job is active_job
        assert state.pdf_hash == opened["hash"]
    finally:
        if active_job is not None:
            test_client.application.config["translation_coordinator"].cancel(active_job.job_id)
        test_client.application.config["app_state"].close()
