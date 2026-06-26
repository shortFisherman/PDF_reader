---
comet_change: batch-translation
role: technical-design
canonical_spec: openspec
---

# Batch Translation — Technical Design

## 1. Goal

在保留单页翻译链路稳定的前提下，新增批量翻译：用户输入起/止页码或点"全文翻译"，系统将范围内**全部页**作为单一多页翻译任务一次性提交 pdf2zh-next，再用多页译文批量回填 right.pdf。范围内已翻译页一并重译并覆盖，以保证跨页文本连贯性。``单次范围超过 10 页时弹窗确认``（提示"通常十页约需 300–400 秒"）。

## 2. Context

现有单页链路：`app.onTranslateClick` → `POST /api/translate/<page>` → `sse_stream.generate`（`extract_page` 单页抽取 → `build_settings(pages="1")` → `run_translation` → `finish_translation`/`replace_page` 替换 right.pdf 单页 → 合并术语表）。`AppState._lock` 串行化所有文档访问。

pdf2zh-next 经源码确认只输出选中页、保留输入顺序：
- `parse_pages`（`pdf2zh_next/config/model.py:437`）支持逗号分隔 `1-based` `"1-K"` 范围/单页。
- `only_include_translated_page`（`config/model.py:190`）仅在 `pages` 指定时生效，输出仅含选中页且**按输入顺序**。
→ 抽取 K 页子集 + `pages="1-K"` → 输出恰 K 页、第 j 页 ↔ 原 `target_pages[j-1]`，映射确定性，无需联网 spike。

## 3. Non-goals

- 不逐页拆分单独喂入引擎（损失跨页连贯，本变更核心）。
- 不实现取消。
- 无增量落盘/分块；不改引擎、配置、术语表合并单页行为。
- 不再跳过已翻译页（重译覆盖）。

## 4. Architecture

```
   POST /api/translate-batch {from, to, prompt}        (1-based; 起止校验→400)
            │
            ▼
 ┌─ sse_stream.generate_batch(ctx) ──────────────────────────────────┐
 │ 1. lock: extract_pages(left_doc, target_pages, tmpdir)            │  pdf_extraction.extract_pages (NEW, 多页 insert_pdf)
 │      target_pages = range(from-1, to)   # 连续区间, 含已翻译      │
 │ 2. yield batch_info {type, from, to, total=len(target_pages)}     │  format_batch_info (NEW)
 │ 3. settings = build_settings(multi_pdf_path, pages="1-K")          │  translation_settings.build_settings (参数化)
 │ 4. for evt in run_translation(settings, multi_pdf_path): yield     │  转发 progress/finish/error
 │ 5. if translate_result:                                            │
 │      lock: replace_pages(mono_pdf, target_pages)                  │  state.replace_pages (NEW)
 │      finish_translation(translate_result, replace_pages, glossary)  # 注意: 多页已在 step5 回填, finish_translation 仅做术语表合并
 │ 6. yield finish                                                    │
 └────────────────────────────────────────────────────────────────────┘
```

### 4.1 GenerateBatchContext

复用/扩展 `GenerateContext`，新增 `from_page`/`to_page`/`page_indices`。`replace_page` 回调改为批量版 `replace_pages(translated_pdf_path)`（闭包捕获 `page_indices`）；术语表合并沿用 `finish_translation` 但**跳过其内部 replace**（多页已在 step5 回填）——做法：传一个空/直通的 replace 给 finish_translation，或拆出独立术语表合并调用。**下文 §7 决策**采用后者：新增 `merge_glossary_only(...)`，`generate_batch` 显式调 `replace_pages` + `merge_glossary_only`，避免 `finish_translation` 的单页 replace 分支。

### 4.2 前端

```
app.onBatchTranslateClick / onFullTranslateClick
  → 校验 (非数字/超出/起>止 → 错误提示, 不开始)
  → range_count = to-from+1 ;  >10 → confirm("通常十页约需 300–400 秒")
  → translator.translateBatch(from,to,{onBatchInfo,onProgress,onFinish,onError})
       POST /api/translate-batch, 读SSE
  → 进度区: 「翻译第 from-to 页（共 N 页）· 」+ 引擎整体% / 阶段标签(段落级)
  → finish: 批量刷新范围内右侧译图(loadPageImage)+loadTranslatedState()
  → isTranslating 互斥禁用单页/范围/全文按钮与输入
```

## 5. New/Modified Units

| 单元 | 文件 | 职责 | 依赖 |
|------|------|------|------|
| `extract_pages` | `pdf_extraction.py` | 多页抽取为单一 PDF（锁内由 AppState 调） | pymupdf |
| `AppState.replace_pages` | `state.py` | 升序逐页回填多个页、批量更新 translated_pages | pymupdf |
| `build_settings`(参数化) | `translation_settings.py` | 单页 `pages="1"` / 多页 `pages="1-K"` + input | config, engine_resolver |
| `generate_batch` + `format_batch_info` | `sse_stream.py` | 多页编排 + batch_info 事件 | run_translation, finish_translation, pdf_extraction |
| `merge_glossary_only` | `translation_lifecycle.py` | 仅合并术语表（多页已回填） | glossary_service |
| `translate_batch`(route) | `routes.py` | 端点页码校验→SSE | generate_batch |
| `translateBatch` | `translator.js` | 解析批量 SSE | sse-client |
| `onBatch/FullTranslateClick` | `app.js` | 校验/确认/进度/刷新 | translator, dom |
| toolbar 元素 | `index.html`, `dom.js` | 起/止输入 + 两按钮 | — |
| 样式 | `style.css` | toolbar 布局 | — |

