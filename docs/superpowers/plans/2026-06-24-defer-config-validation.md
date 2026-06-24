---
change: defer-config-validation
design-doc: docs/superpowers/specs/2026-06-24-defer-config-validation-design.md
base-ref: e34a27dd34922e1a85484d76ee7ee44f9d42c8ee
---

# defer-config-validation 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** �?`config.py` 的导入期校验推迟�?`resolve_engine` 首次消费时，�?`import config` 在无 `config.toml` 环境下不抛错�?
**Architecture:** `config.py` 顶层加载容错（文件缺�?�?`CONFIG={}`），所有字典访问改�?`.get(key, default)` �?KeyError，原 `raise ValueError` 逻辑移入 `_validate_required_config()`，由 `engine_resolver.resolve_engine` 在解析引擎前调用。依赖方向：`config._validate_required_config()` �?`engine_resolver.resolve_engine()` �?`translation_settings.build_settings()`�?
**Tech Stack:** Python 3.12+, tomllib, pytest, ruff

## Global Constraints

- `config.toml` 不存在时 `import config` 不抛错，`CONFIG` 退化为 `{}`
- 必需配置（MODEL、MODEL_API_KEY）的校验推迟�?`resolve_engine` 首次消费�?- 已正确配置的环境运行时行为完全不�?- 测试套件可在�?`config.toml` 的全新克隆中运行
- 不改 `config.toml` �?schema，不引入配置对象、懒加载 property、依赖注入等架构改�?- `ruff check .` �?`pytest -q` 必须全过

---

### Task 1: config.py 容错加载 + 防御性访�?
**Files:**
- Modify: `config.py:19-21`（CONFIG 加载�?- Modify: `config.py:23-27`（model_cfg 访问�?- Modify: `config.py:171-175`（DPI / CACHE_DIR / lang 访问�?
**Interfaces:**
- Consumes: nothing from prior tasks（第一个任务）
- Produces: `CONFIG: dict`（缺失时退化为 `{}`）；`MODEL: str`（默�?`""`）；`MODEL_API_KEY: str`（默�?`""`）；`MODEL_PROVIDER: str`（默�?`"openai_compatible"`）；`DPI: int`（默�?`200`）；`CACHE_DIR: Path`（默�?`Path("cache")`）；`TRANSLATION_LANG_IN: str`（默�?`"en"`）；`TRANSLATION_LANG_OUT: str`（默�?`"zh"`�?
- [x] **Step 1: 修改 CONFIG 加载逻辑 �?config.toml 不存在时退化为�?dict**

修改 `config.py:19-21`，当前代码：
```python
CONFIG_PATH = Path(__file__).parent / "config.toml"
with open(CONFIG_PATH, "rb") as f:
    CONFIG = tomllib.load(f)
```

替换为：
```python
CONFIG_PATH = Path(__file__).parent / "config.toml"
try:
    with open(CONFIG_PATH, "rb") as f:
        CONFIG = tomllib.load(f)
except FileNotFoundError:
    CONFIG = {}
```

- [x] **Step 2: 修改 model_cfg 及派生属�?�?所有硬访问改为 .get()**

修改 `config.py:23-27`，当前代码：
```python
model_cfg = CONFIG["model"]
MODEL_PROVIDER = model_cfg["provider"]
_raw_api_key = os.environ.get("MODEL_API_KEY", model_cfg.get("api_key", ""))
MODEL_API_KEY = (_raw_api_key or "").strip()
MODEL = model_cfg["model"]
```

替换为：
```python
model_cfg = CONFIG.get("model", {})
MODEL_PROVIDER = model_cfg.get("provider", "openai_compatible")
_raw_api_key = os.environ.get("MODEL_API_KEY", model_cfg.get("api_key", ""))
MODEL_API_KEY = (_raw_api_key or "").strip()
MODEL = model_cfg.get("model", "")
```

- [x] **Step 3: 修改 DPI / CACHE_DIR / lang 访问�?.get()**

修改 `config.py:171-175`，当前代码：
```python
DPI = CONFIG["pdf_reader"]["dpi"]
CACHE_DIR = Path(CONFIG["pdf_reader"]["cache_dir"]).resolve()
GLOSSARY_PATH = Path(__file__).parent / "docs" / "glossary.csv"
TRANSLATION_LANG_IN = CONFIG["translation"]["lang_in"]
TRANSLATION_LANG_OUT = CONFIG["translation"]["lang_out"]
```

替换为：
```python
DPI = CONFIG.get("pdf_reader", {}).get("dpi", 200)
CACHE_DIR = Path(CONFIG.get("pdf_reader", {}).get("cache_dir", "cache")).resolve()
GLOSSARY_PATH = Path(__file__).parent / "docs" / "glossary.csv"
TRANSLATION_LANG_IN = CONFIG.get("translation", {}).get("lang_in", "en")
TRANSLATION_LANG_OUT = CONFIG.get("translation", {}).get("lang_out", "zh")
```

