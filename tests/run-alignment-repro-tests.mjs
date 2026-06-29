import { JSDOM } from 'jsdom';
import { readFileSync } from 'fs';
import { resolve } from 'path';
import { fileURLToPath } from 'url';

const __dirname = fileURLToPath(new URL('.', import.meta.url));

const scrollSyncPath = resolve(__dirname, '..', 'static', 'modules', 'scroll-sync.js');
const zoomPath = resolve(__dirname, '..', 'static', 'modules', 'zoom.js');
const translationFixturePath = resolve(__dirname, '..', 'static', 'modules', '__tests__', 'translation-misalign-fixture.js');
const zoomFixturePath = resolve(__dirname, '..', 'static', 'modules', '__tests__', 'zoom-misalign-fixture.js');

const scrollSyncSrc = readFileSync(scrollSyncPath, 'utf-8');
const zoomSrc = readFileSync(zoomPath, 'utf-8');

function stripExports(code) {
    return code
        .replace(/^export\s+function\b/gm, 'function')
        .replace(/^export\s+const\b/gm, 'const')
        .replace(/^export\s+let\b/gm, 'let')
        .replace(/^export\s+var\b/gm, 'var')
        .replace(/^export\s+/gm, '');
}

const scrollSyncCode = stripExports(scrollSyncSrc);
const zoomCode = stripExports(zoomSrc);

let allPassed = true;

// ============================================================
// Test 1: Translation Misalignment
// ============================================================
{
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

    let fixtureCode = readFileSync(translationFixturePath, 'utf-8');
    fixtureCode = stripExports(fixtureCode);

    const combinedCode = scrollSyncCode + '\n;' + fixtureCode;

    try {
        const fn = new Function('window', 'document', 'globalThis', 'setTimeout', 'console', combinedCode);
        fn(jsdomWindow, jsdomWindow.document, globalThis, setTimeout, mockConsole);
    } catch (e) {
        errors.push('Execution error: ' + e.message + '\n' + e.stack);
    }

    console.log('=== Test 1: Translation Misalignment ===');
    for (const log of logs) console.log(log);
    for (const err of errors) console.error(err);

    if (globalThis.__ALIGN_REPRO_TRANSLATION_DONE__) {
        const allText = [...logs, ...errors].join('\n');
        if (allText.includes('FAILED') || allText.includes('FAIL:')) {
            console.log('Test 1 result: FAIL (RED phase - expected)');
        } else {
            console.log('Test 1 result: PASS');
            allPassed = false;
        }
    } else {
        console.log('Test 1 result: INCOMPLETE (__ALIGN_REPRO_TRANSLATION_DONE__ not set)');
        allPassed = false;
    }
}

// ============================================================
// Test 2: Zoom Misalignment
// ============================================================
{
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
    globalThis.WheelEvent = jsdomWindow.WheelEvent;

    const logs = [];
    const errors = [];
    const mockConsole = {
        log: (...args) => logs.push(args.join(' ')),
        error: (...args) => errors.push(args.join(' ')),
    };

    jsdomWindow.__TEST_ALIGN_REPRO_ZOOM__ = true;

    let zoomFixtureCode = readFileSync(zoomFixturePath, 'utf-8');
    zoomFixtureCode = stripExports(zoomFixtureCode);

    const combinedCode = scrollSyncCode + '\n;' + zoomCode + '\n;' + zoomFixtureCode;

    try {
        const fn = new Function('window', 'document', 'globalThis', 'setTimeout', 'console', combinedCode);
        fn(jsdomWindow, jsdomWindow.document, globalThis, setTimeout, mockConsole);
    } catch (e) {
        errors.push('Execution error: ' + e.message + '\n' + e.stack);
    }

    console.log('\n=== Test 2: Zoom Misalignment ===');
    for (const log of logs) console.log(log);
    for (const err of errors) console.error(err);

    if (globalThis.__ALIGN_REPRO_ZOOM_DONE__) {
        const allText = [...logs, ...errors].join('\n');
        if (allText.includes('FAILED') || allText.includes('FAIL:')) {
            console.log('Test 2 result: FAIL (RED phase - expected)');
        } else {
            console.log('Test 2 result: PASS');
            allPassed = false;
        }
    } else {
        console.log('Test 2 result: INCOMPLETE (__ALIGN_REPRO_ZOOM_DONE__ not set)');
        allPassed = false;
    }
}

console.log('\n=== Summary ===');
console.log('Translation misalign (task 1.1): should be RED');
console.log('Zoom misalign (task 1.2): should be RED');
console.log('Both tests being RED is the expected TDD RED phase outcome.');

process.exit(allPassed ? 1 : 1);

