## Context

`static/app.js` 335 行单文件，`<script src="/static/app.js" defer>` 加载（非 module）。5 类职责混杂：DOM 引用与元素创建、SSE 流读取、滚动同步、IntersectionObserver 懒加载、翻译编排与进度 UI。`STAGE_LABELS` 在 `routes.py:32` 与 `app.js:10` 各一份，前后端重复。

约束：前端 UX 完全不变；保守边界；无构建工具（项目无 bundler，原生 JS）；浏览器兼容性保持（ES Module 需 `type="module"`，现代浏览器支持，可接受）。

## Goals / Non-Goals

**Goals:**
- `app.js` 拆为按职责分离的模块，入口仅组合
- `STAGE_LABELS` 单一来源，前后端不重复
- 前端交互行为字节等价
- 无构建工具依赖（原生 ES Module）

**Non-Goals:**
- 不引入 bundler/框架
- 不改前端交互/样式
- 不改后端 API（除可选 stage 标签端点）

## Decisions

### 决策 1：ES Module 拆分

**选择**：`<script type="module" src="/static/app.js">`，`app.js` 作为入口 `import` 各模块：
- `static/modules/dom.js`：DOM 元素引用、`createPageEl`/`loadPageImage`/`unloadPageImage`
- `static/modules/sse-client.js`：`readSSEStream(response, onEvent)` 读取 SSE 流并回调
- `static/modules/scroll-sync.js`：`setupScrollSync`/`setupPageDetection`
- `static/modules/lazy-loader.js`：`setupIntersectionObserver`
- `static/modules/translator.js`：`translateCurrentPage` 编排，含进度 UI
- `static/modules/stages.js`：stage 标签获取与缓存
- `app.js`：入口，组合模块，绑定 open/translate 事件

**备选**：
- (a) IIFE 命名空间（window.pdfReader.xxx）——无需 module，但封装弱、依赖顺序
- (b) 引入 bundler——超保守边界，增加构建依赖

**理由**：ES Module 原生支持，封装清晰，现代浏览器兼容；`type="module"` 默认 defer。

### 决策 2：Stage 标签单一来源

**选择**：后端 `sse_stream.py`（变更 B 迁移后的权威）新增 `GET /api/stages` 端点返回 `STAGE_LABELS` JSON；前端 `stages.js` 启动时 fetch 并缓存，`translator.js` 用缓存值。消除 `app.js` 的硬编码副本。

**备选**：
- (a) 构建时生成 `static/stages.json`——需构建步骤，项目无构建工具
- (b) 前端仍硬编码但加测试防止漂移——未真正单一来源

**理由**：`/api/stages` 简单、零构建依赖、运行时权威；前端启动一次 fetch 开销可忽略。

### 决策 3：行为等价验证

**选择**：前端无现有测试；采用手动验证清单（双栏渲染、滚动同步、懒加载缓冲、翻译进度、错误显示、prompt 切换）逐项确认拆分前后行为一致。可选加最小模块单测（`sse-client` 的事件解析纯函数最易测）。

**理由**：引入完整前端测试框架超保守边界；手动清单覆盖关键路径。

## Risks / Trade-offs

- [`type="module"` CORS/路径] —— 同源静态资源无 CORS 问题；模块路径用相对 `/static/modules/`
- [stage fetch 失败] → `stages.js` fetch 失败时回退到内置最小副本并警告，保证翻译流程不阻断
- [模块拆分后加载顺序] → ES Module import 自动解析依赖，无需手动排序
- [无前端测试保护] → 手动验证清单 + `sse-client` 纯函数单测
