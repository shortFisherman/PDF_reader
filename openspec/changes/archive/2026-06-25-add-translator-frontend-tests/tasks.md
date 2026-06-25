# Tasks: add-translator-frontend-tests

## 1. 测试基础设施

- [x] 1.1 阅读 `tests/run-task-4.x-tests.mjs` 的 ESM + jsdom 运行方式与 polyfill 用法
- [x] 1.2 新建 `tests/run-translator-tests.mjs`，设置 jsdom + `ReadableStream`/`TextDecoder`/`fetch`/`Response` polyfill
- [x] 1.3 在 `package.json` 新增 `test:translator` 脚本指向该文件，非零退出码表示失败

## 2. sse-client 测试

- [x] 2.1 测试：多 `data: {json}\n\n` 事件单 chunk 解析
- [x] 2.2 测试：事件跨 chunk 分片拼接正确
- [x] 2.3 测试：非法 JSON 行被跳过且继续解析后续有效事件
- [x] 2.4 测试：`done` 后 reader 正常结束

## 3. translator 测试

- [x] 3.1 测试：progress → finish 成功路径回调顺序（onProgress/onStageChange/onFinish）
- [x] 3.2 测试：含 stage_current/stage_total 时 label 附带「第 X/Y 段」
- [x] 3.3 测试：SSE error 事件 → onError，onFinish 不调用
- [x] 3.4 测试：HTTP 非 ok → onError（含 server error 文案回退）
- [x] 3.5 测试：prompt 透传 body（有 prompt → `{prompt: value}`，无 → `{prompt: null}`）

## 4. 验证

- [x] 4.1 `node tests/run-translator-tests.mjs` 本地全过、退出码 0
- [x] 4.2 确认未改 `translator.js`/`sse-client.js` 源码
- [x] 4.3 记录本变更为 `add-ci-and-lint-cleanup` 后续接入 `npm test` 的前置

## Review Notes

Code review passed (2026-06-25). No Critical issues.
- Plan deviation (readFileSync+new Function() instead of await import()): pragmatic choice following existing codebase patterns (run-task-4.4-tests.mjs, run-lazy-loader-tests.mjs). project package.json `"type": "commonjs"` prevents ESM import of .js source files.
- Final buffer edge case in sse-client.js is a source module behavior, not a test gap — out of scope for this change.