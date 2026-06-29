# Task 1.2: Ctrl+滚轮失对齐复现红测试

## 任务描述

同样在 jsdom fixture 下复现"Ctrl+滚轮放大大约一档后两栏页内偏移不一致"诱因——构造 zoom 模拟器，断言 zoom 后两栏 `pageIndex` 顶部偏移之差 > 0。预期：在当前实现下应失败（红）。

## 详细要求

### 1. 在已有 fixture 文件中新增 zoom misalignment 测试

复用 `static/modules/__tests__/translation-misalign-fixture.js` 的 fixture 模式，或新建独立文件 `static/modules/__tests__/zoom-misalign-fixture.js`。建议新建独立文件以保持职责单一。

### 2. 构造 zoom 模拟器

- 两栏多页 (3-4页)，每页占位符高度相同（如 450px）
- 加载 `setupZoom({ columns, appEl, onZoomChange })`（从 `zoom.js`）
- 模拟 Ctrl+wheel 事件：触发 `handleWheel`（zoom.js 内部），传入 `deltaY < 0`（放大），使 `--zoom` 从 1 改为 1.1
- zoom.js 中 `handleWheel` 在算完当前列（左栏）的锚点 `scrollTop` 后，仅调 `onZoomChange` 回调（显示百分比指示器），**不调** alignment controller（因为 controller 尚未实现）
- 右栏的 scroll 位置不会被动更新

### 3. 断言

- zoom 后，左栏和右栏相同 `pageIndex` 的 `.page-container` 在视口坐标系下的 `getBoundingClientRect().top` 之差的绝对值 > 0
- 或者在 zoom 后计算左栏 `intraPageOffsetPx`（`scrollTop - pageContainer.offsetTop`）和右栏 `intraPageOffsetPx`，断言两者不一致
- 预期 RED：右栏靠被动 scroll 事件兜底（scroll 事件由左栏写 `scrollTop` 触发回流），但比例不一致导致偏移差

### 4. 测试模式

- 使用 `window.__TEST_ALIGN_REPRO_ZOOM__` 全局标记触发
- 测试块格式仿照 1.1：`assert(cond, msg)` 函数
- 完成后设 `globalThis.__ALIGN_REPRO_ZOOM_DONE__ = true`
- 若失败，日志包含 `FAILED` 或 `FAIL:` 字样

### 5. 更新测试运行器

在 `tests/run-alignment-repro-tests.mjs` 中新增对 zoom misalignment fixture 的加载和执行：
- 读取并执行 `zoom.js`（剥离 export）
- 再读取并执行 `zoom-misalign-fixture.js`
- 设 `jsdomWindow.__TEST_ALIGN_REPRO_ZOOM__ = true`

### 6. 预期结果

**RED**: zoom 后两栏不对齐。当前 `setupZoom` 仅写当前列 `scrollTop`（锚点公式），不通知另一列更新；`setupScrollSync` 的比例互推在 zoom 场景下因 scrollHeight 不变（两栏页高相同），可能刚好对齐或不对齐——需要构造 scrollHeight 不同的场景（如两栏页数不同、或页容器 diff 高度）使不对齐显现。

关键 insight：即使两栏 scrollHeight 相同，zoom 后的 scroll 事件回流触发 `setupScrollSync.sync`，但比例 vf 在 zoom 前后一致（因为 scrollTop 和 scrollHeight 是按锚点公式同步变化的），所以**被动 scroll 事件兜底可能恰好对齐**。要复现 zoom 失对齐，fixture 需要"两栏内容高度不同"（例如左栏比右栏多/少一行，或左右栏页数不同），类似翻译完成图替换导致高度差 2px 的场景。

## 关键上下文

### zoom.js 中 handleWheel 逻辑
```javascript
const oldZoom = zoom;
// ... 计算 newZoom = clamp(zoom * factor, MIN, MAX)
const cy = e.clientY - col.getBoundingClientRect().top;
const newScrollTop = (col.scrollTop + cy) * (newZoom / oldZoom) - cy;
col.scrollTop = newScrollTop;
document.documentElement.style.setProperty('--zoom', newZoom);
onZoomChange(newZoom); // 仅调百分比指示器回调
```

### 关键限制
- `onZoomChange` 仅用于更新百分比显示，不触發对齐
- `handleWheel` 不是 export 的，测试需要直接 dispatch `wheel` 事件到列元素，或暴露 wheel handler

### 复现策略
建议在 fixture 中构造：
1. 左栏 4 页、右栏 3 页（或右栏某页高度少 2px），使两栏 scrollHeight 不同
2. 两栏都滚动到某页中部
3. 对左栏 dispatch `WheelEvent`（`deltaY: -100, ctrlKey: true`，jsdom 中需正确设置）
4. 断言 zoom 后两栏同 pageIndex 的 top 偏移差 > 0

## 文件范围

**可以创建/修改**:
- `static/modules/__tests__/zoom-misalign-fixture.js`（建议新建）
- `tests/run-alignment-repro-tests.mjs`（更新以加载新 fixture）

**不可修改**:
- `zoom.js`, `scroll-sync.js`, `app.js` 等生产代码

## 测试命令

```bash
node tests/run-alignment-repro-tests.mjs
```

## TDD 约束

**必须遵循 TDD**: 红阶段——目标是验证当前实现下 zoom 后的 bug 确实存在。先确保测试可运行且输出 FAIL/RED，这是成功的标志。
