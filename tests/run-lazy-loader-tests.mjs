import { JSDOM } from 'jsdom';
import { readFileSync } from 'fs';
import { resolve } from 'path';
import { fileURLToPath } from 'url';

const __dirname = fileURLToPath(new URL('.', import.meta.url));
const modulePath = resolve(__dirname, '..', 'static', 'modules', 'lazy-loader.js');
let code = readFileSync(modulePath, 'utf-8');

const dom = new JSDOM('<!doctype html><html><body></body></html>', {
    url: 'http://localhost',
    runScripts: 'outside-only',
});

const { window: jsdomWindow } = dom;

globalThis.window = jsdomWindow;
globalThis.document = jsdomWindow.document;
globalThis.setTimeout = setTimeout;
globalThis.globalThis = globalThis;

const logs = [];
const errors = [];

const mockConsole = {
    log: (...args) => logs.push(args.join(' ')),
    error: (...args) => errors.push(args.join(' ')),
};

jsdomWindow.__TEST_SETUP_INTERSECTION_OBSERVER__ = true;
jsdomWindow.__TEST_SETTLE_SCAN__ = true;
jsdomWindow.__TEST_DELAYED_RECLAIM__ = true;

code = code.replace(/^export\s+function\b/gm, 'function');
code = code.replace(/^export\s+const\b/gm, 'const');
code = code.replace(/^export\s+let\b/gm, 'let');
code = code.replace(/^export\s+var\b/gm, 'var');
code = code.replace(/^export\s+/gm, '');

try {
    const fn = new Function('window', 'document', 'globalThis', 'setTimeout', 'console', code);
    fn(jsdomWindow, jsdomWindow.document, globalThis, setTimeout, mockConsole);
} catch (e) {
    errors.push('Execution error: ' + e.message + '\n' + e.stack);
}

console.log('=== Test Output ===');
for (const log of logs) console.log(log);
for (const err of errors) console.error(err);

if (globalThis.__SETUP_IO_TESTS_DONE__ && globalThis.__SETTLE_SCAN_TESTS_DONE__ && globalThis.__DELAYED_RECLAIM_TESTS_DONE__) {
    const allText = [...logs, ...errors].join('\n');
    if (allText.includes('FAILED') || allText.includes('FAIL:')) {
        console.log('\nFAIL');
        process.exit(1);
    } else {
        console.log('\nPASS');
        process.exit(0);
    }
} else {
    const missing = [];
    if (!globalThis.__SETUP_IO_TESTS_DONE__) missing.push('__SETUP_IO_TESTS_DONE__');
    if (!globalThis.__SETTLE_SCAN_TESTS_DONE__) missing.push('__SETTLE_SCAN_TESTS_DONE__');
    if (!globalThis.__DELAYED_RECLAIM_TESTS_DONE__) missing.push('__DELAYED_RECLAIM_TESTS_DONE__');
    console.log('\nINCOMPLETE (' + missing.join(', ') + ' not set)');
    process.exit(1);
}
