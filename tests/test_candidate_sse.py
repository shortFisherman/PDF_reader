"""P1-01 SSE 集成：候选提取只在正文验证并提交成功后运行，失败不阻 finish。"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pymupdf

from pdf_reader import config
from pdf_reader.candidate_service import CandidateExtractionService
from pdf_reader.candidate_store import CandidateStore
from pdf_reader.sse_stream import (
    GenerateBatchContext,
    GenerateContext,
    generate,
    generate_batch,
)
from pdf_reader.strict_glossary import StrictTranslationContext, build_strict_settings
from pdf_reader.task_logging import STATUS_STARTED, TaskContext, task_context_from_indices
from pdf_reader.term_extraction import TermCandidate, TermExtractionClient

_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]")


def _pdf(tmp_path: Path, texts: list[str], name: str = "doc.pdf") -> Path:
    pdf_path = tmp_path / name
    doc = pymupdf.open()
    for text in texts:
        page = doc.new_page()
        has_cjk = bool(_CJK.search(text))
        if has_cjk:
            page.insert_font(fontname="china-s")
        page.insert_text((72, 72), text, fontname="china-s" if has_cjk else "helv")
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def _strict_ctx(tmp_path: Path, rows: list[tuple[str, str]]) -> tuple[StrictTranslationContext, Path]:
    doc_dir = tmp_path / ("d" * 64)
    doc_dir.mkdir()
    context = StrictTranslationContext(
        document_dir=doc_dir,
        document_id="doc-12345678",
        pdf_hash=doc_dir.name,
        effective_glossary_path=None,
        effective_rows=tuple(rows),
    )
    return context, doc_dir


def _task_ctx(job_id: str, context: StrictTranslationContext, page_indices: list[int]) -> TaskContext:
    return task_context_from_indices(
        job_id,
        context.document_id,
        context.pdf_hash,
        page_indices,
        status=STATUS_STARTED,
    )


def _result(mono: Path | None = None) -> MagicMock:
    result = MagicMock()
    result.mono_pdf_path = str(mono) if mono is not None else None
    result.dual_pdf_path = None
    result.auto_extracted_glossary_path = None
    return result


def _finish(result: MagicMock) -> list[dict]:
    return [{"type": "finish", "stage": "generating_pdf", "translate_result": result, "token_usage": {}}]


def _single_ctx(
    *,
    context: StrictTranslationContext,
    doc_dir: Path,
    cache_dir: Path,
    source_pdf: Path,
    service,
    job_id: str = "job-candidate",
    page: int = 0,
    settings=None,
) -> GenerateContext:
    return GenerateContext(
        settings=settings if settings is not None else MagicMock(),
        job_id=job_id,
        finish_job=MagicMock(return_value=True),
        fail_job=MagicMock(return_value=True),
        cancel_job=MagicMock(return_value=True),
        replace_page=MagicMock(),
        merge_glossary=MagicMock(),
        glossary_cache_path=doc_dir,
        page=page,
        glossary_paths=None,
        cache_dir=cache_dir,
        extract_page=MagicMock(return_value=source_pdf),
        strict_context=context,
        task_ctx=_task_ctx(job_id, context, [page]),
        candidate_service=service,
    )


def _batch_ctx(
    *,
    context: StrictTranslationContext,
    doc_dir: Path,
    cache_dir: Path,
    source_pdf: Path,
    service,
    page_indices: list[int],
    job_id: str = "job-candidate-batch",
) -> GenerateBatchContext:
    return GenerateBatchContext(
        settings=MagicMock(),
        job_id=job_id,
        finish_job=MagicMock(return_value=True),
        fail_job=MagicMock(return_value=True),
        cancel_job=MagicMock(return_value=True),
        from_page=1,
        to_page=len(page_indices),
        page_indices=page_indices,
        replace_pages=MagicMock(),
        merge_glossary=MagicMock(),
        glossary_cache_path=doc_dir,
        glossary_paths=None,
        cache_dir=cache_dir,
        extract_pages=MagicMock(return_value=source_pdf),
        strict_context=context,
        task_ctx=_task_ctx(job_id, context, page_indices),
        candidate_service=service,
    )


def test_single_runs_candidates_only_after_commit(tmp_path):
    source_pdf = _pdf(tmp_path, ["AD appears here."], name="source.pdf")
    ok_pdf = _pdf(tmp_path, ["阿尔茨海默病 是诊断结果。"], name="ok.pdf")
    context, doc_dir = _strict_ctx(tmp_path, [("AD", "阿尔茨海默病")])
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    service = MagicMock()
    service.run_for_pdf.return_value = MagicMock(status="ok", candidates=1, pages=(1,))
    ctx = _single_ctx(context=context, doc_dir=doc_dir, cache_dir=cache_dir, source_pdf=source_pdf, service=service)

    with (
        patch("pdf_reader.sse_stream.run_translation", return_value=iter(_finish(_result(mono=ok_pdf)))),
        patch("pdf_reader.sse_stream.debug_trace"),
    ):
        output = list(generate(ctx))
    body = "".join(output)

    assert '"type": "finish"' in body
    ctx.replace_page.assert_called_once()
    service.run_for_pdf.assert_called_once()
    call = service.run_for_pdf.call_args
    assert call.args[0] == source_pdf
    assert call.args[1] == [0]
    assert call.args[2] == doc_dir
    ctx.finish_job.assert_called_once_with("job-candidate")


def test_batch_runs_candidates_with_page_indices(tmp_path):
    source_pdf = _pdf(tmp_path, ["AD page one", "TCS page two"], name="source.pdf")
    ok_pdf = _pdf(tmp_path, ["阿尔茨海默病 第一页", "外用糖皮质激素 第二页"], name="ok.pdf")
    context, doc_dir = _strict_ctx(tmp_path, [])
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    service = MagicMock()
    ctx = _batch_ctx(
        context=context,
        doc_dir=doc_dir,
        cache_dir=cache_dir,
        source_pdf=source_pdf,
        service=service,
        page_indices=[0, 1],
    )

    with (
        patch("pdf_reader.sse_stream.run_translation", return_value=iter(_finish(_result(mono=ok_pdf)))),
        patch("pdf_reader.sse_stream.debug_trace"),
    ):
        output = list(generate_batch(ctx))
    body = "".join(output)

    assert '"type": "finish"' in body
    ctx.replace_pages.assert_called_once()
    service.run_for_pdf.assert_called_once()
    call = service.run_for_pdf.call_args
    assert call.args[0] == source_pdf
    assert call.args[1] == [0, 1]


def test_candidate_failure_does_not_block_finish(tmp_path, managed_caplog):
    import logging

    source_pdf = _pdf(tmp_path, ["AD appears here."], name="source.pdf")
    ok_pdf = _pdf(tmp_path, ["阿尔茨海默病 是诊断结果。"], name="ok.pdf")
    context, doc_dir = _strict_ctx(tmp_path, [("AD", "阿尔茨海默病")])
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    service = MagicMock()
    service.run_for_pdf.side_effect = RuntimeError("candidate boom")
    ctx = _single_ctx(context=context, doc_dir=doc_dir, cache_dir=cache_dir, source_pdf=source_pdf, service=service)

    with (
        patch("pdf_reader.sse_stream.run_translation", return_value=iter(_finish(_result(mono=ok_pdf)))),
        patch("pdf_reader.sse_stream.debug_trace"),
        managed_caplog.at_level(logging.WARNING, logger="pdf_reader.translate"),
    ):
        output = list(generate(ctx))
    body = "".join(output)

    assert '"type": "finish"' in body
    ctx.finish_job.assert_called_once_with("job-candidate")
    assert "candidate extraction degraded" in managed_caplog.text
    assert "candidate boom" not in managed_caplog.text


def test_body_failure_never_calls_candidate_service(tmp_path):
    context, doc_dir = _strict_ctx(tmp_path, [])
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    service = MagicMock()
    ctx = _single_ctx(
        context=context,
        doc_dir=doc_dir,
        cache_dir=cache_dir,
        source_pdf=_pdf(tmp_path, ["plain"], name="source.pdf"),
        service=service,
    )
    with (
        patch("pdf_reader.sse_stream.run_translation", return_value=iter([{"type": "error", "error": "boom"}])),
        patch("pdf_reader.sse_stream.debug_trace"),
    ):
        output = list(generate(ctx))
    assert '"type": "error"' in "".join(output)
    service.run_for_pdf.assert_not_called()
    ctx.finish_job.assert_not_called()


def test_compliance_failure_never_calls_candidate_service(tmp_path):
    source_pdf = _pdf(tmp_path, ["AD appears here."], name="source.pdf")
    wrong_pdf = _pdf(tmp_path, ["AD 出现了。"], name="wrong.pdf")
    context, doc_dir = _strict_ctx(tmp_path, [("AD", "阿尔茨海默病")])
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    service = MagicMock()
    ctx = _single_ctx(context=context, doc_dir=doc_dir, cache_dir=cache_dir, source_pdf=source_pdf, service=service)

    with (
        patch(
            "pdf_reader.sse_stream.run_translation",
            side_effect=lambda *args, **kwargs: iter(_finish(_result(mono=wrong_pdf))),
        ),
        patch("pdf_reader.sse_stream.debug_trace"),
    ):
        output = list(generate(ctx))
    body = "".join(output)

    assert '"type": "finish"' not in body
    assert '"code": "glossary_compliance_failed"' in body
    service.run_for_pdf.assert_not_called()
    ctx.replace_page.assert_not_called()


def test_candidates_never_enter_effective_or_settings(tmp_path, monkeypatch):
    source_pdf = _pdf(tmp_path, ["AD appears here."], name="source.pdf")
    ok_pdf = _pdf(tmp_path, ["阿尔茨海默病 是诊断结果。"], name="ok.pdf")
    context, doc_dir = _strict_ctx(tmp_path, [("AD", "阿尔茨海默病")])
    effective_csv = doc_dir / "effective_glossary.csv"
    effective_csv.write_text("source,target\nAD,阿尔茨海默病\n", encoding="utf-8")
    context = StrictTranslationContext(
        document_dir=doc_dir,
        document_id=context.document_id,
        pdf_hash=context.pdf_hash,
        effective_glossary_path=effective_csv,
        effective_rows=context.effective_rows,
    )
    before = effective_csv.read_bytes()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    upstream = config.UpstreamRuntimeConfig(
        model=config.ModelRuntimeConfig(provider="deepseek", api_key="sk-test", model="deepseek-chat"),
        translation=config.TranslationRuntimeConfig(lang_in="en", lang_out="zh"),
        pdf=config.Pdf2zhRuntimeConfig(),
    )
    settings = build_strict_settings(upstream, None, "1", context)
    service = CandidateExtractionService(upstream.term_extraction, upstream.model)
    monkeypatch.setattr(
        TermExtractionClient,
        "extract_terms",
        lambda self, text: [TermCandidate(source="AD", target="候选译法")],
    )
    ctx = _single_ctx(
        context=context,
        doc_dir=doc_dir,
        cache_dir=cache_dir,
        source_pdf=source_pdf,
        service=service,
        settings=settings,
    )

    with (
        patch("pdf_reader.sse_stream.run_translation", return_value=iter(_finish(_result(mono=ok_pdf)))),
        patch("pdf_reader.sse_stream.debug_trace"),
    ):
        output = list(generate(ctx))
    body = "".join(output)

    assert '"type": "finish"' in body
    assert effective_csv.read_bytes() == before
    assert settings.translation.glossaries == str(effective_csv)
    entries, _, _ = CandidateStore(doc_dir).load()
    assert any(entry.source_key == "ad" and entry.status == "candidate" for entry in entries)
    assert all(entry.status == "candidate" for entry in entries)
