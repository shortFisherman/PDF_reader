---
change: multi-model-provider
design-doc: docs/superpowers/specs/2026-06-19-multi-model-provider-design.md
base-ref: a555b0aee33923f7b879b7b8aa7e23ee89dc4bf8
archived-with: 2026-06-19-multi-model-provider
---

# 多模型供应商支持 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将翻译引擎选择从硬编码 `DeepSeekSettings` 解耦到 `config.toml`，支持 pdf2zh-next 10 种内置引擎 + OpenAI 通用兼容接口的动态切换。

**Architecture:** `config.toml` 新增 `[model]` 配置段，通过 `config.py` 中的 `PROVIDER_MAP` 路由表和 `FIELD_MAP` 字段映射表，在 `services.py` 的 `build_settings()` 中动态选择引擎类并构建参数。未知 provider 自动走 `OpenAICompatibleSettings` 兜底。

**Tech Stack:** Python 3.12, pdf2zh-next v2.9.0 (pydantic BaseModel), tomllib, pytest + monkeypatch

## Global Constraints

- Python 3.12+, 不可引入新的第三方依赖
- 配置文件段名 `[deepseek]` → `[model]`，旧段名不兼容
- 环境变量 `DEEPSEEK_API_KEY` 不再支持，统一使用 `MODEL_API_KEY`
- 必填字段缺失时启动报错（`api_key`、`model`）
- 引擎不支持的字段静默跳过（warning 日志）
- `ruff check` 零错误、`pytest tests/ -v` 全部通过

archived-with: 2026-06-19-multi-model-provider
---

### Task 1: 配置层重构 — config.toml + config.py

**Files:**
- Modify: `config.toml:1-18`
- Modify: `config.py:1-16`
- Modify: `tests/conftest.py:1-40`（新增 mock_config fixture）

**Interfaces:**
- Produces: `config.MODEL_PROVIDER: str`, `config.MODEL_API_KEY: str`, `config.MODEL: str`, `config.MODEL_BASE_URL: str`, `config.MODEL_THINKING_MODE: str | None`, `config.MODEL_REASONING_EFFORT: str | None`, `config.MODEL_ENABLE_JSON_MODE: bool | None`, `config.MODEL_TEMPERATURE: str | None`, `config.MODEL_TIMEOUT: str | None`
- Produces: `config.PROVIDER_MAP: dict[str, type[BaseModel]]`
- Produces: `config.FIELD_MAP: dict[str, dict[str, str]]`

- [x] **Step 1: 在 conftest.py 中新增 mock_config fixture**

```python
# 在 tests/conftest.py 末尾追加
import config

@pytest.fixture
def mock_config(monkeypatch):
    """为测试提供可控的 config 属性，不依赖真实 config.toml"""
    monkeypatch.setattr(config, "MODEL_PROVIDER", "deepseek")
    monkeypatch.setattr(config, "MODEL_API_KEY", "sk-test-key")
    monkeypatch.setattr(config, "MODEL", "deepseek-v4-flash")
    monkeypatch.setattr(config, "MODEL_BASE_URL", "https://api.deepseek.com/v1")
    monkeypatch.setattr(config, "MODEL_THINKING_MODE", None)
    monkeypatch.setattr(config, "MODEL_REASONING_EFFORT", None)
    monkeypatch.setattr(config, "MODEL_ENABLE_JSON_MODE", None)
    monkeypatch.setattr(config, "MODEL_TEMPERATURE", None)
    monkeypatch.setattr(config, "MODEL_TIMEOUT", None)
    yield
```

- [x] **Step 2: 验证 mock_config fixture 生效**

Run: `pytest tests/test_services.py::test_build_settings_basic -v --setup-show`
Expected: 测试失败或通过取决于 config.py 当前状态（此步骤仅确认 fixture 存在）

- [x] **Step 3: 更新 config.toml — `[deepseek]` → `[model]`**

