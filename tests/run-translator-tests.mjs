import { JSDOM } from 'jsdom';
import { ReadableStream } from 'node:stream/web';
import { TextDecoder, TextEncoder } from 'node:util';
import { readFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));

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

function stripExports(code) {
    return code
        .replace(/^import\s+.*$/gm, '')
        .replace(/^export\s+async\s+function\b/gm, 'async function')
        .replace(/^export\s+function\b/gm, 'function')
        .replace(/^export\s+const\b/gm, 'const')
        .replace(/^export\s+let\b/gm, 'let')
        .replace(/^export\s+var\b/gm, 'var')
        .replace(/^export\s+/gm, '');
}

const allCode = [
    stripExports(readFileSync(resolve(__dirname, '..', 'static', 'modules', 'stages.js'), 'utf-8')),
    stripExports(readFileSync(resolve(__dirname, '..', 'static', 'modules', 'sse-client.js'), 'utf-8')),
    stripExports(readFileSync(resolve(__dirname, '..', 'static', 'modules', 'translator.js'), 'utf-8')),
].join('\n');

const wrappedCode = `\n${allCode}\nreturn { readSSEStream, translateCurrentPage, translateBatch, getStageLabel };\n`;

const { readSSEStream, translateCurrentPage, translateBatch, getStageLabel } = (new Function(wrappedCode))();

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
// translator Tests
// ============================================================

// Test 3.1: progress -> finish callback order with stage_current/stage_total
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

// Test 3.2: stage_current/stage_total absent -> no page suffix
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

// Test 3.3: SSE error event -> onError, onFinish not called
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

// Test 3.4: HTTP !ok -> onError with server error message
console.log('--- Test 3.4: HTTP not ok -> onError ---');
{
    const record = [];
    const mockFetchResp = createMockResponse({
        ok: false,
        jsonData: { error: '已有翻译任务正在进行，请稍后再试', code: 'translation_busy' },
    });

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
    assert(
        record[0].msg === '已有翻译任务正在进行，请稍后再试',
        `Test 3.4.3: busy error message preserved, got "${record[0].msg}"`,
    );
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

// ============================================================
// translator translateBatch Tests
// ============================================================

// Test 4.1: translateBatch emits batch_info -> progress -> finish
console.log('--- Test 4.1: translateBatch batch_info/progress/finish ---');
{
    const record = [];
    const sseBody = [
        'data: {"type":"batch_info","from":2,"to":5,"total":4}\n',
        '\n',
        'data: {"type":"progress","progress":10,"stage":"layout_analysis","stage_current":0,"stage_total":0}\n',
        '\n',
        'data: {"type":"progress","progress":60,"stage":"translating","stage_current":1,"stage_total":2}\n',
        '\n',
        'data: {"type":"finish"}\n',
        '\n',
    ].join('');
    const stream = makeSSEStream(sseBody);
    const mockFetchResp = createMockResponse({ ok: true, body: stream });
    globalThis.fetch = async (url, init) => mockFetchResp;

    const callbacks = {
        onBatchInfo: (f, t, total) => record.push({ type: 'batchInfo', f, t, total }),
        onStageChange: (stage, label) => record.push({ type: 'stage', stage, label }),
        onProgress: (p) => record.push({ type: 'progress', p }),
        onFinish: () => record.push({ type: 'finish' }),
        onError: (msg) => record.push({ type: 'error', msg }),
        prompt: null,
    };

    await translateBatch(2, 5, callbacks);

    assert(record[0].type === 'batchInfo' && record[0].f === 2 && record[0].t === 5 && record[0].total === 4, 'Test 4.1.1: onBatchInfo first');
    assert(record.some(r => r.type === 'progress' && r.p === 60), 'Test 4.1.2: onProgress(60) called');
    assert(record.some(r => r.type === 'stage' && r.label.includes('正在翻译')), 'Test 4.1.3: onStageChange translating');
    assert(record.some(r => r.type === 'stage' && r.label.includes('第 1/2 段')), 'Test 4.1.4: stage suffix');
    assert(record[record.length - 1].type === 'finish', 'Test 4.1.5: onFinish last');
    assert(!record.some(r => r.type === 'error'), 'Test 4.1.6: no onError');
}

// Test 4.2: translateBatch HTTP !ok -> onError
console.log('--- Test 4.2: translateBatch HTTP not ok -> onError ---');
{
    const record = [];
    const mockFetchResp = createMockResponse({ ok: false, jsonData: { error: 'page out of range' } });
    globalThis.fetch = async (url, init) => mockFetchResp;

    await translateBatch(0, 1, {
        onBatchInfo: () => {}, onStageChange: () => {}, onProgress: () => {},
        onFinish: () => record.push('finish'),
        onError: (msg) => record.push({ type: 'error', msg }),
        prompt: null,
    });

    assert(record.length === 1, 'Test 4.2.1: exactly 1 callback');
    assert(record[0].type === 'error' && record[0].msg === 'page out of range', 'Test 4.2.2: onError(msg)');
    assert(!record.includes('finish'), 'Test 4.2.3: no onFinish');
}

// Test 4.3: translateBatch prompt forwarded in body
console.log('--- Test 4.3: translateBatch prompt forwarding ---');
{
    let capturedBody = null;
    const stream = makeSSEStream('data: {"type":"batch_info","from":1,"to":1,"total":1}\n\ndata: {"type":"finish"}\n\n');
    const mockFetchResp = createMockResponse({ ok: true, body: stream });
    globalThis.fetch = async (url, init) => { capturedBody = init.body; return mockFetchResp; };

    await translateBatch(1, 1, {
        onBatchInfo: () => {}, onStageChange: () => {}, onProgress: () => {},
        onFinish: () => {}, onError: () => {}, prompt: '正式语气',
    });
    assert(capturedBody === '{"from":1,"to":1,"prompt":"正式语气"}', `Test 4.3.1: body has from/to/prompt`);
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
