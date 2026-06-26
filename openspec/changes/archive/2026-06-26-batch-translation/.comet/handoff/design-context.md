# Comet Design Handoff

- Change: batch-translation
- Phase: design
- Mode: compact
- Context hash: aea72edfbf869c0ef14d6a0837949ee9c523f81dffd3675a0614c6b7a848d9db

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/batch-translation/proposal.md

- Source: openspec/changes/batch-translation/proposal.md
- Lines: 1-29
- SHA256: 58de00ad4a42a583408b5b8eec194afa15869a9478480c586d574ce42123a326

```md
## Why

当前 PDF Reader 仅支持逐页翻译——用户必须停在某一页、点击"Translate"才能翻译该页。对于需要翻译多个连续页面或整篇文档的场景，用户不得不反复手动翻页并逐页点击，体验低效。本变更在保留现有单页翻译能力的同时，新增批量翻译入口，让用户一次翻译指定页码范围或整篇文档，并对大批量翻译提供误触保护。

## What Changes

- 新增页码范围翻译：用户在工具栏输入起/止页码（1-based，与界面显示一致），系统翻译该闭区间内所有页面（含端点）。
- 新增"全文翻译"按钮：一键翻译整篇 PDF（等价于范围 1 到总页数）。
- **一次性多页喂入引擎**：将范围内所有页作为单一多页翻译任务一次性提交给 pdf2zh-next 引擎（而非逐页拆分单独喂入），以获得跨页文本的翻译连贯性与更好效果。
- **不跳过已翻译页（为连贯性）**：为保证多页任务的跨页上下文完整，范围内已翻译页也一并纳入本次多页任务重新翻译并覆盖，不再跳过。
- 大批量确认保护：单次翻译范围页数超过 10 页时，点击翻译后弹窗提示"通常十页约需 300–400 秒"，用户确认后才开始；取消则不翻译。≤ 10 页时不弹窗，直接开始。
- 批量进度展示：展示该多页翻译任务的整体进度（进度百分比 + 阶段标签 + 段落级细节）与范围信息"翻译第 from-to 页（共 N 页）"；完成后批量刷新右侧译页并标记已翻译。
- 后端新增批量翻译 SSE 端点：提取范围内未翻译页为多页 PDF → 以 `pages` 一次性翻译 → 用多页译文批量替换 right.pdf 对应页 → 合并术语表。
- 前端新增批量翻译请求与超 10 页确认弹窗，输入校验（非法页码、起>止时提示错误，不开始翻译）。

## Capabilities

### New Capabilities
- `batch-translation`: 批量/范围翻译编排能力，涵盖页码范围翻译、全文翻译、已翻译页跳过、超 10 页确认保护、批量进度展示（总体 + 当前页），以及前端范围输入与确认交互。批量翻译不改变单页翻译链路的行为，而是复用其 SSE 翻译通道对范围内页面逐页编排。

### Modified Capabilities
<!-- 无。单页翻译能力（page-translation）的既有需求与行为保持不变；批量翻译作为新能力复用其翻译通道，不修改其需求。 -->

## Impact

- **后端**：`routes.py` 新增批量翻译 SSE 端点；`sse_stream.py` 新增多页翻译编排（提取多页 → 一次性翻译 → 批量替换 right.pdf → 合并术语表）；`pdf_extraction.py` 新增多页提取函数；`state.py` 新增多页替换函数。单页翻译路径保持不变。
- **前端**：`templates/index.html` 工具栏新增起/止页码输入与"范围翻译/全文翻译"按钮；`static/app.js` 新增批量翻译请求与确认弹窗；`static/modules/dom.js` 新增元素引用；`static/modules/translator.js` 新增批量翻译模块函数。
- **API**：新增 `/api/translate-batch` SSE 端点（接收 1-based 起/止页码）；现有 `/api/translate/<page>`、`/api/translated-pages` 端点不变。
- **依赖**：无新增第三方依赖；复用现有 pdf2zh-next 引擎（`do_translate_async_stream`）与 SSE 机制。
- **测试**：新增多页提取/替换、批量端点页码校验、确认阈值（前端）、SSE 事件解析相关测试；含一个验证 pdf2zh-next 多页输出结构的 spike。```

## openspec/changes/batch-translation/design.md

- Source: openspec/changes/batch-translation/design.md
- Lines: 1-91
- SHA256: 6fa19bec972787117d4de49280c2b5710919b3c21891b401c48272a35dbf3978

[TRUNCATED]

