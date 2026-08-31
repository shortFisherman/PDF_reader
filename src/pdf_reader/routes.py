import io
import ipaddress
import logging
import os
import re
from typing import cast

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

from pdf_reader import config, config_editor, glossary_service, sse_stream, strict_glossary
from pdf_reader.file_hash import sha256
from pdf_reader.pdf_renderer import render_page
from pdf_reader.task_logging import STATUS_STARTED, task_context_from_indices, task_log
from pdf_reader.translation_coordinator import (
    CoordinatorShutdownError,
    TranslationBusyError,
    TranslationCoordinator,
    TranslationJob,
)

logger = logging.getLogger("pdf_reader.routes")
client_logger = logging.getLogger("pdf_reader.client")

bp = Blueprint("main", __name__)

_CLIENT_ERROR_FIELDS = frozenset({"kind", "message", "source", "line", "column", "stack"})
_CLIENT_ERROR_STRING_LIMITS = {
    "kind": 64,
    "message": 1024,
    "source": 512,
    "stack": 4096,
}
_CLIENT_ERROR_MAX_BODY_BYTES = 8192
_CLIENT_ERROR_MAX_COORDINATE = 2**31 - 1
_CLIENT_ERROR_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def error_response(msg: str, code: int, error_code: str) -> tuple:
    return jsonify({"code": error_code, "error": msg}), code


def _get_state():
    return current_app.config["app_state"]


def _get_settings() -> config.AppSettings:
    return cast(config.AppSettings, current_app.config["app_settings"])


def _get_coordinator() -> TranslationCoordinator:
    return cast(TranslationCoordinator, current_app.config["translation_coordinator"])


def _get_candidate_service():
    """返回旁路候选提取服务；未注入（兼容 fallback）时为 None，正文不受影响。"""
    return current_app.config.get("candidate_extraction_service")


def _get_config_path():
    return current_app.config.get("config_path", config.CONFIG_PATH)


def _is_loopback_remote_addr(remote_addr: str | None) -> bool:
    """仅按 ``request.remote_addr`` 判断本机来源（不信任 Host/X-Forwarded-For）。

    接受 127/8、::1 以及 IPv4-mapped loopback（如 ``::ffff:127.0.0.1``）；
    remote_addr 缺失、非字符串或非法时 fail closed。
    """
    if not isinstance(remote_addr, str) or not remote_addr.strip():
        return False
    try:
        return ipaddress.ip_address(remote_addr.strip()).is_loopback
    except ValueError:
        return False


def _loopback_config_guard() -> tuple | None:
    """配置中心读写共享的 loopback-only 检查；非本机返回 403 响应。"""
    if _is_loopback_remote_addr(request.remote_addr):
        return None
    logger.warning(
        "config center access rejected from non-loopback remote_addr=%r",
        request.remote_addr,
    )
    return error_response(
        "配置中心仅允许本机访问，请通过 127.0.0.1 或 ::1 操作",
        403,
        "config_local_only",
    )


def _clean_client_error_text(value: object, limit: int) -> str:
    """白名单字符串字段规范化：换行/控制字符折叠为空格后截断，保证单行可读。"""
    text = str(value).replace("\r", " ").replace("\n", " ").replace("\t", " ")
    text = _CLIENT_ERROR_CONTROL_CHARS.sub(" ", text)
    text = re.sub(r"[ \t]{2,}", " ", text).strip()
    return text[:limit]