- [x] **Step 4: 运行现有测试验证不引入回�?*

```powershell
pytest -q
```

Expected: 107+ tests pass（因移除导入期校验，�?`config.toml` 环境的测试不再因导入失败�?crash）�?
- [x] **Step 5: Commit**

```powershell
git add config.py; git commit -m "feat: guarded config access �?no crash when config.toml is missing"
```

---

### Task 2: 删除导入期校�?+ 新增延迟校验函数

**Files:**
- Modify: `config.py:36-39`（删除旧�?raise�?- Modify: `config.py`（在 `_resolve_debug` 之前新增 `_validate_required_config`�?
**Interfaces:**
- Consumes: `MODEL` (from Task 1), `MODEL_API_KEY` (from Task 1)
- Produces: `config._validate_required_config() -> None`（检查不通过�?`raise ValueError`�?
- [x] **Step 1: 删除 config.py:36-39 的导入期 raise 校验**

原代码（删除�?4 行）�?```python
if not MODEL_API_KEY or MODEL_API_KEY.startswith("sk-your-api-key"):
    raise ValueError("请设�?model.api_key 或环境变�?MODEL_API_KEY")
if not MODEL:
    raise ValueError("请设�?model.model")
```

- [x] **Step 2: 新增 `_validate_required_config()` 函数**

�?`config.py` �?`_resolve_debug` 函数定义之前（第 177 行之前）插入�?```python
def _validate_required_config() -> None:
    if not MODEL:
        raise ValueError("请设�?model.model")
    if not MODEL_API_KEY or MODEL_API_KEY.startswith("sk-your-api-key"):
        raise ValueError("请设�?model.api_key 或环境变�?MODEL_API_KEY")
```

- [x] **Step 3: 运行 ruff 检�?*

```powershell
ruff check .
```

Expected: All checks pass.

- [x] **Step 4: Commit**

```powershell
git add config.py; git commit -m "feat: defer config validation to _validate_required_config()"
```

---

### Task 3: engine_resolver.py 接入延迟校验

**Files:**
- Modify: `engine_resolver.py:19-25`（`resolve_engine` 函数入口�?
**Interfaces:**
- Consumes: `config._validate_required_config` (from Task 2)
- Produces: `resolve_engine` 在解析引擎前校验必需配置，不通过则抛 `ValueError`

- [x] **Step 1: �?`resolve_engine` 入口添加校验调用**

修改 `engine_resolver.py:19-25`，当前代码：
```python
def resolve_engine(provider: str) -> config.EngineSpec:  # noqa: ANN201
    spec = config.PROVIDER_INDEX.get(provider)
    if spec is None:
        logger.info("Provider '%s' not found, falling back to OpenAI Compatible", provider)
        spec = config.PROVIDER_INDEX["openai_compatible"]
    logger.info("Using engine: %s (%s)", spec.settings_cls.__name__, config.MODEL)
    return spec
```

替换为：
```python
def resolve_engine(provider: str) -> config.EngineSpec:  # noqa: ANN201
    config._validate_required_config()
    spec = config.PROVIDER_INDEX.get(provider)
    if spec is None:
        logger.info("Provider '%s' not found, falling back to OpenAI Compatible", provider)
        spec = config.PROVIDER_INDEX["openai_compatible"]
    logger.info("Using engine: %s (%s)", spec.settings_cls.__name__, config.MODEL)
    return spec
```

- [x] **Step 2: 运行 ruff 检�?*

```powershell
ruff check .
```

Expected: All checks pass.

- [x] **Step 3: Commit**

```powershell
git add engine_resolver.py; git commit -m "feat: call _validate_required_config() at resolve_engine entry"
```

---

### Task 4: 测试 �?调整 conftest + 新增延迟校验测试

**Files:**
- Modify: `tests/conftest.py:45-55`（`mock_config` fixture�?- Create: `tests/test_config_deferred.py`

**Interfaces:**
- Consumes: `config._validate_required_config` (from Task 2), `engine_resolver.resolve_engine` (from Task 3)
- Produces: `mock_config` fixture 适配无文件环境；`test_config_deferred.py` 提供 4 个延迟校验测�?
- [x] **Step 1: 增强 `mock_config` fixture �?确保�?config.toml 依赖**

