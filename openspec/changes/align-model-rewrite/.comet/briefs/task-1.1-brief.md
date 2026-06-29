# Task 1.1: 翻译后失对齐复现红测试

## 任务描述

在 `static/modules/__tests__/` 下新建对齐复现 fixture：用 jsdom 构造两栏 × 多页容器（占位符 + `<img>` 用 `naturalHeight` 让图片高度与占位符预留高度差 2px），断言"翻译完成后替换图后，两栏 `pageIndex` 顶部偏移之差 > 0"。预期：在当前实现下应失败（红）。运行自测脚本（沿用 `scroll-sync.js` 末尾 `window.__TEST_*__` 模式）记录失败输出。

## 详细要求

### 1. 创建测试 fixture 文件 `static/modules/__tests__/translation-misalign-fixture.js`

这个文件使用 jsdom 构造一个两栏多页的 HTML 布局，模拟真实 PDF 阅读器的 DOM 结构：

- 创建 `<body>`，内含左栏 `<div id="left-column">` 和右栏 `<div id="right-column">`
- 每栏包含 3~4 个 `.page-container` 元素，每个带有 `data-page` 属性（0-indexed）
- 每个 `.page-container` 内含一个 `.page-placeholder` div，使用 `--page-ratio` CSS 变量（如 `150%` 对应 1.5 宽高比）
- 给占位符一个固定的 `offsetHeight`（如 450px）
- 构造 `<img>` 元素时，让 `naturalHeight` 比占位符高度少 2px（模拟真实图片与占位符高度差异）

### 2. 模拟"翻译完成后替换图"流程

复现 `app.js` 中 `onFinish` 的流程：
1. 右栏某页已有 loaded 图片 → `unloadPageImage`（用 placeholder 替换 img）
2. `loadPageImage`（创建新 img，`img.onload` 触发时 `placeholder.replaceWith(img)`）
3. 新 `<img>` 的 `naturalHeight` 与占位符高度差 2px

### 3. 断言

在 scroll 事件触发（先滚动到目标页再触发一次 scroll sync）后，计算左栏和右栏相同 `pageIndex` 的 `.page-container` 在视口坐标系下的 `getBoundingClientRect().top`，断言 `Math.abs(leftTop - rightTop) > 0`（即当前实现下两栏不对齐 = RED）。

### 4. 测试模式

- 使用 `window.__TEST_ALIGN_REPRO_TRANSLATION__` 全局标记触发
- 测试块格式仿照 `scroll-sync.js` 末尾的 `__TEST_CREATE_SETTLE_GATE__` 风格：
  - 定义 `assert(cond, msg)` 函数（pass/fail 计数）
  - 测试完成后设 `globalThis.__ALIGN_REPRO_TRANSLATION_DONE__ = true`
  - 若失败，日志包含 `FAILED` 或 `FAIL:` 字样
- 需要导入 `setupScrollSync`（比例同步——当前实现）来激活对齐逻辑

### 5. 创建最小测试运行器 `tests/run-alignment-repro-tests.mjs`

仿照 `tests/run-zoom-tests.mjs` 的模式：
- 使用 jsdom 创建 DOM 环境
- 设置 `globalThis.window`, `globalThis.document` 等
- 读取 fixture 文件和 scroll-sync.js 源码
- 剥离 `export` 前缀
- 用 `new Function()` 执行
- 设 `jsdomWindow.__TEST_ALIGN_REPRO_TRANSLATION__ = true`
- 脚本末尾检查 `globalThis.__ALIGN_REPRO_TRANSLATION_DONE__`，有 FAIL 则 `exit(1)`

### 6. 预期结果

**RED**: 在当前 `setupScrollSync` 比例同步实现下，两栏 `pageIndex` 顶部偏移差 > 0，测试输出 `FAIL` 或 `FAILED`。输出消息应说明左栏 top 与右栏 top 在未对齐时的具体差值。

## 关键上下文

### 当前比例同步逻辑 (`scroll-sync.js` line 50-69)
```javascript
function sync(src, dst) {
    const vf = src.scrollTop / (src.scrollHeight - src.clientHeight);
    dst.scrollTop = vf * (dst.scrollHeight - dst.clientHeight);
}
```
因为左栏 scrollHeight 和右栏 scrollHeight 可能因占位符高度与真图高度差 2px 而不同，比例同步将导致两栏不对齐。

### 关键 DOM 结构
```html
<div class="page-container" data-page="N" data-side="left|right">
  <div class="page-placeholder" style="--page-ratio: 150%">Page N+1</div>
  <!-- 或 <img src="..."> -->
</div>
```

### jsdom 限制
- `scrollIntoView` 在 jsdom 中不可用，但 fixture 通过直接设 `scrollTop` 或 dispatch scroll 事件模拟
- `img.naturalHeight` 在 jsdom 中不会自动设置，需要在 fixture 中手动 Object.defineProperty 或 mock
- `getBoundingClientRect` 在 jsdom 中的默认值可能为全零，需要为关键元素 mock

## 文件范围

**可以创建/修改**:
- `static/modules/__tests__/translation-misalign-fixture.js`（新建）
- `tests/run-alignment-repro-tests.mjs`（新建）

**不可修改**:
- `scroll-sync.js`, `zoom.js`, `app.js`, `translator.js`, `dom.js`, `lazy-loader.js` 等— 本节仅是复现 bug，不改任何生产代码
- `alignment-controller.js` — 尚未创建（任务 2.1）

## 测试命令

```bash
node tests/run-alignment-repro-tests.mjs
```

## TDD 约束

**必须遵循 TDD**: 这是红阶段测试——目标是验证当前实现下的 bug 确实存在，不需要写修复代码。先确保测试可运行且输出 FAIL/RED，这是成功的标志。
