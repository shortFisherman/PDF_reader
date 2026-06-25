---
comet_change: add-translator-frontend-tests
role: technical-design
canonical_spec: openspec
archived-with: 2026-06-25-add-translator-frontend-tests
status: final
---

# Technical Design: translator / sse-client Frontend Tests

## Architecture

```
tests/run-translator-tests.mjs          (唯一新建文件)
  import { JSDOM } from 'jsdom'
  import { ReadableStream, TextDecoder } from 'node:stream/web'
  import { TextEncoder } from 'node:util'
  polyfill: globalThis.ReadableStream, TextDecoder
  mock:     globalThis.fetch, Response
  await import('../static/modules/translator.js')    → 解析 ./sse-client.js ./stages.js
  await import('../static/modules/sse-client.js')
  [sse-client 4 tests]
  [translator 5 tests]
  process.exit(failed > 0 ? 1 : 0)

package.json
  scripts.test:translator: "node tests/run-translator-tests.mjs"
```

被测模块零变更。依赖链 `translator.js → sse-client.js + stages.js` 通过 Node ESM 自然解析，`stages.js` 的 `_cache = null` 触发 `FALLBACK_LABELS` 回退，`getStageLabel` 闭环无网络。

## Polyfill Setup

| API | 来源 | 挂载目标 |
|-----|------|----------|
| `ReadableStream` | `node:stream/web` | `globalThis.ReadableStream` |
| `TextDecoder` | `node:stream/web` | `globalThis.TextDecoder` |
| `TextEncoder` | `node:util` | `globalThis.TextEncoder` |
| `fetch` | 手写 mock | `globalThis.fetch` |
| `Response` | 手写 mock | `globalThis.Response` |

mock `fetch` 签名：`(url, init) => Response`，其中 Response 的 body 为 ReadableStream，ok/json 可控，init 可用于断言 POST body。

## SSE Chunk Mock Pattern

```js
const encoder = new TextEncoder();
const stream = new ReadableStream({
    start(controller) {
        controller.enqueue(encoder.encode(sseText));
        controller.close();
    }
});
const mockResponse = { body: { getReader: () => stream.getReader() } };
```

## sse-client Tests

### Test 2.1: single chunk, multiple events

Input: `data: {"p":0.5}\n\ndata: {"type":"finish"}\n\n`
Assert: onEvent called 2 times with `{p:0.5}` then `{type:"finish"}`

### Test 2.2: event split across chunks

Chunk1: `data: {"type":"pro`
Chunk2: `gress","p":1}\n\n`
Assert: onEvent called once with `{type:"progress","p":1}` — buffer re-assembly correct

### Test 2.3: malformed JSON skipped

Input: `data: {not valid}\n\ndata: {"ok":true}\n\n`
Assert: onEvent called once with `{ok:true}`, no exception thrown

### Test 2.4: empty stream terminates

Input: ReadableStream that immediately closes (0 chunks)
Assert: onEvent called 0 times, function resolves without error

## translator Tests

### Test 3.1: progress → finish callback order

Mock fetch: ok=true, body yields progress + finish SSE events.
Assert: onProgress → onStageChange → onFinish called in order with correct args. onError not called.

### Test 3.2: stage_current/stage_total absent → no page suffix

Mock fetch: progress event without stage_current/stage_total.
Assert: onStageChange label is `正在翻译…` (no `第 X/Y 段`)

### Test 3.3: SSE error event → onError

Mock fetch: ok=true, body yields error SSE event.
Assert: onError called, onFinish not called.

### Test 3.4: HTTP !ok → onError

Mock fetch: ok=false, json() returns `{error: '服务暂不可用'}`.
Assert: onError('服务暂不可用'), onFinish not called.

### Test 3.5: prompt forwarding

- With prompt: fetch init.body === `{"prompt":"请用正式语气翻译"}`
- Without prompt: fetch init.body === `{"prompt":null}`

## Error Handling

- `readSSEStream` catch: only ignores `SyntaxError`; other errors propagate
- `translateCurrentPage` catch: catches all sync/async errors from fetch, json(), and readSSEStream; calls onError with message
- HTTP error path: `resp.ok === false` → parse `resp.json().error` → throw → onError
- Test asserts: `process.exit(failed > 0 ? 1 : 0)`, CI-ready

## Verification

1. `node tests/run-translator-tests.mjs` → exit 0, all tests pass
2. `git diff --name-only` → only `tests/run-translator-tests.mjs` + `package.json` changed
3. Ready as prerequisite for `add-ci-and-lint-cleanup` to add `npm test` step
