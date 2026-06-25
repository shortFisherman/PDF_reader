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

const wrappedCode = `\n${allCode}\nreturn { readSSEStream, translateCurrentPage, getStageLabel };\n`;

const { readSSEStream, translateCurrentPage, getStageLabel } = (new Function(wrappedCode))();

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
