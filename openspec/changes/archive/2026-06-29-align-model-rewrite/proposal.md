## Why

用户在维护此项目时，连续两次尝试修复左右两栏的轻微不对齐问题（左边总比右边高一点，分别在"翻译完成后"和"Ctrl+滚轮缩放时"两个场景诱发），每次修完都会把左右滚动同步改坏，被迫 `git` 回档。根因调查发现：左右对齐状态目前没有任何模块"拥有"它——它是 `scroll-sync`、`zoom`、`app.js` 翻译完成回调三个地方各自的副作用，三者彼此隐式依赖、互相不知道。更糟糕的是，现有 spec 把这个脆弱结构**写成了契约**：`dual-column-reading` 规定同步必须是"bidirectional and proportional"（`scrollTop / (scrollHeight - clientHeight)`），`page-zoom` 的"对齐保持"场景又显式依赖这条比例 scroll-sync 兜底。契约本身就把对齐所有权摊给了两个模块，于是一改就崩。

本次变更把对齐状态收归单一模块所有，建立"页对齐 + 页内偏移"语义取代比例同步，让翻译完成图刷新、Ctrl+滚轮缩放、用户手动滚动三个场景下的对齐行为都从同一写入点派生。这样后续任何对图刷新路径、缩放公式或新交互的修改，都不会再隐式破坏对齐。

## What Changes

- **BREAKING（spec 层语义变更）**：将 `dual-column-reading` 的"bidirectional and proportional scroll sync"语义替换为"页对齐 + 页内偏移同步"语义——对齐目标由 `(页号, 页内偏移)` 二元组表达，由独立的对齐模块维护，scroll 事件仅更新对齐目标，不再直接以比例互推 `scrollTop`。
- **BREAKING（spec 层语义变更）**：将 `page-zoom` 的"zime 后靠比例 scroll-sync 兜底对齐"语义替换为"zime 后由对齐模块按当前对齐目标重新执行对齐"，并明确 zoom 锚点公式与页内偏移语义的关系。
- 新增前端模块 `alignment-controller`，作为唯一向两栏写入 `scrollTop` 的组件，统一处理"用户滚动 / 图载入完成 / 缩放变化"三类触发源；所有其他模块通过事件或回调委托其重对齐，不再直接写 `scrollTop`。
- `scroll-sync` 模块退化为对齐模块的输入源之一（滚动事件 → 更新 `(页号, 页内偏移)` 目标），移除其内嵌的比例互推实现；页面检测 (`setupPageDetection`) 行为保持，但调用点由对齐模块协调。
- `zoom` 模块的 `handleWheel`/`resetZoom` 在改完 `--zoom` 与当前列锚点后，不再被动等待 scroll 事件兜底，而是显式调用对齐模块重对齐另一栏；`syncing` 标志与 `setTimeout(0)` 解锁移出 scroll-sync，由对齐模块统一管理防抖。
- `app.js` 中翻译完成回调 `onFinish` 的右页刷新逻辑（`unloadPageImage` → `loadPageImage`）在 `<img onload>` 触发后，显式通知对齐模块按当前对齐目标重对齐，消除图片载入延迟导致的残余偏差。
- 全程 TDD：先为"页对齐 + 页内偏移"语义及两个失败诱因（翻译完成、缩放）写失败测试锁定预期行为，再重构实现至测试全绿；保留并扩展 `scroll-sync.js` / `zoom.js` 中既有前端自测，确保不回退既有场景。

## Capabilities

### New Capabilities
- `column-alignment`: 对齐状态所有权与"页对齐 + 页内偏移"同步语义。定义 AlignmentController 的写入排他性、对齐目标的表示与更新规则、跨触发源（scroll / image-loaded / zoom）的重对齐入口，以及对齐 settle 的防抖契约。`specs/column-alignment/spec.md` 为本 capability 唯一规格。

### Modified Capabilities
- `dual-column-reading`: Requirement "Two synchronized scrollable columns" 中"bidirectional and proportional scroll sync"条款被替换为"页对齐 + 页内偏移"语义并显式委托给 `column-alignment` capability；`scroll-sync` 模块不再 own 同步算法；保留"two scrollable columns / 浮动工具栏 / 页指示器稳定"等不受同步算法影响的行为。
- `page-zoom`: Requirement "Cursor-anchored zoom" 的子场景"Vertical alignment preserved across columns"由"靠比例 scroll-sync 兜底"改为"经对齐模块按当前对齐目标重对齐另一栏"，并明确"两栏 zoom 同步应用"不再依赖跨栏比例对齐兜底。

## Impact

- **代码影响**：
  - `static/modules/scroll-sync.js`：`setupScrollSync` 比例互推实现退化为对齐模块的事件转发 / page detection 输入源；`createSettleGate` 防抖职责搬迁至对齐模块（或保留但语义改为对齐 settle）。
  - `static/modules/zoom.js`：`handleWheel`/`resetZoom` 在改完 zoom 与当前列锚点后，调用对齐模块 `realign()`；移除"被动靠 scroll 事件兜底"假设。
  - `static/modules/app.js`：翻译完成回调 `onFinish` 在右页图 `onload` 后通知对齐模块 `realign()`；引入并装配 AlignmentController。
  - 新增模块文件：`static/modules/alignment-controller.js`（含对应前端自测）。
- **非代码影响**：
  - 前端仅改动；后端零修改（`routes.py` / `sse_stream.py` / `state.py` 等均不动）。
  - 现有后端测试与 `{ruff,pytest}` 流水不受影响；前端自测新增。
- **显式 Non-goals**（避免上次"想顺便修一下"导致的失控）：
  - 不动后端 `sse_stream.generate` / `generate_batch` 孪生重复——后续独立变更。
  - 不动 `state.py` 的 `AppState` 神对象——后续独立变更。
  - 不修改 SSE 协议、翻译流程、缓存策略、阅读进度上报。
  - 不调整页面占位符高度公式 `dom.js calculatePlaceholderHeight` 的数值，除非设计阶段证明它是翻译后对齐失真的直接原点。
- **风险**：
  - 占位符高度与真实图片渲染高度是否完全一致，是"翻译完成图刷新是否破坏对齐"的关键未知项。若设计阶段验证发现存在量化误差，对齐模块需在图 `onload` 触发点重对齐，而非依赖占位符高度恒等——已在 scenario 中纳入。
  - zoom 锚点是基于"鼠标位置"的连续公式，引入"页内偏移"离散语义后二者需统一，存在设计整合风险，design 阶段需给出几何等价证明或合理近似。