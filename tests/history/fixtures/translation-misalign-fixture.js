// === Translation Misalignment Reproduction Test ===
// Simulates the bug: after translation, the right column's replaced image
// has a different height (2px less) than the placeholder. Proportional scroll
// sync (setupScrollSync) uses scrollTop/scrollHeight ratio, so differing
// scrollHeights cause the columns to misalign.
//
// Triggered by window.__TEST_ALIGN_REPRO_TRANSLATION__

if (typeof window !== 'undefined' && window.__TEST_ALIGN_REPRO_TRANSLATION__) {
    if (typeof setupScrollSync !== 'function') {
        console.error('FAIL: setupScrollSync is not defined');
        console.log('0 passed, 1 FAILED (RED phase)');
        globalThis.__ALIGN_REPRO_TRANSLATION_DONE__ = true;
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
            globalThis.__ALIGN_REPRO_TRANSLATION_DONE__ = true;
        }

        const PAGE_HEIGHT = 450;
        const IMG_HEIGHT = 448;
        const NUM_PAGES = 4;
        const CLIENT_HEIGHT = 800;

        const body = document.body;
        body.innerHTML = '';

        const leftCol = document.createElement('div');
        leftCol.id = 'left-column';
        const rightCol = document.createElement('div');
        rightCol.id = 'right-column';
        body.appendChild(leftCol);
        body.appendChild(rightCol);

        Object.defineProperty(leftCol, 'clientHeight', { value: CLIENT_HEIGHT, configurable: true });
        Object.defineProperty(rightCol, 'clientHeight', { value: CLIENT_HEIGHT, configurable: true });

        const leftPages = [];
        const rightPages = [];

        for (let i = 0; i < NUM_PAGES; i++) {
            const lc = document.createElement('div');
            lc.className = 'page-container';
            lc.dataset.page = i;
            lc.dataset.side = 'left';
            const lph = document.createElement('div');
            lph.className = 'page-placeholder';
            lph.style.setProperty('--page-ratio', '150%');
            lph.textContent = 'Page ' + (i + 1);
            lc.appendChild(lph);
            Object.defineProperty(lc, 'offsetHeight', { value: PAGE_HEIGHT, configurable: true });
            leftCol.appendChild(lc);
            leftPages.push(lc);

            const rc = document.createElement('div');
            rc.className = 'page-container';
            rc.dataset.page = i;
            rc.dataset.side = 'right';
            const rph = document.createElement('div');
            rph.className = 'page-placeholder';
            rph.style.setProperty('--page-ratio', '150%');
            rph.textContent = 'Page ' + (i + 1);
            rc.appendChild(rph);
            Object.defineProperty(rc, 'offsetHeight', { value: PAGE_HEIGHT, configurable: true });
            rightCol.appendChild(rc);
            rightPages.push(rc);
        }

        function mockLeftRects() {
            for (let i = 0; i < NUM_PAGES; i++) {
                leftPages[i].getBoundingClientRect = function () {
                    const top = i * PAGE_HEIGHT - leftCol.scrollTop;
                    return {
                        top: top, bottom: top + PAGE_HEIGHT, height: PAGE_HEIGHT,
                        left: 0, right: 100, width: 100, x: 0, y: top,
                    };
                };
            }
        }

        function mockRightRects() {
            for (let i = 0; i < NUM_PAGES; i++) {
                rightPages[i].getBoundingClientRect = function () {
                    const top = i * PAGE_HEIGHT - rightCol.scrollTop;
                    return {
                        top: top, bottom: top + PAGE_HEIGHT, height: PAGE_HEIGHT,
                        left: 0, right: 100, width: 100, x: 0, y: top,
                    };
                };
            }
        }

        mockLeftRects();
        mockRightRects();

        leftCol.getBoundingClientRect = function () {
            return { top: 0, bottom: CLIENT_HEIGHT, height: CLIENT_HEIGHT,
                left: 0, right: 300, width: 300, x: 0, y: 0 };
        };
        rightCol.getBoundingClientRect = function () {
            return { top: 0, bottom: CLIENT_HEIGHT, height: CLIENT_HEIGHT,
                left: 0, right: 300, width: 300, x: 0, y: 0 };
        };

        const INITIAL_SCROLL_HEIGHT = NUM_PAGES * PAGE_HEIGHT;
        Object.defineProperty(leftCol, 'scrollHeight', {
            get: function () { return INITIAL_SCROLL_HEIGHT; },
            configurable: true,
        });
        Object.defineProperty(rightCol, 'scrollHeight', {
            get: function () { return INITIAL_SCROLL_HEIGHT; },
            configurable: true,
        });

        setupScrollSync({ left: leftCol, right: rightCol });

        // --- Phase 1: scroll both columns to page 2 ---
        const targetScroll = 2 * PAGE_HEIGHT;
        leftCol.scrollTop = targetScroll;
        rightCol.scrollTop = targetScroll;

        assert(leftCol.scrollTop === targetScroll && rightCol.scrollTop === targetScroll,
            'Phase 1: both columns scrolled to page 2');

        // --- Phase 2: simulate translation completion on right column page 2 ---
        // Replace placeholder with img of different naturalHeight
        const targetPage = rightPages[2];
        const newImg = document.createElement('img');
        newImg.src = 'http://localhost/test.png';
        Object.defineProperty(newImg, 'naturalHeight', { value: IMG_HEIGHT, configurable: true });
        targetPage.innerHTML = '';
        targetPage.appendChild(newImg);

        // Adjust right column: page 2 offsetHeight changes, scrollHeight changes
        Object.defineProperty(rightPages[2], 'offsetHeight', { value: IMG_HEIGHT, configurable: true });

        const newRightScrollHeight = INITIAL_SCROLL_HEIGHT - (PAGE_HEIGHT - IMG_HEIGHT);
        Object.defineProperty(rightCol, 'scrollHeight', {
            get: function () { return newRightScrollHeight; },
            configurable: true,
        });

        // Re-mock right page getBoundingClientRect accounting for new height
        for (let i = 0; i < NUM_PAGES; i++) {
            rightPages[i].getBoundingClientRect = function () {
                var acc = 0;
                for (var j = 0; j < NUM_PAGES; j++) {
                    if (j < i) acc += rightPages[j].offsetHeight;
                }
                var h = rightPages[i].offsetHeight;
                var sTop = rightCol.scrollTop;
                var top = acc - sTop;
                return {
                    top: top, bottom: top + h, height: h,
                    left: 0, right: 100, width: 100, x: 0, y: top,
                };
            };
        }

        // --- Phase 3: trigger proportional sync ---
        // Dispatch scroll on left column — proportional sync reads
        // vf = left.scrollTop / (left.scrollHeight - left.clientHeight)
        //    = 900 / (1800 - 800) = 0.9
        // right.scrollTop = 0.9 * (1798 - 800) = 0.9 * 998 = 898.2
        leftCol.dispatchEvent(new Event('scroll'));

        // --- Assertions ---
        var leftPage2Top = leftPages[2].getBoundingClientRect().top;
        var rightPage2Top = rightPages[2].getBoundingClientRect().top;
        var diff = Math.abs(leftPage2Top - rightPage2Top);

        console.log('Left page 2 top: ' + leftPage2Top + ', Right page 2 top: ' + rightPage2Top + ', Diff: ' + diff);

        // The bug: proportional sync causes misalignment when column heights differ
        assert(diff > 0,
            'Bug repro: columns misaligned after translation (diff ' + diff + 'px > 0)');

        // The correct behavior (which this RED test proves is NOT met by current code):
        assert(diff === 0,
            'Expected: columns remain aligned after translation (got diff ' + diff + 'px)');

        done();
    }
}
