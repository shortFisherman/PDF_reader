import io
import logging
import os

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
from werkzeug.exceptions import HTTPException

import config
import glossary_service
import sse_stream
from file_hash import sha256
from pdf_renderer import render_page
from task_logging import STATUS_STARTED, task_context_from_indices, task_log
from translation_coordinator import TranslationBusyError, TranslationCoordinator, TranslationJob
from translation_settings import build_settings

logger = logging.getLogger("pdf_reader.routes")

bp = Blueprint("main", __name__)


def error_response(msg: str, code: int, error_code: str) -> tuple:
    return jsonify({"code": error_code, "error": msg}), code


def _get_state():
    return current_app.config["app_state"]


def _get_coordinator() -> TranslationCoordinator:
    return current_app.config["translation_coordinator"]


def translation_busy_response(active_job: TranslationJob | None = None) -> tuple:
    payload = {
        "error": "已有翻译任务正在进行，请稍后再试",
        "code": "translation_busy",
    }
    if active_job is not None:
        payload["active_job_id"] = active_job.job_id
    return jsonify(payload), 409


@bp.route("/api/open", methods=["POST"])
def open_pdf():
    data = request.get_json(silent=True) or {}
    pdf_path = data.get("path", "").strip()
    logger.debug("[route] open_pdf path=%s", pdf_path)
    if not pdf_path or not os.path.isfile(pdf_path):
        logger.debug("[route] open_pdf invalid path")
        return error_response("file not found", 400, "invalid_file_path")

    coordinator = _get_coordinator()
    active_job = coordinator.active_job
    if active_job is not None:
        task_log(
            logger,
            logging.INFO,
            "rejected document open while translation is active",
            task=task_context_from_indices(
                active_job.job_id,
                active_job.document_id,
                active_job.pdf_hash or "",
                active_job.page_indices,
                status=STATUS_STARTED,
            ),
        )
        return translation_busy_response(active_job)

    state = _get_state()
    result = state.open_pdf(pdf_path, sha256)
    return jsonify(result)


@bp.route("/api/reading-progress", methods=["POST"])
def save_reading_progress():
    data = request.get_json(silent=True) or {}
    page = data.get("page")
    if not isinstance(page, int) or isinstance(page, bool):
        logger.debug("[route] save-reading-progress invalid page=%r", page)
        return error_response("invalid page", 400, "invalid_page")

    state = _get_state()
    try:
        state.save_reading_progress(page)
    except ValueError as e:
        msg = str(e)
        logger.debug("[route] save-reading-progress page=%d rejected: %s", page, msg)
        code_by_message = {
            "no document opened": "no_document_opened",
            "page out of range": "page_out_of_range",
        }
        return error_response(msg, 400, code_by_message.get(msg, "invalid_request"))

    logger.debug("[route] save-reading-progress page=%d", page)
    return jsonify({"ok": True})


@bp.route("/api/page/<side>/<int:page>")
def get_page(side: str, page: int):
    if side not in ("left", "right"):
        return error_response("invalid side", 400, "invalid_side")

    state = _get_state()
    try:
        png_data = state.render_page(side, page, render_page, config.DPI)
    except ValueError:
        return error_response("page out of range", 404, "page_out_of_range")

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
    return error_response("no document opened", 400, "no_document_opened")


@bp.route("/")
def index():
    return render_template("index.html")