当前 `tests/conftest.py:44-55`�?```python
@pytest.fixture
def mock_config(monkeypatch):
    monkeypatch.setattr(config, "MODEL_PROVIDER", "deepseek")
    monkeypatch.setattr(config, "MODEL_API_KEY", "sk-test-key")
    monkeypatch.setattr(config, "MODEL", "deepseek-v4-flash")
    monkeypatch.setattr(config, "MODEL_BASE_URL", None)
    monkeypatch.setattr(config, "MODEL_THINKING_MODE", None)
    monkeypatch.setattr(config, "MODEL_REASONING_EFFORT", None)
    monkeypatch.setattr(config, "MODEL_ENABLE_JSON_MODE", None)
    monkeypatch.setattr(config, "MODEL_TEMPERATURE", None)
    monkeypatch.setattr(config, "MODEL_TIMEOUT", None)
    yield
```

替换为（增加 DPI / CACHE_DIR 等不再由 config.toml 提供的属�?patch，确�?fixture 自包含）�?```python
@pytest.fixture
def mock_config(monkeypatch):
    monkeypatch.setattr(config, "MODEL_PROVIDER", "deepseek")
    monkeypatch.setattr(config, "MODEL_API_KEY", "sk-test-key")
    monkeypatch.setattr(config, "MODEL", "deepseek-v4-flash")
    monkeypatch.setattr(config, "MODEL_BASE_URL", None)
    monkeypatch.setattr(config, "MODEL_THINKING_MODE", None)
    monkeypatch.setattr(config, "MODEL_REASONING_EFFORT", None)
    monkeypatch.setattr(config, "MODEL_ENABLE_JSON_MODE", None)
    monkeypatch.setattr(config, "MODEL_TEMPERATURE", None)
    monkeypatch.setattr(config, "MODEL_TIMEOUT", None)
    monkeypatch.setattr(config, "DPI", 200)
    monkeypatch.setattr(config, "CACHE_DIR", Path("cache"))
    monkeypatch.setattr(config, "TRANSLATION_LANG_IN", "en")
    monkeypatch.setattr(config, "TRANSLATION_LANG_OUT", "zh")
    yield
```

需要同时确�?`conftest.py` 顶部�?import `Path`（当前已�?`from pathlib import Path`）�?
- [x] **Step 2: 创建测试文件 �?测试 1：无 config.toml �?import config 成功�?CONFIG 为空**

创建 `tests/test_config_deferred.py`�?```python
import sys
from unittest.mock import patch


def test_import_config_without_config_toml():
    with patch.dict(sys.modules):
        if "config" in sys.modules:
            del sys.modules["config"]
        with patch("builtins.open", side_effect=FileNotFoundError):
            import config

            assert config.CONFIG == {}
            assert config.MODEL == ""
            assert config.MODEL_API_KEY == ""
            assert config.MODEL_PROVIDER == "openai_compatible"
```

- [x] **Step 3: 运行测试 1 确认通过**

```powershell
pytest tests/test_config_deferred.py::test_import_config_without_config_toml -v
```

Expected: PASS.

- [x] **Step 4: 测试 2 �?MODEL 缺失�?`resolve_engine` �?"请设�?model.model"**

追加�?`tests/test_config_deferred.py`�?```python
import pytest

import config
from engine_resolver import resolve_engine


def test_resolve_engine_raises_when_model_missing(monkeypatch):
    monkeypatch.setattr(config, "MODEL_API_KEY", "sk-test-key")
    monkeypatch.setattr(config, "MODEL", "")

    with pytest.raises(ValueError, match="请设�?model\\.model"):
        resolve_engine("deepseek")
```

- [x] **Step 5: 运行测试 2 确认通过**

```powershell
pytest tests/test_config_deferred.py::test_resolve_engine_raises_when_model_missing -v
```

Expected: PASS.

- [x] **Step 6: 测试 3 �?MODEL_API_KEY 缺失/哨兵�?`resolve_engine` �?"请设�?model.api_key 或环境变�?MODEL_API_KEY"**

追加�?`tests/test_config_deferred.py`�?```python
@pytest.mark.parametrize("key", ["", "sk-your-api-key"])
def test_resolve_engine_raises_when_api_key_missing_or_sentinel(monkeypatch, key):
    monkeypatch.setattr(config, "MODEL_API_KEY", key)
    monkeypatch.setattr(config, "MODEL", "deepseek-v4-flash")

    with pytest.raises(ValueError, match="请设�?model\\.api_key 或环境变�?MODEL_API_KEY"):
        resolve_engine("deepseek")
```

- [x] **Step 7: 运行测试 3 确认通过**

```powershell
pytest tests/test_config_deferred.py::test_resolve_engine_raises_when_api_key_missing_or_sentinel -v
```

Expected: PASS.

- [x] **Step 8: 测试 4 �?已正确配置时行为不变**

