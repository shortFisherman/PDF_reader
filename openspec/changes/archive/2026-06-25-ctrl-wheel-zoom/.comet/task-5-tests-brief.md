# Task Group 5: Frontend Tests (tasks 5.1, 5.2, 5.3)

Add unit tests for the zoom module. Follow the existing test pattern from `lazy-loader.js` + `tests/run-lazy-loader-tests.mjs`.

## 5.1 — Inline tests in zoom.js

At the END of `static/modules/zoom.js`, add an inline test block (after the `setupZoom` function). Follow the pattern in `static/modules/lazy-loader.js` (line 74+):

```js
if (typeof window !== 'undefined' && window.__TEST_ZOOM__) {
    let passCount = 0;
    let failCount = 0;

    function assert(cond, msg) {
        if (cond) { passCount++; }
        else { failCount++; console.error('FAIL: ' + msg); }
    }

    // Test 1: setupZoom returns correct API
    const appEl = document.createElement('div');
    let lastZoom = null;
    const onZoomChange = (z) => { lastZoom = z; };
    const col = document.createElement('div');
    const instance = setupZoom({ columns: [col], appEl, onZoomChange });
    assert(typeof instance.resetZoom === 'function', 'resetZoom is a function');
    assert(typeof instance.getZoom === 'function', 'getZoom is a function');
    assert(typeof instance.dispose === 'function', 'dispose is a function');
    assert(instance.getZoom() === 1, 'initial zoom is 1');

    // Test 2: Non-Ctrl wheel does NOT zoom, does NOT call preventDefault
    let prevented = false;
    const nonCtrlEvent = new WheelEvent('wheel', { ctrlKey: false, deltaY: 100, cancelable: true });
    Object.defineProperty(nonCtrlEvent, 'preventDefault', { value: () => { prevented = true; } });
    col.dispatchEvent(nonCtrlEvent);
    assert(prevented === false, 'non-Ctrl wheel does NOT call preventDefault');
    assert(instance.getZoom() === 1, 'non-Ctrl wheel does not change zoom');
    assert(lastZoom === null, 'non-Ctrl wheel does not call onZoomChange');

    // Test 3: Ctrl+wheel down (deltaY > 0) → zoom out (decrease)
    const lastZoomBefore = lastZoom;
    const zoomBefore = instance.getZoom();
    const ctrlDownEvent = new WheelEvent('wheel', { ctrlKey: true, deltaY: 100, cancelable: true, clientX: 0, clientY: 0 });
    Object.defineProperty(ctrlDownEvent, 'preventDefault', { value: () => { prevented = true; } });
    prevented = false;
    col.dispatchEvent(ctrlDownEvent);
    assert(prevented === true, 'Ctrl wheel calls preventDefault');
    assert(instance.getZoom() < zoomBefore, 'Ctrl+down (deltaY>0) zooms OUT (decrease)');
    assert(lastZoom === instance.getZoom(), 'onZoomChange called with new zoom');

    // Test 4: Ctrl+wheel up (deltaY < 0) → zoom in (increase)
    const ctrlUpEvent = new WheelEvent('wheel', { ctrlKey: true, deltaY: -100, cancelable: true, clientX: 0, clientY: 0 });
    prevented = false;
    const zBeforeUp = instance.getZoom();
    col.dispatchEvent(ctrlUpEvent);
    assert(prevented === true, 'Ctrl+up calls preventDefault');
    assert(instance.getZoom() > zBeforeUp, 'Ctrl+up (deltaY<0) zooms IN (increase)');

    // Test 5: Range clamp — keep zooming out until MIN (0.25)
    while (instance.getZoom() > 0.25) {
        const evt = new WheelEvent('wheel', { ctrlKey: true, deltaY: 100, cancelable: true, clientX: 0, clientY: 0 });
        Object.defineProperty(evt, 'preventDefault', { value: () => {} });
        col.dispatchEvent(evt);
    }
    assert(instance.getZoom() === 0.25, 'clamped to MIN 0.25');
    // Try one more zoom out — should stay at 0.25 (no change)
    const zBefore = instance.getZoom();
    const extraOut = new WheelEvent('wheel', { ctrlKey: true, deltaY: 100, cancelable: true, clientX: 0, clientY: 0 });
    Object.defineProperty(extraOut, 'preventDefault', { value: () => {} });
    col.dispatchEvent(extraOut);
    assert(instance.getZoom() === zBefore, 'no change when already at MIN');

    // Test 6: Range clamp — zoom in until MAX (4)
    while (instance.getZoom() < 4) {
        const evt = new WheelEvent('wheel', { ctrlKey: true, deltaY: -100, cancelable: true, clientX: 0, clientY: 0 });
        Object.defineProperty(evt, 'preventDefault', { value: () => {} });
        col.dispatchEvent(evt);
    }
    assert(instance.getZoom() === 4, 'clamped to MAX 4');

    // Test 7: resetZoom returns to 1
    instance.resetZoom();
    assert(instance.getZoom() === 1, 'resetZoom returns zoom to 1');
    assert(lastZoom === 1, 'onZoomChange(1) called on reset');

    // Test 8: Anchor formula numeric verification
    // Set up known state: scrollTop=200, scrollLeft=100, clientWidth=800, clientHeight=600
    // Mouse at center: clientX=400, clientY=300 (relative to column)
    const col2 = document.createElement('div');
    Object.defineProperties(col2, {
        'scrollTop':          { value: 200, writable: true },
        'scrollLeft':         { value: 100, writable: true },
        'clientWidth':        { value: 800, writable: true },
        'clientHeight':       { value: 600, writable: true },
        'scrollHeight':       { value: 2000, writable: true },
        'scrollWidth':        { value: 800, writable: true },
        'getBoundingClientRect': { value: () => ({ left: 10, top: 10, right: 810, bottom: 610 }), writable: true },
    });
    const appEl2 = document.createElement('div');
    let zoomValue = null;
    const inst2 = setupZoom({ columns: [col2], appEl: appEl2, onZoomChange: z => { zoomValue = z; } });
    
    // Zoom in (deltaY=-100 → +0.1): zoom goes 1→1.1, r=1.1
    // cy = event.clientY(400) - rect.top(10) = 390
    // cx = event.clientX(400) - rect.left(10) = 390
    // newScrollTop = (200 + 390) * 1.1 - 390 = 590 * 1.1 - 390 = 649 - 390 = 259
    // newScrollLeft = (100 + 390) * 1.1 - 390 = 490 * 1.1 - 390 = 539 - 390 = 149
    const zoomInEvent = new WheelEvent('wheel', { ctrlKey: true, deltaY: -100, cancelable: true, clientX: 400, clientY: 400 });
    Object.defineProperty(zoomInEvent, 'preventDefault', { value: () => {} });
    col2.dispatchEvent(zoomInEvent);
    assert(Math.abs(col2.scrollTop - 259) < 1, 'anchor scrollTop correct (expected ~259, got ' + col2.scrollTop + ')');
    assert(Math.abs(col2.scrollLeft - 149) < 1, 'anchor scrollLeft correct (expected ~149, got ' + col2.scrollLeft + ')');
    assert(Math.abs(inst2.getZoom() - 1.1) < 0.001, 'zoom became 1.1');
    assert(Math.abs(zoomValue - 1.1) < 0.001, 'onZoomChange received 1.1');

    // Test 9: dispose removes listeners
    inst2.dispose();
    const zBeforeDisp = inst2.getZoom();
    const evtAfter = new WheelEvent('wheel', { ctrlKey: true, deltaY: -100, cancelable: true, clientX: 0, clientY: 0 });
    Object.defineProperty(evtAfter, 'preventDefault', { value: () => {} });
    col2.dispatchEvent(evtAfter);
    assert(inst2.getZoom() === zBeforeDisp, 'dispose removed listener, zoom unchanged');

    // Final report
    console.log(passCount + ' passed, ' + failCount + ' failed');
    if (failCount === 0) {
        globalThis.__ZOOM_TESTS_DONE__ = true;
    }
}
```

