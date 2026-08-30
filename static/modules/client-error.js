/**
 * 浏览器全局异常采集（P3-07）。
 *
 * 仅从 window error / unhandledrejection 事件提取白名单字段，使用
 * sendBeacon（回退 keepalive fetch）上报到 /api/client-errors；
 * 上报自身失败被吞掉，绝不进入全局错误监听形成递归。
 */

export const CLIENT_ERROR_FIELD_LIMITS = Object.freeze({
    kind: 64,
    message: 1024,
    source: 512,
    stack: 4096,
});

export const CLIENT_ERROR_MAX_PAYLOAD_BYTES = 8192;

const MAX_COORDINATE = 2147483647;

function cleanText(value, limit) {
    if (value === null || value === undefined) return '';
    let out = '';
    let pendingSpace = false;
    for (const ch of String(value)) {
        if (out.length >= limit) break;
        const code = ch.codePointAt(0);
        const isWhitespace = code === 9 || code === 10 || code === 13 || code === 32;
        const isControl = code < 32 || (code >= 127 && code <= 159);
        if (isWhitespace || isControl) {
            if (out.length > 0) pendingSpace = true;
            continue;
        }
        if (pendingSpace) {
            if (out.length >= limit) break;
            out += ' ';
            pendingSpace = false;
        }
        if (out.length >= limit) break;
        out += ch;
    }
    return out;
}

function cleanCoordinate(value) {
    if (typeof value !== 'number' || !Number.isInteger(value)) return null;
    if (value < 0 || value > MAX_COORDINATE) return null;
    return value;
}

function isErrorLike(value) {
    return (
        value instanceof Error ||
        (value !== null &&
            typeof value === 'object' &&
            (typeof value.message === 'string' || typeof value.stack === 'string'))
    );
}

function buildWindowErrorPayload(event, limits) {
    const payload = { kind: 'window_error' };
    const error = event && event.error;
    if (isErrorLike(error)) {
        payload.message = cleanText(error.message || (event && event.message), limits.message);
        payload.stack = cleanText(error.stack, limits.stack);
    } else {
        payload.message = cleanText(event && event.message, limits.message);
        if (error !== null && error !== undefined && error !== (event && event.message)) {
            payload.stack = cleanText(error, limits.stack);
        }
    }
    const source = cleanText(event && event.filename, limits.source);
    if (source) payload.source = source;
    const line = cleanCoordinate(event && event.lineno);
    const column = cleanCoordinate(event && event.colno);
    if (line !== null) payload.line = line;
    if (column !== null) payload.column = column;
    return payload;
}

function buildRejectionPayload(event, limits) {
    const payload = { kind: 'unhandledrejection' };
    const reason = event && event.reason;
    if (isErrorLike(reason)) {
        payload.message = cleanText(reason.message, limits.message);
        payload.stack = cleanText(reason.stack, limits.stack);
    } else if (reason !== null && reason !== undefined) {
        payload.message = cleanText(reason, limits.message);
    }
    return payload;
}

function payloadBytes(payload) {
    const text = JSON.stringify(payload);
    if (typeof TextEncoder !== 'undefined') {
        return new TextEncoder().encode(text).length;
    }
    return text.length;
}

function trimPayload(payload, limits, maxBytes) {
    const trimmed = { ...payload };
    const fields = ['stack', 'message', 'source', 'kind'];
    let guard = 0;
    while (payloadBytes(trimmed) > maxBytes && guard < 64) {
        let shrank = false;
        for (const field of fields) {
            if (typeof trimmed[field] !== 'string' || trimmed[field].length === 0) continue;
            const next = trimmed[field].slice(0, Math.max(1, Math.floor(trimmed[field].length / 2)));
            if (next.length < trimmed[field].length) {
                trimmed[field] = next;
                shrank = true;
                break;
            }
        }
        if (!shrank) break;
        guard++;
    }
    return trimmed;
}

export function createClientErrorReporter({
    api = '/api/client-errors',
    windowObj = window,
    navigatorObj = navigator,
    fetchImpl = fetch,
    fieldLimits = CLIENT_ERROR_FIELD_LIMITS,
    maxPayloadBytes = CLIENT_ERROR_MAX_PAYLOAD_BYTES,
} = {}) {
    let installed = false;
    let inReport = false;

    function report(payload) {
        if (inReport) return;
        inReport = true;
        try {
            const body = JSON.stringify(trimPayload(payload, fieldLimits, maxPayloadBytes));
            const useBeacon = navigatorObj && typeof navigatorObj.sendBeacon === 'function';
            if (useBeacon) {
                try {
                    const blob = new Blob([body], { type: 'application/json' });
                    if (navigatorObj.sendBeacon(api, blob)) return;
                } catch {
                    // sendBeacon 失败时降级到 keepalive fetch
                }
            }
            const sender = typeof fetchImpl === 'function' ? fetchImpl : fetch;
            if (typeof sender !== 'function') return;
            const promise = sender(api, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body,
                keepalive: true,
            });
            if (promise && typeof promise.catch === 'function') {
                promise.catch(() => {
                    // 非关键上报，失败静默；不允许再次触发全局异常监听
                });
            }
        } catch {
            // 上报自身失败绝不递归
        } finally {
            inReport = false;
        }
    }

    function handleWindowError(event) {
        try {
            report(buildWindowErrorPayload(event, fieldLimits));
        } catch {
            // 事件字段提取失败时静默
        }
    }

    function handleRejection(event) {
        try {
            report(buildRejectionPayload(event, fieldLimits));
        } catch {
            // 事件字段提取失败时静默
        }
    }

    function install() {
        if (installed || !windowObj || typeof windowObj.addEventListener !== 'function') {
            return uninstall;
        }
        installed = true;
        windowObj.addEventListener('error', handleWindowError);
        windowObj.addEventListener('unhandledrejection', handleRejection);
        return uninstall;
    }

    function uninstall() {
        if (!installed || !windowObj || typeof windowObj.removeEventListener !== 'function') return;
        windowObj.removeEventListener('error', handleWindowError);
        windowObj.removeEventListener('unhandledrejection', handleRejection);
        installed = false;
    }

    return { install, uninstall, report };
}
