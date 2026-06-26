## 1. 验证 spike（先行）

- [x] 1.1 spike：验证 pdf2zh-next 在多页输入 + `pages="1-K"` + `only_include_translated_page=True` 下，`mono_pdf_path` 的页数与顺序是否严格等于 target_pages 顺序；记录输出↔原索引映射假设并用临时脚本确认（结果写入 design.md 风险项）

## 2. 后端抽取与回填原语

- [x] 2.1 `pdf_extraction.py` 新增 `extract_pages(src_doc, page_indices, tmpdir)`：在锁内把给定 0-based 页索引按序抽取为一个多页 PDF（`insert_pdf` 多页），返回路径
- [x] 2.2 `state.py` 新增 `replace_pages(translated_pdf_path, page_indices)`：在锁内按顺序用译文第 i 页替换 right.pdf 中 `page_indices[i]` 对应页，保存替换文件并把这些页加入 `translated_pages`
- [x] 2.3 `translation_settings.py` 新增多页 settings 构造（或参数化 `build_settings`）：接受多页 PDF 路径与 `pages="1-K"`，其余沿用 `only_include_translated_page=True`/`no_dual=True`/`ignore_cache=True`

## 3. 后端批量翻译编排

- [x] 3.1 `sse_stream.py` 新增 `generate_batch(ctx)`：在锁内计算 target_pages=range(from-1,to)（连续区间，不跳过已翻译页）、抽取多页 PDF，发 `batch_info` 事件（from/to/total=页数），一次性调用翻译引擎转发进度，完成后调用 `replace_pages` 批量回填与 `finish_translation` 合并术语表，发 `finish`
- [x] 3.2 `sse_stream.py` 新增 `batch_info` SSE 事件格式化
- [x] 3.3 `routes.py` 新增 `POST /api/translate-batch` 端点：接收 1-based 起/止页码，校验合法性与文档已开，构建上下文调用 `generate_batch` 返回 SSE 流
- [x] 3.4 确保批量编排在 `AppState._lock` 串行模型内安全（抽取/回填持锁，翻译执行锁外），避免与渲染竞态

## 4. 前端工具栏 UI

- [x] 4.1 `templates/index.html` 工具栏新增起页/止页 `number` 输入（id `from-page`/`to-page`，`min=1`）与"范围翻译"（id `range-translate-btn`）、"全文翻译"（id `full-translate-btn`）按钮
- [x] 4.2 `static/modules/dom.js` `getElements()` 注册新元素引用
- [x] 4.3 `static/style.css` 补充新输入框与按钮样式，保持工具栏布局协调

## 5. 前端批量翻译逻辑

- [x] 5.1 `static/modules/translator.js` 新增 `translateBatch(from, to, callbacks)`：请求 `/api/translate-batch`，解析 `batch_info`/`progress`/`finish`/`error`，回调 `onBatchInfo`/`onProgress`/`onFinish`/`onError`
- [x] 5.2 `static/app.js` 新增 `onBatchTranslateClick()`：读起/止输入，校验（非数字/超出/起>止），按范围页数 `to-from+1` 判断，>10 弹 `confirm`（提示"通常十页约需 300–400 秒"），确认后调用 `translateBatch`
- [x] 5.3 `static/app.js` 新增 `onFullTranslateClick()`：以 `from=1 to=pageCount` 复用确认与执行路径
- [x] 5.4 `static/app.js` 实现批量进度展示：进度区显示「翻译第 from-to 页（共 N 页）· 」+ 引擎整体百分比/阶段标签（段落级），`finish` 后批量刷新范围内右侧译图并 `loadTranslatedState()`

## 6. 互斥与状态

- [x] 6.1 复用 `isTranslating` 标志：批量进行中禁用单页 Translate、范围/全文翻译按钮及起/止输入框
- [x] 6.2 批量完成后刷新 `/api/translated-pages` 标记

## 7. 测试

- [x] 7.1 `tests/test_pdf_extraction.py`：多页抽取 `extract_pages` 顺序与页数测试
- [x] 7.2 `tests/test_state.py`：`replace_pages` 批量回填多页与 `translated_pages` 更新测试（含并发与边界）
- [x] 7.3 `tests/test_routes.py`：批量端点页码校验（非法→400）、无待翻译页直接 finish
- [x] 7.4 `tests/test_sse_stream.py`：`generate_batch` 发 `batch_info`、跳过已翻译、转发进度与 finish
- [x] 7.5 前端：`translateBatch` 解析 `batch_info`/`progress`/`finish` 回调测试（参照 `tests/run-translator-tests.mjs`）
- [x] 7.6 跑 lint/typecheck 与既有测试套件确认无回归