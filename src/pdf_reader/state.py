import json
import logging
import os
import shutil
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar, cast
from uuid import uuid4

import pymupdf

from pdf_reader.task_logging import (
    STATUS_DISCARDED,
    get_current_task,
    task_log,
    truncate_document_id,
    truncate_pdf_hash,
    with_status,
)

logger = logging.getLogger("pdf_reader.state")
T = TypeVar("T")


class StaleDocumentError(RuntimeError):
    """Raised when work tries to mutate a document session that is no longer current."""


@dataclass(frozen=True)
class DocumentSnapshot:
    document_id: str
    pdf_hash: str
    page_count: int
    glossary_cache_path: Path


class AppState:
    def __init__(self, cache_dir: Path) -> None:
        self._lock = threading.Lock()
        self._cache_dir = cache_dir
        self._closed = False
        self._left_doc: pymupdf.Document | None = None
        self._right_doc: pymupdf.Document | None = None
        self._right_pdf_path: str | None = None
        self._pdf_path: str | None = None
        self._pdf_hash: str | None = None
        self._document_id: str | None = None
        self._page_count: int = 0
        self._page_height: float = 0.0
        self._page_width: float = 0.0
        self._translated_pages: set[int] = set()

    @property
    def pdf_path(self) -> str | None:
        return self._pdf_path

    @property
    def pdf_hash(self) -> str | None:
        return self._pdf_hash

    @property
    def left_doc(self) -> pymupdf.Document | None:
        return self._left_doc

    @property
    def right_doc(self) -> pymupdf.Document | None:
        return self._right_doc

    @property
    def page_count(self) -> int:
        return self._page_count

    @property
    def page_height(self) -> float:
        return self._page_height

    @property
    def page_width(self) -> float:
        return self._page_width

    @property
    def translated_pages(self) -> frozenset[int]:
        return frozenset(self._translated_pages)

    @property
    def glossary_cache_path(self) -> Path | None:
        if self._pdf_hash is None:
            return None
        return self._cache_dir / self._pdf_hash

    def _reading_progress_path(self) -> Path | None:
        if self._pdf_hash is None:
            return None
        return self._cache_dir / self._pdf_hash / "reading_progress.json"

    def translation_snapshot(self) -> DocumentSnapshot:
        with self._lock:
            if self._left_doc is None or self._document_id is None or self._pdf_hash is None:
                raise ValueError("no document opened")
            return DocumentSnapshot(
                document_id=self._document_id,
                pdf_hash=self._pdf_hash,
                page_count=self._page_count,
                glossary_cache_path=self._cache_dir / self._pdf_hash,
            )

    def _require_document_locked(self, expected_document_id: str) -> None:
        if (
            self._document_id != expected_document_id
            or self._left_doc is None
            or self._right_doc is None
            or self._right_pdf_path is None
            or self._pdf_hash is None
        ):
            task_log(
                logger,
                logging.WARNING,
                "[stale-result] rejected expected_document_id=%s current_document_id=%s",
                truncate_document_id(expected_document_id),
                truncate_document_id(self._document_id or ""),
                task=with_status(get_current_task(), STATUS_DISCARDED),
            )
            raise StaleDocumentError("stale translation result rejected")

    def save_reading_progress(self, page: int) -> None:
        with self._lock:
            if self._left_doc is None or self._pdf_hash is None:
                raise ValueError("no document opened")
            if not isinstance(page, int) or isinstance(page, bool):
                raise ValueError("page out of range")
            if page < 0 or page >= self._page_count:
                raise ValueError("page out of range")
            path = self._reading_progress_path()
            if path is None:
                raise ValueError("no document opened")
            tmp = path.with_suffix(path.suffix + ".tmp")
            try:
                tmp.write_text(json.dumps({"page": page}), encoding="utf-8")
                os.replace(tmp, path)
                logger.info("[progress] save hash=%s page=%d", truncate_pdf_hash(self._pdf_hash), page)
            except Exception:
                if tmp.exists():
                    try:
                        tmp.unlink()
                    except OSError:
                        pass
                logger.error(
                    "[progress] save failed hash=%s page=%d",
                    truncate_pdf_hash(self._pdf_hash),
                    page,
                    exc_info=True,
                )
                raise

    def load_reading_progress(self) -> int | None:
        path = self._reading_progress_path()
        if path is None or not path.exists():
            logger.debug("[progress] load hash=%s none", truncate_pdf_hash(self._pdf_hash or ""))
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            page = data["page"]
            if not isinstance(page, int) or isinstance(page, bool):
                logger.debug("[progress] load hash=%s none (bad type)", truncate_pdf_hash(self._pdf_hash or ""))
                return None
            if page >= self._page_count or page < 0:
                logger.debug("[progress] load hash=%s clamp=%d", truncate_pdf_hash(self._pdf_hash or ""), page)
                return 0
            logger.debug("[progress] load hash=%s page=%d", truncate_pdf_hash(self._pdf_hash or ""), page)
            return page
        except Exception:
            logger.debug(
                "[progress] load hash=%s none (corrupt)",
                truncate_pdf_hash(self._pdf_hash or ""),
                exc_info=True,
            )
            return None

    def open_pdf(self, pdf_path: str, sha256_func) -> dict:
        with self._lock:
            if self._closed:
                raise RuntimeError("AppState closed")
            self._close_docs()
            pdf_hash = sha256_func(pdf_path)
            cache_subdir = self._cache_dir / pdf_hash
            cache_subdir.mkdir(parents=True, exist_ok=True)
            right_pdf_path = cache_subdir / "right.pdf"
            cache_status = "reused" if right_pdf_path.exists() else "new"
            if cache_status == "new":
                shutil.copy2(pdf_path, right_pdf_path)
            self._left_doc = pymupdf.open(pdf_path)
            self._right_doc = pymupdf.open(str(right_pdf_path))
            self._pdf_path = pdf_path
            self._pdf_hash = pdf_hash
            self._right_pdf_path = str(right_pdf_path)
            self._document_id = uuid4().hex
            self._page_count = self._left_doc.page_count
            sample_page = self._left_doc[0]
            self._page_height = sample_page.rect.height
            self._page_width = sample_page.rect.width
            logger.info(
                "[open] hash=%s pages=%d dim=%.0fx%.0f cache=%s",
                truncate_pdf_hash(pdf_hash),
                self._page_count,
                self._page_width,
                self._page_height,
                cache_status,
            )
            saved_page = self.load_reading_progress()
            return {
                "page_count": self._page_count,
                "page_height": self._page_height,
                "page_width": self._page_width,
                "hash": pdf_hash,
                "document_id": self._document_id,
                "saved_page": saved_page,
            }

    def get_doc(self, side: str) -> pymupdf.Document | None:
        with self._lock:
            return self._left_doc if side == "left" else self._right_doc

    def render_page(self, side: str, page_num: int, render_func, dpi: int) -> bytes:
        """Render a page under the state lock. render_func must not reenter AppState (non-reentrant lock)."""
        with self._lock:
            doc = self._left_doc if side == "left" else self._right_doc
            if doc is None:
                raise ValueError("no document opened")
            return cast(bytes, render_func(doc, page_num, dpi))

    def extract_page(
        self,
        page: int,
        tmpdir: Path,
        extract_func,
        expected_document_id: str | None = None,
    ) -> Path:
        """Extract a single page under the state lock.
        extract_func must not reenter AppState (non-reentrant lock)."""
        with self._lock:
            if expected_document_id is not None:
                self._require_document_locked(expected_document_id)
            if self._left_doc is None:
                raise ValueError("no document opened")
            return cast(Path, extract_func(self._left_doc, page, tmpdir))

    def replace_page(self, translated_pdf_path: str, page_num: int, expected_document_id: str) -> None:
        with self._lock:
            self._require_document_locked(expected_document_id)
            try:
                self._commit_replacement(translated_pdf_path, [page_num])
                task_log(logger, logging.INFO, "page=%d replace into %s", page_num + 1, self._right_pdf_path)
            except Exception:
                task_log(logger, logging.ERROR, "page=%d replace failed", page_num + 1, exc_info=True)
                raise

    def extract_pages(
        self,
        page_indices: list[int],
        tmpdir: Path,
        extract_func,
        expected_document_id: str | None = None,
    ) -> Path:
        """Extract multiple pages under the state lock.
        extract_func must not reenter AppState (non-reentrant lock)."""
        with self._lock:
            if expected_document_id is not None:
                self._require_document_locked(expected_document_id)
            if self._left_doc is None:
                raise ValueError("no document opened")
            return cast(Path, extract_func(self._left_doc, page_indices, tmpdir))

    def replace_pages(
        self,
        translated_pdf_path: str,
        page_indices: list[int],
        expected_document_id: str,
    ) -> None:
        with self._lock:
            self._require_document_locked(expected_document_id)
            try:
                self._commit_replacement(translated_pdf_path, page_indices)
                pages = f"{min(page_indices) + 1}-{max(page_indices) + 1}"
                task_log(logger, logging.INFO, "pages=%s replace into %s", pages, self._right_pdf_path)
            except Exception:
                pages = f"{min(page_indices) + 1}-{max(page_indices) + 1}"
                task_log(logger, logging.ERROR, "pages=%s replace pages failed", pages, exc_info=True)
                raise

    def _commit_replacement(self, translated_pdf_path: str, page_indices: list[int]) -> None:
        """Atomic page replacement. Caller must hold the state lock.

        All page mutations happen on a work copy opened from the last
        committed right.pdf; the temp file is fully closed before the atomic
        rename. The live document handle and _translated_pages are swapped
        only after the disk commit succeeds. On failure the previously
        committed right.pdf stays in place, the memory handle is restored or
        kept usable, the temp file is removed and every opened PyMuPDF
        document is closed.
        """
        right_pdf_path = self._right_pdf_path
        if right_pdf_path is None:
            raise ValueError("no document opened")
        src_doc: pymupdf.Document | None = None
        work_doc: pymupdf.Document | None = None
        old_doc: pymupdf.Document | None = None
        tmp_save = right_pdf_path + ".tmp"
        committed = False
        try:
            src_doc = pymupdf.open(translated_pdf_path)
            work_doc = pymupdf.open(right_pdf_path)
            for j, idx in enumerate(page_indices):
                work_doc.delete_page(idx)
                work_doc.insert_pdf(src_doc, start_at=idx, from_page=j, to_page=j)
            work_doc.save(tmp_save)
            src_doc.close()
            src_doc = None
            work_doc.close()
            work_doc = None
            old_doc = self._right_doc
            self._right_doc = None
            if old_doc is not None:
                old_doc.close()
            os.replace(tmp_save, right_pdf_path)
            committed = True
            self._right_doc = pymupdf.open(right_pdf_path)
            self._translated_pages.update(page_indices)
        except Exception:
            if self._right_doc is None:
                try:
                    self._right_doc = pymupdf.open(right_pdf_path)
                    if committed:
                        self._translated_pages.update(page_indices)
                except Exception:
                    task_log(
                        logger,
                        logging.ERROR,
                        "[replace] reopen %s after failure failed",
                        right_pdf_path,
                        exc_info=True,
                    )
            for doc in (src_doc, work_doc, old_doc):
                if doc is not None and not doc.is_closed:
                    try:
                        doc.close()
                    except Exception:
                        pass
            if os.path.exists(tmp_save):
                try:
                    os.unlink(tmp_save)
                except OSError:
                    pass
            raise

    def merge_glossary(
        self,
        extracted_glossary_path: str | Path | None,
        expected_document_id: str,
        merge_func: Callable[[Path | None, str | Path | None], T],
    ) -> T:
        """Merge glossary output while identity and the document lock remain stable."""
        with self._lock:
            self._require_document_locked(expected_document_id)
            assert self._pdf_hash is not None
            cumulative_path = self._cache_dir / self._pdf_hash / "cumulative_glossary.csv"
            return merge_func(cumulative_path, extracted_glossary_path)

    def with_document_cache(
        self,
        expected_document_id: str,
        operation: Callable[[Path], T],
    ) -> T:
        """在文档身份与状态锁保持稳定时执行一次文档缓存操作。"""
        with self._lock:
            self._require_document_locked(expected_document_id)
            assert self._pdf_hash is not None
            return operation(self._cache_dir / self._pdf_hash)

    def is_doc_open(self) -> bool:
        return self._left_doc is not None

    def is_closed(self) -> bool:
        with self._lock:
            return self._closed

    def close(self) -> None:
        """幂等关闭：释放左右 PyMuPDF 句柄并清空全部状态；关闭后不可再 open。"""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._close_docs()
            self._right_pdf_path = None
            self._pdf_path = None
            self._pdf_hash = None
            self._page_count = 0
            self._page_height = 0.0
            self._page_width = 0.0

    def _close_docs(self) -> None:
        self._document_id = None
        if self._left_doc:
            self._left_doc.close()
            self._left_doc = None
        if self._right_doc:
            self._right_doc.close()
            self._right_doc = None
        self._translated_pages.clear()