```toml
[pdf_reader]
dpi = 200
cache_dir = "cache"

[model]
provider = "deepseek"
api_key = "sk-your-api-key"
model = "deepseek-v4-flash"
base_url = "https://api.deepseek.com/v1"

[translation]
lang_in = "en"
lang_out = "zh"
qps = 4

[server]
host = "127.0.0.1"
port = 5000
debug = true
```

- [x] **Step 4: 重写 config.py — 新增 PROVIDER_MAP、FIELD_MAP、统一配置常量**

```python
import logging
import os
import tomllib
from pathlib import Path

from pdf2zh_next.config.translate_engine_model import (
    AliyunDashScopeSettings,
    DeepSeekSettings,
    GeminiSettings,
    GrokSettings,
    GroqSettings,
    ModelScopeSettings,
    OpenAICompatibleSettings,
    OpenAISettings,
    SiliconFlowSettings,
    ZhipuSettings,
)

CONFIG_PATH = Path(__file__).parent / "config.toml"
with open(CONFIG_PATH, "rb") as f:
    CONFIG = tomllib.load(f)

# ── 模型配置 ──────────────────────────────────────────────
model_cfg = CONFIG["model"]
MODEL_PROVIDER = model_cfg["provider"]
MODEL_API_KEY = os.environ.get("MODEL_API_KEY", model_cfg["api_key"])
MODEL = model_cfg["model"]
MODEL_BASE_URL = model_cfg.get("base_url", "")

MODEL_THINKING_MODE = model_cfg.get("thinking_mode")
MODEL_REASONING_EFFORT = model_cfg.get("reasoning_effort")
MODEL_ENABLE_JSON_MODE = model_cfg.get("enable_json_mode")
MODEL_TEMPERATURE = model_cfg.get("temperature")
MODEL_TIMEOUT = model_cfg.get("timeout")

if not MODEL_API_KEY or MODEL_API_KEY.startswith("sk-your-api-key"):
    raise ValueError("请设置 model.api_key 或环境变量 MODEL_API_KEY")
if not MODEL:
    raise ValueError("请设置 model.model")

# ── 引擎路由表 ────────────────────────────────────────────
PROVIDER_MAP: dict[str, type] = {
    "deepseek":           DeepSeekSettings,
    "zhipu":              ZhipuSettings,
    "siliconflow":        SiliconFlowSettings,
    "aliyun":             AliyunDashScopeSettings,
    "gemini":             GeminiSettings,
    "groq":               GroqSettings,
    "grok":               GrokSettings,
    "modelscope":         ModelScopeSettings,
    "openai":             OpenAISettings,
    "openai_compatible":  OpenAICompatibleSettings,
}

# ── 字段映射表 ────────────────────────────────────────────
FIELD_MAP: dict[str, dict[str, str]] = {
    "api_key": {
        "DeepSeekSettings":    "deepseek_api_key",
        "ZhipuSettings":       "zhipu_api_key",
        "SiliconFlowSettings": "siliconflow_api_key",
        "AliyunDashScopeSettings": "aliyun_dashscope_api_key",
        "GeminiSettings":      "gemini_api_key",
        "GroqSettings":        "groq_api_key",
        "GrokSettings":        "grok_api_key",
        "ModelScopeSettings":  "modelscope_api_key",
        "OpenAISettings":      "openai_api_key",
        "OpenAICompatibleSettings": "openai_compatible_api_key",
    },
    "model": {
        "DeepSeekSettings":    "deepseek_model",
        "ZhipuSettings":       "zhipu_model",
        "SiliconFlowSettings": "siliconflow_model",
        "AliyunDashScopeSettings": "aliyun_dashscope_model",
        "GeminiSettings":      "gemini_model",
        "GroqSettings":        "groq_model",
        "GrokSettings":        "grok_model",
        "ModelScopeSettings":  "modelscope_model",
        "OpenAISettings":      "openai_model",
        "OpenAICompatibleSettings": "openai_compatible_model",
    },
    "base_url": {
        "SiliconFlowSettings": "siliconflow_base_url",
        "AliyunDashScopeSettings": "aliyun_dashscope_base_url",
        "OpenAISettings":      "openai_base_url",
        "OpenAICompatibleSettings": "openai_compatible_base_url",
    },
    "thinking_mode": {
        "DeepSeekSettings": "deepseek_thinking_mode",
    },
    "reasoning_effort": {
        "DeepSeekSettings": "deepseek_reasoning_effort",
        "OpenAISettings":   "openai_reasoning_effort",
        "OpenAICompatibleSettings": "openai_compatible_reasoning_effort",
    },
    "enable_json_mode": {
        "DeepSeekSettings":    "deepseek_enable_json_mode",
        "ZhipuSettings":       "zhipu_enable_json_mode",
        "SiliconFlowSettings": "siliconflow_enable_json_mode",
        "GeminiSettings":      "gemini_enable_json_mode",
        "GroqSettings":        "groq_enable_json_mode",
        "GrokSettings":        "grok_enable_json_mode",
        "ModelScopeSettings":  "modelscope_enable_json_mode",
        "OpenAISettings":      "openai_enable_json_mode",
        "OpenAICompatibleSettings": "openai_compatible_enable_json_mode",
    },
    "temperature": {
        "OpenAISettings":      "openai_temperature",
        "AliyunDashScopeSettings": "aliyun_dashscope_temperature",
        "OpenAICompatibleSettings": "openai_compatible_temperature",
    },
    "timeout": {
        "OpenAISettings":      "openai_timeout",
        "AliyunDashScopeSettings": "aliyun_dashscope_timeout",
        "OpenAICompatibleSettings": "openai_compatible_timeout",
    },
}

# ── 保持不变 ──────────────────────────────────────────────
DPI = CONFIG["pdf_reader"]["dpi"]
CACHE_DIR = Path(CONFIG["pdf_reader"]["cache_dir"]).resolve()
GLOSSARY_PATH = Path(__file__).parent / "docs" / "glossary.csv"
TRANSLATION_LANG_IN = CONFIG["translation"]["lang_in"]
TRANSLATION_LANG_OUT = CONFIG["translation"]["lang_out"]
```

