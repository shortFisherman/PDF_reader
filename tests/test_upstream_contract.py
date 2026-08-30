"""P3-06 上游最小契约：pdf2zh-next 2.9.0 / babeldoc 0.6.2。

离线、确定性：全部使用确定性 fake，不联网、不调用真实翻译服务、不需要 API Key。
升级 pdf2zh-next/BabelDOC 前必须先运行本文件（命令与范围见
docs/governance/dependency-upgrade.md）。任何断言失败都应先定位“上游契约变化”，
再决定更新适配代码还是本测试。
"""

import asyncio
import importlib.metadata as md
import inspect
import json
import threading
import tomllib
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pdf2zh_next
import pytest
from babeldoc.format.pdf.translation_config import TranslateResult
from pdf2zh_next import SettingsModel
from pdf2zh_next.config.model import BasicSettings, PDFSettings, TranslationSettings

from pdf_reader import cache_ops, config
from pdf_reader.sse_stream import GenerateContext, format_sse_event, generate
from pdf_reader.translation_lifecycle import finish_translation
from pdf_reader.translation_orchestrator import TranslationError, run_translation
from pdf_reader.translation_settings import build_settings

REPO_ROOT = Path(__file__).resolve().parents[1]

PINNED_VERSIONS = {"pdf2zh-next": "2.9.0", "babeldoc": "0.6.2"}


def _pyproject_pins() -> dict[str, str]:
    with open(REPO_ROOT / "pyproject.toml", "rb") as fh:
        project = tomllib.load(fh)["project"]
    return {
        name: version
        for dep in project["dependencies"]
        for name, sep, version in (dep.partition("=="),)
        if sep and name in PINNED_VERSIONS
    }


def _lock_pins() -> dict[str, str]:
    pins: dict[str, str] = {}
    for raw in (REPO_ROOT / "requirements.lock").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, version = line.partition("==")
        if sep and name in PINNED_VERSIONS:
            pins[name] = version
    return pins


def _sse_json(sse: str) -> dict:
    assert sse.startswith("data: "), f"不是 SSE data 行: {sse!r}"
    return json.loads(sse[len("data: ") :].rstrip("\n"))


def _make_real_ctx(tmp_path: Path, settings: SettingsModel, extract_page=None) -> GenerateContext:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    return GenerateContext(
        settings=settings,
        job_id="p3-06-contract",
        finish_job=MagicMock(return_value=True),
        fail_job=MagicMock(return_value=True),
        cancel_job=MagicMock(return_value=True),
        replace_page=MagicMock(),
        merge_glossary=MagicMock(),
        glossary_cache_path=None,
        page=0,
        glossary_paths=None,
        cache_dir=cache_dir,
        extract_page=extract_page or MagicMock(return_value=Path("/fake/page.pdf")),
    )


def test_pinned_upstream_versions_match_pyproject_lock_and_installed_metadata():
    pyproject_pins = _pyproject_pins()
    lock_pins = _lock_pins()
    for name, expected in PINNED_VERSIONS.items():
        if name == "pdf2zh-next":
            assert pyproject_pins.get(name) == expected, (
                f"pyproject.toml 中 {name} 应为 {expected}，实际 {pyproject_pins.get(name)!r}；"
                "不要只改测试，先走 dependency-upgrade.md 流程"
            )
        else:
            assert name not in pyproject_pins, (
                f"babeldoc 是传递依赖，不应直接声明在 pyproject.toml：{pyproject_pins[name]!r}"
            )
        assert lock_pins.get(name) == expected, (
            f"requirements.lock 中 {name} 应为 {expected}，实际 {lock_pins.get(name)!r}；"
            "锁文件与 pyproject 不一致，需用 pip-compile 重新生成"
        )
        try:
            installed = md.version(name)
        except md.PackageNotFoundError:
            pytest.fail(f"{name} 未安装：契约测试要求安装 {expected}（pip install -r requirements.lock）")
        assert installed == expected, (
            f"当前安装的 {name} 为 {installed}，契约固定为 {expected}；"
            "升级依赖时必须同步 PINNED_VERSIONS 并让 pyproject/锁文件/安装元数据一致"
        )


