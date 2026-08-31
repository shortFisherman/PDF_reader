"""P0-05 提交门集成测试：fake 上游 + 单页/批量有界重试、原子提交与清理。"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pymupdf
import pytest

from pdf_reader.file_hash import sha256
from pdf_reader.sse_stream import (
    GLOSSARY_COMPLIANCE_FAILED_CODE,
    GLOSSARY_VERIFICATION_UNAVAILABLE_CODE,
    GenerateBatchContext,
    GenerateContext,
    generate,
    generate_batch,
)
from pdf_reader.state import AppState
from pdf_reader.strict_glossary import StrictTranslationContext
from pdf_reader.task_logging import STATUS_STARTED, TaskContext, task_context_from_indices

_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]")


def _pdf(tmp_path: Path, texts: list[str], name: str = "doc.pdf") -> Path:
    """逐页插入文本；含 CJK 时使用 PyMuPDF 内置中文字体保证可提取。"""
    pdf_path = tmp_path / name
    doc = pymupdf.open()
    for text in texts:
        page = doc.new_page()
        if _CJK.search(text):
            page.insert_font(fontname="china-s")
        page.insert_text((72, 72), text, fontname="china-s" if _CJK.search(text) else "helv")
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def _strict_ctx(tmp_path: Path, rows: list[tuple[str, str]]) -> tuple[StrictTranslationContext, Path]:
    doc_dir = tmp_path / ("a" * 64)
    doc_dir.mkdir()
    context = StrictTranslationContext(
        document_dir=doc_dir,
        document_id="doc-12345678",
        pdf_hash=doc_dir.name,
        effective_glossary_path=None,
        effective_rows=tuple(rows),
    )
    return context, doc_dir


def _task_ctx(
    job_id: str,
    context: StrictTranslationContext,
    page_indices: list[int],
    *,
    glossary_revision: str = "",
) -> TaskContext:
    return task_context_from_indices(
        job_id,
        context.document_id,
        context.pdf_hash,
        page_indices,
        status=STATUS_STARTED,
        glossary_revision=glossary_revision,
    )


def _result(mono: Path | None = None, dual: Path | None = None) -> MagicMock:
    result = MagicMock()
    result.mono_pdf_path = str(mono) if mono is not None else None
    result.dual_pdf_path = str(dual) if dual is not None else None
    result.auto_extracted_glossary_path = None
    return result


def _finish_events(result: MagicMock) -> list[dict]:
    return [{"type": "finish", "stage": "generating_pdf", "translate_result": result, "token_usage": {}}]


def _finish_events_with_progress(result: MagicMock, overall: int) -> list[dict]:
    return [
        {
            "type": "progress_start",
            "stage": "layout_analysis",
            "overall_progress": 0,
            "stage_current": 0,
            "stage_total": 0,
        },
        {
            "type": "progress_update",
            "stage": "translating",
            "overall_progress": overall,
            "stage_current": 1,
            "stage_total": 1,
        },
        {"type": "finish", "stage": "generating_pdf", "translate_result": result, "token_usage": {}},
    ]


def _sse_events(body: str) -> list[dict]:
    events = []
    for line in body.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


def _blank_pdf(tmp_path: Path, pages: int, name: str = "blank.pdf") -> Path:
    pdf_path = tmp_path / name
    doc = pymupdf.open()
    for _ in range(pages):
        doc.new_page()
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def _single_ctx(
    *,
    tmp_path: Path,
    context: StrictTranslationContext,
    doc_dir: Path,
    job_id: str,
    cache_dir: Path,
    page: int = 0,
    state: AppState | None = None,
    source_pdf: Path | None = None,
    replace_page=None,
    merge_glossary=None,
    finish_job=None,
    fail_job=None,
    cancel_job=None,
    register_stream=None,
    unregister_stream=None,
    settings=None,
    glossary_revision="",
) -> GenerateContext:
    if replace_page is None:
        replace_page = MagicMock()
    if merge_glossary is None:
        merge_glossary = MagicMock()
    if finish_job is None:
        finish_job = MagicMock(return_value=True)
    if fail_job is None:
        fail_job = MagicMock(return_value=True)
    if cancel_job is None:
        cancel_job = MagicMock(return_value=True)
    if state is None:
        if source_pdf is None:
            extract_page = MagicMock(return_value=Path("/fake/page.pdf"))
        else:
            extract_page = MagicMock(return_value=source_pdf)
    else:
        snapshot = state.translation_snapshot()

        def extract_page(p: int, tmpdir: Path, func) -> Path:
            return state.extract_page(p, tmpdir, func, snapshot.document_id)

        if isinstance(replace_page, MagicMock):
            replace_page = MagicMock(side_effect=lambda path: state.replace_page(path, page, snapshot.document_id))
    return GenerateContext(
        settings=settings if settings is not None else MagicMock(),
        job_id=job_id,
        finish_job=finish_job,
        fail_job=fail_job,
        cancel_job=cancel_job,
        replace_page=replace_page,
        merge_glossary=merge_glossary,
        glossary_cache_path=doc_dir,
        page=page,
        glossary_paths=None,
        cache_dir=cache_dir,
        extract_page=extract_page,
        strict_context=context,
        task_ctx=_task_ctx(job_id, context, [page], glossary_revision=glossary_revision),
        register_stream=register_stream,
        unregister_stream=unregister_stream,
    )


def _batch_ctx(
    *,
    tmp_path: Path,
    context: StrictTranslationContext,
    doc_dir: Path,
    job_id: str,
    cache_dir: Path,
    page_indices: list[int],
    from_page: int = 1,
    to_page: int = 1,
    state: AppState | None = None,
    source_pdf: Path | None = None,
    replace_pages=None,
    merge_glossary=None,
    finish_job=None,
    fail_job=None,
    cancel_job=None,
    glossary_revision="",
) -> GenerateBatchContext:
    if replace_pages is None:
        replace_pages = MagicMock()
    if merge_glossary is None:
        merge_glossary = MagicMock()
    if finish_job is None:
        finish_job = MagicMock(return_value=True)
    if fail_job is None:
        fail_job = MagicMock(return_value=True)
    if cancel_job is None:
        cancel_job = MagicMock(return_value=True)
    if state is None:
        if source_pdf is None:
            extract_pages = MagicMock(return_value=Path("/fake/pages.pdf"))
        else:
            extract_pages = MagicMock(return_value=source_pdf)
    else:
        snapshot = state.translation_snapshot()

        def extract_pages(indices: list[int], tmpdir: Path, func) -> Path:
            return state.extract_pages(indices, tmpdir, func, snapshot.document_id)

        if isinstance(replace_pages, MagicMock):
            replace_pages = MagicMock(
                side_effect=lambda path: state.replace_pages(path, page_indices, snapshot.document_id)
            )
    return GenerateBatchContext(
        settings=MagicMock(),
        job_id=job_id,
        finish_job=finish_job,
        fail_job=fail_job,
        cancel_job=cancel_job,
        from_page=from_page,
        to_page=to_page,
        page_indices=page_indices,
        replace_pages=replace_pages,
        merge_glossary=merge_glossary,
        glossary_cache_path=doc_dir,
        glossary_paths=None,
        cache_dir=cache_dir,
        extract_pages=extract_pages,
        strict_context=context,
        task_ctx=_task_ctx(job_id, context, page_indices, glossary_revision=glossary_revision),
    )


def test_single_wrong_then_wrong_no_commit_stable_code_and_right_pdf_unchanged(tmp_path):
    source_pdf = _pdf(tmp_path, ["AD appears here."], name="source.pdf")
    wrong_pdf = _pdf(tmp_path, ["AD 出现了。"], name="wrong.pdf")
    context, doc_dir = _strict_ctx(tmp_path, [("AD", "阿尔茨海默病")])
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    state = AppState(cache_dir)
    try:
        state.open_pdf(str(source_pdf), sha256)
        job_id = "job-single-bad"
        settings_calls: list = []

        def fake_run(settings, file, flow_label="", task_ctx=None) -> Iterator[dict]:
            settings_calls.append(settings)
            return iter(_finish_events(_result(mono=wrong_pdf)))

        replace_page = MagicMock()
        merge_glossary = MagicMock()
        finish_job = MagicMock(return_value=True)
        fail_job = MagicMock(return_value=True)
        register_stream = MagicMock()
        unregister_stream = MagicMock()
        ctx = _single_ctx(
            tmp_path=tmp_path,
            context=context,
            doc_dir=doc_dir,
            job_id=job_id,
            cache_dir=cache_dir,
            state=state,
            source_pdf=source_pdf,
            replace_page=replace_page,
            merge_glossary=merge_glossary,
            finish_job=finish_job,
            fail_job=fail_job,
            register_stream=register_stream,
            unregister_stream=unregister_stream,
        )
        right_path = state.glossary_cache_path / "right.pdf"
        before = right_path.read_bytes()
        with (
            patch("pdf_reader.sse_stream.run_translation", side_effect=fake_run),
            patch("pdf_reader.sse_stream.debug_trace"),
        ):
            output = list(generate(ctx))
        body = "".join(output)

        assert len(settings_calls) == 2
        assert f'"code": "{GLOSSARY_COMPLIANCE_FAILED_CODE}"' in body
        assert '"type": "finish"' not in body
        replace_page.assert_not_called()
        merge_glossary.assert_not_called()
        finish_job.assert_not_called()
        fail_job.assert_called_once_with(job_id)
        assert right_path.read_bytes() == before
        assert register_stream.call_count == 2
        assert unregister_stream.call_count == 3
        assert all(call.args[0] == job_id for call in register_stream.call_args_list)
        assert not list(cache_dir.glob("pdf-reader-translation-*"))
    finally:
        state._close_docs()


def test_single_first_wrong_second_correct_commits_only_second_and_retries_once(tmp_path):
    from pdf_reader import config
    from pdf_reader.translation_settings import build_settings

    source_pdf = _pdf(tmp_path, ["AD appears here."], name="source.pdf")
    wrong_pdf = _pdf(tmp_path, ["AD 出现了。"], name="wrong.pdf")
    ok_pdf = _pdf(tmp_path, ["阿尔茨海默病 是诊断结果。"], name="ok.pdf")
    context, doc_dir = _strict_ctx(tmp_path, [("AD", "阿尔茨海默病")])
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    job_id = "job-single-retry"
    captured: list[dict] = []
    settings = build_settings(
        config.UpstreamRuntimeConfig(
            model=config.ModelRuntimeConfig(
                provider="deepseek",
                api_key="sk-test-key",
                model="deepseek-v4-flash",
            ),
            translation=config.TranslationRuntimeConfig(lang_in="en", lang_out="zh"),
            pdf=config.Pdf2zhRuntimeConfig(),
        ),
        "x.pdf",
        user_prompt="page prompt",
    )

    def fake_run(settings, file, flow_label="", task_ctx=None) -> Iterator[dict]:
        attempt = len(captured) + 1
        captured.append(
            {
                "settings": settings,
                "output": str(settings.translation.output),
                "flow_label": flow_label,
                "task_ctx": task_ctx,
                "pdf": str(file),
            }
        )
        pdf = wrong_pdf if attempt == 1 else ok_pdf
        return iter(_finish_events_with_progress(_result(mono=pdf), 100))

    replace_page = MagicMock()
    merge_glossary = MagicMock()
    finish_job = MagicMock(return_value=True)
    fail_job = MagicMock(return_value=True)
    register_stream = MagicMock()
    unregister_stream = MagicMock()
    ctx = _single_ctx(
        tmp_path=tmp_path,
        context=context,
        doc_dir=doc_dir,
        job_id=job_id,
        cache_dir=cache_dir,
        source_pdf=source_pdf,
        settings=settings,
        replace_page=replace_page,
        merge_glossary=merge_glossary,
        finish_job=finish_job,
        fail_job=fail_job,
        register_stream=register_stream,
        unregister_stream=unregister_stream,
    )

    with (
        patch("pdf_reader.sse_stream.run_translation", side_effect=fake_run),
        patch("pdf_reader.sse_stream.debug_trace"),
    ):
        output = list(generate(ctx))
    body = "".join(output)

    assert len(captured) == 2
    assert '"stage": "glossary_retry"' in body
    assert '"type": "finish"' in body
    events = _sse_events(body)
    progress_values = [e["progress"] for e in events if e.get("type") == "progress"]
    assert progress_values == sorted(progress_values), progress_values
    retry_event = next(e for e in events if e.get("stage") == "glossary_retry")
    assert retry_event["progress"] >= 95
    assert retry_event["stage_current"] == 2
    assert retry_event["stage_total"] == 2
    retry_index = events.index(retry_event)
    for e in events[retry_index + 1 :]:
        if e.get("type") == "progress" and e.get("stage") != "finish":
            assert 95 <= e["progress"] <= 99, e
    assert any(
        e.get("type") == "progress" and e.get("stage") == "generating_pdf" and e["progress"] == 99 for e in events
    )
    assert any(
        e.get("type") == "progress" and e.get("stage") == "generating_pdf" and e["progress"] == 95 for e in events
    )
    assert any(e.get("type") == "progress" and e.get("stage") == "translating" and e["progress"] == 95 for e in events)
    assert any(e.get("type") == "progress" and e.get("stage") == "translating" and e["progress"] == 99 for e in events)
    assert any(e.get("type") == "progress" and e.get("stage") == "finish" and e["progress"] == 100 for e in events)
    assert events[-1] == {"type": "finish", "progress": 100}
    replace_page.assert_called_once_with(str(ok_pdf))
    merge_glossary.assert_called_once()
    finish_job.assert_called_once_with(job_id)
    fail_job.assert_not_called()
    assert register_stream.call_count == 2
    assert unregister_stream.call_count == 3
    assert captured[0]["output"] != captured[1]["output"]
    assert captured[1]["output"].endswith("attempt-2" + "\\output") or captured[1]["output"].endswith(
        "attempt-2/output"
    )
    assert captured[0]["pdf"] == captured[1]["pdf"]
    assert captured[0]["task_ctx"].job_id == captured[1]["task_ctx"].job_id == job_id
    assert captured[0]["flow_label"] == captured[1]["flow_label"] == "page=1"
    prompt_1 = captured[0]["settings"].translation.custom_system_prompt
    prompt_2 = captured[1]["settings"].translation.custom_system_prompt
    assert isinstance(prompt_1, str) and isinstance(prompt_2, str)
    assert "[权威术语约束]" in prompt_1 and "[权威术语约束]" in prompt_2
    assert "[术语合规纠错]" in prompt_2 and "[术语合规纠错]" not in prompt_1
    assert '"阿尔茨海默病"' in prompt_2
    assert "[术语合规纠错]" not in settings.translation.custom_system_prompt
    assert not list(cache_dir.glob("pdf-reader-translation-*"))


def test_single_first_correct_one_call_one_commit(tmp_path):
    source_pdf = _pdf(tmp_path, ["TCS matters."], name="source.pdf")
    ok_pdf = _pdf(tmp_path, ["外用糖皮质激素 方案。"], name="ok.pdf")
    context, doc_dir = _strict_ctx(tmp_path, [("TCS", "外用糖皮质激素")])
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    calls = []

    def fake_run(settings, file, flow_label="", task_ctx=None) -> Iterator[dict]:
        calls.append(settings)
        return iter(_finish_events(_result(mono=ok_pdf)))

    replace_page = MagicMock()
    merge_glossary = MagicMock()
    finish_job = MagicMock(return_value=True)
    fail_job = MagicMock(return_value=True)
    ctx = _single_ctx(
        tmp_path=tmp_path,
        context=context,
        doc_dir=doc_dir,
        job_id="job-single-ok",
        cache_dir=cache_dir,
        source_pdf=source_pdf,
        replace_page=replace_page,
        merge_glossary=merge_glossary,
        finish_job=finish_job,
        fail_job=fail_job,
    )

    with (
        patch("pdf_reader.sse_stream.run_translation", side_effect=fake_run),
        patch("pdf_reader.sse_stream.debug_trace"),
    ):
        output = list(generate(ctx))
    body = "".join(output)

    assert len(calls) == 1
    assert '"type": "finish"' in body
    assert "glossary_retry" not in body
    replace_page.assert_called_once_with(str(ok_pdf))
    merge_glossary.assert_called_once()
    finish_job.assert_called_once_with("job-single-ok")
    fail_job.assert_not_called()


def test_no_active_terms_skips_verification_and_retry_cost(tmp_path):
    source_pdf = _pdf(tmp_path, ["plain text without terms"], name="source.pdf")
    context, doc_dir = _strict_ctx(tmp_path, [("NOPE", "不存在的译法")])
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    calls = []

    def fake_run(settings, file, flow_label="", task_ctx=None) -> Iterator[dict]:
        calls.append(settings)
        # 路径缺失：若真的读取译文做合规，必然 unavailable；无活跃词条时不应读取。
        return iter(_finish_events(_result()))

    replace_page = MagicMock()
    merge_glossary = MagicMock()
    ctx = _single_ctx(
        tmp_path=tmp_path,
        context=context,
        doc_dir=doc_dir,
        job_id="job-no-terms",
        cache_dir=cache_dir,
        source_pdf=source_pdf,
        replace_page=replace_page,
        merge_glossary=merge_glossary,
    )

    with (
        patch("pdf_reader.sse_stream.run_translation", side_effect=fake_run),
        patch("pdf_reader.sse_stream.terminology_compliance.verify_translated_pdf") as verify,
        patch("pdf_reader.sse_stream.debug_trace"),
    ):
        output = list(generate(ctx))
    body = "".join(output)

    assert len(calls) == 1
    verify.assert_not_called()
    assert '"type": "finish"' in body
    assert GLOSSARY_VERIFICATION_UNAVAILABLE_CODE not in body
    replace_page.assert_not_called()
    merge_glossary.assert_called_once()


def test_single_source_empty_text_with_rows_unavailable_before_upstream(tmp_path):
    blank_pdf = _blank_pdf(tmp_path, 1, name="blank-source.pdf")
    context, doc_dir = _strict_ctx(tmp_path, [("AD", "阿尔茨海默病")])
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    replace_page = MagicMock()
    merge_glossary = MagicMock()
    fail_job = MagicMock(return_value=True)
    ctx = _single_ctx(
        tmp_path=tmp_path,
        context=context,
        doc_dir=doc_dir,
        job_id="job-src-empty",
        cache_dir=cache_dir,
        source_pdf=blank_pdf,
        replace_page=replace_page,
        merge_glossary=merge_glossary,
        fail_job=fail_job,
    )

    with patch("pdf_reader.sse_stream.run_translation") as run, patch("pdf_reader.sse_stream.debug_trace"):
        output = list(generate(ctx))
    body = "".join(output)

    assert f'"code": "{GLOSSARY_VERIFICATION_UNAVAILABLE_CODE}"' in body
    assert '"type": "finish"' not in body
    run.assert_not_called()
    replace_page.assert_not_called()
    merge_glossary.assert_not_called()
    fail_job.assert_called_once_with("job-src-empty")
    assert not list(cache_dir.glob("pdf-reader-translation-*"))


def test_single_source_corrupt_with_rows_unavailable_before_upstream(tmp_path):
    corrupt_pdf = tmp_path / "corrupt-source.pdf"
    corrupt_pdf.write_bytes(b"broken")
    context, doc_dir = _strict_ctx(tmp_path, [("AD", "阿尔茨海默病")])
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    replace_page = MagicMock()
    merge_glossary = MagicMock()
    fail_job = MagicMock(return_value=True)
    ctx = _single_ctx(
        tmp_path=tmp_path,
        context=context,
        doc_dir=doc_dir,
        job_id="job-src-corrupt",
        cache_dir=cache_dir,
        source_pdf=corrupt_pdf,
        replace_page=replace_page,
        merge_glossary=merge_glossary,
        fail_job=fail_job,
    )

    with patch("pdf_reader.sse_stream.run_translation") as run, patch("pdf_reader.sse_stream.debug_trace"):
        output = list(generate(ctx))
    body = "".join(output)

    assert f'"code": "{GLOSSARY_VERIFICATION_UNAVAILABLE_CODE}"' in body
    assert '"type": "finish"' not in body
    run.assert_not_called()
    replace_page.assert_not_called()
    merge_glossary.assert_not_called()
    fail_job.assert_called_once_with("job-src-corrupt")
    assert not list(cache_dir.glob("pdf-reader-translation-*"))


def test_batch_source_empty_text_with_rows_unavailable_before_upstream(tmp_path):
    blank_pdf = _blank_pdf(tmp_path, 2, name="blank-batch.pdf")
    context, doc_dir = _strict_ctx(tmp_path, [("AD", "阿尔茨海默病")])
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    replace_pages = MagicMock()
    merge_glossary = MagicMock()
    fail_job = MagicMock(return_value=True)
    ctx = _batch_ctx(
        tmp_path=tmp_path,
        context=context,
        doc_dir=doc_dir,
        job_id="job-batch-src-empty",
        cache_dir=cache_dir,
        page_indices=[0, 1],
        from_page=1,
        to_page=2,
        source_pdf=blank_pdf,
        replace_pages=replace_pages,
        merge_glossary=merge_glossary,
        fail_job=fail_job,
    )

    with patch("pdf_reader.sse_stream.run_translation") as run, patch("pdf_reader.sse_stream.debug_trace"):
        output = list(generate_batch(ctx))
    body = "".join(output)

    assert f'"code": "{GLOSSARY_VERIFICATION_UNAVAILABLE_CODE}"' in body
    assert '"type": "finish"' not in body
    run.assert_not_called()
    replace_pages.assert_not_called()
    merge_glossary.assert_not_called()
    fail_job.assert_called_once_with("job-batch-src-empty")
    assert not list(cache_dir.glob("pdf-reader-translation-*"))


def test_rows_empty_blank_source_zero_cost_translation(tmp_path):
    blank_pdf = _blank_pdf(tmp_path, 1, name="blank-no-rows.pdf")
    context, doc_dir = _strict_ctx(tmp_path, [])
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    calls = []

    def fake_run(settings, file, flow_label="", task_ctx=None) -> Iterator[dict]:
        calls.append(settings)
        return iter(_finish_events(_result()))

    replace_page = MagicMock()
    merge_glossary = MagicMock()
    ctx = _single_ctx(
        tmp_path=tmp_path,
        context=context,
        doc_dir=doc_dir,
        job_id="job-rows-empty",
        cache_dir=cache_dir,
        source_pdf=blank_pdf,
        replace_page=replace_page,
        merge_glossary=merge_glossary,
    )

    with (
        patch("pdf_reader.sse_stream.run_translation", side_effect=fake_run),
        patch("pdf_reader.sse_stream.terminology_compliance.verify_translated_pdf") as verify,
        patch("pdf_reader.sse_stream.debug_trace"),
    ):
        output = list(generate(ctx))
    body = "".join(output)

    assert len(calls) == 1
    verify.assert_not_called()
    assert '"type": "finish"' in body
    assert GLOSSARY_VERIFICATION_UNAVAILABLE_CODE not in body
    replace_page.assert_not_called()
    merge_glossary.assert_called_once()


def test_single_missing_output_path_unavailable_no_commit(tmp_path):
    source_pdf = _pdf(tmp_path, ["AD appears."], name="source.pdf")
    context, doc_dir = _strict_ctx(tmp_path, [("AD", "阿尔茨海默病")])
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    calls = []

    def fake_run(settings, file, flow_label="", task_ctx=None) -> Iterator[dict]:
        calls.append(settings)
        return iter(_finish_events(_result()))

    replace_page = MagicMock()
    merge_glossary = MagicMock()
    fail_job = MagicMock(return_value=True)
    ctx = _single_ctx(
        tmp_path=tmp_path,
        context=context,
        doc_dir=doc_dir,
        job_id="job-missing",
        cache_dir=cache_dir,
        source_pdf=source_pdf,
        replace_page=replace_page,
        merge_glossary=merge_glossary,
        fail_job=fail_job,
    )

    with (
        patch("pdf_reader.sse_stream.run_translation", side_effect=fake_run),
        patch("pdf_reader.sse_stream.debug_trace"),
    ):
        output = list(generate(ctx))
    body = "".join(output)

    assert len(calls) == 1
    assert f'"code": "{GLOSSARY_VERIFICATION_UNAVAILABLE_CODE}"' in body
    assert '"type": "finish"' not in body
    replace_page.assert_not_called()
    merge_glossary.assert_not_called()
    fail_job.assert_called_once_with("job-missing")


def test_single_dual_path_fallback_verified_and_committed(tmp_path):
    source_pdf = _pdf(tmp_path, ["AD appears."], name="source.pdf")
    ok_pdf = _pdf(tmp_path, ["阿尔茨海默病。"], name="ok-dual.pdf")
    context, doc_dir = _strict_ctx(tmp_path, [("AD", "阿尔茨海默病")])
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    def fake_run(settings, file, flow_label="", task_ctx=None) -> Iterator[dict]:
        return iter(_finish_events(_result(mono=None, dual=ok_pdf)))

    replace_page = MagicMock()
    ctx = _single_ctx(
        tmp_path=tmp_path,
        context=context,
        doc_dir=doc_dir,
        job_id="job-dual",
        cache_dir=cache_dir,
        source_pdf=source_pdf,
        replace_page=replace_page,
    )

    with (
        patch("pdf_reader.sse_stream.run_translation", side_effect=fake_run),
        patch("pdf_reader.sse_stream.debug_trace"),
    ):
        list(generate(ctx))

    replace_page.assert_called_once_with(str(ok_pdf))


def test_single_corrupt_output_unavailable_no_commit(tmp_path):
    source_pdf = _pdf(tmp_path, ["AD appears."], name="source.pdf")
    corrupt_pdf = tmp_path / "corrupt.pdf"
    corrupt_pdf.write_bytes(b"broken")
    context, doc_dir = _strict_ctx(tmp_path, [("AD", "阿尔茨海默病")])
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    def fake_run(settings, file, flow_label="", task_ctx=None) -> Iterator[dict]:
        return iter(_finish_events(_result(mono=corrupt_pdf)))

    replace_page = MagicMock()
    merge_glossary = MagicMock()
    ctx = _single_ctx(
        tmp_path=tmp_path,
        context=context,
        doc_dir=doc_dir,
        job_id="job-corrupt",
        cache_dir=cache_dir,
        source_pdf=source_pdf,
        replace_page=replace_page,
        merge_glossary=merge_glossary,
    )

    with (
        patch("pdf_reader.sse_stream.run_translation", side_effect=fake_run),
        patch("pdf_reader.sse_stream.debug_trace"),
    ):
        output = list(generate(ctx))
    body = "".join(output)

    assert f'"code": "{GLOSSARY_VERIFICATION_UNAVAILABLE_CODE}"' in body
    assert '"type": "finish"' not in body
    replace_page.assert_not_called()
    merge_glossary.assert_not_called()


def test_batch_wrong_then_correct_atomic_retry_commits_only_second(tmp_path):
    source_pdf = _pdf(tmp_path, ["AD on page one", "TCS on page two"], name="source.pdf")
    wrong_pdf = _pdf(tmp_path, ["AD 第一页", "TCS 第二页"], name="wrong-batch.pdf")
    ok_pdf = _pdf(tmp_path, ["阿尔茨海默病 第一页", "外用糖皮质激素 第二页"], name="ok-batch.pdf")
    context, doc_dir = _strict_ctx(tmp_path, [("AD", "阿尔茨海默病"), ("TCS", "外用糖皮质激素")])
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    calls = []

    def fake_run(settings, file, flow_label="", task_ctx=None) -> Iterator[dict]:
        calls.append(settings)
        pdf = wrong_pdf if len(calls) == 1 else ok_pdf
        return iter(_finish_events_with_progress(_result(mono=pdf), 100))

    replace_pages = MagicMock()
    merge_glossary = MagicMock()
    finish_job = MagicMock(return_value=True)
    fail_job = MagicMock(return_value=True)
    ctx = _batch_ctx(
        tmp_path=tmp_path,
        context=context,
        doc_dir=doc_dir,
        job_id="job-batch-retry",
        cache_dir=cache_dir,
        page_indices=[0, 1],
        from_page=1,
        to_page=2,
        source_pdf=source_pdf,
        replace_pages=replace_pages,
        merge_glossary=merge_glossary,
        finish_job=finish_job,
        fail_job=fail_job,
    )

    with (
        patch("pdf_reader.sse_stream.run_translation", side_effect=fake_run),
        patch("pdf_reader.sse_stream.merge_glossary_only") as merge_only,
        patch("pdf_reader.sse_stream.debug_trace"),
    ):
        output = list(generate_batch(ctx))
    body = "".join(output)

    assert len(calls) == 2
    assert '"type": "batch_info"' in body
    assert '"stage": "glossary_retry"' in body
    assert '"type": "finish"' in body
    events = _sse_events(body)
    progress_values = [e["progress"] for e in events if e.get("type") == "progress"]
    assert progress_values == sorted(progress_values), progress_values
    retry_event = next(e for e in events if e.get("stage") == "glossary_retry")
    assert retry_event["progress"] >= 95
    assert retry_event["stage_current"] == 2
    assert retry_event["stage_total"] == 2
    assert any(
        e.get("type") == "progress" and e.get("stage") == "generating_pdf" and e["progress"] == 99 for e in events
    )
    assert any(
        e.get("type") == "progress" and e.get("stage") == "generating_pdf" and e["progress"] == 95 for e in events
    )
    assert any(e.get("type") == "progress" and e.get("stage") == "translating" and e["progress"] == 95 for e in events)
    assert any(e.get("type") == "progress" and e.get("stage") == "translating" and e["progress"] == 99 for e in events)
    assert any(e.get("type") == "progress" and e.get("stage") == "finish" and e["progress"] == 100 for e in events)
    assert events[-1] == {"type": "finish", "progress": 100}
    replace_pages.assert_called_once_with(str(ok_pdf))
    merge_only.assert_called_once()
    finish_job.assert_called_once_with("job-batch-retry")
    fail_job.assert_not_called()
    assert not list(cache_dir.glob("pdf-reader-translation-*"))


def test_batch_wrong_then_wrong_atomic_no_commit_and_right_pdf_unchanged(tmp_path):
    source_pdf = _pdf(tmp_path, ["AD on page one", "TCS on page two"], name="source.pdf")
    wrong_pdf = _pdf(tmp_path, ["AD 第一页", "TCS 第二页"], name="wrong-batch.pdf")
    context, doc_dir = _strict_ctx(tmp_path, [("AD", "阿尔茨海默病"), ("TCS", "外用糖皮质激素")])
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    state = AppState(cache_dir)
    try:
        state.open_pdf(str(source_pdf), sha256)
        job_id = "job-batch-bad"

        def fake_run(settings, file, flow_label="", task_ctx=None) -> Iterator[dict]:
            return iter(_finish_events(_result(mono=wrong_pdf)))

        merge_glossary = MagicMock()
        finish_job = MagicMock(return_value=True)
        fail_job = MagicMock(return_value=True)
        ctx = _batch_ctx(
            tmp_path=tmp_path,
            context=context,
            doc_dir=doc_dir,
            job_id=job_id,
            cache_dir=cache_dir,
            page_indices=[0, 1],
            from_page=1,
            to_page=2,
            state=state,
            source_pdf=source_pdf,
            merge_glossary=merge_glossary,
            finish_job=finish_job,
            fail_job=fail_job,
        )
        right_path = state.glossary_cache_path / "right.pdf"
        before = right_path.read_bytes()
        with (
            patch("pdf_reader.sse_stream.run_translation", side_effect=fake_run),
            patch("pdf_reader.sse_stream.merge_glossary_only") as merge_only,
            patch("pdf_reader.sse_stream.debug_trace"),
        ):
            output = list(generate_batch(ctx))
        body = "".join(output)

        assert f'"code": "{GLOSSARY_COMPLIANCE_FAILED_CODE}"' in body
        assert '"type": "finish"' not in body
        merge_only.assert_not_called()
        merge_glossary.assert_not_called()
        finish_job.assert_not_called()
        fail_job.assert_called_once_with(job_id)
        assert right_path.read_bytes() == before
        assert not list(cache_dir.glob("pdf-reader-translation-*"))
    finally:
        state._close_docs()


def test_batch_page_count_mismatch_unavailable_no_commit(tmp_path):
    source_pdf = _pdf(tmp_path, ["AD on page one", "AD again on two"], name="source.pdf")
    single_page_pdf = _pdf(tmp_path, ["阿尔茨海默病"], name="one-page.pdf")
    context, doc_dir = _strict_ctx(tmp_path, [("AD", "阿尔茨海默病")])
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    def fake_run(settings, file, flow_label="", task_ctx=None) -> Iterator[dict]:
        return iter(_finish_events(_result(mono=single_page_pdf)))

    replace_pages = MagicMock()
    merge_glossary = MagicMock()
    ctx = _batch_ctx(
        tmp_path=tmp_path,
        context=context,
        doc_dir=doc_dir,
        job_id="job-batch-mismatch",
        cache_dir=cache_dir,
        page_indices=[0, 1],
        from_page=1,
        to_page=2,
        source_pdf=source_pdf,
        replace_pages=replace_pages,
        merge_glossary=merge_glossary,
    )

    with (
        patch("pdf_reader.sse_stream.run_translation", side_effect=fake_run),
        patch("pdf_reader.sse_stream.debug_trace"),
    ):
        output = list(generate_batch(ctx))
    body = "".join(output)

    assert f'"code": "{GLOSSARY_VERIFICATION_UNAVAILABLE_CODE}"' in body
    assert '"type": "finish"' not in body
    replace_pages.assert_not_called()
    merge_glossary.assert_not_called()


def test_disconnect_mid_attempt_cancels_worker_and_cleans_workspace(tmp_path):
    import asyncio
    from collections.abc import AsyncIterator

    source_pdf = _pdf(tmp_path, ["AD appears."], name="source.pdf")
    context, doc_dir = _strict_ctx(tmp_path, [("AD", "阿尔茨海默病")])
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    async def slow_source(settings, file) -> AsyncIterator[dict]:
        yield {"type": "progress_start", "stage": "layout_analysis"}
        await asyncio.sleep(0.3)
        yield {"type": "finish", "translate_result": _result(mono=source_pdf)}

    replace_page = MagicMock()
    cancel_job = MagicMock(return_value=True)
    fail_job = MagicMock(return_value=True)
    ctx = _single_ctx(
        tmp_path=tmp_path,
        context=context,
        doc_dir=doc_dir,
        job_id="job-disconnect",
        cache_dir=cache_dir,
        source_pdf=source_pdf,
        replace_page=replace_page,
        cancel_job=cancel_job,
        fail_job=fail_job,
    )

    with (
        patch("pdf_reader.translation_orchestrator.do_translate_async_stream", slow_source),
        patch("pdf_reader.sse_stream.debug_trace"),
    ):
        gen = generate(ctx)
        next(gen)
        gen.close()

    assert not list(cache_dir.glob("pdf-reader-translation-*"))
    replace_page.assert_not_called()
    cancel_job.assert_called_once_with("job-disconnect")
    fail_job.assert_not_called()


def test_compliance_logs_do_not_leak_terms_targets_or_paths(tmp_path, managed_caplog):
    import logging

    source_pdf = _pdf(tmp_path, ["SECRET-SOURCE-TERM appears."], name="source.pdf")
    wrong_pdf = _pdf(tmp_path, ["SECRET-SOURCE-TERM 出现了。"], name="wrong.pdf")
    context, doc_dir = _strict_ctx(tmp_path, [("SECRET-SOURCE-TERM", "秘密目标译法")])
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    def fake_run(settings, file, flow_label="", task_ctx=None) -> Iterator[dict]:
        return iter(_finish_events(_result(mono=wrong_pdf)))

    ctx = _single_ctx(
        tmp_path=tmp_path,
        context=context,
        doc_dir=doc_dir,
        job_id="job-secret",
        cache_dir=cache_dir,
        source_pdf=source_pdf,
    )

    with (
        patch("pdf_reader.sse_stream.run_translation", side_effect=fake_run),
        patch("pdf_reader.sse_stream.debug_trace"),
    ):
        with managed_caplog.at_level(logging.INFO, logger="pdf_reader.translate"):
            list(generate(ctx))

    text = managed_caplog.text
    assert "SECRET-SOURCE-TERM" not in text
    assert "秘密目标译法" not in text
    assert str(wrong_pdf) not in text
    assert "Traceback" not in text


@pytest.mark.integration
def test_coordinator_release_and_cleanup_after_compliance_failure(tmp_path):
    """真实 coordinator：最终失败后 active_job 释放为 None，任务槽可复用。"""
    from pdf_reader.translation_coordinator import TranslationCoordinator

    source_pdf = _pdf(tmp_path, ["AD appears."], name="source.pdf")
    wrong_pdf = _pdf(tmp_path, ["AD 出现了。"], name="wrong.pdf")
    context, doc_dir = _strict_ctx(tmp_path, [("AD", "阿尔茨海默病")])
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    coordinator = TranslationCoordinator()
    job = coordinator.start(context.document_id, [0], pdf_hash=context.pdf_hash)

    def fake_run(settings, file, flow_label="", task_ctx=None) -> Iterator[dict]:
        return iter(_finish_events(_result(mono=wrong_pdf)))

    ctx = _single_ctx(
        tmp_path=tmp_path,
        context=context,
        doc_dir=doc_dir,
        job_id=job.job_id,
        cache_dir=cache_dir,
        source_pdf=source_pdf,
        finish_job=coordinator.finish,
        fail_job=coordinator.fail,
        cancel_job=coordinator.cancel,
        register_stream=coordinator.register_stream,
        unregister_stream=coordinator.unregister_stream,
    )

    with (
        patch("pdf_reader.sse_stream.run_translation", side_effect=fake_run),
        patch("pdf_reader.sse_stream.debug_trace"),
    ):
        list(generate(ctx))

    assert coordinator.active_job is None
    assert coordinator.is_busy is False
    assert not list(cache_dir.glob("pdf-reader-translation-*"))


def test_single_compliance_logs_stable_events_and_revision(tmp_path, managed_caplog):
    source_pdf = _pdf(tmp_path, ["AD appears here."], name="source.pdf")
    wrong_pdf = _pdf(tmp_path, ["AD 出现了。"], name="wrong.pdf")
    ok_pdf = _pdf(tmp_path, ["阿尔茨海默病 是诊断结果。"], name="ok.pdf")
    context, doc_dir = _strict_ctx(tmp_path, [("AD", "阿尔茨海默病")])
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    calls: list[str] = []

    def fake_run(settings, file, flow_label="", task_ctx=None) -> Iterator[dict]:
        calls.append("run")
        pdf = wrong_pdf if len(calls) == 1 else ok_pdf
        return iter(_finish_events(_result(mono=pdf)))

    replace_page = MagicMock()
    ctx = _single_ctx(
        tmp_path=tmp_path,
        context=context,
        doc_dir=doc_dir,
        job_id="job-diag-retry",
        cache_dir=cache_dir,
        source_pdf=source_pdf,
        replace_page=replace_page,
        glossary_revision="d" * 64,
    )

    with (
        patch("pdf_reader.sse_stream.run_translation", side_effect=fake_run),
        patch("pdf_reader.sse_stream.debug_trace"),
        managed_caplog.at_level(logging.INFO, logger="pdf_reader"),
    ):
        output = list(generate(ctx))

    body = "".join(output)
    assert '"type": "finish"' in body
    text = managed_caplog.text
    assert f"rev={'d' * 12}" in text
    assert "event=glossary_active_terms active=1 sources=1" in text
    assert "event=compliance_fail attempt=1" in text
    assert "event=compliance_retry_scheduled attempt=1" in text
    assert "event=compliance_pass attempt=2" in text
    assert "SECRET" not in text


def test_batch_compliance_final_failure_logs_stable_event_and_code(tmp_path, managed_caplog):
    source_pdf = _pdf(tmp_path, ["AD on page one", "TCS on page two"], name="source.pdf")
    wrong_pdf = _pdf(tmp_path, ["AD 第一页", "TCS 第二页"], name="wrong-batch.pdf")
    context, doc_dir = _strict_ctx(tmp_path, [("AD", "阿尔茨海默病"), ("TCS", "外用糖皮质激素")])
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    def fake_run(settings, file, flow_label="", task_ctx=None) -> Iterator[dict]:
        return iter(_finish_events(_result(mono=wrong_pdf)))

    ctx = _batch_ctx(
        tmp_path=tmp_path,
        context=context,
        doc_dir=doc_dir,
        job_id="job-batch-diag-fail",
        cache_dir=cache_dir,
        page_indices=[0, 1],
        from_page=1,
        to_page=2,
        source_pdf=source_pdf,
        glossary_revision="9" * 64,
    )

    with (
        patch("pdf_reader.sse_stream.run_translation", side_effect=fake_run),
        patch("pdf_reader.sse_stream.debug_trace"),
        managed_caplog.at_level(logging.INFO, logger="pdf_reader"),
    ):
        output = list(generate_batch(ctx))

    body = "".join(output)
    assert f'"code": "{GLOSSARY_COMPLIANCE_FAILED_CODE}"' in body
    text = managed_caplog.text
    assert f"rev={'9' * 12}" in text
    assert "event=compliance_fail attempt=1" in text
    assert "event=compliance_retry_scheduled attempt=1" in text
    assert "event=compliance_fail attempt=2" in text
    assert "event=compliance_failed_final" in text


def test_compliance_diagnostics_failure_does_not_block_finish(tmp_path, managed_caplog):
    source_pdf = _pdf(tmp_path, ["AD appears here."], name="source.pdf")
    ok_pdf = _pdf(tmp_path, ["阿尔茨海默病 是诊断结果。"], name="ok.pdf")
    context, doc_dir = _strict_ctx(tmp_path, [("AD", "阿尔茨海默病")])
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    replace_page = MagicMock()
    ctx = _single_ctx(
        tmp_path=tmp_path,
        context=context,
        doc_dir=doc_dir,
        job_id="job-diag-safe",
        cache_dir=cache_dir,
        source_pdf=source_pdf,
        replace_page=replace_page,
    )

    with (
        patch(
            "pdf_reader.term_diagnostics.log_compliance",
            side_effect=RuntimeError("compliance diagnostics boom"),
        ),
        patch("pdf_reader.sse_stream.run_translation", return_value=iter(_finish_events(_result(mono=ok_pdf)))),
        patch("pdf_reader.sse_stream.debug_trace"),
        managed_caplog.at_level(logging.WARNING, logger="pdf_reader"),
    ):
        output = list(generate(ctx))

    body = "".join(output)
    assert '"type": "finish"' in body
    replace_page.assert_called_once_with(str(ok_pdf))
    assert "diagnostics unavailable" in managed_caplog.text
    assert "compliance diagnostics boom" not in managed_caplog.text
