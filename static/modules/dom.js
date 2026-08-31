let _cache = null;

export function getElements() {
    if (_cache) return _cache;

    const leftCol = document.getElementById('left-column');
    const rightCol = document.getElementById('right-column');
    const pageIndicator = document.getElementById('page-indicator');
    const zoomLevel = document.getElementById('zoom-level');
    const zoomReset = document.getElementById('zoom-reset');
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
    const fromPage = document.getElementById('from-page');
    const toPage = document.getElementById('to-page');
    const rangeTranslateBtn = document.getElementById('range-translate-btn');
    const fullTranslateBtn = document.getElementById('full-translate-btn');
    const toolbarToggle = document.getElementById('toolbar-toggle');
    const toolbarExtras = document.getElementById('toolbar-extras');
    const configBtn = document.getElementById('config-btn');
    const glossaryBtn = document.getElementById('glossary-btn');

    _cache = {
        leftCol,
        rightCol,
        pageIndicator,
        zoomLevel,
        zoomReset,
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
        fromPage,
        toPage,
        rangeTranslateBtn,
        fullTranslateBtn,
        toolbarToggle,
        toolbarExtras,
        configBtn,
        glossaryBtn,
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
    placeholder.style.setProperty('--page-ratio', `${ph}%`);
    placeholder.textContent = `Page ${pageNum + 1}`;
    container.appendChild(placeholder);

    return container;
}

export function showError(parent, message) {
    const p = document.createElement('p');
    p.style.color = '#e55';
    p.style.marginTop = '10px';
    p.textContent = message;
    parent.appendChild(p);
}
