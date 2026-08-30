import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { JSDOM } from 'jsdom';

const testsDir = fileURLToPath(new URL('.', import.meta.url));
const rootDir = resolve(testsDir, '..');

const dom = new JSDOM('<!doctype html><html><body></body></html>', {
    url: 'http://localhost',
    runScripts: 'outside-only',
});
const { window: jsdomWindow } = dom;
globalThis.window = jsdomWindow;
globalThis.document = jsdomWindow.document;

const { createClientErrorReporter, CLIENT_ERROR_FIELD_LIMITS } = await import(
    pathToFileURL(resolve(rootDir, 'static', 'modules', 'client-error.js')),
);

function installReporter({ navigatorObj = {}, fetchImpl } = {}) {
    const calls = { fetches: [] };
    const reporter = createClientErrorReporter({
        windowObj: jsdomWindow,
        navigatorObj,
        fetchImpl: fetchImpl || (async (url, options) => {
            calls.fetches.push({ url, options });
            return { ok: true };
        }),
    });
    reporter.install();
    return { reporter, calls };
}

// 1. window error with a real Error: whitelist fields, cleaned newlines, keepalive fetch.
{
    const { reporter, calls } = installReporter();
    const error = new Error('boom\nsecond line');
    jsdomWindow.dispatchEvent(new jsdomWindow.ErrorEvent('error', {
        message: 'boom\nsecond line',
        filename: 'http://localhost/app.js',
        lineno: 12,
        colno: 3,
        error,
    }));

    assert.equal(calls.fetches.length, 1, 'window error event must trigger one report');
    const body = JSON.parse(calls.fetches[0].options.body);
    assert.equal(body.kind, 'window_error');
    assert.equal(body.message, 'boom second line');
    assert.equal(body.source, 'http://localhost/app.js');
    assert.equal(body.line, 12);
    assert.equal(body.column, 3);
    assert.ok(body.stack.includes('boom second line'), 'stack must be extracted from Error');
    assert.deepEqual(
        Object.keys(body).sort(),
        ['column', 'kind', 'line', 'message', 'source', 'stack'],
        'payload must contain only whitelist fields',
    );
    assert.equal(calls.fetches[0].options.keepalive, true, 'fallback fetch must use keepalive');
    assert.equal(calls.fetches[0].url, '/api/client-errors');
    reporter.uninstall();
}

// 2. window error without an Error object still reports message/source/line/column.
{
    const { reporter, calls } = installReporter();
    jsdomWindow.dispatchEvent(new jsdomWindow.ErrorEvent('error', {
        message: 'string only failure',
        filename: 'http://localhost/x.js',
        lineno: 7,
        colno: 2,
    }));

    const body = JSON.parse(calls.fetches[0].options.body);
    assert.equal(body.kind, 'window_error');
    assert.equal(body.message, 'string only failure');
    assert.equal(body.source, 'http://localhost/x.js');
    assert.equal(body.line, 7);
    assert.equal(body.column, 2);
    reporter.uninstall();
}

// 3. unhandledrejection with a real Error.
{
    const { reporter, calls } = installReporter();
    jsdomWindow.dispatchEvent(new jsdomWindow.PromiseRejectionEvent('unhandledrejection', {
        promise: Promise.resolve(),
        reason: new Error('reject boom'),
    }));

    const body = JSON.parse(calls.fetches[0].options.body);
    assert.equal(body.kind, 'unhandledrejection');
    assert.equal(body.message, 'reject boom');
    assert.ok(body.stack.includes('reject boom'), 'stack must be extracted from rejection reason');
    reporter.uninstall();
}

// 4. unhandledrejection with string/plain-object reasons: no business data leakage.
{
    const { reporter, calls } = installReporter();
    jsdomWindow.dispatchEvent(new jsdomWindow.PromiseRejectionEvent('unhandledrejection', {
        promise: Promise.resolve(),
        reason: 'plain\nstring reason',
    }));

    const body = JSON.parse(calls.fetches[0].options.body);
    assert.equal(body.kind, 'unhandledrejection');
    assert.equal(body.message, 'plain string reason');
    assert.ok(!('stack' in body));
    reporter.uninstall();
}
{
    const { reporter, calls } = installReporter();
    jsdomWindow.dispatchEvent(new jsdomWindow.PromiseRejectionEvent('unhandledrejection', {
        promise: Promise.resolve(),
        reason: { userPrompt: 'private business data', apiKey: 'sk-leak-test-123' },
    }));

    const body = JSON.parse(calls.fetches[0].options.body);
    assert.equal(body.message, '[object Object]');
    assert.ok(!('userPrompt' in body), 'object fields must not be serialized');
    assert.ok(!('apiKey' in body), 'api key must not be serialized');
    reporter.uninstall();
}