- [x] **Step 5: 添加 `import config` 到 test_services.py 顶部导入**

在 `tests/test_services.py` 顶部的 `from services import build_settings, render_page, sha256` 后增加一行：

```python
import config
```

- [x] **Step 6: 编写 config 层测试 — 验证新常量存在且有值**

在 `tests/test_services.py` 末尾追加：

```python
def test_config_provider_map_has_deepseek():
    assert "deepseek" in config.PROVIDER_MAP
    assert config.PROVIDER_MAP["deepseek"].__name__ == "DeepSeekSettings"

def test_config_field_map_api_key_exists():
    assert "DeepSeekSettings" in config.FIELD_MAP["api_key"]
    assert config.FIELD_MAP["api_key"]["DeepSeekSettings"] == "deepseek_api_key"

def test_config_raises_on_missing_api_key():
    import importlib
    import config as cfg
    import os
    original_key = os.environ.get("MODEL_API_KEY")
    try:
        os.environ["MODEL_API_KEY"] = "sk-your-api-key-here"
        with pytest.raises(ValueError, match="请设置 model.api_key"):
            importlib.reload(cfg)
    finally:
        if original_key is not None:
            os.environ["MODEL_API_KEY"] = original_key
        else:
            os.environ.pop("MODEL_API_KEY", None)
```

- [x] **Step 7: 运行现有测试确认回归范围**

Run: `pytest tests/ -v`
Expected: 现有 `test_build_settings_*` 测试失败（services.py 仍引用 `config.DEEPSEEK_API_KEY` 等旧常量），新增 config 测试通过。

- [x] **Step 8: Commit**

