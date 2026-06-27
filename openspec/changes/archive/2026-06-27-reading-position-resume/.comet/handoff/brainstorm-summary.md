# Brainstorm Summary

- Change: reading-position-resume
- Date: 2026-06-27

## Confirmed Technical Approach

闭式闭环：打开时由 `AppState.open_pdf` 读取 `cache_dir/<pdf_hash>/reading_progress.json`，越界钳制为 0，返回 `saved_page` 并入 `/api/open` 响应；前端 `openPdf` 在页占位 DOM 构建完成且 IntersectionObserver/scrollSync/pageDetection 装配后，用 `requestAnimationFrame`/settle 等占位高度就绪，对左列第 `saved_page` 个 `.page-container` 调用 `scrollIntoView({block:'start'})` 定位，由现有 `setupPageDetection` 回调刷新 `currentPage`/`els.pageIndicator`；缩放保持默认 100%，不弹窗。

卸载期保存：前端监听 `pagehide`（主）+ `visibilitychange`(hidden 兜底)，触发 `saveProgress()`；仅当文档已打开、`pageCount>0`、`currentPage∈[0,pageCount)` 且 `navigator.sendBeacon` 可用时，用 `application/json` Blob `POST /api/reading-progress` body `{"page":currentPage}`，`sendBeacon` 不可用时回退 `fetch(url,{keepalive:true})`；不阻塞卸载，不依赖 Promise 解析。**切档不保存**（同一标签页内打开新文档时不主动保存旧文档），仅卸载时保存；teardown 只防重复绑定监听。

后端：`routes.py` 新增 `POST /api/reading-progress`，校验整数页码、文档已开、`0<=page<page_count`，调用 `AppState.save_reading_progress(page)` 原子写（`.tmp`+`os.replace`，复用 `self._lock` 串行化）；越界/未开文档返回 400。`AppState.load_reading_progress()` 读取端对文件缺失/损坏吞异常返回 `None`，越界钳制 0。

## Key Trade-offs and Risks

- 卸载期断电/强杀进程可能丢最新页码——已确认接受（仅卸载保存、切档不保存）。
- 进度文件损坏——读取侧 try/except 返回 None，绝不抛路由。
- 文档被替换但路径相同——hash 变化即视作新文档，从第1页开始，无需迁移。
- `sendBeacon` 仅 POST 单次载荷——与现有路由 POST 风格一致，无需改方法。
- 多标签同开同文档——后端 `_lock` 串行化，最后写者赢，页码相近可接受。
- 双层越界守卫（前端 guard + 后端 range-check）确保不写脏值。

## Testing Strategy

- `tests/test_state.py`：`save_reading_progress` 正常落盘/未开抛错/越界抛错/原子写；`load_reading_progress` 命中/缺失/损坏/越界钳制；`open_pdf` 响应含 `saved_page`。
- `tests/test_routes.py`：`POST /api/reading-progress` 成功/未开文档/越界分支；`/api/open` 响应 schema 含 `saved_page`。
- 前端无 JS 测试框架：在 design doc 备注手动验证脚本（打开→翻到第N页→关闭→重开自动定位至N）；后续如需前端测试可单列任务。
- 质量门：`ruff check .`、`ruff format --check .`、`pytest -q` 全绿后进入 verify 阶段。

## Spec Patches

None — OpenSpec `specs/reading-position-resume/spec.md` 的 4 条 requirement + 场景已覆盖本设计全部行为（仅卸载保存、不切档、越界降级、无弹窗、不重放缩放、按 hash 持久化）。本次深度设计未引入新需求或需修改的 requirement。