### 5.1 `extract_pages`

```python
def extract_pages(src_doc, page_indices, tmpdir) -> Path:
    multi = tmpdir / "pages.pdf"
    doc = pymupdf.open()
    doc.insert_pdf(src_doc, from_page=page_indices[0], to_page=page_indices[-1])  # 连续区间一次插入
    doc.save(str(multi)); doc.close()
    return multi
```
（`page_indices` 为连续区间，可一次 `insert_pdf` 整段；若未来需非连续再分次插入。）

### 5.2 `replace_pages`

```python
def replace_pages(self, translated_pdf_path, page_indices):
    with self._lock:
        src = pymupdf.open(translated_pdf_path)
        for j, idx in enumerate(page_indices):          # 升序
            self._right_doc.delete_page(idx)
            self._right_doc.insert_pdf(src, start_at=idx, from_page=j, to_page=j)
        tmp = self._right_pdf_path + ".tmp"
        self._right_doc.save(tmp); src.close(); self._right_doc.close()
        os.replace(tmp, self._right_pdf_path)
        self._right_doc = pymupdf.open(self._right_pdf_path)
        self._translated_pages.update(page_indices)
```
`delete_page(idx)`+`insert_pdf(start_at=idx)` 同位置进出，其他索引保持稳定；升序逐页推进时后续目标索引不受扰动。

### 5.3 `build_settings` 参数化

新增可选 `pages: str = "1"` 与显式 `input_pdf` 替代隐式首个位置参数（保持单页路径默认 `pages="1"`）。

### 5.4 `batch_info` SSE

`data: {"type":"batch_info","from":int,"to":int,"total":int}\n\n`，流首发出（在第一次 progress 前）。其余 `progress`/`finish`/`error` 沿用现有 `format_sse_event`。

## 6. Data Flow / Concurrency

- 串行模型保持：`extract_pages`、`replace_pages` 各持 `AppState._lock`；`run_translation` 在锁外子进程执行（同单页）。
- 单一多页任务=一次 `do_translate_async_stream` 调用=SSE 单流；不并发翻译。

## 7. Key Decisions

1. **喂抽取子集而非原文档+pages**：与现有"锁内取页、锁外喂译文"模型一致、隔离干净；输出↔原索引按子集序确定性映射。
2. **不跳过已翻译页**：范围内全量重译覆盖，保跨页连贯（用户明确选择）；阈值按范围页数判断，无需查 translated-pages。
3. **进度复用引擎整体流**：不引入逐页事件；仅追加一次性 `batch_info`。
4. **多页回填与术语表合并解耦**：`generate_batch` 显式调 `replace_pages` + `merge_glossary_only`，不复用 `finish_translation` 的单页 replace 分支（避免双重回填/语义错位）。
5. **确认弹窗用 `confirm()`**：符合误触保护的最简实现。

## 8. Risks / Trade-offs

- **无增量落盘**：单次多页任务失败→整批无回填（work 译文不写回）。已知接受，换取连贯；后续可探索分块任务兼顾。
- **进度粒度**：无逐页 X/Y；显示整体%+范围信息。已知接受。
- **已翻译页重译覆盖**：旧译文被覆盖。已知接受。
- **大范围长时SSE**：`run_translation` 每秒 `yield ""` 心跳 + 引擎持续 progress 维持连接；`Cache-Control: no-cache`。
- **pymupdf insert_pdf from_page/to_page**：通用支持；若某版本不支持单页插入边界，退化方案为每页建 1 页临时 doc 再 insert。已列为实现期校验点。

## 9. Testing

- 纯单元（无引擎）：`extract_pages` 页数/顺序；`replace_pages` 索引映射（合成 K 页译文 PDF，每页含可区分内容，断言 right.pdf 目标页被替换）；`build_settings` 多页 `pages` 正确性；端点页码校验→400；`generate_batch`（mock run_translation）发 `batch_info`/finish。
- 前端（`run-translator-tests.mjs` 模式）：`translateBatch` 对 `batch_info`/`progress`/`finish`/`error` 回调；>10 确认阈值。
- 回归：现有 `tests/` 全套 + lint/typecheck。

## 10. Acceptance

对应 `specs/batch-translation/spec.md` 全部场景：范围翻译、范围含已翻译页一并重译、范围仅一页、完成刷新译页、全文翻译复用、确认阈值(>10弹窗/按范围页数)、进度展示、页码校验(起>止/超范围/非数字→阻断)、批量端点(batch_info/纳入已翻译页重译/校验→400)。

## 11. Open Items

- 实现期校验：本机 pymupdf 版本对 `insert_pdf(from_page=j,to_page=j)` 单页插入的支持；不支持则采用"每页 1 页临时 doc"退化。
- 实现期确认：`finish_translation` 是否可被 `merge_glossary_only` 平替——直接抽取其术语表合并段独立为函数。