// 5. sendBeacon preferred; keepalive fetch used when sendBeacon is unavailable or rejects.
{
    const beacons = [];
    const fetches = [];
    const reporter = createClientErrorReporter({
        windowObj: jsdomWindow,
        navigatorObj: {
            sendBeacon(url, blob) {
                beacons.push({ url, blob });
                return true;
            },
        },
        fetchImpl: async (url, options) => {
            fetches.push({ url, options });
            return { ok: true };
        },
    });
    reporter.install();
    jsdomWindow.dispatchEvent(new jsdomWindow.ErrorEvent('error', {
        message: 'beacon path',
        error: new Error('beacon path'),
    }));

    assert.equal(beacons.length, 1, 'sendBeacon must be preferred');
    assert.equal(fetches.length, 0);
    assert.equal(beacons[0].url, '/api/client-errors');
    assert.equal(beacons[0].blob.type, 'application/json');
    assert.equal(JSON.parse(await beacons[0].blob.text()).message, 'beacon path');
    reporter.uninstall();
}
{
    const beacons = [];
    const fetches = [];
    const reporter = createClientErrorReporter({
        windowObj: jsdomWindow,
        navigatorObj: {
            sendBeacon() {
                beacons.push('called');
                return false;
            },
        },
        fetchImpl: async (url, options) => {
            fetches.push({ url, options });
            return { ok: true };
        },
    });
    reporter.install();
    jsdomWindow.dispatchEvent(new jsdomWindow.ErrorEvent('error', {
        message: 'fallback path',
        error: new Error('fallback path'),
    }));

    assert.equal(beacons.length, 1);
    assert.equal(fetches.length, 1, 'must fall back to keepalive fetch when sendBeacon returns false');
    assert.equal(fetches[0].options.keepalive, true);
    reporter.uninstall();
}

// 6. Self-reporting failure must not recurse or permanently disable later reports.
{
    let fetches = 0;
    const reporter = createClientErrorReporter({
        windowObj: jsdomWindow,
        navigatorObj: {},
        fetchImpl() {
            fetches++;
            throw new TypeError('report transport failed');
        },
    });
    reporter.install();
    jsdomWindow.dispatchEvent(new jsdomWindow.ErrorEvent('error', {
        message: 'first',
        error: new Error('first'),
    }));
    assert.equal(fetches, 1, 'synchronous self failure must be swallowed');

    jsdomWindow.dispatchEvent(new jsdomWindow.ErrorEvent('error', {
        message: 'second',
        error: new Error('second'),
    }));
    assert.equal(fetches, 2, 'reporter must reset after a self failure');
    reporter.uninstall();
}

// 7. Field length limits and total payload byte cap.
{
    const { reporter, calls } = installReporter();
    jsdomWindow.dispatchEvent(new jsdomWindow.ErrorEvent('error', {
        message: 'm'.repeat(5000),
        filename: 'http://localhost/app.js',
        error: new Error('m'.repeat(5000)),
    }));

    const body = JSON.parse(calls.fetches[0].options.body);
    assert.equal(body.message.length, CLIENT_ERROR_FIELD_LIMITS.message);
    assert.ok(body.stack.length <= CLIENT_ERROR_FIELD_LIMITS.stack);
    assert.ok(body.source.length <= CLIENT_ERROR_FIELD_LIMITS.source);
    reporter.uninstall();
}
{
    const fetches = [];
    const reporter = createClientErrorReporter({
        windowObj: jsdomWindow,
        navigatorObj: {},
        fetchImpl: async (url, options) => {
            fetches.push({ url, options });
            return { ok: true };
        },
        maxPayloadBytes: 256,
    });
    reporter.install();
    jsdomWindow.dispatchEvent(new jsdomWindow.ErrorEvent('error', {
        message: 'm'.repeat(2000),
        error: new Error('t'.repeat(4000)),
    }));

    const body = JSON.parse(fetches[0].options.body);
    const bytes = new TextEncoder().encode(JSON.stringify(body)).length;
    assert.ok(bytes <= 256, `payload must fit maxPayloadBytes, got ${bytes}`);
    reporter.uninstall();
}

// 8. install is idempotent; uninstall removes both global listeners.
{
    let fetches = 0;
    const reporter = createClientErrorReporter({
        windowObj: jsdomWindow,
        navigatorObj: {},
        fetchImpl: async () => {
            fetches++;
            return { ok: true };
        },
    });
    reporter.install();
    reporter.install();
    jsdomWindow.dispatchEvent(new jsdomWindow.ErrorEvent('error', {
        message: 'once',
        error: new Error('once'),
    }));
    assert.equal(fetches, 1, 'double install must not double-report');

    reporter.uninstall();
    jsdomWindow.dispatchEvent(new jsdomWindow.ErrorEvent('error', {
        message: 'gone',
        error: new Error('gone'),
    }));
    jsdomWindow.dispatchEvent(new jsdomWindow.PromiseRejectionEvent('unhandledrejection', {
        promise: Promise.resolve(),
        reason: new Error('gone'),
    }));
    assert.equal(fetches, 1, 'uninstall must remove error and unhandledrejection listeners');
}

// 9. app-controller wires the reporter into init/dispose.
{
    const controllerSource = readFileSync(
        resolve(rootDir, 'static', 'modules', 'app-controller.js'),
        'utf8',
    );
    assert.ok(controllerSource.includes("from './client-error.js'"), 'app-controller imports client-error module');
    assert.ok(controllerSource.includes('clientErrorReporter.install()'), 'app-controller installs reporter in init');
    assert.ok(controllerSource.includes('clientErrorReporter.uninstall()'), 'app-controller uninstalls reporter in dispose');
}

console.log('Client error reporting tests passed');
