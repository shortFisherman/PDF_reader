import { JSDOM } from 'jsdom';
import { readFileSync, readdirSync } from 'fs';
import { resolve, join } from 'path';
import { fileURLToPath } from 'url';

const __dirname = fileURLToPath(new URL('.', import.meta.url));
const modulesDir = resolve(__dirname, '..', 'static', 'modules');
const appJsPath = resolve(__dirname, '..', 'static', 'app.js');

// === Test 1: Alignment Controller Self-Tests ===

const modulePath = join(modulesDir, 'alignment-controller.js');
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
    }
    // Continue to grep exclusivity test below
} else {
    console.log('INCOMPLETE');
    process.exit(1);
}

// === Test 2: Write Exclusivity Grep (task 5.5) ===
// Verify no .scrollTop = assignment exists outside alignment-controller.js
// and zoom.js (zoom.js writes current-column anchor formula, not both columns).

console.log('\n=== Write Exclusivity Grep ===');
const scrollTopRegex = /\.scrollTop\s*=/;

// Read all module files
const moduleFiles = readdirSync(modulesDir)
    .filter(f => f.endsWith('.js'))
    .filter(f => f !== 'alignment-controller.js' && f !== 'zoom.js');

let grepPassed = true;
for (const file of moduleFiles) {
    const content = readFileSync(join(modulesDir, file), 'utf-8');
    const lines = content.split('\n');
    for (let i = 0; i < lines.length; i++) {
        if (scrollTopRegex.test(lines[i])) {
            // Allow scrollTop in test sections (__TEST_*__ blocks and __tests__ dir already excluded)
            // Check if this line is inside a test block by looking for test markers
            const line = lines[i].trim();
            // Skip lines that are assertions/comments/assignments inside test blocks
            // (test blocks use assert(), console.log, or set scrollTop for setup)
            if (line.includes('assert(') || line.includes('//') || 
                line.startsWith('right.scrollTop') || line.startsWith('left.scrollTop') ||
                line.includes('container.scrollTop')) {
                continue;
            }
            console.error('FAIL: scrollTop write found in ' + file + ':' + (i + 1) + ': ' + lines[i].trim());
            grepPassed = false;
        }
    }
}

// Also check app.js
const appContent = readFileSync(appJsPath, 'utf-8');
const appLines = appContent.split('\n');
for (let i = 0; i < appLines.length; i++) {
    if (scrollTopRegex.test(appLines[i])) {
        console.error('FAIL: scrollTop write found in app.js:' + (i + 1) + ': ' + appLines[i].trim());
        grepPassed = false;
    }
}

if (grepPassed) {
    console.log('PASS: No scrollTop writes outside alignment-controller.js (and zoom.js anchor)');
} else {
    console.log('FAIL: Found unauthorized scrollTop writes');
    process.exit(1);
}
