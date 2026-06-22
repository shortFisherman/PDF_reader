import io
import os
import tempfile
from pathlib import Path

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

import config
import glossary_service
import pdf_extraction
import sse_stream
from file_hash import sha256
from pdf_renderer import build_settings, render_page

bp = Blueprint("main", __name__)


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
    if page < 0 or page >= state.page_count:
        return error_response("page out of range", 400)

    data = request.get_json(silent=True) or {}
    user_prompt = (data.get("prompt") or "").strip() or None

    tmpdir = Path(tempfile.mkdtemp())
    output_dir = tempfile.mkdtemp(dir=str(config.CACHE_DIR))
    single_page_pdf = pdf_extraction.extract_single_page(state.left_doc, page, tmpdir)
    glossary_paths = glossary_service.resolve_glossary_paths(state.glossary_cache_path)
    settings = build_settings(
        str(single_page_pdf), user_prompt,
        output_dir=output_dir, glossary_paths=glossary_paths,
    )
    ctx = sse_stream.GenerateContext(
        settings=settings,
        single_page_pdf=single_page_pdf,
        replace_page=lambda path: state.replace_page(path, page),
        glossary_cache_path=state.glossary_cache_path,
        page=page,
        glossary_paths=glossary_paths,
        tmpdir=tmpdir,
        output_dir=output_dir,
    )
    return Response(
        stream_with_context(sse_stream.generate(ctx)),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@bp.route("/api/translated-pages")
def translated_pages():
    state = _get_state()
    return jsonify({"pages": sorted(list(state.translated_pages))})


@bp.route("/api/stages")
def get_stages():
    return jsonify(sse_stream.STAGE_LABELS)


@bp.app_errorhandler(404)
def not_found(e):
    return jsonify({"error": "not found"}), 404


def register_routes(app):
    app.register_blueprint(bp)
