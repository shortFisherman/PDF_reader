export function setupZoom({ columns, appEl, onZoomChange, alignmentController }) {
    const MIN = 0.25;
    const MAX = 2.2;
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
        const oldZoom = zoom;

        appEl.style.setProperty('--zoom', newZoom);
        col.scrollTop = (col.scrollTop + cy) * r - cy;
        col.scrollLeft = (col.scrollLeft + cx) * r - cx;

        zoom = newZoom;
        onZoomChange(zoom);
        if (alignmentController) {
            alignmentController.onZoomChange(newZoom, oldZoom);
        }
    }

    function resetZoom() {
        if (zoom === 1) return;
        const col = columns[0];
        const cx = col.clientWidth / 2;
        const cy = col.clientHeight / 2;
        const r = 1 / zoom;
        const oldZoom = zoom;

        appEl.style.setProperty('--zoom', 1);
        col.scrollTop = (col.scrollTop + cy) * r - cy;
        col.scrollLeft = (col.scrollLeft + cx) * r - cx;

        zoom = 1;
        onZoomChange(zoom);
        if (alignmentController) {
            alignmentController.onZoomChange(1, oldZoom);
        }
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
