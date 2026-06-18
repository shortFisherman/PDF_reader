import hashlib
import io
import json
import os
import shutil
import tempfile
import threading
import tomllib
from pathlib import Path

import pymupdf
from flask import Flask, Response, jsonify, render_template, request, send_file, stream_with_context

from pdf2zh_next import SettingsModel, do_translate_async_stream
from pdf2zh_next.config.model import TranslationSettings as Pdf2zhTranslationSettings
from pdf2zh_next.config.model import PDFSettings as Pdf2zhPDFSettings
from pdf2zh_next.config.translate_engine_model import DeepSeekSettings

app = Flask(__name__)

CONFIG_PATH = Path(__file__).parent / "config.toml"
with open(CONFIG_PATH, "rb") as f:
    CONFIG = tomllib.load(f)

CACHE_DIR = Path(CONFIG["pdf_reader"]["cache_dir"]).resolve()
DPI = CONFIG["pdf_reader"]["dpi"]

DEEPSEEK_API_KEY = CONFIG["deepseek"]["api_key"]
DEEPSEEK_MODEL = CONFIG["deepseek"]["model"]
DEEPSEEK_BASE_URL = CONFIG["deepseek"]["base_url"]

TRANSLATION_LANG_IN = CONFIG["translation"]["lang_in"]
TRANSLATION_LANG_OUT = CONFIG["translation"]["lang_out"]

GLOSSARY_PATH = Path(__file__).parent / "glossary.csv"

state = {
    "pdf_path": None,
    "pdf_hash": None,
    "left_doc": None,
    "right_doc": None,
    "right_pdf_path": None,
    "page_count": 0,
    "page_height": 0,
    "page_width": 0,
    "translated_pages": set(),
}


