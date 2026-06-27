# Comet Design Handoff

- Change: reading-position-resume
- Phase: design
- Mode: compact
- Context hash: 3e0cce56d4416dc9c0c33661b9a190cfc096eed83070f58ae338736ec4240cd4

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/reading-position-resume/proposal.md

- Source: openspec/changes/reading-position-resume/proposal.md
- Lines: 1-27
- SHA256: 5a37d340dd8310d4abac1d7f2c6d375cf08c58d28e8cc82e4601fefa5d6dde03

```md
## Why

用户在关闭 PDF 阅读器后再次打开同一文档时，总是从头从第 1 页开始，需要手动翻回到上次阅读的位置。对外文翻译阅读场景，这一步常意味着连续翻 8、20 甚至上百页，体验割裂。本次变更让阅读器记住每个文档上次停下的页码，并在重新打开时自动跳回。

## What Changes

- 新增"阅读进度持久化"能力：在服务端按 PDF 内容哈希（已有的 `pdf_hash`）把上次阅读页码写入 `cache_dir/<hash>/` 下，使其跨浏览器、跨重装仍然有效。
- `state.py` 在 `open_pdf` 时返回上次保存的页码（如有），并对越界值做钳制降级。
- `routes.py` 新增保存进度的 HTTP 接口，供前端在页面隐藏/卸载时上报当前页码。
- 前端 `static/app.js` 打开文档后读取并自动滚动到上次页码；在页面隐藏/卸载时通过 `navigator.sendBeacon` 上报当前页码。
- 恢复粒度仅页码（不含缩放、不含页内滚动偏移）；恢复方式为自动直接跳转（无询问弹窗）。

## Capabilities

### New Capabilities
- `reading-position-resume`: 记录并恢复单本 PDF 上次阅读页码的能力。按 PDF 内容哈希持久化在服务端 cache 目录，打开文档时自动跳回，关闭/卸载时上报保存。

### Modified Capabilities
<!-- 本次为纯新增能力，不修改任何现有 spec 的 requirement -->
(none)

## Impact

- **后端代码**：`state.py`（新增进度文件读写、`open_pdf` 返回 `saved_page`）、`routes.py`（新增 `POST /api/reading-progress` 与 `GET /api/reading-progress` 路由）。
- **前端代码**：`static/app.js`（打开后定位、页面隐藏/卸载时上报），可能新增少量 helper。
- **存储**：每本 PDF 的 `cache_dir/<hash>/` 下新增进度文件（极小 JSON）。
- **依赖**：无新增第三方依赖；前端使用浏览器内置 `navigator.sendBeacon` / `visibilitychange`。
- **不影响**：翻译流程、雪花缓存、双栏渲染、缩放、术语表等现有能力的对外行为。```

## openspec/changes/reading-position-resume/design.md

- Source: openspec/changes/reading-position-resume/design.md
- Lines: 1-77
- SHA256: 62b0cb80d3fa33009c2f9855bc4da3b1ef1c91af536a8b63c6dda01788e2f3a3

```md
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

(无) 需求与方案已在澄清阶段确认闭环；实现期若发现 `setupPageDetection` 的回调时机需要配合定位，由 build 阶段细调。```

## openspec/changes/reading-position-resume/tasks.md

- Source: openspec/changes/reading-position-resume/tasks.md
- Lines: 1-36
- SHA256: 9dc745b945640ae130ffa3c8b8bc2f89658caf82a2845ff913dc66a5b7a36f6e

