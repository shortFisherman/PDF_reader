const BUF = 2;

function isWithinViewportBuffer(container, bufPages) {
    const col = container.closest('.column');
    if (!col) return false;
    const colRect = col.getBoundingClientRect();
    const containerRect = container.getBoundingClientRect();
    const containerHeight = containerRect.height || 1;

    const viewTop = colRect.top;
    const viewBottom = colRect.bottom;
    const bufTop = viewTop - bufPages * containerHeight;
    const bufBottom = viewBottom + bufPages * containerHeight;

    return containerRect.bottom >= bufTop && containerRect.top <= bufBottom;
}

export function setupIntersectionObserver({ load, unload, settle }) {
    const pendingLoad = new Set();
    const pendingReclaim = new Set();

    const observer = new IntersectionObserver((entries) => {
        for (const entry of entries) {
            const container = entry.target;
            if (entry.isIntersecting) {
                pendingLoad.add(container);
            } else {
                pendingReclaim.add(container);
            }
        }
        // DO NOT call load/unload here — defer to settle scan
    }, {
        root: null,
        rootMargin: `${BUF * 100}% 0px`,
    });

    const allContainers = document.querySelectorAll('.page-container');
    allContainers.forEach(c => observer.observe(c));

    settle.onSettle(() => {
        for (const container of [...pendingLoad]) {
            pendingLoad.delete(container);
            if (isWithinViewportBuffer(container, BUF)) {
                load(container);
            }
        }
    });

    // Return observer so it can be disconnected later if needed
    return { observer, pendingLoad, pendingReclaim };
}

// === Tests for setupIntersectionObserver (IO callback as candidate marker) ===
if (typeof window !== 'undefined' && window.__TEST_SETUP_INTERSECTION_OBSERVER__) {
    if (typeof setupIntersectionObserver !== 'function') {
        console.error('FAIL: setupIntersectionObserver is not defined');
        console.log('0 passed, 0 FAILED (RED phase)');
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

        const intersectingEl = document.createElement('div');
        intersectingEl.className = 'page-container';
        intersectingEl.dataset.page = '0';
        intersectingEl.dataset.side = 'left';
        document.body.appendChild(intersectingEl);

        const nonIntersectingEl = document.createElement('div');
        nonIntersectingEl.className = 'page-container';
        nonIntersectingEl.dataset.page = '1';
        nonIntersectingEl.dataset.side = 'right';
        document.body.appendChild(nonIntersectingEl);

        const OriginalIO = globalThis.IntersectionObserver;
        let capturedCallback = null;
        let capturedOptions = null;
        let observeCalls = [];

        globalThis.IntersectionObserver = function (cb, opts) {
            capturedCallback = cb;
            capturedOptions = opts;
            this.observe = function (el) { observeCalls.push(el); };
            this.unobserve = function () {};
            this.disconnect = function () {};
        };

        let loadCallCount = 0;
        let unloadCallCount = 0;
        const mockLoad = () => { loadCallCount++; };
        const mockUnload = () => { unloadCallCount++; };
        const mockSettle = { isScrollSettled: () => true, onSettle: () => {} };

        try {
            const result = setupIntersectionObserver({
                load: mockLoad,
                unload: mockUnload,
                settle: mockSettle,
            });

            // Test 1: Returns expected shape
            assert(result !== undefined, 'Test 1a: setupIntersectionObserver returns a value');
            assert(result.observer !== undefined, 'Test 1b: returned object has observer');
            assert(result.pendingLoad instanceof Set, 'Test 1c: returned object has pendingLoad Set');
            assert(result.pendingReclaim instanceof Set, 'Test 1d: returned object has pendingReclaim Set');

            // Test 2: rootMargin is 200% 0px
            assert(
                capturedOptions && capturedOptions.rootMargin === '200% 0px',
                'Test 2: rootMargin is 200% 0px'
            );

            // Simulate IO callback firing
            capturedCallback([
                { target: intersectingEl, isIntersecting: true },
                { target: nonIntersectingEl, isIntersecting: false },
            ]);

            // Test 3: load/unload NOT called from IO callback
            assert(loadCallCount === 0, 'Test 3a: load was NOT called from IO callback');
            assert(unloadCallCount === 0, 'Test 3b: unload was NOT called from IO callback');

            // Test 4: Intersecting → pendingLoad set
            assert(result.pendingLoad.has(intersectingEl), 'Test 4a: intersecting element in pendingLoad');
            assert(!result.pendingReclaim.has(intersectingEl), 'Test 4b: intersecting element NOT in pendingReclaim');

            // Test 5: Non-intersecting → pendingReclaim set
            assert(result.pendingReclaim.has(nonIntersectingEl), 'Test 5a: non-intersecting element in pendingReclaim');
            assert(!result.pendingLoad.has(nonIntersectingEl), 'Test 5b: non-intersecting element NOT in pendingLoad');

            // Test 6: Destructured params include settle
            {
                const src = setupIntersectionObserver.toString();
                const match = src.match(/\{([^}]+)\}/);
                const params = match ? match[1] : '';
                assert(params.includes('settle'), 'Test 6: setupIntersectionObserver destructured params include settle');
            }
        } catch (e) {
            assert(false, 'Exception: ' + e.message);
        }

        globalThis.IntersectionObserver = OriginalIO;
        document.body.removeChild(intersectingEl);
        document.body.removeChild(nonIntersectingEl);

        if (failCount === 0) {
            console.log('All ' + passCount + ' tests PASSED');
        } else {
            console.log(passCount + ' passed, ' + failCount + ' FAILED');
        }
        globalThis.__SETUP_IO_TESTS_DONE__ = true;
    }
}

