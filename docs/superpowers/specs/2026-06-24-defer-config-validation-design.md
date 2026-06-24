---
comet_change: defer-config-validation
role: technical-design
canonical_spec: openspec
archived-with: 2026-06-24-defer-config-validation
status: final
---

# defer-config-validation

## 1. Context

`config.py` 在模块导入期（顶层代码）通过 `open(CONFIG_PATH)` 加载 `config.toml`，然后直接 `raise ValueError` 校验 `MODEL_API_KEY` 和 `MODEL`。`config.toml` 已被 `.gitignore` 忽略，全新克隆中任何 `import config` 都会因缺失文件或未配置键而崩溃，使得整个测试套件和 CI 无法运行。当前配置消费点集中在 `engine_resolver.resolve_engine`（由 `translation_settings.build_settings` 调用），这是触发模型配置校验的唯一业务入口。

## 2. Goals

- `import config` 在任意环境（无 `config.toml`、无 API key）下不抛错，`CONFIG` 退化为空 dict
- 必需配置（MODEL、MODEL_API_KEY）的校验推迟到 `resolve_engine` 首次消费时
- 已正确配置的环境运行时行为完全不变
- 测试套件可在无 `config.toml` 的全新克隆中运行

## 3. Non-Goals

- 不改 `config.toml` 的 schema
- 不引入配置对象、懒加载 property、依赖注入等架构改造

## 4. Design

### 4.1 Guarded Config Access

将 `config.py` 中所有 `CONFIG[key]` 字典硬访问改为 `CONFIG.get(key, defaults)`，使任意环境导入都不抛 KeyError：

| 原写法 | 新写法 |
|--------|--------|
| `CONFIG["model"]` | `CONFIG.get("model", {})` |
| `model_cfg["provider"]` | `model_cfg.get("provider", "openai_compatible")` |
| `model_cfg["model"]` | `model_cfg.get("model", "")` |
| `CONFIG["pdf_reader"]["dpi"]` | `CONFIG.get("pdf_reader", {}).get("dpi", 200)` |
| `CONFIG["pdf_reader"]["cache_dir"]` | `CONFIG.get("pdf_reader", {}).get("cache_dir", "cache")` |
| `CONFIG["translation"]["lang_in"]` | `CONFIG.get("translation", {}).get("lang_in", "en")` |
| `CONFIG["translation"]["lang_out"]` | `CONFIG.get("translation", {}).get("lang_out", "zh")` |

`model_cfg["api_key"]` 已使用 `.get("api_key", "")`（第 25 行），无需改动。`_resolve_debug()` 已在第 178-179 行使用 `.get()`，无需改动。

### 4.2 Deferred Validation

删除 `config.py:36-39` 的导入期校验，新增延迟校验函数：

```python
def _validate_required_config() -> None:
    if not MODEL:
        raise ValueError("请设置 model.model")
    if not MODEL_API_KEY or MODEL_API_KEY.startswith("sk-your-api-key"):
        raise ValueError("请设置 model.api_key 或环境变量 MODEL_API_KEY")
```

**调用点**：`engine_resolver.resolve_engine` 在解析引擎前（第 21 行前）调用 `_validate_required_config()`。`translation_settings.build_settings` 第一步即调用 `resolve_engine`，自动覆盖全部翻译路径，无需重复触发。

### 4.3 Rationale

- **为什么在 `resolve_engine` 校验而非每个消费点**：`resolve_engine` 是翻译链路唯一入口；渲染/页面接口不依赖 MODEL，不应被未配置阻断
- **为什么不用 `@cached_property`**：引入惰性求值模型会增加访问复杂度，与本变更"最小改动"原则冲突
- **为什么不保留导入期 warn**：warn 不能代替校验，且 CI 日志中 warn 易被忽略

## 5. Implementation

### 5.1 Files Changed

| 文件 | 改动 |
|------|------|
| `config.py` | 10 处 `dict[key]` → `dict.get`；删除 2 行 `raise`；新增 `_validate_required_config` |
| `engine_resolver.py` | `resolve_engine` 入口加一行调用 `_validate_required_config()` |
| `tests/conftest.py` | 调整 `mock_config` fixture 确保在无 config.toml 下 monkeypatch 生效 |
| `tests/` | 新增 test_config_deferred 等 4 个测试 |

### 5.2 Backward Compatibility

- 有 `config.toml` 的环境：`.get(key, default)` 在 key 存在时返回原值，行为完全不变
- 无 `config.toml` 的环境（全新克隆、CI）：导入成功，首次翻译时在 `resolve_engine` 抛原文案 ValueError

## 6. Risks & Mitigations

| 风险 | 缓解 |
|------|------|
| 配置缺失错误晚于导入期暴露，可能被误以为"导入成功=配置正确" | 在 `resolve_engine` 保留原中文报错文案；CI 添加断言覆盖缺失→消费报错 |
| `.get` 默认值在无配置下不符合预期 | lang_in/lang_out 等的默认值仅为"不抛错"兜底；翻译前 MODEL 校验即报错，不会真正使用默认值 |

## 7. Testing

- 新增测试：无 `config.toml` 时 `import config` 不抛错
- 新增测试：MODEL 缺失时 `resolve_engine` 抛正确 ValueError
- 新增测试：MODEL_API_KEY 缺失/哨兵时 `resolve_engine` 抛正确 ValueError
- 新增测试：已正确配置时行为不变
- 调整 `conftest.mock_config` 以支持无文件环境
- 确认 `pytest -q` 全过、`ruff check .` 全过
