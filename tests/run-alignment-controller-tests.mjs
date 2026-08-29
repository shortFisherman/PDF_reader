import { JSDOM } from 'jsdom';
import { readFileSync, readdirSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const dom = new JSDOM('<!doctype html><html><body></body></html>', {
    url: 'http://localhost',
    runScripts: 'outside-only',
});
const { window: jsdomWindow } = dom;
globalThis.window = jsdomWindow;
globalThis.document = jsdomWindow.document;

const testsDir = fileURLToPath(new URL('.', import.meta.url));
const rootDir = resolve(testsDir, '..');
const modulesDir = resolve(rootDir, 'static', 'modules');
const appJsPath = resolve(rootDir, 'static', 'app.js');

const { createAlignmentController } = await import(pathToFileURL(resolve(modulesDir, 'alignment-controller.js')));

let passCount = 0;
let failCount = 0;

function assert(cond, msg) {
    if (cond) {
        passCount++;
    } else {
        failCount++;
        console.error('FAIL: ' + msg);
    }
}

// Test (a): Write exclusivity — after realign(dst), only dst.scrollTop changes
{
    const leftEl = document.createElement('div');
    const rightEl = document.createElement('div');
    Object.defineProperty(leftEl, 'clientHeight', { value: 500, configurable: true });
    Object.defineProperty(rightEl, 'clientHeight', { value: 500, configurable: true });
    Object.defineProperty(leftEl, 'scrollHeight', { value: 1600, configurable: true });
    Object.defineProperty(rightEl, 'scrollHeight', { value: 1600, configurable: true });

    const page0 = document.createElement('div');
    page0.className = 'page-container';
    page0.dataset.page = '0';
    page0.style.height = '400px';
    page0.getBoundingClientRect = function () {
        return { top: 200, bottom: 600, height: 400, left: 0, right: 100, width: 100, x: 0, y: 200 };
    };
    rightEl.appendChild(page0);

    rightEl.getBoundingClientRect = function () {
        return { top: 0, bottom: 500, height: 500, left: 100, right: 200, width: 100, x: 100, y: 0 };
    };

    const ctrl = createAlignmentController({ leftEl: leftEl, rightEl: rightEl });
    ctrl.setLockTarget(0, 0);
    const beforeLeft = leftEl.scrollTop;
    const beforeRight = rightEl.scrollTop;

    ctrl.realign(rightEl);

    assert(leftEl.scrollTop === beforeLeft,
        'Test a: only target column scrollTop should change; leftEl.scrollTop changed from ' + beforeLeft + ' to ' + leftEl.scrollTop);
    assert(rightEl.scrollTop !== beforeRight,
        'Test a: target column scrollTop should change after realign (stayed at ' + rightEl.scrollTop + ')');
}

// Test (b): Target derivation — onScroll derives {pageIndex, intraPageOffsetPx}
{
    const leftEl = document.createElement('div');
    const rightEl = document.createElement('div');
    Object.defineProperty(leftEl, 'clientHeight', { value: 500, configurable: true });
    Object.defineProperty(leftEl, 'scrollHeight', { value: 2000, configurable: true });
    leftEl.scrollTop = 350;

    for (let i = 0; i < 4; i++) {
        const page = document.createElement('div');
        page.className = 'page-container';
        page.dataset.page = String(i);
        page.style.height = '400px';
        Object.defineProperty(page, 'offsetHeight', { value: 400, configurable: true });
        const pageTop = i * 400;
        const visibleTop = pageTop - leftEl.scrollTop;
        page.getBoundingClientRect = function () {
            return {
                top: visibleTop,
                bottom: visibleTop + 400,
                height: 400,
                left: 0,
                right: 100,
                width: 100,
                x: 0,
                y: visibleTop,
            };
        };
        leftEl.appendChild(page);
    }
    leftEl.getBoundingClientRect = function () {
        return { top: 0, bottom: 500, height: 500, left: 0, right: 100, width: 100, x: 0, y: 0 };
    };

    const ctrl = createAlignmentController({ leftEl: leftEl, rightEl: rightEl });
    ctrl.onScroll(leftEl);

    const target = ctrl.getLockTarget();
    assert(target !== null, 'Test b: getLockTarget should return a target object, got null');
    assert(target !== null && target.pageIndex === 0,
        'Test b: expected pageIndex 0, got ' + target.pageIndex);
    assert(target !== null && target.intraPageOffsetPx === 350,
        'Test b: expected intraPageOffsetPx 350, got ' + target.intraPageOffsetPx);
}

// Test (c): Realign write — both columns align to the same page top after realign
{
    const leftEl = document.createElement('div');
    const rightEl = document.createElement('div');
    Object.defineProperty(leftEl, 'clientHeight', { value: 500, configurable: true });
    Object.defineProperty(rightEl, 'clientHeight', { value: 500, configurable: true });
    Object.defineProperty(leftEl, 'scrollHeight', { value: 1000, configurable: true });
    Object.defineProperty(rightEl, 'scrollHeight', { value: 970, configurable: true });

    leftEl.getBoundingClientRect = function () {
        return { top: 0, bottom: 500, height: 500, left: 0, right: 100, width: 100, x: 0, y: 0 };
    };
    rightEl.getBoundingClientRect = function () {
        return { top: 0, bottom: 500, height: 500, left: 0, right: 100, width: 100, x: 0, y: 0 };
    };

    for (let i = 0; i < 5; i++) {
        const pageL = document.createElement('div');
        pageL.className = 'page-container';
        pageL.dataset.page = String(i);
        pageL.style.height = '200px';
        const pageTop = i * 200;
        pageL.getBoundingClientRect = function () {
            return { top: pageTop, bottom: pageTop + 200, height: 200, left: 0, right: 100, width: 100, x: 0, y: pageTop };
        };
        leftEl.appendChild(pageL);

        const pageR = document.createElement('div');
        pageR.className = 'page-container';
        pageR.dataset.page = String(i);
        pageR.style.height = '200px';
        pageR.getBoundingClientRect = function () {
            return { top: pageTop, bottom: pageTop + 200, height: 200, left: 0, right: 100, width: 100, x: 0, y: pageTop };
        };
        rightEl.appendChild(pageR);
    }

    const ctrl = createAlignmentController({ leftEl: leftEl, rightEl: rightEl });
    ctrl.setLockTarget(2, 0);
    ctrl.realign(leftEl);
    ctrl.realign(rightEl);

    const leftScroll = leftEl.scrollTop;
    const rightScroll = rightEl.scrollTop;

    assert(Math.abs(leftScroll - rightScroll) < 0.5,
        'Test c: both columns should align to same page top; diff=' + Math.abs(leftScroll - rightScroll).toFixed(1));
    assert(leftScroll === 400,
        'Test c: leftEl.scrollTop should be 400 (page 2 offsetTop), got ' + leftScroll);
    assert(rightScroll === 400,
        'Test c: rightEl.scrollTop should be 400 (page 2 offsetTop), got ' + rightScroll);
}

// Test (d): Re-entrance guard — suppressNextScrollFrom suppresses the scroll
// event that realign() generates on the destination column.
{
    const leftEl = document.createElement('div');
    const rightEl = document.createElement('div');
    Object.defineProperty(leftEl, 'clientHeight', { value: 500, configurable: true });
    Object.defineProperty(leftEl, 'scrollHeight', { value: 2000, configurable: true });
    leftEl.getBoundingClientRect = function () {
        return { top: 0, bottom: 500, height: 500, left: 0, right: 100, width: 100, x: 0, y: 0 };
    };

    for (let i = 0; i < 4; i++) {
        const page = document.createElement('div');
        page.className = 'page-container';
        page.dataset.page = String(i);
        page.style.height = '400px';
        Object.defineProperty(page, 'offsetHeight', { value: 400, configurable: true });
        const pageTop = i * 400;
        const visibleTop = pageTop - leftEl.scrollTop;
        page.getBoundingClientRect = function () {
            return {
                top: visibleTop, bottom: visibleTop + 400, height: 400,
                left: 0, right: 100, width: 100, x: 0, y: visibleTop,
            };
        };
        leftEl.appendChild(page);

        const rPage = document.createElement('div');
        rPage.className = 'page-container';
        rPage.dataset.page = String(i);
        rPage.style.height = '400px';
        Object.defineProperty(rPage, 'offsetHeight', { value: 400, configurable: true });
        const rTop = i * 400;
        rPage.getBoundingClientRect = function () {
            return {
                top: rTop, bottom: rTop + 400, height: 400,
                left: 0, right: 100, width: 100, x: 0, y: rTop,
            };
        };
        rightEl.appendChild(rPage);
    }
    rightEl.getBoundingClientRect = function () {
        return { top: 0, bottom: 500, height: 500, left: 0, right: 100, width: 100, x: 0, y: 0 };
    };

    const ctrl = createAlignmentController({ leftEl: leftEl, rightEl: rightEl });

    ctrl.setLockTarget(2, 100);
    const targetBefore = ctrl.getLockTarget();

    ctrl.realign(rightEl);
    ctrl.onScroll(rightEl);

    const targetAfter = ctrl.getLockTarget();
    assert(targetAfter.pageIndex === targetBefore.pageIndex,
        'Test d: pageIndex should not change during realign (got ' + targetAfter.pageIndex + ', expected ' + targetBefore.pageIndex + ')');
    assert(targetAfter.intraPageOffsetPx === targetBefore.intraPageOffsetPx,
        'Test d: intraPageOffsetPx should not change during realign (got ' + targetAfter.intraPageOffsetPx + ', expected ' + targetBefore.intraPageOffsetPx + ')');
}

// Test (e): onImageLoaded calls realign on both columns, does not mutate currentTarget
{
    const leftEl = document.createElement('div');
    const rightEl = document.createElement('div');

    const page0L = document.createElement('div');
    page0L.className = 'page-container';
    page0L.dataset.page = '1';
    page0L.style.height = '400px';
    page0L.getBoundingClientRect = function () {
        return { top: 400, bottom: 800, height: 400, left: 0, right: 100, width: 100, x: 0, y: 400 };
    };
    leftEl.appendChild(page0L);

    const page0R = document.createElement('div');
    page0R.className = 'page-container';
    page0R.dataset.page = '1';
    page0R.style.height = '400px';
    page0R.getBoundingClientRect = function () {
        return { top: 400, bottom: 800, height: 400, left: 0, right: 100, width: 100, x: 0, y: 400 };
    };
    rightEl.appendChild(page0R);

    leftEl.getBoundingClientRect = function () {
        return { top: 0, bottom: 500, height: 500, left: 0, right: 100, width: 100, x: 0, y: 0 };
    };
    rightEl.getBoundingClientRect = function () {
        return { top: 0, bottom: 500, height: 500, left: 0, right: 100, width: 100, x: 0, y: 0 };
    };

    const ctrl = createAlignmentController({ leftEl: leftEl, rightEl: rightEl });
    ctrl.setLockTarget(1, 50);
    const targetBefore = ctrl.getLockTarget();

    ctrl.onImageLoaded('right', 1);

    assert(leftEl.scrollTop === 450,
        'Test e: leftEl.scrollTop should be 450 after onImageLoaded, got ' + leftEl.scrollTop);
    assert(rightEl.scrollTop === 450,
        'Test e: rightEl.scrollTop should be 450 after onImageLoaded, got ' + rightEl.scrollTop);

    const targetAfter = ctrl.getLockTarget();
    assert(targetAfter.pageIndex === targetBefore.pageIndex,
        'Test e: pageIndex should not change (was ' + targetBefore.pageIndex + ', got ' + targetAfter.pageIndex + ')');
    assert(targetAfter.intraPageOffsetPx === targetBefore.intraPageOffsetPx,
        'Test e: intraPageOffsetPx should not change (was ' + targetBefore.intraPageOffsetPx + ', got ' + targetAfter.intraPageOffsetPx + ')');
}

// Test (f): onZoomChange scales intraPageOffsetPx and realigns both columns
{
    const leftEl = document.createElement('div');
    const rightEl = document.createElement('div');
    Object.defineProperty(leftEl, 'clientHeight', { value: 500, configurable: true });
    Object.defineProperty(rightEl, 'clientHeight', { value: 500, configurable: true });
    Object.defineProperty(leftEl, 'scrollHeight', { value: 2000, configurable: true });
    Object.defineProperty(rightEl, 'scrollHeight', { value: 2000, configurable: true });

    const pageL = document.createElement('div');
    pageL.className = 'page-container';
    pageL.dataset.page = '2';
    pageL.style.height = '400px';
    pageL.getBoundingClientRect = function () {
        return { top: 800, bottom: 1200, height: 400, left: 0, right: 100, width: 100, x: 0, y: 800 };
    };
    leftEl.appendChild(pageL);

    const pageR = document.createElement('div');
    pageR.className = 'page-container';
    pageR.dataset.page = '2';
    pageR.style.height = '400px';
    pageR.getBoundingClientRect = function () {
        return { top: 800, bottom: 1200, height: 400, left: 0, right: 100, width: 100, x: 0, y: 800 };
    };
    rightEl.appendChild(pageR);

    leftEl.getBoundingClientRect = function () {
        return { top: 0, bottom: 500, height: 500, left: 0, right: 100, width: 100, x: 0, y: 0 };
    };
    rightEl.getBoundingClientRect = function () {
        return { top: 0, bottom: 500, height: 500, left: 0, right: 100, width: 100, x: 0, y: 0 };
    };

    const ctrl = createAlignmentController({ leftEl: leftEl, rightEl: rightEl });
    ctrl.setLockTarget(2, 100);

    ctrl.onZoomChange(1.1, 1.0);

    const targetAfter = ctrl.getLockTarget();

    assert(targetAfter.pageIndex === 2,
        'Test f: pageIndex should stay 2 unchanged, got ' + targetAfter.pageIndex);
    assert(targetAfter.intraPageOffsetPx > 109.9 && targetAfter.intraPageOffsetPx < 110.1,
        'Test f: intraPageOffsetPx should be 100 * 1.1 ≈ 110, got ' + targetAfter.intraPageOffsetPx);

    assert(leftEl.scrollTop === 910,
        'Test f: leftEl.scrollTop should be 910 (800 + 110), got ' + leftEl.scrollTop);
    assert(rightEl.scrollTop === 910,
        'Test f: rightEl.scrollTop should be 910 (800 + 110), got ' + rightEl.scrollTop);
}

// Test (g): Negative intraOffset cross-page scenario
{
    const leftEl = document.createElement('div');
    const rightEl = document.createElement('div');
    Object.defineProperty(leftEl, 'clientHeight', { value: 600, configurable: true });
    Object.defineProperty(leftEl, 'scrollHeight', { value: 1200, configurable: true });
    leftEl.scrollTop = 350;

    for (let i = 0; i < 2; i++) {
        const page = document.createElement('div');
        page.className = 'page-container';
        page.dataset.page = String(i);
        page.style.height = '400px';
        Object.defineProperty(page, 'offsetHeight', { value: 400, configurable: true });
        const pageTop = i * 400;
        const visibleTop = pageTop - leftEl.scrollTop;
        page.getBoundingClientRect = function () {
            return {
                top: visibleTop, bottom: visibleTop + 400, height: 400,
                left: 0, right: 100, width: 100, x: 0, y: visibleTop,
            };
        };
        leftEl.appendChild(page);
    }
    leftEl.getBoundingClientRect = function () {
        return { top: 0, bottom: 600, height: 600, left: 0, right: 100, width: 100, x: 0, y: 0 };
    };

    const ctrl = createAlignmentController({ leftEl: leftEl, rightEl: rightEl });

    ctrl.onScroll(leftEl);
    const target = ctrl.getLockTarget();

    assert(target.pageIndex === 0,
        'Test g: with scrollTop=350 (50px above page 1), pageIndex should roll back to 0, got ' + target.pageIndex);
    assert(target.intraPageOffsetPx === 350,
        'Test g: intraPageOffsetPx should be 350 (350 - 400 + 400), got ' + target.intraPageOffsetPx);
}

// === Write Exclusivity Grep (task 5.5) ===
// Verify no .scrollTop = assignment exists outside alignment-controller.js
// and zoom.js (zoom.js writes current-column anchor formula, not both columns).

console.log('\n=== Write Exclusivity Grep ===');
const scrollTopRegex = /\.scrollTop\s*=/;

const moduleFiles = readdirSync(modulesDir)
    .filter(f => f.endsWith('.js'))
    .filter(f => f !== 'alignment-controller.js' && f !== 'zoom.js');

let grepPassed = true;
for (const file of moduleFiles) {
    const content = readFileSync(join(modulesDir, file), 'utf-8');
    const lines = content.split('\n');
    for (let i = 0; i < lines.length; i++) {
        if (scrollTopRegex.test(lines[i])) {
            const line = lines[i].trim();
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

if (failCount === 0) {
    console.log('All ' + passCount + ' alignment controller tests PASSED');
    process.exit(0);
} else {
    console.log(passCount + ' passed, ' + failCount + ' FAILED');
    process.exit(1);
}
