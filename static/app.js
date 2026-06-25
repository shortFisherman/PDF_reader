import { getElements, createPageEl, calculatePlaceholderHeight } from './modules/dom.js';
import { setupIntersectionObserver } from './modules/lazy-loader.js';
import { setupScrollSync, setupPageDetection, createSettleGate } from './modules/scroll-sync.js';
import { fetchStageLabels, getStageLabel } from './modules/stages.js';
import { translateCurrentPage } from './modules/translator.js';

const API = '/api';
let pageCount = 0;
let pageHeight = 0;
let pageWidth = 0;
let currentPage = 0;
let isTranslating = false;
let promptVisible = false;
let statusTimer = null;

let els;
let io = null;
let settle = null;

function init() {
    els = getElements();

    els.openBtn.addEventListener('click', openPdf);
    els.pdfPathInput.addEventListener('keydown', e => {
        if (e.key === 'Enter') openPdf();
    });
    els.promptToggle.addEventListener('click', () => {
        promptVisible = !promptVisible;
        els.promptInput.style.display = promptVisible ? 'inline-block' : 'none';
        els.promptToggle.textContent = promptVisible ? '- Prompt' : '+ Prompt';
    });
    els.translateBtn.addEventListener('click', onTranslateClick);

    fetchStageLabels();
}

async function openPdf() {
    if (io) { io.observer.disconnect(); io = null; }
    if (settle) { settle.dispose(); settle = null; }

    const path = els.pdfPathInput.value.trim();
    if (!path) return;

    try {
        const resp = await fetch(`${API}/open`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path }),
        });

        if (!resp.ok) {
            const errText = await resp.text();
            let errMsg = 'Failed to open PDF';
            try {
                const errData = JSON.parse(errText);
                errMsg = errData.error || errMsg;
            } catch (e) {}
            els.fileArea.insertAdjacentHTML('beforeend', `<p style="color:#e55;margin-top:10px">${errMsg}</p>`);
            return;
        }

        const data = await resp.json();
        pageCount = data.page_count;
        pageHeight = data.page_height;
        pageWidth = data.page_width;

        els.leftCol.innerHTML = '';
        els.rightCol.innerHTML = '';

        for (let i = 0; i < pageCount; i++) {
            els.leftCol.appendChild(createPageEl(i, 'left', pageWidth, pageHeight));
            els.rightCol.appendChild(createPageEl(i, 'right', pageWidth, pageHeight));
        }

        els.fileArea.classList.add('hidden');
        els.appView.classList.remove('hidden');
        els.toolbar.classList.remove('hidden');

        settle = createSettleGate(els.leftCol, els.rightCol);

        io = setupIntersectionObserver({
            load: loadPageImage,
            unload: unloadPageImage,
            settle,
        });
        setupScrollSync({ left: els.leftCol, right: els.rightCol });
        setupPageDetection({ container: els.leftCol, settle }, onPageChange);
        loadTranslatedState();

        // Initial viewport scan is handled inside setupIntersectionObserver via rAF
    } catch (e) {
        els.fileArea.insertAdjacentHTML('beforeend', `<p style="color:#e55;margin-top:10px">Network error: ${e.message}</p>`);
    }
}

function loadPageImage(container) {
    const page = parseInt(container.dataset.page);
    const side = container.dataset.side;

    if (container.dataset.loaded === 'true') return;

    const img = document.createElement('img');
    img.src = `${API}/page/${side}/${page}?t=${Date.now()}`;

    img.onload = () => {
        const placeholder = container.querySelector('.page-placeholder');
        if (placeholder) {
            placeholder.replaceWith(img);
        }
        container.dataset.loaded = 'true';
    };

    img.onerror = () => {
        container.dataset.loaded = 'error';
        const placeholder = container.querySelector('.page-placeholder');
        if (placeholder) {
            placeholder.textContent = `Page ${page + 1} (error)`;
        }
    };
}

function unloadPageImage(container) {
    if (container.dataset.loaded !== 'true') return;

    const img = container.querySelector('img');
    if (!img) return;

    const placeholder = document.createElement('div');
    placeholder.className = 'page-placeholder';
    const ph = calculatePlaceholderHeight(pageWidth, pageHeight);
    placeholder.style.setProperty('--page-ratio', `${ph}%`);
    placeholder.textContent = `Page ${parseInt(container.dataset.page) + 1}`;

    img.replaceWith(placeholder);
    container.dataset.loaded = 'false';
}

async function loadTranslatedState() {
    try {
        const resp = await fetch(`${API}/translated-pages`);
        if (!resp.ok) return;
        const data = await resp.json();
        data.pages.forEach(p => {
            const el = els.rightCol.querySelector(`.page-container[data-page="${p}"]`);
            if (el) el.classList.add('translated');
        });
    } catch (e) {}
}

function onPageChange(pageNum) {
    if (pageNum !== currentPage) {
        currentPage = pageNum;
        els.pageIndicator.textContent = `Page ${pageNum + 1}`;
    }
}

async function onTranslateClick() {
    if (isTranslating) return;
    const targetPage = currentPage;
    isTranslating = true;
    els.translateBtn.disabled = true;
    els.translateBtn.textContent = 'Translating...';
    els.progressBar.classList.add('active');
    els.progressFill.style.width = '0%';
    els.progressStatusText.textContent = '';
    els.progressStatusText.classList.remove('error', 'done');
    if (statusTimer) {
        clearTimeout(statusTimer);
        statusTimer = null;
    }

    try {
        await translateCurrentPage(targetPage, {
            prompt: els.promptInput.value.trim() || null,
            onStageChange(stage, labelText) {
                els.progressStatusText.textContent = labelText;
                if (stage === 'finish') {
                    els.progressStatusText.classList.add('done');
                    els.progressStatusText.classList.remove('error');
                } else {
                    els.progressStatusText.classList.remove('done', 'error');
                }
            },
            onProgress(percent) {
                els.progressFill.style.width = `${percent}%`;
            },
            onFinish() {
                els.progressFill.style.width = '100%';
                els.progressStatusText.textContent = getStageLabel('finish');
                els.progressStatusText.classList.add('done');
                els.progressStatusText.classList.remove('error');
                statusTimer = setTimeout(() => {
                    els.progressBar.classList.remove('active');
                    els.progressStatusText.textContent = '';
                    els.progressStatusText.classList.remove('done', 'error');
                }, 2000);

                const rightEl = els.rightCol.querySelector(`.page-container[data-page="${targetPage}"]`);
                if (rightEl) {
                    if (rightEl.dataset.loaded === 'true') {
                        unloadPageImage(rightEl);
                        loadPageImage(rightEl);
                    }
                    rightEl.classList.add('translated');
                }
                loadTranslatedState();
            },
            onError(message) {
                els.progressBar.classList.remove('active');
                els.progressStatusText.textContent = message;
                els.progressStatusText.classList.add('error');
                els.progressStatusText.classList.remove('done');
                statusTimer = setTimeout(() => {
                    els.progressStatusText.textContent = '';
                    els.progressStatusText.classList.remove('error', 'done');
                }, 3000);
            },
        });
    } finally {
        isTranslating = false;
        els.translateBtn.disabled = false;
        els.translateBtn.textContent = 'Translate';
    }
}

init();
