"""P1-01 portable first-run setup mode contracts."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from pdf_reader import app as app_module
from pdf_reader import config


def _setup_settings(tmp_path: Path, *, reason: str = "配置不完整") -> config.AppSettings:
    data: dict = {}
    upstream = config.build_upstream_runtime_config(data, strict=False)
    return config.AppSettings(
        debug=False,
        cache_dir=tmp_path / "cache",
        dpi=200,
        glossary_path=tmp_path / "glossary.csv",
        model_provider=upstream.model.provider,
        model=upstream.model.model,
        lang_in=upstream.translation.lang_in,
        lang_out=upstream.translation.lang_out,
        upstream=upstream,
        setup_mode=True,
        setup_reason=reason,
    )


def test_portable_missing_config_starts_setup_mode_on_loopback(monkeypatch, tmp_path):
    mock_app = MagicMock()
    captured: dict[str, config.AppSettings] = {}

    def fake_create(settings: config.AppSettings) -> MagicMock:
        captured["settings"] = settings
        return mock_app

    monkeypatch.setenv("PDF_READER_PORTABLE_SERVICE", "1")
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("PDF_READER_DEBUG", raising=False)
    monkeypatch.setattr(config, "CONFIG", {})
    monkeypatch.setattr(config, "_CONFIG_LOAD_ERROR", None)
    monkeypatch.setattr(app_module, "create_app", fake_create)
    monkeypatch.setattr(
        "pdf_reader.portable_runtime.readiness_file_from_environment",
        lambda layout: None,
    )

    assert app_module.main([]) == 0

    settings = captured["settings"]
    assert settings.setup_mode is True
    assert "model" in (settings.setup_reason or "")
    mock_app.run.assert_called_once_with(
        host="127.0.0.1",
        port=5000,
        debug=False,
        use_reloader=False,
    )


def test_setup_mode_only_exposes_root_static_config_status_and_health(monkeypatch, tmp_path):
    token = "health-token-" + "x" * 32
    monkeypatch.setenv("PDF_READER_PORTABLE_SERVICE", "1")
    monkeypatch.setenv("PDF_READER_HEALTH_TOKEN", token)
    with patch("pdf_reader.app.logging_config.setup_logging"):
        app = app_module.create_app(_setup_settings(tmp_path))
    app.config["TESTING"] = True
    app.config["config_path"] = tmp_path / "config.toml"
    try:
        with app.test_client() as client:
            root = client.get("/")
            assert root.status_code == 200
            assert b'data-setup-mode="true"' in root.data
            assert "首次配置" in root.data.decode("utf-8")

            assert client.get("/static/style.css").status_code == 200
            assert client.get("/api/config").status_code == 200
            status = client.get("/api/setup/status")
            assert status.status_code == 200
            assert status.get_json() == {
                "mode": "setup",
                "reason": "配置不完整",
                "restart_required_after_save": True,
            }
            health = client.get(
                "/api/health",
                headers={"X-PDF-Reader-Health-Token": token},
            )
            assert health.status_code == 200

            for method, path, kwargs in (
                (client.post, "/api/open", {"json": {"path": "C:/secret.pdf"}}),
                (client.post, "/api/translate/0", {}),
                (client.post, "/api/translate-batch", {"json": {"from": 1, "to": 1}}),
                (client.get, "/api/translated-pages", {}),
                (client.get, "/api/stages", {}),
                (client.get, "/api/glossary", {}),
                (client.post, "/api/client-errors", {"json": {"message": "x"}}),
            ):
                response = method(path, **kwargs)
                assert response.status_code == 503, path
                assert response.get_json()["code"] == "setup_required"
    finally:
        app.config["app_state"].close()


def test_setup_status_never_contains_api_key(monkeypatch, tmp_path):
    secret = "sk-super-secret-value"
    monkeypatch.setenv("PDF_READER_PORTABLE_SERVICE", "1")
    with patch("pdf_reader.app.logging_config.setup_logging"):
        app = app_module.create_app(_setup_settings(tmp_path, reason=f"missing key {secret}"))
    app.config["TESTING"] = True
    try:
        with app.test_client() as client:
            body = client.get("/api/setup/status").data.decode("utf-8")
        assert secret not in body
    finally:
        app.config["app_state"].close()
