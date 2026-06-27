## Context

PDF_reader 是一个本地 Flask 应用：`state.py` 的 `AppState.open_pdf` 已对每本 PDF 计算 SHA-256 `pdf_hash`，并在 `cache_dir/<pdf_hash>/` 下缓存 `right.pdf`、术语表等。前端 `static/app.js` 的 `currentPage` 是纯内存 JS 变量，`onPageChange(state` 来自 `setupPageDetection` 的滚动检测。当前关闭/重开丢页。本次在既有 hash 缓存目录上叠加一个进度文件，打通"打开→恢复 / 卸载→保存"闭环。

涉及模块：`state.py`、`routes.py`、`static/app.js`（必要时新增极小 helper）。无现有 spec 的行为被修改——这是纯新增能力（见 `specs/reading-position-resume/spec.md`）。

## Goals / Non-Goals

**Goals:**
- 打开曾阅读的 PDF 时按 `saved_page` 自动跳回上次的页码，零额外操作。
- 进度按 PDF 内容哈希存放，跨浏览器/重装有效（仅清 cache 失效）。
- 卸载时可靠落盘，使用浏览器原生 `sendBeacon` 避免请求被取消。
- 越界页码安全降级，绝不因进度文件损坏或页码越界而崩溃。

**Non-Goals:**
- 不恢复缩放、页内滚动偏移。
- 不做跨设备/云端同步。
- 不做多文档并行进度（单文档一次）。
- 不弹"是否继续"询问弹窗。
- 不改变翻译/雪花缓存/双栏/术语表等既有能力。

## Decisions

### 1. 进度文件位置与格式
**决定**：`cache_dir/<pdf_hash>/reading_progress.json`，内容 `{"page": <0-based int>}`。

**理由**：`state.py` 的 `open_pdf` 已在 `cache_dir / pdf_hash` 下 `mkdir` 并复用缓存；进度文件天然挂在同一目录，随缓存一起被清理/迁移，生命周期与文档缓存一致，无需新建表或新目录树。

**备选**：① خدمة端 SQLite/集中 json 索引文件（多一层查询与锁，过度工程）；② 前端 `localStorage`（换浏览器/清缓存即丢，不满足"跨重装"目标）。均否决。

### 2. 进度读写时机
**决定**：
- **读**：在 `AppState.open_pdf` 成功打开文档后，同步读取该 hash 目录下进度文件；将越界值钳制为 0；返回值并入 `open_pdf` 现有返回 dict 的新字段 `saved_page`（无记录时为 `None`）。
- **写**：新增独立 `POST /api/reading-progress` 接口而非复用 `/api/open`。写操作在 `AppState` 的新方法（如 `save_reading_progress(page)`）内执行，复用 `self._lock` 与 `self._pdf_hash`/`self._page_count`，越界直接抛错由路由转 400。

**理由**：读与打开同事务自然钳制了"进度页码 vs 当前 page_count"；写走独立接口避免热路径调用，并被前端 `sendBeacon` 在卸载时轻量发起。

**备选**：仅前端 `localStorage` + 打开时再回传保存（无服务端持久，已否决）。

### 3. 前端上报通道
**决定**：监听 `pagehide`（主）与 `visibilitychange`（hidden 兜底），用 `navigator.sendBeacon('/api/reading-progress', blob)` 上报 `application/json` 体 `{"page": currentPage}`。

**理由**：卸载期间普通 `fetch` 可能被浏览器 abort；`sendBeacon` 专为非阻塞卸载期上报设计，在后台标签也会触发。`pagehide` 同时覆盖桌面/移动端；`visibilitychange=hidden` 作为双保险（部分场景先后触发，靠后写覆盖先写无害，因为是同一页码）。

**备选**：① 仅 `beforeunload`（移动端不可靠且 `fetch` 易丢）；② 翻页实时节流保存（被 Non-Goal 否决——本次仅卸载时保存）。

### 4. 打开后的恢复定位
**决定**：`/api/open` 响应追加 `saved_page`。前端 `openPdf` 在 DOM 页占位构建完成后，若 `saved_page` 为有效整数，调用与滚动同步同源的滚动 API 把左列定位到第 `saved_page` 个 `.page-container` 顶部，随后由现有 `setupPageDetection` 回调刷新 `currentPage`/`els.pageIndicator`。若 `saved_page` 为 `null`/0/越界则不定位（停在顶部即第 1 页）。

**理由**：复用既有 IntersectionObserver 懒加载与页检测机制，定位后该页会自动触发懒加载，无新渲染路径。

**风险**：懒加载占位高度使用 `--page-ratio`，垂直 scrollTo 在所有占位就位前可能不准 → 采用 `scrollIntoView({block:'start'})`（占位已带正确高度）而非计算像素偏移。

### 5. 保存的守卫
**决定**：前端在 `pagehide` 时仅在 `pageCount > 0` 且 `currentPage ∈ [0, pageCount)` 才发请求；后端在接口侧再次校验"文档已打开 + 页码越界"，前后双层校验。

**理由**：防御无效/越界写入造成脏进度文件；后端 `save_reading_progress` 用 `self._lock` 保证并发安全。

## Risks / Trade-offs

- **[卸载期上报被极端场景吞掉]**（如直接断电）→ 本次接受这一极小丢失窗口，符合已确认的"仅卸载时保存"方案；未来如需更准可平滑加"翻页节流保存"扩展。
- **[进度文件被外部篡改/损坏]** → 读取处用 `try/except`，解析失败视为无记录（`saved_page=None`），绝不抛到路由。
- **[文档被替换但路径相同、hash 变]** → 进度按 hash 存，新 hash 自然从第 1 页开始，符合"内容变即视为新文档"的预期，无需迁移。
- **[cache 目录被整体清空]** → 进度随缓存一同丢失，等同首阅，符合预期。
- **[sendBeacon 体积/频率限制]** → 单次小 JSON，仅在卸载期发一次，远低于浏览器限额。
- **[多标签同时打开同一文档]** → 后端写由同一 `AppState` 串行化；并发最后写者赢，页码相近，可接受。

## Migration Plan

纯新增，无破坏性变更，无数据迁移：
1. 后端新增进度文件读写与路由（`state.py`、`routes.py`）。
2. 前端 `app.js` 加载、定位、卸载上报逻辑。
3. 老的 `cache_dir/<hash>/` 目录自动在下次打开时按需新增进度文件；不存在的进度文件按"无记录"处理，向后兼容。
4. 回滚：删除新增路由与前端监听即可，已有进度文件无危害，可保留或删除。

## Open Questions

(无) 需求与方案已在澄清阶段确认闭环；实现期若发现 `setupPageDetection` 的回调时机需要配合定位，由 build 阶段细调。