```bash
git add config.toml config.py tests/conftest.py tests/test_services.py
git commit -m "feat(config): add multi-model provider routing and field mapping"
```

archived-with: 2026-06-19-multi-model-provider
---

### Task 2: 引擎路由实现 — services.py

**Files:**
- Modify: `services.py:1-53`

**Interfaces:**
- Consumes: `config.PROVIDER_MAP`, `config.FIELD_MAP`, `config.MODEL_PROVIDER`, `config.MODEL_API_KEY`, `config.MODEL`, `config.MODEL_BASE_URL`, `config.MODEL_THINKING_MODE`, `config.MODEL_REASONING_EFFORT`, `config.MODEL_ENABLE_JSON_MODE`, `config.MODEL_TEMPERATURE`, `config.MODEL_TIMEOUT`
- Produces: `resolve_engine(provider: str) -> type[BaseModel]`
- Produces: `build_engine_kwargs(engine_cls: type[BaseModel]) -> dict`
- Modifies: `build_settings(single_page_pdf, user_prompt, output_dir) -> SettingsModel`（调用上述函数替代硬编码）

- [x] **Step 1: 编写 resolve_engine 和 build_engine_kwargs 的测试**

在 `tests/test_services.py` 末尾追加：

```python
def test_resolve_engine_deepseek(mock_config, monkeypatch):
    monkeypatch.setattr(config, "MODEL_PROVIDER", "deepseek")
    from services import resolve_engine
    from pdf2zh_next.config.translate_engine_model import DeepSeekSettings
    assert resolve_engine("deepseek") is DeepSeekSettings

def test_resolve_engine_unknown_fallback(mock_config, monkeypatch):
    monkeypatch.setattr(config, "MODEL_PROVIDER", "nonexistent")
    from services import resolve_engine
    from pdf2zh_next.config.translate_engine_model import OpenAICompatibleSettings
    assert resolve_engine("nonexistent") is OpenAICompatibleSettings

def test_build_engine_kwargs_deepseek(mock_config, monkeypatch):
    monkeypatch.setattr(config, "MODEL_API_KEY", "sk-test")
    monkeypatch.setattr(config, "MODEL", "deepseek-chat")
    monkeypatch.setattr(config, "MODEL_BASE_URL", "https://api.deepseek.com/v1")
    from services import build_engine_kwargs
    from pdf2zh_next.config.translate_engine_model import DeepSeekSettings
    kwargs = build_engine_kwargs(DeepSeekSettings)
    assert kwargs["deepseek_api_key"] == "sk-test"
    assert kwargs["deepseek_model"] == "deepseek-chat"
    assert kwargs["deepseek_base_url"] == "https://api.deepseek.com/v1"

def test_build_engine_kwargs_zhipu_ignores_thinking_mode(mock_config, monkeypatch):
    monkeypatch.setattr(config, "MODEL_THINKING_MODE", "enabled")
    from services import build_engine_kwargs
    from pdf2zh_next.config.translate_engine_model import ZhipuSettings
    kwargs = build_engine_kwargs(ZhipuSettings)
    assert "zhipu_thinking_mode" not in kwargs

def test_build_engine_kwargs_missing_api_key_raises(mock_config, monkeypatch):
    monkeypatch.setattr(config, "MODEL_API_KEY", None)
    monkeypatch.setattr(config, "MODEL", "some-model")
    from services import build_engine_kwargs
    from pdf2zh_next.config.translate_engine_model import DeepSeekSettings
    with pytest.raises(RuntimeError, match="未配置"):
        build_engine_kwargs(DeepSeekSettings)
```

- [x] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_services.py -v -k "resolve_engine or build_engine_kwargs"`
Expected: 全部 FAIL（`resolve_engine` 和 `build_engine_kwargs` 尚未定义）

- [x] **Step 3: 在 services.py 中实现 resolve_engine 和 build_engine_kwargs**

将 `services.py` 完整重写为：

```python
import hashlib
import logging

