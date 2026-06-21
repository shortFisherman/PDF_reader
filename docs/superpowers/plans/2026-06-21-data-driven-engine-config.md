---
change: data-driven-engine-config
design-doc: docs/superpowers/specs/2026-06-21-data-driven-engine-config-design.md
base-ref: 4952acf8150e5bf8d28623e119015067d9601e9d
---

# Data-Driven Engine Configuration 实现计划

> **对于 agentic workers：** 必须子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 按任务逐一实现。步骤使用 checkbox（`- [ ]`）语法跟踪。

**目标：** 将 `config.py` 中分散在 8 个子字典（79 条字段映射）和 1 个子字典（10 条 provider 映射）的翻译引擎配置，重构成声明式 `EngineSpec` 注册表，每个引擎一行声明。

**架构：** 在 `config.py` 定义 `EngineSpec` frozen dataclass，包含 `provider`、`settings_cls`、`field_map`、`required_fields`。从现有 `PROVIDER_MAP` + `FIELD_MAP` 机械推导出 10 引擎的 `ENGINE_REGISTRY` 和派生 `PROVIDER_INDEX`。`services.py` 的 `resolve_engine` 和 `build_engine_kwargs` 改造为接收 `EngineSpec` 参数，内部使用 `CONFIG_ATTR_MAP` 映射 unified_name → config 模块属性，运行时校验 `settings_cls.model_fields`。

**技术栈：** Python 3.12+, dataclasses, pdf2zh-next, pytest, ruff

## 全局约束

- `config.toml` 字段名和结构不变
- 运行时引擎选择行为不变（未知 provider 回退到 `OpenAICompatibleSettings`）
- `api_key` 和 `model` 为必填字段，缺失抛出 `RuntimeError`
- `base_url` 为静默可选字段，缺失时不警告
- 其它可选字段（thinking_mode, reasoning_effort, enable_json_mode, temperature, timeout）配置了值但引擎不支持时 `logger.warning`
- 引擎 Settings 类字段变更（pdf2zh-next 版本升级）时不注册时报错，而是运行时跳过+警告
- `FIELD_MAP` 和 `PROVIDER_MAP` 仅被 `services.py` 引用，一起删除

---

### 任务 1：等价回归基线

**文件：**
- 创建：`tests/test_engine_registry.py`
- 读取：`config.py:40-113`（现有 PROVIDER_MAP + FIELD_MAP）
- 读取：`services.py:32-69`（现有 resolve_engine + build_engine_kwargs）

**接口：**
- 消费：`config.PROVIDER_MAP`（现有），`config.FIELD_MAP`（现有）
- 消费：`services.resolve_engine`（现有），`services.build_engine_kwargs`（现有）
- 产出：基线测试，后续任务 2、3 的验证门

- [ ] **步骤 1：编写等价回归测试文件**

```python
# tests/test_engine_registry.py
"""等价回归基线：对所有 10 引擎，新旧路径产出一致"""
import config
from services import resolve_engine, build_engine_kwargs


ALL_PROVIDERS = [
    "deepseek",
    "zhipu",
    "siliconflow",
    "aliyun",
    "gemini",
    "groq",
    "grok",
    "modelscope",
    "openai",
    "openai_compatible",
]


def test_all_providers_resolve_to_correct_class():
    for provider in ALL_PROVIDERS:
        cls = resolve_engine(provider)
        expected = config.PROVIDER_MAP[provider]
        assert cls is expected, (
            f"resolve_engine('{provider}') → {cls.__name__}, "
            f"expected {expected.__name__}"
        )


def test_unknown_provider_falls_back_to_openai_compatible():
    cls = resolve_engine("nonexistent_provider_xyz")
    from pdf2zh_next.config.translate_engine_model import OpenAICompatibleSettings
    assert cls is OpenAICompatibleSettings


def test_all_engines_build_kwargs_structure(monkeypatch):
    monkeypatch.setattr(config, "MODEL_API_KEY", "sk-test-key")
    monkeypatch.setattr(config, "MODEL", "test-model")
    monkeypatch.setattr(config, "MODEL_BASE_URL", "https://test.api/v1")
    monkeypatch.setattr(config, "MODEL_THINKING_MODE", "enabled")
    monkeypatch.setattr(config, "MODEL_REASONING_EFFORT", "high")
    monkeypatch.setattr(config, "MODEL_ENABLE_JSON_MODE", "true")
    monkeypatch.setattr(config, "MODEL_TEMPERATURE", "0.3")
    monkeypatch.setattr(config, "MODEL_TIMEOUT", "60")

    for provider in ALL_PROVIDERS:
        engine_cls = resolve_engine(provider)
        kwargs = build_engine_kwargs(engine_cls)
        assert isinstance(kwargs, dict), (
            f"build_engine_kwargs({engine_cls.__name__}) returned {type(kwargs)}"
        )
        assert "api_key" in config.FIELD_MAP, "baseline FIELD_MAP must have api_key"
        engine_name = engine_cls.__name__
        api_field = config.FIELD_MAP["api_key"].get(engine_name)
        model_field = config.FIELD_MAP["model"].get(engine_name)
        assert kwargs[api_field] == "sk-test-key", (
            f"{engine_name}: expected api_key at '{api_field}'"
        )
        assert kwargs[model_field] == "test-model", (
            f"{engine_name}: expected model at '{model_field}'"
        )
```