```md
## 1. 后端：进度持久化与读取（state.py）

- [ ] 1.1 在 `AppState` 新增私有属性 `_reading_progress_path` 派生（由 `glossary_cache_path` 同源逻辑）或私有方法 `_reading_progress_path()`，返回 `cache_dir/<pdf_hash>/reading_progress.json` 或 `None`
- [ ] 1.2 新增 `AppState.save_reading_progress(page: int) -> None`：在 `self._lock` 内校验文档已打开（无则抛 `ValueError`），校验 `0 <= page < self._page_count`（越界抛错），原子写入进度文件（`tmp` + `os.replace` 保证不被半写损坏）
- [ ] 1.3 新增 `AppState.load_reading_progress() -> int | None`：在锁内读取对应 hash 目录进度文件；解析失败/文件缺失返回 `None`；对越界（`>= page_count`）钳制为 0
- [ ] 1.4 在 `open_pdf` 成功打开后调用 `load_reading_progress()`，把 `saved_page`（钳制后整数或 `None`）并入返回 dict
- [ ] 1.5 在 `open_pdf` 开始的 `_close_docs`/重置路径确认进度读写不被误清（进度文件独立于 `right.pdf`，不应被删除）
- [ ] 1.6 按 `logging_config.py` 既有 `getLogger("pdf_reader.state")` 命名空间，在保存/读取/钳制处加 INFO/DEBUG 日志（如 `[progress] save page=N`、`[progress] load page=N clamp=c`），不输出敏感信息

## 2. 后端：HTTP 接口（routes.py）

- [ ] 2.1 新增 `POST /api/reading-progress`：解析 JSON `page`，仅整数；调用 `state.save_reading_progress(page)`，`ValueError("no document opened")` → 400、越界 → 400 "page out of range"，成功返回 `{"ok": true}`，并加 `logger.debug("[route] save-reading-progress page=%d", page)`
- [ ] 2.2 （可选/对齐）确认 `POST /api/open` 响应已带 `saved_page`（随 1.4 落地，无新增路由）；如后续需独立查询再加 `GET /api/reading-progress`，本次默认不加以减小面
- [ ] 2.3 路由命名/日志沿用 `logger = logging.getLogger("pdf_reader.routes")` 现有风格

## 3. 前端：打开后恢复定位（static/app.js）

- [ ] 3.1 `openPdf` 内读取响应 `data.saved_page`；若为有效整数且在 `[1, pageCount]` 之间，在页占位 DOM 构建完成、Observer/页面检测 setup 之后做定位
- [ ] 3.2 实现 `scrollToPage(index)` helper：定位左列第 `index` 个 `.page-container`，优先 `el.scrollIntoView({block:'start'})`；定位后由现有 `setupPageDetection` 回调刷新 `currentPage`/`els.pageIndicator`
- [ ] 3.3 定位使用 `requestAnimationFrame`/settle gate 等待占位高度就绪后再执行，避免懒加载占位未撑开导致定位偏移
- [ ] 3.4 `saved_page` 为 `null`/0/无效时不主动定位（保持顶部首页），不报错
- [ ] 3.5 恢复后可选地短暂提示页码（沿用 `els.pageIndicator`，不弹窗，符合 spec）

## 4. 前端：卸载期上报（static/app.js）

- [ ] 4.1 在 `openPdf` 成功并初始化完成后注册 `pagehide` 监听；保存当前 `currentPage` 与 `pageCount` 到用于上报的闭包变量
- [ ] 4.2 加 `visibilitychange`（`document.hidden`）兜底监听，触发同一 `saveProgress` 函数
- [ ] 4.3 `saveProgress()`：仅当文档已打开、`pageCount > 0`、`currentPage ∈ [0, pageCount)` 且 `navigator.sendBeacon` 可用时，用 `application/json` Blob 发起 `POST /api/reading-progress`，body `{"page": currentPage}`
- [ ] 4.4 重开新文档时清理上一份监听，避免重复注册/误写旧 hash 的进度（保存接口按当前 `pdf_hash` 写，重复监听本身不致错乱，但应一致地 teardown）
- [ ] 4.5 上报不阻塞卸载、不依赖 Promise 解析

## 5. 测试与质量校验

- [ ] 5.1 `tests/test_state.py`：覆盖 `save_reading_progress` 正常落盘、文档未开抛错、越界抛错、文件原子写入；`load_reading_progress` 命中/缺失/损坏/越界钳制；`open_pdf` 响应含 `saved_page`
- [ ] 5.2 `tests/test_routes.py`：`POST /api/reading-progress` 成功/未开文档/越界分支；`/api/open` 响应 schema 含 `saved_page`
- [ ] 5.3 视情况为前端恢复/上报补最小化 DOM/事件测试（若项目无前端测试框架则记录手动验证脚本并归档至 design.md 备注）
- [ ] 5.4 运行 `ruff check .`、`ruff format --check .`、`pytest -q` 全绿后再进入 verify 阶段```

## openspec/changes/reading-position-resume/specs/reading-position-resume/spec.md

- Source: openspec/changes/reading-position-resume/specs/reading-position-resume/spec.md
- Lines: 1-60
- SHA256: 15e92138756f3e2fcbf7f82b0f91cbfae5dade9e51dabded2a8ee6b1fe4bab95

