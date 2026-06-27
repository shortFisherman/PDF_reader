---
comet_change: reading-position-resume
role: technical-design
canonical_spec: openspec
archived-with: 2026-06-27-reading-position-resume
status: final
---

# Technical Design — reading-position-resume

本设计为 OpenSpec 变更 `reading-position-resume` 的深度技术设计。需求契约见 `openspec/changes/reading-position-resume/specs/reading-position-resume/spec.md`（4 条 requirement 已覆盖全部行为，本设计不引入新需求、不修改 requirement）。

## 1. 目标与边界

**目标**
- 打开曾阅读的 PDF 时按 `saved_page` 自动跳回上次页码，零额外操作。
- 进度按 PDF 内容哈希 (`pdf_hash`) 存放，跨浏览器/重装有效（仅清 cache 失效）。
- 卸载期可靠落盘，使用浏览器原生 `sendBeacon`，不被取消。
- 越界页码安全降级，进度文件损坏不致崩溃。

**非目标（已在 OpenSpec 中固化）**
- 不恢复缩放、页内滚动偏移。
- 不做跨设备/云端同步；不做多文档并行进度。
- 不弹"是否继续"询问弹窗。
- 同标签页内切换文档时**不**主动保存旧文档进度（仅卸载保存）。
- 不改变翻译/雪花缓存/双栏/术语表等既有能力。

## 2. 数据结构与存储

进度文件：`config.CACHE_DIR / <pdf_hash> / reading_progress.json`，内容：

```json
{ "page": <0-based int> }
```

- 生命周期与该文档缓存同目录（`right.pdf`、术语表同在），随 cache 整体清理，无需独立迁移。
- 无 schema 版本号：单字段、不可空时直接钳制；后续如需扩展（如时间戳）可平滑增字段，旧字段兼容。

## 3. 后端组件

### 3.1 `state.py` 改动

新增私有方法 `_reading_progress_path(self) -> Path | None`，复用 `glossary_cache_path` 同源逻辑（基于 `self._pdf_hash`）。

新增 `AppState.save_reading_progress(self, page: int) -> None`：
- 在 `self._lock` 内执行。
- 文档未打开（`self._left_doc is None` 或 `self._pdf_hash is None`）→ 抛 `ValueError("no document opened")`。
- `page` 非整数或 `page < 0 or page >= self._page_count` → 抛 `ValueError("page out of range")`。
- 路径为 `None` → 抛 `ValueError`。
- 原子写：写 `reading_progress.json.tmp` → `os.replace(tmp, final)`（与现有 `replace_page` 手法一致），失败时清理 tmp。

新增 `AppState.load_reading_progress(self) -> int | None`：
- 在 `self._lock` 内执行。
- 路径为 `None` → 返回 `None`。
- 文件缺失/JSON 解析失败/缺 `page` 键/类型错误 → 返回 `None`（吞异常，记 DEBUG）。
- 越界（`page >= self._page_count`）→ 钳制为 0；负值钳制为 0。

修改 `AppState.open_pdf(...)` 返回 dict：成功打开后调用 `load_reading_progress()`，把 `saved_page`（钳制后 int 或 `None`）并入现有返回键 `{page_count, page_height, page_width, hash, saved_page}`。

日志沿用 `logger = logging.getLogger("pdf_reader.state")`：
- `[progress] save hash=... page=N`
- `[progress] load hash=... page=N | none | clamp=N`（DEBUG 命中/缺失/钳制）

### 3.2 `routes.py` 改动

新增路由 `@bp.route("/api/reading-progress", methods=["POST"])`：
- 解析 `request.get_json(silent=True)` 的 `page`，非整数返回 400（不写文件）。
- 调用 `state.save_reading_progress(page)`：
  - `ValueError("no document opened")` → 400 `{"error": "no document opened"}`
  - `ValueError("page out of range")` → 400 `{"error": "page out of range"}`
- 成功 → `{"ok": True}`，HTTP 200。
- 日志 `logger.debug("[route] save-reading-progress page=%d", page)` 与既有风格一致；失败用既有 `error_response`。

> 不新增 `GET /api/reading-progress`：`/api/open` 响应已携带 `saved_page`，减小接口面（与 spec 一致：spec 未要求独立 GET）。

## 4. 前端组件（`static/app.js`）

### 4.1 打开后恢复定位

`openPdf()` 内，在现有页占位构建（`createPageEl` 循环）完成、`setupIntersectionObserver`/`setupScrollSync`/`setupPageDetection` 装配之后：

```js
const saved = Number.isInteger(data.saved_page) ? data.saved_page : null;
if (saved !== null && saved >= 0 && saved < pageCount) {
    requestAnimationFrame(() => scrollToPage(saved)); // 等 settle/rAF 占位高度就绪
}
```

`scrollToPage(index)` helper：
- 取左列 `els.leftCol.querySelector('.page-container[data-page="<index>"]')`。
- 调用 `el.scrollIntoView({block:'start'})`（占位已带正确 `--page-ratio` 高度，定位准）。
- 触发后由现有 `setupPageDetection` 回调 `onPageChange` 刷新 `currentPage` 与 `els.pageIndicator`（无需手动设指示）。
- `saved` 为 null/0/无效时不主动定位（停顶部首页），不报错。

