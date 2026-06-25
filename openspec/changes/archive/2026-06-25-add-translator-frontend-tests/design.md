# Design: add-translator-frontend-tests

## Context

前端为原生 ES Module，无构建工具。现有 `.mjs` 测试（`tests/run-task-4.x-tests.mjs`、`run-lazy-loader-tests.mjs`）已确立运行模式：用 Node 直接跑 ESM、jsdom 提供浏览器环境。`translator.js` 依赖 `fetch`、`getStageLabel`；`sse-client.js` 依赖 `response.body.getReader()` + `TextDecoder`。需在 jsdom 下提供这些 API 的桩/mock。

## Goals / Non-Goals

**Goals:**
- 测试覆盖 `translateCurrentPage` 的回调时序与错误路径。
- 测试覆盖 `readSSEStream` 的 SSE 行解析与分片拼接。
- 接入成功路径，可在本地 `node tests/run-translator-tests.mjs`（或经 package.json 脚本）一键运行；保持退出码语义（失败非零）以便后续 CI。
- 不改被测模块（`translator.js`/`sse-client.js`）的源码。

**Non-Goals:**
- 不测 `app.js`、`scroll-sync`、`lazy-loader`、`dom.js`、`stages.js`（部分已覆盖或超出范围）。
- 不引入 vitest/jest 等测试框架（保持原生 ESM + 断言函数）。
- 不在此变更接入 CI（属 `add-ci-and-lint-cleanup` 后续补充 npm 步骤）。

## Decisions

### 决策 1：沿用现有 `.mjs` 直跑模式
参考 `run-task-4.x-tests.mjs` 用动态 `import()` 加载被测 ESM，jsdom 提供 `fetch`/`Response`/`ReadableStream` polyfill。手写极简断言（assert + 失败计数 + 退出码）。
- 替代方案：引入 vitest → 否决（违反无构建/无框架原则，且增依赖）。

### 冶策 2：mock `fetch` 与 `Response`/`body`
为 `translateCurrentPage` 构造一个返回 `Response` 的 `fetch`，`response.body` 为手构造的 `ReadableStream`（按 SSE chunk 推入）、`response.ok` 可控、`response.json` 在错误路径返回 `{error}`。`getStageLabel` 通过真实 `stages.js`（其内部从后端拉取，测试中先注入本地 labels）或直接 mock。
- 处理 `getStageLabel`：在测试中 mock `./stages.js` 的导入较难（ESM 静态导入），改为让测试在调用前先填充 stages 模块的本地缓存（若有 `setStageLabels` 之类接口）；若无，则在测试中直接断言 `onStageChange` 收到的 stage 名而不断言 label 文案，绕开对后端的依赖。

### 决策 3：测试组织
新建 `tests/run-translator-tests.mjs`（可拆为 `run-translator-tests.mjs` + `run-sse-client-tests.mjs`，本变更先合并一个文件分 describe 块）。`package.json` 新增 `test:translator` 脚本指向该文件。

## Risks / Trade-offs

- **[风险] jsdom 不提供 `ReadableStream`/`TextDecoder`** → 缓解：Node 内置 `stream/web` 提供 `ReadableStream` 与 `TextDecoder`，在测试 setup 中挂到 jsdom window / global；参考现有 task-4.x 测试是否已处理。
- **[风险] 静态 import 使 mock stages.js 困难** → 缓解：按决策 2 只断言 stage 名而非 label 文案，避免依赖后端 fetch。
- **[风险] module 解析路径差异** → 缓解：用 `pathToFileURL` + 相对项目根加载被测模块，沿用现有测试已知可跑的导入方式。