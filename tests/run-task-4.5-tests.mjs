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

const fnMatch = source.match(/function unloadPageImage\(container\) \{([\s\S]*?)\n\}(?=\s*(?:\r?\n|$))/);
if (!fnMatch) {
    console.error('Could not parse unloadPageImage from app.js');
    process.exit(1);
}

const fnBody = fnMatch[1];

function calculatePlaceholderHeight(pageWidth, pageHeight) {
    if (pageWidth && pageHeight) {
        const ratio = pageHeight / pageWidth;
        return Math.round(100 * ratio);
    }
    return 600;
}

const _unloadPageImageFn = new Function(
    'container',
    'document',
    'calculatePlaceholderHeight',
    'pageWidth',
    'pageHeight',
    fnBody
);
function unloadPageImage(container) {
    return _unloadPageImageFn(container, document, calculatePlaceholderHeight, 800, 1200);
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

    const img = document.createElement('img');
    img.src = '/api/page/left/0';
    container.appendChild(img);

    return container;
}

// ============================================================
// Test 1: loaded='true' → img replaced with placeholder, dataset.loaded = 'false'
// ============================================================
console.log('--- Test 1: loaded=true → unloads and sets loaded=false ---');
{
    const container = makeContainer(0, 'left', 'true');
    const imgBefore = container.querySelector('img');
    assert(imgBefore !== null, 'Test 1.0: Container has img before unload');

    unloadPageImage(container);

    const imgAfter = container.querySelector('img');
    assert(imgAfter === null, 'Test 1.1: img is removed after unload');

    const placeholder = container.querySelector('.page-placeholder');
    assert(placeholder !== null, 'Test 1.2: Placeholder created after unload');
    assert(placeholder.style.getPropertyValue('--page-ratio') === '150%', 'Test 1.3: Placeholder has correct --page-ratio');
    assert(placeholder.textContent === 'Page 1', 'Test 1.4: Placeholder shows correct page text');

    assert(container.dataset.loaded === 'false', 'Test 1.5: container.dataset.loaded set to false after unload');
}

// ============================================================
// Test 2: loaded='false' → no-op
// ============================================================
console.log('--- Test 2: loaded=false → no-op ---');
{
    const container = makeContainer(3, 'right', 'false');
    const childCountBefore = container.children.length;
    const imgBefore = container.querySelector('img');

    unloadPageImage(container);

    assert(container.children.length === childCountBefore, 'Test 2.1: No children removed when loaded=false');
    assert(container.querySelector('img') === imgBefore, 'Test 2.2: img element still present');
    assert(container.querySelector('.page-placeholder') === null, 'Test 2.3: No placeholder created');
    assert(container.dataset.loaded === 'false', 'Test 2.4: dataset.loaded still false');
}

// ============================================================
// Test 3: loaded unset → no-op
// ============================================================
console.log('--- Test 3: loaded unset → no-op ---');
{
    const container = makeContainer(5, 'left');
    const childCountBefore = container.children.length;

    unloadPageImage(container);

    assert(container.children.length === childCountBefore, 'Test 3.1: No children removed when loaded unset');
    assert(container.querySelector('img') !== null, 'Test 3.2: img element still present');
    assert(container.querySelector('.page-placeholder') === null, 'Test 3.3: No placeholder created');
    assert(container.dataset.loaded === undefined, 'Test 3.4: dataset.loaded remains undefined');
}

// ============================================================
// Test 4: loaded='error' → no-op
// ============================================================
console.log('--- Test 4: loaded=error → no-op ---');
{
    const container = makeContainer(7, 'right', 'error');
    const childCountBefore = container.children.length;

    unloadPageImage(container);

    assert(container.children.length === childCountBefore, 'Test 4.1: No children removed when loaded=error');
    assert(container.querySelector('img') !== null, 'Test 4.2: img element still present');
    assert(container.querySelector('.page-placeholder') === null, 'Test 4.3: No placeholder created');
    assert(container.dataset.loaded === 'error', 'Test 4.4: dataset.loaded still error');
}

// ============================================================
// Test 5: loaded='loading' → no-op
// ============================================================
console.log('--- Test 5: loaded=loading → no-op ---');
{
    const container = makeContainer(2, 'left', 'loading');
    const childCountBefore = container.children.length;

    unloadPageImage(container);

    assert(container.children.length === childCountBefore, 'Test 5.1: No children removed when loaded=loading');
    assert(container.querySelector('img') !== null, 'Test 5.2: img element still present');
    assert(container.dataset.loaded === 'loading', 'Test 5.3: dataset.loaded still loading');
}

// ============================================================
// Test 6: After unload, container can be re-loaded (dataset.loaded='false' allows it)
// ============================================================
console.log('--- Test 6: After unload, container state allows re-load ---');
{
    const container = makeContainer(4, 'left', 'true');

    unloadPageImage(container);

    assert(container.dataset.loaded === 'false', 'Test 6.1: dataset.loaded is false after unload');
    assert(container.dataset.loaded !== 'true', 'Test 6.2: A subsequent loadPageImage guard would allow loading');

    const img = container.querySelector('img');
    assert(img === null, 'Test 6.3: img is removed');

    const placeholder = container.querySelector('.page-placeholder');
    assert(placeholder !== null, 'Test 6.4: Placeholder exists for re-load');
}

// ============================================================
// Test 7: Placeholder has NO dataset.loaded set
// ============================================================
console.log('--- Test 7: Placeholder has no dataset.loaded ---');
{
    const container = makeContainer(8, 'right', 'true');

    unloadPageImage(container);

    const placeholder = container.querySelector('.page-placeholder');
    assert(placeholder !== null, 'Test 7.1: Placeholder created');
    assert(!placeholder.dataset.loaded, 'Test 7.2: Placeholder has NO dataset.loaded attribute');
}

// ============================================================
// Test 8: loaded='true' but no img → still early return (after guard pass, before img check)
// ============================================================
console.log('--- Test 8: loaded=true, no img → no-op on missing img ---');
{
    const container = document.createElement('div');
    container.className = 'page-container';
    container.dataset.page = '10';
    container.dataset.side = 'left';
    container.dataset.loaded = 'true';

    unloadPageImage(container);

    assert(container.children.length === 0, 'Test 8.1: No new children when img is missing');
    assert(container.dataset.loaded === 'true', 'Test 8.2: loaded stays true (no unload, img missing so no reset)');
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