@bp.route("/api/translate/<int:page>", methods=["POST"])
def translate_page(page: int):
    logger.debug("[route] translate_page page=%d", page)
    state = _get_state()
    try:
        snapshot = state.translation_snapshot()
    except ValueError:
        logger.debug("[route] translate_page no doc")
        return error_response("no document opened", 400, "no_document_opened")
    if page < 0 or page >= snapshot.page_count:
        logger.debug("[route] translate_page page out of range")
        return error_response("page out of range", 400, "page_out_of_range")

    data = request.get_json(silent=True) or {}
    user_prompt = (data.get("prompt") or "").strip() or None

    glossary_paths = glossary_service.resolve_glossary_paths(snapshot.glossary_cache_path)
    settings = build_settings(
        "",
        user_prompt,
        glossary_paths=glossary_paths,
    )
    coordinator = _get_coordinator()
    try:
        job = coordinator.start(snapshot.document_id, [page], pdf_hash=snapshot.pdf_hash)
    except TranslationBusyError as exc:
        task_log(
            logger,
            logging.INFO,
            "rejected overlapping single-page request",
            task=task_context_from_indices(
                exc.active_job.job_id,
                exc.active_job.document_id,
                exc.active_job.pdf_hash or "",
                exc.active_job.page_indices,
                status=STATUS_STARTED,
            ),
        )
        return translation_busy_response(exc.active_job)
    ctx = sse_stream.GenerateContext(
        settings=settings,
        job_id=job.job_id,
        finish_job=coordinator.finish,
        fail_job=coordinator.fail,
        cancel_job=coordinator.cancel,
        replace_page=lambda path: state.replace_page(path, page, snapshot.document_id),
        merge_glossary=lambda extracted: state.merge_glossary(
            extracted,
            snapshot.document_id,
            glossary_service.merge_after_translate,
        ),
        glossary_cache_path=snapshot.glossary_cache_path,
        page=page,
        glossary_paths=glossary_paths,
        cache_dir=config.CACHE_DIR,
        task_ctx=task_context_from_indices(
            job.job_id,
            snapshot.document_id,
            snapshot.pdf_hash,
            [page],
            status=STATUS_STARTED,
        ),
        extract_page=lambda page, tmpdir, func: state.extract_page(
            page,
            tmpdir,
            func,
            snapshot.document_id,
        ),
    )
    try:
        response = Response(
            stream_with_context(sse_stream.generate(ctx)),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    except Exception:
        coordinator.fail(job.job_id)
        raise
    response.call_on_close(lambda: coordinator.fail(job.job_id))
    return response


@bp.route("/api/translate-batch", methods=["POST"])
def translate_batch():
    state = _get_state()
    try:
        snapshot = state.translation_snapshot()
    except ValueError:
        logger.debug("[route] translate_batch no doc")
        return error_response("no document opened", 400, "no_document_opened")

    data = request.get_json(silent=True) or {}
    from_page = data.get("from")
    to_page = data.get("to")
    logger.debug("[route] translate_batch from=%s to=%s", from_page, to_page)
    page_count = snapshot.page_count

    if not isinstance(from_page, int) or not isinstance(to_page, int):
        logger.debug("[route] translate_batch invalid page numbers")
        return error_response("invalid page numbers", 400, "invalid_page_numbers")
    if from_page < 1 or to_page < 1 or from_page > page_count or to_page > page_count:
        logger.debug("[route] translate_batch page out of range")
        return error_response("page out of range", 400, "page_out_of_range")
    if from_page > to_page:
        logger.debug("[route] translate_batch invalid page range")
        return error_response("invalid page range", 400, "invalid_page_range")

    user_prompt = (data.get("prompt") or "").strip() or None
    page_indices = list(range(from_page - 1, to_page))
    k = len(page_indices)
    pages_str = f"1-{k}" if k > 1 else "1"

    glossary_paths = glossary_service.resolve_glossary_paths(snapshot.glossary_cache_path)
    settings = build_settings(
        "",
        user_prompt,
        glossary_paths=glossary_paths,
        pages=pages_str,
    )
    coordinator = _get_coordinator()
    try:
        job = coordinator.start(snapshot.document_id, page_indices, pdf_hash=snapshot.pdf_hash)
    except TranslationBusyError as exc:
        task_log(
            logger,
            logging.INFO,
            "rejected overlapping batch request",
            task=task_context_from_indices(
                exc.active_job.job_id,
                exc.active_job.document_id,
                exc.active_job.pdf_hash or "",
                exc.active_job.page_indices,
                status=STATUS_STARTED,
            ),
        )
        return translation_busy_response(exc.active_job)
    ctx = sse_stream.GenerateBatchContext(
        settings=settings,
        job_id=job.job_id,
        finish_job=coordinator.finish,
        fail_job=coordinator.fail,
        cancel_job=coordinator.cancel,
        from_page=from_page,
        to_page=to_page,
        page_indices=page_indices,
        replace_pages=lambda path: state.replace_pages(path, page_indices, snapshot.document_id),
        merge_glossary=lambda extracted: state.merge_glossary(
            extracted,
            snapshot.document_id,
            glossary_service.merge_after_translate,
        ),
        glossary_cache_path=snapshot.glossary_cache_path,
        glossary_paths=glossary_paths,
        cache_dir=config.CACHE_DIR,
        task_ctx=task_context_from_indices(
            job.job_id,
            snapshot.document_id,
            snapshot.pdf_hash,
            page_indices,
            status=STATUS_STARTED,
        ),
        extract_pages=lambda indices, tmpdir, func: state.extract_pages(
            indices,
            tmpdir,
            func,
            snapshot.document_id,
        ),
    )
    try:
        response = Response(
            stream_with_context(sse_stream.generate_batch(ctx)),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    except Exception:
        coordinator.fail(job.job_id)
        raise
    response.call_on_close(lambda: coordinator.fail(job.job_id))
    return response


@bp.route("/api/translated-pages")
def translated_pages():
    state = _get_state()
    return jsonify({"pages": sorted(list(state.translated_pages))})


@bp.route("/api/stages")
def get_stages():
    return jsonify(sse_stream.STAGE_LABELS)


@bp.app_errorhandler(404)
def not_found(e):
    return jsonify({"code": "not_found", "error": "not found"}), 404


@bp.app_errorhandler(HTTPException)
def http_error(exc: HTTPException):
    status = exc.code or 500
    logger.warning("HTTP error %s while processing %s %s", status, request.method, request.path)
    if status == 500:
        return jsonify({"code": "internal_error", "error": "服务器内部错误"}), 500
    return jsonify({"code": f"http_{status}", "error": "请求错误"}), status


@bp.app_errorhandler(Exception)
def internal_error(exc: Exception):
    logger.error(
        "Unhandled exception while processing %s %s",
        request.method,
        request.path,
        exc_info=exc,
    )
    return jsonify({"code": "internal_error", "error": "服务器内部错误"}), 500


def register_routes(app):
    app.config.setdefault("translation_coordinator", TranslationCoordinator())
    app.register_blueprint(bp)
