---
change: add-translator-frontend-tests
design-doc: docs/superpowers/specs/2026-06-25-translator-frontend-tests-design.md
base-ref: 6a256b21b178e4914f905f6733a7f8b8738dca61
archived-with: 2026-06-25-add-translator-frontend-tests
---

# translator / sse-client Frontend Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add jsdom-based frontend tests for `translateCurrentPage` (5 cases) and `readSSEStream` (4 cases) via a single ESM test runner, with hands-free polyfills and mocks.

**Architecture:** Single file `tests/run-translator-tests.mjs` — polyfills `ReadableStream`/`TextDecoder`/`TextEncoder` from `node:stream/web` and `node:util`, hand-writes `fetch`/`Response` mocks on `globalThis`, then `await import()` loads the source modules. No source files are changed.

**Tech Stack:** Node 18+, jsdom 29 (already a devDependency), `node:stream/web`, `node:util`, ES module dynamic `import()`, simple `assert()` + passed/failed counters.

## Global Constraints

- Source modules `static/modules/translator.js`, `static/modules/sse-client.js`, `static/modules/stages.js` must not be modified
- `package.json` type is `"commonjs"` — test file uses `.mjs` extension for ESM
- Test runner exits code 0 on pass, code 1 on any failure
- All tests use a single `passed`/`failed` counter pattern matching existing `tests/run-task-4.4-tests.mjs`
- jsdom 29 is already in `devDependencies` — no new dependencies

archived-with: 2026-06-25-add-translator-frontend-tests
---

### Task 1: Scaffold Test Runner with Infrastructure and sse-client Tests

**Files:**
- Create: `tests/run-translator-tests.mjs`
- Modify: `package.json:11` (add `test:translator` script)

**Interfaces:**
- Produces: `assert(condition, msg)` helper, `makeSSEStream(text)`, `createMockResponse(opts)` factory, `passed`/`failed` counters, global polyfills for `ReadableStream`/`TextDecoder`/`TextEncoder`
- Produces: `readSSEStream` imported from `../static/modules/sse-client.js` (used by sse-client tests in this task)
- Produces: `translateCurrentPage` imported from `../static/modules/translator.js` (used by translator tests in Task 2)

- [x] **Step 1: Read existing `tests/run-task-4.4-tests.mjs` to internalize the assert/counter pattern**

Open `tests/run-task-4.4-tests.mjs:39-48` for reference — the `passed`/`failed` counters plus `assert(condition, msg)` and the summary `process.exit(failed > 0 ? 1 : 0)` pattern.

- [x] **Step 2: Create `tests/run-translator-tests.mjs` with jsdom + polyfills + mock factories + module imports + sse-client tests**

Write the complete file:

```js
import { JSDOM } from 'jsdom';
import { ReadableStream, TextDecoder } from 'node:stream/web';
import { TextEncoder } from 'node:util';

const dom = new JSDOM('<!doctype html><html><body></body></html>', {
    url: 'http://localhost',
    runScripts: 'outside-only',
});
const { window: jsdomWindow } = dom;
globalThis.window = jsdomWindow;
globalThis.document = jsdomWindow.document;
globalThis.ReadableStream = ReadableStream;
globalThis.TextDecoder = TextDecoder;
globalThis.TextEncoder = TextEncoder;

let passed = 0;
let failed = 0;

function assert(condition, msg) {
    if (condition) {
        passed++;
    } else {
        failed++;
        console.error(`FAIL: ${msg}`);
    }
}

function makeSSEStream(text) {
    const encoder = new TextEncoder();
    return new ReadableStream({
        start(controller) {
            controller.enqueue(encoder.encode(text));
            controller.close();
        },
    });
}

function createMockResponse(opts = {}) {
    const { ok = true, body = null, jsonData = {} } = opts;
    return {
        ok,
        status: ok ? 200 : 500,
        body: body ? { getReader: () => body.getReader() } : null,
        json: async () => jsonData,
    };
}

const sseClient = await import('../static/modules/sse-client.js');
const { readSSEStream } = sseClient;

const translator = await import('../static/modules/translator.js');
const { translateCurrentPage } = translator;

// ============================================================
// sse-client Tests
// ============================================================

// Test 2.1: single chunk, multiple events
console.log('--- Test 2.1: single chunk, multiple events ---');
{
    const events = [];
    const stream = makeSSEStream('data: {"p":0.5}\n\ndata: {"type":"finish"}\n\n');
    const mockResp = createMockResponse({ body: stream });
    await readSSEStream(mockResp, (evt) => events.push(evt));
    assert(events.length === 2, 'Test 2.1.1: 2 events parsed');
    assert(events[0].p === 0.5, 'Test 2.1.2: first event is {p:0.5}');
    assert(events[1].type === 'finish', 'Test 2.1.3: second event is {type:"finish"}');
}

// Test 2.2: event split across chunks
console.log('--- Test 2.2: event split across chunks ---');
{
    const events = [];
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
        start(controller) {
            controller.enqueue(encoder.encode('data: {"type":"pro'));
            controller.enqueue(encoder.encode('gress","p":1}\n\n'));
            controller.close();
        },
    });
    const mockResp = createMockResponse({ body: stream });
    await readSSEStream(mockResp, (evt) => events.push(evt));
    assert(events.length === 1, 'Test 2.2.1: 1 event parsed from split chunks');
    assert(events[0].type === 'progress', 'Test 2.2.2: type is progress');
    assert(events[0].p === 1, 'Test 2.2.3: p is 1');
}

// Test 2.3: malformed JSON skipped, next valid event still parsed
console.log('--- Test 2.3: malformed JSON skipped ---');
{
    const events = [];
    const stream = makeSSEStream('data: {not valid}\n\ndata: {"ok":true}\n\n');
    const mockResp = createMockResponse({ body: stream });
    await readSSEStream(mockResp, (evt) => events.push(evt));
    assert(events.length === 1, 'Test 2.3.1: only valid event parsed');
    assert(events[0].ok === true, 'Test 2.3.2: valid event is {ok:true}');
}

// Test 2.4: empty stream terminates without events
console.log('--- Test 2.4: empty stream terminates ---');
{
    const events = [];
    const stream = new ReadableStream({
        start(controller) {
            controller.close();
        },
    });
    const mockResp = createMockResponse({ body: stream });
    await readSSEStream(mockResp, (evt) => events.push(evt));
    assert(events.length === 0, 'Test 2.4.1: no events from empty stream');
}

// ============================================================
// Summary
// ============================================================
console.log('');
console.log(`Results: ${passed} passed, ${failed} failed`);
if (failed > 0) {
    process.exit(1);
} else {
    console.log('PASS');
    process.exit(0);
}
```

- [x] **Step 3: Run the test runner to verify sse-client tests pass**

```powershell
node tests/run-translator-tests.mjs
```

Expected output:
```
archived-with: 2026-06-25-add-translator-frontend-tests
--- Test 2.1: single chunk, multiple events ---
archived-with: 2026-06-25-add-translator-frontend-tests
--- Test 2.2: event split across chunks ---
archived-with: 2026-06-25-add-translator-frontend-tests
--- Test 2.3: malformed JSON skipped ---
archived-with: 2026-06-25-add-translator-frontend-tests
--- Test 2.4: empty stream terminates ---

Results: 8 passed, 0 failed
PASS
```

And exit code 0.

- [x] **Step 4: Add `test:translator` script to `package.json`**

Edit `package.json` line 11 — replace the existing `"test"` line and add the new script:

In `package.json`, find:
```json
  "scripts": {
    "test": "echo \"Error: no test specified\" && exit 1"
  },
```

Replace with:
```json
  "scripts": {
    "test": "echo \"Error: no test specified\" && exit 1",
    "test:translator": "node tests/run-translator-tests.mjs"
  },
```

- [x] **Step 5: Verify the npm script works**

```powershell
npm run test:translator
```

Expected: same output as Step 3, exit code 0.

- [x] **Step 6: Commit Task 1**

```bash
git add tests/run-translator-tests.mjs package.json
git commit -m "feat: add test infrastructure and sse-client tests (4 cases)"
```

archived-with: 2026-06-25-add-translator-frontend-tests
---

### Task 2: Add translator Tests

**Files:**
- Modify: `tests/run-translator-tests.mjs` (insert translator tests after sse-client tests, before summary)

**Interfaces:**
- Consumes: `translateCurrentPage` imported in Task 1, `makeSSEStream()`, `createMockResponse()`, `assert()`, `passed`/`failed` counters
- Consumes: `globalThis.fetch` will be mocked per test via `globalThis.fetch = async (url, init) => mockResponse`

