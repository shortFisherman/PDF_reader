# Comet Design Handoff

- Change: cumulative-glossary-across-pages
- Phase: design
- Mode: compact
- Context hash: 9b4a36e5964258ba27300eaff2c7262667f125517f4cd5602a1ec74854b49a4e

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/cumulative-glossary-across-pages/proposal.md

- Source: openspec/changes/cumulative-glossary-across-pages/proposal.md
- Lines: 1-25
- SHA256: 5787554eb1f2c490603be0ec8d7c1f72ef8f503099fe3cbf03519df4010112a7

```md
## Why

当前 PDF 阅读器是「看一页翻译一页」的交互模式。每次翻译单独一页时，pdf2zh-next 的术语提取阶段会将该页发现的专业术语自动翻译并生成术语表，但翻译完成后术语表随临时目录一起被清理，下一页面翻译时 LLM 无法看到前面已提取的术语。对于阅读专业教材的场景，这导致同一术语在不同页面可能被译成不同的中文，破坏译名一致性。

## What Changes

- 翻译前：检查是否已有该 PDF 的累积术语表，若有则通过 `glossaries` 参数传递给翻译管道
- 翻译后：从翻译结果中提取自动生成的术语表，与已有的累积术语表合并去重后持久化
- 以 PDF 的 SHA256 哈希作为缓存键，不同教材的术语表互不干扰

## Capabilities

### New Capabilities

- `cumulative-glossary-persistence`: 每页翻译提取的术语自动合并到按 PDF 隔离的持久化累积术语表中，后续页面翻译时自动加载

### Modified Capabilities

无。此变更仅影响术语表的生命周期管理，不改变已有 spec 级行为。

## Impact

- `routes.py`：翻译完成后合并术语表，翻译前加载累积术语表
- `services.py`：`build_settings` 支持累积术语表路径
- `state.py`：暴露 PDF 缓存子目录路径供术语表存取
```

## openspec/changes/cumulative-glossary-across-pages/design.md

- Source: openspec/changes/cumulative-glossary-across-pages/design.md
- Lines: 1-67
- SHA256: 293476f18ca446c1c5ec13071eeebb6ad2fc080dd5008a56dfe04637ac61bd60

```md
## Context

当前 `translate_page()` 中每页翻译流程：

1. `build_settings()` 创建 `SettingsModel`，其中 `glossaries` 仅指向静态的 `GLOSSARY_PATH`
2. `do_translate_async_stream()` 运行完整流水线（术语提取 → 正文翻译 → PDF 生成）
3. 翻译完成后，`translate_result.auto_extracted_glossary_path` 指向本页术语表 CSV
4. `finally` 块中 `shutil.rmtree(output_dir)` 清理所有产物

PDF 已在 `AppState.open_pdf()` 中按 SHA256 创建缓存子目录 `CACHE_DIR/<hash>/`，该目录在对话期间持久存在。

## Goals / Non-Goals

**Goals:**
- 同一 PDF 多次翻译时术语表跨页面累积
- 不同 PDF 使用独立术语表（按 SHA256 哈希隔离）
- 与现有人工术语表（`GLOSSARY_PATH`）兼容共存

**Non-Goals:**
- 不修改 pdf2zh-next / babeldoc 源码
- 不改变 UI 交互
- 不提供术语表编辑功能

## Decisions

### 决策 1：术语表存储位置

**选择**：`CACHE_DIR/<pdf_hash>/cumulative_glossary.csv`

**理由**：`AppState.open_pdf()` 已创建此目录用于 `right.pdf`，零额外复杂度。不同教材天然隔离。

**备选**：新建独立 `glossary_cache/` 目录 → 引入额外目录管理逻辑，无必要。

### 决策 2：合并策略

**选择**：以 `source` 列为键，同一 source 出现多次时用出现次数最多的 `target`（多数投票）。

**理由**：与 pdf2zh-next 内部 `finalize_auto_extracted_glossary()` 的投票逻辑一致。去重后的 CSV 文件体积可控（教育类教材约 50-200 术语/章）。

**备选**：按时间戳覆盖 → 新提取的可能不如之前的准确，投票更稳健。

### 决策 3：`glossaries` 参数传递方式

**选择**：逗号拼接多路径，如 `"docs/glossary.csv,cache/<hash>/cumulative_glossary.csv"`

**理由**：`pdf2zh_next` 的 `_get_glossaries()` 已支持逗号分隔多路径 (`glossaries.split(",")`)，每个独立加载为 `Glossary` 对象。管道内部自动合并到 `shared_context.user_glossaries` 并注入术语提取和正文翻译两个阶段的 prompt。

**备选**：先合并为单个文件再传 → 多一次文件 I/O，且丢失「哪个术语来自哪个来源」的分组信息。

### 决策 4：翻译后合并时机

**选择**：在 `finally` 块清理 `output_dir` 之前，从 `translate_result.auto_extracted_glossary_path` 读取并合并。

**理由**：`auto_extracted_glossary_path` 指向 `output_dir` 内的 CSV 文件，清理前必须拷贝出来。读取 → 合并到累积表 → 写回 → 再清理原目录。

### 决策 5：`build_settings` 接口变更

**选择**：新增可选参数 `glossary_paths: list[str] | None`，替代原来的 hard-coded 单一路径逻辑。

**理由**：清晰表达「可能有多个术语表来源」的语义，向后兼容（不传时行为不变）。

## Risks / Trade-offs

- [风险] 累积术语表随时间增大 → 每次 hyperscan 扫描可能变慢
  - 缓解：教材级术语总量通常 <500 条，hyperscan 可高效处理数万条
- [风险] 术语表 CSV 并发写入 → 文件损坏
  - 缓解：Flask 默认单线程，不存在并发。如未来改为异步，需加文件锁
```

