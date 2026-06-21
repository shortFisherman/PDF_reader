## Context

`config.py` 当前用两个顶层字典描述引擎：
- `PROVIDER_MAP: dict[str, type]`（provider key → SettingsClass）
- `FIELD_MAP: dict[str, dict[str, str]]`（unified_name → {SettingsClass_name → engine_field_name}），含 8 个子字典（api_key/model/base_url/thinking_mode/reasoning_effort/enable_json_mode/temperature/timeout）

新增引擎需在 `PROVIDER_MAP` 加 1 条 + 在 `FIELD_MAP` 的每个相关子字典加 1 条，散落 9 处。`services.build_engine_kwargs` 遍历硬编码的 8 个 unified_name，与 `FIELD_MAP` 结构强耦合。

约束：`config.toml` 的 `[model]` 字段不变，10 引擎行为字节等价，保守边界。

## Goals / Non-Goals

**Goals:**
- 每个引擎一处声明式定义（provider key、SettingsClass、字段映射）
- 新增引擎只加 1 处声明
- `build_engine_kwargs` 逻辑通用化，不再硬编码 unified_name 列表
- 10 引擎行为等价，现有测试全绿

**Non-Goals:**
- 不改 `config.toml` 字段名
- 不改运行时引擎选择行为
- 不引入插件系统或动态加载（静态注册表即可）

## Decisions

### 决策 1：注册表数据结构

**选择**：定义 `EngineSpec` dataclass + `ENGINE_REGISTRY: list[EngineSpec]`：

```python
@dataclass(frozen=True)
class EngineSpec:
    provider: str                      # "deepseek"
    settings_cls: type                  # DeepSeekSettings
    field_map: dict[str, str]           # unified_name -> engine_field_name（仅含该引擎支持的）
    # 例: {"api_key": "deepseek_api_key", "model": "deepseek_model", "thinking_mode": "deepseek_thinking_mode", ...}
```

`provider` → `EngineSpec` 的查找索引由注册表派生。每个引擎的字段映射集中在其 `EngineSpec` 内，不再分散到 8 个子字典。

**备选**：
- (a) 字典嵌套 `{"deepseek": {"cls": ..., "fields": {...}}}`——dataclass 有类型提示更安全
- (b) 装饰器注册 `@register_engine("deepseek", ...)`——动态注册增加隐式顺序，静态列表更显式

**理由**：dataclass 冻结实例 + 显式列表，类型安全、易读、新增引擎一处声明。

### 决策 2：build_engine_kwargs 通用化

**选择**：`build_engine_kwargs(spec: EngineSpec) -> dict` 遍历 `spec.field_map`，对每个 `unified_name` 从 `config` 读取 `MODEL_{unified_name.upper()}`（model 特例），值非空则写入 `engine_field`。缺失必填（api_key/model）抛错，可选字段忽略并警告。

**理由**：逻辑由 `EngineSpec.field_map` 驱动，不再硬编码 8 个字段名。

### 决策 3：10 引擎等价迁移

**选择**：从现有 `PROVIDER_MAP` + `FIELD_MAP` 机械推导每个引擎的 `EngineSpec.field_map`（只含该引擎在 FIELD_MAP 各子字典中实际出现的条目），逐引擎对照现有行为编写等价测试。

**理由**：避免行为漂移；现有 `test_services.py` 的引擎配置测试作为回归基线。

## Risks / Trade-offs

- [迁移遗漏某引擎某字段] → 逐引擎等价测试覆盖 10 引擎 × 8 字段矩阵
- [dataclass 引入轻微 import 成本] → 可忽略
- [注册表顺序影响 provider 查找] → 用 dict 索引而非列表遍历查找，顺序无关
