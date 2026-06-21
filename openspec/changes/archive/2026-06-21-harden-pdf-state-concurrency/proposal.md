## Why

`AppState` 的线程安全存在两处真实缺陷：`render_page` 在锁外渲染（`get_doc` 取锁返回 doc 后才 render，与 `replace_page` 并发会读到被关闭/替换的 doc）；`/api/translate/<page>` 无页码范围校验，越界页会触发 `pymupdf` 异常。这些是逻辑正确性缺陷，应修复，并以此建立 TDD 安全网。

> **Debug gate 修正**：初始设计还假设 `replace_page` 存在"锁内慢 IO 阻塞"与"并发翻译不同页损坏 right.pdf"问题。实现阶段的 systematic-debugging 调查发现原代码 `replace_page` 已全程持主锁、已是并发安全的串行实现，且 Windows 上 `os.replace` 无法替换被打开的文件。故回退 `replace_page` 到原实现，变更范围简化为渲染竞态修复 + 页码校验。

## What Changes

- 修复 `state.py:render_page` 竞态：渲染全过程持有锁，确保翻译替换页面期间并发渲染不会读到半保存/已关闭的 `pymupdf.Document`
- 为 `/api/translate/<int:page>` 增加页码范围校验：越界页返回 400 而非触发底层异常
- 为以上每项缺陷先补特征测试（TDD），再修复使测试通过；现有 45 个测试保持全绿
- 保留并发 replace 不同页测试作为回归保护（验证原代码的串行化正确性）

## Capabilities

### New Capabilities

无。本变更是对现有行为的正确性加固，不引入新能力。

### Modified Capabilities

- `code-quality-foundations`: 强化"线程安全全局状态访问"需求——当前 `render_page` 在锁外渲染违反了该需求；需明确渲染持锁全程的并发安全契约
- `pdf-rendering`: 新增并发安全渲染需求——翻译替换某页期间，对其他页（或同页）的并发渲染请求 SHALL 不读到被关闭或半保存的文档
- `page-translation`: 新增页码范围校验需求——翻译越界页 SHALL 返回 400 错误而非底层异常

## Impact

- **代码**：`state.py`（`render_page` 持锁）、`routes.py`（`translate_page` 增加页码校验）
- **API**：`/api/translate/<page>` 对越界页返回 400（此前是 200/异常）；其余 `/api/*` 契约不变
- **依赖**：无新增第三方依赖
- **测试**：新增渲染竞态、页码校验测试；并发 replace 回归测试；现有测试保持通过
- **风险**：渲染持锁阻塞 replace（10-50ms，单用户可接受）
