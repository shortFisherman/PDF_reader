## 1. 行为基线与手动验证清单

- [x] 1.1 编写 `docs/manual-verification-checklist.md`：列出拆分前后需一致的行为（双栏渲染、滚动同步、独立右栏滚动、当前页检测、懒加载缓冲5页、卸载离屏、翻译进度各 stage、prompt 切换、错误显示、open 失败提示）
- [ ] 1.2 现状手动走一遍清单，记录预期行为作为对照基线

## 2. 新增后端 /api/stages 端点

- [x] 2.1 在 `routes.py`（或变更B后的 `sse_stream.py`）新增 `GET /api/stages` 返回 `STAGE_LABELS` JSON
- [x] 2.2 在 `tests/test_routes.py` 编写测试：`/api/stages` 返回正确 stage 标签映射
- [x] 2.3 运行测试通过

## 3. 抽取 scroll-sync 模块

- [x] 3.1 创建 `static/modules/scroll-sync.js`，迁移 `setupScrollSync`/`setupPageDetection`，ES Module export
- [ ] 3.2 手动验证清单：滚动同步、独立滚动、当前页指示器行为一致

## 4. 抽取 lazy-loader 模块

- [x] 4.1 创建 `static/modules/lazy-loader.js`，迁移 `setupIntersectionObserver` 与 `loadPageImage`/`unloadPageImage` 的观察逻辑
- [ ] 4.2 手动验证清单：懒加载缓冲、卸载离屏、1000页性能一致

## 5. 抽取 dom 模块

- [x] 5.1 创建 `static/modules/dom.js`，迁移 DOM 元素引用与 `createPageEl`/`calculatePlaceholderHeight`
- [ ] 5.2 手动验证清单：页面元素创建、占位符比例一致

## 6. 抽取 sse-client 模块

- [x] 6.1 创建 `static/modules/sse-client.js`，实现 `readSSEStream(response, onEvent)` 迁移 SSE 读取与 `data: {json}\n\n` 解析
- [ ] 6.2 可选：编写 `tests/test_sse_client.py` 或 JS 纯函数测试验证事件解析

## 7. 抽取 stages 模块与 translator 模块

- [x] 7.1 创建 `static/modules/stages.js`：启动时 fetch `/api/stages` 并缓存，fetch 失败回退内置最小副本
- [x] 7.2 创建 `static/modules/translator.js`：迁移 `translateCurrentPage` 编排，用 `sse-client` 与 `stages` 模块
- [ ] 7.3 手动验证清单：翻译进度各 stage 标签、段落级进度、完成/错误显示一致

## 8. 重构 app.js 入口与 index.html

- [ ] 8.1 重写 `static/app.js` 为入口：import 各模块，绑定 open/translate/prompt 事件，组合调用
- [ ] 8.2 更新 `templates/index.html`：`<script type="module" src="/static/app.js">`
- [ ] 8.3 删除 `app.js` 中的 `STAGE_LABELS` 硬编码副本（已由 stages 模块提供）
- [ ] 8.4 完整手动验证清单走一遍，所有行为与基线一致

## 9. 全量回归与 lint

- [ ] 9.1 运行 `pytest tests/ -v`，全部后端测试通过
- [ ] 9.2 运行 `ruff check`，零错误
- [ ] 9.3 grep 确认 `STAGE_LABELS` 仅在后端单一来源（`sse_stream.py` 或 `routes.py`）定义，前端无硬编码
