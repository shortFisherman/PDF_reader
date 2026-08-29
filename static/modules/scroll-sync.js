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

    return {
        isScrollSettled, onSettle, dispose,
        trigger() {
            settled = true;
            const cbs = [...callbacks];
            cbs.forEach(cb => cb());
        },
    };
}

/**
 * @deprecated align-model-rewrite: 即将被 AlignmentController 替换。
 *   比例互推逻辑将迁移到 createAlignmentController.onScroll/realign，
 *   scroll-sync.js 仅保留 createSettleGate 与 setupPageDetection。
 */
export function setupScrollSync({ left: _left, right: _right }) {
    // @deprecated align-model-rewrite: 比例互推已由 AlignmentController 替代。
    //   本函数保留空壳以维持 import 不破坏，将在 align-model-rewrite 完成后移除。
}

export function setupPageDetection({ container, settle }, onPageChange) {
    settle.onSettle(() => {
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
