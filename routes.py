import asyncio
import io
import json
import logging
import os
import queue
import shutil
import tempfile
import threading
from pathlib import Path

import pymupdf
from flask import (
    Blueprint,
    Response,
    current_app,
    jsonify,
    render_template,
    request,
    send_file,
    stream_with_context,
)
from pdf2zh_next import do_translate_async_stream

import config
from glossary_merger import merge_glossary_csvs
from services import build_settings, render_page, sha256

bp = Blueprint("main", __name__)

STAGE_LABELS = {
    "layout_analysis": "\u6b63\u5728\u5206\u6790\u7248\u9762\u2026",
    "translating": "\u6b63\u5728\u7ffb\u8bd1\u2026",
    "generating_pdf": "\u6b63\u5728\u751f\u6210\u8bd1\u6587\u2026",
    "generating_pdf_bilingual": "\u6b63\u5728\u751f\u6210\u8bd1\u6587\u2026",
    "finish": "\u7ffb\u8bd1\u5b8c\u6210",
}


def error_response(msg: str, code: int) -> tuple:
    return jsonify({"error": msg}), code


def _get_state():
    return current_app.config["app_state"]


@bp.route("/api/open", methods=["POST"])
def open_pdf():
    data = request.get_json(silent=True) or {}
    pdf_path = data.get("path", "").strip()
    if not pdf_path or not os.path.isfile(pdf_path):
        return error_response("file not found", 400)

    state = _get_state()
    result = state.open_pdf(pdf_path, sha256)
    return jsonify(result)


@bp.route("/api/page/<side>/<int:page>")
def get_page(side: str, page: int):
    if side not in ("left", "right"):
        return error_response("invalid side", 400)

    state = _get_state()
    try:
        png_data = state.render_page(side, page, render_page, config.DPI)
    except ValueError:
        return error_response("page out of range", 404)

    return send_file(
        io.BytesIO(png_data),
        mimetype="image/png",
    )


@bp.route("/api/page-count/<side>")
def page_count(side: str):
    state = _get_state()
    if side == "left" and state.left_doc:
        return jsonify({"count": state.left_doc.page_count})
    elif side == "right" and state.right_doc:
        return jsonify({"count": state.right_doc.page_count})
    return error_response("no document opened", 400)


@bp.route("/")
def index():
    return render_template("index.html")