```md
## Context

当前 PDF Reader 已具备单页翻译链路：前端 `onTranslateClick()`（`app.js`）→ `/api/translate/<int:page>` SSE 端点（`routes.py`）→ `sse_stream.generate()`（提取单页 → `run_translation` → `finish_translation` 替换 right.pdf → 合并术语表）。状态保存在 `AppState`（`state.py`），其中 `translated_pages` 记录已翻译页集合，`replace_page` 在锁内替换 `right.pdf` 对应页。

单页链路已经成熟且稳定。但单页链路是把"单页 PDF"喂给引擎（`build_settings` 设置 `pages="1"` 且 `only_include_translated_page=True`，输入是抽取出的单页 PDF）。**重要约束**：pdf2zh-next 引擎本身能接受多页 PDF，并且一次性喂入多页相比逐页拆分单独喂入，跨页文本的翻译更连贯、效果更好。因此本变更的批量翻译**不采用"逐页循环复用单页链路"**，而是**将范围内未翻译页作为单一多页翻译任务一次性提交给引擎**，再以多页译文一次性批量回填 right.pdf。

约束：
- 多页翻译任务仍须遵守 `AppState._lock` 串行模型：多页提取与多页回填分别在锁内完成，翻译执行在锁外（同单页链路）。
- 进度来自引擎对"整段多页任务"的单条进度流；不再有"逐页 X/Y 计数"的天然粒度（见决策 2 与风险）。
- 误触保护在前端按"实际待翻译页数"判断（扣减已翻译页）。
- 不引入翻译取消（本次非目标）。
- 需验证 pdf2zh-next 在 `pages` 多页 + `only_include_translated_page=True` 下输出结构与"输出第 i 页 ↔ 原始页索引"的映射（见风险与 spike）。

## Goals / Non-Goals

**Goals:**
- 新增多页范围翻译与全文翻译入口。
- **一次性多页喂入引擎**以获得跨页翻译连贯性。
- 跳过已翻译页，避免重复耗时。
- 超 10 页（按待翻译页数计）确认保护，≤10 页直接开始。
- 进度展示多页任务整体进度 + 阶段/段落细节与范围信息。
- 页码输入校验（非法/超出范围/起>止）阻断错误请求。

**Non-Goals:**
- 不逐页拆分单独喂入引擎（明确放弃，因损失跨页连贯性）。
- 不实现取消机制（后续可再加）。
- 不修改翻译引擎、配置、术语表合并的单页链路行为。
- 不改动单页"Translate"按钮既有行为。
- 不做多段任务的异步分块/增量保存（本次为单一多页任务，见风险）。

## Decisions

### 决策 1：将范围内未翻译页作为单一多页翻译任务一次性喂入引擎

**选择**：后端新增 `POST /api/translate-batch` SSE 端点，接收 `{from, to, prompt}`（1-based）。流程为：
1. 计算 `target_pages = range(from-1, to) 内 0-based 索引`（含端点的连续区间，**不跳过已翻译页**——为保证多页上下文完整连贯）。
2. 若区间为空（起>止已在入口校验阻断），不会到达此处。
3. 在 `AppState._lock` 内用新增 `pdf_extraction.extract_pages(src_doc, target_pages, tmpdir)` 把这些页抽取为一个**多页 PDF**。
4. `build_settings` 改/新增一个多页变体：输入=多页 PDF 路径，`pages="1-<k>"`（k=len(target_pages)），`only_include_translated_page=True`、`no_dual=True`、`ignore_cache=True` 等沿用。
5. `do_translate_async_stream` **一次**翻译整段多页 PDF，SSE 转发引擎进度。
6. 得到 `translate_result.mono_pdf_path`（含 k 页译文，按 target_pages 顺序），调用新增 `state.replace_pages(translated_pdf, target_pages)` 在锁内**批量回填** right.pdf 对应原索引页。
7. `finish_translation` 合并术语表一次，发出 `finish`。

**备选 A：逐页循环复用单页链路（外层逐页喂入）。** 缺点：每页单独喂入，跨页文本无连贯上下文，效果差（本变更正为此而改）。优点是每页完成即落盘、失效粒度小。
**备选 B：直接对完整原文档设 `pages="from-to"`、`only_include_translated_page=True`，不抽取子集。** 与抽取子集喂入在"翻译哪几页"上等价（引擎只处理指定 pages），但需用原文档路径且 pages 为原文档 1-based 索引；抽取子集方式与现有"`extract_*` 在锁内取页、译文喂回"模型更一致、隔离更干净，故选抽取子集。

**理由**：一次性多页喂入兼顾跨页连贯性；抽取子集与既有 lock 模型一致；批量回填一次完成。

### 决策 2：SSE 事件结构沿用现有 `progress`/`finish`/`error`，追加"批量范围信息"一次性事件

- 沿用现有 `progress`（引擎整体进度，含 stage、stage_current/stage_total、overall_progress）。
- 新增一次性的 `batch_info` 事件（在流起始发出）：`{type:"batch_info", from, to, total}`，前端据此显示"翻译第 from-to 页（共 total 页）"。
- 复用现有 `finish`/`error` 语义。
- **不**引入逐页 `batch_page_done`/`batch_skipped` 计数事件（一次性多页任务无逐页产出粒度；跳过信息已在 `batch_info.total/skipped` 体现）。

**与原"总体 X/Y + 当前页"的取舍**：单次多页任务天然只有"整体进度+段落级细节"，没有"第 X/Y 页"的逐页计数。前端展示=「翻译第 from-to 页（含 N 页，跳过 M 页）」+ 引擎整体百分比/阶段标签（含"第 j/k 段"）。这是为换取跨页连贯性所接受的进度粒度变化（已在风险中记录，交由用户在确认阶段知悉）。

**理由**：最小改动复用现有解析；范围信息与进度分离，互不干扰。

### 决策 3：不跳过已翻译页——范围内全部重译以保证跨页连贯

为本变更的核心目标（跨页连贯）服务：已翻译页也一并纳入多页任务重新翻译并覆盖。不再读 `translated_pages` 做跳过判断。`replace_pages` 回填覆盖范围内所有页并把这些页标记为已翻译。

**理由**：若跳过区间内某个已翻译页，喂给引擎的多页 PDF 会缺失该页，破坏该页与其前后页的跨页上下文。完整连贯优先于"省时间"（用户明确选择）。

### 决策 4：超 10 页确认保护放前端，按"范围页数"判断

前端点击范围/全文翻译时，计算范围页数 `to-from+1`。> 10 则 `confirm()` 弹窗（提示"通常十页约需 300–400 秒"），确认后才请求批量端点；≤ 10 直接请求。不再需要查询 `/api/translated-pages` 计算待翻译页数。

**备选：后端入口判断并要求前端二次确认。** 缺点：多一次往返，无额外收益。

**理由**：已翻译页集合前端本就需要（刷新译页标记），复用计算阈值零成本；这是用户意图判断，属于前端职责。

### 决策 5：前端新增 `translator.js` 的 `translateBatch` 与 `app.js` 的 `onBatchTranslateClick`/`onFullTranslateClick`

`translateBatch(from, to, callbacks)` 请求 `/api/translate-batch`，解析 `batch_info` 与 `progress`/`finish`/`error`，回调 `onBatchInfo(from,to,total,skipped)`、`onProgress(percent,stage,label)`、`onFinish()`、`onError(msg)`。`app.js` 据此把进度区文字设为「翻译第 from-to 页（含 N 页，跳过 M 页）· 」+ 当前阶段标签与百分比；`finish` 后刷新范围内所有右侧译图并 `loadTranslatedState()` 标记。

**理由**：与 `translateCurrentPage` 对称，保持前端模块结构一致（`frontend-modular-architecture` 既有约定）。

### 决策 6：页码输入 UI
```