## openspec/changes/cumulative-glossary-across-pages/tasks.md

- Source: openspec/changes/cumulative-glossary-across-pages/tasks.md
- Lines: 1-18
- SHA256: f39909a58b628aa5b7bba56cbaea28e63ec5eae2b49721d921f72d5750b2e5b1

```md
## 1. 累积术语表管理

- [ ] 1.1 `state.py`：在 `AppState` 中新增属性 `glossary_cache_path`，返回 `CACHE_DIR/<pdf_hash>/`，打开 PDF 时计算
- [ ] 1.2 新增 `glossary_merger.py`（或在 `services.py` 中）：实现合并函数，读取两个 CSV 按 `source` 列合并去重，多数投票选 `target`
- [ ] 1.3 `services.py`：`build_settings` 新增可选参数 `glossary_paths: list[str] | None`，逗号拼接后传给 `TranslationSettings.globals`

## 2. 翻译流程集成

- [ ] 2.1 `routes.py` `translate_page()`：翻译前根据 `state.pdf_hash` 检查是否存在 `cumulative_glossary.csv`，存在则加入 `glossary_paths`
- [ ] 2.2 `routes.py` `translate_page()`：翻译完成后，从 `translate_result.auto_extracted_glossary_path` 读取并合并到累计术语表（在 `finally` 清理前执行）
- [ ] 2.3 合并时处理边界：累积表为空（首次）、auto_extracted 为空（无可提取术语）等

## 3. 验证

- [ ] 3.1 手动测试：翻译同一 PDF 第一页 → 确认 `cumulative_glossary.csv` 已创建
- [ ] 3.2 手动测试：翻译同一 PDF 第二页 → 确认累积术语表被加载且新增术语已合并
- [ ] 3.3 手动测试：打开另一 PDF 翻译 → 确认使用独立术语表
- [ ] 3.4 运行现有测试确保无回归：`pytest tests/`
```

## openspec/changes/cumulative-glossary-across-pages/specs/cumulative-glossary-persistence/spec.md

- Source: openspec/changes/cumulative-glossary-across-pages/specs/cumulative-glossary-persistence/spec.md
- Lines: 1-41
- SHA256: 827455a9ee182948c6ef1e1f4970d101fdd7a49df85b74c4c759f3b5d6d6cc42

```md
## ADDED Requirements

### Requirement: 累积术语表加载

翻译某页前，如果该 PDF 已有累积术语表文件，系统 SHALL 将其路径与用户静态术语表路径一并传递给翻译管道。

#### Scenario: 已有累积术语表
- **WHEN** 用户翻译某页，且 `CACHE_DIR/<pdf_hash>/cumulative_glossary.csv` 已存在
- **THEN** `build_settings` 的 `glossaries` 参数包含该路径，翻译管道加载并注入术语提取和正文翻译 prompt

#### Scenario: 无累积术语表（首次翻译）
- **WHEN** 用户首次翻译该 PDF 的某页，且 `CACHE_DIR/<pdf_hash>/cumulative_glossary.csv` 不存在
- **THEN** 行为与当前一致，术语提取正常执行，不加载额外术语表

#### Scenario: 切换教材
- **WHEN** 用户打开另一本 PDF 并翻译
- **THEN** 使用该 PDF 哈希对应的独立累积术语表，不与上一本教材的术语表混淆

### Requirement: 累积术语表合并

翻译完成后，系统 SHALL 将本轮自动提取的术语与已有累积术语表合并去重后持久化。

#### Scenario: 首次合并
- **WHEN** 翻译完成且 `translate_result.auto_extracted_glossary_path` 指向有效 CSV，且累积术语表不存在
- **THEN** 直接将自动提取的术语 CSV 作为累积术语表写入 `CACHE_DIR/<pdf_hash>/cumulative_glossary.csv`

#### Scenario: 追加合并
- **WHEN** 翻译完成且自动提取术语表和累积术语表均存在
- **THEN** 读取两者，按 `source` 列合并，同一 source 取多数投票的 `target`，写回累积术语表

#### Scenario: 无自动提取术语
- **WHEN** 翻译完成但 auto_extracted_glossary_path 为 None 或文件不包含新术语
- **THEN** 累积术语表保持不变

### Requirement: 与静态术语表兼容

系统 SHALL 同时支持用户静态术语表（`GLOSSARY_PATH`）和累积术语表，两者共存不冲突。

#### Scenario: 静态术语表 + 累积术语表共存
- **WHEN** 用户配置了 `docs/glossary.csv` 且已有累积术语表
- **THEN** `glossaries` 参数包含两个路径（逗号分隔），两个术语表同时生效
```

