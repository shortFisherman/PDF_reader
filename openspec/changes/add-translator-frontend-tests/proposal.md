# Proposal: add-translator-frontend-tests

## Why

前端翻译编排模块 `static/modules/translator.js`（`translateCurrentPage`）与 SSE 解析模块 `static/modules/sse-client.js`（`readSSEStream`）目前**无测试覆盖**（CodeGraph 已标注 ⚠️ no covering tests）。这是最易回归的前端逻辑：回调时序（onProgress→onStageChange→onFinish/onError）、错误兜底、SSE 事件解析。项目已在 `package.json` 装了 `jsdom` devDep，但 `.mjs` 测试仅覆盖 lazy-loader/task-4.x。本变更新增覆盖 translator 与 sse-client 的 jsdom 测试。

## What Changes

- 新增 jsdom 测试覆盖 `translateCurrentPage`：成功路径（progress→stage→finish 回调时序）、错误事件路径（onError 调用）、HTTP 非 ok 路径（`resp.ok` false → throw → onError）、自定义 prompt 透传 body。
- 新增 jsdom 测试覆盖 `readSSEStream`：`data: {json}\n\n` 多事件解析、单行分片跨 chunk 拼接、非法 JSON 行跳过不抛、`done` 结束。
- 接入 `tests/` 前端测试运行配置（复用现有 `run-*.mjs` 模式或新建 `run-translator-tests.mjs`）。
- 在 `package.json` 加 `test:translator`（或更新 `test`）脚本便于本地与后续 CI 执行。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `frontend-modular-architecture`: `translator` 与 `sse-client` 模块 SHALL 有自动化测试覆盖核心回调时序与 SSE 解析行为。

## Impact

- **代码**：新增 `tests/` 下前测 `.mjs` 文件与运行脚本；`package.json` 脚本更新。
- **依赖**：复用已装 `jsdom`；可能需在 CI（`add-ci-and-lint-cleanup`）中补充 `npm test` 步骤（属后续变更，本变更先确保本地可跑）。
- **风险**：要让 ES Module import 在 Node+jsdom 下可跑，需确认现有 `.mjs` 测试的运行方式并沿用，避免引入构建工具（项目「无框架无构建」约束）。