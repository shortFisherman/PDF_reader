const BUF = 2;
const RECLAIM_DISTANCE = 10;

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
        for (const container of [...pendingReclaim]) {
            pendingReclaim.delete(container);
            if (!isWithinViewportBuffer(container, RECLAIM_DISTANCE)) {
                unload(container);
            }
        }
    });

    // Initial viewport scan: load BUF-range pages after first layout.
    // Must use requestAnimationFrame (not setTimeout) because IO callbacks
    // and layout happen during the rendering update; rAF runs after layout
    // is computed, so getBoundingClientRect reflects true geometry.
    requestAnimationFrame(() => {
        for (const container of allContainers) {
            if (container.dataset.loaded === 'true') continue;
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

// === Tests for delayed reclaim (Task 4.3) ===
if (typeof window !== 'undefined' && window.__TEST_DELAYED_RECLAIM__) {
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

        // Test: RECLAIM_DISTANCE = 10 constant exists
        assert(
            typeof RECLAIM_DISTANCE !== 'undefined' && RECLAIM_DISTANCE === 10,
            'Test 0: RECLAIM_DISTANCE is defined and equals 10'
        );

        const col = document.createElement('div');
        col.className = 'column';
        document.body.appendChild(col);

        const nearContainer = document.createElement('div');
        nearContainer.className = 'page-container';
        nearContainer.dataset.page = '0';
        nearContainer.dataset.side = 'left';
        col.appendChild(nearContainer);

        const farContainer = document.createElement('div');
        farContainer.className = 'page-container';
        farContainer.dataset.page = '1';
        farContainer.dataset.side = 'right';
        col.appendChild(farContainer);

        // Viewport: top=0, bottom=600
        const colGBCR = { top: 0, bottom: 600, left: 0, right: 400, width: 400, height: 600 };
        // Each container is 400px tall
        // RECLAIM_DISTANCE = 10, so buffer edge at viewBottom + 10*400 = 600 + 4000 = 4600
        // far-away page starts at 4601 (top=4601, bottom=5001) — beyond buffer
        // near-viewport page at top=4000, bottom=4400 — within buffer
        const nearGBCR = { top: 4000, bottom: 4400, left: 0, right: 400, width: 400, height: 400 };
        const farGBCR = { top: 4601, bottom: 5001, left: 0, right: 400, width: 400, height: 400 };

        col.getBoundingClientRect = () => colGBCR;
        nearContainer.getBoundingClientRect = () => nearGBCR;
        farContainer.getBoundingClientRect = () => farGBCR;

        const OriginalIO = globalThis.IntersectionObserver;
        let _capturedCallback = null;

        globalThis.IntersectionObserver = function (cb, _opts) {
            _capturedCallback = cb;
            this.observe = function () {};
            this.unobserve = function () {};
            this.disconnect = function () {};
        };

        let settledCb = null;
        const mockSettle = {
            isScrollSettled: () => true,
            onSettle: (cb) => { settledCb = cb; },
        };

        let _loadCallCount = 0;
        let _unloadCallCount = 0;
        const unloadedContainers = [];
        const mockLoad = () => { _loadCallCount++; };
        const mockUnload = (container) => { _unloadCallCount++; unloadedContainers.push(container); };

        try {
            const result = setupIntersectionObserver({
                load: mockLoad,
                unload: mockUnload,
                settle: mockSettle,
            });

            assert(settledCb !== null, 'Test 1: settle.onSettle was registered');

            // Put both containers in pendingReclaim
            result.pendingReclaim.add(nearContainer);
            result.pendingReclaim.add(farContainer);
            // Also add a page to pendingLoad to verify it gets emptied too
            const dummyLoad = document.createElement('div');
            dummyLoad.className = 'page-container';
            dummyLoad.dataset.page = '2';
            dummyLoad.dataset.side = 'left';
            col.appendChild(dummyLoad);
            dummyLoad.getBoundingClientRect = () => ({ top: 100, bottom: 500, left: 0, right: 400, width: 400, height: 400 });
            result.pendingLoad.add(dummyLoad);

            // Fire settle
            settledCb();

            // Test 2: Far-away page was unloaded
            assert(unloadedContainers.includes(farContainer), 'Test 2: far-away container was unloaded');

            // Test 3: Near-viewport page was NOT unloaded
            assert(!unloadedContainers.includes(nearContainer), 'Test 3: near-viewport container was NOT unloaded');

            // Test 4: Both pendingLoad and pendingReclaim emptied after settle
            assert(result.pendingLoad.size === 0, 'Test 4a: pendingLoad empty after settle scan');
            assert(result.pendingReclaim.size === 0, 'Test 4b: pendingReclaim empty after settle scan');

            // Test 5: RECLAIM_DISTANCE = 10 is used in setupIntersectionObserver
            const fnSrc = setupIntersectionObserver.toString();
            assert(fnSrc.includes('RECLAIM_DISTANCE'), 'Test 5: setupIntersectionObserver references RECLAIM_DISTANCE');

            // Clean up dummy
            col.removeChild(dummyLoad);
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
        globalThis.__DELAYED_RECLAIM_TESTS_DONE__ = true;
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
        let _capturedCallback = null;
        let _capturedOptions = null;
        let observeCalls = [];

        globalThis.IntersectionObserver = function (cb, _opts) {
            _capturedCallback = cb;
            _capturedOptions = _opts;
            this.observe = function (el) { observeCalls.push(el); };
            this.unobserve = function () {};
            this.disconnect = function () {};
        };

        let settledCb = null;
        const mockSettle = {
            isScrollSettled: () => true,
            onSettle: (cb) => { settledCb = cb; },
        };

        let _loadCallCount = 0;
        let _unloadCallCount = 0;
        const loadedContainers = [];
        const mockLoad = (container) => { _loadCallCount++; loadedContainers.push(container); };
        const mockUnload = () => { _unloadCallCount++; };

        try {
            const result = setupIntersectionObserver({
                load: mockLoad,
                unload: mockUnload,
                settle: mockSettle,
            });

            assert(settledCb !== null, 'Test 1: settle.onSettle was registered with a callback');

            result.pendingReclaim.add(outOfViewContainer);

            _capturedCallback([
                { target: inViewContainer, isIntersecting: true },
                { target: outOfViewContainer, isIntersecting: true },
            ]);

            assert(result.pendingLoad.has(inViewContainer), 'Test 2a: in-viewport container in pendingLoad');
            assert(result.pendingLoad.has(outOfViewContainer), 'Test 2b: out-of-viewport container also in pendingLoad');

            settledCb();

            assert(loadedContainers.includes(inViewContainer), 'Test 3: in-viewport container was loaded on settle');
            assert(_loadCallCount === 1, 'Test 3b: exactly one load call on settle');

            assert(!loadedContainers.includes(outOfViewContainer), 'Test 4a: out-of-viewport container was NOT loaded');
            assert(!result.pendingLoad.has(outOfViewContainer), 'Test 4b: out-of-viewport container removed from pendingLoad');

            assert(result.pendingLoad.size === 0, 'Test 5: pendingLoad is empty after settle scan');

            assert(result.pendingReclaim.size === 0, 'Test 6: pendingReclaim is empty after settle scan');
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