- [ ] **步骤 2：运行测试验证在现状代码上通过**

```powershell
python -m pytest tests/test_engine_registry.py -v
```

预期：3 个测试全部 PASS（在现有 PROVIDER_MAP + FIELD_MAP + resolve_engine + build_engine_kwargs 上验证基线）

- [ ] **步骤 3：提交基线测试**

```bash
git add tests/test_engine_registry.py
git commit -m "test: add equivalence regression baseline for engine registry"
```

---

### 任务 2：实现 EngineSpec 注册表

**文件：**
- 修改：`config.py`（在 `PROVIDER_MAP` 之后新增 EngineSpec + ENGINE_REGISTRY + PROVIDER_INDEX）
- 不删除：`PROVIDER_MAP` 和 `FIELD_MAP`（任务 3 再删除）

**接口：**
- 消费：`config.PROVIDER_MAP`（现有，作为推导依据），`config.FIELD_MAP`（现有）
- 产出：`config.EngineSpec`（dataclass），`config.ENGINE_REGISTRY: list[EngineSpec]`，`config.PROVIDER_INDEX: dict[str, EngineSpec]`

- [ ] **步骤 1：在 `config.py` 定义 `EngineSpec` dataclass 和注册表**

在 `config.py` 的 `PROVIDER_MAP` 定义之后（约第 51 行后）插入以下代码。注意：**不删除** PROVIDER_MAP 和 FIELD_MAP。

