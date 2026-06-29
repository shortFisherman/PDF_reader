export function createAlignmentController({ leftEl, rightEl }) {
    const state = {
        currentTarget: { pageIndex: 0, intraPageOffsetPx: 0 },
        lockSide: null,
    };

    let leftScrollHandler = null;
    let rightScrollHandler = null;

    function setLockTarget(pageIndex, offsetPx) {
        state.currentTarget.pageIndex = pageIndex;
        state.currentTarget.intraPageOffsetPx = offsetPx;
    }

    function getLockTarget() {
        const t = state.currentTarget;
        return { pageIndex: t.pageIndex, intraPageOffsetPx: t.intraPageOffsetPx };
    }

    function realign(column) {
        const pageContainer = column.querySelector('.page-container[data-page="' + state.currentTarget.pageIndex + '"]');
        if (!pageContainer) return;

        const pcRect = pageContainer.getBoundingClientRect();
        const colRect = column.getBoundingClientRect();
        const pageContainerOffsetTop = pcRect.top - colRect.top + column.scrollTop;

        column.scrollTop = pageContainerOffsetTop + state.currentTarget.intraPageOffsetPx;
    }

    function onScroll(src) {
        const containers = src.querySelectorAll('.page-container');
        if (!containers || containers.length === 0) return;

        let bestPage = null;
        let bestCoverage = 0;
        const viewTop = src.scrollTop;
        const viewBottom = viewTop + src.clientHeight;

        containers.forEach(function (c) {
            const rect = c.getBoundingClientRect();
            const colRect = src.getBoundingClientRect();
            const top = rect.top - colRect.top + src.scrollTop;
            const bottom = top + rect.height;
            const overlap = Math.min(bottom, viewBottom) - Math.max(top, viewTop);
            if (overlap <= 0) return;
            const coverage = overlap / rect.height;
            if (coverage > bestCoverage) {
                bestCoverage = coverage;
                bestPage = c;
            }
        });

        if (!bestPage) return;

        let pageIndex = parseInt(bestPage.dataset.page);
        const pcRect = bestPage.getBoundingClientRect();
        const colRect = src.getBoundingClientRect();
        const pageContainerOffsetTop = pcRect.top - colRect.top + src.scrollTop;

        let intraOffset = src.scrollTop - pageContainerOffsetTop;

        if (intraOffset < 0) {
            pageIndex -= 1;
            const nextPage = src.querySelector('.page-container[data-page="' + (pageIndex + 1) + '"]');
            if (nextPage) {
                intraOffset += nextPage.offsetHeight;
            }
        }

        state.currentTarget.pageIndex = pageIndex;
        state.currentTarget.intraPageOffsetPx = intraOffset;

        const side = src === leftEl ? 'left' : 'right';
        state.lockSide = side;

        const dst = side === 'left' ? rightEl : leftEl;
        realign(dst);
    }

    function onImageLoaded(side, pageIndex) { /* stub */ }
    function onZoomChange(newZoom, oldZoom) { /* stub */ }

    function installScrollListeners() {
        leftScrollHandler = function () { onScroll(leftEl); };
        rightScrollHandler = function () { onScroll(rightEl); };
        leftEl.addEventListener('scroll', leftScrollHandler);
        rightEl.addEventListener('scroll', rightScrollHandler);
    }

    function dispose() {
        if (leftScrollHandler) {
            leftEl.removeEventListener('scroll', leftScrollHandler);
            leftScrollHandler = null;
        }
        if (rightScrollHandler) {
            rightEl.removeEventListener('scroll', rightScrollHandler);
            rightScrollHandler = null;
        }
    }

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

            // Add page-container[data-page="0"] so realign can compute scrollTop
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

            pending--;
            done(pending);
        }

        // Test (c): Realign write — both columns align to the same page top after realign
        {
            const leftEl = document.createElement('div');
            const rightEl = document.createElement('div');
            Object.defineProperty(leftEl, 'clientHeight', { value: 500, configurable: true });
            Object.defineProperty(rightEl, 'clientHeight', { value: 500, configurable: true });
            // 30px scrollHeight difference (placeholder vs real images, 2px * 15 pages)
            Object.defineProperty(leftEl, 'scrollHeight', { value: 1000, configurable: true });
            Object.defineProperty(rightEl, 'scrollHeight', { value: 970, configurable: true });

            // Mock getBoundingClientRect so page 2 offsetTop is computable
            leftEl.getBoundingClientRect = function () {
                return { top: 0, bottom: 500, height: 500, left: 0, right: 100, width: 100, x: 0, y: 0 };
            };
            rightEl.getBoundingClientRect = function () {
                return { top: 0, bottom: 500, height: 500, left: 0, right: 100, width: 100, x: 0, y: 0 };
            };

            // Add 5 page-containers (200px each) to both columns
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

            pending--;
            done(pending);
        }

        // Test (d): Re-entrance guard — derivation must not run during realign
        {
            const leftEl = document.createElement('div');
            const rightEl = document.createElement('div');
            Object.defineProperty(leftEl, 'clientHeight', { value: 500, configurable: true });
            Object.defineProperty(leftEl, 'scrollHeight', { value: 2000, configurable: true });
            leftEl.getBoundingClientRect = function () {
                return { top: 0, bottom: 500, height: 500, left: 0, right: 100, width: 100, x: 0, y: 0 };
            };

            const ctrl = createAlignmentController({ leftEl: leftEl, rightEl: rightEl });

            let derivationCallsDuringRealign = 0;
            const _origOnScroll = ctrl.onScroll;
            const _origRealign = ctrl.realign;

            // Spy: wrap onScroll to count derivation attempts
            ctrl.onScroll = function (src) {
                derivationCallsDuringRealign++;
                _origOnScroll(src);
            };

            // Simulate realign flow: realign writes scrollTop -> browser fires
            // synchronous scroll event -> onScroll called (potentially re-entrant)
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
