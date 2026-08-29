import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

logger = logging.getLogger("pdf_reader.translate")


@dataclass(frozen=True)
class TranslationJob:
    job_id: str
    document_id: str
    page_indices: tuple[int, ...]
    created_at: datetime
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

    def start(self, document_id: str, page_indices: list[int] | tuple[int, ...]) -> TranslationJob:
        with self._lock:
            if self._active_job is not None:
                raise TranslationBusyError(self._active_job)
            job = TranslationJob(
                job_id=uuid4().hex,
                document_id=document_id,
                page_indices=tuple(page_indices),
                created_at=datetime.now(UTC),
            )
            self._active_job = job
            logger.info(
                "[job=%s] started document_id=%s pages=%s",
                job.job_id,
                job.document_id,
                job.page_indices,
            )
            return job

    def finish(self, job_id: str) -> bool:
        return self._release(job_id, "finished")

    def fail(self, job_id: str) -> bool:
        return self._release(job_id, "failed")

    def _release(self, job_id: str, outcome: str) -> bool:
        with self._lock:
            if self._active_job is None or self._active_job.job_id != job_id:
                logger.debug("[job=%s] ignored duplicate or stale %s release", job_id, outcome)
                return False
            job = self._active_job
            self._active_job = None
            logger.info(
                "[job=%s] %s document_id=%s pages=%s",
                job.job_id,
                outcome,
                job.document_id,
                job.page_indices,
            )
            return True