```python
# config.py —— 在 PROVIDER_MAP 定义之后、FIELD_MAP 定义之前插入

from dataclasses import dataclass


@dataclass(frozen=True)
class EngineSpec:
    provider: str
    settings_cls: type
    field_map: dict[str, str]
    required_fields: tuple[str, ...]


def _derive_field_map(engine_class_name: str) -> dict[str, str]:
    """从现有 FIELD_MAP 机械推导单个引擎的 field_map"""
    result: dict[str, str] = {}
    for unified_name, class_mapping in FIELD_MAP.items():
        if engine_class_name in class_mapping:
            result[unified_name] = class_mapping[engine_class_name]
    return result


ENGINE_REGISTRY: list[EngineSpec] = [
    EngineSpec(
        provider="deepseek",
        settings_cls=DeepSeekSettings,
        field_map=_derive_field_map("DeepSeekSettings"),
        required_fields=("api_key", "model"),
    ),
    EngineSpec(
        provider="zhipu",
        settings_cls=ZhipuSettings,
        field_map=_derive_field_map("ZhipuSettings"),
        required_fields=("api_key", "model"),
    ),
    EngineSpec(
        provider="siliconflow",
        settings_cls=SiliconFlowSettings,
        field_map=_derive_field_map("SiliconFlowSettings"),
        required_fields=("api_key", "model"),
    ),
    EngineSpec(
        provider="aliyun",
        settings_cls=AliyunDashScopeSettings,
        field_map=_derive_field_map("AliyunDashScopeSettings"),
        required_fields=("api_key", "model"),
    ),
    EngineSpec(
        provider="gemini",
        settings_cls=GeminiSettings,
        field_map=_derive_field_map("GeminiSettings"),
        required_fields=("api_key", "model"),
    ),
    EngineSpec(
        provider="groq",
        settings_cls=GroqSettings,
        field_map=_derive_field_map("GroqSettings"),
        required_fields=("api_key", "model"),
    ),
    EngineSpec(
        provider="grok",
        settings_cls=GrokSettings,
        field_map=_derive_field_map("GrokSettings"),
        required_fields=("api_key", "model"),
    ),
    EngineSpec(
        provider="modelscope",
        settings_cls=ModelScopeSettings,
        field_map=_derive_field_map("ModelScopeSettings"),
        required_fields=("api_key", "model"),
    ),
    EngineSpec(
        provider="openai",
        settings_cls=OpenAISettings,
        field_map=_derive_field_map("OpenAISettings"),
        required_fields=("api_key", "model"),
    ),
    EngineSpec(
        provider="openai_compatible",
        settings_cls=OpenAICompatibleSettings,
        field_map=_derive_field_map("OpenAICompatibleSettings"),
        required_fields=("api_key", "model"),
    ),
]


PROVIDER_INDEX: dict[str, EngineSpec] = {
    spec.provider: spec for spec in ENGINE_REGISTRY
}
```

- [ ] **步骤 2：运行导入测试确认注册表无语法错误**

```powershell
python -c "import config; print(len(config.ENGINE_REGISTRY), 'engines registered'); print(dict(config.PROVIDER_INDEX))"
```

预期：输出 `10 engines registered` 和 provider 映射字典

- [ ] **步骤 3：运行等价回归测试确认旧代码不受影响**

```powershell
python -m pytest tests/test_engine_registry.py -v
```

预期：3 个测试全部 PASS（旧路径未受干扰）

- [ ] **步骤 4：提交注册表实现**

```bash
git add config.py
git commit -m "feat: add EngineSpec dataclass and ENGINE_REGISTRY"
```

---

### 任务 3：重构 services 使用 EngineSpec

**文件：**
- 修改：`services.py:32-110`（resolve_engine, build_engine_kwargs, build_settings）
- 修改：`config.py`（删除 `PROVIDER_MAP` 和 `FIELD_MAP`）
- 修改：`tests/test_engine_registry.py`（新增新路径等价性测试）
- 不修改：`tests/test_services.py`（所有现有测试必须无改动通过，提供回归防护）

**接口：**
- 消费：`config.EngineSpec`（任务 2 产出），`config.PROVIDER_INDEX`
- 消费：`config.MODEL_PROVIDER`, `config.MODEL_API_KEY`, `config.MODEL`, `config.MODEL_BASE_URL`, 等
- 产出：`resolve_engine(provider: str) -> EngineSpec`（返回类型从 `type` 变为 `EngineSpec`）
- 产出：`build_engine_kwargs(spec: EngineSpec) -> dict`（参数从 `engine_cls` 变为 `spec: EngineSpec`）
- 产出：`build_settings(...)` 内部调用链更新为使用 EngineSpec

- [ ] **步骤 1：在 `tests/test_engine_registry.py` 新增新路径等价性测试**

在文件末尾追加以下测试。这些测试比较新旧 `build_engine_kwargs` 路径对 10 引擎的产出是否完全一致，作为迁移正确性的门。

