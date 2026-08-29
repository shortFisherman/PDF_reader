import { readFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { JSDOM } from 'jsdom';

const __dirname = dirname(fileURLToPath(import.meta.url));
const rootDir = resolve(__dirname, '..');
const html = readFileSync(resolve(rootDir, 'templates', 'index.html'), 'utf8');

const dom = new JSDOM(html, { url: 'http://localhost', runScripts: 'outside-only' });
const { window: jsdomWindow } = dom;
globalThis.window = jsdomWindow;
globalThis.document = jsdomWindow.document;
Object.defineProperty(globalThis, 'navigator', { value: jsdomWindow.navigator, configurable: true });
globalThis.requestAnimationFrame = (fn) => fn();

let passed = 0;
let failed = 0;

function check(condition, message) {
    if (condition) {
        passed++;
    } else {
        failed++;
        console.error(`FAIL: ${message}`);
    }
}

function createFakeScheduler() {
    let nextId = 1;
    const pending = new Map();
    return {
        set(fn, ms) {
            const id = nextId++;
            pending.set(id, { fn, ms });
            return id;
        },
        clear(id) {
            pending.delete(id);
        },
        runAll() {
            const items = [...pending.values()];
            pending.clear();
            for (const item of items) {
                item.fn();
            }
        },
        pendingCount() {
            return pending.size;
        },
    };
}

function stripExports(code) {
    return code
        .replace(/^import\s+.*$/gm, '')
        .replace(/^export\s+function\b/gm, 'function')
        .replace(/^export\s+const\b/gm, 'const')
        .replace(/^export\s+let\b/gm, 'let')
        .replace(/^export\s+var\b/gm, 'var')
        .replace(/^export\s+/gm, '');
}

function loadModule(names, files) {
    const code = files
        .map((file) => stripExports(readFileSync(resolve(rootDir, 'static', 'modules', file), 'utf8')))
        .join('\n');
    const factory = new Function(`${code}\nreturn { ${names.join(', ')} };`);
    return factory();
}

function makeEls() {
    function el() {
        return {
            classList: { add() {}, remove() {}, toggle() {} },
            style: {},
            dataset: {},
            textContent: '',
            value: '',
            innerHTML: '',
            disabled: false,
            addEventListener() {},
            removeEventListener() {},
            appendChild() {},
            querySelector() { return null; },
            querySelectorAll() { return []; },
        };
    }
    return {
        openBtn: el(),
        pdfPathInput: el(),
        translateBtn: el(),
        rangeTranslateBtn: el(),
        fullTranslateBtn: el(),
        fromPage: el(),
        toPage: el(),
        progressBar: el(),
        progressFill: el(),
        progressStatusText: el(),
        fileArea: el(),
        leftCol: el(),
        rightCol: el(),
        appView: el(),
        toolbar: el(),
        promptInput: el(),
        promptToggle: el(),
        zoomLevel: el(),
        zoomReset: el(),
        pageIndicator: el(),
        toolbarToggle: el(),
        toolbarExtras: el(),
    };
}

function makeSpy() {
    let calls = 0;
    const fn = () => { calls++; };
    fn.count = () => calls;
    return fn;
}

// ============================================================
// 1. TranslationUIController state machine + DOM + scheduler
// ============================================================
const { TranslationUIController, TRANSLATION_STATES } = loadModule(
    ['TranslationUIController', 'TRANSLATION_STATES'],
    ['translation-ui-controller.js'],
);
const els = makeEls();
const sched = createFakeScheduler();
const controller = new TranslationUIController({
    els,
    scheduler: sched.set,
    clearScheduled: sched.clear,
});

{
    check(controller.state === TRANSLATION_STATES.IDLE, 'controller starts idle');
    check(controller.isBusy === false, 'controller not busy initially');
}

{
    let finishTask;
    const gate = new Promise((r) => { finishTask = r; });
    const started = controller.run({
        prefix: '',
        finishLabel: '翻译完成',
        task: ({ signal, onStage, onProgress, onFinish }) => {
            check(signal instanceof AbortSignal, 'operation receives AbortSignal');
            onProgress(30);
            onStage('translating', '正在翻译…');
            return gate.then(() => onFinish());
        },
    });
    check(started === true, 'single run accepted');
    check(controller.state === TRANSLATION_STATES.RUNNING, 'running while task pending');
    check(els.translateBtn.disabled === true, 'busy disables translate button');
    check(els.rangeTranslateBtn.disabled === true, 'busy disables range button');
    check(els.fullTranslateBtn.disabled === true, 'busy disables full button');
    check(els.fromPage.disabled === true, 'busy disables from-page');
    check(els.toPage.disabled === true, 'busy disables to-page');
    check(els.progressStatusText.textContent === '正在翻译…', 'stage text rendered');
    check(els.progressFill.style.width === '30%', 'progress rendered');
    check(controller.run({ task: () => {} }) === false, 'second run rejected while busy');
    check(controller.state === TRANSLATION_STATES.RUNNING, 'state stays running after rejected run');

    finishTask();
    await new Promise((r) => setTimeout(r, 0));
    check(controller.state === TRANSLATION_STATES.SUCCEEDED, 'success transition');
    check(els.progressFill.style.width === '100%', 'success fill 100%');
    check(els.progressStatusText.textContent === '翻译完成', 'success text');
    check(els.translateBtn.disabled === false, 'controls restored after success');
    sched.runAll();
    check(controller.state === TRANSLATION_STATES.IDLE, 'scheduled reset to idle');
    check(els.progressStatusText.textContent === '', 'reset clears text');
}

{
    const batchController = new TranslationUIController({
        els: makeEls(),
        scheduler: sched.set,
        clearScheduled: sched.clear,
    });
    const batchEls = batchController._els;
    let renderedDuringRun = '';
    batchController.run({
        prefix: '翻译第 2-5 页（共 4 页）· ',
        finishLabel: '翻译完成',
        task: ({ onStage, onFinish, onProgress, onPrefix }) => {
            onPrefix('翻译第 1-3 页（共 3 页）· ');
            onProgress(10);
            onStage('layout_analysis', '正在分析版面…');
            renderedDuringRun = batchEls.progressStatusText.textContent;
            onFinish();
        },
    });
    check(
        renderedDuringRun === '翻译第 1-3 页（共 3 页）· 正在分析版面…',
        'batch prefix + stage rendered via shared path',
    );
    check(batchController.state === TRANSLATION_STATES.SUCCEEDED, 'batch succeeds through shared path');
    sched.runAll();
}

{
    let finishFirst;
    const firstGate = new Promise((r) => { finishFirst = r; });
    let firstCallbacks = null;
    const firstEls = makeEls();
    const firstController = new TranslationUIController({
        els: firstEls,
        scheduler: sched.set,
        clearScheduled: sched.clear,
    });
    let firstSucceeded = 0;
    firstController.run({
        prefix: 'op1 · ',
        task: (cbs) => {
            firstCallbacks = cbs;
            return firstGate;
        },
        onSucceeded: () => { firstSucceeded++; },
    });
    firstController.abortCurrent();

    const secondEls = makeEls();
    const secondController = new TranslationUIController({
        els: secondEls,
        scheduler: sched.set,
        clearScheduled: sched.clear,
    });
    let finishSecond;
    const secondGate = new Promise((r) => { finishSecond = r; });
    secondController.run({
        prefix: 'op2 · ',
        task: (cbs) => {
            cbs.onStage('translating', '第二阶段');
            return secondGate;
        },
    });
    firstCallbacks.onPrefix('迟到批量前缀 · ');
    firstCallbacks.onProgress(99);
    firstCallbacks.onStage('translating', '迟到阶段');
    finishFirst();
    await new Promise((r) => setTimeout(r, 0));
    check(
        secondEls.progressStatusText.textContent === 'op2 · 第二阶段',
        'old operation batch_info/prefix cannot modify current operation text',
    );
    check(firstSucceeded === 0, 'aborted old operation never runs onSucceeded');
    finishSecond();
    await new Promise((r) => setTimeout(r, 0));
}

{
    const failEls = makeEls();
    const failController = new TranslationUIController({ els: failEls, scheduler: sched.set, clearScheduled: sched.clear });
    failController.run({
        prefix: '',
        task: ({ onError }) => onError('安全摘要'),
    });
    check(failController.state === TRANSLATION_STATES.FAILED, 'failure transition');
    check(failEls.progressStatusText.textContent === '安全摘要', 'failure text is safe message');
    check(failEls.translateBtn.disabled === false, 'controls restored after failure');
    sched.runAll();
    check(failController.state === TRANSLATION_STATES.IDLE, 'failure scheduled reset');
}

{
    let finishLate;
    const gate = new Promise((r) => { finishLate = r; });
    let captured = null;
    const abortEls = makeEls();
    const abortController = new TranslationUIController({ els: abortEls, scheduler: sched.set, clearScheduled: sched.clear });
    abortController.run({
        prefix: '',
        task: (cbs) => {
            captured = cbs;
            cbs.onProgress(50);
            cbs.onStage('translating', '正在翻译…');
            return gate;
        },
    });
    abortController.abortCurrent();
    check(abortController.state === TRANSLATION_STATES.ABORTED, 'abort transition');
    check(abortEls.translateBtn.disabled === false, 'controls restored after abort');
    check(abortEls.progressStatusText.textContent === '', 'abort clears status text');
    check(abortEls.progressBar.classList, 'abort keeps bar object');

    captured.onProgress(90);
    captured.onStage('translating', '迟到');
    captured.onPrefix('迟到前缀');
    captured.onError('迟到错误');
    finishLate();
    await new Promise((r) => setTimeout(r, 0));
    check(abortController.state === TRANSLATION_STATES.ABORTED, 'late callbacks do not change aborted state');
    check(abortEls.progressStatusText.textContent === '', 'late callbacks do not write DOM');

    abortController.dispose();
    abortController.dispose();
    check(abortController.state === TRANSLATION_STATES.IDLE, 'dispose resets to idle and is idempotent');
}

{
    let abortCount = 0;
    const abortSignalEls = makeEls();
    const idemController = new TranslationUIController({
        els: abortSignalEls,
        scheduler: sched.set,
        clearScheduled: sched.clear,
    });
    let releaseTask;
    const pendingTask = new Promise((r) => { releaseTask = r; });
    idemController.run({
        task: ({ signal }) => {
            signal.addEventListener('abort', () => { abortCount++; });
            return pendingTask;
        },
    });
    idemController.abortCurrent();
    idemController.abortCurrent();
    check(abortCount === 1, 'abortCurrent is idempotent (single abort event)');
    check(idemController.state === TRANSLATION_STATES.ABORTED, 'state aborted after repeated abort');
    releaseTask();
    await new Promise((r) => setTimeout(r, 0));
    check(idemController.state === TRANSLATION_STATES.ABORTED, 'late resolve after abort does not flip terminal');
}

{
    const syncThrowEls = makeEls();
    const syncThrowController = new TranslationUIController({
        els: syncThrowEls,
        scheduler: sched.set,
        clearScheduled: sched.clear,
    });
    const accepted = syncThrowController.run({
        prefix: '',
        task: () => {
            throw new Error('RAW-SYNC-SENTINEL');
        },
    });
    check(accepted === true, 'sync throw run accepted and contained');
    check(syncThrowController.state === TRANSLATION_STATES.FAILED, 'sync throw -> failed');
    check(syncThrowEls.progressStatusText.textContent === '翻译失败', 'sync throw shows fixed safe summary');
    check(!syncThrowEls.progressStatusText.textContent.includes('RAW-SYNC-SENTINEL'), 'sync throw raw text not leaked');
    check(syncThrowEls.translateBtn.disabled === false, 'controls restored after sync throw');
    sched.runAll();
}

{
    const finishThrowEls = makeEls();
    const finishThrowController = new TranslationUIController({
        els: finishThrowEls,
        scheduler: sched.set,
        clearScheduled: sched.clear,
    });
    let finishThrowSucceeded = 0;
    finishThrowController.run({
        finishLabel: '翻译完成',
        task: ({ onFinish }) => {
            onFinish();
            throw new Error('RAW-FINISH-THROW-SENTINEL');
        },
        onSucceeded: () => { finishThrowSucceeded++; },
    });
    check(
        finishThrowController.state === TRANSLATION_STATES.SUCCEEDED,
        'onFinish then sync throw keeps succeeded terminal',
    );
    check(finishThrowSucceeded === 1, 'onSucceeded exactly once after finish+throw');
    check(finishThrowEls.progressStatusText.textContent === '翻译完成', 'finish+throw keeps success text');
    check(!finishThrowEls.progressStatusText.textContent.includes('RAW-FINISH-THROW'), 'finish+throw sentinel not leaked');
    sched.runAll();
}

{
    const errorThrowEls = makeEls();
    const errorThrowController = new TranslationUIController({
        els: errorThrowEls,
        scheduler: sched.set,
        clearScheduled: sched.clear,
    });
    errorThrowController.run({
        task: ({ onError }) => {
            onError('第一次失败文本');
            throw new Error('RAW-ERROR-THROW-SENTINEL');
        },
    });
    check(
        errorThrowController.state === TRANSLATION_STATES.FAILED,
        'onError then sync throw keeps first failed terminal',
    );
    check(errorThrowEls.progressStatusText.textContent === '第一次失败文本', 'onError+throw keeps first failure text');
    check(!errorThrowEls.progressStatusText.textContent.includes('RAW-ERROR-THROW'), 'error+throw sentinel not leaked');
    check(sched.pendingCount() === 1, 'error+throw does not duplicate reset schedule');
    sched.runAll();
}

{
    const abortThrowEls = makeEls();
    const abortThrowController = new TranslationUIController({
        els: abortThrowEls,
        scheduler: sched.set,
        clearScheduled: sched.clear,
    });
    abortThrowController.run({
        task: ({ onAbort }) => {
            onAbort();
            throw new Error('RAW-ABORT-THROW-SENTINEL');
        },
    });
    check(
        abortThrowController.state === TRANSLATION_STATES.ABORTED,
        'onAbort then sync throw keeps aborted terminal',
    );
    check(abortThrowEls.progressStatusText.textContent === '', 'abort+throw keeps no error text');
    check(!abortThrowEls.progressStatusText.textContent.includes('RAW-ABORT-THROW'), 'abort+throw sentinel not leaked');
}

{
    const rejectEls = makeEls();
    const rejectController = new TranslationUIController({
        els: rejectEls,
        scheduler: sched.set,
        clearScheduled: sched.clear,
    });
    rejectController.run({
        task: () => Promise.reject(new Error('RAW-REJECT-SENTINEL')),
    });
    await new Promise((r) => setTimeout(r, 0));
    check(rejectController.state === TRANSLATION_STATES.FAILED, 'promise rejection -> failed');
    check(rejectEls.progressStatusText.textContent === '翻译失败', 'rejection shows fixed safe summary');
    check(!rejectEls.progressStatusText.textContent.includes('RAW-REJECT-SENTINEL'), 'rejection raw text not leaked');
    check(rejectEls.translateBtn.disabled === false, 'controls restored after rejection');
    sched.runAll();
}

{
    const emptyEls = makeEls();
    const emptyController = new TranslationUIController({
        els: emptyEls,
        scheduler: sched.set,
        clearScheduled: sched.clear,
    });
    let emptySucceeded = 0;
    emptyController.run({
        task: () => Promise.resolve(),
        onSucceeded: () => { emptySucceeded++; },
    });
    await new Promise((r) => setTimeout(r, 0));
    check(emptyController.state === TRANSLATION_STATES.FAILED, 'resolve without terminal -> failed');
    check(emptyEls.progressStatusText.textContent === '翻译失败', 'resolve-without-terminal shows safe summary');
    check(emptyEls.translateBtn.disabled === false, 'controls restored after resolve-without-terminal');
    check(emptySucceeded === 0, 'onSucceeded not called without terminal finish');
    sched.runAll();
}

{
    const normalEls = makeEls();
    const normalController = new TranslationUIController({
        els: normalEls,
        scheduler: sched.set,
        clearScheduled: sched.clear,
    });
    let normalSucceeded = 0;
    normalController.run({
        task: ({ onFinish }) => {
            onFinish();
            return Promise.resolve();
        },
        onSucceeded: () => { normalSucceeded++; },
    });
    await new Promise((r) => setTimeout(r, 0));
    check(normalController.state === TRANSLATION_STATES.SUCCEEDED, 'terminal then resolve stays succeeded');
    check(normalSucceeded === 1, 'onSucceeded called exactly once');
    sched.runAll();
}

{
    const validationEls = makeEls();
    const validationController = new TranslationUIController({
        els: validationEls,
        scheduler: sched.set,
        clearScheduled: sched.clear,
    });
    validationController.showValidationError('请输入有效页码');
    check(validationEls.progressStatusText.textContent === '请输入有效页码', 'validation message shown');
    check(validationController.state === TRANSLATION_STATES.IDLE, 'validation keeps idle state');
    sched.runAll();
    check(validationEls.progressStatusText.textContent === '', 'validation message clears');
}

// ============================================================
// 2. translator AbortSignal / onAbort
// ============================================================
const translator = loadModule(
    ['translateCurrentPage', 'translateBatch'],
    ['stages.js', 'sse-client.js', 'translator.js'],
);

{
    const abortController = new AbortController();
    let capturedSignal = null;
    let aborted = false;
    let errored = false;
    globalThis.fetch = async (url, init) => {
        capturedSignal = init.signal;
        return new Promise((resolve, reject) => {
            init.signal.addEventListener('abort', () => {
                const error = new Error('The operation was aborted.');
                error.name = 'AbortError';
                reject(error);
            });
        });
    };
    const pending = translator.translateCurrentPage(1, {
        signal: abortController.signal,
        onStageChange: () => {},
        onProgress: () => {},
        onFinish: () => {},
        onError: () => { errored = true; },
        onAbort: () => { aborted = true; },
    });
    check(capturedSignal === abortController.signal, 'single fetch receives AbortSignal');
    abortController.abort();
    await pending;
    check(aborted === true, 'single abort calls onAbort');
    check(errored === false, 'single abort does not call onError');
}

{
    const abortController = new AbortController();
    let capturedSignal = null;
    let aborted = false;
    let errored = false;
    globalThis.fetch = async (url, init) => {
        capturedSignal = init.signal;
        return new Promise((resolve, reject) => {
            init.signal.addEventListener('abort', () => {
                const error = new Error('The operation was aborted.');
                error.name = 'AbortError';
                reject(error);
            });
        });
    };
    const pending = translator.translateBatch(1, 2, {
        signal: abortController.signal,
        onBatchInfo: () => {},
        onStageChange: () => {},
        onProgress: () => {},
        onFinish: () => {},
        onError: () => { errored = true; },
        onAbort: () => { aborted = true; },
        prompt: null,
    });
    check(capturedSignal === abortController.signal, 'batch fetch receives AbortSignal');
    abortController.abort();
    await pending;
    check(aborted === true, 'batch abort calls onAbort');
    check(errored === false, 'batch abort does not call onError');
}

// ============================================================
// 3. reader-session dispose semantics
// ============================================================
const { createReaderSession } = loadModule(['createReaderSession'], ['reader-session.js']);
{
    const zoom = { dispose: makeSpy() };
    const alignment = { dispose: makeSpy() };
    const io = { observer: { disconnect: makeSpy() } };
    const settle = { dispose: makeSpy() };
    const progressCleanup = makeSpy();
    const session = createReaderSession({ zoom, alignment, io, settle, progressCleanup });
    check(session.disposed === false, 'session starts active');
    session.dispose();
    session.dispose();
    check(session.disposed === true, 'session disposed flag set');
    check(zoom.dispose.count() === 1, 'zoom.dispose exactly once');
    check(alignment.dispose.count() === 1, 'alignment.dispose exactly once');
    check(io.observer.disconnect.count() === 1, 'io.observer.disconnect exactly once');
    check(settle.dispose.count() === 1, 'settle.dispose exactly once');
    check(progressCleanup.count() === 1, 'progressCleanup exactly once');
}

// ============================================================
// 4. app.js harness: open success/failure session lifecycle
// ============================================================
{
    const appSource = readFileSync(resolve(rootDir, 'static', 'app.js'), 'utf8');
    const readerSessionSource = readFileSync(resolve(rootDir, 'static', 'modules', 'reader-session.js'), 'utf8');
    const controllerSource = readFileSync(
        resolve(rootDir, 'static', 'modules', 'translation-ui-controller.js'),
        'utf8',
    );

    check(appSource.includes("from './modules/translation-ui-controller.js'"), 'app.js imports controller module');
    check(appSource.includes("from './modules/reader-session.js'"), 'app.js imports reader-session module');
    check(!appSource.includes('els.progressBar.classList'), 'no direct progress bar DOM ops in app.js');
    check(!appSource.includes('els.progressStatusText'), 'no direct status text DOM ops in app.js');
    check(!appSource.includes('els.translateBtn.disabled'), 'no direct translate button disable in app.js');
    check(!appSource.includes('setBatchControlsDisabled'), 'no duplicated batch disable helper in app.js');
    check((appSource.match(/translationController\.run\(/g) || []).length === 2, 'single+batch share controller.run');
    check(!controllerSource.includes('setPrefix('), 'controller has no legacy public setPrefix');
    check(!appSource.includes('.setPrefix('), 'app uses only operation-scoped onPrefix');

    const harnessEls = makeEls();
    const errors = [];
    const zoom = { dispose: makeSpy(), resetZoom() {} };
    const alignment = {
        dispose: makeSpy(),
        installScrollListeners() {},
        setLockTarget() {},
        realign() {},
        onImageLoaded() {},
    };
    const io = { observer: { disconnect: makeSpy() } };
    const settle = { dispose: makeSpy() };

    let pagehideAdds = 0;
    let pagehideRemoves = 0;
    let visAdds = 0;
    let visRemoves = 0;
    let pagehideHandler = null;
    const origWinAdd = jsdomWindow.addEventListener.bind(jsdomWindow);
    const origWinRemove = jsdomWindow.removeEventListener.bind(jsdomWindow);
    const origDocAdd = jsdomWindow.document.addEventListener.bind(jsdomWindow.document);
    const origDocRemove = jsdomWindow.document.removeEventListener.bind(jsdomWindow.document);
    jsdomWindow.addEventListener = (type, fn, opts) => {
        if (type === 'pagehide') {
            pagehideAdds++;
            pagehideHandler = fn;
        }
        origWinAdd(type, fn, opts);
    };
    jsdomWindow.removeEventListener = (type, fn, opts) => {
        if (type === 'pagehide') pagehideRemoves++;
        origWinRemove(type, fn, opts);
    };
    jsdomWindow.document.addEventListener = (type, fn, opts) => {
        if (type === 'visibilitychange') visAdds++;
        origDocAdd(type, fn, opts);
    };
    jsdomWindow.document.removeEventListener = (type, fn, opts) => {
        if (type === 'visibilitychange') visRemoves++;
        origDocRemove(type, fn, opts);
    };

    class FakeTranslationController {
        constructor() {
            this.runCalls = 0;
            this.abortCalls = 0;
            this.validation = [];
            this.active = false;
        }
        run(operation) {
            this.runCalls++;
            this.active = true;
            operation.task({
                signal: new AbortController().signal,
                onStage: () => {},
                onProgress: () => {},
                onFinish: () => {},
                onError: () => {},
                onAbort: () => {},
            });
            return true;
        }
        abortCurrent() {
            if (this.active) {
                this.active = false;
                this.abortCalls++;
            }
        }
        showValidationError(message) {
            this.validation.push(message);
        }
    }

    const openResponses = [
        { ok: true, json: async () => ({ page_count: 2, page_height: 10, page_width: 10, saved_page: null }) },
        { ok: true, json: async () => ({ page_count: 3, page_height: 12, page_width: 12, saved_page: null }) },
        {
            ok: false,
            json: async () => ({ error: 'file not found' }),
            text: async () => JSON.stringify({ error: 'file not found' }),
        },
    ];
    let openIndex = 0;
    let readingProgressCalls = 0;
    globalThis.fetch = async (url) => {
        if (url === '/api/translated-pages') {
            return { ok: true, json: async () => ({ pages: [] }) };
        }
        if (url === '/api/reading-progress') {
            readingProgressCalls++;
            return { ok: true, json: async () => ({ ok: true }) };
        }
        return openResponses[openIndex++];
    };

    const combined = `${stripExports(readerSessionSource)}\n${stripExports(appSource)}`;
    const factory = new Function(
        'getElements',
        'createPageEl',
        'calculatePlaceholderHeight',
        'showError',
        'setupIntersectionObserver',
        'createSettleGate',
        'setupPageDetection',
        'createAlignmentController',
        'fetchStageLabels',
        'getStageLabel',
        'translateCurrentPage',
        'translateBatch',
        'setupZoom',
        'TranslationUIController',
        'window',
        'document',
        'fetch',
        'requestAnimationFrame',
        `${combined}\nreturn { openPdf, getSession: () => session, getTranslationController: () => translationController };`,
    );

    const api = factory(
        () => harnessEls,
        () => ({}),
        () => 600,
        (parent, message) => errors.push(message),
        () => io,
        () => settle,
        () => {},
        () => alignment,
        () => {},
        (stage) => (stage === 'finish' ? '翻译完成' : stage),
        async (page, callbacks) => { callbacks.onFinish(); },
        async (from, to, callbacks) => { callbacks.onFinish(); },
        () => zoom,
        FakeTranslationController,
        jsdomWindow,
        jsdomWindow.document,
        globalThis.fetch,
        globalThis.requestAnimationFrame,
    );

    harnessEls.pdfPathInput.value = '/first.pdf';
    await api.openPdf();
    const session1 = api.getSession();
    check(session1 !== null && session1.disposed === false, 'first successful open creates active session');
    check(pagehideAdds === 1, 'first open registers pagehide listener');
    check(visAdds === 1, 'first open registers visibilitychange listener');
    const fakeController = api.getTranslationController();
    fakeController.run({ task: () => {} });
    check(fakeController.active === true, 'fake controller has active request before session swap');

    const before = {
        zoom: zoom.dispose.count(),
        alignment: alignment.dispose.count(),
        io: io.observer.disconnect.count(),
        settle: settle.dispose.count(),
        pagehideRemoves,
        visRemoves,
        abort: fakeController.abortCalls,
    };

    harnessEls.pdfPathInput.value = '/second.pdf';
    await api.openPdf();
    check(session1.disposed === true, 'old session disposed after second successful open');
    check(pagehideAdds === 2, 'second open registers new pagehide listener');
    check(visAdds === 2, 'second open registers new visibilitychange listener');
    check(zoom.dispose.count() === before.zoom + 1, 'zoom.dispose exactly once on session swap');
    check(alignment.dispose.count() === before.alignment + 1, 'alignment.dispose exactly once on session swap');
    check(io.observer.disconnect.count() === before.io + 1, 'observer.disconnect exactly once on session swap');
    check(settle.dispose.count() === before.settle + 1, 'settle.dispose exactly once on session swap');
    check(pagehideRemoves === before.pagehideRemoves + 1, 'pagehide listener removed exactly once');
    check(visRemoves === before.visRemoves + 1, 'visibilitychange listener removed exactly once');
    check(
        fakeController.abortCalls === before.abort + 1,
        'old request aborted exactly once on session swap',
    );
    check(fakeController.active === false, 'active request cleared after session swap');

    const session2 = api.getSession();
    check(session2 !== null && session2.disposed === false, 'new session active after second open');

    harnessEls.pdfPathInput.value = '/missing.pdf';
    await api.openPdf();
    check(errors.length === 1 && errors[0] === 'file not found', 'failed open shows safe error');
    check(zoom.dispose.count() === before.zoom + 1, 'failed open keeps old session (zoom not disposed)');
    check(alignment.dispose.count() === before.alignment + 1, 'failed open keeps old session (alignment not disposed)');
    check(session2.disposed === false, 'failed open keeps current session active');

    const pagehideBefore = { abort: fakeController.abortCalls, pagehideRemoves };
    fakeController.active = true;
    check(typeof pagehideHandler === 'function', 'pagehide handler captured');
    pagehideHandler();
    check(readingProgressCalls === 1, 'pagehide handler saves reading progress');
    check(fakeController.abortCalls === pagehideBefore.abort + 1, 'pagehide handler aborts current request');
    check(fakeController.active === false, 'pagehide abort clears active request');

    const idle = {
        zoom: zoom.dispose.count(),
        alignment: alignment.dispose.count(),
        io: io.observer.disconnect.count(),
        settle: settle.dispose.count(),
    };
    session2.dispose();
    session2.dispose();
    check(zoom.dispose.count() === idle.zoom + 1, 'session dispose idempotent (zoom once)');
    check(alignment.dispose.count() === idle.alignment + 1, 'session dispose idempotent (alignment once)');
    check(io.observer.disconnect.count() === idle.io + 1, 'session dispose idempotent (observer once)');
    check(settle.dispose.count() === idle.settle + 1, 'session dispose idempotent (settle once)');
    check(fakeController.abortCalls === pagehideBefore.abort + 1, 'repeated dispose/cleanup has no extra abort side effect');
    check(pagehideRemoves === pagehideBefore.pagehideRemoves + 1, 'dispose removes pagehide listener exactly once');
}

console.log('');
console.log(`Results: ${passed} passed, ${failed} failed`);
if (failed > 0) {
    process.exit(1);
} else {
    console.log('PASS');
    process.exit(0);
}
