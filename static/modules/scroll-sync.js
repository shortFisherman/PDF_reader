export function setupScrollSync({ left, right }) {
    let syncing = false;

    left.addEventListener('scroll', () => {
        if (!syncing) {
            syncing = true;
            right.scrollTop = left.scrollTop;
            requestAnimationFrame(() => {
                syncing = false;
            });
        }
    });
}

export function setupPageDetection({ container }, onPageChange) {
    container.addEventListener('scroll', () => {
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
