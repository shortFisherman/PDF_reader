## Why

`AppState` 的线程安全存在三处竞态/阻塞缺陷：`render_page` 在锁外渲染（`get_doc` 取锁返回 doc 后才 render，与 `replace_page` 并发会读到被关闭/替换的 doc）；`replace_page` 在锁内做 `save`/`os.replace`/reopen 慢磁盘 IO，阻塞所有读操作且并发翻译不同页会互相破坏 `right.pdf`；`/api/translate/<page>` 无页码范围校验，越界页会触发 `pymupdf` 异常。这些是逻辑正确性缺陷，应在重构结构前先修复，并以此建立 TDD 安全网。

## What Changes

- 修复 `state.py:render_page` 竞态：渲染全过程持有锁（或对 doc 取稳定快照），确保翻译替换页面期间并发渲染不会读到半保存/已关闭的 `pymupdf.Document`
- 修复 `state.py:replace_page` 锁内慢 IO 阻塞：将 `save`/`os.replace`/reopen 的磁盘 IO 移出临界区，临界区只保护内存状态切换；采用原子替换（写临时文件 → `os.replace`）保证 `right.pdf` 不会因并发翻译不同页而损坏
- 为并发翻译不同页提供隔离：同一 `right.pdf` 的页替换串行化，避免两个翻译线程同时 save/replace 导致文件交错损坏
- 为 `/api/translate/<int:page>` 增加页码范围校验：越界页返回 400 而非触发底层异常
- 为以上每项缺陷先补特征测试（TDD），再修复使测试通过；现有 45 个测试保持全绿

## Capabilities

### New Capabilities

无。本变更是对现有行为的正确性加固，不引入新能力。

### Modified Capabilities

- `code-quality-foundations`: 强化"线程安全全局状态访问"需求——当前 `render_page` 在锁外渲染违反了该需求；需明确渲染与页替换的并发安全契约，并禁止锁内执行慢磁盘 IO
- `pdf-rendering`: 新增并发安全渲染需求——翻译替换某页期间，对其他页（或同页）的并发渲染请求 SHALL 不读到被关闭或半保存的文档
- `page-translation`: 新增页码范围校验需求——翻译越界页 SHALL 返回 400 错误而非底层异常；新增并发翻译隔离需求——同一 `right.pdf` 的页替换 SHALL 串行化
- `translation-output-isolation`: 强化 `right.pdf` 写入需求——页替换 SHALL 使用原子写（临时文件 + `os.replace`），并发翻译不同页 SHALL 不互相损坏 `right.pdf`

## Impact

- **代码**：`state.py`（`render_page`/`replace_page`/可能新增页级锁或读写锁）、`routes.py`（`translate_page` 增加页码校验）
- **API**：`/api/translate/<page>` 对越界页返回 400（此前是 500/异常）；其余 `/api/*` 契约不变
- **依赖**：无新增第三方依赖
- **测试**：新增并发渲染、并发翻译隔离、页码校验测试；现有测试保持通过
- **风险**：锁粒度调整需避免死锁；临界区缩小后需保证内存状态与磁盘文件一致性