def _clean_client_error_coordinate(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 0 or value > _CLIENT_ERROR_MAX_COORDINATE:
        return None
    return value


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
    settings = _get_settings()
    try:
        png_data = state.render_page(side, page, render_page, settings.dpi)
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

    app_settings = _get_settings()
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
    except CoordinatorShutdownError:
        logger.info("rejected translate request during coordinator shutdown")
        return translation_busy_response(None)
    try:
        strict_ctx = strict_glossary.prepare_strict_translation_context(snapshot)
        settings_model = strict_glossary.build_strict_settings(
            app_settings.upstream,
            user_prompt,
            "1",
            strict_ctx,
        )
    except Exception as exc:
        coordinator.fail(job.job_id)
        stage = getattr(exc, "stage", "settings")
        cause_type = getattr(exc, "cause_type", type(exc).__name__)
        logger.error(
            "strict glossary prepare failed stage=%s cause=%s doc=%s",
            stage,
            cause_type,
            snapshot.pdf_hash[:12],
        )
        return error_response("术语词表准备失败，请查看服务端日志", 500, "glossary_prepare_failed")
    ctx = sse_stream.GenerateContext(
        settings=settings_model,
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
        glossary_paths=(
            [str(strict_ctx.effective_glossary_path)] if strict_ctx.effective_glossary_path is not None else None
        ),
        cache_dir=app_settings.cache_dir,
        provider=app_settings.model_provider,
        model=app_settings.model,
        lang_in=app_settings.lang_in,
        lang_out=app_settings.lang_out,
        debug=app_settings.debug,
        register_stream=coordinator.register_stream,
        unregister_stream=coordinator.unregister_stream,
        strict_context=strict_ctx,
        candidate_service=_get_candidate_service(),
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

    app_settings = _get_settings()
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
    except CoordinatorShutdownError:
        logger.info("rejected batch request during coordinator shutdown")
        return translation_busy_response(None)
    try:
        strict_ctx = strict_glossary.prepare_strict_translation_context(snapshot)
        settings_model = strict_glossary.build_strict_settings(
            app_settings.upstream,
            user_prompt,
            pages_str,
            strict_ctx,
        )
    except Exception as exc:
        coordinator.fail(job.job_id)
        stage = getattr(exc, "stage", "settings")
        cause_type = getattr(exc, "cause_type", type(exc).__name__)
        logger.error(
            "strict glossary prepare failed stage=%s cause=%s doc=%s",
            stage,
            cause_type,
            snapshot.pdf_hash[:12],
        )
        return error_response("术语词表准备失败，请查看服务端日志", 500, "glossary_prepare_failed")
    ctx = sse_stream.GenerateBatchContext(
        settings=settings_model,
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
        glossary_paths=(
            [str(strict_ctx.effective_glossary_path)] if strict_ctx.effective_glossary_path is not None else None
        ),
        cache_dir=app_settings.cache_dir,
        provider=app_settings.model_provider,
        model=app_settings.model,
        lang_in=app_settings.lang_in,
        lang_out=app_settings.lang_out,
        debug=app_settings.debug,
        register_stream=coordinator.register_stream,
        unregister_stream=coordinator.unregister_stream,
        strict_context=strict_ctx,
        candidate_service=_get_candidate_service(),
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


@bp.route("/api/config", methods=["GET"])
def get_config_center():
    denied = _loopback_config_guard()
    if denied is not None:
        return denied
    try:
        return jsonify(config_editor.load_config_state(_get_config_path()))
    except config_editor.ConfigEditError as exc:
        logger.warning("config center GET failed: code=%s", exc.code)
        return error_response(exc.message, 500, exc.code)


@bp.route("/api/config", methods=["PUT"])
def put_config_center():
    denied = _loopback_config_guard()
    if denied is not None:
        return denied
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error_response("请求体必须是 JSON 对象", 400, "invalid_payload")
    try:
        result = config_editor.save_config(data, _get_config_path())
    except config_editor.RevisionConflictError as exc:
        logger.warning("config center PUT conflict: code=%s", exc.code)
        return error_response(exc.message, 409, exc.code)
    except config_editor.ConfigEditError as exc:
        status = 500 if exc.code in ("config_read_failed", "config_write_failed") else 400
        logger.warning("config center PUT rejected: code=%s status=%d", exc.code, status)
        return error_response(exc.message, status, exc.code)
    logger.info("config center PUT saved")
    return jsonify(result)


@bp.route("/api/stages")
def get_stages():
    return jsonify(sse_stream.STAGE_LABELS)


@bp.route("/api/client-errors", methods=["POST"])
def client_errors():
    """受限的前端错误上报：仅本机来源 + 白名单字段，绝不记录请求体原文。"""
    if not _is_loopback_remote_addr(request.remote_addr):
        logger.warning(
            "client error report rejected from non-loopback remote_addr=%r",
            request.remote_addr,
        )
        return error_response("客户端错误上报仅允许本机访问", 403, "client_errors_local_only")

    if request.content_length is not None and request.content_length > _CLIENT_ERROR_MAX_BODY_BYTES:
        return error_response("客户端错误负载过大", 413, "payload_too_large")

    raw = request.get_data(cache=True)
    if len(raw) > _CLIENT_ERROR_MAX_BODY_BYTES:
        return error_response("客户端错误负载过大", 413, "payload_too_large")

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error_response("请求体必须是 JSON 对象", 400, "invalid_payload")
    unknown = set(data) - _CLIENT_ERROR_FIELDS
    if unknown:
        return error_response("请求体包含不支持的字段", 400, "invalid_payload")

    cleaned: dict[str, str | int] = {}
    for field, limit in _CLIENT_ERROR_STRING_LIMITS.items():
        value = data.get(field)
        if value is None:
            continue
        if not isinstance(value, str):
            return error_response("字段类型错误", 400, "invalid_payload")
        cleaned[field] = _clean_client_error_text(value, limit)
    for field in ("line", "column"):
        value = data.get(field)
        if value is None:
            continue
        coordinate = _clean_client_error_coordinate(value)
        if coordinate is None:
            return error_response("字段类型错误", 400, "invalid_payload")
        cleaned[field] = coordinate

    if not cleaned:
        return error_response("至少需要一个上报字段", 400, "invalid_payload")
    if not (cleaned.get("message") or cleaned.get("stack")):
        return error_response("message 或 stack 不能为空", 400, "invalid_payload")

    client_logger.warning(
        "client error kind=%r source=%r line=%s column=%s message=%r stack=%r",
        cleaned.get("kind", "browser_error"),
        cleaned.get("source", ""),
        cleaned.get("line", "-"),
        cleaned.get("column", "-"),
        cleaned.get("message", ""),
        cleaned.get("stack", ""),
    )
    return jsonify({"ok": True}), 202


@bp.app_errorhandler(404)
def not_found(e):
    return jsonify({"code": "not_found", "error": "not found"}), 404


@bp.app_errorhandler(HTTPException)
def http_error(exc: HTTPException):
    status = exc.code or 500
    if status == 500:
        logger.error(
            "HTTP error 500 while processing %s %s",
            request.method,
            request.path,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
    else:
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
    """注册 blueprint 并消费已注入的 ``app_settings``。

    生产装配路径由 ``create_app(settings)`` 先写入 ``app.config["app_settings"]``，
    本函数只读取该值，绝不因此重建配置。兼容 fallback 仅在 key 真正缺失
    （例如测试直接构造 Flask 后调用本函数）时惰性执行 ``config.build_app_settings()``，
    key 已存在时不会触碰配置模块全局。
    """
    if "app_settings" not in app.config:
        app.config["app_settings"] = config.build_app_settings()
    app.config.setdefault("translation_coordinator", TranslationCoordinator())
    app.config.setdefault("candidate_extraction_service", None)
    app.register_blueprint(bp)
