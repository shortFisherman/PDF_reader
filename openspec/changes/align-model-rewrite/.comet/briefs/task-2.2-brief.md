# Task 2.2: 实现 currentTarget + setLockTarget + onScroll 派生 + realign 写入

## 任务描述

实现 `state = { currentTarget: {pageIndex, intraPageOffsetPx}, lockSide }`。`setLockTarget(pageIndex, offsetPx)` 写 `currentTarget`。`onScroll(src)`：iterate `src.querySelectorAll('.page-container')`，选 rect 覆盖视口中点的页取 `pageIndex`；`intraOffset = src.scrollTop - pageContainer.offsetTop`；若 `< 0` 则 `pageIndex -= 1, intraOffset += page(idx+1).offsetHeight`（跨页标准化）；`lockSide = src`；调 `realign(dst)`。`realign(column)` 写 `column.scrollTop = pageContainer.offsetTop + intraPageOffsetPx`，`offsetTop` 用 `pageContainer.getBoundingClientRect().top - column.getBoundingClientRect().top + column.scrollTop` 算。暴露 `getLockTarget()`。让 2.1 的 (a)(b)(c) 三测试转绿。

## 详细要求

### 1. 实现 state 管理

```javascript
const state = {
    currentTarget: { pageIndex: 0, intraPageOffsetPx: 0 },
    lockSide: null,  // 'left' | 'right'
};
```

### 2. 实现 setLockTarget

```javascript
function setLockTarget(pageIndex, offsetPx) {
    state.currentTarget.pageIndex = pageIndex;
    state.currentTarget.intraPageOffsetPx = offsetPx;
}
```

### 3. 实现 onScroll(src) — target 派生

当用户滚动某栏时：
- 遍历 `src.querySelectorAll('.page-container')`
- 对每个 `.page-container`，计算其在视口中的覆盖面积
- 视口边界：`src.scrollTop` ~ `src.scrollTop + src.clientHeight`
- 页容器边界：`pc.getBoundingClientRect().top - col.getBoundingClientRect().top + col.scrollTop` 到 `+ pc.offsetHeight`
- 选覆盖面积最大的页（>50% 覆盖优先），取 `pageIndex = parseInt(pc.dataset.page)`
- 计算 `intraOffset = src.scrollTop - pageContainerOffsetTop`
  - 其中 `pageContainerOffsetTop = pc.getBoundingClientRect().top - src.getBoundingClientRect().top + src.scrollTop`
- 若 `intraOffset < 0`：`pageIndex -= 1`，`intraOffset += nextPageElem.offsetHeight`（跨页标准化）
- 设 `state.lockSide = src` 的 side 标识
- 调 `realign(dst)` 同步另一栏

### 4. 实现 realign(column)

写 `column.scrollTop` 使该栏对齐到 state.currentTarget：

```javascript
function realign(column) {
    const pageContainer = column.querySelector(`.page-container[data-page="${state.currentTarget.pageIndex}"]`);
    if (!pageContainer) return;
    
    const pcRect = pageContainer.getBoundingClientRect();
    const colRect = column.getBoundingClientRect();
    const pageContainerOffsetTop = pcRect.top - colRect.top + column.scrollTop;
    
    column.scrollTop = pageContainerOffsetTop + state.currentTarget.intraPageOffsetPx;
}
```

### 5. getLockTarget()

```javascript
function getLockTarget() {
    const t = state.currentTarget;
    return { pageIndex: t.pageIndex, intraPageOffsetPx: t.intraPageOffsetPx };
}
```

### 6. 让测试转绿

修改 `alignment-controller.js` 内嵌自测，使 2.1 的测试 (a)(b)(c) 全部通过：
- (a) Write 排他性：`realign(dst)` 后 `dst.scrollTop` 变化、`src.scrollTop` 不变
- (b) Target 派生：`onScroll(src)` 后 `getLockTarget()` 返回正确 `{pageIndex, intraPageOffsetPx}`
- (c) Realign 写入：两栏不同 scrollHeight（差 30px），realign 后同 `pageIndex` 顶 alignment 差 < 0.5

测试 (d) 重入保护可能仍红（2.3 实现）。

### 7. installScrollListeners + dispose

```javascript
function installScrollListeners() {
    leftEl.addEventListener('scroll', () => onScroll(leftEl));
    rightEl.addEventListener('scroll', () => onScroll(rightEl));
}

function dispose() {
    // Remove listeners (keep references for cleanup)
}
```

## 预期结果

**GREEN**: `node tests/run-alignment-controller-tests.mjs` 测试 (a)(b)(c) 通过，(d) 仍红（重入保护待实现）。

## 文件范围

**修改**: `static/modules/alignment-controller.js`（实现逻辑 + 更新自测断言）

**不修改**: 其他任何文件

## 测试命令

```bash
node tests/run-alignment-controller-tests.mjs
```

## TDD 约束

严格 TDD：先确认 2.1 测试 (a)(b)(c) 红 → 实现 → 断言转绿。提供 RED→GREEN 证据。
