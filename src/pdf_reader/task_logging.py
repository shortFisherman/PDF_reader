"""任务级日志上下文与敏感信息脱敏（P2-06）。

集中约定：

- 任务日志统一由 :func:`task_log` 输出，稳定前缀格式：
  ``[job=<完整 job_id> doc=<8 字符> hash=<12 字符> page=N|pages=A-B status=<状态>]``。
- 页码一律 1-based：单页 ``page=N``，批量 ``pages=A-B``（A==B 时 ``pages=N``）。
- 截断长度：``document_id`` 8 字符，``pdf hash`` 12 字符。
- 生命周期状态：created、started、client_disconnected、cancelling、finished、
  failed、discarded、cleaned；join timeout 时使用额外状态 cleanup_deferred，
  绝不错误声称 cleaned。coordinator 释放语义保留 cancelled。
- 上下文通过 ``contextvars`` 在当前执行链传播；后台 worker 线程必须显式
  :func:`set_current_task`，不能依赖请求线程的字段。
- 控制台与 ``logs/pdf_reader.log`` 使用 :class:`SafeFormatter` 在格式化边界
  脱敏 API Key 与常见 token（``sk-...``、Authorization/Bearer、api_key 字段）；
  traceback 结构保留，秘密值被替换。路径/HTML 属于服务端诊断内容，保留。
"""

import logging
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace

DOCUMENT_ID_LOG_LENGTH = 8
PDF_HASH_LOG_LENGTH = 12

STATUS_CREATED = "created"
STATUS_STARTED = "started"
STATUS_CLIENT_DISCONNECTED = "client_disconnected"
STATUS_CANCELLING = "cancelling"
STATUS_FINISHED = "finished"
STATUS_FAILED = "failed"
STATUS_DISCARDED = "discarded"
STATUS_CLEANED = "cleaned"
STATUS_CLEANUP_DEFERRED = "cleanup_deferred"
STATUS_CANCELLED = "cancelled"

_REDACTED = "***REDACTED***"
_CREDENTIAL_REDACTED = "<redacted>"
_SK_TOKEN = re.compile(r"\bsk-[A-Za-z0-9_\-]{4,}\b")
_AUTH_BEARER = re.compile(r"(?i)(authorization[\"']?\s*[:=]\s*[\"']?(?:bearer\s+)?)[A-Za-z0-9._~+/=_-]+")
_API_KEY_FIELD = re.compile(r"(?i)(api_key[\"']?\s*[:=]\s*[\"']?)[^\"'\s,}]+")
_STANDALONE_BEARER = re.compile(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/=_-]{8,}")


@dataclass(frozen=True)
class TaskContext:
    """不可变任务日志上下文。document_id/pdf_hash 均为截断后的展示值。"""

    job_id: str
    document_id: str
    pdf_hash: str
    page: int | None = None
    from_page: int | None = None
    to_page: int | None = None
    status: str = STATUS_STARTED

    def __post_init__(self) -> None:
        """中心截断不变量：无论调用方传入多长的值，日志上下文只保留截断形式。"""
        object.__setattr__(self, "document_id", truncate_document_id(self.document_id))
        object.__setattr__(self, "pdf_hash", truncate_pdf_hash(self.pdf_hash))


_current_task: ContextVar[TaskContext | None] = ContextVar("pdf_reader_current_task", default=None)


def get_current_task() -> TaskContext | None:
    return _current_task.get()


def set_current_task(ctx: TaskContext | None) -> None:
    _current_task.set(ctx)


@contextmanager
def task_log_context(ctx: TaskContext | None) -> Iterator[None]:
    token = _current_task.set(ctx)
    try:
        yield
    finally:
        _current_task.reset(token)


def truncate_document_id(value: str) -> str:
    return value[:DOCUMENT_ID_LOG_LENGTH] if value else "-"


def truncate_pdf_hash(value: str) -> str:
    return value[:PDF_HASH_LOG_LENGTH] if value else "-"


def pages_label(ctx: TaskContext) -> str:
    if ctx.page is not None:
        return f"page={ctx.page}"
    if ctx.from_page is not None and ctx.to_page is not None:
        if ctx.from_page == ctx.to_page:
            return f"pages={ctx.from_page}"
        return f"pages={ctx.from_page}-{ctx.to_page}"
    return ""


def with_status(ctx: TaskContext | None, status: str) -> TaskContext | None:
    if ctx is None:
        return None
    return replace(ctx, status=status)


def task_context_from_indices(
    job_id: str,
    document_id: str,
    pdf_hash: str,
    page_indices: list[int] | tuple[int, ...],
    status: str = STATUS_STARTED,
) -> TaskContext:
    """从 0-based 页码列表构造 1-based 日志上下文。"""
    indices = list(page_indices or [])
    if not indices:
        return TaskContext(
            job_id=job_id,
            document_id=truncate_document_id(document_id),
            pdf_hash=truncate_pdf_hash(pdf_hash),
            status=status,
        )
    if len(indices) == 1 or min(indices) == max(indices):
        return TaskContext(
            job_id=job_id,
            document_id=truncate_document_id(document_id),
            pdf_hash=truncate_pdf_hash(pdf_hash),
            page=min(indices) + 1,
            status=status,
        )
    return TaskContext(
        job_id=job_id,
        document_id=truncate_document_id(document_id),
        pdf_hash=truncate_pdf_hash(pdf_hash),
        from_page=min(indices) + 1,
        to_page=max(indices) + 1,
        status=status,
    )


def task_log(
    logger: logging.Logger,
    level: int,
    message: str,
    *args: object,
    task: TaskContext | None = None,
    exc_info: bool | BaseException | None = None,
) -> None:
    """输出任务日志；有上下文时加统一前缀，无上下文时保持可读原样。"""
    ctx = task if task is not None else _current_task.get()
    if ctx is not None:
        fields = [f"job={ctx.job_id}", f"doc={ctx.document_id}", f"hash={ctx.pdf_hash}"]
        label = pages_label(ctx)
        if label:
            fields.append(label)
        fields.append(f"status={ctx.status}")
        message = f"[{' '.join(fields)}] {message}"
    if exc_info is not None:
        logger.log(level, message, *args, exc_info=exc_info)
    else:
        logger.log(level, message, *args)


def _configured_secrets() -> set[str]:
    secrets: set[str] = set()
    try:
        from pdf_reader import config

        if config.MODEL_API_KEY:
            secrets.add(config.MODEL_API_KEY)
    except Exception:
        pass
    env_key = os.environ.get("MODEL_API_KEY")
    if env_key:
        secrets.add(env_key)
    return secrets


def redact_secrets(text: str) -> str:
    for secret in _configured_secrets():
        if secret:
            text = text.replace(secret, _REDACTED)
    text = _SK_TOKEN.sub(_REDACTED, text)
    text = _AUTH_BEARER.sub(lambda match: match.group(1) + _CREDENTIAL_REDACTED, text)
    text = _API_KEY_FIELD.sub(lambda match: match.group(1) + _CREDENTIAL_REDACTED, text)
    text = _STANDALONE_BEARER.sub(lambda match: match.group(1) + _CREDENTIAL_REDACTED, text)
    return text


class SafeFormatter(logging.Formatter):
    """在格式化边界脱敏密钥；traceback 结构保留。"""

    def format(self, record: logging.LogRecord) -> str:
        return redact_secrets(super().format(record))
