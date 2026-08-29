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
