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
from typing import Any
from unittest.mock import MagicMock, patch

import pdf2zh_next
import pytest
from babeldoc.format.pdf.translation_config import (
    SharedContextCrossSplitPart,
)
from babeldoc.format.pdf.translation_config import (
    TranslationConfig as BabelDOCTranslationConfig,
)
from babeldoc.glossary import Glossary, GlossaryEntry
from pdf2zh_next import SettingsModel
from pdf2zh_next.config.model import BasicSettings, PDFSettings, TranslationSettings

from pdf_reader import cache_ops, config
from pdf_reader.sse_stream import GenerateContext, format_sse_event, generate
from pdf_reader.translation_lifecycle import finish_translation
from pdf_reader.translation_orchestrator import TranslationError, TranslationStream, run_translation
from pdf_reader.translation_settings import build_settings

REPO_ROOT = Path(__file__).resolve().parents[1]

PINNED_VERSIONS = {"pdf2zh-next": "2.9.0", "babeldoc": "0.6.2"}


def _upstream(
    model: config.ModelRuntimeConfig | None = None,
    translation: config.TranslationRuntimeConfig | None = None,
    pdf: config.Pdf2zhRuntimeConfig | None = None,
) -> config.UpstreamRuntimeConfig:
    return config.UpstreamRuntimeConfig(
        model=model
        or config.ModelRuntimeConfig(
            provider="openai",
            api_key="sk-test-key",
            model="gpt-4o-mini",
        ),
        translation=translation or config.TranslationRuntimeConfig(lang_in="en", lang_out="zh"),
        pdf=pdf or config.Pdf2zhRuntimeConfig(),
    )


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


def _make_translate_result(
    mono_pdf_path: str | Path | None = None,
    dual_pdf_path: str | Path | None = None,
    auto_extracted_glossary_path: str | Path | None = None,
) -> Any:
    """构造上游 finish 事件的结果对象（babeldoc 0.6.2 最小深层契约）。

    pdf2zh_next 顶层不公开 TranslateResult；本项目只依赖
    babeldoc.format.pdf.translation_config.TranslateResult 的
    mono_pdf_path/dual_pdf_path/auto_extracted_glossary_path 三个输出字段。
    该路径是私有 API：升级 babeldoc 时若不可导入，必须先核对 mono/dual/glossary
    输出适配与 docs/governance/dependency-upgrade.md 记录的最小深层契约再更新本测试，
    不得降级为无字段校验的 SimpleNamespace 式占位。
    """
    try:
        from babeldoc.format.pdf.translation_config import TranslateResult
    except ImportError as exc:
        pytest.fail(
            "babeldoc 0.6.2 的 TranslateResult 深层契约路径已不可用"
            f"（pdf2zh_next 顶层也不公开该类型）：{exc}；"
            "本项目依赖其 mono_pdf_path/dual_pdf_path/auto_extracted_glossary_path 输出字段，"
            "必须先核对 mono/dual/glossary 适配与 dependency-upgrade.md 最小深层契约再更新测试。"
        )
    return TranslateResult(
        mono_pdf_path=mono_pdf_path,
        dual_pdf_path=dual_pdf_path,
        auto_extracted_glossary_path=auto_extracted_glossary_path,
    )


USER_TERM_SOURCE = "user authoritative term"
USER_TERM_TARGET = "用户权威译法"
AUTO_TERM_SOURCE = "auto candidate term"
AUTO_TERM_TARGET = "自动候选译法"


def _make_glossary(name: str, entries: list[tuple[str, str]]) -> Glossary:
    return Glossary(name=name, entries=[GlossaryEntry(source, target) for source, target in entries])


