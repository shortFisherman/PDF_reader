# Brainstorm Summary

- Change: batch-translation
- Date: 2026-06-26

## Confirmed Technical Approach

浏览器 toolbar 新增起/止页码输入 + "范围翻译" / "全文翻译" 按钮。前端按范围页数 `to-from+1` 判断 >10 弹确认（提示"通常十页约需 300–400 秒"），确认后请求新增后端端点 `POST /api/translate-batch {from,to,prompt}`（1-based）。

后端在 `AppState._lock` 内用新增 `pdf_extraction.extract_pages(left_doc, page_indices, tmpdir)` 把范围内全部页（连续区间 `range(from-1,to)`，**含已翻译页一并重译**以保跨页连贯）抽取为一个多页 PDF；`build_settings` 参数化为多页输入 + `pages="1-K"` + `only_include_translated_page=True` + `no_dual=True` + `ignore_cache=True`；`sse_stream.generate_batch` 一次性 `run_translation`、发 `batch_info {from,to,total}`、转发引擎 progress/finish/error，完成后在锁内新增 `state.replace_pages(mono_pdf, target_pages)` 批量回填 right.pdf 对应页（升序逐页 `delete_page(i)` + `insert_pdf(translated, start_at=i, from_page=j, to_page=j)`，保存 `.tmp`→os.replace→重开），`finish` 前调用 `finish_translation` 合并术语表一次。

前端 `translator.translateBatch` 解析批量 SSE，`app.onBatchTranslateClick`/`onFullTranslateClick` 处理校验/确认；进度区显示「翻译第 from-to 页（共 N 页）· 」+ 引擎整体百分比/阶段标签（段落级），完成后批量刷新范围内右侧译图并 `loadTranslatedState()`。复用 `isTranslating` 互斥禁用单页与批量按钮。

## Key Trade-offs and Risks

- 单次多页任务**无增量落盘**：中途失败则整批无回填（work 已翻译但不写回 right.pdf）。换取跨页连贯性——本变更核心目标。
- 进度为引擎整体流，**无逐页 X/Y 计数**：粒度变化已在 open 阶段经用户知悉并接受。
- 已翻译页被重译覆盖（用户为连贯性明确选择不跳过）。
- SSE 长连接超时：沿用 `run_translation` 每秒 `yield ""` 心跳 + 引擎持续 progress 事件。
- pdf2zh 多页输出↔原索引映射经源码确认为确定性（`parse_pages` 支持逗号/范围 1-based；`only_include_translated_page` 输出按输入顺序仅含选中页），无需联网 spike，降级为合成译文 PDF 的纯单元测试。

## Testing Strategy

- 纯单元（无需引擎/API）：`extract_pages` 多页顺序与页数；`replace_pages` 索引映射（合成 K 页译文 PDF）；`parse_pages` 构造正确性 via `build_settings_multi`；端点页码校验 →400；`generate_batch` 发 `batch_info`/无待翻译直接 finish/转发进度（mock `run_translation`）。
- 前端：`translateBatch` 解析 `batch_info`/`progress`/`finish`/`error` 回调（沿用 `tests/run-translator-tests.mjs` 模式）；超 10 页确认阈值。
- 回归：现有 `tests/` 全套 + lint/typecheck。

## Spec Patches

None — open 阶段 `specs/batch-translation/spec.md` 已含充分验收场景（范围/全文/不跳过重译/确认阈值按范围页数/进度展示/页码校验/批量SSE端点），无需写回 delta spec 补丁。