def test_settings_model_and_consumed_nested_fields_exist():
    top_fields = SettingsModel.model_fields
    for field in ("basic", "translation", "pdf", "translate_engine_settings"):
        assert field in top_fields, f"SettingsModel 缺少本项目消费的顶层字段 {field}"

    translation_fields = TranslationSettings.model_fields
    for field in (
        "lang_in",
        "lang_out",
        "ignore_cache",
        "save_auto_extracted_glossary",
        "output",
        "glossaries",
        "custom_system_prompt",
    ):
        assert field in translation_fields, f"TranslationSettings 缺少字段 {field}（build_settings/generate 依赖）"

    pdf_fields = PDFSettings.model_fields
    for field in ("pages", "no_dual", "only_include_translated_page", "watermark_output_mode"):
        assert field in pdf_fields, f"PDFSettings 缺少字段 {field}（build_settings 依赖）"

    assert "debug" in BasicSettings.model_fields, "BasicSettings 缺少 debug 字段"


def test_settings_assignment_compatibility(mock_config, monkeypatch):
    monkeypatch.setattr(config, "GLOSSARY_PATH", Path("nonexistent.csv"))
    settings = build_settings("dummy.pdf", output_dir="C:/tmp/out", glossary_paths=["/tmp/g.csv"])

    assert settings.translation.lang_in == "en"
    assert settings.translation.lang_out == "zh"
    assert settings.translation.ignore_cache is True
    assert settings.translation.save_auto_extracted_glossary is True
    assert settings.translation.glossaries == "/tmp/g.csv"
    assert settings.translation.output == "C:/tmp/out"
    settings.translation.output = "C:/tmp/changed"
    assert settings.translation.output == "C:/tmp/changed"
    assert settings.pdf.pages == "1"
    assert settings.pdf.no_dual is True
    assert settings.pdf.only_include_translated_page is True
    assert settings.pdf.watermark_output_mode == "no_watermark"
    assert settings.basic.debug is False


def test_engine_registry_field_map_matches_upstream_settings_classes():
    for spec in config.ENGINE_REGISTRY:
        model_fields = getattr(spec.settings_cls, "model_fields", {})
        missing = [field for field in spec.field_map.values() if field not in model_fields]
        assert not missing, (
            f"引擎 {spec.provider} 的字段映射 {missing} 不在 {spec.settings_cls.__name__} 中；"
            "build_engine_kwargs 会静默跳过缺失字段，升级依赖时必须同步 ENGINE_REGISTRY"
        )


def test_do_translate_async_stream_is_async_generator_with_positional_pair():
    assert inspect.isasyncgenfunction(pdf2zh_next.do_translate_async_stream), (
        "do_translate_async_stream 必须是异步生成器函数（本项目在 worker 线程 async for 消费）"
    )
    params = list(inspect.signature(pdf2zh_next.do_translate_async_stream).parameters.values())
    assert len(params) >= 2, "do_translate_async_stream 至少接受 (settings, file) 两个参数"
    assert all(param.kind in (param.POSITIONAL_ONLY, param.POSITIONAL_OR_KEYWORD) for param in params[:2]), (
        "本项目按 (settings, file) 位置参数调用 do_translate_async_stream"
    )


def test_committed_event_types_still_map_to_sse():
    start = _sse_json(format_sse_event({"type": "progress_start", "stage": "layout_analysis"}))
    assert start == {
        "type": "progress",
        "progress": 0,
        "stage": "layout_analysis",
        "stage_current": 0,
        "stage_total": 0,
    }

    update = _sse_json(
        format_sse_event(
            {
                "type": "progress_update",
                "overall_progress": 42,
                "stage": "translating",
                "stage_current": 2,
                "stage_total": 5,
            }
        )
    )
    assert update == {"type": "progress", "progress": 42, "stage": "translating", "stage_current": 2, "stage_total": 5}

    finish = _sse_json(format_sse_event({"type": "finish", "stage": "generating_pdf"}))
    assert finish == {
        "type": "progress",
        "progress": 95,
        "stage": "generating_pdf",
        "stage_current": 0,
        "stage_total": 0,
    }

    error = _sse_json(format_sse_event({"type": "error", "error": "raw upstream error"}))
    assert error == {"type": "error", "code": "translation_error", "error": "上游翻译失败"}


def test_uncommitted_event_types_are_ignored_not_crashed():
    assert format_sse_event({"type": "progress_end", "overall_progress": 20.0}) is None
    assert format_sse_event({"type": "unknown_future_event", "anything": True}) is None
    assert format_sse_event({"type": "_done"}) is None


