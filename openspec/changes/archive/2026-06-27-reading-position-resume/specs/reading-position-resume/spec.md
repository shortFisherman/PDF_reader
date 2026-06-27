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
- **THEN** 界面 MUST 不出现询问/确认弹窗，仅可选地短暂提示已跳转到的页码