import csv
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from flask import Flask

from pdf_reader.strict_glossary import StrictTranslationContext


def test_index_route(test_client):
    resp = test_client.get("/")
    assert resp.status_code == 200


def test_open_missing_file(test_client):
    resp = test_client.post("/api/open", json={"path": "/nonexistent/file.pdf"})
    assert resp.status_code == 400
    data = json.loads(resp.data)
    assert "error" in data


def test_get_page_no_doc(test_client):
    resp = test_client.get("/api/page/left/0")
    assert resp.status_code in (400, 404)
    data = json.loads(resp.data)
    assert "error" in data


def test_page_count_no_doc(test_client):
    resp = test_client.get("/api/page-count/left")
    assert resp.status_code == 400
    data = json.loads(resp.data)
    assert "error" in data


def test_translate_no_doc(test_client):
    resp = test_client.post("/api/translate/0")
    assert resp.status_code == 400
    data = json.loads(resp.data)
    assert "error" in data


def test_translated_pages_no_doc(test_client):
    resp = test_client.get("/api/translated-pages")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data == {"pages": []}


def test_debug_trace_logger_exists():
    import logging

    from pdf_reader.debug_trace import trace_logger

    assert isinstance(trace_logger, logging.Logger)
    assert trace_logger.name == "pdf_reader.debug_trace"
    assert trace_logger.level == logging.NOTSET


def test_translate_page_integrates_cumulative_glossary(app_state, sample_pdf, monkeypatch):
    """严格路径把 fresh effective glossary 传给 settings；翻译后仍执行旧合并回调。"""
    from pdf_reader.file_hash import sha256 as sha256_func

    # 1. Open PDF, create cumulative glossary
    app_state.open_pdf(str(sample_pdf), sha256_func)
    glossary_cache = app_state.glossary_cache_path
    assert glossary_cache is not None
    effective_file = glossary_cache / "effective_glossary.csv"
    with open(effective_file, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["source", "target"])
        w.writerow(["alpha", "\u963f\u5c14\u6cd5"])

    # 2. Create auto-extracted glossary that translation will produce
    auto_file = glossary_cache / "auto_extracted.csv"
    with open(auto_file, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["source", "target"])
        w.writerow(["beta", "\u8d1d\u5854"])

    # 3. Mock TranslateResult
    mock_result = MagicMock()
    mock_result.mono_pdf_path = Path(str(sample_pdf))
    mock_result.dual_pdf_path = None
    mock_result.auto_extracted_glossary_path = auto_file

    # 4. Record-keeper mocks
    settings_call_kwargs = []
    merge_calls = []

    def fake_prepare(snapshot):  # noqa: ANN202
        return StrictTranslationContext(
            document_dir=snapshot.glossary_cache_path,
            document_id=snapshot.document_id,
            pdf_hash=snapshot.pdf_hash,
            effective_glossary_path=effective_file,
            effective_rows=(("alpha", "\u963f\u5c14\u6cd5"),),
        )

    def fake_build_settings(upstream, user_prompt, pages, context):  # noqa: ANN202
        settings_call_kwargs.append({"glossary_paths": [str(context.effective_glossary_path)]})
        return MagicMock()

    async def fake_translate_stream(settings, file):  # noqa: ANN202
        yield {
            "type": "progress_start",
            "stage": "layout_analysis",
            "overall_progress": 0,
            "stage_current": 0,
            "stage_total": 0,
        }
        yield {
            "type": "finish",
            "stage": "generating_pdf",
            "translate_result": mock_result,
        }

    def fake_merge(cumulative, auto):  # noqa: ANN202
        merge_calls.append((str(cumulative), str(auto)))

    monkeypatch.setattr("pdf_reader.routes.strict_glossary.prepare_strict_translation_context", fake_prepare)
    monkeypatch.setattr("pdf_reader.routes.strict_glossary.build_strict_settings", fake_build_settings)
    monkeypatch.setattr("pdf_reader.translation_orchestrator.do_translate_async_stream", fake_translate_stream)
    monkeypatch.setattr("pdf_reader.glossary_service.merge_glossary_csvs", fake_merge)

    # 5. Create Flask app with our state
    app = Flask(__name__)
    app.config["app_state"] = app_state
    app.config["TESTING"] = True
    from pdf_reader.routes import register_routes

    register_routes(app)

    # 6. Request translation
    with app.test_client() as client:
        resp = client.post("/api/translate/0", json={})
        assert resp.status_code == 200
        body = resp.data.decode("utf-8")
        assert '"type": "finish"' in body

    # 7. Verify strict builder received only the effective glossary
    assert len(settings_call_kwargs) == 1
    assert settings_call_kwargs[0]["glossary_paths"] == [str(effective_file)]

    # 8. Verify merge_glossary_csvs called with correct paths
    assert len(merge_calls) == 1
    assert merge_calls[0] == (str(glossary_cache / "cumulative_glossary.csv"), str(auto_file))


