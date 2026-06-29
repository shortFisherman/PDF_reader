# Task 2.1: 创建空 controller 与 4 个失败自测

## 任务描述

新建 `static/modules/alignment-controller.js`：导出 `createAlignmentController({leftEl, rightEl})` 返回 `{onScroll, onImageLoaded, onZoomChange, realign, setLockTarget, getLockTarget, installScrollListeners, dispose}`（全部空函数 stub）。末尾复刻 `scroll-sync.js` 既有自测模式：`if (window.__TEST_ALIGNMENT_CONTROLLER__) { ... }`，写 4 个针对 `column-alignment` 关键 scenario 的失败测试：(a) write 排他性、(b) target 派生、(c) realign 写入、(d) realigning 重入保护。跑 `node tests/run-alignment-controller-tests.mjs` 应失败。

## 详细要求

### 1. 新建 `static/modules/alignment-controller.js`

导出工厂函数：

```javascript
export function createAlignmentController({ leftEl, rightEl }) {
    // state 初始化（本节为空实现，在 2.2 实现）

    function onScroll(src) { /* stub */ }
    function onImageLoaded(side, pageIndex) { /* stub */ }
    function onZoomChange(newZoom, oldZoom) { /* stub */ }
    function realign(column) { /* stub */ }
    function setLockTarget(pageIndex, offsetPx) { /* stub */ }
    function getLockTarget() { return null; /* stub */ }
    function installScrollListeners() { /* stub */ }
    function dispose() { /* stub */ }

    return {
        onScroll,
        onImageLoaded,
        onZoomChange,
        realign,
        setLockTarget,
        getLockTarget,
        installScrollListeners,
        dispose,
    };
}
```

### 2. 内嵌自测块 (4 个 RED 测试)

使用 `window.__TEST_ALIGNMENT_CONTROLLER__` 触发。测试格式严格仿照 `scroll-sync.js` 的 `__TEST_CREATE_SETTLE_GATE__` 块：

```
assert(cond, msg)    // pass/fail 计数
done(remaining)      // 递减 pending 计数，pending==0 时输出结果
```

4 个测试 scenario：

#### (a) Write 排他性测试
- 创建 leftEl, rightEl（均为 div 元素）
- 调用 `createAlignmentController({ leftEl, rightEl })`
- 调用 `controller.realign(dst)` 后，**仅** `dst.scrollTop` 应变化
- 当前 stub 不写 `scrollTop` → 断言失败（两个栏的 scrollTop 都是 0 或不变）

#### (b) Target 派生测试
- 创建 leftEl, rightEl，在 leftEl 中构造多页 `.page-container`，mock `getBoundingClientRect`
- 调用 `controller.onScroll(leftEl)` 
- 断言 `getLockTarget()` 返回类似 `{ pageIndex: N, intraPageOffsetPx: M }` 的对象
- 当前 stub 返回 null → 断言失败

#### (c) Realign 写入测试
- 创建 leftEl, rightEl，两栏 scrollHeight 差 30px（模拟占位符 vs 真图 2px × 15页 差异）
- mock `getBoundingClientRect` 使 page N 的 `offsetTop` 可计算
- 设置 target `(N, 0)`，调用 `controller.realign(leftEl)` + `controller.realign(rightEl)`
- 断言两栏 scrollTop 写到同 page N 的顶（`Math.abs(leftTargetTop - rightTargetTop) < 0.5`）
- 当前 stub 不写 scrollTop → 断言失败

#### (d) Realigning 重入保护测试
- spy `derivation function`（即 onScroll 的派生逻辑）
- 调用 `controller.realign(col)`，模拟其可能触发的回流 scroll 事件进入 `onScroll`
- 断言派生函数**未被调用**、`getLockTarget()` 不变
- 当前 stub 不设 realigning flag → 可能通过也可能失败，取决于是否设 flag

### 3. 创建最小测试运行器 `tests/run-alignment-controller-tests.mjs`

仿照 `tests/run-alignment-repro-tests.mjs` 的模式（但更简化）：
- jsdom 新建环境
- globalThis.window, globalThis.document 等
- 读取 `alignment-controller.js`，剥离 export 前缀
- 用 `new Function()` 执行
- 设 `jsdomWindow.__TEST_ALIGNMENT_CONTROLLER__ = true`
- 检查 `globalThis.__ALIGNMENT_CONTROLLER_TESTS_DONE__`

测试完成后设 `globalThis.__ALIGNMENT_CONTROLLER_TESTS_DONE__ = true`

### 4. 预期结果

**RED**: 4 个测试全 FAIL（stub 不写 scrollTop、不派生 target、无重入保护）。运行 `node tests/run-alignment-controller-tests.mjs` → exit 1。

## 关键约定

- `assert(cond, msg)` 使用 `console.error('FAIL: ' + msg)` 输出失败信息
- 最终汇总：`if (failCount === 0) { console.log('All N tests PASSED'); } else { console.log('M passed, N FAILED'); }`
- 完成后设 `globalThis.__ALIGNMENT_CONTROLLER_TESTS_DONE__ = true`

## 文件范围

**创建**:
- `static/modules/alignment-controller.js`（新建）
- `tests/run-alignment-controller-tests.mjs`（新建）

**不修改**: 任何现有文件

## 测试命令

```bash
node tests/run-alignment-controller-tests.mjs
```

## TDD 约束

这是 RED 阶段——先写 4 个失败测试，功能只留 stub。测试通过才是成功，测试失败（RED）在本阶段是**正确的**。
