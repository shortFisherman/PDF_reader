/** P1-04 文档术语管理面板。所有服务端文本只通过 textContent 渲染。 */

const VIEW_LABELS = {
    authoritative: '权威术语',
    candidates: '候选术语',
};

const STATUS_LABELS = {
    candidate: '候选（不影响正文）',
    accepted: '已接受（影响正文）',
    rejected: '已拒绝（不影响正文）',
};

export function createGlossaryPanel({
    fetchImpl = fetch,
    documentObj = document,
    windowObj = window,
    api = '/api',
    confirmFn = (message) => windowObj.confirm(message),
} = {}) {
    let documentId = null;
    let overlay = null;
    let listEl = null;
    let statusEl = null;
    let errorEl = null;
    let searchInput = null;
    let sortSelect = null;
    let orderSelect = null;
    let pageLabel = null;
    let prevBtn = null;
    let nextBtn = null;
    let termForm = null;
    let sourceInput = null;
    let targetInput = null;
    let noteInput = null;
    let lockedInput = null;
    let formTitle = null;
    let importInput = null;
    let exportLink = null;
    let lastTrigger = null;
    let opened = false;
    let editingSource = null;
    let state = {
        view: 'authoritative',
        items: [],
        revision: { user: 0, candidates: 0 },
        counts: { authoritative: 0, candidates: 0 },
        page: 1,
        totalPages: 1,
        query: '',
        sort: 'source',
        order: 'asc',
    };

    function el(tag, className, text) {
        const node = documentObj.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    function button(text, className = 'glossary-btn-secondary') {
        const node = el('button', className, text);
        node.type = 'button';
        return node;
    }

    function setMessage(message, kind = 'status') {
        if (kind === 'error') {
            errorEl.textContent = message;
            errorEl.classList.remove('hidden');
            statusEl.textContent = '';
            statusEl.classList.add('hidden');
            return;
        }
        statusEl.textContent = message;
        statusEl.className = `glossary-status ${kind}`;
        statusEl.classList.toggle('hidden', !message);
        errorEl.textContent = '';
        errorEl.classList.add('hidden');
    }

    function buildShell() {
        overlay = el('div', 'glossary-overlay');
        overlay.setAttribute('aria-hidden', 'true');
        const dialog = el('div', 'glossary-dialog');
        dialog.setAttribute('role', 'dialog');
        dialog.setAttribute('aria-modal', 'true');
        dialog.setAttribute('aria-labelledby', 'glossary-title');

        const header = el('header', 'glossary-header');
        const titles = el('div', 'glossary-titles');
        const title = el('h2', '', '术语管理');
        title.id = 'glossary-title';
        titles.append(title, el('p', '', '管理当前文档术语；全局 docs/glossary.csv 保持只读显示'));
        const closeBtn = button('×', 'glossary-close-btn');
        closeBtn.setAttribute('aria-label', '关闭术语管理');
        closeBtn.addEventListener('click', close);
        header.append(titles, closeBtn);

        const notice = el('p', 'glossary-notice', '候选不会影响正文；只有接受后才会进入有效词表。');
        const tabs = el('div', 'glossary-tabs');
        for (const [view, label] of Object.entries(VIEW_LABELS)) {
            const tab = button(label, 'glossary-tab');
            tab.dataset.view = view;
            tab.addEventListener('click', () => switchView(view));
            tabs.appendChild(tab);
        }

        const toolbar = el('div', 'glossary-toolbar');
        searchInput = el('input', 'glossary-search');
        searchInput.type = 'search';
        searchInput.maxLength = 200;
        searchInput.placeholder = '搜索 source 或 target';
        searchInput.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') applySearch();
        });
        const searchBtn = button('搜索');
        searchBtn.addEventListener('click', applySearch);
        sortSelect = el('select', 'glossary-select');
        sortSelect.addEventListener('change', () => {
            state.sort = sortSelect.value;
            state.page = 1;
            load();
        });
        orderSelect = el('select', 'glossary-select');
        for (const [value, label] of [['asc', '升序'], ['desc', '降序']]) {
            const option = el('option', '', label);
            option.value = value;
            orderSelect.appendChild(option);
        }
        orderSelect.addEventListener('change', () => {
            state.order = orderSelect.value;
            state.page = 1;
            load();
        });
        const addBtn = button('新建术语', 'glossary-btn-primary');
        addBtn.addEventListener('click', () => {
            if (state.view !== 'authoritative') switchView('authoritative');
            resetForm();
            sourceInput.focus();
        });
        const importBtn = button('导入 CSV');
        importBtn.addEventListener('click', () => importInput.click());
        importInput = el('input', 'hidden');
        importInput.type = 'file';
        importInput.accept = '.csv,text/csv';
        importInput.addEventListener('change', importCsv);
        exportLink = el('a', 'glossary-btn-secondary', '导出 CSV');
        exportLink.setAttribute('download', 'document-glossary.csv');
        toolbar.append(searchInput, searchBtn, sortSelect, orderSelect, addBtn, importBtn, importInput, exportLink);

        termForm = el('form', 'glossary-term-form');
        formTitle = el('h3', '', '新建文档术语');
        sourceInput = field(termForm, 'Source', 'text', 200);
        targetInput = field(termForm, 'Target', 'text', 500);
        noteInput = field(termForm, '备注', 'text', 500);
        const lockLabel = el('label', 'glossary-lock-field');
        lockedInput = el('input');
        lockedInput.type = 'checkbox';
        lockLabel.append(lockedInput, documentObj.createTextNode('创建后锁定'));
        const saveBtn = button('保存', 'glossary-btn-primary');
        saveBtn.type = 'submit';
        const cancelEditBtn = button('清空');
        cancelEditBtn.addEventListener('click', resetForm);
        termForm.prepend(formTitle);
        termForm.append(lockLabel, saveBtn, cancelEditBtn);
        termForm.addEventListener('submit', saveTerm);

        listEl = el('div', 'glossary-list');
        const pager = el('div', 'glossary-pager');
        prevBtn = button('上一页');
        nextBtn = button('下一页');
        pageLabel = el('span', 'glossary-page-label');
        prevBtn.addEventListener('click', () => changePage(-1));
        nextBtn.addEventListener('click', () => changePage(1));
        pager.append(prevBtn, pageLabel, nextBtn);

        const footer = el('footer', 'glossary-footer');
        statusEl = el('p', 'glossary-status hidden');
        statusEl.setAttribute('role', 'status');
        statusEl.setAttribute('aria-live', 'polite');
        errorEl = el('p', 'glossary-error hidden');
        errorEl.setAttribute('role', 'alert');
        footer.append(statusEl, errorEl, pager);

        dialog.append(header, notice, tabs, toolbar, termForm, listEl, footer);
        overlay.appendChild(dialog);
        overlay.addEventListener('click', (event) => {
            if (event.target === overlay) close();
        });
        documentObj.body.appendChild(overlay);
        updateSortOptions();
    }

    function field(form, labelText, type, maxLength) {
        const label = el('label', 'glossary-field');
        label.appendChild(el('span', '', labelText));
        const input = el('input', 'glossary-input');
        input.type = type;
        input.maxLength = maxLength;
        label.appendChild(input);
        form.appendChild(label);
        return input;
    }

    function updateSortOptions() {
        const options = state.view === 'authoritative'
            ? [['source', 'Source'], ['target', 'Target'], ['scope', '范围'], ['locked', '锁定'], ['updated_at', '更新时间']]
            : [['source', 'Source'], ['status', '状态'], ['observations', '观察次数'], ['pages', '页覆盖'], ['updated_at', '更新时间']];
        if (!options.some(([value]) => value === state.sort)) state.sort = 'source';
        sortSelect.textContent = '';
        for (const [value, label] of options) {
            const option = el('option', '', `排序：${label}`);
            option.value = value;
            option.selected = value === state.sort;
            sortSelect.appendChild(option);
        }
        orderSelect.value = state.order;
    }

    function resetForm() {
        editingSource = null;
        formTitle.textContent = '新建文档术语';
        sourceInput.value = '';
        targetInput.value = '';
        noteInput.value = '';
        lockedInput.checked = false;
        lockedInput.disabled = false;
    }

    function applySearch() {
        state.query = searchInput.value.trim();
        state.page = 1;
        load();
    }

    function switchView(view) {
        state.view = view;
        state.page = 1;
        state.query = '';
        searchInput.value = '';
        termForm.classList.toggle('hidden', view !== 'authoritative');
        updateSortOptions();
        resetForm();
        load();
    }

    function changePage(delta) {
        const target = state.page + delta;
        if (target < 1 || target > state.totalPages) return;
        state.page = target;
        load();
    }

    async function readJson(response) {
        try {
            return await response.json();
        } catch {
            return null;
        }
    }

    async function load({ preserveMessage = false } = {}) {
        if (!documentId) {
            setMessage('请先打开 PDF 文档', 'error');
            return false;
        }
        if (!preserveMessage) setMessage('正在加载术语…', 'loading');
        const params = new URLSearchParams({
            document_id: documentId,
            view: state.view,
            q: state.query,
            sort: state.sort,
            order: state.order,
            page: String(state.page),
            page_size: '20',
        });
        let response;
        try {
            response = await fetchImpl(`${api}/glossary?${params}`);
        } catch {
            setMessage('网络错误，请稍后重试', 'error');
            return false;
        }
        const data = await readJson(response);
        if (!response.ok || !data || !Array.isArray(data.items)) {
            setMessage(data && data.error ? data.error : '术语加载失败', 'error');
            return false;
        }
        state.items = data.items;
        state.revision = data.revision;
        state.counts = data.counts || state.counts;
        state.page = data.page;
        state.totalPages = data.total_pages;
        render();
        if (!preserveMessage) setMessage('');
        return true;
    }

    function render() {
        for (const tab of overlay.querySelectorAll('.glossary-tab')) {
            const view = tab.dataset.view;
            tab.classList.toggle('active', view === state.view);
            tab.textContent = `${VIEW_LABELS[view]}（${state.counts[view] || 0}）`;
        }
        listEl.textContent = '';
        if (!state.items.length) {
            listEl.appendChild(el('p', 'glossary-empty', '没有符合条件的术语'));
        } else if (state.view === 'authoritative') {
            state.items.forEach(item => listEl.appendChild(renderAuthority(item)));
        } else {
            state.items.forEach(item => listEl.appendChild(renderCandidate(item)));
        }
        pageLabel.textContent = `第 ${state.page} / ${state.totalPages} 页`;
        prevBtn.disabled = state.page <= 1;
        nextBtn.disabled = state.page >= state.totalPages;
        exportLink.href = `${api}/glossary/export?document_id=${encodeURIComponent(documentId)}`;
    }

    function badge(text, className = '') {
        return el('span', `glossary-badge ${className}`.trim(), text);
    }

    function renderAuthority(item) {
        const card = el('article', 'glossary-card glossary-authority-card');
        const heading = el('div', 'glossary-card-heading');
        const pair = el('div', 'glossary-pair');
        pair.append(el('strong', 'glossary-source', item.source), el('span', 'glossary-arrow', '→'), el('span', 'glossary-target', item.target));
        const badges = el('div', 'glossary-badges');
        const originLabel = item.origin === 'global' ? '全局只读' : item.origin === 'accepted_candidate' ? '已接受候选' : '文档用户术语';
        badges.appendChild(badge(originLabel));
        if (item.locked) badges.appendChild(badge('已锁定', 'locked'));
        if (!item.effective) badges.appendChild(badge('被更高优先级覆盖', 'muted'));
        heading.append(pair, badges);
        card.appendChild(heading);
        if (item.note) card.appendChild(el('p', 'glossary-note', item.note));
        const actions = el('div', 'glossary-actions');
        if (item.origin === 'user') {
            if (item.editable) {
                const editBtn = button('编辑');
                editBtn.addEventListener('click', () => beginEdit(item));
                actions.appendChild(editBtn);
            }
            if (item.lockable) {
                const lockBtn = button(item.locked ? '解锁' : '锁定');
                lockBtn.addEventListener('click', () => mutate('/glossary/terms/lock', {
                    source: item.source,
                    locked: !item.locked,
                    origin: item.origin,
                }));
                actions.appendChild(lockBtn);
            }
            if (item.deletable) {
                const deleteBtn = button('删除', 'glossary-btn-danger');
                deleteBtn.addEventListener('click', () => {
                    if (confirmFn(`删除文档术语“${item.source}”？`)) {
                        mutate('/glossary/terms', { source: item.source }, 'DELETE');
                    }
                });
                actions.appendChild(deleteBtn);
            }
        } else if (item.origin === 'accepted_candidate') {
            if (item.lockable) {
                const lockBtn = button(item.locked ? '解锁' : '锁定');
                lockBtn.addEventListener('click', () => mutate('/glossary/terms/lock', {
                    source: item.source,
                    locked: !item.locked,
                    origin: item.origin,
                }));
                actions.appendChild(lockBtn);
            }
            if (item.deletable) {
                const deleteBtn = button('删除', 'glossary-btn-danger');
                deleteBtn.addEventListener('click', () => {
                    if (confirmFn(`删除已接受术语“${item.source}”？`)) {
                        mutate('/glossary/candidates/reject', { source: item.source });
                    }
                });
                actions.appendChild(deleteBtn);
            }
            const reviewBtn = button('查看候选');
            reviewBtn.addEventListener('click', () => {
                state.view = 'candidates';
                state.query = item.source;
                searchInput.value = item.source;
                state.page = 1;
                termForm.classList.add('hidden');
                updateSortOptions();
                load();
            });
            actions.appendChild(reviewBtn);
        }
        card.appendChild(actions);
        return card;
    }

    function beginEdit(item) {
        editingSource = item.source;
        formTitle.textContent = `编辑：${item.source}`;
        sourceInput.value = item.source;
        targetInput.value = item.target;
        noteInput.value = item.note || '';
        lockedInput.checked = item.locked;
        lockedInput.disabled = true;
        sourceInput.focus();
    }

    function renderCandidate(item) {
        const card = el('article', `glossary-card glossary-candidate-card status-${item.status}`);
        const heading = el('div', 'glossary-card-heading');
        heading.append(el('strong', 'glossary-source', item.source), badge(STATUS_LABELS[item.status] || item.status, item.status));
        if (item.locked) heading.appendChild(badge('已锁定', 'locked'));
        card.appendChild(heading);
        const targetSelect = el('select', 'glossary-select glossary-target-select');
        for (const suggestion of item.targets) {
            const option = el('option', '', `${suggestion.target} · ${suggestion.observations} 次 · ${suggestion.distinct_page_count} 页`);
            option.value = suggestion.target;
            option.selected = suggestion.target === (item.accepted_target || item.recommended_target);
            targetSelect.appendChild(option);
        }
        const customTarget = el('input', 'glossary-input');
        customTarget.type = 'text';
        customTarget.maxLength = 500;
        customTarget.value = item.accepted_target || item.recommended_target || '';
        targetSelect.addEventListener('change', () => { customTarget.value = targetSelect.value; });
        card.append(targetSelect, customTarget);

        for (const suggestion of item.targets) {
            const detail = el('details', 'glossary-evidence');
            const summary = el('summary', '', `${suggestion.target}：${suggestion.observations} 次；页码 ${suggestion.pages.join('、') || '未知'}`);
            detail.appendChild(summary);
            if (!suggestion.evidence.length) detail.appendChild(el('p', '', '无可显示证据'));
            suggestion.evidence.forEach(text => detail.appendChild(el('p', 'glossary-evidence-text', text)));
            card.appendChild(detail);
        }
        const actions = el('div', 'glossary-actions');
        const acceptBtn = button(item.status === 'accepted' ? '更新接受译法' : '接受', 'glossary-btn-primary');
        acceptBtn.addEventListener('click', () => mutate('/glossary/candidates/accept', {
            source: item.source,
            target: customTarget.value.trim(),
        }));
        const rejectBtn = button('拒绝', 'glossary-btn-danger');
        rejectBtn.addEventListener('click', () => mutate('/glossary/candidates/reject', { source: item.source }));
        actions.append(acceptBtn, rejectBtn);
        targetSelect.disabled = item.locked === true;
        customTarget.disabled = item.locked === true;
        acceptBtn.disabled = item.locked === true;
        rejectBtn.disabled = item.locked === true;
        card.appendChild(actions);
        return card;
    }

    async function saveTerm(event) {
        event.preventDefault();
        const source = sourceInput.value.trim();
        const target = targetInput.value.trim();
        if (!source || !target) {
            setMessage('Source 和 Target 不能为空', 'error');
            return;
        }
        if (editingSource) {
            await mutate('/glossary/terms', {
                source: editingSource,
                new_source: source,
                target,
                note: noteInput.value.trim(),
            }, 'PUT');
        } else {
            await mutate('/glossary/terms', {
                source,
                target,
                note: noteInput.value.trim(),
                locked: lockedInput.checked,
            }, 'POST');
        }
        resetForm();
    }

    async function mutate(path, fields, method = 'POST') {
        if (!documentId) return false;
        setMessage('正在保存…', 'loading');
        let response;
        try {
            response = await fetchImpl(`${api}${path}`, {
                method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    document_id: documentId,
                    revision: state.revision,
                    ...fields,
                }),
            });
        } catch {
            setMessage('网络错误，请稍后重试', 'error');
            return false;
        }
        const data = await readJson(response);
        if (!response.ok || !data || data.ok !== true) {
            if (data && data.code === 'glossary_revision_conflict') {
                await load({ preserveMessage: true });
                setMessage('数据已被其他页面更新，已刷新，请重新操作', 'error');
            } else if (data && data.decision_saved === true) {
                await load({ preserveMessage: true });
                setMessage(data.error || '决定已保存，但有效词表更新失败', 'error');
            } else {
                setMessage(data && data.error ? `${data.error}（${data.code || 'unknown'}）` : '保存失败，请重试', 'error');
            }
            return false;
        }
        state.revision = data.revision || state.revision;
        await load({ preserveMessage: true });
        setMessage('已保存并更新有效词表', 'success');
        return true;
    }

    async function importCsv() {
        const file = importInput.files && importInput.files[0];
        if (!file) return;
        let text;
        try {
            text = await file.text();
        } catch {
            setMessage('无法读取 CSV 文件', 'error');
            return;
        }
        await mutate('/glossary/import', { csv: text });
        importInput.value = '';
    }

    function onKeyDown(event) {
        if (opened && event.key === 'Escape') {
            event.preventDefault();
            close();
        }
    }

    async function open(trigger = null) {
        if (!overlay) buildShell();
        lastTrigger = trigger;
        opened = true;
        overlay.classList.add('open');
        overlay.setAttribute('aria-hidden', 'false');
        exportLink.href = documentId
            ? `${api}/glossary/export?document_id=${encodeURIComponent(documentId)}`
            : '#';
        searchInput.focus();
        return load();
    }

    function close() {
        if (!overlay || !opened) return;
        opened = false;
        overlay.classList.remove('open');
        overlay.setAttribute('aria-hidden', 'true');
        if (lastTrigger && typeof lastTrigger.focus === 'function') lastTrigger.focus();
    }

    function setDocument(nextDocumentId) {
        documentId = typeof nextDocumentId === 'string' && nextDocumentId ? nextDocumentId : null;
        state.revision = { user: 0, candidates: 0 };
        state.page = 1;
        state.query = '';
        state.items = [];
        if (opened) load();
    }

    function dispose() {
        documentObj.removeEventListener('keydown', onKeyDown);
        if (overlay) overlay.remove();
        overlay = null;
        opened = false;
    }

    documentObj.addEventListener('keydown', onKeyDown);
    return {
        open,
        close,
        load,
        setDocument,
        dispose,
        getState: () => ({ ...state }),
    };
}