def test_translate_page_out_of_range(app_state, sample_pdf):
    from pdf_reader.file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)

    from flask import Flask

    from pdf_reader.routes import register_routes

    app = Flask(__name__)
    app.config["app_state"] = app_state
    app.config["TESTING"] = True
    register_routes(app)

    with app.test_client() as client:
        resp = client.post(f"/api/translate/{app_state.page_count}", json={})
        assert resp.status_code == 400
        data = json.loads(resp.data)
        assert data["error"] == "page out of range"

        resp = client.post("/api/translate/999", json={})
        assert resp.status_code == 400
        data = json.loads(resp.data)
        assert data["error"] == "page out of range"


def test_get_stages(test_client):
    resp = test_client.get("/api/stages")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert len(data) == 5
    assert data["layout_analysis"] == "\u6b63\u5728\u5206\u6790\u7248\u9762\u2026"
    assert data["translating"] == "\u6b63\u5728\u7ffb\u8bd1\u2026"
    assert data["generating_pdf"] == "\u6b63\u5728\u751f\u6210\u8bd1\u6587\u2026"
    assert data["generating_pdf_bilingual"] == "\u6b63\u5728\u751f\u6210\u8bd1\u6587\u2026"
    assert data["finish"] == "\u7ffb\u8bd1\u5b8c\u6210"
    assert data == {
        "layout_analysis": "\u6b63\u5728\u5206\u6790\u7248\u9762\u2026",
        "translating": "\u6b63\u5728\u7ffb\u8bd1\u2026",
        "generating_pdf": "\u6b63\u5728\u751f\u6210\u8bd1\u6587\u2026",
        "generating_pdf_bilingual": "\u6b63\u5728\u751f\u6210\u8bd1\u6587\u2026",
        "finish": "\u7ffb\u8bd1\u5b8c\u6210",
    }


def test_translate_batch_validation_errors(app_state, sample_pdf):
    from flask import Flask

    from pdf_reader.file_hash import sha256 as sha256_func
    from pdf_reader.routes import register_routes

    app_state.open_pdf(str(sample_pdf), sha256_func)
    app = Flask(__name__)
    app.config["app_state"] = app_state
    app.config["TESTING"] = True
    register_routes(app)

    with app.test_client() as client:
        resp = client.post("/api/translate-batch", json={"from": 5, "to": 2})
        assert resp.status_code == 400
        assert "error" in json.loads(resp.data)

        resp = client.post("/api/translate-batch", json={"from": 0, "to": 1})
        assert resp.status_code == 400
        resp = client.post("/api/translate-batch", json={"from": 1, "to": 99})
        assert resp.status_code == 400

        resp = client.post("/api/translate-batch", json={"from": None, "to": 1})
        assert resp.status_code == 400


def test_translate_batch_no_doc(test_client):
    resp = test_client.post("/api/translate-batch", json={"from": 1, "to": 1})
    assert resp.status_code == 400
    assert "error" in json.loads(resp.data)


def test_open_response_includes_saved_page_key(app_state, sample_pdf):
    from pdf_reader.file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    from flask import Flask

    from pdf_reader.routes import register_routes

    app = Flask(__name__)
    app.config["app_state"] = app_state
    app.config["TESTING"] = True
    register_routes(app)

    with app.test_client() as client:
        resp = client.post("/api/open", json={"path": str(sample_pdf)})
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "saved_page" in data
    app_state._close_docs()


