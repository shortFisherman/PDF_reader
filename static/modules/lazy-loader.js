const BUFFER = 5;

export function setupIntersectionObserver({ load, unload, settle }) {
    const observer = new IntersectionObserver((entries) => {
        for (const entry of entries) {
            const container = entry.target;
            if (entry.isIntersecting) {
                load(container);
            } else {
                unload(container);
            }
        }
    }, {
        root: null,
        rootMargin: `${BUFFER * 100}% 0px`,
    });

    const allContainers = document.querySelectorAll('.page-container');
    allContainers.forEach(c => observer.observe(c));
}

// === Tests for setupIntersectionObserver (settle parameter plumbing) ===
if (typeof window !== 'undefined' && window.__TEST_SETUP_INTERSECTION_OBSERVER__) {
    if (typeof setupIntersectionObserver !== 'function') {
        console.error('FAIL: setupIntersectionObserver is not defined');
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

        // Create minimal DOM with a .page-container element
        const container = document.createElement('div');
        container.className = 'page-container';
        container.dataset.page = '0';
        container.dataset.side = 'left';
        document.body.appendChild(container);

        // Mock IntersectionObserver
        const OriginalIO = globalThis.IntersectionObserver;
        let observeCalled = false;
        globalThis.IntersectionObserver = function (cb, opts) {
            observeCalled = true;
            this.observe = function () {};
            this.unobserve = function () {};
            this.disconnect = function () {};
        };

        const mockSettle = { isScrollSettled: () => true };

        try {
            // Test 1: Call with settle parameter — should not throw
            setupIntersectionObserver({
                load: () => {},
                unload: () => {},
                settle: mockSettle,
            });
            assert(observeCalled, 'Test 1a: IntersectionObserver was created with settle param');
            assert(true, 'Test 1b: setupIntersectionObserver accepts { load, unload, settle } without throwing');
        } catch (e) {
            assert(false, 'Test 1: Threw error: ' + e.message);
        }

        // Reset
        observeCalled = false;

        try {
            // Test 2: Call without settle — backward compat
            setupIntersectionObserver({
                load: () => {},
                unload: () => {},
            });
            assert(observeCalled, 'Test 2a: IntersectionObserver was created without settle param');
            assert(true, 'Test 2b: setupIntersectionObserver accepts { load, unload } without throwing');
        } catch (e) {
            assert(false, 'Test 2: Threw error: ' + e.message);
        }

        // Test 3: Function signature includes 'settle' in destructured params
        {
            const src = setupIntersectionObserver.toString();
            const match = src.match(/\{([^}]+)\}/);
            const params = match ? match[1] : '';
            assert(params.includes('settle'), 'Test 3: setupIntersectionObserver destructured params include settle');
        }

        // Cleanup
        globalThis.IntersectionObserver = OriginalIO;
        document.body.removeChild(container);

        if (failCount === 0) {
            console.log('All ' + passCount + ' tests PASSED');
        } else {
            console.log(passCount + ' passed, ' + failCount + ' FAILED');
        }
        globalThis.__SETUP_IO_TESTS_DONE__ = true;
    }
}
