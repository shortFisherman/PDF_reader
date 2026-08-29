import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from pdf_reader.task_logging import (
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


class TranslationCoordinator:
    """Thread-safe single-slot coordinator for document-mutating translation jobs."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active_job: TranslationJob | None = None

    @property
    def active_job(self) -> TranslationJob | None:
        with self._lock:
            return self._active_job

    @property
    def is_busy(self) -> bool:
        with self._lock:
            return self._active_job is not None

    def start(
        self,
        document_id: str,
        page_indices: list[int] | tuple[int, ...],
        pdf_hash: str | None = None,
    ) -> TranslationJob:
        with self._lock:
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
