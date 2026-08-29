// === Zoom Misalignment Reproduction Test ===
// Simulates the bug: after Ctrl+wheel zoom, the zoom handler updates only
// the zoomed column's scrollTop via the anchor formula. setupScrollSync's
// proportional sync then fires (via scroll event) and maps scrollTop to the
// other column using the vf ratio. When columns have different scrollHeights
// (e.g., left has more pages), the proportional mapping produces a different
// scrollTop, causing the columns to misalign.
//
// Triggered by window.__TEST_ALIGN_REPRO_ZOOM__

if (typeof window !== 'undefined' && window.__TEST_ALIGN_REPRO_ZOOM__) {
    if (typeof setupZoom !== 'function') {
        console.error('FAIL: setupZoom is not defined');
        console.log('0 passed, 1 FAILED (RED phase)');
        globalThis.__ALIGN_REPRO_ZOOM_DONE__ = true;
    } else if (typeof setupScrollSync !== 'function') {
        console.error('FAIL: setupScrollSync is not defined');
        console.log('0 passed, 1 FAILED (RED phase)');
        globalThis.__ALIGN_REPRO_ZOOM_DONE__ = true;
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

        function done() {
            if (failCount === 0) {
                console.log('All ' + passCount + ' tests PASSED');
            } else {
                console.log(passCount + ' passed, ' + failCount + ' FAILED');
            }
            globalThis.__ALIGN_REPRO_ZOOM_DONE__ = true;
        }

        var PAGE_HEIGHT = 450;
        var LEFT_PAGES = 4;
        var RIGHT_PAGES = 3;
        var CLIENT_HEIGHT = 800;
        var COL_WIDTH = 400;

        var body = document.body;
        body.innerHTML = '';

        var appEl = document.createElement('div');
        appEl.id = 'app';
        document.body.appendChild(appEl);

        var leftCol = document.createElement('div');
        leftCol.id = 'left-column';
        var rightCol = document.createElement('div');
        rightCol.id = 'right-column';
        body.appendChild(leftCol);
        body.appendChild(rightCol);

        Object.defineProperty(leftCol, 'clientHeight', { value: CLIENT_HEIGHT, configurable: true });
        Object.defineProperty(rightCol, 'clientHeight', { value: CLIENT_HEIGHT, configurable: true });
        Object.defineProperty(leftCol, 'clientWidth', { value: COL_WIDTH, configurable: true });
        Object.defineProperty(rightCol, 'clientWidth', { value: COL_WIDTH, configurable: true });

        var leftPages = [];
        var rightPages = [];

        for (var i = 0; i < LEFT_PAGES; i++) {
            var lc = document.createElement('div');
            lc.className = 'page-container';
            lc.dataset.page = i;
            lc.dataset.side = 'left';
            var lph = document.createElement('div');
            lph.className = 'page-placeholder';
            lph.style.setProperty('--page-ratio', '150%');
            lph.textContent = 'Left Page ' + (i + 1);
            lc.appendChild(lph);
            Object.defineProperty(lc, 'offsetHeight', { value: PAGE_HEIGHT, configurable: true });
            leftCol.appendChild(lc);
            leftPages.push(lc);
        }

        for (var j = 0; j < RIGHT_PAGES; j++) {
            var rc = document.createElement('div');
            rc.className = 'page-container';
            rc.dataset.page = j;
            rc.dataset.side = 'right';
            var rph = document.createElement('div');
            rph.className = 'page-placeholder';
            rph.style.setProperty('--page-ratio', '150%');
            rph.textContent = 'Right Page ' + (j + 1);
            rc.appendChild(rph);
            Object.defineProperty(rc, 'offsetHeight', { value: PAGE_HEIGHT, configurable: true });
            rightCol.appendChild(rc);
            rightPages.push(rc);
        }

        function mockLeftPageRects() {
            for (var i = 0; i < LEFT_PAGES; i++) {
                leftPages[i].getBoundingClientRect = function () {
                    var top = this._pageIndex * PAGE_HEIGHT - leftCol.scrollTop;
                    return {
                        top: top, bottom: top + PAGE_HEIGHT, height: PAGE_HEIGHT,
                        left: 0, right: COL_WIDTH, width: COL_WIDTH, x: 0, y: top,
                    };
                };
                leftPages[i]._pageIndex = i;
            }
        }

        function mockRightPageRects() {
            for (var j = 0; j < RIGHT_PAGES; j++) {
                rightPages[j].getBoundingClientRect = function () {
                    var top = this._pageIndex * PAGE_HEIGHT - rightCol.scrollTop;
                    return {
                        top: top, bottom: top + PAGE_HEIGHT, height: PAGE_HEIGHT,
                        left: 0, right: COL_WIDTH, width: COL_WIDTH, x: 0, y: top,
                    };
                };
                rightPages[j]._pageIndex = j;
            }
        }

        mockLeftPageRects();
        mockRightPageRects();

        leftCol.getBoundingClientRect = function () {
            return {
                top: 0, bottom: CLIENT_HEIGHT, height: CLIENT_HEIGHT,
                left: 0, right: COL_WIDTH, width: COL_WIDTH, x: 0, y: 0,
            };
        };
        rightCol.getBoundingClientRect = function () {
            return {
                top: 0, bottom: CLIENT_HEIGHT, height: CLIENT_HEIGHT,
                left: 0, right: COL_WIDTH, width: COL_WIDTH, x: 0, y: 0,
            };
        };

        var LEFT_SCROLL_HEIGHT = LEFT_PAGES * PAGE_HEIGHT;
        var RIGHT_SCROLL_HEIGHT = RIGHT_PAGES * PAGE_HEIGHT;

        Object.defineProperty(leftCol, 'scrollHeight', {
            value: LEFT_SCROLL_HEIGHT, configurable: true, writable: true,
        });
        Object.defineProperty(rightCol, 'scrollHeight', {
            value: RIGHT_SCROLL_HEIGHT, configurable: true, writable: true,
        });
        Object.defineProperty(leftCol, 'scrollWidth', {
            value: COL_WIDTH, configurable: true, writable: true,
        });
        Object.defineProperty(rightCol, 'scrollWidth', {
            value: COL_WIDTH, configurable: true, writable: true,
        });

        setupScrollSync({ left: leftCol, right: rightCol });

        var lastZoom = null;
        function onZoomChange(z) {
            lastZoom = z;
        }

        var zoomInstance = setupZoom({ columns: [leftCol, rightCol], appEl: appEl, onZoomChange: onZoomChange });
        assert(typeof zoomInstance.getZoom === 'function', 'Test 0a: zoomInstance has getZoom');
        assert(zoomInstance.getZoom() === 1, 'Test 0b: initial zoom = 1');

        var initialScroll = PAGE_HEIGHT * 1.5;
        leftCol.scrollTop = initialScroll;
        rightCol.scrollTop = initialScroll;

        assert(Math.abs(leftCol.scrollTop - rightCol.scrollTop) < 0.01,
            'Phase 1: both columns at same initial scrollTop (' + leftCol.scrollTop + ')');

        var initLeftTop = leftPages[1].getBoundingClientRect().top;
        var initRightTop = rightPages[1].getBoundingClientRect().top;
        assert(Math.abs(initLeftTop - initRightTop) < 0.01,
            'Phase 1: page 1 aligned (leftTop=' + initLeftTop + ', rightTop=' + initRightTop + ')');

        var wheelEvent = new WheelEvent('wheel', {
            deltaY: -100,
            deltaX: 0,
            deltaMode: 0,
            ctrlKey: true,
            clientX: 200,
            clientY: 300,
            cancelable: true,
            bubbles: true,
        });
        leftCol.dispatchEvent(wheelEvent);

        assert(lastZoom !== null && lastZoom > 1,
            'Phase 2: zoom increased (zoom=' + lastZoom + ')');
        assert(appEl.style.getPropertyValue('--zoom') === String(lastZoom),
            'Phase 2: --zoom CSS variable set to ' + lastZoom);

        var r = lastZoom / 1;
        var cy = 300 - 0;
        var expectedLeftScrollTop = (initialScroll + cy) * r - cy;
        assert(Math.abs(leftCol.scrollTop - expectedLeftScrollTop) < 0.01,
            'Phase 2: left scrollTop follows anchor formula (expected ' + expectedLeftScrollTop + ', got ' + leftCol.scrollTop + ')');

        leftCol.dispatchEvent(new Event('scroll'));

        var leftMax = LEFT_SCROLL_HEIGHT - CLIENT_HEIGHT;
        var rightMax = RIGHT_SCROLL_HEIGHT - CLIENT_HEIGHT;
        var vf = leftCol.scrollTop / leftMax;
        var expectedRightScrollTop = vf * rightMax;

        console.log('left scrollTop=' + leftCol.scrollTop + ', right scrollTop=' + rightCol.scrollTop);
        console.log('vf=' + vf + ', expectedRightScrollTop=' + expectedRightScrollTop);

        var leftPage1Top = leftPages[1].getBoundingClientRect().top;
        var rightPage1Top = rightPages[1].getBoundingClientRect().top;
        var diff = Math.abs(leftPage1Top - rightPage1Top);

        console.log('Left page 1 top=' + leftPage1Top + ', Right page 1 top=' + rightPage1Top + ', Diff=' + diff);

        assert(diff > 0,
            'Bug repro: columns misaligned after Ctrl+wheel zoom (diff ' + diff + 'px > 0)');

        assert(diff === 0,
            'Expected: columns remain aligned after zoom (got diff ' + diff + 'px)');

        zoomInstance.dispose();
        done();
    }
}
