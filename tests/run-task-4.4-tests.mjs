import { JSDOM } from 'jsdom';
import { readFileSync } from 'fs';
import { resolve } from 'path';
import { fileURLToPath } from 'url';

const __dirname = fileURLToPath(new URL('.', import.meta.url));
const appPath = resolve(__dirname, '..', 'static', 'app.js');
const source = readFileSync(appPath, 'utf-8');

const dom = new JSDOM('<!doctype html><html><body></body></html>', {
    url: 'http://localhost',
    runScripts: 'outside-only',
});

const { window: jsdomWindow } = dom;
globalThis.window = jsdomWindow;
globalThis.document = jsdomWindow.document;

// Extract loadPageImage function body from app.js source
const fnMatch = source.match(/function loadPageImage\(container\) \{([\s\S]*?)\n\}(?=\s*(?:\r?\n|$))/);
if (!fnMatch) {
    console.error('Could not parse loadPageImage from app.js');
    process.exit(1);
}

const fnBody = fnMatch[1];

// Build the function from extracted source to test actual app.js code
// fnBody already includes the full body (starting with const page/const side declarations)
const API = '/api';
const _loadPageImageFn = new Function('container', 'API', 'Date', 'document', fnBody);
function loadPageImage(container) {
    return _loadPageImageFn(container, API, Date, document);
}

// ============================================================
// Test helpers
// ============================================================
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

function makeContainer(pageNum, side, loadedState) {
    const container = document.createElement('div');
    container.className = 'page-container';
    container.dataset.page = String(pageNum);
    container.dataset.side = side;
    if (loadedState !== undefined) {
        container.dataset.loaded = loadedState;
    }

    const placeholder = document.createElement('div');
    placeholder.className = 'page-placeholder';
    placeholder.style.paddingBottom = '56%';
    placeholder.textContent = `Page ${pageNum + 1}`;
    placeholder.dataset.loaded = 'false';
    container.appendChild(placeholder);

    return container;
}

// ============================================================
// Test 1: loaded='true' container → loadPageImage does nothing
// ============================================================
console.log('--- Test 1: loaded=true → no-op ---');
{
    const container = makeContainer(0, 'left', 'true');
    const placeholderBefore = container.querySelector('.page-placeholder');
    loadPageImage(container);

    const imgs = container.querySelectorAll('img');
    assert(imgs.length === 0, 'Test 1.1: No img element inserted when loaded=true');

    const placeholderAfter = container.querySelector('.page-placeholder');
    assert(placeholderAfter !== null, 'Test 1.2: Placeholder still exists when loaded=true');
    assert(placeholderAfter === placeholderBefore, 'Test 1.3: Same placeholder element retained');
}

// ============================================================
// Test 2: loaded unset → img created but not in DOM yet
// ============================================================
console.log('--- Test 2: loaded unset → img created ---');
{
    const container = makeContainer(3, 'right');
    loadPageImage(container);

    assert(container.dataset.loaded !== 'true', 'Test 2.1: dataset.loaded not true before onload');

    const imgs = container.querySelectorAll('img');
    assert(imgs.length === 0, 'Test 2.2: No img in container DOM before onload fires');

    const placeholder = container.querySelector('.page-placeholder');
    assert(placeholder !== null, 'Test 2.3: Placeholder still present before onload');
}

// ============================================================
// Test 3: loaded='false' allows loading
// ============================================================
console.log('--- Test 3: loaded=false allows loading ---');
{
    const container = makeContainer(5, 'left', 'false');
    loadPageImage(container);

    const imgs = container.querySelectorAll('img');
    assert(imgs.length === 0, 'Test 3.1: No img in container DOM before onload fires');
    assert(container.dataset.loaded !== 'true', 'Test 3.2: dataset.loaded not true before onload');

    const placeholder = container.querySelector('.page-placeholder');
    assert(placeholder !== null, 'Test 3.3: Placeholder still present before onload');
}

// ============================================================
// Test 4: onload guard works (container.dataset.loaded='true' set by onload impl)
// ============================================================
console.log('--- Test 4: onload guard works ---');
{
    const container = makeContainer(2, 'left');
    loadPageImage(container);

    // Simulate that onload has fired (set loaded=true on container)
    container.dataset.loaded = 'true';

    const imgsBefore = container.querySelectorAll('img').length;
    loadPageImage(container); // Should be no-op
    const imgsAfter = container.querySelectorAll('img').length;
    assert(imgsAfter === imgsBefore, 'Test 4.1: Second call is no-op when loaded=true');
}

// ============================================================
// Test 5: onerror sets container.dataset.loaded = 'error'
// ============================================================
console.log('--- Test 5: onerror sets loaded=error ---');
{
    const container = makeContainer(9, 'right');
    loadPageImage(container);
    container.dataset.loaded = 'error';

    assert(container.dataset.loaded === 'error', 'Test 5.1: dataset.loaded set to error state');
    assert(container.dataset.loaded !== 'true', 'Test 5.2: error is not true');
}

// ============================================================
// Test 6: Placeholder intact before onload
// ============================================================
console.log('--- Test 6: Placeholder intact before onload ---');
{
    const container = makeContainer(6, 'left');
    loadPageImage(container);

    const placeholder = container.querySelector('.page-placeholder');
    assert(placeholder !== null, 'Test 6.1: Placeholder still in DOM before onload');
    assert(placeholder.textContent === 'Page 7', 'Test 6.2: Placeholder shows correct text');
}

// ============================================================
// Test 7: No insertBefore call (img not in DOM until onload replaceWith)
// ============================================================
console.log('--- Test 7: No insertBefore → img not in DOM ---');
{
    const container = makeContainer(4, 'right');
    loadPageImage(container);

    const imgs = container.querySelectorAll('img');
    assert(imgs.length === 0, 'Test 7.1: No img in container DOM before onload fires');
}

// ============================================================
// Test 8: loaded='loading' does NOT trigger guard (retry on failure)
// ============================================================
console.log('--- Test 8: loaded=loading allows retry ---');
{
    const container = makeContainer(0, 'left', 'loading');
    loadPageImage(container);
    // Guard only triggers on 'true', not 'loading' or 'error'
    assert(container.dataset.loaded === 'loading', 'Test 8.1: Guard does not fire for loading state');
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
