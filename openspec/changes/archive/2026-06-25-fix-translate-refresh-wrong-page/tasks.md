# Tasks

- [x] 1. 修复 `static/app.js` `onTranslateClick`：入口处捕获 `targetPage` 快照，`translateCurrentPage` 调用与 `onFinish` 回调均使用 `targetPage` 替代 `currentPage`
- [x] 2. 在 `onFinish` 中增加 `dataset.loaded === 'true'` 守卫：仅对当前已加载图片执行 unload+load，对已卸载页面跳过强制加载并仅标记 `translated`
- [x] 3. 运行前端测试（`tests/run-translator-tests.mjs` 等）与后端测试（pytest）确认无回归