> 右列由现有 `setupScrollSync` 自动镜像，无需单独滚动右列。

### 4.2 卸载期上报

在 `openPdf` 成功并初始化完成后注册监听，并把 `currentPage`/`pageCount` 用闭包变量或模块级变量供上报读取：

- 主：`window.addEventListener('pagehide', saveProgress)`（covers 桌面/移动端 unload 与 bfcache）。
- 兜底：`document.addEventListener('visibilitychange', () => { if (document.hidden) saveProgress(); })`（后台标签也触发；先后触发靠后写覆盖先写，页码相同无害）。
- 重开新文档时：先 `removeEventListener` 上一份监听再注册新一份，防重复绑定（**不**保存旧文档——已确认切档不保存）。

`saveProgress()`：
```js
function saveProgress() {
  if (!pageCount || !Number.isInteger(currentPage)) return;
  if (currentPage < 0 || currentPage >= pageCount) return;
  const body = JSON.stringify({ page: currentPage });
  const blob = new Blob([body], { type: 'application/json' });
  if (navigator.sendBeacon) {
    navigator.sendBeacon(`${API}/reading-progress`, blob);
  } else {
    fetch(`${API}/reading-progress`, {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body, keepalive: true
    }).catch(() => {});
  }
}
```
- 不阻塞卸载、不依赖 Promise 解析。
- `navigator.sendBeacon` 优先，`keepalive` fetch 兜底（轴 2 决策 A 主 B 兜底）。

### 4.3 teardown 与 lifecycle

- `zoomInst`/`io`/`settle` 现有的 dispose 逻辑保留。
- 新增 progress 监听的 teardown：在 `openPdf` 入口（重开新文档时）先解绑上一份 `pagehide`/`visibilitychange` 监听，再注册新一份，避免累积绑定写错 hash（实际接口按当前 `pdf_hash` 写，但解绑保持一致性）。

## 5. 并发、原子性与回滚

- 写进度：`self._lock` 串行化；`.tmp` + `os.replace` 原子替换，杜绝半写损坏。
- 读进度：与打开同事务，自然钳制"进度页码 vs 当前 page_count"。
- 多标签同开同文档：`_lock` 串行，最后写者赢，页码相近可接受。
- 回滚：删除新增路由/方法与前端监听即可；既有进度文件无危害可保留或删。

## 6. 风险与取舍

| 风险 | 处理 |
|------|------|
| 卸载期断电/强杀丢最新页 | 已确认接受（仅卸载保存、切档不保存） |
| 进度文件被外部篡改/损坏 | 读取端吞异常返回 `None`，绝不抛路由 |
| 文档替换但路径不变 | hash 变即新文档，从第1页开始，无需迁移 |
| `sendBeacon` 体积/频率限制 | 单次小 JSON，仅在卸载期发一次，远低于限额 |
| 懒加载占位高度未撑开致定位偏移 | `rAF` + `scrollIntoView` 而非像素计算；占位带正确 `--page-ratio` |
| 双重 `pagehide`+`visibilitychange` 触发 | 后写覆盖前写，页码相同无害，无需去重 |

## 7. 测试策略

**后端**
- `tests/test_state.py`：
  - `save_reading_progress` 正常落盘 / 文档未开抛错 / 越界抛错 / 原子写（中途断言 tmp 不残留）。
  - `load_reading_progress` 命中 / 缺失返回 None / 损坏 JSON 返回 None / 越界钳制 0。
  - `open_pdf` 响应含 `saved_page`（无记录为 None；有记录为 int）。
- `tests/test_routes.py`：
  - `POST /api/reading-progress` 成功返回 `{"ok":true}` / 未开文档 400 / 越界 400 / 非整数页 400。
  - 校验文件确实落盘且格式正确。
  - `/api/open` 响应 schema 含 `saved_page` 字段。

**前端**
- 本项目当前无 JS 测试框架 → design doc 备注手动验证脚本：
  1. 启动 app，打开一本 PDF，滚到第 N（如 8）页。
  2. 关闭标签页。
  3. 重新访问 app，打开同一 PDF。
  4. 断言：左右列自动滚动到第 8 页占位顶部，页码指示显示 `Page 9`（saved_page+1）。
  5. 边界：首次打开的新 PDF 停在第1页；进度越界降级到第1页；切换文档不报错。
- 若后续引入前端测试框架，可单列任务补 `saveProgress` 守卫与 `scrollToPage` 行为用例。

> 已执行验证（实现期）：见 `docs/superpowers/plans/2026-06-27-reading-position-resume.md` Task 3.3 / Task 4.5 步骤；通过判定为左右列自动滚到目标页顶部、`page-indicator` 显示 `Page (saved_page+1)`；首次打开新 PDF 停首页；越界降级首页；切换文档无额外 save 请求、无控制台报错。

**质量门**
- `ruff check .`、`ruff format --check .`、`pytest -q` 全绿后方可进入 verify 阶段。

## 8. 实现顺序建议

与 `tasks.md` 分组对应：①后端 state 持久化读写 → ②后端路由 → ③前端恢复定位 → ④前端卸载上报（含 teardown）→ ⑤测试与质量校验。每完成一组提交一次，提交信息体现设计意图。