def test_save_reading_progress_route_success(app_state, sample_pdf, tmp_path):
    from pdf_reader.file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    from flask import Flask

    from pdf_reader.routes import register_routes

    app = Flask(__name__)
    app.config["app_state"] = app_state
    app.config["TESTING"] = True
    register_routes(app)

    with app.test_client() as client:
        resp = client.post("/api/reading-progress", json={"page": 1})
        assert resp.status_code == 200
        assert json.loads(resp.data) == {"ok": True}

    progress_file = app_state._reading_progress_path()
    assert progress_file is not None and progress_file.exists()
    assert json.loads(progress_file.read_text(encoding="utf-8")) == {"page": 1}
    app_state._close_docs()


def test_save_reading_progress_route_no_doc():
    from flask import Flask

    from pdf_reader.routes import register_routes
    from pdf_reader.state import AppState

    app = Flask(__name__)
    app.config["app_state"] = AppState(Path("/tmp/cache_no_doc_routes"))
    app.config["TESTING"] = True
    register_routes(app)

    with app.test_client() as client:
        resp = client.post("/api/reading-progress", json={"page": 0})
        assert resp.status_code == 400
        assert json.loads(resp.data)["error"] == "no document opened"


def test_save_reading_progress_route_out_of_range(app_state, sample_pdf):
    from pdf_reader.file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    page_count = app_state.page_count
    from flask import Flask

    from pdf_reader.routes import register_routes

    app = Flask(__name__)
    app.config["app_state"] = app_state
    app.config["TESTING"] = True
    register_routes(app)

    with app.test_client() as client:
        resp = client.post("/api/reading-progress", json={"page": page_count})
        assert resp.status_code == 400
        assert json.loads(resp.data)["error"] == "page out of range"

        assert not app_state._reading_progress_path().exists()
    app_state._close_docs()


def test_save_reading_progress_route_non_integer(app_state, sample_pdf):
    from pdf_reader.file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    from flask import Flask

    from pdf_reader.routes import register_routes

    app = Flask(__name__)
    app.config["app_state"] = app_state
    app.config["TESTING"] = True
    register_routes(app)

    with app.test_client() as client:
        for bad in [{"page": "x"}, {"page": True}, {}, {"page": 1.5}]:
            resp = client.post("/api/reading-progress", json=bad)
            assert resp.status_code == 400
            assert "error" in json.loads(resp.data)
        assert not app_state._reading_progress_path().exists()
    app_state._close_docs()


def test_translate_batch_emits_batch_info_and_finish(app_state, sample_pdf, monkeypatch):
    from pathlib import Path
    from unittest.mock import MagicMock

    from flask import Flask

    from pdf_reader.file_hash import sha256 as sha256_func
    from pdf_reader.routes import register_routes

    app_state.open_pdf(str(sample_pdf), sha256_func)
    page_count = app_state.page_count

    def fake_prepare(snapshot):  # noqa: ANN202
        return StrictTranslationContext(
            document_dir=snapshot.glossary_cache_path,
            document_id=snapshot.document_id,
            pdf_hash=snapshot.pdf_hash,
            effective_glossary_path=None,
            effective_rows=(),
        )

    def fake_build_settings(upstream, user_prompt, pages, context):  # noqa: ANN202
        return MagicMock()

    async def fake_translate_stream(settings, file):  # noqa: ANN202
        yield {
            "type": "progress_start",
            "stage": "layout_analysis",
            "overall_progress": 0,
            "stage_current": 0,
            "stage_total": 0,
        }
        mock_result = MagicMock()
        mock_result.mono_pdf_path = Path(str(sample_pdf))
        mock_result.dual_pdf_path = None
        mock_result.auto_extracted_glossary_path = None
        yield {"type": "finish", "stage": "generating_pdf", "translate_result": mock_result, "token_usage": {}}

    monkeypatch.setattr("pdf_reader.routes.strict_glossary.prepare_strict_translation_context", fake_prepare)
    monkeypatch.setattr("pdf_reader.routes.strict_glossary.build_strict_settings", fake_build_settings)
    monkeypatch.setattr("pdf_reader.translation_orchestrator.do_translate_async_stream", fake_translate_stream)
    monkeypatch.setattr("pdf_reader.glossary_service.merge_glossary_csvs", lambda c, a: None)

    app = Flask(__name__)
    app.config["app_state"] = app_state
    app.config["TESTING"] = True
    register_routes(app)

    with app.test_client() as client:
        resp = client.post("/api/translate-batch", json={"from": 1, "to": page_count})
        assert resp.status_code == 200
        body = resp.data.decode("utf-8")
        assert '"type": "batch_info"' in body
        assert '"from": 1' in body and f'"to": {page_count}' in body
        assert '"type": "finish"' in body