def _shared_context_with_user_and_auto_glossaries() -> SharedContextCrossSplitPart:
    shared = SharedContextCrossSplitPart()
    shared.initialize_glossaries([_make_glossary("user_glossary", [(USER_TERM_SOURCE, USER_TERM_TARGET)])])
    # 自动提取器只“复述”出自动候选词，没有复述用户权威术语。
    shared.add_raw_extracted_term_pair(AUTO_TERM_SOURCE, AUTO_TERM_TARGET)
    shared.finalize_auto_extracted_glossary()
    return shared


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
        "min_text_length",
        "qps",
        "pool_max_workers",
        "term_qps",
        "term_pool_max_workers",
        "no_auto_extract_glossary",
        "ignore_cache",
        "save_auto_extracted_glossary",
        "primary_font_family",
        "output",
        "glossaries",
        "custom_system_prompt",
    ):
        assert field in translation_fields, f"TranslationSettings 缺少字段 {field}（build_settings/generate 依赖）"

    pdf_fields = PDFSettings.model_fields
    for field in (
        "pages",
        "no_dual",
        "no_mono",
        "only_include_translated_page",
        "watermark_output_mode",
        "split_short_lines",
        "short_line_split_factor",
        "skip_clean",
        "disable_rich_text_translate",
        "enhance_compatibility",
        "translate_table_text",
        "skip_scanned_detection",
        "ocr_workaround",
        "auto_enable_ocr_workaround",
        "no_merge_alternating_line_numbers",
        "skip_formula_offset_calculation",
        "non_formula_line_iou_threshold",
        "figure_table_protection_threshold",
        "formular_font_pattern",
        "formular_char_pattern",
    ):
        assert field in pdf_fields, f"PDFSettings 缺少字段 {field}（build_settings 依赖）"

    assert "debug" in BasicSettings.model_fields, "BasicSettings 缺少 debug 字段"


def test_settings_assignment_compatibility(mock_config, monkeypatch):
    monkeypatch.setattr(config, "GLOSSARY_PATH", Path("nonexistent.csv"))
    settings = build_settings(
        _upstream(),
        "dummy.pdf",
        output_dir="C:/tmp/out",
        glossary_paths=["/tmp/g.csv"],
    )

    assert settings.translation.lang_in == "en"
    assert settings.translation.lang_out == "zh"
    assert settings.translation.ignore_cache is True
    assert settings.translation.no_auto_extract_glossary is True
    assert settings.translation.save_auto_extracted_glossary is False
    assert settings.translation.glossaries == "/tmp/g.csv"
    assert settings.translation.output == "C:/tmp/out"
    settings.translation.output = "C:/tmp/changed"
    assert settings.translation.output == "C:/tmp/changed"
    assert settings.pdf.pages == "1"
    assert settings.pdf.no_dual is True
    assert settings.pdf.only_include_translated_page is True
    assert settings.pdf.watermark_output_mode == "no_watermark"
    assert settings.basic.debug is False


def test_build_settings_strict_path_forces_auto_extract_off_for_both_config_values(mock_config, monkeypatch, tmp_path):
    """P0-04：正文 SettingsModel 恒为严格路径，auto_extract_glossary 不能绕过。"""
    global_csv = tmp_path / "global_terms.csv"
    global_csv.write_text("source,target\nGlobal Term,全局术语\n", encoding="utf-8")
    monkeypatch.setattr(config, "GLOSSARY_PATH", global_csv)
    user_csv = tmp_path / "user_terms.csv"
    user_csv.write_text("source,target\nUser Term,用户术语\n", encoding="utf-8")

    for auto_extract in (True, False):
        translation = config.TranslationRuntimeConfig(
            lang_in="en",
            lang_out="zh",
            auto_extract_glossary=auto_extract,
        )
        settings = build_settings(
            _upstream(translation=translation),
            "dummy.pdf",
            glossary_paths=[str(user_csv)],
        )

        assert settings.translation.no_auto_extract_glossary is True
        assert settings.translation.save_auto_extracted_glossary is False
        # 严格路径只接受调用方传入的有效词表，绝不自动附加全局/累计 CSV。
        assert settings.translation.glossaries == str(user_csv)