import pymupdf
from pdf2zh_next import SettingsModel
from pdf2zh_next.config.model import PDFSettings as Pdf2zhPDFSettings
from pdf2zh_next.config.model import TranslationSettings as Pdf2zhTranslationSettings
from pdf2zh_next.config.translate_engine_model import OpenAICompatibleSettings

import config

logger = logging.getLogger("pdf_reader")


def sha256(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def render_page(doc: pymupdf.Document, page_num: int, dpi: int) -> bytes:
    if page_num < 0 or page_num >= doc.page_count:
        raise ValueError("page out of range")
    page = doc[page_num]
    pix = page.get_pixmap(dpi=dpi)
    return pix.tobytes(output="png")


def resolve_engine(provider: str):
    engine_cls = config.PROVIDER_MAP.get(provider)
    if engine_cls is None:
        logger.info("Provider '%s' not found, falling back to OpenAI Compatible", provider)
        return OpenAICompatibleSettings
    logger.info("Using engine: %s (%s)", engine_cls.__name__, config.MODEL)
    return engine_cls


def build_engine_kwargs(engine_cls):
    engine_fields = engine_cls.model_fields
    engine_name = engine_cls.__name__
    kwargs = {}

    for unified_name in ("api_key", "model", "base_url", "thinking_mode",
                         "reasoning_effort", "enable_json_mode",
                         "temperature", "timeout"):
        engine_field = config.FIELD_MAP.get(unified_name, {}).get(engine_name)
        if engine_field is None:
            continue
        if engine_field not in engine_fields:
            continue

        value = getattr(config, f"MODEL_{unified_name.upper()}", None)

        if value is not None:
            kwargs[engine_field] = value
        elif unified_name in ("api_key", "model"):
            raise RuntimeError(f"model.{unified_name} 未配置")
        elif unified_name == "base_url":
            pass
        else:
            logger.warning("当前引擎不支持 %s，已忽略", unified_name)

    return kwargs


def build_settings(single_page_pdf: str, user_prompt: str | None = None, output_dir: str | None = None) -> SettingsModel:
    engine_cls = resolve_engine(config.MODEL_PROVIDER)
    engine_kwargs = build_engine_kwargs(engine_cls)

    translation_kwargs = {
        "lang_in": config.TRANSLATION_LANG_IN,
        "lang_out": config.TRANSLATION_LANG_OUT,
        "ignore_cache": True,
    }
    if user_prompt and user_prompt.strip():
        translation_kwargs["custom_system_prompt"] = user_prompt.strip()
    if config.GLOSSARY_PATH.exists() and config.GLOSSARY_PATH.stat().st_size > 0:
        translation_kwargs["glossaries"] = str(config.GLOSSARY_PATH)
    if output_dir is not None:
        translation_kwargs["output"] = output_dir

    return SettingsModel(
        translation=Pdf2zhTranslationSettings(**translation_kwargs),
        pdf=Pdf2zhPDFSettings(
            pages="1",
            no_dual=True,
            only_include_translated_page=True,
            watermark_output_mode="no_watermark",
        ),
        translate_engine_settings=engine_cls(**engine_kwargs),
    )
```

- [x] **Step 4: 运行新增测试确认通过**

Run: `pytest tests/test_services.py -v -k "resolve_engine or build_engine_kwargs"`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add services.py tests/test_services.py
git commit -m "feat(services): add multi-model engine routing and field mapping"
```

archived-with: 2026-06-19-multi-model-provider
---

### Task 3: 测试套件 — 更新现有测试 + 新增 provider 测试

**Files:**
- Modify: `tests/test_services.py:45-61`（更新现有 build_settings 测试）
- Modify: `tests/test_services.py`（末尾追加新测试）

**Interfaces:**
- Consumes: `services.build_settings()`, `services.resolve_engine()`, `services.build_engine_kwargs()`
- Consumes: `config.PROVIDER_MAP`, `config.FIELD_MAP`, 所有 `config.MODEL_*` 常量
- Consumes: `tests/conftest.py::mock_config` fixture

- [x] **Step 1: 更新现有 test_build_settings_* 测试适配 mock_config**

将 `tests/test_services.py` 中现有 4 个 `test_build_settings_*` 测试的签名添加 `mock_config` 参数。找到并替换：

```python
def test_build_settings_basic(mock_config):
    settings = build_settings("dummy.pdf")
    assert settings.translation.lang_in == "en"
    assert settings.translation.lang_out == "zh"
    assert settings.translation.ignore_cache is True

def test_build_settings_with_prompt(mock_config):
    settings = build_settings("dummy.pdf", "translate waveguide as 波导")
    assert settings.translation.custom_system_prompt == "translate waveguide as 波导"

def test_build_settings_with_output_dir(mock_config):
    settings = build_settings("dummy.pdf", output_dir="/tmp/translate_output")
    assert settings.translation.output == "/tmp/translate_output"

def test_build_settings_without_output_dir(mock_config):
    settings = build_settings("dummy.pdf")
    assert getattr(settings.translation, "output", None) is None
```

注意：`test_sha256_consistent`、`test_sha256_different`、`test_render_page_*` 不需要 mock_config，保持不变。

- [x] **Step 2: 运行更新后的现有测试确认通过**

Run: `pytest tests/test_services.py -v -k "test_build_settings_basic or test_build_settings_with_prompt or test_build_settings_with_output_dir or test_build_settings_without_output_dir"`
Expected: PASS（4 个测试均通过）

- [x] **Step 3: 新增 test_build_settings_deepseek_with_thinking 测试**

在 `tests/test_services.py` 末尾追加：

```python
def test_build_settings_deepseek_with_thinking(mock_config, monkeypatch):
    monkeypatch.setattr(config, "MODEL_PROVIDER", "deepseek")
    monkeypatch.setattr(config, "MODEL_THINKING_MODE", "enabled")
    monkeypatch.setattr(config, "MODEL_REASONING_EFFORT", "high")
    from pdf2zh_next.config.translate_engine_model import DeepSeekSettings

    settings = build_settings("dummy.pdf")
    engine = settings.translate_engine_settings

    assert isinstance(engine, DeepSeekSettings)
    assert engine.deepseek_api_key == "sk-test-key"
    assert engine.deepseek_model == "deepseek-v4-flash"
    assert engine.deepseek_thinking_mode == "enabled"
    assert engine.deepseek_reasoning_effort == "high"
```

- [x] **Step 4: 新增 test_build_settings_unknown_provider 测试**

```python
def test_build_settings_unknown_provider(mock_config, monkeypatch):
    monkeypatch.setattr(config, "MODEL_PROVIDER", "some_custom_gateway")
    monkeypatch.setattr(config, "MODEL_API_KEY", "sk-custom")
    monkeypatch.setattr(config, "MODEL", "custom-model")
    monkeypatch.setattr(config, "MODEL_BASE_URL", "https://custom.api/v1")
    from pdf2zh_next.config.translate_engine_model import OpenAICompatibleSettings

    settings = build_settings("dummy.pdf")
    engine = settings.translate_engine_settings

    assert isinstance(engine, OpenAICompatibleSettings)
    assert engine.openai_compatible_api_key == "sk-custom"
    assert engine.openai_compatible_model == "custom-model"
    assert engine.openai_compatible_base_url == "https://custom.api/v1"
```

- [x] **Step 5: 新增 test_build_settings_unsupported_field_ignored 测试**

```python
def test_build_settings_unsupported_field_ignored(mock_config, monkeypatch):
    monkeypatch.setattr(config, "MODEL_PROVIDER", "zhipu")
    monkeypatch.setattr(config, "MODEL_THINKING_MODE", "enabled")
    monkeypatch.setattr(config, "MODEL_TEMPERATURE", "0.5")
    from pdf2zh_next.config.translate_engine_model import ZhipuSettings

    settings = build_settings("dummy.pdf")
    engine = settings.translate_engine_settings

    assert isinstance(engine, ZhipuSettings)
    assert engine.zhipu_api_key == "sk-test-key"
    assert engine.zhipu_model == "deepseek-v4-flash"
    assert not hasattr(engine, "zhipu_thinking_mode")
    assert not hasattr(engine, "zhipu_temperature")
```

- [x] **Step 6: 新增 test_build_settings_missing_api_key_raises 测试**

```python
def test_build_settings_missing_api_key_raises(mock_config, monkeypatch):
    monkeypatch.setattr(config, "MODEL_API_KEY", None)
    with pytest.raises(RuntimeError, match="未配置"):
        build_settings("dummy.pdf")
```

- [x] **Step 7: 运行全部测试**

Run: `pytest tests/test_services.py -v`
Expected: 全部 20 个测试 PASS（8 个原有 + 3 配置测试 + 5 路由测试 + 4 provider 测试）

- [x] **Step 8: Commit**

```bash
git add tests/test_services.py tests/conftest.py
git commit -m "test: update build_settings tests for multi-model provider"
```

archived-with: 2026-06-19-multi-model-provider
---

### Task 4: 文档与模板 — config.example.toml + README.md

**Files:**
- Modify: `config.example.toml:1-65`
- Modify: `README.md:90-103`

**Interfaces:**
- 无代码接口，纯文档变更

- [x] **Step 1: 更新 config.example.toml**

将 `config.example.toml` 完整替换为：

```toml
# =============================================================================
# PDF 阅读器 — 配置文件模板
# =============================================================================
# 使用方式：
#   1. 复制此文件为 config.toml：  cp config.example.toml config.toml
#   2. 编辑 config.toml 填入你的实际配置
#   3. config.toml 已被 .gitignore 忽略，不会提交到 git
#
# API Key 配置方式（二选一）：
#   方式 A（推荐）：设置环境变量 MODEL_API_KEY
#       PowerShell:  $env:MODEL_API_KEY = "sk-你的密钥"
#       CMD:          set MODEL_API_KEY=sk-你的密钥
#   方式 B：直接在下方的 api_key 字段填写
#       ⚠️ 注意不要将含真实 API Key 的 config.toml 提交到 git
#
# 支持的 provider 及高级参数：
#   ┌────────────────────┬──────────────────────────────────────────┐
#   │ provider           │ 支持的高级参数                           │
#   ├────────────────────┼──────────────────────────────────────────┤
#   │ deepseek           │ thinking_mode, reasoning_effort          │
#   │ zhipu              │ enable_json_mode                         │
#   │ siliconflow        │ enable_json_mode                         │
#   │ aliyun             │ temperature, timeout, enable_json_mode   │
#   │ gemini             │ enable_json_mode                         │
#   │ groq               │ enable_json_mode                         │
#   │ grok               │ enable_json_mode                         │
#   │ modelscope         │ enable_json_mode                         │
#   │ openai             │ temperature, timeout, reasoning_effort,  │
#   │                    │ enable_json_mode                         │
#   │ openai_compatible  │ temperature, timeout, reasoning_effort,  │
#   │                    │ enable_json_mode                         │
#   └────────────────────┴──────────────────────────────────────────┘
#   未列出的 provider 名自动走 openai_compatible 兜底（OpenAI 兼容接口）
# =============================================================================

# -----------------------------------------------------------------------------
# PDF 阅读器设置
# -----------------------------------------------------------------------------
[pdf_reader]
# 页面渲染 DPI（越高越清晰，但图片越大）
dpi = 200
# 翻译缓存目录（保存 right.pdf 等中间文件）
cache_dir = "cache"

# -----------------------------------------------------------------------------
# 模型配置（翻译服务使用的 LLM 模型）
# -----------------------------------------------------------------------------
[model]
# 模型供应商（必填）
#   可选值：deepseek / zhipu / siliconflow / aliyun / gemini / groq / grok
#          modelscope / openai / openai_compatible
provider = "deepseek"

# API Key（必填）
#   - 也可通过环境变量 MODEL_API_KEY 设置（优先级更高）
api_key = "sk-your-api-key-here"

# 模型名称（必填）
model = "deepseek-v4-flash"

# API 基础地址（可选，留空则使用引擎内置默认值）
#   - 仅 siliconflow / aliyun / openai / openai_compatible 支持自定义
base_url = "https://api.deepseek.com/v1"

# -----------------------------------------------------------------------------
# 高级参数（全部可选，仅部分引擎支持）
# -----------------------------------------------------------------------------
# thinking_mode = "enabled"     # deepseek 专用：思考模式（enabled / disabled）
# reasoning_effort = "high"     # deepseek / openai / openai_compatible
# enable_json_mode = false      # 强制 JSON 输出模式
# temperature = "0.7"           # openai / aliyun / openai_compatible
# timeout = "500"               # openai / aliyun / openai_compatible（秒）

# -----------------------------------------------------------------------------
# 翻译设置
# -----------------------------------------------------------------------------
[translation]
# 源语言（ISO 639-1 代码）
lang_in = "en"
# 目标语言（ISO 639-1 代码）
lang_out = "zh"
# 每秒最大翻译请求数（避免触发 API 限流）
qps = 4

# -----------------------------------------------------------------------------
# 服务器设置
# -----------------------------------------------------------------------------
[server]
# 监听地址（127.0.0.1 = 仅本机访问，0.0.0.0 = 局域网内可访问）
host = "127.0.0.1"
# 监听端口
port = 5000
# 调试模式（开发时开启，生产环境关闭）
debug = true
```

- [x] **Step 2: 更新 README.md 配置章节**

将 README.md 的第 93-103 行（"### 配置模型 API Key" 部分）替换为：

```markdown
### 配置模型

编辑 `config.toml` 的 `[model]` 段：

```toml
[model]
provider = "deepseek"                          # 供应商
api_key  = "sk-your-api-key"                   # API Key
model    = "deepseek-v4-flash"                 # 模型名
base_url = "https://api.deepseek.com/v1"       # 可选
```

也可通过环境变量设置 `MODEL_API_KEY`（推荐，优先级更高）：

```powershell
$env:MODEL_API_KEY = "sk-your-api-key"
```

#### 切换供应商

将 `provider` 改为其他值即可，示例：

```toml
# 使用智谱
provider = "zhipu"
api_key  = "your-zhipu-key"
model    = "glm-4-flash"

# 使用 OpenAI 兼容接口（如本地 Ollama）
provider = "openai_compatible"
api_key  = "ollama"
model    = "qwen2.5:7b"
base_url = "http://localhost:11434/v1"
```

支持 10 个内置引擎 + OpenAI 通用兼容接口，详见 `config.example.toml` 中的完整表格。

> **迁移提示：** 旧版 `[deepseek]` 配置段已废弃，请改为 `[model]`。旧环境变量 `DEEPSEEK_API_KEY` 不再支持，请改用 `MODEL_API_KEY`。

其余配置项（语言对、端口等）均可在 `config.toml` 中修改，文件内含详细的中文注释。
```

- [x] **Step 3: 运行 ruff check 确认零 lint 错误**

```bash
pip install ruff; if ($?) { ruff check }
```
Expected: 无输出（零错误）

- [x] **Step 4: 运行全部测试确认**

Run: `pytest tests/ -v`
Expected: 全部 20 个测试 PASS

- [x] **Step 5: Commit**

```bash
git add config.example.toml README.md
git commit -m "docs: update config template and README for multi-model provider"
```