追加�?`tests/test_config_deferred.py`�?```python
from pdf2zh_next.config.translate_engine_model import DeepSeekSettings


def test_resolve_engine_with_valid_config(monkeypatch):
    monkeypatch.setattr(config, "MODEL_API_KEY", "sk-valid-key")
    monkeypatch.setattr(config, "MODEL", "deepseek-v4-flash")

    spec = resolve_engine("deepseek")

    assert isinstance(spec, config.EngineSpec)
    assert spec.settings_cls is DeepSeekSettings
    assert spec.provider == "deepseek"
```

- [x] **Step 9: 运行测试 4 确认通过**

```powershell
pytest tests/test_config_deferred.py::test_resolve_engine_with_valid_config -v
```

Expected: PASS.

- [x] **Step 10: 运行测试 5 �?MODEL_API_KEY 从环境变量读取时 `_validate_required_config` 不抛�?*

追加�?`tests/test_config_deferred.py`�?```python
def test_validate_passes_when_api_key_from_env(monkeypatch):
    monkeypatch.setattr(config, "MODEL_API_KEY", "sk-from-env")
    monkeypatch.setattr(config, "MODEL", "some-model")

    config._validate_required_config()
```

- [x] **Step 11: 运行测试 5 确认通过**

```powershell
pytest tests/test_config_deferred.py::test_validate_passes_when_api_key_from_env -v
```

Expected: PASS.

- [x] **Step 12: 运行全部新测�?*

```powershell
pytest tests/test_config_deferred.py -v
```

Expected: 5 passed.

- [x] **Step 13: Commit**

```powershell
git add tests/conftest.py tests/test_config_deferred.py; git commit -m "test: add deferred config validation tests"
```

---

### Task 5: 回归测试 �?现有测试全过

**Files:**
- Test: `tests/test_services.py`, `tests/test_engine_registry.py`, `tests/test_translation_orchestrator.py`, `tests/test_debug_trace.py`（可能是依赖 config 导入的全部）

**Interfaces:**
- Consumes: 所有前�?Tasks 的产�?
- [x] **Step 1: 运行完整测试套件**

```powershell
pytest -q
```

Expected: 112+ tests pass（原�?107 + 新增 5），0 failures�?
- [x] **Step 2: 运行 ruff 全面检�?*

```powershell
ruff check .
```

Expected: All checks pass, 0 errors.

- [x] **Step 3: 若有失败，根据失败信息定位修复后重新运行 Step 1-2**

- [x] **Step 4: 手动验证 �?�?config.toml 环境下翻译链路正�?*

```powershell
python -c "from translation_settings import build_settings; settings = build_settings('dummy.pdf'); print(type(settings.translate_engine_settings).__name__)"
```

Expected: 打印对应 engine settings 类名，不抛错�?
- [x] **Step 5: 手动验证 �?�?config.toml 环境�?import 不抛�?*

临时重命�?`config.toml`�?```powershell
Rename-Item -LiteralPath "config.toml" -NewName "config.toml.bak"
python -c "import config; print('CONFIG:', config.CONFIG); print('MODEL:', config.MODEL)"
Rename-Item -LiteralPath "config.toml.bak" -NewName "config.toml"
```

Expected: `CONFIG: {}`, `MODEL: `(空字符串)，不抛错�?
- [x] **Step 6: 确认变更完成�?commit**

```powershell
git status
git log --oneline -5
```

Expected: 3 �?commit（config 改造、engine_resolver 接入、测试），无未暂存变更�?
---

### 自审清单

1. **Spec 覆盖**�?   - [x] Guarded Config Access（Task 1�? �?`.get()` 替换）✓
   - [x] Deferred Validation（Task 2：`_validate_required_config` + Task 3：`resolve_engine` 接入）✓
   - [x] Backward Compatibility（Task 5 回归测试 + 手动验证）✓
   - [x] �?config.toml 导入成功（Task 4 测试 1、Task 5 手动验证）✓
   - [x] MODEL 缺失�?resolve_engine 抛错（Task 4 测试 2）✓
   - [x] MODEL_API_KEY 缺失/哨兵�?resolve_engine 抛错（Task 4 测试 3）✓
   - [x] 已正确配置行为不变（Task 4 测试 4）✓
   - [x] conftest.mock_config 调整（Task 4 Step 1）✓
   - [x] pytest -q + ruff check . 全过（Task 5 Step 1-2）✓

2. **占位符扫�?*：无 TBD、TODO�?implement later"�?add appropriate error handling" 等红字模式。所有步骤均包含实际代码�?
3. **类型一致�?*�?   - `_validate_required_config() -> None`：Task 2 定义、Task 3 调用、Task 4 测试 �?签名一�?�?   - `resolve_engine(provider: str) -> config.EngineSpec`：Task 3 修改、Task 4 测试 �?签名一�?�?   - `.get()` 默认值与 Design Doc §4.1 表格一�?�?   - `mock_config` fixture 新增�?monkeypatch 属性名�?Task 1 产物一�?�?