def test_auto_extract_flags_reach_babeldoc_config_and_user_glossaries(
    mock_config,
    monkeypatch,
    tmp_path,
):
    """真实转换链：严格正文 SettingsModel 到达 BabelDOC 时自动提取恒关闭。

    pdf2zh-next 2.9.0 的 create_babeldoc_config 不把 save_auto_extracted_glossary
    转发给 BabelDOC，因此 BabelDOC 侧仍为默认 True；但 no_auto_extract_glossary
    恒为 True，自动词表不存在，实际不会写自动词表文件。升级依赖时必须重新核对该缺口。
    """
    from pdf2zh_next.high_level import create_babeldoc_config

    global_csv = tmp_path / "global_terms.csv"
    global_csv.write_text("source,target\nGlobal Term,全局术语\n", encoding="utf-8")
    monkeypatch.setattr(config, "GLOSSARY_PATH", global_csv)
    user_csv = tmp_path / "user_terms.csv"
    user_csv.write_text("source,target\nUser Term,用户术语\n", encoding="utf-8")
    pdf = config.Pdf2zhRuntimeConfig(translate_table_text=False)

    for auto_extract in (True, False):
        translation = config.TranslationRuntimeConfig(
            lang_in="en",
            lang_out="zh",
            auto_extract_glossary=auto_extract,
        )
        settings = build_settings(
            _upstream(translation=translation, pdf=pdf),
            "dummy.pdf",
            glossary_paths=[str(user_csv)],
        )
        with patch("pdf2zh_next.high_level.get_translator", return_value=object()):
            babeldoc_cfg = create_babeldoc_config(settings, Path("dummy.pdf"))

        assert babeldoc_cfg.auto_extract_glossary is False
        assert babeldoc_cfg.save_auto_extracted_glossary is True
        user_glossaries = babeldoc_cfg.shared_context_cross_split_part.user_glossaries
        assert [g.name for g in user_glossaries] == ["user_terms"]
        assert {(e.source, e.target) for g in user_glossaries for e in g.entries} == {("User Term", "用户术语")}


def test_babeldoc_falls_back_to_pool_only_when_term_pool_is_none():
    """BabelDOC 0.6.2 真实契约：None 跟随 pool_max_workers，0 不会。"""

    def make_config(term_pool_max_workers: int | None) -> BabelDOCTranslationConfig:
        return BabelDOCTranslationConfig(
            translator=None,
            input_file="dummy.pdf",
            lang_in="en",
            lang_out="zh",
            doc_layout_model=None,
            pool_max_workers=3,
            term_pool_max_workers=term_pool_max_workers,
        )

    assert make_config(None).term_pool_max_workers == 3
    assert make_config(0).term_pool_max_workers == 0


def test_babeldoc_auto_on_selects_only_auto_glossary_for_translation():
    """BabelDOC 0.6.2 契约：auto-on 且自动词表存在时，正文只选择自动词表。"""
    shared = _shared_context_with_user_and_auto_glossaries()
    assert shared.auto_extracted_glossary is not None

    selected = shared.get_glossaries_for_translation(auto_extract_enabled=True)

    assert [g.name for g in selected] == ["auto_extracted_glossary"]
    selected_sources = {e.source for g in selected for e in g.entries}
    assert selected_sources == {AUTO_TERM_SOURCE}
    assert USER_TERM_SOURCE not in selected_sources


def test_babeldoc_auto_off_selects_user_then_auto_for_translation():
    """BabelDOC 0.6.2 契约：auto-off 时正文选择 user + auto（如存在）。"""
    shared = _shared_context_with_user_and_auto_glossaries()

    selected = shared.get_glossaries_for_translation(auto_extract_enabled=False)

    assert [g.name for g in selected] == ["user_glossary", "auto_extracted_glossary"]
    assert [(g.name, e.source, e.target) for g in selected for e in g.entries] == [
        ("user_glossary", USER_TERM_SOURCE, USER_TERM_TARGET),
        ("auto_extracted_glossary", AUTO_TERM_SOURCE, AUTO_TERM_TARGET),
    ]


