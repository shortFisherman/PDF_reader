/**
 * @param {HTMLElement} leftEl
 * @param {HTMLElement} rightEl
 * @returns {{ isScrollSettled: () => boolean, onSettle: (cb: () => void) => void, dispose: () => void }}
 */
export function createSettleGate(leftEl, rightEl) {
    const SETTLE_MS = 150;
    let settled = false;
    let timer = null;
    const callbacks = [];

    function reset() {
        settled = false;
        clearTimeout(timer);
        timer = setTimeout(() => {
            settled = true;
            const cbs = [...callbacks];
            cbs.forEach(cb => cb());
        }, SETTLE_MS);
    }

    leftEl.addEventListener('scroll', reset);
    rightEl.addEventListener('scroll', reset);

    function isScrollSettled() {
        return settled;
    }

    function onSettle(cb) {
        callbacks.push(cb);
    }

    function dispose() {
        clearTimeout(timer);
        leftEl.removeEventListener('scroll', reset);
        rightEl.removeEventListener('scroll', reset);
        callbacks.length = 0;
    }

    return {
        isScrollSettled, onSettle, dispose,
        trigger() {
            settled = true;
            const cbs = [...callbacks];
            cbs.forEach(cb => cb());
        },
    };
}

export function setupScrollSync({ left, right }) {
    let syncing = false;

    left.addEventListener('scroll', () => {
        if (syncing) return;
        const f = left.scrollHeight <= left.clientHeight ? 0
            : left.scrollTop / (left.scrollHeight - left.clientHeight);
        syncing = true;
        requestAnimationFrame(() => {
            right.scrollTop = f * (right.scrollHeight - right.clientHeight);
            syncing = false;
        });
    });

    right.addEventListener('scroll', () => {
        if (syncing) return;
        const f = right.scrollHeight <= right.clientHeight ? 0
            : right.scrollTop / (right.scrollHeight - right.clientHeight);
        syncing = true;
        requestAnimationFrame(() => {
            left.scrollTop = f * (left.scrollHeight - left.clientHeight);
            syncing = false;
        });
    });
}

export function setupPageDetection({ container, settle }, onPageChange) {
    settle.onSettle(() => {
        const containers = container.querySelectorAll('.page-container');
        let bestPage = 0;
        let bestCoverage = 0;
        const viewTop = container.scrollTop;
        const viewBottom = viewTop + container.clientHeight;

        containers.forEach(c => {
            const rect = c.getBoundingClientRect();
            const colRect = container.getBoundingClientRect();
            const top = rect.top - colRect.top + container.scrollTop;
            const bottom = top + rect.height;
            const overlap = Math.min(bottom, viewBottom) - Math.max(top, viewTop);
            const coverage = overlap / rect.height;
            if (coverage > bestCoverage) {
                bestCoverage = coverage;
                bestPage = parseInt(c.dataset.page);
            }
        });

        onPageChange(bestPage);
    });
}

// === Tests for createSettleGate ===
if (typeof window !== 'undefined' && window.__TEST_CREATE_SETTLE_GATE__) {
    if (typeof createSettleGate !== 'function') {
        console.error('FAIL: createSettleGate is not defined');
        console.log('0 passed, 3 FAILED (RED phase)');
    } else {
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

        function done(remaining) {
            if (remaining <= 0) {
                if (failCount === 0) {
                    console.log(`All ${passCount} tests PASSED`);
                } else {
                    console.log(`${passCount} passed, ${failCount} FAILED`);
                }
                globalThis.__SETTLE_GATE_TESTS_DONE__ = true;
            }
        }

        let pending = 3;

        // Test 1: After scroll, isScrollSettled() returns false; after 150ms, returns true and callback fires
        {
            const left = document.createElement('div');
            const right = document.createElement('div');
            const gate = createSettleGate(left, right);
            let called = false;
            gate.onSettle(() => { called = true; });
            left.dispatchEvent(new Event('scroll'));
            assert(gate.isScrollSettled() === false, 'Test 1: After scroll, should not be settled');
            setTimeout(() => {
                assert(gate.isScrollSettled() === true, 'Test 1: After settle time, should be settled');
                assert(called === true, 'Test 1: Callback should have been called');
                gate.dispose();
                pending--;
                done(pending);
            }, 200);
        }

        // Test 2: Multiple scrolls reset timer — callback fires only after last scroll + 150ms
        {
            const left = document.createElement('div');
            const right = document.createElement('div');
            const gate2 = createSettleGate(left, right);
            let callCount = 0;
            gate2.onSettle(() => { callCount++; });
            left.dispatchEvent(new Event('scroll'));
            setTimeout(() => {
                right.dispatchEvent(new Event('scroll'));
            }, 50);
            setTimeout(() => {
                assert(callCount === 1, 'Test 2: Callback should fire only once after final settle');
                assert(gate2.isScrollSettled() === true, 'Test 2: After settle, isScrollSettled should be true');
                gate2.dispose();
                pending--;
                done(pending);
            }, 300);
        }

        // Test 3: dispose() removes listeners — events after dispose don't reset timer
        {
            const left = document.createElement('div');
            const right = document.createElement('div');
            const gate3 = createSettleGate(left, right);
            gate3.dispose();
            left.dispatchEvent(new Event('scroll'));
            setTimeout(() => {
                assert(gate3.isScrollSettled() === false, 'Test 3: After dispose + scroll, should not settle (no listeners)');
                pending--;
                done(pending);
            }, 200);
        }
    }
}

