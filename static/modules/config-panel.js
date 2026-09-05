/**
 * 配置中心面板（P4-xx）。
 *
 * 以可注入依赖的工厂实现：所有 DOM/浏览器依赖显式传入，jsdom 测试直接
 * 驱动 fake fetch 与真实 DOM，不依赖浏览器全局。职责：
 *
 * - 始终可见的“配置”按钮打开 modal/drawer，Esc/关闭按钮/点击遮罩可关闭；
 * - 按必填/可选/进阶分组渲染 schema，每个字段显示中文名、TOML 路径、
 *   用途说明与默认/常用值提示；
 * - provider 使用友好下拉（最后一项实际值 openai_compatible），按 provider
 *   显示/隐藏适用字段，openai_compatible 时 Base URL 标记必填；
 * - API Key 使用密码框且从不回显，仅在新值非空时随顶层 api_key 提交；
 * - 加载/保存状态、错误码与“重启后生效”提示齐全。
 */

const GROUP_LABELS = { required: '必填', optional: '可选', advanced: '进阶' };

function inputId(path) {
    return 'cfg-' + path.replace(/\./g, '-');
}

export function createConfigPanel({
    fetchImpl = fetch,
    documentObj = document,
    windowObj = window,
    api = '/api',
    setupMode = false,
} = {}) {
    let overlay = null;
    let dialog = null;
    let bodyEl = null;
    let statusEl = null;
    let errorEl = null;
    let envBannerEl = null;
    let saveBtn = null;
    let apiKeyInput = null;
    let providerSelect = null;
    let lastTrigger = null;
    let opened = false;
    let state = { schema: [], values: {}, revision: null, envOverrides: {} };
    const fieldMap = new Map();

    function createElement(tag, className, text) {
        const el = documentObj.createElement(tag);
        if (className) el.className = className;
        if (text !== undefined) el.textContent = text;
        return el;
    }

    function buildShell() {
        overlay = createElement('div', 'config-overlay');
        overlay.setAttribute('aria-hidden', 'true');

        dialog = createElement('div', 'config-dialog');
        dialog.setAttribute('role', 'dialog');
        dialog.setAttribute('aria-modal', 'true');
        dialog.setAttribute('aria-labelledby', 'config-dialog-title');
        dialog.setAttribute('aria-describedby', 'config-dialog-desc');

        const header = createElement('div', 'config-dialog-header');
        const titleWrap = createElement('div', 'config-dialog-titles');
        const title = createElement('h2', '', setupMode ? '首次配置' : '配置中心');
        title.id = 'config-dialog-title';
        const subtitle = createElement(
            'p',
            '',
            setupMode
                ? '填写必需信息并保存；配置会写入便携 data/config/config.toml'
                : '修改会写入 config.toml，服务重启后生效',
        );
        subtitle.id = 'config-dialog-desc';
        titleWrap.append(title, subtitle);

        const closeBtn = createElement('button', 'config-close-btn', '×');
        closeBtn.type = 'button';
        closeBtn.setAttribute('aria-label', '关闭配置');
        closeBtn.dataset.close = 'true';
        closeBtn.addEventListener('click', () => close());
        header.append(titleWrap, closeBtn);

        envBannerEl = createElement('div', 'config-env-banner hidden');

        bodyEl = createElement('div', 'config-dialog-body');
        bodyEl.setAttribute('tabindex', '-1');

        const footer = createElement('div', 'config-dialog-footer');
        statusEl = createElement('p', 'config-status hidden');
        statusEl.setAttribute('role', 'status');
        statusEl.setAttribute('aria-live', 'polite');
        errorEl = createElement('p', 'config-error hidden');
        errorEl.setAttribute('role', 'alert');
        const spacer = createElement('span', 'config-spacer');
        const cancelBtn = createElement('button', 'config-btn-secondary', '关闭');
        cancelBtn.type = 'button';
        cancelBtn.dataset.close = 'true';
        cancelBtn.addEventListener('click', () => close());
        saveBtn = createElement('button', 'config-btn-primary', '保存配置');
        saveBtn.type = 'button';
        saveBtn.addEventListener('click', submit);
        footer.append(statusEl, errorEl, spacer, cancelBtn, saveBtn);

        dialog.append(header, envBannerEl, bodyEl, footer);
        overlay.appendChild(dialog);

        overlay.addEventListener('click', (event) => {
            if (event.target === overlay) close();
        });
        documentObj.body.appendChild(overlay);
    }

    function buildHint(spec) {
        const parts = [];
        if (spec.default !== null && spec.default !== undefined && spec.default !== '') {
            parts.push(`默认值：${spec.default}`);
        } else if (spec.group !== 'required') {
            parts.push('默认：留空使用内置默认');
        }
        if (spec.suggestions && spec.suggestions.length) {
            parts.push(`常用值：${spec.suggestions.join('、')}`);
        }
        return parts.join('；');
    }

    function createDatalist(spec, index) {
        if (!spec.suggestions || !spec.suggestions.length) return null;
        const list = createElement('datalist');
        list.id = `cfg-dl-${index}`;
        for (const suggestion of spec.suggestions) {
            const option = createElement('option');
            option.value = suggestion;
            list.appendChild(option);
        }
        return list;
    }

    function currentValue(spec) {
        const [section, key] = spec.path.split('.');
        const sectionValues = state.values[section] || {};
        const raw = sectionValues[key];
        if (raw === undefined || raw === null) return spec.default !== undefined && spec.default !== null ? spec.default : '';
        return raw;
    }

    function createControl(spec, index) {
        const value = currentValue(spec);
        let control;
        if (spec.control === 'select' || spec.control === 'bool') {
            control = createElement('select');
            if (value === '' || value === null || value === undefined) {
                const empty = createElement('option');
                empty.value = '';
                empty.textContent = '留空（使用默认）';
                empty.selected = true;
                control.appendChild(empty);
            }
            for (const option of spec.options || []) {
                const optionEl = createElement('option');
                optionEl.value = String(option.value);
                optionEl.textContent = option.label;
                if (value !== '' && value !== null && value !== undefined && String(value) === String(option.value)) {
                    optionEl.selected = true;
                }
                control.appendChild(optionEl);
            }
            if (spec.control === 'bool') control.className = 'config-control config-control-bool';
            else control.className = 'config-control config-control-select';
        } else if (spec.control === 'int' || spec.control === 'float') {
            control = createElement('input');
            control.type = 'number';
            control.className = 'config-control config-control-number';
            if (spec.control === 'float') control.step = 'any';
            if (spec.minimum !== null && spec.minimum !== undefined) control.min = String(spec.minimum);
            if (spec.maximum !== null && spec.maximum !== undefined) control.max = String(spec.maximum);
            if (value !== '' && value !== null && value !== undefined) control.value = String(value);
            if (spec.suggestions && spec.suggestions.length) {
                control.setAttribute('list', `cfg-dl-${index}`);
            }
        } else if (spec.control === 'password') {
            control = createElement('input');
            control.type = 'password';
            control.className = 'config-control config-control-password';
            control.autocomplete = 'off';
            control.value = '';
        } else {
            control = createElement('input');
            control.type = 'text';
            control.className = 'config-control config-control-text';
            if (value !== '' && value !== null && value !== undefined) control.value = String(value);
            if (spec.suggestions && spec.suggestions.length) {
                control.setAttribute('list', `cfg-dl-${index}`);
            }
        }
        control.id = inputId(spec.path);
        return control;
    }

    function createField(spec, index) {
        const wrap = createElement('div', 'config-field');
        wrap.dataset.path = spec.path;

        const labelRow = createElement('div', 'config-field-label');
        const label = createElement('label', 'config-label', spec.name);
        label.htmlFor = inputId(spec.path);
        const requiredStar = createElement('span', 'config-required hidden', '*');
        requiredStar.setAttribute('aria-label', '必填');
        if (spec.group === 'required') requiredStar.classList.remove('hidden');
        label.appendChild(requiredStar);
        const pathEl = createElement('code', 'config-path', spec.path);
        labelRow.append(label, pathEl);

        const descEl = createElement('p', 'config-desc', spec.description);
        const control = createControl(spec, index);
        const hintEl = createElement('p', 'config-hint', buildHint(spec));
        const list = createDatalist(spec, index);
        wrap.append(labelRow, descEl, control, hintEl);
        if (list) wrap.appendChild(list);

        fieldMap.set(spec.path, { spec, wrap, control, hintEl, requiredStar });
        return wrap;
    }

    function renderForm() {
        bodyEl.textContent = '';
        fieldMap.clear();
        providerSelect = null;
        apiKeyInput = null;

        if (state.envOverrides && state.envOverrides.MODEL_API_KEY) {
            envBannerEl.classList.remove('hidden');
            envBannerEl.textContent = '环境变量 MODEL_API_KEY 正在覆盖 API Key：页面显示的是文件状态，'
                + '写入文件不会立即生效，且环境变量仍然优先。';
        } else {
            envBannerEl.classList.add('hidden');
            envBannerEl.textContent = '';
        }

        for (const group of ['required', 'optional', 'advanced']) {
            const fields = state.schema.filter(spec => spec.group === group);
            if (!fields.length) continue;
            const sectionEl = createElement('section', 'config-group');
            sectionEl.dataset.group = group;
            const heading = createElement('h3', 'config-group-title', GROUP_LABELS[group]);
            sectionEl.appendChild(heading);
            const groupBody = createElement('div', 'config-group-body');
            fields.forEach((spec, i) => groupBody.appendChild(createField(spec, i)));
            sectionEl.appendChild(groupBody);
            bodyEl.appendChild(sectionEl);
        }

        providerSelect = fieldMap.get('model.provider')?.control || null;
        apiKeyInput = fieldMap.get('model.api_key')?.control || null;
        if (providerSelect) {
            providerSelect.addEventListener('change', onProviderChange);
        }
        onProviderChange();
    }

    function isApplicable(spec, provider) {
        return !spec.providers || spec.providers.includes(provider);
    }

    function onProviderChange() {
        const provider = providerSelect ? providerSelect.value : null;
        for (const { spec, wrap, requiredStar, hintEl } of fieldMap.values()) {
            const visible = isApplicable(spec, provider);
            wrap.classList.toggle('config-field-hidden', !visible);
            // 切换服务商后，旧的“发送温度/发送推理强度”开关会使重启校验失败，
            // 在不适用时立即重置为 false，保证保存结果可启动。
            if (!visible && (spec.path === 'model.send_temperature' || spec.path === 'model.send_reasoning_effort')) {
                const control = fieldMap.get(spec.path).control;
                if (control && control.value !== 'false') control.value = 'false';
            }
            const requiredNow = spec.group === 'required' || (spec.required_for || []).includes(provider);
            requiredStar.classList.toggle('hidden', !requiredNow);
            wrap.classList.toggle('config-field-required-now', requiredNow);
            if (spec.required_for && spec.required_for.includes(provider)) {
                hintEl.dataset.requiredNow = 'true';
            } else {
                delete hintEl.dataset.requiredNow;
            }
        }
        if (apiKeyInput) {
            if (state.envOverrides && state.envOverrides.MODEL_API_KEY) {
                const apiKeyStatus = state.values.model && state.values.model.api_key;
                apiKeyInput.placeholder = apiKeyStatus && apiKeyStatus.configured
                    ? '环境变量已设置；输入可覆盖文件值'
                    : '环境变量 MODEL_API_KEY 为空/无效，请先修正';
            } else {
                const apiKeyStatus = state.values.model && state.values.model.api_key;
                apiKeyInput.placeholder = apiKeyStatus && apiKeyStatus.configured
                    ? '已配置，输入可覆盖'
                    : '必填：请输入 API Key';
            }
        }
    }

    function readControl(spec, control) {
        if (spec.control === 'bool') {
            if (control.value === '') return null;
            return control.value === 'true';
        }
        if (spec.control === 'int') {
            if (control.value.trim() === '') return null;
            const num = Number(control.value);
            return Number.isInteger(num) ? num : NaN;
        }
        if (spec.control === 'float') {
            if (control.value.trim() === '') return null;
            return Number(control.value);
        }
        return control.value.trim();
    }

    function setNestedValue(values, path, value) {
        const [section, key] = path.split('.');
        if (!values[section]) values[section] = {};
        values[section][key] = value;
    }

    function gatherValues() {
        const values = {};
        const errors = [];
        const provider = providerSelect ? providerSelect.value : null;
        for (const { spec, control } of fieldMap.values()) {
            if (spec.secret) continue;
            if (!isApplicable(spec, provider)) continue;
            const requiredNow = spec.group === 'required' || (spec.required_for || []).includes(provider);
            let value = readControl(spec, control);
            const empty = value === null || value === '' || (typeof value === 'number' && Number.isNaN(value));
            if (empty) {
                if (requiredNow) {
                    errors.push(`${spec.name}（${spec.path}）为必填项`);
                    continue;
                }
                value = null;
            } else if (spec.control === 'int' || spec.control === 'float') {
                if (Number.isNaN(value)) {
                    errors.push(`${spec.name}（${spec.path}）必须是有效数字`);
                    continue;
                }
            }
            setNestedValue(values, spec.path, value);
        }
        // 切换服务商后，这两个开关会被隐藏并重置为 false；必须显式提交，
        // 否则旧 TOML 中的 true 会保留，导致重启时后端校验失败。
        // 其余不适用字段（temperature/reasoning_effort/base_url 等）继续不提交，
        // 保留旧值——后端对它们只警告/忽略，不会阻塞保存。
        for (const path of ['model.send_temperature', 'model.send_reasoning_effort']) {
            const entry = fieldMap.get(path);
            if (!entry || isApplicable(entry.spec, provider)) continue;
            const value = readControl(entry.spec, entry.control);
            if (value === null || value === undefined || value === '') continue;
            setNestedValue(values, path, value);
        }
        // API Key 必填校验：未配置且未输入时直接阻止保存；
        // 环境变量存在但为空/无效时，写文件也不会生效，必须提示先修正环境变量。
        const apiKeyStatus = state.values.model && state.values.model.api_key;
        const apiKeyTyped = apiKeyInput && apiKeyInput.value.trim();
        if (!apiKeyStatus || apiKeyStatus.configured !== true) {
            if (state.envOverrides && state.envOverrides.MODEL_API_KEY) {
                errors.push(
                    'API Key 必填：环境变量 MODEL_API_KEY 当前为空或无效，'
                    + '请先修正或移除该环境变量（写入文件不会生效）',
                );
            } else if (!apiKeyTyped) {
                errors.push('API Key 必填：请输入 API Key');
            }
        }
        return { values, errors };
    }

    function setStatus(text, kind) {
        if (kind === 'error') {
            errorEl.textContent = text;
            errorEl.classList.remove('hidden');
            statusEl.classList.add('hidden');
            statusEl.textContent = '';
        } else {
            statusEl.textContent = text;
            statusEl.className = 'config-status';
            if (kind) statusEl.classList.add(kind);
            statusEl.classList.remove('hidden');
            errorEl.classList.add('hidden');
            errorEl.textContent = '';
        }
    }

    function showRestartHint() {
        const message = setupMode
            ? '保存成功：配置已原子写入。请关闭程序并再次双击 PDF Reader，届时将进入正式模式。'
            : '保存成功：配置已写入 config.toml，服务重启后生效（当前会话仍使用旧配置）。';
        setStatus(message, 'success');
    }

    async function load() {
        setStatus('正在加载配置…', 'loading');
        let resp;
        try {
            resp = await fetchImpl(`${api}/config`);
        } catch {
            setStatus('网络错误，请稍后重试', 'error');
            return;
        }
        let data = null;
        try {
            data = await resp.json();
        } catch { /* 非 JSON 响应 */ }
        if (!resp.ok || !data || !Array.isArray(data.schema)) {
            const message = data && data.error ? data.error : '配置加载失败';
            setStatus(message, 'error');
            return;
        }
        state = {
            schema: data.schema,
            values: data.values || {},
            revision: data.revision || null,
            envOverrides: data.env_overrides || {},
            repairRequired: data.repair_required === true,
            repairMessage: data.repair_message || '',
        };
        renderForm();
        if (state.repairRequired) {
            setStatus(state.repairMessage || '现有配置文件已损坏，保存后可修复。', 'error');
        } else if (setupMode) {
            setStatus('请填写必填项；校验错误不会写入配置文件。', 'loading');
        } else {
            setStatus('', null);
            statusEl.classList.add('hidden');
        }
    }

    async function submit() {
        if (!saveBtn) return;
        saveBtn.disabled = true;
        const { values, errors } = gatherValues();
        if (errors.length) {
            setStatus(errors[0], 'error');
            saveBtn.disabled = false;
            return;
        }
        const payload = { values, revision: state.revision };
        if (apiKeyInput && apiKeyInput.value.trim()) {
            payload.api_key = apiKeyInput.value.trim();
        }
        setStatus('正在保存…', 'loading');
        let resp;
        try {
            resp = await fetchImpl(`${api}/config`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
        } catch {
            setStatus('网络错误，请稍后重试', 'error');
            saveBtn.disabled = false;
            return;
        }
        let data = null;
        try {
            data = await resp.json();
        } catch { /* 非 JSON 响应 */ }
        if (!resp.ok || !data || data.ok !== true) {
            const message = data && data.error ? `${data.error}（${data.code || 'unknown'}）` : '保存失败，请重试';
            setStatus(message, 'error');
            saveBtn.disabled = false;
            return;
        }
        state.revision = data.revision || state.revision;
        if (apiKeyInput) apiKeyInput.value = '';
        onProviderChange();
        showRestartHint();
        saveBtn.disabled = false;
    }

    function onKeyDown(event) {
        if (event.key === 'Escape') {
            event.preventDefault();
            close();
        }
    }

    function open(trigger) {
        if (!overlay) buildShell();
        lastTrigger = trigger || documentObj.activeElement;
        opened = true;
        overlay.classList.add('open');
        overlay.setAttribute('aria-hidden', 'false');
        windowObj.addEventListener('keydown', onKeyDown);
        const closeBtn = dialog.querySelector('[data-close="true"]');
        if (closeBtn) closeBtn.focus();
        return load();
    }

    function close() {
        if (!opened) return;
        opened = false;
        overlay.classList.remove('open');
        overlay.setAttribute('aria-hidden', 'true');
        windowObj.removeEventListener('keydown', onKeyDown);
        if (lastTrigger && typeof lastTrigger.focus === 'function') lastTrigger.focus();
    }

    function dispose() {
        close();
        if (overlay && overlay.parentNode) overlay.parentNode.removeChild(overlay);
        overlay = null;
        dialog = null;
    }

    return {
        open,
        close,
        save: submit,
        dispose,
        isOpen: () => opened,
        getState: () => state,
    };
}
