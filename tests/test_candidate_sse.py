"""P1-01/P1-05 SSE 集成：候选 prepare 在严格翻译前，commit 只在 PDF 提交后。"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import DEFAULT, MagicMock, patch

import pymupdf

from pdf_reader import config, strict_glossary
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
from pdf_reader.term_extraction import TermCandidate, TermExtractionClient, TermExtractionResult, TokenUsage

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


def _prepared(status: str = "ok", candidates: int = 1, pages: tuple[int, ...] = (1,)) -> MagicMock:
    return MagicMock(
        observations=(MagicMock(),) if status == "ok" else (),
        report=MagicMock(status=status, candidates=candidates, pages=pages),
    )


def _commit_report(status: str = "ok", candidates: int = 1, pages: tuple[int, ...] = (1,)) -> MagicMock:
    return MagicMock(status=status, candidates=candidates, pages=pages)


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
    active_job_provider=None,
) -> GenerateContext:
    if active_job_provider is None:

        def active_job_provider() -> object:
            return MagicMock(
                job_id=job_id,
                document_id=context.document_id,
                pdf_hash=context.pdf_hash,
            )

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
        active_job_provider=active_job_provider,
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
    active_job_provider=None,
) -> GenerateBatchContext:
    if active_job_provider is None:

        def active_job_provider() -> object:
            return MagicMock(
                job_id=job_id,
                document_id=context.document_id,
                pdf_hash=context.pdf_hash,
            )

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
        active_job_provider=active_job_provider,
    )


def _tracked_service(calls: list[str], *, prepare_status: str = "ok", commit_status: str = "ok") -> MagicMock:
    service = MagicMock()
    prepared = _prepared(prepare_status)
    service.prepare.return_value = prepared
    service.commit.return_value = _commit_report(commit_status)
    service.prepare.side_effect = lambda *args, **kwargs: calls.append("prepare") or DEFAULT
    service.commit.side_effect = lambda *args, **kwargs: calls.append("commit") or DEFAULT
    return service


def test_single_prepares_before_translation_and_commits_after_pdf(tmp_path):
    source_pdf = _pdf(tmp_path, ["AD appears here."], name="source.pdf")
    ok_pdf = _pdf(tmp_path, ["阿尔茨海默病 是诊断结果。"], name="ok.pdf")
    context, doc_dir = _strict_ctx(tmp_path, [("AD", "阿尔茨海默病")])
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    calls: list[str] = []
    service = _tracked_service(calls)
    ctx = _single_ctx(context=context, doc_dir=doc_dir, cache_dir=cache_dir, source_pdf=source_pdf, service=service)
    ctx.extract_page.side_effect = lambda *args, **kwargs: calls.append("extract") or source_pdf
    ctx.replace_page.side_effect = lambda *args: calls.append("replace_page")
    ctx.merge_glossary.side_effect = lambda *args: calls.append("merge_glossary")
    ctx.finish_job.side_effect = lambda *args: calls.append("finish") or True

    def fake_run_translation(settings, pdf_path, flow_label: str = "", task_ctx=None) -> Iterator[dict]:
        calls.append("translate")
        return iter(_finish(_result(mono=ok_pdf)))

    real_resolve = strict_glossary.resolve_active_terms_from_pdf

    def fake_resolve(pdf_path, rows) -> object:
        calls.append("terms")
        return real_resolve(pdf_path, rows)

    with (
        patch("pdf_reader.sse_stream.run_translation", side_effect=fake_run_translation),
        patch("pdf_reader.strict_glossary.resolve_active_terms_from_pdf", side_effect=fake_resolve),
        patch("pdf_reader.sse_stream.debug_trace"),
    ):
        output = list(generate(ctx))
    body = "".join(output)

    assert '"type": "finish"' in body
    assert calls == ["extract", "terms", "prepare", "translate", "replace_page", "merge_glossary", "commit", "finish"]
    service.prepare.assert_called_once()
    service.commit.assert_called_once()
    prepare_call = service.prepare.call_args
    assert prepare_call.args[0] == source_pdf
    assert prepare_call.args[1] == [0]
    assert prepare_call.args[2] == doc_dir
    commit_call = service.commit.call_args
    assert commit_call.args[0] is service.prepare.return_value
    assert commit_call.args[1] == doc_dir


def test_batch_prepares_before_translation_and_commits_after_pdf(tmp_path):
    source_pdf = _pdf(tmp_path, ["AD page one", "TCS page two"], name="source.pdf")
    ok_pdf = _pdf(tmp_path, ["阿尔茨海默病 第一页", "外用糖皮质激素 第二页"], name="ok.pdf")
    context, doc_dir = _strict_ctx(tmp_path, [])
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    calls: list[str] = []
    service = _tracked_service(calls)
    ctx = _batch_ctx(
        context=context,
        doc_dir=doc_dir,
        cache_dir=cache_dir,
        source_pdf=source_pdf,
        service=service,
        page_indices=[0, 1],
    )
    ctx.extract_pages.side_effect = lambda *args, **kwargs: calls.append("extract") or source_pdf
    ctx.replace_pages.side_effect = lambda *args: calls.append("replace_pages")
    ctx.merge_glossary.side_effect = lambda *args: calls.append("merge_glossary")
    ctx.finish_job.side_effect = lambda *args: calls.append("finish") or True

    def fake_run_translation(settings, pdf_path, flow_label: str = "", task_ctx=None) -> Iterator[dict]:
        calls.append("translate")
        return iter(_finish(_result(mono=ok_pdf)))

    real_resolve = strict_glossary.resolve_active_terms_from_pdf

    def fake_resolve(pdf_path, rows) -> object:
        calls.append("terms")
        return real_resolve(pdf_path, rows)

    with (
        patch("pdf_reader.sse_stream.run_translation", side_effect=fake_run_translation),
        patch("pdf_reader.strict_glossary.resolve_active_terms_from_pdf", side_effect=fake_resolve),
        patch("pdf_reader.sse_stream.debug_trace"),
    ):
        output = list(generate_batch(ctx))
    body = "".join(output)

    assert '"type": "finish"' in body
    assert calls == ["extract", "terms", "prepare", "translate", "replace_pages", "merge_glossary", "commit", "finish"]
    service.prepare.assert_called_once()
    service.commit.assert_called_once()
    prepare_call = service.prepare.call_args
    assert prepare_call.args[0] == source_pdf
    assert prepare_call.args[1] == [0, 1]
    assert prepare_call.args[2] == doc_dir
    commit_call = service.commit.call_args
    assert commit_call.args[0] is service.prepare.return_value
    assert commit_call.args[1] == doc_dir


def test_single_prepare_failure_does_not_block_finish(tmp_path, managed_caplog):
    source_pdf = _pdf(tmp_path, ["AD appears here."], name="source.pdf")
    ok_pdf = _pdf(tmp_path, ["阿尔茨海默病 是诊断结果。"], name="ok.pdf")
    context, doc_dir = _strict_ctx(tmp_path, [("AD", "阿尔茨海默病")])
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    service = MagicMock()
    service.prepare.side_effect = RuntimeError("candidate boom")
    ctx = _single_ctx(context=context, doc_dir=doc_dir, cache_dir=cache_dir, source_pdf=source_pdf, service=service)

    with (
        patch("pdf_reader.sse_stream.run_translation", return_value=iter(_finish(_result(mono=ok_pdf)))),
        patch("pdf_reader.sse_stream.debug_trace"),
        managed_caplog.at_level(logging.WARNING, logger="pdf_reader.translate"),
    ):
        output = list(generate(ctx))
    body = "".join(output)

    assert '"type": "finish"' in body
    service.prepare.assert_called_once()
    service.commit.assert_not_called()
    ctx.finish_job.assert_called_once_with("job-candidate")
    assert "candidate extraction degraded" in managed_caplog.text
    assert "candidate boom" not in managed_caplog.text


def test_batch_prepare_failure_does_not_block_finish(tmp_path, managed_caplog):
    source_pdf = _pdf(tmp_path, ["AD page one"], name="source.pdf")
    ok_pdf = _pdf(tmp_path, ["阿尔茨海默病 第一页"], name="ok.pdf")
    context, doc_dir = _strict_ctx(tmp_path, [])
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    service = MagicMock()
    service.prepare.side_effect = RuntimeError("candidate boom")
    ctx = _batch_ctx(
        context=context,
        doc_dir=doc_dir,
        cache_dir=cache_dir,
        source_pdf=source_pdf,
        service=service,
        page_indices=[0],
    )

    with (
        patch("pdf_reader.sse_stream.run_translation", return_value=iter(_finish(_result(mono=ok_pdf)))),
        patch("pdf_reader.sse_stream.debug_trace"),
        managed_caplog.at_level(logging.WARNING, logger="pdf_reader.translate"),
    ):
        output = list(generate_batch(ctx))
    body = "".join(output)

    assert '"type": "finish"' in body
    service.prepare.assert_called_once()
    service.commit.assert_not_called()
    ctx.finish_job.assert_called_once_with("job-candidate-batch")
    assert "candidate extraction degraded" in managed_caplog.text


def test_commit_failure_does_not_reverse_finished(tmp_path, managed_caplog):
    source_pdf = _pdf(tmp_path, ["AD appears here."], name="source.pdf")
    ok_pdf = _pdf(tmp_path, ["阿尔茨海默病 是诊断结果。"], name="ok.pdf")
    context, doc_dir = _strict_ctx(tmp_path, [("AD", "阿尔茨海默病")])
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    service = MagicMock()
    service.prepare.return_value = _prepared()
    service.commit.side_effect = RuntimeError("candidate commit boom")
    ctx = _single_ctx(context=context, doc_dir=doc_dir, cache_dir=cache_dir, source_pdf=source_pdf, service=service)

    with (
        patch("pdf_reader.sse_stream.run_translation", return_value=iter(_finish(_result(mono=ok_pdf)))),
        patch("pdf_reader.sse_stream.debug_trace"),
        managed_caplog.at_level(logging.WARNING, logger="pdf_reader.translate"),
    ):
        output = list(generate(ctx))
    body = "".join(output)

    assert '"type": "finish"' in body
    ctx.replace_page.assert_called_once()
    service.commit.assert_called_once()
    ctx.finish_job.assert_called_once_with("job-candidate")
    assert "candidate commit degraded" in managed_caplog.text
    assert "candidate commit boom" not in managed_caplog.text


def test_batch_commit_failure_still_finishes(tmp_path, managed_caplog):
    source_pdf = _pdf(tmp_path, ["AD page one"], name="source.pdf")
    ok_pdf = _pdf(tmp_path, ["阿尔茨海默病 第一页"], name="ok.pdf")
    context, doc_dir = _strict_ctx(tmp_path, [])
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    service = MagicMock()
    service.prepare.return_value = _prepared()
    service.commit.side_effect = RuntimeError("candidate commit boom")
    ctx = _batch_ctx(
        context=context,
        doc_dir=doc_dir,
        cache_dir=cache_dir,
        source_pdf=source_pdf,
        service=service,
        page_indices=[0],
    )

    with (
        patch("pdf_reader.sse_stream.run_translation", return_value=iter(_finish(_result(mono=ok_pdf)))),
        patch("pdf_reader.sse_stream.debug_trace"),
        managed_caplog.at_level(logging.WARNING, logger="pdf_reader.translate"),
    ):
        output = list(generate_batch(ctx))
    body = "".join(output)

    assert '"type": "finish"' in body
    ctx.replace_pages.assert_called_once()
    service.commit.assert_called_once()
    ctx.finish_job.assert_called_once_with("job-candidate-batch")
    assert "candidate commit degraded" in managed_caplog.text


def test_body_failure_prepares_but_never_commits(tmp_path):
    context, doc_dir = _strict_ctx(tmp_path, [])
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    service = MagicMock()
    service.prepare.return_value = _prepared()
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
    service.prepare.assert_called_once()
    service.commit.assert_not_called()
    ctx.finish_job.assert_not_called()


def test_compliance_failure_prepares_but_never_commits(tmp_path):
    source_pdf = _pdf(tmp_path, ["AD appears here."], name="source.pdf")
    wrong_pdf = _pdf(tmp_path, ["AD 出现了。"], name="wrong.pdf")
    context, doc_dir = _strict_ctx(tmp_path, [("AD", "阿尔茨海默病")])
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    service = MagicMock()
    service.prepare.return_value = _prepared()
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
    service.prepare.assert_called_once()
    service.commit.assert_not_called()
    ctx.replace_page.assert_not_called()


def test_pdf_replace_failure_prepares_but_never_commits(tmp_path):
    source_pdf = _pdf(tmp_path, ["AD appears here."], name="source.pdf")
    ok_pdf = _pdf(tmp_path, ["阿尔茨海默病 是诊断结果。"], name="ok.pdf")
    context, doc_dir = _strict_ctx(tmp_path, [("AD", "阿尔茨海默病")])
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    service = MagicMock()
    service.prepare.return_value = _prepared()
    ctx = _single_ctx(context=context, doc_dir=doc_dir, cache_dir=cache_dir, source_pdf=source_pdf, service=service)
    ctx.replace_page.side_effect = RuntimeError("replace boom")

    with (
        patch("pdf_reader.sse_stream.run_translation", return_value=iter(_finish(_result(mono=ok_pdf)))),
        patch("pdf_reader.sse_stream.debug_trace"),
    ):
        output = list(generate(ctx))
    body = "".join(output)

    assert '"type": "error"' in body
    assert '"type": "finish"' not in body
    service.prepare.assert_called_once()
    service.commit.assert_not_called()
    ctx.finish_job.assert_not_called()


def test_disconnect_after_prepare_never_commits(tmp_path):
    import asyncio
    from collections.abc import AsyncIterator

    source_pdf = _pdf(tmp_path, ["AD appears here."], name="source.pdf")
    context, doc_dir = _strict_ctx(tmp_path, [("AD", "阿尔茨海默病")])
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    service = MagicMock()
    service.prepare.return_value = _prepared()
    ctx = _single_ctx(
        context=context,
        doc_dir=doc_dir,
        cache_dir=cache_dir,
        source_pdf=source_pdf,
        service=service,
    )

    ok_pdf = _pdf(tmp_path, ["阿尔茨海默病 是诊断结果。"], name="ok.pdf")

    async def slow_source(settings, file) -> AsyncIterator[dict]:
        yield {"type": "progress_start", "stage": "layout_analysis"}
        await asyncio.sleep(0.3)
        yield {"type": "finish", "translate_result": _result(mono=ok_pdf)}

    with (
        patch("pdf_reader.translation_orchestrator.do_translate_async_stream", slow_source),
        patch("pdf_reader.sse_stream.debug_trace"),
    ):
        gen = generate(ctx)
        next(gen)
        gen.close()

    service.prepare.assert_called_once()
    service.commit.assert_not_called()
    assert not (doc_dir / "term_candidates.json").exists()
    assert not list(cache_dir.glob("pdf-reader-translation-*"))


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
        "extract_terms_with_usage",
        lambda self, text: TermExtractionResult(
            terms=[TermCandidate(source="AD", target="候选译法")],
            usage=None,
        ),
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


def test_single_passes_identity_and_active_job_provider_to_candidate_service(tmp_path):
    source_pdf = _pdf(tmp_path, ["AD appears here."], name="source.pdf")
    ok_pdf = _pdf(tmp_path, ["阿尔茨海默病 是诊断结果。"], name="ok.pdf")
    context, doc_dir = _strict_ctx(tmp_path, [("AD", "阿尔茨海默病")])
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    service = MagicMock()
    service.prepare.return_value = _prepared()
    service.commit.return_value = _commit_report()
    provider = MagicMock()
    ctx = _single_ctx(
        context=context,
        doc_dir=doc_dir,
        cache_dir=cache_dir,
        source_pdf=source_pdf,
        service=service,
        active_job_provider=provider,
    )

    with (
        patch("pdf_reader.sse_stream.run_translation", return_value=iter(_finish(_result(mono=ok_pdf)))),
        patch("pdf_reader.sse_stream.debug_trace"),
    ):
        output = list(generate(ctx))

    assert '"type": "finish"' in "".join(output)
    prepare_call = service.prepare.call_args
    assert prepare_call.kwargs["identity"].job_id == "job-candidate"
    assert prepare_call.kwargs["identity"].document_id == context.document_id
    assert prepare_call.kwargs["identity"].pdf_hash == context.pdf_hash
    assert prepare_call.kwargs["identity"].document_dir == doc_dir
    assert prepare_call.kwargs["active_job_provider"] is provider
    commit_call = service.commit.call_args
    assert commit_call.kwargs["identity"].job_id == "job-candidate"
    assert commit_call.kwargs["identity"].document_id == context.document_id
    assert commit_call.kwargs["identity"].pdf_hash == context.pdf_hash
    assert commit_call.kwargs["identity"].document_dir == doc_dir
    assert commit_call.kwargs["active_job_provider"] is provider


def test_identity_rejected_candidate_does_not_change_finish_and_writes_nothing(tmp_path, monkeypatch):
    from pdf_reader.candidate_service import CandidateExtractionService
    from pdf_reader.term_extraction import TermExtractionClient

    source_pdf = _pdf(tmp_path, ["AD appears here."], name="source.pdf")
    ok_pdf = _pdf(tmp_path, ["阿尔茨海默病 是诊断结果。"], name="ok.pdf")
    context, doc_dir = _strict_ctx(tmp_path, [("AD", "阿尔茨海默病")])
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    upstream = config.UpstreamRuntimeConfig(
        model=config.ModelRuntimeConfig(provider="deepseek", api_key="sk-test", model="deepseek-chat"),
        translation=config.TranslationRuntimeConfig(lang_in="en", lang_out="zh"),
        pdf=config.Pdf2zhRuntimeConfig(),
    )
    service = CandidateExtractionService(upstream.term_extraction, upstream.model)
    monkeypatch.setattr(
        TermExtractionClient,
        "extract_terms_with_usage",
        lambda self, text: TermExtractionResult(
            terms=[TermCandidate(source="AD", target="候选译法")],
            usage=None,
        ),
    )
    other = MagicMock(job_id="other-job", document_id=context.document_id, pdf_hash=context.pdf_hash)
    ctx = _single_ctx(
        context=context,
        doc_dir=doc_dir,
        cache_dir=cache_dir,
        source_pdf=source_pdf,
        service=service,
        active_job_provider=lambda: other,
    )

    with (
        patch("pdf_reader.sse_stream.run_translation", return_value=iter(_finish(_result(mono=ok_pdf)))),
        patch("pdf_reader.sse_stream.debug_trace"),
    ):
        output = list(generate(ctx))
    body = "".join(output)

    assert '"type": "finish"' in body
    ctx.finish_job.assert_called_once_with("job-candidate")
    assert not (doc_dir / "term_candidates.json").exists()


def test_identity_changed_after_prepare_rejects_commit_but_finishes(tmp_path, monkeypatch, managed_caplog):
    from pdf_reader.candidate_service import CandidateExtractionService
    from pdf_reader.term_extraction import TermExtractionClient

    source_pdf = _pdf(tmp_path, ["AD appears here."], name="source.pdf")
    ok_pdf = _pdf(tmp_path, ["阿尔茨海默病 是诊断结果。"], name="ok.pdf")
    context, doc_dir = _strict_ctx(tmp_path, [("AD", "阿尔茨海默病")])
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    upstream = config.UpstreamRuntimeConfig(
        model=config.ModelRuntimeConfig(provider="deepseek", api_key="sk-test", model="deepseek-chat"),
        translation=config.TranslationRuntimeConfig(lang_in="en", lang_out="zh"),
        pdf=config.Pdf2zhRuntimeConfig(),
    )
    service = CandidateExtractionService(upstream.term_extraction, upstream.model)
    monkeypatch.setattr(
        TermExtractionClient,
        "extract_terms_with_usage",
        lambda self, text: TermExtractionResult(
            terms=[TermCandidate(source="AD", target="候选译法")],
            usage=None,
        ),
    )
    active = MagicMock(job_id="job-candidate", document_id=context.document_id, pdf_hash=context.pdf_hash)
    other = MagicMock(job_id="other-job", document_id=context.document_id, pdf_hash=context.pdf_hash)
    calls = {"n": 0}

    def provider() -> object:
        calls["n"] += 1
        return active if calls["n"] == 1 else other

    ctx = _single_ctx(
        context=context,
        doc_dir=doc_dir,
        cache_dir=cache_dir,
        source_pdf=source_pdf,
        service=service,
        active_job_provider=provider,
    )

    with (
        patch("pdf_reader.sse_stream.run_translation", return_value=iter(_finish(_result(mono=ok_pdf)))),
        patch("pdf_reader.sse_stream.debug_trace"),
        managed_caplog.at_level(logging.WARNING, logger="pdf_reader.candidate"),
    ):
        output = list(generate(ctx))
    body = "".join(output)

    assert calls["n"] == 2
    assert '"type": "finish"' in body
    ctx.finish_job.assert_called_once_with("job-candidate")
    assert not (doc_dir / "term_candidates.json").exists()
    assert "candidate identity rejected at commit" in managed_caplog.text


def test_single_info_logs_carry_revision_and_candidate_summary(tmp_path, monkeypatch, managed_caplog):
    source_pdf = _pdf(tmp_path, ["AD appears here."], name="source.pdf")
    ok_pdf = _pdf(tmp_path, ["阿尔茨海默病 是诊断结果。"], name="ok.pdf")
    context, doc_dir = _strict_ctx(tmp_path, [("AD", "阿尔茨海默病")])
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    upstream = config.UpstreamRuntimeConfig(
        model=config.ModelRuntimeConfig(provider="deepseek", api_key="sk-test", model="deepseek-chat"),
        translation=config.TranslationRuntimeConfig(lang_in="en", lang_out="zh"),
        pdf=config.Pdf2zhRuntimeConfig(),
    )
    service = CandidateExtractionService(upstream.term_extraction, upstream.model)
    monkeypatch.setattr(
        TermExtractionClient,
        "extract_terms_with_usage",
        lambda self, text: TermExtractionResult(
            terms=[TermCandidate(source="AD", target="候选译法")],
            usage=TokenUsage(prompt_tokens=9, completion_tokens=4, total_tokens=13),
        ),
    )
    task_ctx = TaskContext(
        job_id="job-diag",
        document_id=context.document_id,
        pdf_hash=context.pdf_hash,
        page=1,
        status=STATUS_STARTED,
        glossary_revision="c" * 64,
    )
    ctx = _single_ctx(
        context=context,
        doc_dir=doc_dir,
        cache_dir=cache_dir,
        source_pdf=source_pdf,
        service=service,
        job_id="job-diag",
    )
    ctx.task_ctx = task_ctx

    with (
        patch("pdf_reader.sse_stream.run_translation", return_value=iter(_finish(_result(mono=ok_pdf)))),
        patch("pdf_reader.sse_stream.debug_trace"),
        managed_caplog.at_level(logging.INFO, logger="pdf_reader"),
    ):
        output = list(generate(ctx))

    assert '"type": "finish"' in "".join(output)
    text = managed_caplog.text
    assert f"rev={'c' * 12}" in text
    assert "candidate summary" in text
    assert "proposed=1" in text
    assert "kept=1" in text
    assert "event=candidate_prepare" in text
    assert "event=candidate_commit" in text
    assert "pending=1" in text
    assert "accepted=0" in text
    assert "rejected=0" in text
    assert "usage=prompt=9 completion=4 total=13" in text
    assert "候选译法" not in text


def test_diagnostics_function_failure_does_not_block_finish(tmp_path, monkeypatch, managed_caplog):
    source_pdf = _pdf(tmp_path, ["AD appears here."], name="source.pdf")
    ok_pdf = _pdf(tmp_path, ["阿尔茨海默病 是诊断结果。"], name="ok.pdf")
    context, doc_dir = _strict_ctx(tmp_path, [("AD", "阿尔茨海默病")])
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    service = MagicMock()
    service.prepare.return_value = _prepared()
    service.commit.return_value = _commit_report()
    ctx = _single_ctx(
        context=context,
        doc_dir=doc_dir,
        cache_dir=cache_dir,
        source_pdf=source_pdf,
        service=service,
    )

    with (
        patch(
            "pdf_reader.term_diagnostics.log_candidate_summary",
            side_effect=RuntimeError("candidate diagnostics boom"),
        ),
        patch(
            "pdf_reader.term_diagnostics.log_glossary_active_terms",
            side_effect=RuntimeError("glossary diagnostics boom"),
        ),
        patch("pdf_reader.sse_stream.run_translation", return_value=iter(_finish(_result(mono=ok_pdf)))),
        patch("pdf_reader.sse_stream.debug_trace"),
        managed_caplog.at_level(logging.WARNING, logger="pdf_reader"),
    ):
        output = list(generate(ctx))

    body = "".join(output)
    assert '"type": "finish"' in body
    ctx.replace_page.assert_called_once_with(str(ok_pdf))
    ctx.finish_job.assert_called_once_with("job-candidate")
    service.commit.assert_called_once()
    assert "diagnostics unavailable" in managed_caplog.text
    assert "diagnostics boom" not in managed_caplog.text


def test_batch_info_logs_carry_revision(managed_caplog, tmp_path):
    source_pdf = _pdf(tmp_path, ["AD page one", "TCS page two"], name="source.pdf")
    ok_pdf = _pdf(tmp_path, ["阿尔茨海默病 第一页", "外用糖皮质激素 第二页"], name="ok.pdf")
    context, doc_dir = _strict_ctx(tmp_path, [("AD", "阿尔茨海默病"), ("TCS", "外用糖皮质激素")])
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    service = MagicMock()
    service.prepare.return_value = _prepared()
    service.commit.return_value = _commit_report()
    ctx = _batch_ctx(
        context=context,
        doc_dir=doc_dir,
        cache_dir=cache_dir,
        source_pdf=source_pdf,
        service=service,
        page_indices=[0, 1],
        job_id="job-diag-batch",
    )
    ctx.task_ctx = TaskContext(
        job_id="job-diag-batch",
        document_id=context.document_id,
        pdf_hash=context.pdf_hash,
        from_page=1,
        to_page=2,
        status=STATUS_STARTED,
        glossary_revision="e" * 64,
    )

    with (
        patch("pdf_reader.sse_stream.run_translation", return_value=iter(_finish(_result(mono=ok_pdf)))),
        patch("pdf_reader.sse_stream.debug_trace"),
        managed_caplog.at_level(logging.INFO, logger="pdf_reader"),
    ):
        output = list(generate_batch(ctx))

    assert '"type": "finish"' in "".join(output)
    text = managed_caplog.text
    assert f"rev={'e' * 12}" in text
    assert "pages=1-2" in text