// === Tests for setupPageDetection ===
if (typeof window !== 'undefined' && window.__TEST_SETUP_PAGE_DETECTION__) {
    if (typeof setupPageDetection !== 'function') {
        console.error('FAIL: setupPageDetection is not defined');
        console.log('0 passed, 3 FAILED (RED phase)');
    } else {
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

        function done(remaining) {
            if (remaining <= 0) {
                if (failCount === 0) {
                    console.log(`All ${passCount} tests PASSED`);
                } else {
                    console.log(`${passCount} passed, ${failCount} FAILED`);
                }
                globalThis.__PAGE_DETECTION_TESTS_DONE__ = true;
            }
        }

        let pending = 3;

        // Test 1: setupPageDetection fires callback on settle
        {
            const container = document.createElement('div');
            let settledCb = null;
            const settle = {
                onSettle(cb) { settledCb = cb; },
            };
            let calledPage = -1;
            setupPageDetection({ container, settle }, (page) => { calledPage = page; });

            // settle has not been triggered yet
            assert(calledPage === -1, 'Test 1: Callback should NOT fire before settle');

            // trigger settle
            if (settledCb) settledCb();
            assert(calledPage === 0, 'Test 1: Callback should fire on settle (calledPage was ' + calledPage + ')');

            pending--;
            done(pending);
        }

        // Test 2: setupPageDetection does NOT fire during scrolls (only on settle)
        {
            const container = document.createElement('div');
            let settledCb = null;
            const settle = {
                onSettle(cb) { settledCb = cb; },
            };
            let callCount = 0;
            setupPageDetection({ container, settle }, () => { callCount++; });

            // dispatch scroll events — these should NOT trigger the callback
            container.dispatchEvent(new Event('scroll'));
            container.dispatchEvent(new Event('scroll'));
            container.dispatchEvent(new Event('scroll'));
            assert(callCount === 0, 'Test 2: Callback should NOT fire during scrolls (got ' + callCount + ' calls)');

            // trigger settle — callback should fire now
            if (settledCb) settledCb();
            assert(callCount === 1, 'Test 2: Callback should fire exactly once on settle (got ' + callCount + ' calls)');

            pending--;
            done(pending);
        }

        // Test 3: Correct page selected based on >50% viewport coverage
        {
            const container = document.createElement('div');
            Object.defineProperty(container, 'clientHeight', { value: 400, configurable: true });
            // scrolled 350px down — page 0 mostly offscreen, page 1 has ~83% coverage
            container.scrollTop = 350;

            // Page 0: content at 0-300, scrolled past → rect.top in viewport = 0 - 350 = -350
            const page0 = document.createElement('div');
            page0.className = 'page-container';
            page0.dataset.page = '0';
            page0.style.height = '300px';
            page0.getBoundingClientRect = () => ({ top: -350, bottom: -50, height: 300, left: 0, right: 100, width: 100, x: 0, y: -350 });

            // Page 1: content at 300-600, partially visible → rect.top = 300 - 350 = -50
            const page1 = document.createElement('div');
            page1.className = 'page-container';
            page1.dataset.page = '1';
            page1.style.height = '300px';
            page1.getBoundingClientRect = () => ({ top: -50, bottom: 250, height: 300, left: 0, right: 100, width: 100, x: 0, y: -50 });

            // Page 2: content at 600-900, partially visible → rect.top = 600 - 350 = 250
            const page2 = document.createElement('div');
            page2.className = 'page-container';
            page2.dataset.page = '2';
            page2.style.height = '300px';
            page2.getBoundingClientRect = () => ({ top: 250, bottom: 550, height: 300, left: 0, right: 100, width: 100, x: 0, y: 250 });

            // Page 3: content at 900-1200, offscreen → rect.top = 900 - 350 = 550
            const page3 = document.createElement('div');
            page3.className = 'page-container';
            page3.dataset.page = '3';
            page3.style.height = '300px';
            page3.getBoundingClientRect = () => ({ top: 550, bottom: 850, height: 300, left: 0, right: 100, width: 100, x: 0, y: 550 });

            container.appendChild(page0);
            container.appendChild(page1);
            container.appendChild(page2);
            container.appendChild(page3);

            container.getBoundingClientRect = () => ({ top: 0, bottom: 400, height: 400, left: 0, right: 100, width: 100, x: 0, y: 0 });

            let settledCb = null;
            const settle = {
                onSettle(cb) { settledCb = cb; },
            };
            let detectedPage = -1;
            setupPageDetection({ container, settle }, (page) => { detectedPage = page; });

            if (settledCb) settledCb();
            // Page 1 coverage: rect.top=-50, top=-50-0+350=300, bottom=600
            //   viewport 350-750, overlap=min(600,750)-max(300,350)=600-350=250, coverage=250/300=0.83
            assert(detectedPage === 1, 'Test 3: Should select page 1 (~83% coverage). Got page ' + detectedPage);

            pending--;
            done(pending);
        }
    }
}

