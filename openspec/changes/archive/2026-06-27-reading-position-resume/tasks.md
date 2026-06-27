## 1. 后端：进度持久化与读取（state.py）

- [x] 1.1 在 `AppState` 新增私有属性 `_reading_progress_path` 派生（由 `glossary_cache_path` 同源逻辑）或私有方法 `_reading_progress_path()`，返回 `cache_dir/<pdf_hash>/reading_progress.json` 或 `None`
- [x] 1.2 新增 `AppState.save_reading_progress(page: int) -> None`：在 `self._lock` 内校验文档已打开（无则抛 `ValueError`），校验 `0 <= page < self._page_count`（越界抛错），原子写入进度文件（`tmp` + `os.replace` 保证不被半写损坏）
- [x] 1.3 新增 `AppState.load_reading_progress() -> int | None`：在锁内读取对应 hash 目录进度文件；解析失败/文件缺失返回 `None`；对越界（`>= page_count`）钳制为 0
- [x] 1.4 在 `open_pdf` 成功打开后调用 `load_reading_progress()`，把 `saved_page`（钳制后整数或 `None`）并入返回 dict
- [x] 1.5 在 `open_pdf` 开始的 `_close_docs`/重置路径确认进度读写不被误清（进度文件独立于 `right.pdf`，不应被删除）
- [x] 1.6 按 `logging_config.py` 既有 `getLogger("pdf_reader.state")` 命名空间，在保存/读取/钳制处加 INFO/DEBUG 日志（如 `[progress] save page=N`、`[progress] load page=N clamp=c`），不输出敏感信息

## 2. 后端：HTTP 接口（routes.py）

- [x] 2.1 新增 `POST /api/reading-progress`：解析 JSON `page`，仅整数；调用 `state.save_reading_progress(page)`，`ValueError("no document opened")` → 400、越界 → 400 "page out of range"，成功返回 `{"ok": true}`，并加 `logger.debug("[route] save-reading-progress page=%d", page)`
- [x] 2.2 （可选/对齐）确认 `POST /api/open` 响应已带 `saved_page`（随 1.4 落地，无新增路由）；如后续需独立查询再加 `GET /api/reading-progress`，本次默认不加以减小面
- [x] 2.3 路由命名/日志沿用 `logger = logging.getLogger("pdf_reader.routes")` 现有风格

## 3. 前端：打开后恢复定位（static/app.js）

- [x] 3.1 `openPdf` 内读取响应 `data.saved_page`；若为有效整数且在 `[1, pageCount]` 之间，在页占位 DOM 构建完成、Observer/页面检测 setup 之后做定位
- [x] 3.2 实现 `scrollToPage(index)` helper：定位左列第 `index` 个 `.page-container`，优先 `el.scrollIntoView({block:'start'})`；定位后由现有 `setupPageDetection` 回调刷新 `currentPage`/`els.pageIndicator`
- [x] 3.3 定位使用 `requestAnimationFrame`/settle gate 等待占位高度就绪后再执行，避免懒加载占位未撑开导致定位偏移
- [x] 3.4 `saved_page` 为 `null`/0/无效时不主动定位（保持顶部首页），不报错
- [x] 3.5 恢复后可选地短暂提示页码（沿用 `els.pageIndicator`，不弹窗，符合 spec）

## 4. 前端：卸载期上报（static/app.js）

- [x] 4.1 在 `openPdf` 成功并初始化完成后注册 `pagehide` 监听；保存当前 `currentPage` 与 `pageCount` 到用于上报的闭包变量
- [x] 4.2 加 `visibilitychange`（`document.hidden`）兜底监听，触发同一 `saveProgress` 函数
- [x] 4.3 `saveProgress()`：仅当文档已打开、`pageCount > 0`、`currentPage ∈ [0, pageCount)` 且 `navigator.sendBeacon` 可用时，用 `application/json` Blob 发起 `POST /api/reading-progress`，body `{"page": currentPage}`
- [x] 4.4 重开新文档时清理上一份监听，避免重复注册/误写旧 hash 的进度（保存接口按当前 `pdf_hash` 写，重复监听本身不致错乱，但应一致地 teardown）
- [x] 4.5 上报不阻塞卸载、不依赖 Promise 解析

## 5. 测试与质量校验

- [x] 5.1 `tests/test_state.py`：覆盖 `save_reading_progress` 正常落盘、文档未开抛错、越界抛错、文件原子写入；`load_reading_progress` 命中/缺失/损坏/越界钳制；`open_pdf` 响应含 `saved_page`
- [x] 5.2 `tests/test_routes.py`：`POST /api/reading-progress` 成功/未开文档/越界分支；`/api/open` 响应 schema 含 `saved_page`
- [x] 5.3 视情况为前端恢复/上报补最小化 DOM/事件测试（若项目无前端测试框架则记录手动验证脚本并归档至 design.md 备注）
- [x] 5.4 运行 `ruff check .`、`ruff format --check .`、`pytest -q` 全绿后再进入 verify 阶段