# 历史前端诊断归档（P3-03）

本目录存放 P3-03 之前的前端 RED 阶段/诊断脚本与 fixture。它们**不参与** `npm test`
与 `npm run lint:js`（`tests/history/**` 已被 ESLint 显式忽略），也不保证能在当前
HEAD 上运行：

- `run-alignment-repro-tests.mjs` — 复现对齐 RED 阶段失败的历史 runner。
- `run-lazy-loader-tests.mjs`、`run-task-4.4-tests.mjs`、`run-task-4.5-tests.mjs` —
  依赖旧 `static/modules/lazy-loader.js` / `scroll-sync.js` 内嵌 `__TEST_*` 分支的
  历史 harness；P3-03 已移除生产模块中的内嵌自测分支，因此这些文件只作追溯。
- `fixtures/` — 旧对齐/缩放 misalign fixture，只被历史 runner 读取。

正式测试见 `../README.md`（`tests/README.md`）。不要把这些归档加入 `npm test`
脚本，也不要据此判断当前前端行为。
