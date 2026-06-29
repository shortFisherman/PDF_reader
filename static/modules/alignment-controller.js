export function createAlignmentController({ leftEl, rightEl }) {
    function onScroll(src) { /* stub */ }
    function onImageLoaded(side, pageIndex) { /* stub */ }
    function onZoomChange(newZoom, oldZoom) { /* stub */ }
    function realign(column) { /* stub */ }
    function setLockTarget(pageIndex, offsetPx) { /* stub */ }
    function getLockTarget() { return null; /* stub */ }
    function installScrollListeners() { /* stub */ }
    function dispose() { /* stub */ }

    return {
        onScroll,
        onImageLoaded,
        onZoomChange,
        realign,
        setLockTarget,
        getLockTarget,
        installScrollListeners,
        dispose,
    };
}

// === Tests for createAlignmentController ===
if (typeof window !== 'undefined' && window.__TEST_ALIGNMENT_CONTROLLER__) {
    if (typeof createAlignmentController !== 'function') {
        console.error('FAIL: createAlignmentController is not defined');
        console.log('0 passed, 4 FAILED (RED phase)');
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
                    console.log('All ' + passCount + ' tests PASSED');
                } else {
                    console.log(passCount + ' passed, ' + failCount + ' FAILED');
                }
                globalThis.__ALIGNMENT_CONTROLLER_TESTS_DONE__ = true;
            }
        }

        let pending = 4;

        // Test (a): Write exclusivity — after realign(dst), only dst.scrollTop changes
        {
            const leftEl = document.createElement('div');
            const rightEl = document.createElement('div');
            Object.defineProperty(leftEl, 'clientHeight', { value: 500, configurable: true });
            Object.defineProperty(rightEl, 'clientHeight', { value: 500, configurable: true });
            Object.defineProperty(leftEl, 'scrollHeight', { value: 1600, configurable: true });
            Object.defineProperty(rightEl, 'scrollHeight', { value: 1600, configurable: true });

            const ctrl = createAlignmentController({ leftEl, rightEl });
            ctrl.setLockTarget(0, 0);
            const beforeLeft = leftEl.scrollTop;
            const beforeRight = rightEl.scrollTop;

            ctrl.realign(rightEl);

            assert(leftEl.scrollTop === beforeLeft,
                'Test a: only target column scrollTop should change; leftEl.scrollTop changed from ' + beforeLeft + ' to ' + leftEl.scrollTop);
            assert(rightEl.scrollTop !== beforeRight,
                'Test a: target column scrollTop should change after realign (stayed at ' + rightEl.scrollTop + ')');

            pending--;
            done(pending);
        }

        // Test (b): Target derivation — onScroll derives {pageIndex, intraPageOffsetPx}
        {
            const leftEl = document.createElement('div');
            const rightEl = document.createElement('div');
            Object.defineProperty(leftEl, 'clientHeight', { value: 500, configurable: true });
            Object.defineProperty(leftEl, 'scrollHeight', { value: 2000, configurable: true });
            leftEl.scrollTop = 350;

            // 4 pages, 400px each
            for (let i = 0; i < 4; i++) {
                const page = document.createElement('div');
                page.className = 'page-container';
                page.dataset.page = String(i);
                page.style.height = '400px';
                const pageTop = i * 400;
                const visibleTop = pageTop - leftEl.scrollTop;
                page.getBoundingClientRect = () => ({
                    top: visibleTop,
                    bottom: visibleTop + 400,
                    height: 400,
                    left: 0,
                    right: 100,
                    width: 100,
                    x: 0,
                    y: visibleTop,
                });
                leftEl.appendChild(page);
            }
            leftEl.getBoundingClientRect = () => ({ top: 0, bottom: 500, height: 500, left: 0, right: 100, width: 100, x: 0, y: 0 });

            const ctrl = createAlignmentController({ leftEl, rightEl });
            ctrl.onScroll(leftEl);

            const target = ctrl.getLockTarget();
            assert(target !== null, 'Test b: getLockTarget should return a target object, got null');
            assert(target !== null && typeof target.pageIndex === 'number',
                'Test b: target.pageIndex should be a number');
            assert(target !== null && typeof target.intraPageOffsetPx === 'number',
                'Test b: target.intraPageOffsetPx should be a number');

            pending--;
            done(pending);
        }

        // Test (c): Realign write — both columns align to the same page top after realign
        {
            const leftEl = document.createElement('div');
            const rightEl = document.createElement('div');
            Object.defineProperty(leftEl, 'clientHeight', { value: 500, configurable: true });
            Object.defineProperty(rightEl, 'clientHeight', { value: 500, configurable: true });
            // 30px scrollHeight difference (placeholder vs real images, 2px × 15 pages)
            Object.defineProperty(leftEl, 'scrollHeight', { value: 1000, configurable: true });
            Object.defineProperty(rightEl, 'scrollHeight', { value: 970, configurable: true });

            // Mock getBoundingClientRect so page 2 offsetTop is computable
            leftEl.getBoundingClientRect = () => ({ top: 0, bottom: 500, height: 500, left: 0, right: 100, width: 100, x: 0, y: 0 });
            rightEl.getBoundingClientRect = () => ({ top: 0, bottom: 500, height: 500, left: 0, right: 100, width: 100, x: 0, y: 0 });

            const ctrl = createAlignmentController({ leftEl, rightEl });
            ctrl.setLockTarget(2, 0);
            ctrl.realign(leftEl);
            ctrl.realign(rightEl);

            const leftScroll = leftEl.scrollTop;
            const rightScroll = rightEl.scrollTop;

            assert(Math.abs(leftScroll - rightScroll) < 0.5,
                'Test c: both columns should align to same page top; diff=' + Math.abs(leftScroll - rightScroll).toFixed(1));
            assert(leftScroll > 0,
                'Test c: leftEl.scrollTop should be > 0 after realign (is ' + leftScroll + ')');
            assert(rightScroll > 0,
                'Test c: rightEl.scrollTop should be > 0 after realign (is ' + rightScroll + ')');

            pending--;
            done(pending);
        }

        // Test (d): Re-entrance guard — derivation must not run during realign
        {
            const leftEl = document.createElement('div');
            const rightEl = document.createElement('div');
            Object.defineProperty(leftEl, 'clientHeight', { value: 500, configurable: true });
            Object.defineProperty(leftEl, 'scrollHeight', { value: 2000, configurable: true });
            leftEl.getBoundingClientRect = () => ({ top: 0, bottom: 500, height: 500, left: 0, right: 100, width: 100, x: 0, y: 0 });

            const ctrl = createAlignmentController({ leftEl, rightEl });

            let derivationCallsDuringRealign = 0;
            const _origOnScroll = ctrl.onScroll;
            const _origRealign = ctrl.realign;

            // Spy: wrap onScroll to count derivation attempts
            ctrl.onScroll = function (src) {
                derivationCallsDuringRealign++;
                _origOnScroll(src);
            };

            // Simulate realign flow: realign writes scrollTop → browser fires
            // synchronous scroll event → onScroll called (potentially re-entrant)
            ctrl.realign = function (col) {
                _origRealign(col);
                // This represents the synchronous scroll event that fires
                // when realign writes to scrollTop in a real browser.
                // A re-entrance guard would prevent onScroll from processing.
                ctrl.onScroll(col);
            };

            ctrl.realign(leftEl);

            assert(derivationCallsDuringRealign === 0,
                'Test d: re-entrance guard missing — derivation called ' + derivationCallsDuringRealign + ' time(s) during realign');

            pending--;
            done(pending);
        }
    }
}
