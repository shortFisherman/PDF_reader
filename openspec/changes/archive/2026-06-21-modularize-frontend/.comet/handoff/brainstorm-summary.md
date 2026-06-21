# Brainstorm Summary

- Change: modularize-frontend
- Date: 2026-06-21

## Confirmed Technical Approach

将 `static/app.js`（335行单文件）拆为 ES Module 架构，`app.js` 作为薄入口组合 6 个职责模块：
- `dom.js`：DOM 元素引用与页面元素创建
- `sse-client.js`：SSE 流读取与 `data: {json}\n\n` 解析（纯函数，无 DOM）
- `scroll-sync.js`：左右栏滚动同步与当前页检测
- `lazy-loader.js`：IntersectionObserver 懒加载
- `stages.js`：`/api/stages` fetch 并缓存，失败回退
- `translator.js`：翻译编排，通过回调通信，DOM-free

共享状态由 `app.js` 以 `let` 变量持有，通过参数传递给模块，模块通过回调返回结果。

`STAGE_LABELS` 单一来源：后端 `sse_stream.py`（权威）→ `GET /api/stages` 端点（`routes.py`）→ 前端 `stages.js` 启动时 fetch。

`index.html` 改为 `<script type="module" src="/static/app.js">`。

## Key Trade-offs and Risks

- ES Module 的 `type="module"` 默认 defer，现代浏览器兼容，无需 bundler
- 模块无构建依赖，纯原生 JS
- 风险：`/api/stages` 获取失败 → 回退内置最小副本 + console.warn
- 无前端自动化测试 → 手动验证清单覆盖 9 项关键行为

## Testing Strategy

- 后端：`pytest tests/test_routes.py` 新增 `GET /api/stages` 测试
- 前端：手动验证清单（`docs/manual-verification-checklist.md`）覆盖双栏渲染、滚动同步、懒加载、翻译进度、错误显示
- 可选：`sse-client.js` 纯函数事件解析单测

## Spec Patches

None — existing delta specs in `specs/` already cover the modified capabilities adequately.