Full source: openspec/changes/batch-translation/design.md

## openspec/changes/batch-translation/tasks.md

- Source: openspec/changes/batch-translation/tasks.md
- Lines: 1-42
- SHA256: 4d81af4a4b97d9db6b3f6bddf807b643acc6fdf67d775c353054683e4038ba1a

```md
## 1. 验证 spike（先行）

- [ ] 1.1 spike：验证 pdf2zh-next 在多页输入 + `pages="1-K"` + `only_include_translated_page=True` 下，`mono_pdf_path` 的页数与顺序是否严格等于 target_pages 顺序；记录输出↔原索引映射假设并用临时脚本确认（结果写入 design.md 风险项）

## 2. 后端抽取与回填原语

- [ ] 2.1 `pdf_extraction.py` 新增 `extract_pages(src_doc, page_indices, tmpdir)`：在锁内把给定 0-based 页索引按序抽取为一个多页 PDF（`insert_pdf` 多页），返回路径
- [ ] 2.2 `state.py` 新增 `replace_pages(translated_pdf_path, page_indices)`：在锁内按顺序用译文第 i 页替换 right.pdf 中 `page_indices[i]` 对应页，保存替换文件并把这些页加入 `translated_pages`
- [ ] 2.3 `translation_settings.py` 新增多页 settings 构造（或参数化 `build_settings`）：接受多页 PDF 路径与 `pages="1-K"`，其余沿用 `only_include_translated_page=True`/`no_dual=True`/`ignore_cache=True`

## 3. 后端批量翻译编排

- [ ] 3.1 `sse_stream.py` 新增 `generate_batch(ctx)`：在锁内计算 target_pages=range(from-1,to)（连续区间，不跳过已翻译页）、抽取多页 PDF，发 `batch_info` 事件（from/to/total=页数），一次性调用翻译引擎转发进度，完成后调用 `replace_pages` 批量回填与 `finish_translation` 合并术语表，发 `finish`
- [ ] 3.2 `sse_stream.py` 新增 `batch_info` SSE 事件格式化
- [ ] 3.3 `routes.py` 新增 `POST /api/translate-batch` 端点：接收 1-based 起/止页码，校验合法性与文档已开，构建上下文调用 `generate_batch` 返回 SSE 流
- [ ] 3.4 确保批量编排在 `AppState._lock` 串行模型内安全（抽取/回填持锁，翻译执行锁外），避免与渲染竞态

## 4. 前端工具栏 UI

- [ ] 4.1 `templates/index.html` 工具栏新增起页/止页 `number` 输入（id `from-page`/`to-page`，`min=1`）与"范围翻译"（id `range-translate-btn`）、"全文翻译"（id `full-translate-btn`）按钮
- [ ] 4.2 `static/modules/dom.js` `getElements()` 注册新元素引用
- [ ] 4.3 `static/style.css` 补充新输入框与按钮样式，保持工具栏布局协调

## 5. 前端批量翻译逻辑

- [ ] 5.1 `static/modules/translator.js` 新增 `translateBatch(from, to, callbacks)`：请求 `/api/translate-batch`，解析 `batch_info`/`progress`/`finish`/`error`，回调 `onBatchInfo`/`onProgress`/`onFinish`/`onError`
- [ ] 5.2 `static/app.js` 新增 `onBatchTranslateClick()`：读起/止输入，校验（非数字/超出/起>止），按范围页数 `to-from+1` 判断，>10 弹 `confirm`（提示"通常十页约需 300–400 秒"），确认后调用 `translateBatch`
- [ ] 5.3 `static/app.js` 新增 `onFullTranslateClick()`：以 `from=1 to=pageCount` 复用确认与执行路径
- [ ] 5.4 `static/app.js` 实现批量进度展示：进度区显示「翻译第 from-to 页（共 N 页）· 」+ 引擎整体百分比/阶段标签（段落级），`finish` 后批量刷新范围内右侧译图并 `loadTranslatedState()`

## 6. 互斥与状态

- [ ] 6.1 复用 `isTranslating` 标志：批量进行中禁用单页 Translate、范围/全文翻译按钮及起/止输入框
- [ ] 6.2 批量完成后刷新 `/api/translated-pages` 标记

## 7. 测试

- [ ] 7.1 `tests/test_pdf_extraction.py`：多页抽取 `extract_pages` 顺序与页数测试
- [ ] 7.2 `tests/test_state.py`：`replace_pages` 批量回填多页与 `translated_pages` 更新测试（含并发与边界）
- [ ] 7.3 `tests/test_routes.py`：批量端点页码校验（非法→400）、无待翻译页直接 finish
- [ ] 7.4 `tests/test_sse_stream.py`：`generate_batch` 发 `batch_info`、跳过已翻译、转发进度与 finish
- [ ] 7.5 前端：`translateBatch` 解析 `batch_info`/`progress`/`finish` 回调测试（参照 `tests/run-translator-tests.mjs`）
- [ ] 7.6 跑 lint/typecheck 与既有测试套件确认无回归```

