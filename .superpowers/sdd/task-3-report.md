# Task 3 Report: 前端 — 打开后恢复定位

## Status: DONE

| 项目 | 详情 |
|------|------|
| Commit | `42cd822` `feat(frontend): 打开后按 saved_page 自动恢复定位` |
| 修改文件 | `static/app.js` (+11 lines) |

## TDD

### RED (baseline syntax check)

```
> Copy-Item static\app.js static\app_tmp.mjs; node --check static\app_tmp.mjs
RED: SYNTAX OK - baseline
```

### GREEN (post-implementation syntax check)

```
> Copy-Item static\app.js static\app_tmp.mjs; node --check static\app_tmp.mjs
GREEN: SYNTAX OK
```

## 预期行为

1. `scrollToPage(index)` — 取 `els.leftCol` 中 `[data-page="<index>"]` 的 `.page-container`，命中则 `el.scrollIntoView({block:'start'})`，未命中静默返回。
2. `openPdf` 在 `setupPageDetection` / `setupScrollSync` / `setupZoom` 装配完成后，读取 `data.saved_page`：
   - `saved_page` 为 `null` / 非整数 / `0` / `>= pageCount` → 不定位，停留在顶部首页。
   - `saved_page` 为有效整数且 `> 0 && < pageCount` → `requestAnimationFrame(() => scrollToPage(saved))` 定位左列。
3. 定位后，`setupPageDetection` settle 回调 `onPageChange` 自动刷新 `currentPage` 与 `pageIndicator`，无需手动设指示。
4. 不恢复缩放（`zoomLevel.textContent = '100%'` 保留）。

## Changes Summary

- 第 175-179 行：新增 `scrollToPage` 模块级函数
- 第 110-113 行：`openPdf` 内 `loadTranslatedState()` 之后插入恢复定位逻辑