def _assert_error_shape(resp, expected_code) -> dict:
    data = json.loads(resp.data)
    assert data["code"] == expected_code, f"unexpected code in {data}"
    assert isinstance(data["error"], str) and data["error"]
    return data


def test_api_error_contract_400_and_404_branches(test_client):
    cases = [
        ("open missing", test_client.post("/api/open", json={"path": "/nonexistent/file.pdf"}), "invalid_file_path"),
        ("reading invalid", test_client.post("/api/reading-progress", json={"page": "x"}), "invalid_page"),
        ("page count no doc", test_client.get("/api/page-count/left"), "no_document_opened"),
        ("translate no doc", test_client.post("/api/translate/0"), "no_document_opened"),
        ("batch no doc", test_client.post("/api/translate-batch", json={"from": 1, "to": 1}), "no_document_opened"),
        ("missing route", test_client.get("/api/does-not-exist"), "not_found"),
    ]
    for label, resp, expected_code in cases:
        _assert_error_shape(resp, expected_code)


def test_api_error_contract_with_open_document(app_state, sample_pdf):
    from pdf_reader.file_hash import sha256 as sha256_func
    from pdf_reader.routes import register_routes

    app_state.open_pdf(str(sample_pdf), sha256_func)
    app = Flask(__name__)
    app.config.update(app_state=app_state, TESTING=True)
    register_routes(app)

    with app.test_client() as client:
        cases = [
            ("invalid side", client.get("/api/page/bad/0"), "invalid_side"),
            ("page out of range", client.get(f"/api/page/left/{app_state.page_count}"), "page_out_of_range"),
            (
                "reading out of range",
                client.post("/api/reading-progress", json={"page": app_state.page_count}),
                "page_out_of_range",
            ),
            (
                "translate out of range",
                client.post(f"/api/translate/{app_state.page_count}", json={}),
                "page_out_of_range",
            ),
            (
                "batch invalid numbers",
                client.post("/api/translate-batch", json={"from": None, "to": 1}),
                "invalid_page_numbers",
            ),
            ("batch out of range", client.post("/api/translate-batch", json={"from": 0, "to": 1}), "page_out_of_range"),
            (
                "batch invalid range",
                client.post("/api/translate-batch", json={"from": 2, "to": 1}),
                "invalid_page_range",
            ),
        ]
        for label, resp, expected_code in cases:
            _assert_error_shape(resp, expected_code)


def test_method_not_allowed_returns_json_error(test_client):
    resp = test_client.post("/api/page/left/0")
    assert resp.status_code == 405
    data = json.loads(resp.data)
    assert data["code"] == "http_405"
    assert data["error"]