```python
# tests/test_engine_registry.py 追加内容

def test_engine_registry_covers_all_providers():
    existing_providers = set(config.PROVIDER_MAP.keys())
    registry_providers = set(config.PROVIDER_INDEX.keys())
    assert existing_providers == registry_providers, (
        f"Missing: {existing_providers - registry_providers}, "
        f"Extra: {registry_providers - existing_providers}"
    )


def _old_build_engine_kwargs(engine_cls):
    """快照当前 build_engine_kwargs 的实现作为对照"""
    engine_fields = engine_cls.model_fields
    engine_name = engine_cls.__name__
    kwargs = {}
    for unified_name in ("api_key", "model", "base_url", "thinking_mode",
                         "reasoning_effort", "enable_json_mode",
                         "temperature", "timeout"):
        config_attr_name = "MODEL" if unified_name == "model" else f"MODEL_{unified_name.upper()}"
        value = getattr(config, config_attr_name, None)
        engine_field = config.FIELD_MAP.get(unified_name, {}).get(engine_name)
        if engine_field is None:
            if value is not None and unified_name not in ("api_key", "model", "base_url"):
                continue
            continue
        if engine_field not in engine_fields:
            continue
        if value is not None:
            kwargs[engine_field] = value
        elif unified_name in ("api_key", "model"):
            raise RuntimeError(f"model.{unified_name} 未配置")
        elif unified_name == "base_url":
            pass
    return kwargs


def _new_build_engine_kwargs(spec):
    """新路径 build_engine_kwargs，与 services.py 重构后保持一致"""
    CONFIG_ATTR_MAP = {
        "model": "MODEL",
        "api_key": "MODEL_API_KEY",
        "base_url": "MODEL_BASE_URL",
        "thinking_mode": "MODEL_THINKING_MODE",
        "reasoning_effort": "MODEL_REASONING_EFFORT",
        "enable_json_mode": "MODEL_ENABLE_JSON_MODE",
        "temperature": "MODEL_TEMPERATURE",
        "timeout": "MODEL_TIMEOUT",
    }
    kwargs = {}
    engine_fields = spec.settings_cls.model_fields
    for unified_name, engine_field in spec.field_map.items():
        config_attr = CONFIG_ATTR_MAP[unified_name]
        value = getattr(config, config_attr, None)
        if engine_field not in engine_fields:
            import logging
            logger = logging.getLogger("pdf_reader")
            logger.warning("引擎 %s 不支持字段 %s，已跳过", spec.provider, engine_field)
            continue
        if value is not None:
            kwargs[engine_field] = value
        elif unified_name in spec.required_fields:
            raise RuntimeError(f"model.{unified_name} 未配置")
        elif unified_name == "base_url":
            pass
        else:
            import logging
            logger = logging.getLogger("pdf_reader")
            logger.warning("当前引擎不支持 %s，已忽略", unified_name)
    return kwargs


def test_new_path_matches_old_path(monkeypatch):
    monkeypatch.setattr(config, "MODEL_API_KEY", "sk-test-key")
    monkeypatch.setattr(config, "MODEL", "test-model")
    monkeypatch.setattr(config, "MODEL_BASE_URL", "https://test.api/v1")
    monkeypatch.setattr(config, "MODEL_THINKING_MODE", "enabled")
    monkeypatch.setattr(config, "MODEL_REASONING_EFFORT", "high")
    monkeypatch.setattr(config, "MODEL_ENABLE_JSON_MODE", "true")
    monkeypatch.setattr(config, "MODEL_TEMPERATURE", "0.3")
    monkeypatch.setattr(config, "MODEL_TIMEOUT", "60")

    for provider, spec in config.PROVIDER_INDEX.items():
        old_kwargs = _old_build_engine_kwargs(spec.settings_cls)
        new_kwargs = _new_build_engine_kwargs(spec)
        assert old_kwargs == new_kwargs, (
            f"{provider}: old={old_kwargs} != new={new_kwargs}"
        )
```

- [ ] **步骤 2：运行新旧路径对比测试，确认新路径实现仍有等价表现**

```powershell
python -m pytest tests/test_engine_registry.py::test_new_path_matches_old_path -v
python -m pytest tests/test_engine_registry.py::test_engine_registry_covers_all_providers -v
```

预期：`test_new_path_matches_old_path` FAIL（还未实现 `_new_build_engine_kwargs` 对应的真实代码——目的是确认测试存在且可执行），`test_engine_registry_covers_all_providers` PASS

- [ ] **步骤 3：重写 `services.py` 的 `resolve_engine`**

将 `services.py` 第 32-38 行替换为：

