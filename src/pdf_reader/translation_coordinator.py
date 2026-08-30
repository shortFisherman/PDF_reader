import logging
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from pdf_reader.task_logging import (
    STATUS_CANCELLING,
    STATUS_CREATED,
    STATUS_STARTED,
    task_context_from_indices,
    task_log,
)

logger = logging.getLogger("pdf_reader.translate")


@dataclass(frozen=True)
class TranslationJob:
    job_id: str
    document_id: str
    page_indices: tuple[int, ...]
    created_at: datetime
    pdf_hash: str | None = None
    status: str = "active"


class TranslationBusyError(RuntimeError):
    def __init__(self, active_job: TranslationJob) -> None:
        super().__init__("translation already in progress")
        self.active_job = active_job


class CoordinatorShutdownError(RuntimeError):
    """协调器已进入关闭流程，不再接受新任务。"""


@dataclass(frozen=True)
class ShutdownReport:
    """main 关闭协调结果：完成/超时/无任务 + worker 是否确认退出。"""

    outcome: str  # "no_active_job" | "completed" | "timeout"
    active_job_id: str | None
    worker_joined: bool


class TranslationCoordinator:
    """Thread-safe single-slot coordinator for document-mutating translation jobs."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active_job: TranslationJob | None = None
        self._closed = False
        self._streams: dict[str, object] = {}

    @property
    def active_job(self) -> TranslationJob | None:
        with self._lock:
            return self._active_job

    @property
    def is_busy(self) -> bool:
        with self._lock:
            return self._active_job is not None

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def start(
        self,
        document_id: str,
        page_indices: list[int] | tuple[int, ...],
        pdf_hash: str | None = None,
    ) -> TranslationJob:
        with self._lock:
            if self._closed:
                raise CoordinatorShutdownError("coordinator is shutting down")
            if self._active_job is not None:
                raise TranslationBusyError(self._active_job)
            job = TranslationJob(
                job_id=uuid4().hex,
                document_id=document_id,
                page_indices=tuple(page_indices),
                created_at=datetime.now(UTC),
                pdf_hash=pdf_hash,
            )
            self._active_job = job
            created_ctx = task_context_from_indices(
                job.job_id,
                job.document_id,
                job.pdf_hash or "",
                job.page_indices,
                status=STATUS_CREATED,
            )
            task_log(logger, logging.INFO, "translation job created", task=created_ctx)
            task_log(
                logger,
                logging.INFO,
                "translation job started",
                task=task_context_from_indices(
                    job.job_id,
                    job.document_id,
                    job.pdf_hash or "",
                    job.page_indices,
                    status=STATUS_STARTED,
                ),
            )
            return job

    def finish(self, job_id: str) -> bool:
        return self._release(job_id, "finished")

    def fail(self, job_id: str) -> bool:
        return self._release(job_id, "failed")

    def cancel(self, job_id: str) -> bool:
        return self._release(job_id, "cancelled")

    def register_stream(self, job_id: str, stream: object) -> None:
        """登记 worker 流供关闭流程协作式取消；关闭后登记为 no-op。"""
        with self._lock:
            if self._closed:
                return
            self._streams[job_id] = stream

    def unregister_stream(self, job_id: str) -> None:
        with self._lock:
            self._streams.pop(job_id, None)

    def shutdown(self, timeout: float = 10.0) -> ShutdownReport:
        """有界关闭：拒绝新任务、请求协作式取消并等待 worker 与 active job 释放。

        不 kill 任何线程；worker 不响应取消时保留其临时目录（由启动恢复处理）。
        """
        with self._lock:
            if self._closed:
                job = self._active_job
                return ShutdownReport(
                    outcome="no_active_job" if job is None else "timeout",
                    active_job_id=job.job_id if job is not None else None,
                    worker_joined=not any(getattr(s, "is_alive", False) for s in self._streams.values()),
                )
            self._closed = True
            streams = list(self._streams.values())
            job = self._active_job
            shutdown_ctx = (
                task_context_from_indices(
                    job.job_id,
                    job.document_id,
                    job.pdf_hash or "",
                    job.page_indices,
                    status=STATUS_CANCELLING,
                )
                if job is not None
                else None
            )

        deadline = time.monotonic() + max(0.0, timeout)
        for stream in streams:
            try:
                stream.cancel()  # type: ignore[attr-defined]
            except Exception:
                task_log(
                    logger,
                    logging.ERROR,
                    "stream cancel failed",
                    task=shutdown_ctx,
                    exc_info=True,
                )
        for stream in streams:
            remaining = max(0.0, deadline - time.monotonic())
            try:
                stream.join(timeout=remaining)  # type: ignore[attr-defined]
            except Exception:
                task_log(
                    logger,
                    logging.ERROR,
                    "stream join failed",
                    task=shutdown_ctx,
                    exc_info=True,
                )
        worker_joined = not any(getattr(stream, "is_alive", False) for stream in streams)

        while self._active_job is not None and time.monotonic() < deadline:
            time.sleep(0.05)

        with self._lock:
            still_active = self._active_job
        if job is None:
            outcome = "no_active_job"
        elif still_active is None:
            outcome = "completed"
        else:
            outcome = "timeout"
        return ShutdownReport(
            outcome=outcome,
            active_job_id=job.job_id if job is not None else None,
            worker_joined=worker_joined,
        )

    def _release(self, job_id: str, outcome: str) -> bool:
        with self._lock:
            if self._active_job is None or self._active_job.job_id != job_id:
                # 重复/迟到释放没有完整已知上下文，静默，避免产出缺 doc/hash/pages 的半截任务日志。
                return False
            job = self._active_job
            self._active_job = None
            ctx = task_context_from_indices(
                job.job_id,
                job.document_id,
                job.pdf_hash or "",
                job.page_indices,
                status=outcome,
            )
            task_log(logger, logging.INFO, f"translation job {outcome}", task=ctx)
            return True
