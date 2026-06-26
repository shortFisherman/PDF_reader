import { readSSEStream } from './sse-client.js';
import { getStageLabel } from './stages.js';

export async function translateCurrentPage(page, callbacks) {
    const { onStageChange, onProgress, onFinish, onError } = callbacks;

    try {
        const resp = await fetch(`/api/translate/${page}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ prompt: callbacks.prompt || null }),
        });

        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.error || 'Translation failed');
        }

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
                onError(evt.error);
            }
        });
    } catch (e) {
        onError(e.message || '翻译出错');
    }
}

export async function translateBatch(from, to, callbacks) {
    const { onBatchInfo, onStageChange, onProgress, onFinish, onError } = callbacks;

    try {
        const resp = await fetch('/api/translate-batch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ from, to, prompt: callbacks.prompt || null }),
        });

        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.error || 'Batch translation failed');
        }

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
                onError(evt.error);
            }
        });
    } catch (e) {
        onError(e.message || '批量翻译出错');
    }
}