```python
def resolve_engine(provider: str) -> config.EngineSpec:  # noqa: ANN201
    spec = config.PROVIDER_INDEX.get(provider)
    if spec is None:
        logger.info("Provider '%s' not found, falling back to OpenAI Compatible", provider)
        from pdf2zh_next.config.translate_engine_model import OpenAICompatibleSettings
        return config.EngineSpec(
            provider="openai_compatible",
            settings_cls=OpenAICompatibleSettings,
            field_map={},
            required_fields=(),
        )
    logger.info("Using engine: %s (%s)", spec.settings_cls.__name__, config.MODEL)
    return spec
```

- [ ] **步骤 4：重写 `services.py` 的 `build_engine_kwargs`**

将 `services.py` 第 41-69 行替换为：

```python
CONFIG_ATTR_MAP: dict[str, str] = {
    "model": "MODEL",
    "api_key": "MODEL_API_KEY",
    "base_url": "MODEL_BASE_URL",
    "thinking_mode": "MODEL_THINKING_MODE",
    "reasoning_effort": "MODEL_REASONING_EFFORT",
    "enable_json_mode": "MODEL_ENABLE_JSON_MODE",
    "temperature": "MODEL_TEMPERATURE",
    "timeout": "MODEL_TIMEOUT",
}


def build_engine_kwargs(spec: config.EngineSpec) -> dict:  # noqa: ANN001, ANN201
    engine_fields = spec.settings_cls.model_fields
    kwargs: dict = {}

    for unified_name, engine_field in spec.field_map.items():
        config_attr = CONFIG_ATTR_MAP[unified_name]
        value = getattr(config, config_attr, None)

        if engine_field not in engine_fields:
            logger.warning("引擎 %s 不支持字段 %s，已跳过", spec.provider, engine_field)
            continue

        if value is not None:
            kwargs[engine_field] = value
        elif unified_name in spec.required_fields:
            raise RuntimeError(f"model.{unified_name} 未配置")
        elif unified_name == "base_url":
            pass
        else:
            logger.warning("当前引擎不支持 %s，已忽略", unified_name)

    return kwargs
```

- [ ] **步骤 5：更新 `services.py` 的 `build_settings` 调用链**

将 `services.py` 第 79-80 行和第 109 行更新为：

```python
# 第 79-80 行替换为：
    spec = resolve_engine(config.MODEL_PROVIDER)
    engine_kwargs = build_engine_kwargs(spec)

# 第 109 行替换为：
        translate_engine_settings=spec.settings_cls(**engine_kwargs),
```

最终 `build_settings` 函数的关键部分如下（仅变更这 3 行，其余不变）：

```python
def build_settings(
    single_page_pdf: str,
    user_prompt: str | None = None,
    output_dir: str | None = None,
    glossary_paths: list[str] | None = None,
    debug: bool = False,
) -> SettingsModel:
    spec = resolve_engine(config.MODEL_PROVIDER)
    engine_kwargs = build_engine_kwargs(spec)

    translation_kwargs = {
        "lang_in": config.TRANSLATION_LANG_IN,
        "lang_out": config.TRANSLATION_LANG_OUT,
        "ignore_cache": True,
        "save_auto_extracted_glossary": True,
    }
    # ... (中间保持不变) ...
    return SettingsModel(
        basic=BasicSettings(debug=debug),
        translation=Pdf2zhTranslationSettings(**translation_kwargs),
        pdf=Pdf2zhPDFSettings(
            pages="1",
            no_dual=True,
            only_include_translated_page=True,
            watermark_output_mode="no_watermark",
        ),
        translate_engine_settings=spec.settings_cls(**engine_kwargs),
    )
```

- [ ] **步骤 6：运行等价回归测试确认新旧路径一致**

```powershell
python -m pytest tests/test_engine_registry.py -v
```

预期：全部 PASS（包括 `test_new_path_matches_old_path`）

- [ ] **步骤 7：删除 `config.py` 的 `PROVIDER_MAP` 和 `FIELD_MAP`**

删除 `config.py` 第 40-113 行（即 `PROVIDER_MAP` 和 `FIELD_MAP` 定义），同时删除 `_derive_field_map` 辅助函数（不再需要）。

