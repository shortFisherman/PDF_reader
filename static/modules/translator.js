import { readSSEStream } from './sse-client.js';
import { getStageLabel } from './stages.js';

const NETWORK_ERROR_MESSAGE = '网络错误，请稍后重试';
const REQUEST_ERROR_MESSAGE = '翻译请求失败';
const SSE_ERROR_MESSAGE = '翻译失败';

function safeMessage(value, fallback) {
    return (typeof value === 'string' && value.trim()) ? value : fallback;
}

export async function translateCurrentPage(page, callbacks) {
    const { onStageChange, onProgress, onFinish, onError, onAbort, signal } = callbacks;

    let resp;
    try {
        resp = await fetch(`/api/translate/${page}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ prompt: callbacks.prompt || null }),
            signal,
        });
    } catch (e) {
        if (e && e.name === 'AbortError') {
            if (onAbort) onAbort();
        } else {
            onError(NETWORK_ERROR_MESSAGE);
        }
        return;
    }

    if (!resp.ok) {
        let msg = REQUEST_ERROR_MESSAGE;
        try {
            const err = await resp.json();
            msg = safeMessage(err && err.error, msg);
        } catch { /* 非 JSON 错误体：保留固定 fallback */ }
        onError(msg);
        return;
    }

    try {
        await readSSEStream(resp, (evt) => {
            if (evt.type === 'progress') {
                onProgress(evt.progress);
                if (evt.stage) {
                    let label = getStageLabel(evt.stage);
                    if (evt.stage_current > 0 && evt.stage_total > 0) {
                        label += ` 第 ${evt.stage_current}/${evt.stage_total} 段`;
                    }
                    onStageChange(evt.stage, label);
                }
            } else if (evt.type === 'finish') {
                onFinish();
            } else if (evt.type === 'error') {
                onError(safeMessage(evt.error, SSE_ERROR_MESSAGE));
            }
        });
    } catch (e) {
        if (e && e.name === 'AbortError') {
            if (onAbort) onAbort();
        } else {
            onError(NETWORK_ERROR_MESSAGE);
        }
    }
}

export async function translateBatch(from, to, callbacks) {
    const { onBatchInfo, onStageChange, onProgress, onFinish, onError, onAbort, signal } = callbacks;

    let resp;
    try {
        resp = await fetch('/api/translate-batch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ from, to, prompt: callbacks.prompt || null }),
            signal,
        });
    } catch (e) {
        if (e && e.name === 'AbortError') {
            if (onAbort) onAbort();
        } else {
            onError(NETWORK_ERROR_MESSAGE);
        }
        return;
    }

    if (!resp.ok) {
        let msg = REQUEST_ERROR_MESSAGE;
        try {
            const err = await resp.json();
            msg = safeMessage(err && err.error, msg);
        } catch { /* 非 JSON 错误体：保留固定 fallback */ }
        onError(msg);
        return;
    }

    try {
        await readSSEStream(resp, (evt) => {
            if (evt.type === 'batch_info') {
                onBatchInfo(evt.from, evt.to, evt.total);
            } else if (evt.type === 'progress') {
                onProgress(evt.progress);
                if (evt.stage) {
                    let label = getStageLabel(evt.stage);
                    if (evt.stage_current > 0 && evt.stage_total > 0) {
                        label += ` 第 ${evt.stage_current}/${evt.stage_total} 段`;
                    }
                    onStageChange(evt.stage, label);
                }
            } else if (evt.type === 'finish') {
                onFinish();
            } else if (evt.type === 'error') {
                onError(safeMessage(evt.error, SSE_ERROR_MESSAGE));
            }
        });
    } catch (e) {
        if (e && e.name === 'AbortError') {
            if (onAbort) onAbort();
        } else {
            onError(NETWORK_ERROR_MESSAGE);
        }
    }
}