def test_internal_error_sanitizes_response_and_keeps_log(managed_caplog, monkeypatch, tmp_path):
    import logging

    from pdf_reader.routes import register_routes
    from pdf_reader.state import AppState
    from pdf_reader.translation_coordinator import TranslationCoordinator

    state = AppState(tmp_path / "cache")
    app = Flask(__name__)
    app.config.update(
        app_state=state,
        TESTING=False,
        translation_coordinator=TranslationCoordinator(),
    )
    register_routes(app)

    sentinel = "sk-secret-123 C:\\Users\\secret\\file.txt <img src=x onerror=alert(1)>"

    def boom(page):  # noqa: ANN202
        raise RuntimeError(sentinel)

    monkeypatch.setattr(state, "save_reading_progress", boom)
    with managed_caplog.at_level(logging.ERROR, logger="pdf_reader.routes"):
        with app.test_client() as client:
            resp = client.post("/api/reading-progress", json={"page": 0})

    assert resp.status_code == 500
    data = json.loads(resp.data)
    assert data == {"code": "internal_error", "error": "服务器内部错误"}
    body = resp.data.decode("utf-8")
    for secret in ("sk-secret-123", "Users\\secret", "onerror"):
        assert secret not in body
    assert "sk-secret-123" in managed_caplog.text


def test_translate_context_uses_injected_settings_not_module_globals(app_state, sample_pdf, monkeypatch):
    """翻译上下文消费注入的 provider/model/lang/debug/cache，与 config 模块全局冲突时以注入值为准。"""
    from pdf_reader import config
    from pdf_reader.file_hash import sha256
    from pdf_reader.routes import register_routes
    from pdf_reader.translation_coordinator import TranslationCoordinator

    app_state.open_pdf(str(sample_pdf), sha256)
    settings = config.AppSettings(
        debug=False,
        cache_dir=app_state._cache_dir,
        dpi=200,
        glossary_path=config.GLOSSARY_PATH,
        model_provider="deepseek",
        model="deepseek-chat",
        lang_in="en",
        lang_out="zh",
        upstream=config.build_upstream_runtime_config(
            {
                "model": {"provider": "deepseek", "model": "deepseek-chat", "api_key": "sk-test"},
                "pdf_reader": {},
                "translation": {"lang_in": "en", "lang_out": "zh"},
            }
        ),
    )
    monkeypatch.setattr(config, "MODEL_PROVIDER", "zhipu")
    monkeypatch.setattr(config, "MODEL", "zhipu-ai")
    monkeypatch.setattr(config, "TRANSLATION_LANG_IN", "ja")
    monkeypatch.setattr(config, "TRANSLATION_LANG_OUT", "ko")
    monkeypatch.setattr(config, "DEBUG", True)

    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        app_settings=settings,
        app_state=app_state,
        translation_coordinator=TranslationCoordinator(),
    )
    register_routes(app)
    captured = {}

    with (
        patch("pdf_reader.routes.strict_glossary.prepare_strict_translation_context") as prepare,
        patch("pdf_reader.routes.strict_glossary.build_strict_settings", return_value=MagicMock()),
        patch("pdf_reader.routes.sse_stream.generate") as generate,
    ):
        prepare.return_value = StrictTranslationContext(
            document_dir=app_state.glossary_cache_path,
            document_id="doc-id",
            pdf_hash=app_state.pdf_hash or "",
            effective_glossary_path=None,
            effective_rows=(),
        )

        def capture(ctx) -> object:
            captured["ctx"] = ctx
            return iter([""])

        generate.side_effect = capture
        with app.test_client() as client:
            resp = client.post("/api/translate/0", json={})
        assert resp.status_code == 200

    ctx = captured["ctx"]
    assert ctx.cache_dir == settings.cache_dir
    assert ctx.provider == "deepseek"
    assert ctx.model == "deepseek-chat"
    assert ctx.lang_in == "en"
    assert ctx.lang_out == "zh"
    assert ctx.debug is False