- [x] **Step 1: Insert translator test 3.1 (progress → finish callback order) after the sse-client block and before the Summary block**

In `tests/run-translator-tests.mjs`, find the line:
```js
// ============================================================
// Summary
// ============================================================
```

Insert the full translator tests block above it:

```js
// ============================================================
// translator Tests
// ============================================================

// Test 3.1: progress → finish callback order with stage_current/stage_total
console.log('--- Test 3.1: progress -> finish callback order ---');
{
    const record = [];
    const sseBody = [
        'data: {"type":"progress","progress":0.3,"stage":"translating","stage_current":1,"stage_total":3}\n',
        '\n',
        'data: {"type":"progress","progress":0.7,"stage":"translating","stage_current":2,"stage_total":3}\n',
        '\n',
        'data: {"type":"finish"}\n',
        '\n',
    ].join('');
    const stream = makeSSEStream(sseBody);
    const mockFetchResp = createMockResponse({ ok: true, body: stream });

    globalThis.fetch = async (url, init) => mockFetchResp;

    const callbacks = {
        onStageChange: (stage, label) => record.push({ type: 'stage', stage, label }),
        onProgress: (p) => record.push({ type: 'progress', p }),
        onFinish: () => record.push({ type: 'finish' }),
        onError: (msg) => record.push({ type: 'error', msg }),
    };

    await translateCurrentPage(1, callbacks);

    assert(record.length === 5, 'Test 3.1.1: 5 callbacks total');
    assert(record[0].type === 'progress' && record[0].p === 0.3, 'Test 3.1.2: first onProgress(0.3)');
    assert(record[1].type === 'stage' && record[1].stage === 'translating' && record[1].label.includes('正在翻译'), 'Test 3.1.3: onStageChange for stage 1');
    assert(record[1].label.includes('第 1/3 段'), 'Test 3.1.4: label has stage suffix');
    assert(record[2].type === 'progress' && record[2].p === 0.7, 'Test 3.1.5: second onProgress(0.7)');
    assert(record[3].type === 'stage' && record[3].label.includes('第 2/3 段'), 'Test 3.1.6: label has stage suffix');
    assert(record[4].type === 'finish', 'Test 3.1.7: onFinish called last');
    assert(!record.some(r => r.type === 'error'), 'Test 3.1.8: onError not called');
}

// Test 3.2: stage_current/stage_total absent → no page suffix
console.log('--- Test 3.2: no stage_current/stage_total -> no suffix ---');
{
    const record = [];
    const sseBody = [
        'data: {"type":"progress","progress":0.5,"stage":"translating"}\n',
        '\n',
        'data: {"type":"finish"}\n',
        '\n',
    ].join('');
    const stream = makeSSEStream(sseBody);
    const mockFetchResp = createMockResponse({ ok: true, body: stream });

    globalThis.fetch = async (url, init) => mockFetchResp;

    const callbacks = {
        onStageChange: (stage, label) => record.push({ type: 'stage', stage, label }),
        onProgress: (p) => record.push({ type: 'progress', p }),
        onFinish: () => record.push({ type: 'finish' }),
        onError: (msg) => record.push({ type: 'error', msg }),
    };

    await translateCurrentPage(1, callbacks);

    const stageRecord = record.find(r => r.type === 'stage');
    assert(stageRecord !== undefined, 'Test 3.2.1: onStageChange called');
    assert(stageRecord.label === '正在翻译…', `Test 3.2.2: label is "正在翻译…", got "${stageRecord.label}"`);
    assert(!stageRecord.label.includes('第'), 'Test 3.2.3: label has no stage suffix');
}

// Test 3.3: SSE error event → onError, onFinish not called
console.log('--- Test 3.3: SSE error event -> onError ---');
{
    const record = [];
    const stream = makeSSEStream('data: {"type":"error","error":"SSE stream error"}\n\n');
    const mockFetchResp = createMockResponse({ ok: true, body: stream });

    globalThis.fetch = async (url, init) => mockFetchResp;

    const callbacks = {
        onStageChange: () => {},
        onProgress: () => {},
        onFinish: () => record.push('finish'),
        onError: (msg) => record.push({ type: 'error', msg }),
    };

    await translateCurrentPage(1, callbacks);

    assert(record.length === 1, 'Test 3.3.1: exactly 1 callback');
    assert(record[0].type === 'error', 'Test 3.3.2: onError called');
    assert(record[0].msg === 'SSE stream error', 'Test 3.3.3: error message correct');
    assert(!record.includes('finish'), 'Test 3.3.4: onFinish not called');
}

// Test 3.4: HTTP !ok → onError with server error message
console.log('--- Test 3.4: HTTP not ok -> onError ---');
{
    const record = [];
    const mockFetchResp = createMockResponse({ ok: false, jsonData: { error: '服务暂不可用' } });

    globalThis.fetch = async (url, init) => mockFetchResp;

    const callbacks = {
        onStageChange: () => {},
        onProgress: () => {},
        onFinish: () => record.push('finish'),
        onError: (msg) => record.push({ type: 'error', msg }),
    };

    await translateCurrentPage(1, callbacks);

    assert(record.length === 1, 'Test 3.4.1: exactly 1 callback');
    assert(record[0].type === 'error', 'Test 3.4.2: onError called');
    assert(record[0].msg === '服务暂不可用', `Test 3.4.3: error message is "服务暂不可用", got "${record[0].msg}"`);
    assert(!record.includes('finish'), 'Test 3.4.4: onFinish not called');
}

// Test 3.5: prompt forwarding in fetch body
console.log('--- Test 3.5: prompt forwarding ---');
{
    let capturedBody = null;
    const stream = makeSSEStream('data: {"type":"finish"}\n\n');
    const mockFetchResp = createMockResponse({ ok: true, body: stream });

    globalThis.fetch = async (url, init) => {
        capturedBody = init.body;
        return mockFetchResp;
    };

    // With prompt
    await translateCurrentPage(1, {
        onStageChange: () => {},
        onProgress: () => {},
        onFinish: () => {},
        onError: () => {},
        prompt: '请用正式语气翻译',
    });
    assert(capturedBody === '{"prompt":"请用正式语气翻译"}', `Test 3.5.1: prompt in body, got "${capturedBody}"`);

    // Without prompt
    capturedBody = null;
    await translateCurrentPage(1, {
        onStageChange: () => {},
        onProgress: () => {},
        onFinish: () => {},
        onError: () => {},
    });
    assert(capturedBody === '{"prompt":null}', `Test 3.5.2: null prompt in body, got "${capturedBody}"`);
}
```

