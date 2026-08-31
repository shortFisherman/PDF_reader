"""P1-01 候选提取服务：正文翻译成功提交后的旁路运行器。

不变量：
- 只在调用方确认正文已经最终验证并提交成功后运行；正文失败路径不会调用本服务；
- 候选只写入 ``term_candidates.json``（``CandidateStore``），绝不写
  user/effective/global 权威词表，也不改变正文 ``SettingsModel``；
- 网络/解析/存储失败全部降级为安全日志，不阻止正文 ``finish``；
- 常规日志只记录 provider/状态/数量/页码等稳定字段，不记录全文、Prompt、
  target、路径、API Key 或响应正文。
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from pdf_reader.candidate_store import CandidateObservation, CandidateStore
from pdf_reader.config import CandidateExtractionRuntimeConfig, ModelRuntimeConfig
from pdf_reader.task_logging import TaskContext, task_log
from pdf_reader.term_extraction import STRATEGY_VERSION, TermExtractionClient, TermExtractionError
from pdf_reader.term_model import TermStoreError

logger = logging.getLogger("pdf_reader.candidate")


@dataclass(frozen=True)
class CandidateExtractionReport:
    """一次候选提取的稳定摘要；正文成功语义不依赖本结果。"""

    status: str
    candidates: int = 0
    pages: tuple[int, ...] = ()


class CandidateExtractionService:
    """正文提交后的旁路候选提取服务（同步首版，严格 timeout，无悬挂线程）。"""

    def __init__(
        self,
        cfg: CandidateExtractionRuntimeConfig,
        model_cfg: ModelRuntimeConfig,
    ) -> None:
        self._cfg = cfg
        self._provider = model_cfg.provider
        self._client = TermExtractionClient(model_cfg, cfg)
        self._semaphore = threading.BoundedSemaphore(cfg.max_workers)

    def run_for_pdf(
        self,
        pdf_path: str | Path,
        page_indices: list[int] | tuple[int, ...],
        document_dir: Path | None,
        task_ctx: TaskContext | None = None,
    ) -> CandidateExtractionReport:
        """从已抽取的真实源 PDF 提取候选并原子写入候选存储。"""
        with self._semaphore:
            return self._run(pdf_path, page_indices, document_dir, task_ctx)

    def _run(
        self,
        pdf_path: str | Path,
        page_indices: list[int] | tuple[int, ...],
        document_dir: Path | None,
        task_ctx: TaskContext | None,
    ) -> CandidateExtractionReport:
        if not self._cfg.enabled:
            task_log(logger, logging.DEBUG, "candidate extraction skipped: disabled", task=task_ctx)
            return CandidateExtractionReport(status="disabled")
        if not self._client.supported:
            task_log(
                logger,
                logging.WARNING,
                "candidate extraction unsupported: provider=%s",
                self._provider,
                task=task_ctx,
            )
            return CandidateExtractionReport(status="unsupported")

        try:
            text, pages = self._read_source_text(pdf_path, page_indices)
        except Exception as exc:
            task_log(
                logger,
                logging.WARNING,
                "candidate source extraction failed: reason=%s",
                type(exc).__name__,
                task=task_ctx,
            )
            return CandidateExtractionReport(status="source_failed")
        if not text.strip():
            task_log(
                logger,
                logging.INFO,
                "candidate extraction skipped: empty source pages=%s",
                pages,
                task=task_ctx,
            )
            return CandidateExtractionReport(status="empty", pages=pages)

        truncated = len(text) > self._cfg.max_input_chars
        if truncated:
            # 确定性有界策略：超限时保留前缀，不随机/不按行猜测边界。
            text = text[: self._cfg.max_input_chars]
        try:
            candidates = self._client.extract_terms(text)
        except TermExtractionError as exc:
            task_log(
                logger,
                logging.WARNING,
                "candidate extraction failed: reason=%s",
                type(exc).__name__,
                task=task_ctx,
            )
            return CandidateExtractionReport(status="failed", pages=pages)
        except Exception as exc:
            task_log(
                logger,
                logging.WARNING,
                "candidate extraction failed: reason=%s",
                type(exc).__name__,
                task=task_ctx,
            )
            return CandidateExtractionReport(status="failed", pages=pages)
        if not candidates:
            task_log(
                logger,
                logging.INFO,
                "candidate extraction done: no candidates pages=%s",
                pages,
                task=task_ctx,
            )
            return CandidateExtractionReport(status="no_candidates", pages=pages)

        observations = [
            CandidateObservation(source=candidate.source, target=candidate.target, pages=pages)
            for candidate in candidates
        ]
        try:
            if document_dir is None:
                raise TermStoreError("missing document cache dir")
            CandidateStore(document_dir).record_observations(
                observations,
                strategy_version=STRATEGY_VERSION,
            )
        except TermStoreError as exc:
            task_log(
                logger,
                logging.WARNING,
                "candidate store write failed: reason=%s",
                type(exc).__name__,
                task=task_ctx,
            )
            return CandidateExtractionReport(status="store_failed", pages=pages)
        except Exception as exc:
            task_log(
                logger,
                logging.WARNING,
                "candidate store write failed: reason=%s",
                type(exc).__name__,
                task=task_ctx,
            )
            return CandidateExtractionReport(status="store_failed", pages=pages)

        task_log(
            logger,
            logging.INFO,
            "candidate extraction done: candidates=%d pages=%s truncated=%s",
            len(candidates),
            pages,
            truncated,
            task=task_ctx,
        )
        return CandidateExtractionReport(status="ok", candidates=len(candidates), pages=pages)

    @staticmethod
    def _read_source_text(
        pdf_path: str | Path,
        page_indices: list[int] | tuple[int, ...],
    ) -> tuple[str, tuple[int, ...]]:
        """用 PyMuPDF 读取已抽取局部 PDF 的源文本。

        ``pdf_path`` 是仅含本次任务页的局部 PDF（页索引 0..k-1），
        ``page_indices`` 是原文 0-based 页索引。必须按局部索引读取，并按
        原文索引 +1 记录 1-based 证据页；局部 PDF 页数与请求页数不一致时
        拒绝读取（由调用方降级为 source_failed）。
        """
        doc = pymupdf.open(str(pdf_path))
        try:
            if doc.page_count != len(page_indices):
                raise ValueError("extracted pdf page count mismatch")
            parts: list[str] = []
            pages: list[int] = []
            for local_index, original_index in enumerate(page_indices):
                if isinstance(original_index, bool) or not isinstance(original_index, int) or original_index < 0:
                    raise ValueError("invalid page index")
                page_text = doc[local_index].get_text()
                if page_text.strip():
                    parts.append(page_text)
                    pages.append(original_index + 1)
            return "\n".join(parts), tuple(sorted(set(pages)))
        finally:
            doc.close()
