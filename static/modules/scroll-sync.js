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
            callbacks.length = 0;
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

    return { isScrollSettled, onSettle, dispose };
}

export function setupScrollSync({ left, right }) {
    let syncing = false;

    left.addEventListener('scroll', () => {
        if (!syncing) {
            syncing = true;
            right.scrollTop = left.scrollTop;
            requestAnimationFrame(() => {
                syncing = false;
            });
        }
    });
}

export function setupPageDetection({ container }, onPageChange) {
    container.addEventListener('scroll', () => {
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
{
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
