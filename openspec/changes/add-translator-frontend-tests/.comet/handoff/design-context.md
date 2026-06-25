# Comet Design Handoff

- Change: add-translator-frontend-tests
- Phase: design
- Mode: compact
- Context hash: 1d84d6b556b81199f3c5aafae8348e500a87a3e9f9acb87d2690b4adbd0143c3

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/add-translator-frontend-tests/proposal.md

- Source: openspec/changes/add-translator-frontend-tests/proposal.md
- Lines: 1-27
- SHA256: 6c1c6f0cdfc72afe73034c77aafef2a091f9dbc470c026ea22d6de5399643e9f

```md
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
- **风险**：要让 ES Module import 在 Node+jsdom 下可跑，需确认现有 `.mjs` 测试的运行方式并沿用，避免引入构建工具（项目「无框架无构建」约束）。```

## openspec/changes/add-translator-frontend-tests/design.md

- Source: openspec/changes/add-translator-frontend-tests/design.md
- Lines: 1-36
- SHA256: 1e3bb869451426dd0c0405273793cdc4ec3208c2b505c43250c0371b5a5027d0

```md
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
- **[风险] module 解析路径差异** → 缓解：用 `pathToFileURL` + 相对项目根加载被测模块，沿用现有测试已知可跑的导入方式。```

## openspec/changes/add-translator-frontend-tests/tasks.md

- Source: openspec/changes/add-translator-frontend-tests/tasks.md
- Lines: 1-27
- SHA256: e0d4a7768c93d282e9cd9b82d90782be959bf82c1ad1414b8165d839fd0c43fb

```md
# Tasks: add-translator-frontend-tests

## 1. 测试基础设施

- [ ] 1.1 阅读 `tests/run-task-4.x-tests.mjs` 的 ESM + jsdom 运行方式与 polyfill 用法
- [ ] 1.2 新建 `tests/run-translator-tests.mjs`，设置 jsdom + `ReadableStream`/`TextDecoder`/`fetch`/`Response` polyfill
- [ ] 1.3 在 `package.json` 新增 `test:translator` 脚本指向该文件，非零退出码表示失败

## 2. sse-client 测试

- [ ] 2.1 测试：多 `data: {json}\n\n` 事件单 chunk 解析
- [ ] 2.2 测试：事件跨 chunk 分片拼接正确
- [ ] 2.3 测试：非法 JSON 行被跳过且继续解析后续有效事件
- [ ] 2.4 测试：`done` 后 reader 正常结束

## 3. translator 测试

- [ ] 3.1 测试：progress → finish 成功路径回调顺序（onProgress/onStageChange/onFinish）
- [ ] 3.2 测试：含 stage_current/stage_total 时 label 附带「第 X/Y 段」
- [ ] 3.3 测试：SSE error 事件 → onError，onFinish 不调用
- [ ] 3.4 测试：HTTP 非 ok → onError（含 server error 文案回退）
- [ ] 3.5 测试：prompt 透传 body（有 prompt → `{prompt: value}`，无 → `{prompt: null}`）

## 4. 验证

- [ ] 4.1 `node tests/run-translator-tests.mjs` 本地全过、退出码 0
- [ ] 4.2 确认未改 `translator.js`/`sse-client.js` 源码
- [ ] 4.3 记录本变更为 `add-ci-and-lint-cleanup` 后续接入 `npm test` 的前置```

## openspec/changes/add-translator-frontend-tests/specs/frontend-modular-architecture/spec.md

- Source: openspec/changes/add-translator-frontend-tests/specs/frontend-modular-architecture/spec.md
- Lines: 1-48
- SHA256: 7bb53c899fcbfd68120d60b08ce1444c11c6df72d2811689ee48c56f120fc907

```md
# frontend-modular-architecture Delta: add-translator-frontend-tests

## ADDED Requirements

### Requirement: Automated tests for translator and sse-client modules

The `translator` and `sse-client` frontend modules SHALL be covered by automated tests (runnable locally without a build step) verifying their core behaviors: SSE stream parsing, translation callback ordering, and error handling.

#### Scenario: readSSEStream parses multiple data events

- **WHEN** a response body streams multiple `data: {json}\n\n` events across one or more chunks
- **THEN** `readSSEStream` SHALL parse each event and invoke the callback once per event with the decoded JSON object, including events split across chunk boundaries

#### Scenario: readSSEStream terminates on empty stream

- **WHEN** the response body stream ends immediately with no data chunks
- **THEN** `readSSEStream` SHALL resolve without invoking any callbacks and without throwing

#### Scenario: readSSEStream skips malformed lines

- **WHEN** a chunk contains a `data: ` line whose payload is not valid JSON
- **THEN** `readSSEStream` SHALL skip that line WITHOUT throwing and SHALL continue parsing subsequent valid events

#### Scenario: translateCurrentPage invokes callbacks in order

- **WHEN** `translateCurrentPage` is called and the SSE stream yields a progress event followed by a finish event
- **THEN** `onProgress` SHALL be invoked with the progress value, `onStageChange` SHALL be invoked (when a stage is present) with the stage and label, and `onFinish` SHALL be invoked last

#### Scenario: translateCurrentPage appends page suffix to stage label conditionally

- **WHEN** a progress event includes `stage_current` and `stage_total` both greater than 0
- **THEN** the `onStageChange` label SHALL include the page segment suffix (e.g. `第 2/5 段`)
- **WHEN** `stage_current` or `stage_total` is 0 or absent
- **THEN** the label SHALL NOT include the page segment suffix

#### Scenario: translateCurrentPage handles SSE error event

- **WHEN** the SSE stream yields an `error` event
- **THEN** `onError` SHALL be invoked with the error message and `onFinish` SHALL NOT be invoked

#### Scenario: translateCurrentPage handles HTTP failure

- **WHEN** the `/api/translate/<page>` response is not ok
- **THEN** `translateCurrentPage` SHALL invoke `onError` with the server error message (or a fallback) and SHALL NOT invoke `onFinish`

#### Scenario: translateCurrentPage forwards prompt to request body

- **WHEN** `translateCurrentPage` is called with a `prompt` in the callbacks object
- **THEN** the POST request body SHALL contain `{ prompt: <value> }`, and SHALL contain `{ prompt: null }` when no prompt is provided```

