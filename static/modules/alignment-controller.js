export function createAlignmentController({ leftEl, rightEl }) {
    const state = {
        currentTarget: { pageIndex: 0, intraPageOffsetPx: 0 },
        lockSide: null,
    };

    let leftScrollHandler = null;
    let rightScrollHandler = null;
    let realignTarget = null;

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

        // Mark this column as the realign target so that the async scroll event
        // triggered by the scrollTop write below is suppressed in onScroll.
        // This prevents the echo effect: realign writes scrollTop → browser
        // fires async scroll event → onScroll re-derives → wobble at page boundaries.
        realignTarget = column;

        const pcRect = pageContainer.getBoundingClientRect();
        const colRect = column.getBoundingClientRect();
        const pageContainerOffsetTop = pcRect.top - colRect.top + column.scrollTop;

        column.scrollTop = pageContainerOffsetTop + state.currentTarget.intraPageOffsetPx;

        // Sync horizontal scroll from the lock-side (source) column.
        // Use proportional sync since pages have the same width across both columns.
        var srcEl = null;
        if (state.lockSide === 'left') {
            srcEl = leftEl;
        } else if (state.lockSide === 'right') {
            srcEl = rightEl;
        }
        if (srcEl && srcEl !== column) {
            if (srcEl.scrollWidth > srcEl.clientWidth && column.scrollWidth > column.clientWidth) {
                var hf = srcEl.scrollLeft / (srcEl.scrollWidth - srcEl.clientWidth);
                column.scrollLeft = hf * (column.scrollWidth - column.clientWidth);
            }
        }
    }

    function onScroll(src) {
        // Suppress scroll events triggered by realign() on this column.
        // realign() sets realignTarget before writing scrollTop; the async scroll
        // event that follows must not re-derive the target, otherwise it creates
        // a feedback loop that causes vertical wobble at page boundaries.
        if (src === realignTarget) {
            realignTarget = null;
            return;
        }
        realignTarget = null;

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

    function onImageLoaded(side, pageIndex) {
        realign(leftEl);
        realign(rightEl);
    }
    function onZoomChange(newZoom, oldZoom) {
        state.currentTarget.intraPageOffsetPx *= newZoom / oldZoom;
        realign(leftEl);
        realign(rightEl);
    }

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

        let pending = 7;

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

        // Test (d): Re-entrance guard — after realign writes scrollTop,
        // onScroll on the same column must skip derivation to prevent echo.
        {
            const leftEl = document.createElement('div');
            const rightEl = document.createElement('div');
            Object.defineProperty(leftEl, 'clientHeight', { value: 500, configurable: true });
            Object.defineProperty(leftEl, 'scrollHeight', { value: 2000, configurable: true });
            leftEl.getBoundingClientRect = function () {
                return { top: 0, bottom: 500, height: 500, left: 0, right: 100, width: 100, x: 0, y: 0 };
            };

            // Add page-containers so onScroll and realign have DOM to work with
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

            // Set a lock target that differs from what onScroll would derive
            // from the DOM (scrollTop=0, page 0). If the guard fails and
            // onScroll runs, it would overwrite to {pageIndex:0, intraPageOffsetPx:0}.
            ctrl.setLockTarget(2, 100);
            const targetBefore = ctrl.getLockTarget();

            // realign marks rightEl as realignTarget. The async scroll event
            // that real browsers fire after scrollTop write should reach onScroll
            // and be suppressed because src === realignTarget.
            ctrl.realign(rightEl);

            // In jsdom, scroll events don't fire synchronously on scrollTop = assign.
            // We simulate the real browser: onScroll(rightEl) is called by the scroll
            // event listener that installScrollListeners would set up.
            ctrl.onScroll(rightEl);

            const targetAfter = ctrl.getLockTarget();
            assert(targetAfter.pageIndex === targetBefore.pageIndex,
                'Test d: pageIndex should not change during realign (got ' + targetAfter.pageIndex + ', expected ' + targetBefore.pageIndex + ')');
            assert(targetAfter.intraPageOffsetPx === targetBefore.intraPageOffsetPx,
                'Test d: intraPageOffsetPx should not change during realign (got ' + targetAfter.intraPageOffsetPx + ', expected ' + targetBefore.intraPageOffsetPx + ')');

            pending--;
            done(pending);
        }

        // Test (e): onImageLoaded calls realign on both columns, does not mutate currentTarget
        {
            const leftEl = document.createElement('div');
            const rightEl = document.createElement('div');

            // Add page-containers so realign has DOM to work with
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

            // realign scrollTop = pageContainerOffsetTop + intraPageOffsetPx
            // pageContainerOffsetTop = pcRect.top - colRect.top + column.scrollTop
            // = 400 - 0 + 0 = 400, + 50 = 450
            assert(leftEl.scrollTop === 450,
                'Test e: leftEl.scrollTop should be 450 after onImageLoaded, got ' + leftEl.scrollTop);
            assert(rightEl.scrollTop === 450,
                'Test e: rightEl.scrollTop should be 450 after onImageLoaded, got ' + rightEl.scrollTop);

            const targetAfter = ctrl.getLockTarget();
            assert(targetAfter.pageIndex === targetBefore.pageIndex,
                'Test e: pageIndex should not change (was ' + targetBefore.pageIndex + ', got ' + targetAfter.pageIndex + ')');
            assert(targetAfter.intraPageOffsetPx === targetBefore.intraPageOffsetPx,
                'Test e: intraPageOffsetPx should not change (was ' + targetBefore.intraPageOffsetPx + ', got ' + targetAfter.intraPageOffsetPx + ')');

            pending--;
            done(pending);
        }

        // Test (f): onZoomChange scales intraPageOffsetPx and realigns both columns
        {
            const leftEl = document.createElement('div');
            const rightEl = document.createElement('div');
            Object.defineProperty(leftEl, 'clientHeight', { value: 500, configurable: true });
            Object.defineProperty(rightEl, 'clientHeight', { value: 500, configurable: true });
            Object.defineProperty(leftEl, 'scrollHeight', { value: 2000, configurable: true });
            Object.defineProperty(rightEl, 'scrollHeight', { value: 2000, configurable: true });

            // Add page 2 to both columns so realign can find it
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

            const targetBefore = ctrl.getLockTarget();
            ctrl.onZoomChange(1.1, 1.0);

            const targetAfter = ctrl.getLockTarget();

            // intraPageOffsetPx * 1.1 = 110
            assert(targetAfter.pageIndex === 2,
                'Test f: pageIndex should stay 2 unchanged, got ' + targetAfter.pageIndex);
            assert(targetAfter.intraPageOffsetPx > 109.9 && targetAfter.intraPageOffsetPx < 110.1,
                'Test f: intraPageOffsetPx should be 100 * 1.1 ≈ 110, got ' + targetAfter.intraPageOffsetPx);

            // realign writes: pageContainerOffsetTop (800) + intraPageOffsetPx (110) = 910
            assert(leftEl.scrollTop === 910,
                'Test f: leftEl.scrollTop should be 910 (800 + 110), got ' + leftEl.scrollTop);
            assert(rightEl.scrollTop === 910,
                'Test f: rightEl.scrollTop should be 910 (800 + 110), got ' + rightEl.scrollTop);

            pending--;
            done(pending);
        }

        // Test (g): Negative intraOffset cross-page scenario
        // When viewport top is above a page container, intraOffset < 0,
        // pageIndex rolls back and intraOffset adds the next page's height.
        {
            const leftEl = document.createElement('div');
            const rightEl = document.createElement('div');
            Object.defineProperty(leftEl, 'clientHeight', { value: 600, configurable: true });
            Object.defineProperty(leftEl, 'scrollHeight', { value: 1200, configurable: true });
            leftEl.scrollTop = 350; // viewport center at ~650px

            // Page 0: 0-400px, page 1: 400-800px
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

            // scrollTop = 350, page 1 starts at offsetTop 400
            // intraOffset = 350 - 400 = -50 (< 0)
            // -> pageIndex -= 1 -> 0, intraOffset += 400 = 350
            // This means the content at scrollTop 350 is actually 350px into page 0
            ctrl.onScroll(leftEl);
            const target = ctrl.getLockTarget();

            assert(target.pageIndex === 0,
                'Test g: with scrollTop=350 (50px above page 1), pageIndex should roll back to 0, got ' + target.pageIndex);
            assert(target.intraPageOffsetPx === 350,
                'Test g: intraPageOffsetPx should be 350 (350 - 400 + 400), got ' + target.intraPageOffsetPx);

            pending--;
            done(pending);
        }
    }
}
