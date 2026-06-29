import { JSDOM } from 'jsdom';
import { readFileSync } from 'fs';
import { resolve } from 'path';
import { fileURLToPath } from 'url';

const __dirname = fileURLToPath(new URL('.', import.meta.url));
const modulePath = resolve(__dirname, '..', 'static', 'modules', 'alignment-controller.js');
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

jsdomWindow.__TEST_ALIGNMENT_CONTROLLER__ = true;

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

console.log('=== Alignment Controller Tests ===');
for (const log of logs) console.log(log);
for (const err of errors) console.error(err);

if (globalThis.__ALIGNMENT_CONTROLLER_TESTS_DONE__) {
    const logsAndErrors = [...logs, ...errors].join('\n');
    if (logsAndErrors.includes('FAILED') || logsAndErrors.includes('FAIL:')) {
        process.exit(1);
    } else {
        process.exit(0);
    }
} else {
    console.log('INCOMPLETE');
    process.exit(1);
}
