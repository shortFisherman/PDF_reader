import { getElements, createPageEl, calculatePlaceholderHeight } from './modules/dom.js';
import { setupIntersectionObserver } from './modules/lazy-loader.js';
import { createSettleGate, setupPageDetection } from './modules/scroll-sync.js';
import { fetchStageLabels, getStageLabel } from './modules/stages.js';
import { translateCurrentPage, translateBatch } from './modules/translator.js';
import { setupZoom } from './modules/zoom.js';

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
let zoomInst = null;
let progressCleanup = null;

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
    els.rangeTranslateBtn.addEventListener('click', onBatchTranslateClick);
    els.fullTranslateBtn.addEventListener('click', onFullTranslateClick);
    els.zoomReset.addEventListener('click', () => {
        if (zoomInst) zoomInst.resetZoom();
    });

    els.toolbarToggle.addEventListener('click', () => {
        const extras = els.toolbarExtras;
        const isCollapsed = extras.classList.toggle('collapsed');
        els.toolbarToggle.textContent = isCollapsed ? '▶' : '▼';
    });

    fetchStageLabels();
}

async function openPdf() {
    if (zoomInst) { zoomInst.dispose(); zoomInst = null; }
    if (io) { io.observer.disconnect(); io = null; }
    if (settle) { settle.dispose(); settle = null; }
    if (progressCleanup) { progressCleanup(); progressCleanup = null; }

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
        setupPageDetection({ container: els.leftCol, settle }, onPageChange);
        zoomInst = setupZoom({
            columns: [els.leftCol, els.rightCol],
            appEl: els.appView,
            onZoomChange: z => { els.zoomLevel.textContent = Math.round(z * 100) + '%'; }
        });
        els.zoomLevel.textContent = '100%';
        loadTranslatedState();

        const saved = Number.isInteger(data.saved_page) ? data.saved_page : null;
        if (saved !== null && saved > 0 && saved < pageCount) {
            requestAnimationFrame(() => scrollToPage(saved));
        }

        // 卸载期上报：pagehide（主）+ visibilitychange hidden（兜底）
        function onPageHide() { saveProgress(); }
        function onVisibility() { if (document.hidden) saveProgress(); }
        window.addEventListener('pagehide', onPageHide);
        document.addEventListener('visibilitychange', onVisibility);
        progressCleanup = () => {
            window.removeEventListener('pagehide', onPageHide);
            document.removeEventListener('visibilitychange', onVisibility);
        };

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

function scrollToPage(index) {
    const el = els.leftCol.querySelector(`.page-container[data-page="${index}"]`);
    if (!el) return;
    el.scrollIntoView({ block: 'start' });
}

function saveProgress() {
    if (!pageCount || !Number.isInteger(currentPage)) return;
    if (currentPage < 0 || currentPage >= pageCount) return;
    const body = JSON.stringify({ page: currentPage });
    if (typeof navigator.sendBeacon === 'function') {
        const blob = new Blob([body], { type: 'application/json' });
        const sent = navigator.sendBeacon(`${API}/reading-progress`, blob);
        if (!sent) {
            fetch(`${API}/reading-progress`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body,
                keepalive: true,
            }).catch(() => {});
        }
    } else {
        fetch(`${API}/reading-progress`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body,
            keepalive: true,
        }).catch(() => {});
    }
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
    setBatchControlsDisabled(true);
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
        setBatchControlsDisabled(false);
        els.translateBtn.textContent = 'Translate';
    }
}

const BATCH_CONFIRM_THRESHOLD = 10;

function setBatchControlsDisabled(disabled) {
    els.rangeTranslateBtn.disabled = disabled;
    els.fullTranslateBtn.disabled = disabled;
    els.fromPage.disabled = disabled;
    els.toPage.disabled = disabled;
}

async function runBatchTranslate(from, to) {
    if (isTranslating) return;

    const pageCnt = pageCount;
    if (!Number.isInteger(from) || !Number.isInteger(to)) {
        els.progressStatusText.textContent = '请输入有效页码';
        els.progressStatusText.classList.add('error');
        return;
    }
    if (from < 1 || to < 1 || from > pageCnt || to > pageCnt) {
        els.progressStatusText.textContent = '页码超出范围';
        els.progressStatusText.classList.add('error');
        return;
    }
    if (from > to) {
        els.progressStatusText.textContent = '起页不能大于止页';
        els.progressStatusText.classList.add('error');
        return;
    }

    const rangeCount = to - from + 1;
    if (rangeCount > BATCH_CONFIRM_THRESHOLD) {
        if (!window.confirm(`翻译 ${rangeCount} 页，预计花费较长时间，确认翻译？`)) return;
    }

    isTranslating = true;
    setBatchControlsDisabled(true);
    els.translateBtn.disabled = true;
    els.translateBtn.textContent = 'Translating...';
    els.progressBar.classList.add('active');
    els.progressFill.style.width = '0%';
    els.progressStatusText.textContent = `翻译第 ${from}-${to} 页（共 ${rangeCount} 页）· `;
    els.progressStatusText.classList.remove('error', 'done');
    if (statusTimer) { clearTimeout(statusTimer); statusTimer = null; }

    try {
        await translateBatch(from, to, {
            prompt: els.promptInput.value.trim() || null,
            onBatchInfo(f, t, total) {
                els.progressStatusText.textContent = `翻译第 ${f}-${t} 页（共 ${total} 页）· `;
            },
            onStageChange(stage, labelText) {
                const base = `翻译第 ${from}-${to} 页（共 ${rangeCount} 页）· `;
                els.progressStatusText.textContent = base + labelText;
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

                // Batch refresh right-column translated images in range
                for (let p = from - 1; p <= to - 1; p++) {
                    const rightEl = els.rightCol.querySelector(`.page-container[data-page="${p}"]`);
                    if (rightEl) {
                        if (rightEl.dataset.loaded === 'true') {
                            unloadPageImage(rightEl);
                            loadPageImage(rightEl);
                        }
                        rightEl.classList.add('translated');
                    }
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
        setBatchControlsDisabled(false);
        els.translateBtn.disabled = false;
        els.translateBtn.textContent = 'Translate';
    }
}

async function onBatchTranslateClick() {
    const from = parseInt(els.fromPage.value, 10);
    const to = parseInt(els.toPage.value, 10);
    await runBatchTranslate(from, to);
}

async function onFullTranslateClick() {
    await runBatchTranslate(1, pageCount);
}

init();