// === Tests for settle scan (Task 4.2) ===
if (typeof window !== 'undefined' && window.__TEST_SETTLE_SCAN__) {
    if (typeof setupIntersectionObserver !== 'function') {
        console.error('FAIL: setupIntersectionObserver is not defined');
        console.log('0 passed, 0 FAILED (RED phase)');
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

        const col = document.createElement('div');
        col.className = 'column';
        document.body.appendChild(col);

        const inViewContainer = document.createElement('div');
        inViewContainer.className = 'page-container';
        inViewContainer.dataset.page = '0';
        inViewContainer.dataset.side = 'left';
        col.appendChild(inViewContainer);

        const outOfViewContainer = document.createElement('div');
        outOfViewContainer.className = 'page-container';
        outOfViewContainer.dataset.page = '1';
        outOfViewContainer.dataset.side = 'right';
        col.appendChild(outOfViewContainer);

        const colGBCR = { top: 0, bottom: 600, left: 0, right: 400, width: 400, height: 600 };
        const inViewGBCR = { top: 100, bottom: 500, left: 0, right: 400, width: 400, height: 400 };
        const outOfViewGBCR = { top: -2000, bottom: -1600, left: 0, right: 400, width: 400, height: 400 };

        col.getBoundingClientRect = () => colGBCR;
        inViewContainer.getBoundingClientRect = () => inViewGBCR;
        outOfViewContainer.getBoundingClientRect = () => outOfViewGBCR;

        const OriginalIO = globalThis.IntersectionObserver;
        let capturedCallback = null;
        let capturedOptions = null;
        let observeCalls = [];

        globalThis.IntersectionObserver = function (cb, opts) {
            capturedCallback = cb;
            capturedOptions = opts;
            this.observe = function (el) { observeCalls.push(el); };
            this.unobserve = function () {};
            this.disconnect = function () {};
        };

        let settledCb = null;
        const mockSettle = {
            isScrollSettled: () => true,
            onSettle: (cb) => { settledCb = cb; },
        };

        let loadCallCount = 0;
        let unloadCallCount = 0;
        const loadedContainers = [];
        const mockLoad = (container) => { loadCallCount++; loadedContainers.push(container); };
        const mockUnload = () => { unloadCallCount++; };

        try {
            const result = setupIntersectionObserver({
                load: mockLoad,
                unload: mockUnload,
                settle: mockSettle,
            });

            assert(settledCb !== null, 'Test 1: settle.onSettle was registered with a callback');

            result.pendingReclaim.add(outOfViewContainer);

            capturedCallback([
                { target: inViewContainer, isIntersecting: true },
                { target: outOfViewContainer, isIntersecting: true },
            ]);

            assert(result.pendingLoad.has(inViewContainer), 'Test 2a: in-viewport container in pendingLoad');
            assert(result.pendingLoad.has(outOfViewContainer), 'Test 2b: out-of-viewport container also in pendingLoad');

            settledCb();

            assert(loadedContainers.includes(inViewContainer), 'Test 3: in-viewport container was loaded on settle');
            assert(loadCallCount === 1, 'Test 3b: exactly one load call on settle');

            assert(!loadedContainers.includes(outOfViewContainer), 'Test 4a: out-of-viewport container was NOT loaded');
            assert(!result.pendingLoad.has(outOfViewContainer), 'Test 4b: out-of-viewport container removed from pendingLoad');

            assert(result.pendingLoad.size === 0, 'Test 5: pendingLoad is empty after settle scan');

            assert(result.pendingReclaim.has(outOfViewContainer), 'Test 6: pendingReclaim was NOT touched');
        } catch (e) {
            assert(false, 'Exception: ' + e.message);
        }

        globalThis.IntersectionObserver = OriginalIO;
        document.body.removeChild(col);

        if (failCount === 0) {
            console.log('All ' + passCount + ' tests PASSED');
        } else {
            console.log(passCount + ' passed, ' + failCount + ' FAILED');
        }
        globalThis.__SETTLE_SCAN_TESTS_DONE__ = true;
    }
}
