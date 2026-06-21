let _cache = null;

export function getElements() {
    if (_cache) return _cache;

    const leftCol = document.getElementById('left-column');
    const rightCol = document.getElementById('right-column');
    const pageIndicator = document.getElementById('page-indicator');
    const translateBtn = document.getElementById('translate-btn');
    const promptInput = document.getElementById('prompt-input');
    const promptToggle = document.getElementById('prompt-toggle');
    const progressBar = document.getElementById('progress-bar');
    const progressFill = document.getElementById('progress-fill');
    const progressStatusText = document.getElementById('progress-status-text');
    const fileArea = document.getElementById('file-input-area');
    const appView = document.getElementById('app');
    const toolbar = document.getElementById('toolbar');
    const openBtn = document.getElementById('open-btn');
    const pdfPathInput = document.getElementById('pdf-path');

    _cache = {
        leftCol,
        rightCol,
        pageIndicator,
        translateBtn,
        promptInput,
        promptToggle,
        progressBar,
        progressFill,
        progressStatusText,
        fileArea,
        appView,
        toolbar,
        openBtn,
        pdfPathInput,
    };

    return _cache;
}

export function calculatePlaceholderHeight(pageWidth, pageHeight) {
    if (pageWidth && pageHeight) {
        const ratio = pageHeight / pageWidth;
        return Math.round(100 * ratio);
    }
    return 600;
}

export function createPageEl(pageNum, side, pageWidth, pageHeight) {
    const container = document.createElement('div');
    container.className = 'page-container';
    container.dataset.page = pageNum;
    container.dataset.side = side;

    const ph = calculatePlaceholderHeight(pageWidth, pageHeight);

    const placeholder = document.createElement('div');
    placeholder.className = 'page-placeholder';
    placeholder.style.paddingBottom = `${ph}%`;
    placeholder.textContent = `Page ${pageNum + 1}`;
    placeholder.dataset.loaded = 'false';
    container.appendChild(placeholder);

    return container;
}
