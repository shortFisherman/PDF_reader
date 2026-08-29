/**
 * 翻译 UI 状态机（P2-02）。
 *
 * 集中管理单页/批量翻译共享的 busy 控件、进度条、stage/status 文本、
 * 成功/失败/abort 恢复与延时清理，并用 operation generation 隔离迟到回调。
 *
 * 重要边界：浏览器 AbortController 只终止客户端 fetch/SSE 消费，不是可靠的
 * 服务端取消确认；服务端任务最终生命周期仍由 SSE 断开与后端机制决定。
 */

export const TRANSLATION_STATES = Object.freeze({
    IDLE: 'idle',
    RUNNING: 'running',
    SUCCEEDED: 'succeeded',
    FAILED: 'failed',
    ABORTED: 'aborted',
});

export class TranslationUIController {
    constructor({
        els,
        scheduler = (fn, ms) => setTimeout(fn, ms),
        clearScheduled = (id) => clearTimeout(id),
        successResetDelay = 2000,
        errorResetDelay = 3000,
    }) {
        this._els = els;
        this._scheduler = scheduler;
        this._clearScheduled = clearScheduled;
        this._successResetDelay = successResetDelay;
        this._errorResetDelay = errorResetDelay;
        this._state = TRANSLATION_STATES.IDLE;
        this._generation = 0;
        this._current = null;
        this._timer = null;
        this._prefix = '';
        this._stageText = '';
        this._finishLabel = '翻译完成';
    }

    get state() {
        return this._state;
    }

    get isBusy() {
        return this._state === TRANSLATION_STATES.RUNNING;
    }

    showValidationError(message) {
        this._clearTimer();
        this._els.progressStatusText.textContent = message;
        this._els.progressStatusText.classList.add('error');
        this._els.progressStatusText.classList.remove('done');
        this._scheduleReset(this._errorResetDelay);
    }

    run(operation) {
        if (this._state === TRANSLATION_STATES.RUNNING) {
            return false;
        }
        this._discardCurrent();
        const generation = ++this._generation;
        const abortController = new AbortController();
        this._current = { generation, abortController };
        this._prefix = operation.prefix || '';
        this._stageText = '';
        this._finishLabel = operation.finishLabel || '翻译完成';
        this._state = TRANSLATION_STATES.RUNNING;
        this._clearTimer();
        this._setBusy(true);
        this._els.progressBar.classList.add('active');
        this._els.progressFill.style.width = '0%';
        this._els.progressStatusText.classList.remove('error', 'done');
        this._render();

        const isCurrent = () => this._current !== null && this._current.generation === generation;
        const safe = (fn) => (...args) => {
            if (isCurrent()) {
                fn(...args);
            }
        };

        let task;
        try {
            task = operation.task({
                signal: abortController.signal,
                onStage: safe((stage, label) => {
                    this._stageText = label || '';
                    this._render();
                }),
                onProgress: safe((percent) => {
                    this._els.progressFill.style.width = `${percent}%`;
                }),
                onFinish: safe(() => {
                    this._succeed();
                    if (operation.onSucceeded) {
                        operation.onSucceeded();
                    }
                }),
                onError: safe((message) => this._fail(message)),
                onAbort: safe(() => this._markAborted()),
                onPrefix: safe((prefix) => {
                    this._prefix = prefix;
                    this._render();
                }),
            });
        } catch {
            if (isCurrent()) {
                this._failSafe();
            }
            return true;
        }

        Promise.resolve(task)
            .then(() => {
                if (isCurrent()) {
                    // task 正常 resolve 但从未触发终态（如空 SSE/无终态结束）：安全失败并恢复控件。
                    this._failSafe();
                }
            })
            .catch((error) => {
                if (!isCurrent()) {
                    return;
                }
                if (error && error.name === 'AbortError') {
                    this._markAborted();
                } else {
                    // Promise rejection 只显示固定安全摘要，绝不渲染 raw error.message。
                    this._failSafe();
                }
            });
        return true;
    }

    abortCurrent() {
        if (!this._current) {
            return;
        }
        this._current.abortController.abort();
        this._markAborted();
    }

    dispose() {
        this.abortCurrent();
        this._resetNow();
    }

    _discardCurrent() {
        if (!this._current) {
            return;
        }
        this._current.abortController.abort();
        this._current = null;
    }

    _succeed() {
        this._current = null;
        this._state = TRANSLATION_STATES.SUCCEEDED;
        this._setBusy(false);
        this._els.progressFill.style.width = '100%';
        this._els.progressStatusText.textContent = this._finishLabel;
        this._els.progressStatusText.classList.add('done');
        this._els.progressStatusText.classList.remove('error');
        this._scheduleReset(this._successResetDelay);
    }

    _fail(message) {
        this._current = null;
        this._state = TRANSLATION_STATES.FAILED;
        this._setBusy(false);
        this._els.progressBar.classList.remove('active');
        this._els.progressStatusText.textContent = message;
        this._els.progressStatusText.classList.add('error');
        this._els.progressStatusText.classList.remove('done');
        this._scheduleReset(this._errorResetDelay);
    }

    _markAborted() {
        this._current = null;
        this._state = TRANSLATION_STATES.ABORTED;
        this._setBusy(false);
        this._clearTimer();
        this._els.progressBar.classList.remove('active');
        this._els.progressFill.style.width = '0%';
        this._els.progressStatusText.textContent = '';
        this._els.progressStatusText.classList.remove('error', 'done');
    }

    _resetNow() {
        this._state = TRANSLATION_STATES.IDLE;
        this._setBusy(false);
        this._els.progressBar.classList.remove('active');
        this._els.progressFill.style.width = '0%';
        this._els.progressStatusText.textContent = '';
        this._els.progressStatusText.classList.remove('error', 'done');
    }

    _setBusy(busy) {
        const controls = [
            this._els.translateBtn,
            this._els.rangeTranslateBtn,
            this._els.fullTranslateBtn,
            this._els.fromPage,
            this._els.toPage,
        ];
        for (const control of controls) {
            if (control) {
                control.disabled = busy;
            }
        }
    }

    _render() {
        this._els.progressStatusText.textContent = (this._prefix ? this._prefix : '') + (this._stageText || '');
    }

    _scheduleReset(delay) {
        this._clearTimer();
        this._timer = this._scheduler(() => {
            this._timer = null;
            this._resetNow();
        }, delay);
    }

    _clearTimer() {
        if (this._timer !== null) {
            this._clearScheduled(this._timer);
            this._timer = null;
        }
    }

    _failSafe() {
        this._fail('翻译失败');
    }
}