`_derive_field_map` 函数在 ENGINE_REGISTRY 推导完成后已无价值（注册表现在直接包含硬编码的 field_map）。将其替换为每个引擎的显式 field_map 字面量——机械推导仅用于注册表编写的正确性保障，运行时不需要 `_derive_field_map`。

因此，所有 10 个 `EngineSpec` 的 `field_map` 参数从 `_derive_field_map("ClassName")` 替换为显式字典。例如：

```python
ENGINE_REGISTRY: list[EngineSpec] = [
    EngineSpec(
        provider="deepseek",
        settings_cls=DeepSeekSettings,
        field_map={
            "api_key": "deepseek_api_key",
            "model": "deepseek_model",
            "thinking_mode": "deepseek_thinking_mode",
            "reasoning_effort": "deepseek_reasoning_effort",
            "enable_json_mode": "deepseek_enable_json_mode",
        },
        required_fields=("api_key", "model"),
    ),
    EngineSpec(
        provider="zhipu",
        settings_cls=ZhipuSettings,
        field_map={
            "api_key": "zhipu_api_key",
            "model": "zhipu_model",
            "enable_json_mode": "zhipu_enable_json_mode",
        },
        required_fields=("api_key", "model"),
    ),
    EngineSpec(
        provider="siliconflow",
        settings_cls=SiliconFlowSettings,
        field_map={
            "api_key": "siliconflow_api_key",
            "model": "siliconflow_model",
            "base_url": "siliconflow_base_url",
            "enable_json_mode": "siliconflow_enable_json_mode",
        },
        required_fields=("api_key", "model"),
    ),
    EngineSpec(
        provider="aliyun",
        settings_cls=AliyunDashScopeSettings,
        field_map={
            "api_key": "aliyun_dashscope_api_key",
            "model": "aliyun_dashscope_model",
            "base_url": "aliyun_dashscope_base_url",
            "temperature": "aliyun_dashscope_temperature",
            "timeout": "aliyun_dashscope_timeout",
        },
        required_fields=("api_key", "model"),
    ),
    EngineSpec(
        provider="gemini",
        settings_cls=GeminiSettings,
        field_map={
            "api_key": "gemini_api_key",
            "model": "gemini_model",
            "enable_json_mode": "gemini_enable_json_mode",
        },
        required_fields=("api_key", "model"),
    ),
    EngineSpec(
        provider="groq",
        settings_cls=GroqSettings,
        field_map={
            "api_key": "groq_api_key",
            "model": "groq_model",
            "enable_json_mode": "groq_enable_json_mode",
        },
        required_fields=("api_key", "model"),
    ),
    EngineSpec(
        provider="grok",
        settings_cls=GrokSettings,
        field_map={
            "api_key": "grok_api_key",
            "model": "grok_model",
            "enable_json_mode": "grok_enable_json_mode",
        },
        required_fields=("api_key", "model"),
    ),
    EngineSpec(
        provider="modelscope",
        settings_cls=ModelScopeSettings,
        field_map={
            "api_key": "modelscope_api_key",
            "model": "modelscope_model",
            "enable_json_mode": "modelscope_enable_json_mode",
        },
        required_fields=("api_key", "model"),
    ),
    EngineSpec(
        provider="openai",
        settings_cls=OpenAISettings,
        field_map={
            "api_key": "openai_api_key",
            "model": "openai_model",
            "base_url": "openai_base_url",
            "reasoning_effort": "openai_reasoning_effort",
            "enable_json_mode": "openai_enable_json_mode",
            "temperature": "openai_temperature",
            "timeout": "openai_timeout",
        },
        required_fields=("api_key", "model"),
    ),
    EngineSpec(
        provider="openai_compatible",
        settings_cls=OpenAICompatibleSettings,
        field_map={
            "api_key": "openai_compatible_api_key",
            "model": "openai_compatible_model",
            "base_url": "openai_compatible_base_url",
            "reasoning_effort": "openai_compatible_reasoning_effort",
            "enable_json_mode": "openai_compatible_enable_json_mode",
            "temperature": "openai_compatible_temperature",
            "timeout": "openai_compatible_timeout",
        },
        required_fields=("api_key", "model"),
    ),
]
```

