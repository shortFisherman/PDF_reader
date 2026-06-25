## Design

### 根因分析

`static/app.js` 中 `currentPage` 是模块级可变变量，由 `onPageChange`（line 150）在用户滚动时持续更新。`onTranslateClick` 在 line 172 以 `translateCurrentPage(currentPage, ...)` 启动翻译时，`currentPage` 指向被翻译的页。但 `onFinish` 回调在 line 197 再次读取 `currentPage`：

```javascript
const rightEl = els.rightCol.querySelector(`.page-container[data-page="${currentPage}"]`);
```

翻译耗时约 30–40 秒，期间用户滚动后 `currentPage` 已指向新的可见页。`onFinish` 因此定位到错误页面容器，对其执行 unload+load（导致可见页闪烁），而被翻译的页面从未被刷新，仍显示翻译前的缓存英文图片。

日志佐证：用户翻译 page 1（0-indexed，即第 2 页），翻译完成后仅发出 `GET /api/page/right/2`（0-indexed 第 3 页 = 滚动后的可见页），未请求 `right/1`（被翻译页）。

### 修复方案

在 `onTranslateClick` 入口处将 `currentPage` 快照到局部常量 `targetPage`，翻译请求与 `onFinish` 回调均使用 `targetPage`：

```javascript
async function onTranslateClick() {
    if (isTranslating) return;
    const targetPage = currentPage;          // 快照：翻译目标页
    isTranslating = true;
    // ...
    await translateCurrentPage(targetPage, { ... });
}
```

`onFinish` 中用 `targetPage` 定位容器，并增加 loaded 状态判断以处理极端场景：

```javascript
onFinish() {
    // ... 进度 UI ...
    const rightEl = els.rightCol.querySelector(`.page-container[data-page="${targetPage}"]`);
    if (rightEl) {
        if (rightEl.dataset.loaded === 'true') {
            // 图片当前已加载（在视口附近）—— 重新加载以显示译文
            unloadPageImage(rightEl);
            loadPageImage(rightEl);
        }
        // 若图片已被 lazy-loader 卸载（用户滚远），不强制加载；
        // 用户滚回时 lazy-loader 以新时间戳请求，自动获取译文版本
        rightEl.classList.add('translated');
    }
    loadTranslatedState();
}
```

### 极端场景分析（滚动条跳跃上百页）

1. **翻译完成时目标页在视口附近（loaded='true'）**：执行 unload+load，用新时间戳请求，后端返回译文。✅
2. **翻译完成时目标页已被卸载（loaded='false'，用户滚出 >10 页）**：跳过 load，仅标记 `translated`。用户滚回时 IntersectionObserver 触发 `loadPageImage`，因 `dataset.loaded !== 'true'` 会发起新请求（带新时间戳），后端 `right_doc` 已含译文，返回译文版本。✅
3. **翻译完成时目标页处于加载中（loaded 为 undefined 或 'false' 且 img 正在加载）**：`dataset.loaded === 'true'` 判断为 false，跳过 unload，避免中断在途请求；该在途请求仍会以旧时间戳完成，但由于 `loadTranslatedState` 会标记 `translated` 类，且用户后续滚动触发重新加载时会获取译文。此竞态极罕见（仅在翻译完成瞬间恰好首次加载该页），影响有限。

方案只改动 `static/app.js` 一个文件、一个函数，不引入新模块、新接口或新依赖。
