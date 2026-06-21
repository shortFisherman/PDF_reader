## Why

`static/app.js` 是 335 行单文件，揉合 DOM 操作、SSE 流客户端、滚动同步、IntersectionObserver 懒加载、翻译状态管理 5 类职责。`STAGE_LABELS` 在 `routes.py:32` 和 `app.js:10` 各写一份，前后端重复维护易漂移。前端难以独立测试与扩展。

## What Changes

- 将 `app.js` 按职责拆为多个模块（ES Module 或 IIFE 命名空间，视现有加载方式而定）：
  - `dom.js`：DOM 元素引用与页面元素创建/加载/卸载
  - `sse-client.js`：SSE 流读取与事件解析
  - `scroll-sync.js`：左右栏滚动同步与当前页检测
  - `lazy-loader.js`：IntersectionObserver 懒加载逻辑
  - `translator.js`：翻译请求编排与进度 UI
  - `app.js`：入口，组合上述模块
- `STAGE_LABELS` 单一来源：后端 `sse_stream.py`（变更 B 已迁移）为权威，前端通过一个 `/api/stages` 端点或构建时生成 `stages.json` 获取，消除重复
- 前端交互行为（双栏、滚动、翻译、懒加载、进度）完全不变
- `index.html` 的 `<script>` 引用更新为新模块结构

## Capabilities

### New Capabilities

- `frontend-modular-architecture`: 前端模块化架构——将单文件 `app.js` 拆为按职责分离的模块，stage 标签单一来源消除前后端重复

### Modified Capabilities

- `dual-column-reading`: 滚动同步逻辑迁移至 `scroll-sync` 模块，行为不变
- `lazy-loading`: IntersectionObserver 逻辑迁移至 `lazy-loader` 模块，行为不变
- `page-translation`: SSE 客户端与翻译编排迁移至 `sse-client`/`translator` 模块，行为不变；stage 标签单一来源
- `code-quality-foundations`: 前端 JS 模块化需求扩展

## Impact

- **代码**：`static/app.js`（瘦身为入口）、新增 `static/*.js` 模块、`templates/index.html`（script 引用）
- **API**：可能新增 `GET /api/stages`（若选运行时获取 stage 标签）；或仅构建时生成静态文件，无新 API
- **前端 UX**：完全不变
- **测试**：前端无现有测试；考虑加最小模块单元测试或手动验证清单
- **风险**：ES Module 兼容性（需 `type="module"` 或 bundler）；stage 标签同步策略选择
