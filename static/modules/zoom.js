export function setupZoom({ columns, appEl, onZoomChange }) {
    const MIN = 0.25;
    const MAX = 4;
    const STEP = 0.1;
    let zoom = 1;

    function handleWheel(e) {
        if (!e.ctrlKey) return;
        e.preventDefault();
        const col = e.currentTarget;
        const dir = Math.sign(e.deltaY);
        const newZoom = Math.min(MAX, Math.max(MIN, zoom - dir * STEP));
        if (newZoom === zoom) return;

        const cx = e.clientX - col.getBoundingClientRect().left;
        const cy = e.clientY - col.getBoundingClientRect().top;
        const r = newZoom / zoom;

        appEl.style.setProperty('--zoom', newZoom);
        col.scrollTop = (col.scrollTop + cy) * r - cy;
        col.scrollLeft = (col.scrollLeft + cx) * r - cx;

        zoom = newZoom;
        onZoomChange(zoom);
    }

    function resetZoom() {
        if (zoom === 1) return;
        const col = columns[0];
        const cx = col.clientWidth / 2;
        const cy = col.clientHeight / 2;
        const r = 1 / zoom;

        appEl.style.setProperty('--zoom', 1);
        col.scrollTop = (col.scrollTop + cy) * r - cy;
        col.scrollLeft = (col.scrollLeft + cx) * r - cx;

        zoom = 1;
        onZoomChange(zoom);
    }

    function getZoom() {
        return zoom;
    }

    columns.forEach(col => {
        col.addEventListener('wheel', handleWheel, { passive: false });
    });

    function dispose() {
        columns.forEach(col => {
            col.removeEventListener('wheel', handleWheel);
        });
    }

    return { resetZoom, getZoom, dispose };
}

// === Tests for zoom ===
if (typeof window !== 'undefined' && window.__TEST_ZOOM__) {
    if (typeof setupZoom !== 'function') {
        console.error('FAIL: setupZoom is not defined');
        console.log('0 passed, 0 FAILED (RED phase)');
    } else {
        let passCount = 0;
        let failCount = 0;

        function assert(cond, msg) {
            if (cond) { passCount++; }
            else { failCount++; console.error('FAIL: ' + msg); }
        }

        const appEl = document.createElement('div');
        const col = document.createElement('div');
        let wheelHandler = null;
        let preventDefaultCalls = 0;

        col.addEventListener = function (type, handler) {
            if (type === 'wheel') wheelHandler = handler;
        };
        col.removeEventListener = function () {};
        col.getBoundingClientRect = function () {
            return { left: 0, top: 0, width: 400, height: 600, right: 400, bottom: 600 };
        };

        const zoomChanges = [];
        function onZoomChange(z) { zoomChanges.push(z); }

        function fireCtrlWheel(deltaY, opts) {
            const e = {
                ctrlKey: true,
                deltaY: deltaY,
                preventDefault: function () { preventDefaultCalls++; },
                clientX: (opts && opts.clientX != null) ? opts.clientX : 100,
                clientY: (opts && opts.clientY != null) ? opts.clientY : 100,
                currentTarget: col,
            };
            wheelHandler(e);
        }

        function firePlainWheel(deltaY) {
            const e = {
                ctrlKey: false,
                deltaY: deltaY,
                preventDefault: function () { preventDefaultCalls++; },
                clientX: 100,
                clientY: 100,
                currentTarget: col,
            };
            wheelHandler(e);
        }

        try {
            const instance = setupZoom({ columns: [col], appEl, onZoomChange });

            assert(typeof instance.resetZoom === 'function', 'Test 1a: returns resetZoom');
            assert(typeof instance.getZoom === 'function', 'Test 1b: returns getZoom');
            assert(typeof instance.dispose === 'function', 'Test 1c: returns dispose');
            assert(instance.getZoom() === 1, 'Test 1d: initial zoom = 1');
            assert(zoomChanges.length === 0, 'Test 1e: no onZoomChange calls initially');

            fireCtrlWheel(100);
            assert(instance.getZoom() < 1, 'Test 2a: zoom decreased after Ctrl+wheel down');
            assert(zoomChanges.length === 1, 'Test 2b: onZoomChange called once');
            assert(preventDefaultCalls === 1, 'Test 2c: preventDefault called on Ctrl+wheel');

            const beforeIn = instance.getZoom();
            fireCtrlWheel(-100);
            assert(instance.getZoom() > beforeIn, 'Test 3a: zoom increased after Ctrl+wheel up');
            assert(zoomChanges.length === 2, 'Test 3b: onZoomChange called again');

            const beforePlain = instance.getZoom();
            const pdCallsBefore = preventDefaultCalls;
            firePlainWheel(100);
            assert(instance.getZoom() === beforePlain, 'Test 4a: zoom unchanged on non-Ctrl wheel');
            assert(preventDefaultCalls === pdCallsBefore, 'Test 4b: preventDefault NOT called on non-Ctrl');
            assert(zoomChanges.length === 2, 'Test 4c: onZoomChange NOT called on non-Ctrl');

            instance.resetZoom();
            for (let i = 0; i < 20; i++) fireCtrlWheel(100);
            assert(instance.getZoom() === 0.25, 'Test 5a: zoom clamped to MIN 0.25');
            fireCtrlWheel(100);
            assert(instance.getZoom() === 0.25, 'Test 5b: zoom stays at MIN');

            instance.resetZoom();
            for (let i = 0; i < 50; i++) fireCtrlWheel(-100);
            assert(instance.getZoom() === 4, 'Test 6a: zoom clamped to MAX 4');
            fireCtrlWheel(-100);
            assert(instance.getZoom() === 4, 'Test 6b: zoom stays at MAX');

            instance.resetZoom();
            assert(instance.getZoom() === 1, 'Test 7a: resetZoom returns zoom to 1');
            assert(appEl.style.getPropertyValue('--zoom') === '1', 'Test 7b: resetZoom sets --zoom to 1');

            const lastChange = zoomChanges[zoomChanges.length - 1];
            assert(lastChange === 1, 'Test 8: onZoomChange received 1 on reset');

            instance.resetZoom();
            fireCtrlWheel(-100);
            const cssZoom = appEl.style.getPropertyValue('--zoom');
            assert(cssZoom !== '' && cssZoom !== '1', 'Test 9: --zoom CSS property set on Ctrl+wheel');

            instance.dispose();

        } catch (e) {
            assert(false, 'Exception: ' + e.message + '\n' + e.stack);
        }

        if (failCount === 0) {
            console.log('All ' + passCount + ' tests PASSED');
        } else {
            console.log(passCount + ' passed, ' + failCount + ' FAILED');
        }
        globalThis.__ZOOM_TESTS_DONE__ = true;
    }
}
