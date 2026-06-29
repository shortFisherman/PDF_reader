import { JSDOM } from 'jsdom';
import { readFileSync } from 'fs';
import { resolve } from 'path';
import { fileURLToPath } from 'url';

const __dirname = fileURLToPath(new URL('.', import.meta.url));

const scrollSyncPath = resolve(__dirname, '..', 'static', 'modules', 'scroll-sync.js');
const fixturePath = resolve(__dirname, '..', 'static', 'modules', '__tests__', 'translation-misalign-fixture.js');

let scrollSyncCode = readFileSync(scrollSyncPath, 'utf-8');
let fixtureCode = readFileSync(fixturePath, 'utf-8');

const dom = new JSDOM('<!doctype html><html><body></body></html>', {
    url: 'http://localhost',
    runScripts: 'outside-only',
});

const { window: jsdomWindow } = dom;

globalThis.window = jsdomWindow;
globalThis.document = jsdomWindow.document;
globalThis.setTimeout = setTimeout;
globalThis.globalThis = globalThis;
globalThis.Event = jsdomWindow.Event;

const logs = [];
const errors = [];

const mockConsole = {
    log: (...args) => logs.push(args.join(' ')),
    error: (...args) => errors.push(args.join(' ')),
};

jsdomWindow.__TEST_ALIGN_REPRO_TRANSLATION__ = true;

function stripExports(code) {
    return code
        .replace(/^export\s+function\b/gm, 'function')
        .replace(/^export\s+const\b/gm, 'const')
        .replace(/^export\s+let\b/gm, 'let')
        .replace(/^export\s+var\b/gm, 'var')
        .replace(/^export\s+/gm, '');
}

scrollSyncCode = stripExports(scrollSyncCode);
fixtureCode = stripExports(fixtureCode);

const combinedCode = scrollSyncCode + '\n;' + fixtureCode;

try {
    const fn = new Function('window', 'document', 'globalThis', 'setTimeout', 'console', combinedCode);
    fn(jsdomWindow, jsdomWindow.document, globalThis, setTimeout, mockConsole);
} catch (e) {
    errors.push('Execution error: ' + e.message + '\n' + e.stack);
}

console.log('=== Test Output ===');
for (const log of logs) console.log(log);
for (const err of errors) console.error(err);

if (globalThis.__ALIGN_REPRO_TRANSLATION_DONE__) {
    const allText = [...logs, ...errors].join('\n');
    if (allText.includes('FAILED') || allText.includes('FAIL:')) {
        console.log('\nFAIL');
        process.exit(1);
    } else {
        console.log('\nPASS');
        process.exit(0);
    }
} else {
    console.log('\nINCOMPLETE (__ALIGN_REPRO_TRANSLATION_DONE__ not set)');
    process.exit(1);
}
