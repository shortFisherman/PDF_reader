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

工具栏新增两个 `number` 输入（起页/止页，`min=1 max=pageCount`）+"范围翻译"按钮+"全文翻译"按钮。批量进行中三者与单页 Translate 按钮均 disabled（复用 `isTranslating`），避免并发翻译。

## Risks / Trade-offs

- [多页输出↔原索引映射未经验证] → **spike 先验证** pdf2zh-next 在 `pages="1-k"` + `only_include_translated_page=True` 下 `mono_pdf_path` 的页数与顺序是否严格等于 target_pages 顺序。若输出页数不等于输入页数，回填需按"输出页顺序 = target_pages 顺序"假设并加断言/校验。
- [单次多页任务无增量落盘] → 若中途失败，已抽取+翻译的工作不落盘（right.pdf 未回填），整批无成果保留。权衡：换取跨页连贯性。后续可探索分块多页任务以兼顾连贯与增量保存。
- [批量单流耗时较长，SSE 可能被代理超时] → 沿用现有 `Cache-Control: no-cache` 及 `run_translation` 每秒 `yield ""` 心跳；引擎对长任务亦持续产出 progress 事件维持连接。
- [全文翻译对超大文档误触] → 由超 10 页确认保护覆盖；全文翻译对 >10 页文档必然触发确认。
- [已翻译页被重译覆盖] → 本次为跨页连贯明确选择重译范围内全部页，用户已知悉；旧译文被覆盖。
- [number 输入边界] → 前端 `min/max` + 显式校验，后端再校验返回 400，双保险。
- [进度粒度变化与先前选择不同] → 已在决策 2 与本风险记录，需在确认阶段知悉用户。