def test_register_routes_builds_settings_only_when_key_missing(monkeypatch):
    """兼容 fallback 惰性执行：key 已注入时不调用 build_app_settings，缺失时才调用一次。"""
    from pdf_reader import config
    from pdf_reader.routes import register_routes

    fallback = config.AppSettings(
        debug=False,
        cache_dir=Path("cache"),
        dpi=200,
        glossary_path=Path("docs/glossary.csv"),
        model_provider="openai_compatible",
        model="",
        lang_in="en",
        lang_out="zh",
        upstream=config.build_upstream_runtime_config(
            {
                "model": {
                    "provider": "openai_compatible",
                    "model": "m",
                    "api_key": "sk-test",
                    "base_url": "https://example.com/v1",
                },
                "pdf_reader": {},
                "translation": {"lang_in": "en", "lang_out": "zh"},
            }
        ),
    )
    calls: list[tuple[object, ...]] = []

    def spy(
        config_data: dict | None = None,
        *,
        cli_debug: bool | None = None,
        run_cfg: config.ServerConfig | None = None,
    ) -> config.AppSettings:
        calls.append((config_data, cli_debug, run_cfg))
        return fallback

    monkeypatch.setattr(config, "build_app_settings", spy)

    injected_app = Flask(__name__)
    injected_app.config["app_settings"] = fallback
    register_routes(injected_app)
    assert calls == []

    missing_app = Flask(__name__)
    register_routes(missing_app)
    assert missing_app.config["app_settings"] is fallback
    assert len(calls) == 1


def test_client_errors_valid_report_logs_cleaned_fields(test_client, managed_caplog):
    import logging

    payload = {
        "kind": "window_error",
        "message": "boom\nsecond line\x00",
        "source": "http://127.0.0.1/app.js",
        "line": 12,
        "column": 3,
        "stack": "Error: boom\n    at app.js:12:3",
    }
    with managed_caplog.at_level(logging.WARNING, logger="pdf_reader.client"):
        resp = test_client.post("/api/client-errors", json=payload)

    assert resp.status_code == 202
    assert resp.get_json() == {"ok": True}
    records = [r for r in managed_caplog.records if r.name == "pdf_reader.client"]
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    message = records[0].message
    assert "kind='window_error'" in message
    assert "message='boom second line'" in message
    assert "source='http://127.0.0.1/app.js'" in message
    assert "line=12 column=3" in message
    assert "stack='Error: boom at app.js:12:3'" in message
    assert "\n" not in message
    assert "\x00" not in message


def test_client_errors_invalid_payloads(test_client, managed_caplog):
    import logging

    cases = [
        ["not", "an", "object"],
        "plain text",
        42,
        {"message": "x", "user_prompt": "secret business data"},
        {"message": 42},
        {"line": "12"},
        {},
        {"kind": "window_error"},
        {"message": ""},
    ]
    with managed_caplog.at_level(logging.WARNING, logger="pdf_reader.client"):
        for payload in cases:
            resp = test_client.post("/api/client-errors", json=payload)
            assert resp.status_code == 400, f"unexpected status for {payload!r}"
            assert resp.get_json()["code"] == "invalid_payload", f"unexpected code for {payload!r}"

        resp = test_client.post("/api/client-errors", data="null", content_type="application/json")
        assert resp.status_code == 400
        assert resp.get_json()["code"] == "invalid_payload"

        resp = test_client.post("/api/client-errors", data="{broken", content_type="application/json")
        assert resp.status_code == 400
        assert resp.get_json()["code"] == "invalid_payload"

    assert not [r for r in managed_caplog.records if r.name == "pdf_reader.client"]


def test_client_errors_non_loopback_rejected(test_client, managed_caplog):
    import logging

    with managed_caplog.at_level(logging.WARNING):
        resp = test_client.post(
            "/api/client-errors",
            json={"message": "must not be accepted"},
            environ_base={"REMOTE_ADDR": "203.0.113.9"},
        )

    assert resp.status_code == 403
    assert resp.get_json()["code"] == "client_errors_local_only"
    assert not [r for r in managed_caplog.records if r.name == "pdf_reader.client"]


def test_client_errors_accepts_loopback_variants(test_client, managed_caplog):
    import logging

    with managed_caplog.at_level(logging.WARNING, logger="pdf_reader.client"):
        for addr in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
            resp = test_client.post(
                "/api/client-errors",
                json={"kind": "window_error", "message": f"boom-{addr}"},
                environ_base={"REMOTE_ADDR": addr},
            )
            assert resp.status_code == 202, addr
            assert resp.get_json() == {"ok": True}

    assert len([r for r in managed_caplog.records if r.name == "pdf_reader.client"]) == 3