- [x] **Step 2: Run `node tests/run-translator-tests.mjs` to verify all 9 test cases (4 sse-client + 5 translator) pass**

```powershell
node tests/run-translator-tests.mjs
```

Expected output:
```
archived-with: 2026-06-25-add-translator-frontend-tests
--- Test 2.1: single chunk, multiple events ---
archived-with: 2026-06-25-add-translator-frontend-tests
--- Test 2.2: event split across chunks ---
archived-with: 2026-06-25-add-translator-frontend-tests
--- Test 2.3: malformed JSON skipped ---
archived-with: 2026-06-25-add-translator-frontend-tests
--- Test 2.4: empty stream terminates ---
archived-with: 2026-06-25-add-translator-frontend-tests
--- Test 3.1: progress -> finish callback order ---
archived-with: 2026-06-25-add-translator-frontend-tests
--- Test 3.2: no stage_current/stage_total -> no suffix ---
archived-with: 2026-06-25-add-translator-frontend-tests
--- Test 3.3: SSE error event -> onError ---
archived-with: 2026-06-25-add-translator-frontend-tests
--- Test 3.4: HTTP not ok -> onError ---
archived-with: 2026-06-25-add-translator-frontend-tests
--- Test 3.5: prompt forwarding ---

Results: 26 passed, 0 failed
PASS
```

Exit code 0.

- [x] **Step 3: Verify the npm script also passes**

```powershell
npm run test:translator
```

Expected: same output as Step 2, exit code 0.

- [x] **Step 4: Confirm no source modules were changed**

```powershell
git diff --name-only
```

Expected output shows only:
```
package.json
tests/run-translator-tests.mjs
```

`git diff --name-only` must not include `static/modules/translator.js`, `static/modules/sse-client.js`, or `static/modules/stages.js`.

- [x] **Step 5: Commit Task 2**

```bash
git add tests/run-translator-tests.mjs
git commit -m "feat: add translator tests (5 cases: callback order, suffix, error, HTTP error, prompt)"
```
