import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const testsDir = fileURLToPath(new URL('.', import.meta.url));
const rootDir = resolve(testsDir, '..');
const html = readFileSync(resolve(rootDir, 'templates', 'index.html'), 'utf8');
const packageJson = JSON.parse(readFileSync(resolve(rootDir, 'package.json'), 'utf8'));

const requiredHtml = [
    '<title>PDF 双语阅读器</title>',
    '<h2>打开 PDF 文档</h2>',
    'title="展开更多功能"',
    '>▶</button>',
    '>重置缩放</button>',
    '<label for="from-page">起</label>',
    '<label for="to-page">止</label>',
    '>范围</button>',
    '>全文</button>',
];

for (const fragment of requiredHtml) {
    assert.ok(html.includes(fragment), `missing readable UI fragment: ${fragment}`);
}

assert.equal(
    packageJson.description,
    '用于阅读英文教材和论文的本地双语 PDF 翻译阅读器。',
);

console.log('UI copy checks passed');
