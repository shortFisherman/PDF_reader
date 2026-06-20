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