```md
## ADDED Requirements

### Requirement: 服务端按 PDF 内容哈希持久化阅读页码
系统 MUST 在服务端按 PDF 的内容哈希（既有 `pdf_hash`）记录每本文档上次阅读到的页码（0 基索引），存放在该文档已有的 `cache_dir/<pdf_hash>/` 目录下，使其在不同浏览器、清缓存以外的场景下跨会话保留。

#### Scenario: 打开曾阅读过的文档自动恢复页码
- **WHEN** 用户打开一本此前阅读过且 cache 目录中存在进度记录的 PDF
- **THEN** `POST /api/open` 的响应 MUST 包含 `saved_page` 字段（0 基整数），其值为上次保存的页码
- **AND** 前端 MUST 自动滚动定位到该页码对应的页占位，并将页码指示更新为 `Page (saved_page + 1)`

#### Scenario: 进度越界安全降级
- **WHEN** 进度文件中保存的页码大于或等于当前打开文档的 `page_count`
- **THEN** 系统 MUST 将 `saved_page` 钳制为 0（即第 1 页），不得抛出异常或越界跳转

#### Scenario: 首次打开的新文档无默认页码
- **WHEN** 用户打开一本 cache 目录中不存在进度记录的 PDF
- **THEN** `POST /api/open` 响应 MUST 不返回有效的 `saved_page`（缺失或为 `null`）
- **AND** 前端 MUST 停留在第 1 页，不触发任何恢复跳转

### Requirement: 前端在页面隐藏/卸载时上报当前页码
前端 MUST 在阅读器处于打开文档状态时，监听页面隐藏/卸载事件，并通过 `navigator.sendBeacon` 向保存接口上报当前页码，以最小化数据丢失窗口且不被浏览器取消。

#### Scenario: 关闭标签页时保存当前页码
- **WHEN** 文档已打开且用户关闭标签页或浏览器，触发 `pagehide`/`visibilitychange`（hidden）
- **THEN** 前端 MUST 通过 `navigator.sendBeacon` 发起一次 `POST /api/reading-progress`，请求体记录当前 `currentPage`
- **AND** 该上报 MUST 不阻塞页面卸载

#### Scenario: 未打开文档时不发起保存
- **WHEN** 触发卸载事件但当前没有打开的文档（无 `pdf_hash`）
- **THEN** 前端 MUST 不发起保存请求

#### Scenario: 仅保存有效页码
- **WHEN** 当前页码为非整数或超出 `[0, page_count)` 区间
- **THEN** 前端 MUST 不发起保存请求

### Requirement: 保存进度接口按 hash 越界校验
`POST /api/reading-progress` MUST 仅在当前文档已打开（存在 `pdf_hash`）时接受保存，将页码写入对应 hash 的 cache 目录进度文件；对越界页码拒绝并返回错误。

#### Scenario: 保存有效页码
- **WHEN** 已打开文档且上报页码 `page` 满足 `0 <= page < page_count`
- **THEN** 系统 MUST 把该页码持久化到 `cache_dir/<pdf_hash>/` 下进度文件并返回成功
- **AND** 进度文件 MUST 为可被后续 `open_pdf` 读取的格式

#### Scenario: 未打开文档时拒绝保存
- **WHEN** 调用保存接口但当前没有打开的文档
- **THEN** 系统 MUST 返回错误（HTTP 400 "no document opened"）

#### Scenario: 越界页码拒绝
- **WHEN** 上报页码超出 `[0, page_count)` 区间
- **THEN** 系统 MUST 返回错误（HTTP 400 "page out of range"），且不写文件

### Requirement: 恢复粒度与方式限定
本能力 SHALL 仅恢复页码粒度，MUST 不恢复缩放级别或页内滚动偏移；恢复方式 MUST 为打开后自动直接跳转，不弹询问弹窗、不要求用户确认。

#### Scenario: 恢复时不重放缩放
- **WHEN** 上次阅读时调整过缩放，重新打开并恢复页码
- **THEN** 前端 MUST 以默认缩放（100%）展示该页，不恢复上次的缩放值

#### Scenario: 恢复时无确认弹窗
- **WHEN** 自动定位到上次页码
- **THEN** 界面 MUST 不出现询问/确认弹窗，仅可选地短暂提示已跳转到的页码```

