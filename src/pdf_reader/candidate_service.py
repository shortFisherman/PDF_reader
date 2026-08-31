"""P1-01/P1-02/P1-05 两阶段候选提取服务。

不变量：
- ``prepare`` 阶段在严格正文翻译前读取输入 PDF、调用模型提取并做本地过滤，
  返回不可变 ``PreparedCandidates``（observations + report），绝不写
  ``CandidateStore``；
- ``commit`` 阶段只在调用方确认正文 PDF 已经最终验证并提交成功后执行，先
  以 ``PreparedCandidates`` 冻结的请求身份（``prepare`` 时传入的
  ``CandidateIdentity``）为权威，重验当前 active job 的
  job_id/document_id/pdf_hash/document_dir 仍与冻结身份一致，再原子写
  ``CandidateStore``；身份变化/存储失败返回降级报告且不写任何候选；
- 正文失败、合规失败、PDF 提交失败、断开/取消路径不会调用 ``commit``，
  已 prepare 的候选只存在于内存，随任务工作区一起丢弃；
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
from collections.abc import Callable, Sequence
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
    job_id: str = ""
    document_id: str = ""
    pdf_hash: str = ""


@dataclass(frozen=True)
class CandidateIdentity:
    """候选提取请求携带的任务/文档身份；提交前必须再次与 active job 校验。"""

    job_id: str
    document_id: str
    pdf_hash: str
    document_dir: Path


@dataclass(frozen=True)
class PreparedCandidates:
    """``prepare`` 阶段的不可变产物：已过滤候选观察、稳定报告与冻结身份。

    ``prepare`` 从不写盘；``commit`` 只消费本对象，且带身份时以
    ``identity`` 为权威——提交时另传的 identity/document_dir 都必须与它
    完全一致，禁止用新身份或新目录改写冻结身份对应的文档观察。PDF 未成功
    提交时调用方直接丢弃本对象即可，绝不落盘。
    """

    observations: tuple[CandidateObservation, ...]
    report: CandidateExtractionReport
    identity: CandidateIdentity | None = None


class CandidateExtractionService:
    """两阶段候选提取服务（同步首版，严格 timeout，无悬挂线程）。

    生产路径必须携带 ``identity`` 与 ``active_job_provider``：``prepare``
    在网络请求前校验一次当前 active job 并把身份冻结进
    ``PreparedCandidates``；``commit`` 在写入前以冻结身份再校验一次
    job/document/pdf_hash/document_dir，校验失败返回 ``identity_rejected``
    且不写任何候选。
    """

    def __init__(
        self,
        cfg: CandidateExtractionRuntimeConfig,
        model_cfg: ModelRuntimeConfig,
    ) -> None:
        self._cfg = cfg
        self._provider = model_cfg.provider
        self._client = TermExtractionClient(model_cfg, cfg)
        self._semaphore = threading.BoundedSemaphore(cfg.max_workers)

    def prepare(
        self,
        pdf_path: str | Path,
        page_indices: list[int] | tuple[int, ...],
        document_dir: Path | None,
        task_ctx: TaskContext | None = None,
        *,
        identity: CandidateIdentity | None = None,
        active_job_provider: Callable[[], object | None] | None = None,
    ) -> PreparedCandidates:
        """严格翻译前阶段：读取输入 PDF、模型提取/过滤，返回不可变 prepared。

        绝不写 ``CandidateStore``。带 ``identity`` 时 ``document_dir`` 必须
        等于 ``identity.document_dir``，否则返回 ``identity_rejected`` 报告
        且 observations 为空；身份校验失败同样返回 ``identity_rejected``
        报告且 observations 为空。任何降级都不阻止正文继续。
        """
        with self._semaphore:
            report, observations = self._prepare_locked(
                pdf_path,
                page_indices,
                document_dir,
                task_ctx,
                identity=identity,
                active_job_provider=active_job_provider,
            )
            if identity is not None:
                report = self._with_identity(report, identity)
            return PreparedCandidates(
                observations=observations,
                report=report,
                identity=identity,
            )

    def commit(
        self,
        prepared: PreparedCandidates,
        document_dir: Path | None = None,
        task_ctx: TaskContext | None = None,
        *,
        identity: CandidateIdentity | None = None,
        active_job_provider: Callable[[], object | None] | None = None,
    ) -> CandidateExtractionReport:
        """PDF 成功提交后的阶段：重验 active job 身份并原子写 CandidateStore。

        身份门通过后，prepare 已降级或没有观察时原样返回
        ``prepared.report``（no-op）；带身份 prepared 以
        ``prepared.identity`` 为权威：另传 identity 必须完全相等，写目录
        必须等于 ``prepared.identity.document_dir``，active job 必须仍与
        冻结身份一致，任何 mismatch 都返回 ``identity_rejected`` 且不写；
        无身份 prepared 禁止在 commit 时被升级为带身份。身份拒绝/存储失败
        返回降级报告且不写任何候选。任何异常都不反转已提交正文的 finished
        终态。
        """
        with self._semaphore:
            frozen_identity = prepared.identity
            if frozen_identity is not None:
                if identity is not None and identity != frozen_identity:
                    return self._identity_rejected(prepared.report, task_ctx)
                target_dir = document_dir
                if target_dir is None:
                    target_dir = frozen_identity.document_dir
                if target_dir != frozen_identity.document_dir:
                    return self._identity_rejected(prepared.report, task_ctx)
                if not self._identity_is_current(frozen_identity, active_job_provider):
                    return self._identity_rejected(prepared.report, task_ctx)
            elif identity is not None:
                # 无身份 prepared 不允许在 commit 时被升级为带身份。
                return self._identity_rejected(prepared.report, task_ctx)
            else:
                # 原有无身份兼容路径：不校验 active job，直接写调用方目录。
                target_dir = document_dir
            if not prepared.observations:
                return prepared.report
            try:
                if target_dir is None:
                    raise TermStoreError("missing document cache dir")
                CandidateStore(target_dir).record_observations(
                    list(prepared.observations),
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
                return self._report_with_status(prepared.report, "store_failed")
            except Exception as exc:
                task_log(
                    logger,
                    logging.WARNING,
                    "candidate store write failed: reason=%s",
                    type(exc).__name__,
                    task=task_ctx,
                )
                return self._report_with_status(prepared.report, "store_failed")
            task_log(
                logger,
                logging.INFO,
                "candidate commit done: candidates=%d pages=%s",
                len(prepared.observations),
                prepared.report.pages,
                task=task_ctx,
            )
            return self._report_with_status(prepared.report, "ok")

    def _prepare_locked(
        self,
        pdf_path: str | Path,
        page_indices: list[int] | tuple[int, ...],
        document_dir: Path | None,
        task_ctx: TaskContext | None,
        *,
        identity: CandidateIdentity | None,
        active_job_provider: Callable[[], object | None] | None,
    ) -> tuple[CandidateExtractionReport, tuple[CandidateObservation, ...]]:
        if identity is not None and document_dir != identity.document_dir:
            task_log(
                logger,
                logging.WARNING,
                "candidate identity rejected: document_dir mismatch",
                task=task_ctx,
            )
            return CandidateExtractionReport(status="identity_rejected"), ()
        if not self._cfg.enabled:
            task_log(logger, logging.DEBUG, "candidate extraction skipped: disabled", task=task_ctx)
            return CandidateExtractionReport(status="disabled"), ()
        if not self._client.supported:
            task_log(
                logger,
                logging.WARNING,
                "candidate extraction unsupported: provider=%s",
                self._provider,
                task=task_ctx,
            )
            return CandidateExtractionReport(status="unsupported"), ()
        if not self._identity_is_current(identity, active_job_provider):
            task_log(
                logger,
                logging.WARNING,
                "candidate identity rejected before extraction",
                task=task_ctx,
            )
            return CandidateExtractionReport(status="identity_rejected"), ()

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
            return CandidateExtractionReport(status="source_failed"), ()
        if not page_texts:
            task_log(
                logger,
                logging.INFO,
                "candidate extraction skipped: empty source",
                task=task_ctx,
            )
            return CandidateExtractionReport(status="empty"), ()

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
            return CandidateExtractionReport(status="failed", pages=pages), ()
        except Exception as exc:
            task_log(
                logger,
                logging.WARNING,
                "candidate extraction failed: reason=%s",
                type(exc).__name__,
                task=task_ctx,
            )
            return CandidateExtractionReport(status="failed", pages=pages), ()
        if not candidates:
            task_log(
                logger,
                logging.INFO,
                "candidate extraction done: no candidates pages=%s",
                pages,
                task=task_ctx,
            )
            return CandidateExtractionReport(status="no_candidates", pages=pages), ()

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
            ), ()

        observations = [
            CandidateObservation(
                source=item.source,
                target=item.target,
                pages=item.pages,
                evidence=item.evidence,
            )
            for item in kept
        ]
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
        ), tuple(observations)

    @staticmethod
    def _with_identity(report: CandidateExtractionReport, identity: CandidateIdentity) -> CandidateExtractionReport:
        """把请求身份字段填入报告；status/统计不变。"""
        return CandidateExtractionReport(
            status=report.status,
            candidates=report.candidates,
            pages=report.pages,
            filtered=report.filtered,
            filtered_by_reason=report.filtered_by_reason,
            job_id=identity.job_id,
            document_id=identity.document_id,
            pdf_hash=identity.pdf_hash,
        )

    @staticmethod
    def _report_with_status(report: CandidateExtractionReport, status: str) -> CandidateExtractionReport:
        """重建报告并替换状态；其余字段不变。"""
        return CandidateExtractionReport(
            status=status,
            candidates=report.candidates,
            pages=report.pages,
            filtered=report.filtered,
            filtered_by_reason=report.filtered_by_reason,
            job_id=report.job_id,
            document_id=report.document_id,
            pdf_hash=report.pdf_hash,
        )

    @staticmethod
    def _identity_rejected(
        report: CandidateExtractionReport,
        task_ctx: TaskContext | None,
    ) -> CandidateExtractionReport:
        """记录 commit 身份拒绝并返回降级报告。"""
        task_log(
            logger,
            logging.WARNING,
            "candidate identity rejected at commit",
            task=task_ctx,
        )
        return CandidateExtractionService._report_with_status(report, "identity_rejected")

    @staticmethod
    def _identity_is_current(
        identity: CandidateIdentity | None,
        active_job_provider: Callable[[], object | None] | None,
    ) -> bool:
        """候选提交门：当前 active job 必须与请求身份完全相同，且目录名=pdf_hash。"""
        if identity is None:
            return True
        if active_job_provider is None:
            return False
        if identity.document_dir.name != identity.pdf_hash:
            return False
        try:
            active = active_job_provider()
        except Exception:
            return False
        if active is None:
            return False
        if getattr(active, "job_id", None) != identity.job_id:
            return False
        if getattr(active, "document_id", None) != identity.document_id:
            return False
        if identity.pdf_hash and getattr(active, "pdf_hash", None) != identity.pdf_hash:
            return False
        return True

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
    """P1-03 服务层边界：候选 target 列表与统计摘要（P1-04 管理服务复用同一排序）。

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