def _sha256(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _render_page(doc: pymupdf.Document, page_num: int) -> bytes:
    if page_num < 0 or page_num >= doc.page_count:
        raise ValueError("page out of range")
    page = doc[page_num]
    pix = page.get_pixmap(dpi=DPI)
    return pix.tobytes(output="png")


@app.route("/api/open", methods=["POST"])
def open_pdf():
    data = request.get_json(silent=True) or {}
    pdf_path = data.get("path", "").strip()
    if not pdf_path or not os.path.isfile(pdf_path):
        return jsonify({"error": "file not found"}), 400

    pdf_hash = _sha256(pdf_path)
    cache_subdir = CACHE_DIR / pdf_hash
    cache_subdir.mkdir(parents=True, exist_ok=True)
    right_pdf_path = cache_subdir / "right.pdf"

    if not right_pdf_path.exists():
        shutil.copy2(pdf_path, right_pdf_path)

    left_doc = pymupdf.open(pdf_path)
    right_doc = pymupdf.open(str(right_pdf_path))

    sample_page = left_doc[0]
    state["pdf_path"] = pdf_path
    state["pdf_hash"] = pdf_hash
    state["left_doc"] = left_doc
    state["right_doc"] = right_doc
    state["right_pdf_path"] = str(right_pdf_path)
    state["page_count"] = left_doc.page_count
    state["page_height"] = sample_page.rect.height
    state["page_width"] = sample_page.rect.width

    return jsonify({
        "page_count": left_doc.page_count,
        "page_height": sample_page.rect.height,
        "page_width": sample_page.rect.width,
        "hash": pdf_hash,
    })


@app.route("/api/page/<side>/<int:page>")
def get_page(side, page):
    doc = None
    if side == "left":
        doc = state["left_doc"]
    elif side == "right":
        doc = state["right_doc"]
    else:
        return jsonify({"error": "invalid side"}), 400

    if doc is None:
        return jsonify({"error": "no document opened"}), 400

    try:
        png_data = _render_page(doc, page)
    except ValueError:
        return jsonify({"error": "page out of range"}), 404

    return send_file(
        io.BytesIO(png_data),
        mimetype="image/png",
    )


@app.route("/api/page-count/<side>")
def page_count(side):
    if side == "left" and state["left_doc"]:
        return jsonify({"count": state["left_doc"].page_count})
    elif side == "right" and state["right_doc"]:
        return jsonify({"count": state["right_doc"].page_count})
    return jsonify({"error": "no document opened"}), 400


@app.route("/")
def index():
    return render_template("index.html")


def _build_settings(single_page_pdf: str, user_prompt: str | None = None) -> SettingsModel:
    translation_kwargs = {
        "lang_in": TRANSLATION_LANG_IN,
        "lang_out": TRANSLATION_LANG_OUT,
        "ignore_cache": True,
    }
    if user_prompt and user_prompt.strip():
        translation_kwargs["custom_system_prompt"] = user_prompt.strip()
    if GLOSSARY_PATH.exists() and GLOSSARY_PATH.stat().st_size > 0:
        translation_kwargs["glossaries"] = str(GLOSSARY_PATH)

    return SettingsModel(
        translation=Pdf2zhTranslationSettings(**translation_kwargs),
        pdf=Pdf2zhPDFSettings(
            pages="1",
            no_dual=True,
            only_include_translated_page=True,
            watermark_output_mode="no_watermark",
        ),
        translate_engine_settings=DeepSeekSettings(
            deepseek_api_key=DEEPSEEK_API_KEY,
            deepseek_model=DEEPSEEK_MODEL,
        ),
    )


def _replace_page_in_right_pdf(translated_pdf_path: str, page_num: int):
    src_doc = pymupdf.open(translated_pdf_path)
    right_doc = state["right_doc"]

    right_doc.delete_page(page_num)
    right_doc.insert_pdf(src_doc, start_at=page_num)

    tmp_save = state["right_pdf_path"] + ".tmp"
    right_doc.save(tmp_save)
    src_doc.close()
    right_doc.close()

    os.replace(tmp_save, state["right_pdf_path"])
    state["right_doc"] = pymupdf.open(str(state["right_pdf_path"]))
    state["translated_pages"].add(page_num)


@app.route("/api/translate/<int:page>", methods=["POST"])
def translate_page(page):
    if state["left_doc"] is None:
        return jsonify({"error": "no document opened"}), 400

    data = request.get_json(silent=True) or {}
    user_prompt = (data.get("prompt") or "").strip() or None

    tmpdir = tempfile.mkdtemp()
    tmpdir_path = Path(tmpdir)
    single_page_pdf = tmpdir_path / "page.pdf"
    single_doc = pymupdf.open()
    single_doc.insert_pdf(state["left_doc"], from_page=page, to_page=page)
    single_doc.save(str(single_page_pdf))
    single_doc.close()

    def generate():
        try:
            settings = _build_settings(str(single_page_pdf), user_prompt)
            event_queue = []
            event_lock = threading.Lock()
            error_info = None

            def run_translation():
                import asyncio
                nonlocal error_info
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)

                    async def _run():
                        async for evt in do_translate_async_stream(settings, str(single_page_pdf)):
                            with event_lock:
                                event_queue.append(evt)
                        return True

                    loop.run_until_complete(_run())
                except Exception as e:
                    error_info = str(e)
                finally:
                    with event_lock:
                        event_queue.append({"type": "_done"})

            thread = threading.Thread(target=run_translation, daemon=True)
            thread.start()

            translate_result = None
            while True:
                with event_lock:
                    if event_queue:
                        evt = event_queue.pop(0)
                    else:
                        evt = None

                if evt is None:
                    import time
                    time.sleep(0.1)
                    yield ""
                    continue

                if evt.get("type") == "_done":
                    break

                evt_type = evt.get("type", "")
                if evt_type == "progress_start":
                    yield f"data: {json.dumps({'type': 'progress', 'progress': 0, 'stage': evt.get('stage', '')})}\n\n"
                elif evt_type == "progress_update":
                    yield f"data: {json.dumps({'type': 'progress', 'progress': evt.get('overall_progress', 0)})}\n\n"
                elif evt_type == "finish":
                    translate_result = evt.get("translate_result")
                    yield f"data: {json.dumps({'type': 'progress', 'progress': 95})}\n\n"
                elif evt_type == "error":
                    yield f"data: {json.dumps({'type': 'error', 'error': evt.get('error', 'unknown')})}\n\n"
                    return

            if error_info:
                yield f"data: {json.dumps({'type': 'error', 'error': error_info})}\n\n"
                return

            if translate_result is None:
                yield f"data: {json.dumps({'type': 'error', 'error': 'no translation result'})}\n\n"
                return

            try:
                translated_pdf = translate_result.mono_pdf_path
                if translated_pdf is None and translate_result.dual_pdf_path is not None:
                    translated_pdf = translate_result.dual_pdf_path

                if translated_pdf is not None:
                    _replace_page_in_right_pdf(str(translated_pdf), page)
                else:
                    yield f"data: {json.dumps({'type': 'error', 'error': 'no output PDF'})}\n\n"
                    return
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
                return

            yield f"data: {json.dumps({'type': 'finish', 'progress': 100})}\n\n"
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.route("/api/translated-pages")
def translated_pages():
    return jsonify({"pages": sorted(list(state["translated_pages"]))})


@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "not found"}), 404


if __name__ == "__main__":
    debug = CONFIG.get("server", {}).get("debug", True)
    host = CONFIG.get("server", {}).get("host", "127.0.0.1")
    port = CONFIG.get("server", {}).get("port", 5000)
    print(f"Starting PDF Reader on http://{host}:{port}")
    app.run(host=host, port=port, debug=debug)
