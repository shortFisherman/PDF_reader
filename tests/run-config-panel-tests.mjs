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

const { createConfigPanel } = await import(
    pathToFileURL(resolve(rootDir, 'static', 'modules', 'config-panel.js'))
);

const SCHEMA = [
    {
        path: 'model.provider',
        name: '模型服务商',
        group: 'required',
        control: 'select',
        description: '选择模型服务商。',
        default: 'openai_compatible',
        suggestions: [],
        options: [
            { value: 'deepseek', label: 'DeepSeek' },
            { value: 'zhipu', label: '智谱' },
            { value: 'openai', label: 'OpenAI' },
            { value: 'openai_compatible', label: '自定义 OpenAI 兼容接口' },
        ],
        providers: null,
        required_for: [],
        secret: false,
        minimum: null,
        maximum: null,
    },
    {
        path: 'model.api_key',
        name: 'API Key',
        group: 'required',
        control: 'password',
        description: '服务商 API Key，不回显。',
        default: '',
        suggestions: [],
        options: [],
        providers: null,
        required_for: [],
        secret: true,
        minimum: null,
        maximum: null,
    },
    {
        path: 'model.model',
        name: '模型名称',
        group: 'required',
        control: 'string',
        description: '实际调用的模型名。',
        default: '',
        suggestions: ['gpt-4o-mini', 'deepseek-chat'],
        options: [],
        providers: null,
        required_for: [],
        secret: false,
        minimum: null,
        maximum: null,
    },
    {
        path: 'model.base_url',
        name: 'Base URL',
        group: 'optional',
        control: 'string',
        description: '服务接口地址。',
        default: '',
        suggestions: ['https://api.openai.com/v1'],
        options: [],
        providers: ['openai', 'openai_compatible'],
        required_for: ['openai_compatible'],
        secret: false,
        minimum: null,
        maximum: null,
    },
    {
        path: 'model.thinking_mode',
        name: '思考模式',
        group: 'optional',
        control: 'select',
        description: 'DeepSeek 思考模式。',
        default: null,
        suggestions: [],
        options: [
            { value: 'enabled', label: '启用' },
            { value: 'disabled', label: '关闭' },
        ],
        providers: ['deepseek'],
        required_for: [],
        secret: false,
        minimum: null,
        maximum: null,
    },
    {
        path: 'model.send_temperature',
        name: '发送温度',
        group: 'optional',
        control: 'bool',
        description: '是否随请求发送温度。',
        default: false,
        suggestions: [],
        options: [
            { value: 'true', label: '开启' },
            { value: 'false', label: '关闭' },
        ],
        providers: ['openai', 'openai_compatible'],
        required_for: [],
        secret: false,
        minimum: null,
        maximum: null,
    },
    {
        path: 'model.send_reasoning_effort',
        name: '发送推理强度',
        group: 'optional',
        control: 'bool',
        description: '是否随请求发送推理强度。',
        default: false,
        suggestions: [],
        options: [
            { value: 'true', label: '开启' },
            { value: 'false', label: '关闭' },
        ],
        providers: ['openai', 'openai_compatible'],
        required_for: [],
        secret: false,
        minimum: null,
        maximum: null,
    },
    {
        path: 'model.enable_json_mode',
        name: 'JSON 模式',
        group: 'optional',
        control: 'bool',
        description: '可选 JSON 输出模式。',
        default: null,
        suggestions: [],
        options: [
            { value: 'true', label: '开启' },
            { value: 'false', label: '关闭' },
        ],
        providers: null,
        required_for: [],
        secret: false,
        minimum: null,
        maximum: null,
    },
    {
        path: 'pdf_reader.dpi',
        name: '页面渲染 DPI',
        group: 'optional',
        control: 'int',
        description: 'PDF 渲染分辨率。',
        default: 200,
        suggestions: ['150', '300'],
        options: [],
        providers: null,
        required_for: [],
        secret: false,
        minimum: 1,
        maximum: null,
    },
    {
        path: 'translation.default_system_prompt',
        name: '默认系统提示词',
        group: 'optional',
        control: 'string',
        description: '可选系统提示词。',
        default: '',
        suggestions: [],
        options: [],
        providers: null,
        required_for: [],
        secret: false,
        minimum: null,
        maximum: null,
    },
    {
        path: 'translation.qps',
        name: '主翻译每秒启动请求数',
        group: 'optional',
        control: 'int',
        description: '主翻译每秒最多启动的请求数；>100 可保存但请谨慎。',
        default: 4,
        suggestions: ['1', '2', '4', '8', '16'],
        options: [],
        providers: null,
        required_for: [],
        secret: false,
        minimum: 1,
        maximum: null,
    },
    {
        path: 'translation.pool_max_workers',
        name: '主翻译最大线程数',
        group: 'optional',
        control: 'int',
        description: '主翻译最多同时工作的线程数；留空（推荐）时自动跟随 qps；>100 可保存但风险高。',
        default: null,
        suggestions: ['2', '4', '8'],
        options: [],
        providers: null,
        required_for: [],
        secret: false,
        minimum: 1,
        maximum: null,
    },
    {
        path: 'pdf2zh.split_short_lines',
        name: '拆分短行',
        group: 'advanced',
        control: 'bool',
        description: 'PDF 高级处理选项。',
        default: false,
        suggestions: [],
        options: [
            { value: 'true', label: '开启' },
            { value: 'false', label: '关闭' },
        ],
        providers: null,
        required_for: [],
        secret: false,
        minimum: null,
        maximum: null,
    },
];