同时从 `config.py` 中删除 `from dataclasses import dataclass`（如果不需保留的），以及 `_derive_field_map` 函数。

- [ ] **步骤 8：更新 `tests/test_services.py` 中引用 `PROVIDER_MAP`/`FIELD_MAP` 的测试**

`test_config_provider_map_has_deepseek` 和 `test_config_field_map_api_key_exists` 直接引用已删除的 `config.PROVIDER_MAP` / `config.FIELD_MAP`，需要适配：

```python
# 原 test_config_provider_map_has_deepseek 改为：
def test_config_provider_index_has_deepseek():
    assert "deepseek" in config.PROVIDER_INDEX
    assert config.PROVIDER_INDEX["deepseek"].settings_cls.__name__ == "DeepSeekSettings"

# 原 test_config_field_map_api_key_exists 改为：
def test_config_deepseek_field_map_api_key():
    spec = config.PROVIDER_INDEX["deepseek"]
    assert "api_key" in spec.field_map
    assert spec.field_map["api_key"] == "deepseek_api_key"
```

另外，`test_resolve_engine_deepseek` 的断言从 `resolve_engine("deepseek") is DeepSeekSettings` 改为：

```python
def test_resolve_engine_deepseek(mock_config, monkeypatch):
    monkeypatch.setattr(config, "MODEL_PROVIDER", "deepseek")
    from pdf2zh_next.config.translate_engine_model import DeepSeekSettings
    from services import resolve_engine
    spec = resolve_engine("deepseek")
    assert isinstance(spec, config.EngineSpec)
    assert spec.settings_cls is DeepSeekSettings
```

`test_resolve_engine_unknown_fallback` 的断言从 `resolve_engine("nonexistent") is OpenAICompatibleSettings` 改为：

```python
def test_resolve_engine_unknown_fallback(mock_config, monkeypatch):
    monkeypatch.setattr(config, "MODEL_PROVIDER", "nonexistent")
    from pdf2zh_next.config.translate_engine_model import OpenAICompatibleSettings
    from services import resolve_engine
    spec = resolve_engine("nonexistent")
    assert isinstance(spec, config.EngineSpec)
    assert spec.settings_cls is OpenAICompatibleSettings
```

`test_build_engine_kwargs_deepseek` 的第一个参数从 `DeepSeekSettings` 类改为 `EngineSpec`：

```python
def test_build_engine_kwargs_deepseek(mock_config, monkeypatch):
    monkeypatch.setattr(config, "MODEL_API_KEY", "sk-test")
    monkeypatch.setattr(config, "MODEL", "deepseek-chat")
    monkeypatch.setattr(config, "MODEL_BASE_URL", "https://api.deepseek.com/v1")
    from services import build_engine_kwargs
    spec = config.PROVIDER_INDEX["deepseek"]
    kwargs = build_engine_kwargs(spec)
    assert kwargs["deepseek_api_key"] == "sk-test"
    assert kwargs["deepseek_model"] == "deepseek-chat"
```

`test_build_engine_kwargs_zhipu_ignores_thinking_mode` 同样改为使用 `EngineSpec`：

```python
def test_build_engine_kwargs_zhipu_ignores_thinking_mode(mock_config, monkeypatch):
    monkeypatch.setattr(config, "MODEL_THINKING_MODE", "enabled")
    from services import build_engine_kwargs
    spec = config.PROVIDER_INDEX["zhipu"]
    kwargs = build_engine_kwargs(spec)
    assert "zhipu_thinking_mode" not in kwargs
```

`test_build_engine_kwargs_missing_api_key_raises` 同样：

```python
def test_build_engine_kwargs_missing_api_key_raises(mock_config, monkeypatch):
    monkeypatch.setattr(config, "MODEL_API_KEY", None)
    monkeypatch.setattr(config, "MODEL", "some-model")
    from services import build_engine_kwargs
    spec = config.PROVIDER_INDEX["deepseek"]
    with pytest.raises(RuntimeError, match="未配置"):
        build_engine_kwargs(spec)
```

- [ ] **步骤 9：运行全部测试和等价回归**

