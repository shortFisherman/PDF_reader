# 验证报告：fix-translate-refresh-wrong-page

**日期**: 2026-06-25  
**变更类型**: hotfix  
**验证模式**: light（3 任务，0 delta spec，1 实现文件）

## 问题摘要

翻译完成后右侧 PDF 闪烁但被翻译的页面未被译文替换。根因：`onFinish` 回调使用模块级可变变量 `currentPage` 定位刷新目标，而用户在翻译等待期间滚动后 `currentPage` 已指向新的可见页，导致刷新了错误页面。

## 修复内容

`static/app.js` `onTranslateClick` 函数（+1 行快照，2 处 `currentPage`→`targetPage`，+2 行 `dataset.loaded` 守卫）：

1. 入口处 `const targetPage = currentPage;` 快照翻译目标页
2. `translateCurrentPage(targetPage, ...)` 和 `onFinish` 中 `querySelector` 均使用 `targetPage`
3. `onFinish` 增加 `if (rightEl.dataset.loaded === 'true')` 守卫：仅对已加载图片执行 unload+load；已卸载页面（用户滚远）仅标记 `translated`，由 lazy-loader 在用户滚回时自动加载译文版本

## 6 项轻量验证结果

| # | 检查项 | 结果 | 证据 |
|---|--------|------|------|
| 1 | tasks.md 全部 `[x]` | PASS | 未勾选 0，已勾选 3 |
| 2 | 变更文件与 tasks 描述一致 | PASS | 仅 `static/app.js`（11 行），匹配 task 1-2 描述 |
| 3 | 构建通过 | PASS | `pytest -q`：127 passed, 5 warnings（SWIG 弃告警，既有） |
| 4 | 相关测试通过 | PASS | translator 30/30, task-4.4 16/16, task-4.5 29/29 |
| 5 | 无安全问题 | PASS | 无硬编码密钥，无新增不安全操作，`targetPage` 为数值页码 |
| 6 | 轻量代码审查 | PASS | 见下方详细审查 |

## 轻量代码审查（正确性 / 安全 / 边界）

### 正确性
- `targetPage` 在翻译启动时快照 `currentPage`，整个生命周期使用固定值 ✅
- `onFinish` 用 `targetPage` 定位页面容器，刷新正确的被翻译页 ✅
- `classList.add('translated')` 在 loaded 守卫之外，无论图片是否已加载都标记译文状态 ✅
- `loadTranslatedState()` 仍正常运行，同步所有已翻译页 ✅

### 安全
- `targetPage` 为整数页码，来源于 `onPageChange(pageNum)`，无注入风险 ✅
- 无新增网络请求、无硬编码密钥、无不安全操作 ✅

### 边界场景
- **用户未滚动**：`targetPage === currentPage`，行为与修复前一致 ✅
- **用户滚动到其他页**：`targetPage` 是被翻译页，刷新正确页面 ✅
- **用户滚远（图片已卸载 loaded='false'）**：跳过 unload+load，仅标记 `translated`；用户滚回时 lazy-loader 以新时间戳请求，后端返回译文 ✅
- **翻译出错**：`onError` 而非 `onFinish`，不触发刷新 ✅
- **rightEl 为 null**：`if (rightEl)` 守卫处理 ✅
- **loaded='true' 但远离视口**：仍执行 reload（图片已加载，刷新内容）；lazy-loader 后续可能卸载，不影响正确性 ✅

## 结论

**验证结果：PASS** — 全部 6 项检查通过，无 CRITICAL 或 IMPORTANT 问题。修复正确消除根因，覆盖用户报告的场景及极端滚动场景。
