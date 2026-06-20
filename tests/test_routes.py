import csv
import json
from pathlib import Path
from unittest.mock import MagicMock

from flask import Flask


def test_index_route(test_client):
    resp = test_client.get('/')
    assert resp.status_code == 200

def test_open_missing_file(test_client):
    resp = test_client.post('/api/open', json={"path": "/nonexistent/file.pdf"})
    assert resp.status_code == 400
    data = json.loads(resp.data)
    assert "error" in data

def test_get_page_no_doc(test_client):
    resp = test_client.get('/api/page/left/0')
    assert resp.status_code in (400, 404)
    data = json.loads(resp.data)
    assert "error" in data

def test_page_count_no_doc(test_client):
    resp = test_client.get('/api/page-count/left')
    assert resp.status_code == 400
    data = json.loads(resp.data)
    assert "error" in data

def test_translate_no_doc(test_client):
    resp = test_client.post('/api/translate/0')
    assert resp.status_code == 400
    data = json.loads(resp.data)
    assert "error" in data

def test_translated_pages_no_doc(test_client):
    resp = test_client.get('/api/translated-pages')
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data == {"pages": []}


def test_debug_trace_logger_exists():
    from routes import trace_logger
    import logging
    assert isinstance(trace_logger, logging.Logger)
    assert trace_logger.name == "pdf_reader.debug_trace"
    assert trace_logger.level == logging.INFO


def test_translate_page_integrates_cumulative_glossary(app_state, sample_pdf, monkeypatch):
    """build_settings receives cumulative glossary path; merge happens after translation."""
    from services import sha256 as sha256_func

    # 1. Open PDF, create cumulative glossary
    app_state.open_pdf(str(sample_pdf), sha256_func)
    glossary_cache = app_state.glossary_cache_path
    assert glossary_cache is not None
    cumulative_file = glossary_cache / "cumulative_glossary.csv"
    with open(cumulative_file, "w", newline="", encoding="utf-8") as f:
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

    def fake_build_settings(pdf_path, user_prompt=None, output_dir=None, glossary_paths=None, debug=None):  # noqa: ANN202
        settings_call_kwargs.append({"glossary_paths": glossary_paths})
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

    monkeypatch.setattr("routes.build_settings", fake_build_settings)
    monkeypatch.setattr("routes.do_translate_async_stream", fake_translate_stream)
    monkeypatch.setattr("routes.merge_glossary_csvs", fake_merge)

    # 5. Create Flask app with our state
    app = Flask(__name__)
    app.config["app_state"] = app_state
    app.config["TESTING"] = True
    from routes import register_routes

    register_routes(app)

    # 6. Request translation
    with app.test_client() as client:
        resp = client.post("/api/translate/0", json={})
        assert resp.status_code == 200
        body = resp.data.decode("utf-8")
        assert '"type": "finish"' in body

    # 7. Verify build_settings received cumulative glossary
    assert len(settings_call_kwargs) == 1
    assert settings_call_kwargs[0]["glossary_paths"] == [str(cumulative_file)]

    # 8. Verify merge_glossary_csvs called with correct paths
    assert len(merge_calls) == 1
    assert merge_calls[0] == (str(cumulative_file), str(auto_file))