```powershell
python -m pytest tests/test_engine_registry.py tests/test_services.py -v
```

预期：全部 PASS

- [ ] **步骤 10：提交重构**

```bash
git add config.py services.py tests/test_services.py tests/test_engine_registry.py
git commit -m "refactor: migrate to data-driven EngineSpec registry"
```

---

### 任务 4：扩展性验证

**文件：**
- 修改：`tests/test_engine_registry.py`（追加假引擎扩展性测试）

**接口：**
- 消费：`config.EngineSpec`（任务 2 产出）
- 消费：`services.build_engine_kwargs(spec: EngineSpec)`（任务 3 产出）
- 消费：`config.MODEL_API_KEY`, `config.MODEL`

- [ ] **步骤 1：编写扩展性测试**

在 `tests/test_engine_registry.py` 末尾追加：

```python
# tests/test_engine_registry.py 追加内容

from dataclasses import dataclass
from unittest.mock import MagicMock

from services import build_engine_kwargs


def test_fake_engine_extensibility(monkeypatch):
    fake_settings_cls = MagicMock()
    fake_settings_cls.__name__ = "FakeEngineSettings"
    fake_settings_cls.model_fields = {
        "fake_api_key": MagicMock(),
        "fake_model": MagicMock(),
    }

    fake_spec = config.EngineSpec(
        provider="fake",
        settings_cls=fake_settings_cls,
        field_map={
            "api_key": "fake_api_key",
            "model": "fake_model",
        },
        required_fields=("api_key", "model"),
    )

    monkeypatch.setattr(config, "MODEL_API_KEY", "sk-fake-key")
    monkeypatch.setattr(config, "MODEL", "fake-model-v1")

    kwargs = build_engine_kwargs(fake_spec)

    assert kwargs == {
        "fake_api_key": "sk-fake-key",
        "fake_model": "fake-model-v1",
    }


def test_fake_engine_optional_field_warns(monkeypatch, caplog):
    import logging
    caplog.set_level(logging.WARNING)

    fake_settings_cls = MagicMock()
    fake_settings_cls.__name__ = "MinimalEngineSettings"
    fake_settings_cls.model_fields = {
        "minimal_key": MagicMock(),
        "minimal_model": MagicMock(),
    }

    fake_spec = config.EngineSpec(
        provider="minimal",
        settings_cls=fake_settings_cls,
        field_map={
            "api_key": "minimal_key",
            "model": "minimal_model",
            "temperature": "nonexistent_field",
        },
        required_fields=("api_key", "model"),
    )

    monkeypatch.setattr(config, "MODEL_API_KEY", "sk-minimal")
    monkeypatch.setattr(config, "MODEL", "minimal-model")
    monkeypatch.setattr(config, "MODEL_TEMPERATURE", "0.5")

    kwargs = build_engine_kwargs(fake_spec)

    assert kwargs["minimal_key"] == "sk-minimal"
    assert kwargs["minimal_model"] == "minimal-model"
    assert any("不支持字段" in record.message for record in caplog.records)
```

- [ ] **步骤 2：运行扩展性测试**

```powershell
python -m pytest tests/test_engine_registry.py::test_fake_engine_extensibility tests/test_engine_registry.py::test_fake_engine_optional_field_warns -v
```

预期：全部 PASS

- [ ] **步骤 3：提交扩展性测试**

```bash
git add tests/test_engine_registry.py
git commit -m "test: add extensibility verification for EngineSpec"
```

---

### 任务 5：全量回归与 lint

**文件：**
- 无代码变更（仅运行验证命令）

- [ ] **步骤 1：运行全部测试套件**

```powershell
python -m pytest tests/ -v
```

预期：所有测试 PASS，无 FAIL、无 ERROR

- [ ] **步骤 2：运行 ruff 检查**

```powershell
ruff check
```

预期：零错误（All checks passed）

- [ ] **步骤 3（可选）：运行 ruff format 检查**

```powershell
ruff format --check .
```

预期：无差异或按项目约定处理

- [ ] **步骤 4：最终确认**

```powershell
git status
git log --oneline -5
```

预期：工作区干净，最近 4 次提交为本次变更的 4 个任务提交