def test_client_errors_oversized_body_rejected(test_client, managed_caplog):
    import logging

    with managed_caplog.at_level(logging.WARNING, logger="pdf_reader.client"):
        resp = test_client.post("/api/client-errors", json={"message": "x" * 9000})

    assert resp.status_code == 413
    assert resp.get_json()["code"] == "payload_too_large"
    assert not [r for r in managed_caplog.records if r.name == "pdf_reader.client"]


def test_client_errors_truncates_long_string_fields(test_client, managed_caplog):
    import logging

    with managed_caplog.at_level(logging.WARNING, logger="pdf_reader.client"):
        resp = test_client.post(
            "/api/client-errors",
            json={"kind": "window_error", "message": "m" * 5000},
        )
        assert resp.status_code == 202
        resp = test_client.post(
            "/api/client-errors",
            json={"kind": "window_error", "stack": "t" * 5000},
        )
        assert resp.status_code == 202

    records = [r for r in managed_caplog.records if r.name == "pdf_reader.client"]
    assert len(records) == 2
    assert ("m" * 1024) in records[0].message
    assert ("m" * 1025) not in records[0].message
    assert ("t" * 4096) in records[1].message
    assert ("t" * 4097) not in records[1].message


def test_client_errors_redacts_secrets_from_final_log_output(test_client):
    import logging

    from pdf_reader.task_logging import SafeFormatter

    captured = []
    handler = logging.Handler()
    handler.setLevel(logging.WARNING)
    handler.setFormatter(SafeFormatter("%(message)s"))
    handler.emit = lambda record: captured.append(handler.format(record))
    client_logger = logging.getLogger("pdf_reader.client")
    client_logger.addHandler(handler)
    try:
        resp = test_client.post(
            "/api/client-errors",
            json={
                "kind": "window_error",
                "message": "api_key=sk-super-secret-123456 and Authorization: Bearer abcdefghijklmnop",
                "stack": "sk-another-secret-9999",
            },
        )
    finally:
        client_logger.removeHandler(handler)
        handler.close()

    assert resp.status_code == 202
    output = "\n".join(captured)
    assert "sk-super-secret-123456" not in output
    assert "sk-another-secret-9999" not in output
    assert "abcdefghijklmnop" not in output
    assert "<redacted>" in output


def test_http_exception_500_records_traceback(managed_caplog, monkeypatch, tmp_path):
    import logging

    from werkzeug.exceptions import InternalServerError

    from pdf_reader.routes import register_routes
    from pdf_reader.state import AppState
    from pdf_reader.translation_coordinator import TranslationCoordinator

    state = AppState(tmp_path / "cache")
    app = Flask(__name__)
    app.config.update(
        app_state=state,
        TESTING=False,
        translation_coordinator=TranslationCoordinator(),
    )
    register_routes(app)

    def boom(page):  # noqa: ANN202
        raise InternalServerError("boom-http500-diagnostic")

    monkeypatch.setattr(state, "save_reading_progress", boom)
    with managed_caplog.at_level(logging.ERROR, logger="pdf_reader.routes"):
        with app.test_client() as client:
            resp = client.post("/api/reading-progress", json={"page": 0})

    assert resp.status_code == 500
    assert resp.get_json() == {"code": "internal_error", "error": "服务器内部错误"}
    records = [r for r in managed_caplog.records if r.name == "pdf_reader.routes"]
    assert len(records) == 1
    assert records[0].levelno == logging.ERROR
    assert "HTTP error 500 while processing POST /api/reading-progress" in records[0].message
    assert "Traceback (most recent call last):" in managed_caplog.text
    assert "boom-http500-diagnostic" in managed_caplog.text


def test_http_exception_4xx_has_no_traceback(test_client, managed_caplog):
    import logging

    with managed_caplog.at_level(logging.WARNING, logger="pdf_reader.routes"):
        resp = test_client.post("/api/page/left/0")

    assert resp.status_code == 405
    records = [r for r in managed_caplog.records if r.name == "pdf_reader.routes"]
    assert len(records) == 1
    assert "HTTP error 405" in records[0].message
    assert "Traceback" not in managed_caplog.text
