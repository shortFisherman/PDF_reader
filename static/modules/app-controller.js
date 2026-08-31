/**
 * 阅读器应用控制器（P3-03）。
 *
 * 把原 `app.js` 的装配与页面协调逻辑收束为可注入依赖的工厂：所有 DOM/浏览器
 * 依赖显式传入，测试直接 import 本模块并用 fake 驱动，不再改写源码字符串或
 * 依赖测试全局标记。浏览器入口 `app.js` 只负责装配真实依赖并调用 `init()`。
 */

import { createClientErrorReporter } from './client-error.js';

export function createReaderAppController({
    getElements,
    createPageEl,
    calculatePlaceholderHeight,
    showError,
    setupIntersectionObserver,
    createSettleGate,
    setupPageDetection,
    createAlignmentController,
    fetchStageLabels,
    getStageLabel,
    translateCurrentPage,
    translateBatch,
    setupZoom,
    TranslationUIController,
    createReaderSession,
    createConfigPanel = null,
    createGlossaryPanel = null,
    fetchImpl = fetch,
    windowObj = window,
    documentObj = document,
    requestAnimationFrameFn = requestAnimationFrame,
    confirmFn = (message) => windowObj.confirm(message),
}) {
    const API = '/api';
    let pageCount = 0;
    let pageHeight = 0;
    let pageWidth = 0;
    let currentPage = 0;
    let promptVisible = false;

    let els = null;
    let session = null;
    let translationController = null;
    let alignController = null;
    let zoomInst = null;
    let progressCleanup = null;
    let configPanel = null;
    let glossaryPanel = null;
    let clientErrorReporter = null;

    function createProgressCleanup() {
        function onPageHide() {
            saveProgress();
            translationController.abortCurrent();
        }
        function onVisibility() {
            if (documentObj.hidden) saveProgress();
        }
        windowObj.addEventListener('pagehide', onPageHide);
        documentObj.addEventListener('visibilitychange', onVisibility);
        return () => {
            windowObj.removeEventListener('pagehide', onPageHide);
            documentObj.removeEventListener('visibilitychange', onVisibility);
            // 页面卸载/文档释放时 abort 浏览器请求；服务端任务生命周期仍由 SSE 断开与后端机制决定。
            translationController.abortCurrent();
        };
    }

    async function openPdf() {
        const path = els.pdfPathInput.value.trim();
        if (!path) return;

        let resp;
        try {
            resp = await fetchImpl(`${API}/open`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path }),
            });
        } catch {
            showError(els.fileArea, '网络错误，请稍后重试');
            return;
        }

        if (!resp.ok) {
            const errText = await resp.text();
            let errMsg = 'Failed to open PDF';
            try {
                const errData = JSON.parse(errText);
                errMsg = (errData && typeof errData.error === 'string' && errData.error.trim())
                    ? errData.error
                    : errMsg;
            } catch { /* 非 JSON 错误体：保留固定 fallback */ }
            showError(els.fileArea, errMsg);
            return; // 失败打开保留旧 session（与 409 语义一致）
        }

        const data = await resp.json();

        // 仅在新文档 open 成功、准备替换 DOM 时才释放旧 session，失败打开不销毁旧文档。
        if (session) {
            session.dispose();
            session = null;
        }
        progressCleanup = null;
        alignController = null;
        zoomInst = null;

        pageCount = data.page_count;
        pageHeight = data.page_height;
        pageWidth = data.page_width;
        if (glossaryPanel) glossaryPanel.setDocument(data.document_id);
        if (els.glossaryBtn) els.glossaryBtn.disabled = false;

        els.leftCol.innerHTML = '';
        els.rightCol.innerHTML = '';

        for (let i = 0; i < pageCount; i++) {
            els.leftCol.appendChild(createPageEl(i, 'left', pageWidth, pageHeight));
            els.rightCol.appendChild(createPageEl(i, 'right', pageWidth, pageHeight));
        }

        els.fileArea.classList.add('hidden');
        els.appView.classList.remove('hidden');
        els.toolbar.classList.remove('hidden');

        const settle = createSettleGate(els.leftCol, els.rightCol);
        const io = setupIntersectionObserver({
            load: loadPageImage,
            unload: unloadPageImage,
            settle,
        });
        setupPageDetection({ container: els.leftCol, settle }, onPageChange);

        const newAlignController = createAlignmentController({ leftEl: els.leftCol, rightEl: els.rightCol });
        newAlignController.installScrollListeners();

        const newZoom = setupZoom({
            columns: [els.leftCol, els.rightCol],
            appEl: els.appView,
            onZoomChange: z => { els.zoomLevel.textContent = Math.round(z * 100) + '%'; },
            alignmentController: newAlignController,
        });
        els.zoomLevel.textContent = '100%';
        zoomInst = newZoom;

        progressCleanup = createProgressCleanup();
        session = createReaderSession({
            zoom: zoomInst,
            alignment: newAlignController,
            io,
            settle,
            progressCleanup,
        });
        alignController = newAlignController;

        loadTranslatedState();

        const saved = Number.isInteger(data.saved_page) ? data.saved_page : null;
        if (saved !== null && saved > 0 && saved < pageCount) {
            requestAnimationFrameFn(() => scrollToPage(saved));
        }
    }

    function loadPageImage(container, onLoadCallback) {
        const page = parseInt(container.dataset.page, 10);
        const side = container.dataset.side;

        if (container.dataset.loaded === 'true') return;

        const img = documentObj.createElement('img');
        img.src = `${API}/page/${side}/${page}?t=${Date.now()}`;

        img.onload = () => {
            const placeholder = container.querySelector('.page-placeholder');
            if (placeholder) {
                placeholder.replaceWith(img);
            }
            container.dataset.loaded = 'true';
            if (onLoadCallback) onLoadCallback();
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

        const placeholder = documentObj.createElement('div');
        placeholder.className = 'page-placeholder';
        const ph = calculatePlaceholderHeight(pageWidth, pageHeight);
        placeholder.style.setProperty('--page-ratio', `${ph}%`);
        placeholder.textContent = `Page ${parseInt(container.dataset.page, 10) + 1}`;

        img.replaceWith(placeholder);
        container.dataset.loaded = 'false';
    }

    async function loadTranslatedState() {
        try {
            const resp = await fetchImpl(`${API}/translated-pages`);
            if (!resp.ok) return;
            const data = await resp.json();
            data.pages.forEach(p => {
                const el = els.rightCol.querySelector(`.page-container[data-page="${p}"]`);
                if (el) el.classList.add('translated');
            });
        } catch { /* 非关键状态刷新，失败静默 */ }
    }

    function scrollToPage(index) {
        if (!alignController) return;
        alignController.setLockTarget(index, 0);
        alignController.realign(els.leftCol);
        alignController.realign(els.rightCol);
    }

    function saveProgress() {
        if (!pageCount || !Number.isInteger(currentPage)) return;
        if (currentPage < 0 || currentPage >= pageCount) return;
        const body = JSON.stringify({ page: currentPage });
        if (typeof navigator.sendBeacon === 'function') {
            const blob = new Blob([body], { type: 'application/json' });
            const sent = navigator.sendBeacon(`${API}/reading-progress`, blob);
            if (!sent) {
                fetchImpl(`${API}/reading-progress`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body,
                    keepalive: true,
                }).catch(() => { /* 非关键上报，失败静默 */ });
            }
        } else {
            fetchImpl(`${API}/reading-progress`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body,
                keepalive: true,
            }).catch(() => { /* 非关键上报，失败静默 */ });
        }
    }

    function onPageChange(pageNum) {
        if (pageNum !== currentPage) {
            currentPage = pageNum;
            els.pageIndicator.textContent = `Page ${pageNum + 1}`;
        }
    }

    function refreshSinglePage(targetPage) {
        const rightEl = els.rightCol.querySelector(`.page-container[data-page="${targetPage}"]`);
        if (rightEl) {
            if (rightEl.dataset.loaded === 'true') {
                unloadPageImage(rightEl);
                loadPageImage(rightEl, function () {
                    if (alignController) alignController.onImageLoaded('right', targetPage);
                });
            }
            rightEl.classList.add('translated');
        }
        loadTranslatedState();
    }

    function refreshBatchRange(from, to) {
        for (let p = from - 1; p <= to - 1; p++) {
            const rightEl = els.rightCol.querySelector(`.page-container[data-page="${p}"]`);
            if (rightEl) {
                if (rightEl.dataset.loaded === 'true') {
                    unloadPageImage(rightEl);
                    loadPageImage(rightEl, function () {
                        if (alignController) alignController.onImageLoaded('right', p);
                    });
                }
                rightEl.classList.add('translated');
            }
        }
        loadTranslatedState();
    }

    function onTranslateClick() {
        const targetPage = currentPage;
        translationController.run({
            prefix: '',
            finishLabel: getStageLabel('finish'),
            task: ({ signal, onStage, onProgress, onFinish, onError, onAbort }) =>
                translateCurrentPage(targetPage, {
                    prompt: els.promptInput.value.trim() || null,
                    signal,
                    onStageChange: onStage,
                    onProgress,
                    onFinish,
                    onError,
                    onAbort,
                }),
            onSucceeded: () => refreshSinglePage(targetPage),
        });
    }

    const BATCH_CONFIRM_THRESHOLD = 10;

    function runBatchTranslate(from, to) {
        const pageCnt = pageCount;
        if (!Number.isInteger(from) || !Number.isInteger(to)) {
            translationController.showValidationError('请输入有效页码');
            return;
        }
        if (from < 1 || to < 1 || from > pageCnt || to > pageCnt) {
            translationController.showValidationError('页码超出范围');
            return;
        }
        if (from > to) {
            translationController.showValidationError('起页不能大于止页');
            return;
        }

        const rangeCount = to - from + 1;
        if (rangeCount > BATCH_CONFIRM_THRESHOLD) {
            if (!confirmFn(`翻译 ${rangeCount} 页，预计花费较长时间，确认翻译？`)) return;
        }

        translationController.run({
            prefix: `翻译第 ${from}-${to} 页（共 ${rangeCount} 页）· `,
            finishLabel: getStageLabel('finish'),
            task: ({ signal, onStage, onProgress, onFinish, onError, onAbort, onPrefix }) =>
                translateBatch(from, to, {
                    prompt: els.promptInput.value.trim() || null,
                    signal,
                    onBatchInfo: (f, t, total) =>
                        onPrefix(`翻译第 ${f}-${t} 页（共 ${total} 页）· `),
                    onStageChange: onStage,
                    onProgress,
                    onFinish,
                    onError,
                    onAbort,
                }),
            onSucceeded: () => refreshBatchRange(from, to),
        });
    }

    function onBatchTranslateClick() {
        const from = parseInt(els.fromPage.value, 10);
        const to = parseInt(els.toPage.value, 10);
        runBatchTranslate(from, to);
    }

    function onFullTranslateClick() {
        runBatchTranslate(1, pageCount);
    }

    function init() {
        els = getElements();
        translationController = new TranslationUIController({ els });

        if (!clientErrorReporter) {
            clientErrorReporter = createClientErrorReporter({
                api: `${API}/client-errors`,
                windowObj,
                navigatorObj: windowObj && windowObj.navigator,
                fetchImpl,
            });
        }
        clientErrorReporter.install();

        if (createConfigPanel && els.configBtn) {
            configPanel = createConfigPanel({ fetchImpl, windowObj, documentObj, api: API });
            els.configBtn.addEventListener('click', () => {
                configPanel.open(els.configBtn);
            });
        }

        if (createGlossaryPanel && els.glossaryBtn) {
            glossaryPanel = createGlossaryPanel({ fetchImpl, windowObj, documentObj, api: API });
            els.glossaryBtn.addEventListener('click', () => {
                glossaryPanel.open(els.glossaryBtn);
            });
        }

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

    function dispose() {
        if (session) {
            session.dispose();
            session = null;
            progressCleanup = null;
        } else if (progressCleanup) {
            progressCleanup();
            progressCleanup = null;
        }
        if (translationController) {
            translationController.dispose();
        }
        if (configPanel) {
            configPanel.dispose();
        }
        if (glossaryPanel) {
            glossaryPanel.dispose();
        }
        if (clientErrorReporter) {
            clientErrorReporter.uninstall();
            clientErrorReporter = null;
        }
    }

    return {
        init,
        openPdf,
        dispose,
        getSession: () => session,
        getTranslationController: () => translationController,
        getConfigPanel: () => configPanel,
        getGlossaryPanel: () => glossaryPanel,
    };
}
