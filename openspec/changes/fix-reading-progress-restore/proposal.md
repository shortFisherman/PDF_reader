# Proposal: 修复断点恢复功能失效

## 动机

用户报告断点恢复功能完全失效：关闭PDF时`reading_progress.json`正确记录了当前页数（如167），但重新打开PDF后页面位置重置为第0页。

## 目标

恢复阅读进度断点恢复功能，使用户重新打开PDF时能自动滚动到上次离开的页面。

## 范围

- 修复 `static/app.js` 中 `scrollToPage()` 函数调用 `alignController.realign()` 时缺少列参数的bug
- 该bug导致 `realign()` 内部抛出 `TypeError`，滚动操作静默失败
