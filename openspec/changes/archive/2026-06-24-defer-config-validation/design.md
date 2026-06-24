# Design: defer-config-validation

## Context

`config.py` 在模块顶层执行 `open(CONFIG_PATH)` 加载 `config.toml`，并在 `config.py:36-39` 直接 `raise ValueError` 校验 `MODEL_API_KEY`/`MODEL`。`config.toml` 已被 `.gitignore` 忽略，因此全新克隆中 `import config` 必然失败。这阻断了 CI 与无配置环境下的测试运行。当前服务的消费点集中在 `engine_resolver.resolve_engine` 与 `translation_settings.build_settings`，这两处是触发翻译的唯一业务入口。

## Goals / Non-Goals

**Goals:**
- `import config` 在任意环境（含无 `config.toml` / 无 API key）下都不抛错。
- 配置缺失错误在「配置首次被业务消费」（解析引擎/构建翻译参数）时以人类可读的中文报错抛出。
- 已正确配置环境的运行时行为与原先完全一致（同样的报错文案、同样的触发语义）。
- 测试套件可在无 `config.toml` 的全新克隆中运行（为本变更及后续 CI 变更铺路）。

**Non-Goals:**
- 不改 `config.toml` 的 schema 或加载机制（仍是模块导入期加载，缺失文件时 `CONFIG` 取空 dict 容错，不抛错）。
- 不引入配置对象/依赖注入等架构改造。
- 不做运行时热重载或多环境 profile。
- 不处理 `requirements` / 虚拟环境的可移植性（属 CI 变更范围）。

## Decisions

### 决策 1：文件缺失走容错而非抛错
`config.py:20` 的 `open(CONFIG_PATH)` 改为：文件不存在时 `CONFIG = {}`，后续以 `dict.get` 安全取值（已是第 23-34 行的模式）。这样导入不依赖 `config.toml` 存在。
- 替代方案：在缺失时仍抛错但仅警告 → 否决，因 CI 全新克隆需导入成功。

### 决策 2：API key/model 校验延迟到消费点
删除导入期 `config.py:36-39` 的 `raise`。新增一个内部校验函数 `_validate_required()`，由 `engine_resolver.resolve_engine`（消费 `MODEL`/`MODEL_API_KEY` 的首个业务入口）在解析前调用，缺失时抛与原先文案一致的 `ValueError`。
- 替代方案：在每个 property getter 里校验 → 否决，过度分散且重复触发。
- 替代方案：用 `@functools.cached_property` 惰性求值 → 引入更复杂的访问模型，超出本变更 scope。

### 决策 3：校验触发点选择 `resolve_engine`
`translation_settings.build_settings` 第一步即调用 `resolve_engine`，故只在 `resolve_engine` 入口校验即可覆盖全部翻译路径，单一入口、改动最小。`pdf_renderer`/`page` 渲染路径不依赖 API key，无需校验，符合「按需校验」语义。

### 决策 4：测试 fixture 调整
`tests/conftest.py` 的 `mock_config` 已 monkeypatch 各 `MODEL_*` 属性——保持不变，但需确保其不再依赖「导入期校验」的存在。新增一个测试覆盖「无 config.toml 时 import 成功、消费时报错」的场景。新增测试覆盖「已配置时行为不变」。

## Risks / Trade-offs

- **[风险] 配置缺失错误晚于导入期暴露** → 缓解：在 `resolve_engine` 等关键消费点显式校验并保留原中文文案；CI 与测试新增断言覆盖「缺失→消费期报错」。
- **[风险] 外部脚本依赖导入即校验来提前失败** → 缓解：属本变更已知 BREAKING 行为，已在 proposal 标注；项目内无此类外部脚本。
- **[风险] 容错 `CONFIG = {}` 掩盖 `config.toml` 笔误** → 缓解：`DPI`/`CACHE_DIR` 等整型/路径键在缺失时应有明确默认或显式报错，本变更在 design 阶段确认 `DPI`/`CACHE_DIR` 缺失的处理（维持现状或补 KeyError 报错），写入 tasks。