def test_babeldoc_auto_on_without_auto_glossary_falls_back_to_user():
    """边界事实：auto-on 但提取器没有任何产出时，BabelDOC 回退到用户词表。"""
    shared = SharedContextCrossSplitPart()
    shared.initialize_glossaries([_make_glossary("user_glossary", [(USER_TERM_SOURCE, USER_TERM_TARGET)])])
    shared.finalize_auto_extracted_glossary()
    assert shared.auto_extracted_glossary is None

    selected = shared.get_glossaries_for_translation(auto_extract_enabled=True)

    assert [g.name for g in selected] == ["user_glossary"]


def test_auto_on_requires_extractor_to_repeat_user_terms_before_body_translation():
    """固定当前限制：auto-on 时，未被提取器复述的用户术语不会进入正文词表。"""
    shared = _shared_context_with_user_and_auto_glossaries()

    selected = shared.get_glossaries_for_translation(auto_extract_enabled=True)
    selected_sources = {e.source for g in selected for e in g.entries}

    assert USER_TERM_SOURCE not in selected_sources


def test_term_pool_zero_reaches_babeldoc_as_followed_positive(mock_config, monkeypatch):
    """真实 high_level → BabelDOC 路径：0 被省略后最终得到跟随后的正数。

    只 stub get_translator 的联网健康检查；SettingsModel → BabelDOCConfig
    转换与 BabelDOC 回退逻辑均为真实上游代码。
    """
    from pdf2zh_next.high_level import create_babeldoc_config

    monkeypatch.setattr(config, "GLOSSARY_PATH", Path("nonexistent.csv"))
    translation = config.TranslationRuntimeConfig(
        lang_in="en",
        lang_out="zh",
        pool_max_workers=3,
        term_pool_max_workers=0,
    )
    pdf = config.Pdf2zhRuntimeConfig(translate_table_text=False)
    settings = build_settings(_upstream(translation=translation, pdf=pdf), "dummy.pdf")
    assert settings.translation.term_pool_max_workers is None

    with patch("pdf2zh_next.high_level.get_translator", return_value=object()):
        babeldoc_config = create_babeldoc_config(settings, Path("dummy.pdf"))

    assert babeldoc_config.term_pool_max_workers == 3
    assert babeldoc_config.pool_max_workers == 3


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
    settings = build_settings(_upstream(), "dummy.pdf")
    result = _make_translate_result(
        mono_pdf_path=str(tmp_path / "mono.pdf"),
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
    result = _make_translate_result(
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
    release = threading.Event()
    stream: TranslationStream | None = None
    threads_before = {thread.ident for thread in threading.enumerate()}

    async def stuck_stream(settings, file) -> AsyncIterator[dict]:
        yield {"type": "progress_start", "stage": "layout_analysis"}
        while not release.wait(0.01):
            await asyncio.sleep(0)

    try:
        with patch("pdf_reader.translation_orchestrator.do_translate_async_stream", stuck_stream):
            stream = run_translation(MagicMock(), "fake.pdf")
            assert isinstance(next(stream), dict)
            stream.cancel()
            stream.join(timeout=0.2)

        assert stream.is_alive, "协作式取消不得强制 kill 不响应取消的上游环节"
    finally:
        release.set()
        if stream is not None:
            stream.join(timeout=5.0)
            assert not stream.is_alive, "释放 gate 后 worker 应在有界时间内退出"
            leaked = [t.name for t in threading.enumerate() if t.ident not in threads_before]
            assert not leaked, f"测试结束后仍残留本测试创建的线程：{leaked}"


def test_worker_exception_surfaces_as_translation_error():
    async def failing_stream(settings, file) -> AsyncIterator[dict]:
        yield {"type": "progress_start", "stage": "layout_analysis"}
        raise RuntimeError("contract engine failure")

    with patch("pdf_reader.translation_orchestrator.do_translate_async_stream", failing_stream):
        with pytest.raises(TranslationError, match="contract engine failure"):
            list(run_translation(MagicMock(), "fake.pdf"))


def test_openai_send_temperature_uses_historical_temprature_spelling():
    """OpenAI 上游字段是历史拼写 openai_send_temprature，升级依赖前必须先核对。"""
    from pdf2zh_next.config.translate_engine_model import OpenAISettings

    spec = config.PROVIDER_INDEX["openai"]
    assert spec.field_map["send_temperature"] == "openai_send_temprature"
    assert "openai_send_temprature" in OpenAISettings.model_fields


def test_openai_send_switches_reach_translator_request_options(mock_config, monkeypatch):
    """transform 后的 OpenAITranslator.options 必须真实包含 temperature/reasoning_effort。"""
    from pdf2zh_next.translator.translator_impl.openai import OpenAITranslator

    monkeypatch.setattr(config, "GLOSSARY_PATH", Path("nonexistent.csv"))
    model_cfg = config.ModelRuntimeConfig(
        provider="openai",
        api_key="sk-test-key",
        model="gpt-4o-mini",
        temperature="0.7",
        send_temperature=True,
        reasoning_effort="high",
        send_reasoning_effort=True,
    )
    settings = build_settings(_upstream(model=model_cfg), "dummy.pdf")
    settings.validate_settings()

    translator = OpenAITranslator(settings, MagicMock())
    assert translator.options["temperature"] == 0.7
    assert translator.options["reasoning_effort"] == "high"


def test_send_switches_off_preserve_old_request_options(mock_config, monkeypatch):
    """开关默认关闭时，旧行为不变：请求 options 不含 temperature/reasoning_effort。"""
    from pdf2zh_next.translator.translator_impl.openai import OpenAITranslator

    monkeypatch.setattr(config, "GLOSSARY_PATH", Path("nonexistent.csv"))
    settings = build_settings(_upstream(), "dummy.pdf")
    settings.validate_settings()

    translator = OpenAITranslator(settings, MagicMock())
    assert "temperature" not in translator.options
    assert "reasoning_effort" not in translator.options


def test_openai_compatible_send_switches_transform_into_openai_request_fields(
    mock_config,
    monkeypatch,
):
    from pdf2zh_next.config.translate_engine_model import OpenAISettings
    from pdf2zh_next.translator.translator_impl.openai import OpenAITranslator

    monkeypatch.setattr(config, "GLOSSARY_PATH", Path("nonexistent.csv"))
    model_cfg = config.ModelRuntimeConfig(
        provider="openai_compatible",
        api_key="sk-test-key",
        model="custom-model",
        base_url="https://example.com/v1",
        temperature="0.2",
        send_temperature=True,
        reasoning_effort="low",
        send_reasoning_effort=True,
    )
    settings = build_settings(_upstream(model=model_cfg), "dummy.pdf")
    assert settings.translate_engine_settings.openai_compatible_send_temperature is True
    settings.validate_settings()
    assert isinstance(settings.translate_engine_settings, OpenAISettings)
    assert settings.translate_engine_settings.openai_send_temprature is True
    assert settings.translate_engine_settings.openai_send_reasoning_effort is True

    translator = OpenAITranslator(settings, MagicMock())
    assert translator.options["temperature"] == 0.2
    assert translator.options["reasoning_effort"] == "low"


def test_aliyun_send_temperature_transform_into_openai_request_options(mock_config, monkeypatch):
    from pdf2zh_next.config.translate_engine_model import OpenAISettings
    from pdf2zh_next.translator.translator_impl.openai import OpenAITranslator

    monkeypatch.setattr(config, "GLOSSARY_PATH", Path("nonexistent.csv"))
    model_cfg = config.ModelRuntimeConfig(
        provider="aliyun",
        api_key="sk-test-key",
        model="qwen-plus-latest",
        temperature="0.5",
        send_temperature=True,
    )
    settings = build_settings(_upstream(model=model_cfg), "dummy.pdf")
    assert settings.translate_engine_settings.aliyun_dashscope_send_temperature is True
    settings.validate_settings()
    assert isinstance(settings.translate_engine_settings, OpenAISettings)
    assert settings.translate_engine_settings.openai_send_temprature is True

    translator = OpenAITranslator(settings, MagicMock())
    assert translator.options["temperature"] == 0.5


def test_pdf2zh_consumed_upstream_defaults_match_design():
    """pdf2zh-next 2.9.0 的消费字段默认值必须与设计目录一致。"""
    pdf = PDFSettings()
    assert pdf.split_short_lines is False
    assert pdf.short_line_split_factor == 0.8
    assert pdf.skip_clean is False
    assert pdf.disable_rich_text_translate is False
    assert pdf.enhance_compatibility is False
    assert pdf.translate_table_text is True
    assert pdf.skip_scanned_detection is False
    assert pdf.ocr_workaround is False
    assert pdf.auto_enable_ocr_workaround is False
    assert pdf.no_merge_alternating_line_numbers is False
    assert pdf.skip_formula_offset_calculation is False
    assert pdf.non_formula_line_iou_threshold == 0.9
    assert pdf.figure_table_protection_threshold == 0.9
    assert pdf.formular_font_pattern is None
    assert pdf.formular_char_pattern is None


def test_formula_mapping_uses_historical_formular_spelling():
    """本项目使用正确拼写 formula_*，上游 2.9.0 字段是历史拼写 formular_*。"""
    assert "formular_font_pattern" in PDFSettings.model_fields
    assert "formular_char_pattern" in PDFSettings.model_fields
    assert "formula_font_pattern" not in PDFSettings.model_fields
    assert "formula_char_pattern" not in PDFSettings.model_fields

    pdf_cfg = config.Pdf2zhRuntimeConfig(
        formula_font_pattern="^math",
        formula_char_pattern="\\d+",
    )
    settings = build_settings(_upstream(pdf=pdf_cfg), "dummy.pdf")
    assert settings.pdf.formular_font_pattern == "^math"
    assert settings.pdf.formular_char_pattern == "\\d+"


def test_pdf2zh_fields_reach_upstream_settings(mock_config, monkeypatch):
    monkeypatch.setattr(config, "GLOSSARY_PATH", Path("nonexistent.csv"))
    pdf_cfg = config.Pdf2zhRuntimeConfig(
        split_short_lines=True,
        short_line_split_factor=0.5,
        skip_clean=True,
        disable_rich_text_translate=True,
        enhance_compatibility=True,
        translate_table_text=False,
        skip_scanned_detection=True,
        ocr_workaround=True,
        auto_enable_ocr_workaround=True,
        no_merge_alternating_line_numbers=True,
        skip_formula_offset_calculation=True,
        non_formula_line_iou_threshold=0.4,
        figure_table_protection_threshold=0.6,
        formula_font_pattern="^math",
        formula_char_pattern="\\d+",
    )
    settings = build_settings(_upstream(pdf=pdf_cfg), "dummy.pdf")
    pdf = settings.pdf
    assert pdf.split_short_lines is True
    assert pdf.short_line_split_factor == 0.5
    assert pdf.skip_clean is True
    assert pdf.disable_rich_text_translate is True
    assert pdf.enhance_compatibility is True
    assert pdf.translate_table_text is False
    assert pdf.skip_scanned_detection is True
    assert pdf.ocr_workaround is True
    assert pdf.auto_enable_ocr_workaround is True
    assert pdf.no_merge_alternating_line_numbers is True
    assert pdf.skip_formula_offset_calculation is True
    assert pdf.non_formula_line_iou_threshold == 0.4
    assert pdf.figure_table_protection_threshold == 0.6
    assert pdf.formular_font_pattern == "^math"
    assert pdf.formular_char_pattern == "\\d+"
