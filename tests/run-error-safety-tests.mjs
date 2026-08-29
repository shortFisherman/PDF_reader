import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { JSDOM } from 'jsdom';

const testsDir = fileURLToPath(new URL('.', import.meta.url));
const rootDir = resolve(testsDir, '..');

const dom = new JSDOM('<!doctype html><html><body><div id="errors"></div></body></html>', {
    url: 'http://localhost',
    runScripts: 'outside-only',
});
const { window: jsdomWindow } = dom;
globalThis.window = jsdomWindow;
globalThis.document = jsdomWindow.document;

function stripExports(code) {
    return code
        .replace(/^export\s+function\b/gm, 'function')
        .replace(/^export\s+const\b/gm, 'const')
        .replace(/^export\s+let\b/gm, 'let')
        .replace(/^export\s+var\b/gm, 'var')
        .replace(/^export\s+/gm, '');
}

const domCode = stripExports(readFileSync(resolve(rootDir, 'static', 'modules', 'dom.js'), 'utf-8'));
const { showError } = (new Function(`${domCode}\nreturn { showError };`))();

// 1. Malicious sentinel is rendered as text only, never as an element.
const SENTINEL = '<img src=x onerror="window.__pwned = true">C:\\Users\\secret\\file.txt sk-secret-123';
const parent = document.getElementById('errors');
showError(parent, SENTINEL);

assert.equal(parent.querySelector('img'), null, 'sentinel must not create an img element');
assert.equal(jsdomWindow.__pwned, undefined, 'sentinel onerror must not execute');
assert.ok(parent.textContent.includes(SENTINEL), 'sentinel must be visible as textContent');
assert.equal(parent.innerHTML.includes('<img'), false, 'no raw HTML injection');

// 2. Production app.js must not inject error text via insertAdjacentHTML.
const appJs = readFileSync(resolve(rootDir, 'static', 'app.js'), 'utf-8');
assert.ok(!appJs.includes('insertAdjacentHTML('), 'app.js must not use insertAdjacentHTML for errors');
assert.ok(appJs.includes('showError'), 'app.js must use the safe showError helper');

console.log('Error safety checks passed');