const VALUES = {
    model: {
        provider: 'openai',
        api_key: { source: 'file', configured: true },
        model: 'gpt-4o-mini',
        base_url: 'https://api.openai.com/v1',
        thinking_mode: null,
        send_temperature: true,
        send_reasoning_effort: true,
        enable_json_mode: null,
    },
    pdf_reader: { dpi: 200 },
    translation: { qps: 4, pool_max_workers: null, default_system_prompt: '' },
    pdf2zh: { split_short_lines: false },
};

function configResponse(envApiKey = false, apiKeyStatus) {
    const values = JSON.parse(JSON.stringify(VALUES));
    if (apiKeyStatus) values.model.api_key = apiKeyStatus;
    return {
        ok: true,
        json: async () => ({
            schema: SCHEMA,
            values,
            revision: 'rev-123',
            env_overrides: { MODEL_API_KEY: envApiKey },
        }),
    };
}

function makeFetch(handler) {
    return async (url, options) => handler(url, options);
}

let passCount = 0;
let failCount = 0;

function check(cond, msg) {
    if (cond) {
        passCount++;
    } else {
        failCount++;
        console.error('FAIL: ' + msg);
    }
}

const tick = () => new Promise(r => setTimeout(r, 0));

// 1. 打开/关闭：overlay 显示、dialog 语义、关闭按钮、Esc、点击遮罩
{
    const panel = createConfigPanel({
        fetchImpl: makeFetch(() => configResponse()),
        documentObj: jsdomWindow.document,
        windowObj: jsdomWindow,
        api: '/api',
    });
    const trigger = jsdomWindow.document.createElement('button');
    jsdomWindow.document.body.appendChild(trigger);
    await panel.open(trigger);
    const overlay = jsdomWindow.document.querySelector('.config-overlay');
    check(overlay !== null, 'panel creates overlay');
    check(overlay && overlay.classList.contains('open'), 'overlay opens');
    const dialog = jsdomWindow.document.querySelector('.config-dialog');
    check(dialog && dialog.getAttribute('role') === 'dialog', 'dialog has role=dialog');
    check(dialog && dialog.getAttribute('aria-modal') === 'true', 'dialog has aria-modal');
    check(dialog && dialog.getAttribute('aria-labelledby') === 'config-dialog-title', 'dialog labelled');
    check(dialog && dialog.querySelector('#config-dialog-title'), 'dialog has title');

    await tick();
    const closeBtn = dialog.querySelector('[data-close="true"]');
    closeBtn.click();
    check(panel.isOpen() === false, 'close button closes panel');
    check(overlay.classList.contains('open') === false, 'overlay hidden after close');

    await panel.open(trigger);
    jsdomWindow.dispatchEvent(new jsdomWindow.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    check(panel.isOpen() === false, 'Esc closes panel');

    await panel.open(trigger);
    overlay.dispatchEvent(new jsdomWindow.MouseEvent('click', { bubbles: true }));
    check(panel.isOpen() === false, 'click on overlay closes panel');
    panel.dispose();
}

// 2. 分组与说明：必填/可选/进阶 + 字段名/路径/说明/默认常用提示
{
    const panel = createConfigPanel({
        fetchImpl: makeFetch(() => configResponse()),
        documentObj: jsdomWindow.document,
        windowObj: jsdomWindow,
    });
    await panel.open();
    const groups = [...jsdomWindow.document.querySelectorAll('.config-group')];
    check(groups.length === 3, 'three groups rendered, got ' + groups.length);
    check(groups.map(g => g.dataset.group).join(',') === 'required,optional,advanced', 'group order required/optional/advanced');
    const titles = [...jsdomWindow.document.querySelectorAll('.config-group-title')].map(el => el.textContent);
    check(titles.join(',') === '必填,可选,进阶', 'group titles are 必填/可选/进阶');

    const requiredGroup = jsdomWindow.document.querySelector('.config-group[data-group="required"]');
    check(requiredGroup.querySelectorAll('.config-field').length === 3, 'required group has 3 fields');
    check(requiredGroup.querySelector('.config-label').textContent.includes('模型服务商'), 'field shows Chinese name');
    check(requiredGroup.querySelector('.config-path').textContent === 'model.provider', 'field shows TOML path');
    check(requiredGroup.querySelector('.config-desc').textContent.includes('选择模型服务商'), 'field shows description');

    const dpiField = jsdomWindow.document.querySelector('.config-field[data-path="pdf_reader.dpi"]');
    check(dpiField.querySelector('.config-hint').textContent.includes('默认值：200'), 'hint shows default value');
    check(dpiField.querySelector('.config-hint').textContent.includes('常用值：150、300'), 'hint shows common values');
    check(dpiField.querySelector('input').type === 'number', 'number field uses number input');
    check(dpiField.querySelector('datalist') !== null, 'number field has datalist');
    const jsonMode = jsdomWindow.document.querySelector('#cfg-model-enable_json_mode');
    check(jsonMode.options[0].value === '' && jsonMode.options[0].textContent === '留空（使用默认）', 'null bool renders empty default option');
    const thinking = jsdomWindow.document.querySelector('#cfg-model-thinking_mode');
    check(thinking.options[0].value === '' && thinking.options[0].textContent === '留空（使用默认）', 'thinking_mode renders empty default option');
    const qpsField = jsdomWindow.document.querySelector('.config-field[data-path="translation.qps"]');
    const poolField = jsdomWindow.document.querySelector('.config-field[data-path="translation.pool_max_workers"]');
    check(qpsField.querySelector('input').max === '', 'qps input has no max limit');
    check(poolField.querySelector('input').max === '', 'pool_max_workers input has no max limit');
    check(poolField.querySelector('.config-desc').textContent.includes('留空（推荐）时自动跟随 qps'), 'pool description recommends blank auto-follow');
    panel.dispose();
}

// 3. provider 映射与字段显隐：最后一项 openai_compatible，Base URL 必填提示
{
    const panel = createConfigPanel({
        fetchImpl: makeFetch(() => configResponse()),
        documentObj: jsdomWindow.document,
        windowObj: jsdomWindow,
    });
    await panel.open();
    const provider = jsdomWindow.document.querySelector('#cfg-model-provider');
    const labels = [...provider.options].map(o => o.textContent);
    const values = [...provider.options].map(o => o.value);
    check(labels.join(',') === 'DeepSeek,智谱,OpenAI,自定义 OpenAI 兼容接口', 'friendly provider labels, got ' + labels.join(','));
    check(values[values.length - 1] === 'openai_compatible', 'last provider value is openai_compatible');
    check(provider.value === 'openai', 'current provider loaded into select');

    const baseUrlField = jsdomWindow.document.querySelector('.config-field[data-path="model.base_url"]');
    const thinkingField = jsdomWindow.document.querySelector('.config-field[data-path="model.thinking_mode"]');
    check(baseUrlField.classList.contains('config-field-hidden') === false, 'base_url visible for openai');
    check(thinkingField.classList.contains('config-field-hidden') === true, 'thinking_mode hidden for openai');

    provider.value = 'openai_compatible';
    provider.dispatchEvent(new jsdomWindow.Event('change', { bubbles: true }));
    check(baseUrlField.classList.contains('config-field-hidden') === false, 'base_url visible for openai_compatible');
    check(baseUrlField.classList.contains('config-field-required-now') === true, 'base_url marked required for openai_compatible');
    check(baseUrlField.querySelector('.config-hint').dataset.requiredNow === 'true', 'base_url hint marks required');

    provider.value = 'deepseek';
    provider.dispatchEvent(new jsdomWindow.Event('change', { bubbles: true }));
    check(baseUrlField.classList.contains('config-field-hidden') === true, 'base_url hidden for deepseek');
    check(thinkingField.classList.contains('config-field-hidden') === false, 'thinking_mode visible for deepseek');
    panel.dispose();
}

// 4. 加载与保存：revision/values 提交、API Key 仅顶层且非空才发送
{
    let calls = [];
    const panel = createConfigPanel({
        fetchImpl: makeFetch((url, options) => {
            calls.push({ url, options });
            if (url === '/api/config' && options && options.method === 'PUT') {
                return {
                    ok: true,
                    json: async () => ({ ok: true, restart_required: true, revision: 'rev-456' }),
                };
            }
            return configResponse();
        }),
        documentObj: jsdomWindow.document,
        windowObj: jsdomWindow,
    });
    await panel.open();
    jsdomWindow.document.querySelector('#cfg-model-model').value = 'gpt-4o';
    jsdomWindow.document.querySelector('#cfg-pdf_reader-dpi').value = '300';
    jsdomWindow.document.querySelector('#cfg-translation-qps').value = '148';
    jsdomWindow.document.querySelector('#cfg-translation-pool_max_workers').value = '148';
    await panel.save();

    const putCall = calls.find(c => c.options && c.options.method === 'PUT');
    check(putCall !== undefined, 'save issues PUT request');
    const body = JSON.parse(putCall.options.body);
    check(body.revision === 'rev-123', 'PUT carries current revision');
    check(body.values.model.model === 'gpt-4o', 'PUT carries edited model value');
    check(body.values.pdf_reader.dpi === 300, 'PUT carries numeric dpi');
    check(body.values.translation.qps === 148, 'PUT carries qps=148');
    check(body.values.translation.pool_max_workers === 148, 'PUT carries pool_max_workers=148');
    check(body.values.model.provider === 'openai', 'PUT carries provider');
    check(body.values.model.send_temperature === true, 'PUT carries bool value');
    check(body.values.model.enable_json_mode === null, 'PUT carries null for unset optional bool');
    check(body.api_key === undefined, 'PUT omits api_key when empty');

    jsdomWindow.document.querySelector('#cfg-model-api_key').value = 'sk-new-key';
    await panel.save();
    const putCall2 = calls.filter(c => c.options && c.options.method === 'PUT')[1];
    const body2 = JSON.parse(putCall2.options.body);
    check(body2.api_key === 'sk-new-key', 'PUT sends api_key at top level when entered');
    check(jsdomWindow.document.querySelector('#cfg-model-api_key').value === '', 'api key input cleared after save');
    const statusText = jsdomWindow.document.querySelector('.config-status').textContent;
    check(statusText.includes('重启') === true, 'success status mentions restart');
    panel.dispose();
}

// 5. API Key 不回显：加载后输入框为空且提示已配置
{
    const panel = createConfigPanel({
        fetchImpl: makeFetch(() => configResponse()),
        documentObj: jsdomWindow.document,
        windowObj: jsdomWindow,
    });
    await panel.open();
    const input = jsdomWindow.document.querySelector('#cfg-model-api_key');
    check(input.value === '', 'api key input never echoes configured value');
    check(input.type === 'password', 'api key input is password type');
    check(input.placeholder.includes('已配置'), 'api key placeholder says configured');
    panel.dispose();
}

// 6. 错误/成功状态：错误码展示，成功后显示重启提示
{
    let putCount = 0;
    const panel = createConfigPanel({
        fetchImpl: makeFetch((url, options) => {
            if (url === '/api/config' && options && options.method === 'PUT') {
                putCount++;
                if (putCount === 1) {
                    return {
                        ok: false,
                        json: async () => ({ code: 'invalid_config', error: '字段类型错误' }),
                    };
                }
                return { ok: true, json: async () => ({ ok: true, restart_required: true, revision: 'rev-9' }) };
            }
            return configResponse();
        }),
        documentObj: jsdomWindow.document,
        windowObj: jsdomWindow,
    });
    await panel.open();
    await panel.save();
    let errorText = jsdomWindow.document.querySelector('.config-error').textContent;
    check(errorText.includes('字段类型错误') && errorText.includes('invalid_config'), 'error shows Chinese message with stable code');

    await panel.save();
    const statusText = jsdomWindow.document.querySelector('.config-status').textContent;
    check(statusText.includes('保存成功'), 'success status after retry');
    check(statusText.includes('服务重启后生效'), 'success status mentions restart semantics');
    check(jsdomWindow.document.querySelector('.config-status').classList.contains('success'), 'success status styled');
    panel.dispose();
}

// 7. 环境变量覆盖提示 + provider 切换时重置无效开关
{
    const panel = createConfigPanel({
        fetchImpl: makeFetch(() => configResponse(true)),
        documentObj: jsdomWindow.document,
        windowObj: jsdomWindow,
    });
    await panel.open();
    const banner = jsdomWindow.document.querySelector('.config-env-banner');
    check(banner && banner.classList.contains('hidden') === false, 'env banner visible when MODEL_API_KEY set');
    check(banner.textContent.includes('环境变量 MODEL_API_KEY'), 'env banner mentions environment variable');
    const secretInput = jsdomWindow.document.querySelector('#cfg-model-api_key');
    check(secretInput.placeholder.includes('环境变量已设置'), 'api key placeholder explains env priority');

    const provider = jsdomWindow.document.querySelector('#cfg-model-provider');
    const sendTemp = jsdomWindow.document.querySelector('#cfg-model-send_temperature');
    check(sendTemp.value === 'true', 'send_temperature loaded as true for openai');
    provider.value = 'deepseek';
    provider.dispatchEvent(new jsdomWindow.Event('change', { bubbles: true }));
    check(sendTemp.value === 'false', 'send_temperature reset when provider becomes inapplicable');
    panel.dispose();
}

// 8. provider 回归：从 openai 切换到 deepseek/zhipu 后，隐藏的
//    send_temperature/send_reasoning_effort 必须随 PUT 显式提交 false，
//    清掉旧 TOML 中的 true，保存成功。
{
    let calls = [];
    const panel = createConfigPanel({
        fetchImpl: makeFetch((url, options) => {
            calls.push({ url, options });
            if (url === '/api/config' && options && options.method === 'PUT') {
                return {
                    ok: true,
                    json: async () => ({ ok: true, restart_required: true, revision: 'rev-789' }),
                };
            }
            return configResponse();
        }),
        documentObj: jsdomWindow.document,
        windowObj: jsdomWindow,
    });
    await panel.open();

    const provider = jsdomWindow.document.querySelector('#cfg-model-provider');
    const sendTemp = jsdomWindow.document.querySelector('#cfg-model-send_temperature');
    const sendReasoning = jsdomWindow.document.querySelector('#cfg-model-send_reasoning_effort');
    check(sendTemp.value === 'true' && sendReasoning.value === 'true', 'openai loads both send toggles as true');

    provider.value = 'deepseek';
    provider.dispatchEvent(new jsdomWindow.Event('change', { bubbles: true }));
    check(sendTemp.value === 'false' && sendReasoning.value === 'false', 'switching to deepseek resets both toggles to false');
    const thinking = jsdomWindow.document.querySelector('#cfg-model-thinking_mode');
    check(thinking.value === '' && thinking.options[0].textContent === '留空（使用默认）', 'thinking_mode stays blank for deepseek');
    await panel.save();

    let putCall = calls.filter(c => c.options && c.options.method === 'PUT')[0];
    let body = JSON.parse(putCall.options.body);
    check(body.values.model.provider === 'deepseek', 'deepseek save payload carries provider');
    check(body.values.model.send_temperature === false, 'deepseek save explicitly clears send_temperature');
    check(body.values.model.send_reasoning_effort === false, 'deepseek save explicitly clears send_reasoning_effort');
    check(body.values.model.thinking_mode === null, 'deepseek save keeps thinking_mode null when blank');
    let statusText = jsdomWindow.document.querySelector('.config-status').textContent;
    check(statusText.includes('保存成功'), 'deepseek save succeeds');

    provider.value = 'zhipu';
    provider.dispatchEvent(new jsdomWindow.Event('change', { bubbles: true }));
    await panel.save();

    putCall = calls.filter(c => c.options && c.options.method === 'PUT')[1];
    body = JSON.parse(putCall.options.body);
    check(body.values.model.provider === 'zhipu', 'zhipu save payload carries provider');
    check(body.values.model.send_temperature === false, 'zhipu save explicitly clears send_temperature');
    check(body.values.model.send_reasoning_effort === false, 'zhipu save explicitly clears send_reasoning_effort');
    statusText = jsdomWindow.document.querySelector('.config-status').textContent;
    check(statusText.includes('保存成功'), 'zhipu save succeeds');
    panel.dispose();
}

// 9. API Key 必填：未配置且未输入阻止保存；输入后允许；
//    空 MODEL_API_KEY 环境变量覆盖时提示先修正环境变量，不得误报可保存。
{
    let putCalls = 0;
    let panel = createConfigPanel({
        fetchImpl: makeFetch((url, options) => {
            if (url === '/api/config' && options && options.method === 'PUT') {
                putCalls++;
                return {
                    ok: true,
                    json: async () => ({ ok: true, restart_required: true, revision: 'rev-key' }),
                };
            }
            return configResponse(false, { source: 'missing', configured: false });
        }),
        documentObj: jsdomWindow.document,
        windowObj: jsdomWindow,
    });
    await panel.open();
    await panel.save();
    let errorText = jsdomWindow.document.querySelector('.config-error').textContent;
    check(errorText.includes('API Key 必填'), 'missing key blocks save with required error');
    check(putCalls === 0, 'no PUT issued when api key missing');

    jsdomWindow.document.querySelector('#cfg-model-api_key').value = 'sk-typed-key';
    await panel.save();
    check(putCalls === 1, 'PUT issued once api key typed');
    check(
        jsdomWindow.document.querySelector('.config-status').textContent.includes('保存成功'),
        'save succeeds with typed api key',
    );
    panel.dispose();

    panel = createConfigPanel({
        fetchImpl: makeFetch((url, options) => {
            if (url === '/api/config' && options && options.method === 'PUT') {
                putCalls++;
                return {
                    ok: true,
                    json: async () => ({ ok: true, restart_required: true, revision: 'rev-key2' }),
                };
            }
            return configResponse(true, { source: 'environment', configured: false });
        }),
        documentObj: jsdomWindow.document,
        windowObj: jsdomWindow,
    });
    await panel.open();
    const secretInput = jsdomWindow.document.querySelector('#cfg-model-api_key');
    check(secretInput.placeholder.includes('请先修正'), 'empty env override placeholder asks to fix env var');
    await panel.save();
    errorText = jsdomWindow.document.querySelector('.config-error').textContent;
    check(errorText.includes('环境变量 MODEL_API_KEY'), 'empty env override blocks save with env hint');
    check(putCalls === 1, 'no PUT issued while empty env override');
    panel.dispose();
}

console.log(`config-panel tests: ${passCount} passed, ${failCount} failed`);
if (failCount > 0) process.exit(1);
