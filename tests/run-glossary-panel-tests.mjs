import { JSDOM } from 'jsdom';
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';

const rootDir = resolve(import.meta.dirname, '..');
const dom = new JSDOM('<!doctype html><html><body><button id="trigger">术语</button></body></html>', {
    url: 'http://127.0.0.1/',
});
const windowObj = dom.window;
const documentObj = windowObj.document;
globalThis.window = windowObj;
globalThis.document = documentObj;

const { createGlossaryPanel } = await import(
    pathToFileURL(resolve(rootDir, 'static', 'modules', 'glossary-panel.js')),
);

let passed = 0;
let failed = 0;
function check(condition, message) {
    if (condition) passed++;
    else {
        failed++;
        console.error('FAIL:', message);
    }
}

function response(ok, data, status = ok ? 200 : 400) {
    return { ok, status, json: async () => data };
}

function authorityPayload(revision = { user: 2, candidates: 3 }) {
    return {
        view: 'authoritative',
        revision,
        counts: { authoritative: 3, candidates: 1 },
        page: 1,
        page_size: 20,
        total_pages: 1,
        total: 3,
        items: [
            {
                source: '<img src=x onerror=alert(1)>',
                target: '<b>安全文本</b>',
                scope: 'document',
                origin: 'user',
                locked: false,
                effective: true,
                editable: true,
                lockable: true,
                deletable: true,
                note: '<script>bad()</script>',
                updated_at: '2026-08-31T00:00:00+00:00',
            },
            {
                source: 'AD',
                target: '用户译法',
                scope: 'document',
                origin: 'accepted_candidate',
                locked: false,
                effective: true,
                editable: true,
                lockable: true,
                deletable: true,
                note: '',
                updated_at: '2026-08-31T00:00:00+00:00',
            },
            {
                source: 'Global',
                target: '全局',
                scope: 'global',
                origin: 'global',
                locked: false,
                effective: false,
                editable: false,
                lockable: false,
                deletable: false,
                note: '',
                updated_at: '2026-08-31T00:00:00+00:00',
            },
        ],
    };
}

function candidatePayload(revision = { user: 2, candidates: 3 }) {
    return {
        view: 'candidates',
        revision,
        counts: { authoritative: 3, candidates: 1 },
        page: 1,
        page_size: 20,
        total_pages: 1,
        total: 1,
        items: [{
            source: 'AD',
            status: 'candidate',
            affects_translation: false,
            accepted_target: null,
            recommended_target: '特应性皮炎',
            observations: 4,
            pages: 2,
            updated_at: '2026-08-31T00:00:00+00:00',
            targets: [{
                target: '特应性皮炎',
                rank: 1,
                accepted: false,
                rejected: false,
                observations: 4,
                distinct_page_count: 2,
                pages: [1, 3],
                evidence: ['<img src=x onerror=evil()>', 'bounded evidence'],
                last_observed_at: '2026-08-31T00:00:00+00:00',
            }],
        }],
    };
}

function byText(selector, text) {
    return [...documentObj.querySelectorAll(selector)].find(node => node.textContent === text);
}

// 1. 状态语义、搜索/分页外壳与 HTML 安全渲染。
{
    const calls = [];
    const panel = createGlossaryPanel({
        documentObj,
        windowObj,
        fetchImpl: async (url, options) => {
            calls.push({ url: String(url), options });
            return response(true, authorityPayload());
        },
    });
    panel.setDocument('doc-1');
    await panel.open(documentObj.querySelector('#trigger'));
    check(documentObj.querySelector('.glossary-overlay').classList.contains('open'), 'panel opens');
    check(documentObj.querySelector('.glossary-notice').textContent.includes('候选不会影响正文'), 'candidate warning visible');
    check(documentObj.querySelectorAll('.glossary-list img').length === 0, 'malicious source does not create img element');
    check(documentObj.querySelectorAll('.glossary-list script').length === 0, 'malicious note does not create script element');
    check(documentObj.querySelector('.glossary-source').textContent === '<img src=x onerror=alert(1)>', 'source rendered as text');
    check(calls[0].url.includes('document_id=doc-1'), 'GET carries document identity');
    check(documentObj.querySelector('.glossary-page-label').textContent === '第 1 / 1 页', 'pagination rendered');
    check(documentObj.querySelector('.glossary-tab.active').textContent.includes('权威术语'), 'authority tab active');
    panel.dispose();
}

