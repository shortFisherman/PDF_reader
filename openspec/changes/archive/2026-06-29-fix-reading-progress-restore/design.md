# Design: 修复断点恢复功能

## 根因

`static/app.js` 第197行 `scrollToPage()` 函数中调用 `alignController.realign()` 时缺少 `column` 参数。

`AlignmentController.realign(column)` 要求传入一个DOM元素作为列参数，函数内部第一行即调用 `column.querySelector(...)`。当无参数调用时，`column` 为 `undefined`，导致 `TypeError: Cannot read properties of undefined`。

由于 `scrollToPage` 在 `requestAnimationFrame` 回调中执行（见 `openPdf()` 第121行），异常被浏览器静默吞咽，无任何可见错误提示。

## 修复方案

修改 `scrollToPage()` 函数，分别对左右两列调用 `realign()`：

```javascript
function scrollToPage(index) {
    if (!alignController) return;
    alignController.setLockTarget(index, 0);
    alignController.realign(els.leftCol);
    alignController.realign(els.rightCol);
}
```

这与代码库中其他 `realign()` 调用点保持一致（`onScroll`、`onImageLoaded`、`onZoomChange` 均传入列参数）。