## 5.2 — Test runner: tests/run-zoom-tests.mjs

Create `tests/run-zoom-tests.mjs`. Follow the pattern from `tests/run-lazy-loader-tests.mjs`:

```js
import { JSDOM } from 'jsdom';
import { readFileSync } from 'fs';
import { resolve } from 'path';
import { fileURLToPath } from 'url';

const __dirname = fileURLToPath(new URL('.', import.meta.url));
const modulePath = resolve(__dirname, '..', 'static', 'modules', 'zoom.js');
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

jsdomWindow.__TEST_ZOOM__ = true;

code = code.replace(/^export\s+function\b/gm, 'function');
code = code.replace(/^export\s+const\b/gm, 'const');
code = code.replace(/^export\s+let\b/gm, 'let');
code = code.replace(/^export\s+var\b/gm, 'var');
code = code.replace(/^export\s+/gm, '');

try {
    const fn = new Function('window', 'document', 'globalThis', 'setTimeout', 'console', code);
    fn(jsdomWindow, jsdomWindow.document, globalThis, setTimeout, mockConsole);
} catch (e) {
    console.error('FAIL: module threw an error');
    console.error(e);
    process.exit(1);
}

if (globalThis.__ZOOM_TESTS_DONE__) {
    const output = errors.filter(e => !e.includes('FAIL:')).join('');
    console.log('ZOOM TESTS PASSED');
    if (errors.length > 0) {
        const failErrors = errors.filter(e => e.includes('FAIL:'));
        console.log(failErrors.length + ' failures:');
        failErrors.forEach(e => console.log('  ' + e));
        process.exit(1);
    }
    process.exit(0);
} else {
    console.error('ZOOM TESTS FAILED: __ZOOM_TESTS_DONE__ not set');
    process.exit(1);
}
```

## 5.3 — package.json script

In `package.json`, add to `"scripts"`:
```json
"test:zoom": "node tests/run-zoom-tests.mjs"
```

## Files to create/modify
- `static/modules/zoom.js` — append inline test block
- `tests/run-zoom-tests.mjs` — CREATE new file
- `package.json` — add test:zoom script

## Output
- Commit with message: `feat: add zoom unit tests and test:zoom script`
- Write report to `openspec/changes/ctrl-wheel-zoom/.comet/task-5-report.md`
- MUST provide RED/GREEN evidence:
  - RED: run `node tests/run-zoom-tests.mjs` BEFORE adding tests (should fail or not exist)
  - GREEN: run `node tests/run-zoom-tests.mjs` AFTER — all tests should pass
  - Also run regression: `npm run test:translator`, `node tests/run-lazy-loader-tests.mjs`, `node tests/run-task-4.5-tests.mjs`