// 2. 新建、编辑 source/target、锁定、删除都带复合 revision，成功后刷新。
{
    const mutations = [];
    let revision = { user: 2, candidates: 3 };
    const panel = createGlossaryPanel({
        documentObj,
        windowObj,
        confirmFn: () => true,
        fetchImpl: async (url, options = {}) => {
            if (!options.method) return response(true, authorityPayload(revision));
            const body = JSON.parse(options.body);
            mutations.push({ url: String(url), method: options.method, body });
            revision = { user: revision.user + 1, candidates: revision.candidates };
            return response(true, { ok: true, revision, effective_rows: 3 });
        },
    });
    panel.setDocument('doc-crud');
    await panel.open();

    const form = documentObj.querySelector('.glossary-term-form');
    const inputs = form.querySelectorAll('input.glossary-input');
    inputs[0].value = 'TCS';
    inputs[1].value = '外用糖皮质激素';
    form.dispatchEvent(new windowObj.Event('submit', { bubbles: true, cancelable: true }));
    await new Promise(resolvePromise => setTimeout(resolvePromise, 0));
    check(mutations[0].url.endsWith('/api/glossary/terms') && mutations[0].method === 'POST', 'create uses POST');
    check(mutations[0].body.revision.user === 2 && mutations[0].body.revision.candidates === 3, 'create carries compound revision');

    byText('button', '编辑').click();
    inputs[0].value = 'renamed source';
    inputs[1].value = '修改译法';
    form.dispatchEvent(new windowObj.Event('submit', { bubbles: true, cancelable: true }));
    await new Promise(resolvePromise => setTimeout(resolvePromise, 0));
    check(mutations[1].method === 'PUT', 'edit uses PUT');
    check(mutations[1].body.source === '<img src=x onerror=alert(1)>', 'edit carries original source identity');
    check(mutations[1].body.new_source === 'renamed source' && mutations[1].body.target === '修改译法', 'edit changes source and target');

    byText('button', '锁定').click();
    await new Promise(resolvePromise => setTimeout(resolvePromise, 0));
    check(mutations[2].url.endsWith('/api/glossary/terms/lock') && mutations[2].body.locked === true, 'lock action sent');

    byText('button', '删除').click();
    await new Promise(resolvePromise => setTimeout(resolvePromise, 0));
    check(mutations[3].method === 'DELETE', 'delete uses DELETE');
    const acceptedCard = documentObj.querySelectorAll('.glossary-authority-card')[1];
    byText.call(null, '.glossary-authority-card:nth-of-type(2) button', '锁定').click();
    await new Promise(resolvePromise => setTimeout(resolvePromise, 0));
    check(mutations[4].body.origin === 'accepted_candidate', 'accepted authoritative term can be locked');
    check(acceptedCard.textContent.includes('已接受候选'), 'accepted term remains visually distinct');
    check(documentObj.querySelector('.glossary-status').textContent.includes('更新有效词表'), 'success confirms effective update');
    panel.dispose();
}