## openspec/changes/batch-translation/specs/batch-translation/spec.md

- Source: openspec/changes/batch-translation/specs/batch-translation/spec.md
- Lines: 1-109
- SHA256: 360dc0ef91135124483cd01b98ff9bd1db3338243d53963c61057c44ef3a0deb

[TRUNCATED]

```md
## ADDED Requirements

### Requirement: 页码范围翻译

系统 SHALL 允许用户在工具栏输入起/止页码（1-based，与界面"Page N"显示一致），翻译该闭区间内（含端点）的**全部页**。范围翻译 SHALL 将范围内所有页作为**单一多页翻译任务一次性提交**给 pdf2zh-next 引擎（而非逐页拆分单独喂入），以获得跨页文本的翻译连贯性。用户输入的 1-based 页码 SHALL 在内部转换为 0-based 索引；系统 SHALL 把区间内全部页抽取为一个多页 PDF，以 `pages` 多页范围一次性翻译，再将多页译文按原页索引批量回填 right.pdf。**范围内已翻译页也一并纳入重译并覆盖**（不跳过），以保证多页跨页上下文完整连贯。

#### Scenario: 用户翻译合法范围

- **WHEN** 用户输入起页 2、止页 5（文档总页数 ≥ 5）并点击范围翻译
- **THEN** 系统 SHALL 将内部索引 1、2、3、4 对应的页面（即界面显示的第 2、3、4、5 页）抽取为一个多页 PDF 并一次性翻译，再用译文批量替换 right.pdf 中对应页

#### Scenario: 范围含已翻译页一并重译

- **WHEN** 范围内某页已被翻译过，用户对其所在范围再次请求范围翻译
- **THEN** 系统 SHALL 不跳过该页，将其随同范围内其余页一起纳入多页任务重新翻译并覆盖该页既有译文，以保证跨页连贯

#### Scenario: 范围仅一页

- **WHEN** 用户输入起页与止页相同（如 3 到 3）
- **THEN** 系统 SHALL 一次性翻译该单页并替换 right.pdf 对应页

#### Scenario: 范围翻译完成刷新译页

- **WHEN** 范围多页翻译任务完成并批量回填 right.pdf
- **THEN** 范围内所有页的右侧译图 SHALL 刷新为译文内容并标记为已翻译

### Requirement: 全文翻译

系统 SHALL 提供"全文翻译"按钮，点击后翻译整篇 PDF（等价于页码范围 1 到文档总页数）。

#### Scenario: 触发全文翻译

- **WHEN** 用户点击"全文翻译"按钮
- **THEN** 系统 SHALL 以范围 1 到总页数发起批量翻译（多页任务一次性翻译并批量回填），行为与同等范围的范围翻译一致

#### Scenario: 全文翻译复用范围机制

- **WHEN** 全文翻译执行
- **THEN** 全文翻译 SHALL 遵循与范围翻译相同的不跳过已翻译页（全量重译）、进度展示与（当范围超过 10 页时）确认保护规则

### Requirement: 大批量确认保护

单次批量翻译的范围页数（`to-from+1`）超过 10 页时，系统 SHALL 在开始翻译前弹出确认对话框，告知"通常十页约需 300–400 秒"；用户确认后才开始翻译，取消则不翻译任何页。范围页数 ≤ 10 时 SHALL 不弹窗，直接开始翻译。

#### Scenario: 超过十页需确认

- **WHEN** 范围页数为 11 页（或更多）
- **THEN** 系统 SHALL 弹出确认对话框，显示长时间耗时提示，用户点击确认后才开始批量翻译，用户点击取消则不翻译

#### Scenario: 恰好十页不需确认

- **WHEN** 范围页数为 10 页（或更少）
- **THEN** 系统 SHALL 不弹出确认对话框，直接开始批量翻译

#### Scenario: 已翻译页不参与阈值判断

- **WHEN** 范围为 15 页（无论其中多少页已翻译）
- **THEN** 系统 SHALL 按 15 页判断（> 10），弹出确认对话框，确认后才翻译

### Requirement: 批量翻译进度展示

批量翻译进行时，系统 SHALL 展示该单一多页翻译任务的整体进度（引擎进度百分比与阶段标签，含段落级细节）以及范围信息"翻译第 from-to 页（共 N 页）"，其中 N 为范围页数 `to-from+1`。

#### Scenario: 范围信息与整体进度展示

- **WHEN** 批量多页翻译任务进行中
- **THEN** 进度区 SHALL 显示「翻译第 from-to 页（共 N 页）」与引擎整体进度百分比/阶段标签（含段落级"第 j/k 段"）

#### Scenario: 批量翻译完成展示

- **WHEN** 批量多页翻译任务完成
- **THEN** 进度区 SHALL 短暂展示完成状态后回到空闲状态，翻译按钮恢复可用，范围内所有右侧译图刷新并标记已翻译

### Requirement: 批量翻译页码范围校验

系统 SHALL 在开始批量翻译前校验用户输入的起/止页码；非法输入（非数字、超出文档范围、起页大于止页）SHALL 提示错误且不开始任何翻译。

#### Scenario: 起页大于止页

- **WHEN** 用户输入起页 5、止页 2
```

Full source: openspec/changes/batch-translation/specs/batch-translation/spec.md