def test_workspace_output_injection_and_unknown_event_ignore_with_real_settings(tmp_path, mock_config, monkeypatch):
    monkeypatch.setattr(config, "GLOSSARY_PATH", Path("nonexistent.csv"))
    settings = build_settings("dummy.pdf")
    result = TranslateResult(
        mono_pdf_path=str(tmp_path / "mono.pdf"),
        dual_pdf_path=None,
        auto_extracted_glossary_path=str(tmp_path / "auto.csv"),
    )
    captured = {}

    def extract_spy(page, tmpdir, func) -> Path:
        captured["output_value"] = str(settings.translation.output)
        captured["output_dir_exists"] = Path(settings.translation.output).is_dir()
        return Path("/fake/page.pdf")

    events = [
        {"type": "progress_end", "overall_progress": 20.0},
        "",
        {"type": "unknown_future_event", "anything": True},
        {"type": "finish", "stage": "generating_pdf", "translate_result": result, "token_usage": {}},
    ]
    ctx = _make_real_ctx(tmp_path, settings, extract_page=extract_spy)

    with patch("pdf_reader.sse_stream.run_translation", return_value=iter(events)):
        with patch("pdf_reader.sse_stream.debug_trace"):
            output = list(generate(ctx))

    assert captured["output_dir_exists"] is True
    assert Path(captured["output_value"]).name == "output"
    assert Path(captured["output_value"]).parent.name.startswith(cache_ops.TEMP_WORKSPACE_PREFIX)
    assert "" in output
    assert any(_sse_json(item)["type"] == "progress" for item in output if item)
    assert any(_sse_json(item)["type"] == "finish" for item in output if item)
    assert not any(_sse_json(item)["type"] == "error" for item in output if item)
    ctx.replace_page.assert_called_once_with(str(tmp_path / "mono.pdf"))
    ctx.merge_glossary.assert_called_once_with(str(tmp_path / "auto.csv"))


def test_finish_result_dual_fallback_and_glossary_path_with_real_upstream_result(tmp_path):
    result = TranslateResult(
        mono_pdf_path=None,
        dual_pdf_path=str(tmp_path / "dual.pdf"),
        auto_extracted_glossary_path=Path(tmp_path / "auto.csv"),
    )
    replace_page = MagicMock()
    merge_glossary = MagicMock()

    with patch("pdf_reader.translation_lifecycle.debug_trace.log_glossary_merge"):
        finish_translation(result, replace_page, merge_glossary, page=1, job_id="contract")

    replace_page.assert_called_once_with(str(tmp_path / "dual.pdf"))
    merge_glossary.assert_called_once_with(Path(tmp_path / "auto.csv"))


def test_cooperative_cancel_discards_late_events_and_worker_exits():
    release = threading.Event()

    async def gated_stream(settings, file) -> AsyncIterator[dict]:
        yield {"type": "progress_start", "stage": "layout_analysis"}
        while not release.wait(0.01):
            await asyncio.sleep(0)
        yield {"type": "finish", "stage": "generating_pdf", "translate_result": None, "token_usage": {}}

    with patch("pdf_reader.translation_orchestrator.do_translate_async_stream", gated_stream):
        stream = run_translation(MagicMock(), "fake.pdf")
        first = next(stream)
        assert isinstance(first, dict) and first["type"] == "progress_start"
        stream.cancel()
        release.set()
        stream.join(timeout=5.0)

    assert not stream.is_alive
    assert stream.late_result_dropped is True
    delivered = []
    while True:
        try:
            delivered.append(next(stream))
        except StopIteration:
            break
    assert all(item == "" for item in delivered)
    assert not any(isinstance(item, dict) and item.get("type") == "finish" for item in delivered)


def test_cancel_does_not_force_kill_non_cooperative_worker():
    async def stuck_stream(settings, file) -> AsyncIterator[dict]:
        yield {"type": "progress_start", "stage": "layout_analysis"}
        await asyncio.sleep(3600)

    with patch("pdf_reader.translation_orchestrator.do_translate_async_stream", stuck_stream):
        stream = run_translation(MagicMock(), "fake.pdf")
        assert isinstance(next(stream), dict)
        stream.cancel()
        stream.join(timeout=0.2)

    assert stream.is_alive, "协作式取消不得强制 kill 不响应取消的上游环节"


def test_worker_exception_surfaces_as_translation_error():
    async def failing_stream(settings, file) -> AsyncIterator[dict]:
        yield {"type": "progress_start", "stage": "layout_analysis"}
        raise RuntimeError("contract engine failure")

    with patch("pdf_reader.translation_orchestrator.do_translate_async_stream", failing_stream):
        with pytest.raises(TranslationError, match="contract engine failure"):
            list(run_translation(MagicMock(), "fake.pdf"))