// 3. 候选接受前可改 target；接受与拒绝均可操作，证据仍按文本渲染。
{
    const mutations = [];
    const panel = createGlossaryPanel({
        documentObj,
        windowObj,
        fetchImpl: async (url, options = {}) => {
            if (!options.method) {
                return response(true, String(url).includes('view=candidates') ? candidatePayload() : authorityPayload());
            }
            mutations.push({ url: String(url), body: JSON.parse(options.body) });
            return response(true, { ok: true, revision: { user: 2, candidates: 4 }, effective_rows: 2 });
        },
    });
    panel.setDocument('doc-candidate');
    await panel.open();
    byText('button', '候选术语（1）').click();
    await new Promise(resolvePromise => setTimeout(resolvePromise, 0));
    check(documentObj.querySelector('.glossary-badge').textContent.includes('不影响正文'), 'candidate status says not effective');
    check(documentObj.querySelectorAll('.glossary-evidence img').length === 0, 'evidence HTML stays text');
    const target = documentObj.querySelector('.glossary-candidate-card > .glossary-input');
    target.value = '用户修改译法';
    byText('button', '接受').click();
    await new Promise(resolvePromise => setTimeout(resolvePromise, 0));
    check(mutations[0].url.endsWith('/api/glossary/candidates/accept'), 'accept endpoint called');
    check(mutations[0].body.target === '用户修改译法', 'edited target accepted');
    byText('button', '拒绝').click();
    await new Promise(resolvePromise => setTimeout(resolvePromise, 0));
    check(mutations[1].url.endsWith('/api/glossary/candidates/reject'), 'reject endpoint called');
    panel.dispose();
}

// 4. revision 冲突自动刷新且不静默覆盖；决定已保存/编译失败也刷新恢复。
{
    let mode = 'conflict';
    let getCount = 0;
    const panel = createGlossaryPanel({
        documentObj,
        windowObj,
        fetchImpl: async (_url, options = {}) => {
            if (!options.method) {
                getCount++;
                return response(true, authorityPayload({ user: getCount + 2, candidates: 3 }));
            }
            if (mode === 'conflict') {
                return response(false, {
                    code: 'glossary_revision_conflict',
                    error: '冲突',
                    revision: { user: 9, candidates: 3 },
                }, 409);
            }
            return response(false, {
                code: 'glossary_compile_failed',
                error: '用户决定已保存，但有效词表更新失败',
                decision_saved: true,
                revision: { user: 10, candidates: 3 },
            }, 500);
        },
    });
    panel.setDocument('doc-conflict');
    await panel.open();
    byText('button', '锁定').click();
    await new Promise(resolvePromise => setTimeout(resolvePromise, 0));
    check(getCount === 2, 'revision conflict triggers reload');
    check(documentObj.querySelector('.glossary-error').textContent.includes('已刷新'), 'conflict recovery is explicit');

    mode = 'compile';
    byText('button', '锁定').click();
    await new Promise(resolvePromise => setTimeout(resolvePromise, 0));
    check(getCount === 3, 'saved-decision compile failure also reloads');
    check(documentObj.querySelector('.glossary-error').textContent.includes('用户决定已保存'), 'partial failure message retained');
    panel.dispose();
}

// 5. CSV 导入/导出入口与 Esc 焦点恢复。
{
    const mutations = [];
    const trigger = documentObj.querySelector('#trigger');
    const panel = createGlossaryPanel({
        documentObj,
        windowObj,
        fetchImpl: async (_url, options = {}) => {
            if (!options.method) return response(true, authorityPayload());
            mutations.push(JSON.parse(options.body));
            return response(true, { ok: true, revision: { user: 3, candidates: 3 }, imported: 1, effective_rows: 3 });
        },
    });
    panel.setDocument('doc-csv');
    await panel.open(trigger);
    const exportLink = byText('a', '导出 CSV');
    check(exportLink.href.includes('/api/glossary/export?document_id=doc-csv'), 'export link carries document identity');
    const input = documentObj.querySelector('input[type="file"]');
    Object.defineProperty(input, 'files', {
        configurable: true,
        value: [{ text: async () => 'source,target\nAD,特应性皮炎\n' }],
    });
    input.dispatchEvent(new windowObj.Event('change', { bubbles: true }));
    await new Promise(resolvePromise => setTimeout(resolvePromise, 0));
    check(mutations[0].csv.includes('AD,特应性皮炎'), 'CSV text sent to import endpoint');
    documentObj.dispatchEvent(new windowObj.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    check(!documentObj.querySelector('.glossary-overlay').classList.contains('open'), 'Escape closes panel');
    check(documentObj.activeElement === trigger, 'close restores trigger focus');
    panel.dispose();
}

console.log(`glossary-panel tests: ${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
