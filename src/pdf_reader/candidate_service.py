"""P1-01/P1-02 候选提取服务：正文翻译成功提交后的旁路运行器。

不变量：
- 只在调用方确认正文已经最终验证并提交成功后运行；正文失败路径不会调用本服务；
- 候选只写入 ``term_candidates.json``（``CandidateStore``），绝不写
  user/effective/global 权威词表，也不改变正文 ``SettingsModel``；
- P1-02 起，模型候选先经 ``candidate_filter`` 确定性后置过滤：普通词/幻觉/
  格式异常被拒绝，保留候选必须携带实际命中页与有界源文证据；过滤只作用于
  自动候选，绝不删除、降级或重写用户 authoritative/locked/accepted 决定；
- 网络/解析/存储失败全部降级为安全日志，不阻止正文 ``finish``；
- 常规日志只记录 provider/状态/数量/页码/过滤原因计数等稳定字段，不记录
  source、target、证据、全文、Prompt、路径、API Key 或响应正文。
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from pdf_reader.candidate_filter import (
    CANDIDATE_STRATEGY_VERSION,
    FilteredCandidate,
    filter_candidates,
)
from pdf_reader.candidate_store import CandidateObservation, CandidateStore
from pdf_reader.config import CandidateExtractionRuntimeConfig, ModelRuntimeConfig
from pdf_reader.task_logging import TaskContext, task_log
from pdf_reader.term_extraction import TermExtractionClient, TermExtractionError
from pdf_reader.term_model import (
    CandidateSuggestionSummary,
    CandidateTargetSummary,
    TermStoreError,
)

logger = logging.getLogger("pdf_reader.candidate")


@dataclass(frozen=True)
class CandidateExtractionReport:
    """一次候选提取的稳定摘要；正文成功语义不依赖本结果。"""

    status: str
    candidates: int = 0
    pages: tuple[int, ...] = ()
    filtered: int = 0
    filtered_by_reason: tuple[tuple[str, int], ...] = ()


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
            page_texts = self._read_source_text(pdf_path, page_indices)
        except Exception as exc:
            task_log(
                logger,
                logging.WARNING,
                "candidate source extraction failed: reason=%s",
                type(exc).__name__,
                task=task_ctx,
            )
            return CandidateExtractionReport(status="source_failed")
        if not page_texts:
            task_log(
                logger,
                logging.INFO,
                "candidate extraction skipped: empty source",
                task=task_ctx,
            )
            return CandidateExtractionReport(status="empty")

        pages = tuple(sorted({page for page, _ in page_texts}))
        full_text = "\n".join(text for _, text in page_texts)
        truncated = len(full_text) > self._cfg.max_input_chars
        # 确定性有界策略：超限时保留前缀，不随机/不按行猜测边界；逐页截断块
        # 与送给模型的 sent_text 完全一致，保证页码/证据只来自实际输入。
        sent_text = full_text[: self._cfg.max_input_chars]
        page_chunks = _truncate_pages(page_texts, sent_text)
        try:
            candidates = self._client.extract_terms(sent_text)
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

        filtered = filter_candidates(candidates, sent_text, page_chunks)
        kept = [item for item in filtered if item.reason is None]
        rejected = [item for item in filtered if item.reason is not None]
        reasons = _reason_counts(filtered)
        if rejected:
            task_log(
                logger,
                logging.INFO,
                "candidate filter: filtered=%d reasons=%s",
                len(rejected),
                reasons,
                task=task_ctx,
            )
        if not kept:
            task_log(
                logger,
                logging.INFO,
                "candidate extraction done: no candidates pages=%s filtered=%d",
                pages,
                len(rejected),
                task=task_ctx,
            )
            return CandidateExtractionReport(
                status="all_filtered",
                candidates=0,
                pages=pages,
                filtered=len(rejected),
                filtered_by_reason=reasons,
            )

        observations = [
            CandidateObservation(
                source=item.source,
                target=item.target,
                pages=item.pages,
                evidence=item.evidence,
            )
            for item in kept
        ]
        try:
            if document_dir is None:
                raise TermStoreError("missing document cache dir")
            CandidateStore(document_dir).record_observations(
                observations,
                strategy_version=CANDIDATE_STRATEGY_VERSION,
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
            "candidate extraction done: candidates=%d pages=%s truncated=%s filtered=%d",
            len(kept),
            pages,
            truncated,
            len(rejected),
            task=task_ctx,
        )
        return CandidateExtractionReport(
            status="ok",
            candidates=len(kept),
            pages=pages,
            filtered=len(rejected),
            filtered_by_reason=reasons,
        )

    @staticmethod
    def _read_source_text(
        pdf_path: str | Path,
        page_indices: list[int] | tuple[int, ...],
    ) -> list[tuple[int, str]]:
        """用 PyMuPDF 读取已抽取局部 PDF 的逐页源文本。

        ``pdf_path`` 是仅含本次任务页的局部 PDF（页索引 0..k-1），
        ``page_indices`` 是原文 0-based 页索引。必须按局部索引读取，并按
        原文索引 +1 记录 1-based 证据页；空文本页跳过。局部 PDF 页数与请求
        页数不一致时拒绝读取（由调用方降级为 source_failed）。
        """
        doc = pymupdf.open(str(pdf_path))
        try:
            if doc.page_count != len(page_indices):
                raise ValueError("extracted pdf page count mismatch")
            result: list[tuple[int, str]] = []
            for local_index, original_index in enumerate(page_indices):
                if isinstance(original_index, bool) or not isinstance(original_index, int) or original_index < 0:
                    raise ValueError("invalid page index")
                page_text = doc[local_index].get_text()
                if page_text.strip():
                    result.append((original_index + 1, page_text))
            return result
        finally:
            doc.close()


def _truncate_pages(
    page_texts: list[tuple[int, str]],
    sent_text: str,
) -> list[tuple[int, str]]:
    """把已截断的 ``sent_text`` 映射回逐页文本块。

    页间 ``"\\n"`` 分隔符按旧服务语义计入 ``sent_text`` 前缀；返回的每页
    文本块只包含实际落入送给模型前缀内的内容。
    """
    chunks: list[tuple[int, str]] = []
    pos = 0
    for index, (page, text) in enumerate(page_texts):
        if pos >= len(sent_text):
            break
        if index > 0:
            if pos + 1 >= len(sent_text):
                break
            pos += 1
        chunk = text[: len(sent_text) - pos]
        if chunk:
            chunks.append((page, chunk))
        pos += len(chunk)
    return chunks


def _reason_counts(filtered: Sequence[FilteredCandidate]) -> tuple[tuple[str, int], ...]:
    """按原因汇总过滤数量，输出稳定有序（只含原因名与数量，不含原文）。"""
    counts: dict[str, int] = {}
    for item in filtered:
        if item.reason is not None:
            counts[item.reason] = counts.get(item.reason, 0) + 1
    return tuple(sorted(counts.items()))


class CandidateTermService:
    """P1-03 服务层边界：候选 target 列表与统计摘要（供未来 P1-04 UI/API 复用）。

    只做 Python 服务层：不新增 HTTP/UI。所有摘要由 ``CandidateStore`` 在路径
    锁内读取并应用确定性推荐排序（accepted target > 普通未拒绝建议 > rejected
    target；组内不同页覆盖数降序 → 观察次数降序 → target 字典序）。
    """

    def __init__(self, document_dir: Path) -> None:
        self._store = CandidateStore(document_dir)

    def list_summaries(self) -> tuple[CandidateSuggestionSummary, ...]:
        """全部 source 的候选摘要，按规范化 source key 确定性排序。"""
        return self._store.candidate_summaries()

    def target_summaries(self, source: str) -> tuple[CandidateTargetSummary, ...]:
        """单个 source 的确定性推荐 target 列表；source 不存在抛 TermNotFoundError。"""
        return self._store.target_summaries(source)