@bp.route("/api/translate/<int:page>", methods=["POST"])
def translate_page(page: int):
    state = _get_state()
    if state.left_doc is None:
        return error_response("no document opened", 400)

    data = request.get_json(silent=True) or {}
    user_prompt = (data.get("prompt") or "").strip() or None

    tmpdir = tempfile.mkdtemp()
    output_dir = tempfile.mkdtemp(dir=str(config.CACHE_DIR))
    tmpdir_path = Path(tmpdir)
    single_page_pdf = tmpdir_path / "page.pdf"
    single_doc = pymupdf.open()
    single_doc.insert_pdf(state.left_doc, from_page=page, to_page=page)
    single_doc.save(str(single_page_pdf))
    single_doc.close()

    def generate():
        try:
            cumulative_glossary_path = state.glossary_cache_path
            glossary_paths: list[str] | None = None
            if cumulative_glossary_path is not None:
                cumulative_file = cumulative_glossary_path / "cumulative_glossary.csv"
                if cumulative_file.exists() and cumulative_file.stat().st_size > 0:
                    glossary_paths = [str(cumulative_file)]
                    logging.getLogger("pdf_reader").info("Loading cumulative glossary: %s", cumulative_file)
                else:
                    logging.getLogger("pdf_reader").info("No cumulative glossary found at: %s", cumulative_file)

            settings = build_settings(
                str(single_page_pdf),
                user_prompt,
                output_dir=output_dir,
                glossary_paths=glossary_paths,
            )
            event_queue: queue.Queue = queue.Queue()
            error_info: str | None = None

            def run_translation() -> None:
                nonlocal error_info
                loop: asyncio.AbstractEventLoop | None = None
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)

                    async def _run() -> bool:
                        async for evt in do_translate_async_stream(settings, str(single_page_pdf)):
                            event_queue.put(evt)
                        return True

                    loop.run_until_complete(_run())
                except Exception as e:
                    error_info = str(e)
                finally:
                    if loop is not None:
                        try:
                            pending = asyncio.all_tasks(loop)
                            if pending:
                                for task in pending:
                                    task.cancel()
                                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                        except Exception:
                            pass
                        loop.close()
                    event_queue.put({"type": "_done"})

            thread = threading.Thread(target=run_translation, daemon=True)
            thread.start()

            translate_result = None
            while True:
                try:
                    evt = event_queue.get(timeout=1.0)
                except queue.Empty:
                    yield ""
                    continue

                if evt.get("type") == "_done":
                    break

                evt_type = evt.get("type", "")
                # BabelDOC event contract (from do_translate_async_stream):
                #   progress_start:   stage, overall_progress, stage_current, stage_total
                #   progress_update:  stage, overall_progress, stage_current, stage_total
                #   progress_end:     stage, overall_progress
                #   finish:           translate_result, token_usage
                if evt_type == "progress_start":
                    yield "data: " + json.dumps({
                        "type": "progress", "progress": 0,
                        "stage": evt.get("stage", ""),
                        "stage_current": evt.get("stage_current", 0),
                        "stage_total": evt.get("stage_total", 0),
                    }) + "\n\n"
                elif evt_type == "progress_update":
                    yield "data: " + json.dumps({
                        "type": "progress",
                        "progress": evt.get("overall_progress", 0),
                        "stage": evt.get("stage", ""),
                        "stage_current": evt.get("stage_current", 0),
                        "stage_total": evt.get("stage_total", 0),
                    }) + "\n\n"
                elif evt_type == "finish":
                    translate_result = evt.get("translate_result")
                    yield "data: " + json.dumps({
                        "type": "progress", "progress": 95,
                        "stage": evt.get("stage", "generating_pdf"),
                        "stage_current": 0, "stage_total": 0,
                    }) + "\n\n"
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
                    state.replace_page(str(translated_pdf), page)
                else:
                    yield f"data: {json.dumps({'type': 'error', 'error': 'no output PDF'})}\n\n"
                    return
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
                return

            result_logger = logging.getLogger("pdf_reader")
            glossary_path_value = getattr(translate_result, "auto_extracted_glossary_path", "MISSING_ATTR")
            result_logger.info(
                "translate_result has auto_extracted_glossary_path: %s (type=%s)",
                glossary_path_value, type(glossary_path_value).__name__,
            )

            if (
                cumulative_glossary_path is not None
                and translate_result.auto_extracted_glossary_path
            ):
                auto_path = Path(translate_result.auto_extracted_glossary_path)
                cumulative_file = cumulative_glossary_path / "cumulative_glossary.csv"
                result_logger.info(
                    "Merging glossary: auto=%s → cumulative=%s",
                    auto_path, cumulative_file,
                )
                try:
                    merge_glossary_csvs(cumulative_file, auto_path)
                    result_logger.info("Glossary merge complete")
                except Exception:
                    result_logger.warning(
                        "Failed to merge glossary for page %d", page, exc_info=True
                    )
            else:
                result_logger.info(
                    "Skipping glossary merge: cumulative_path=%s, auto_path=%s",
                    cumulative_glossary_path,
                    translate_result.auto_extracted_glossary_path if hasattr(translate_result, "auto_extracted_glossary_path") else "ATTR_MISSING",
                )

            yield "data: " + json.dumps({
                "type": "progress", "progress": 100,
                "stage": "finish", "stage_current": 0, "stage_total": 0,
            }) + "\n\n"
            yield f"data: {json.dumps({'type': 'finish', 'progress': 100})}\n\n"
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
            shutil.rmtree(output_dir, ignore_errors=True)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@bp.route("/api/translated-pages")
def translated_pages():
    state = _get_state()
    return jsonify({"pages": sorted(list(state.translated_pages))})


@bp.app_errorhandler(404)
def not_found(e):
    return jsonify({"error": "not found"}), 404


def register_routes(app):
    app.register_blueprint(bp)
