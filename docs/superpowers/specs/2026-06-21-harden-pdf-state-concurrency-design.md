---
comet_change: harden-pdf-state-concurrency
role: technical-design
canonical_spec: openspec
archived-with: 2026-06-21-harden-pdf-state-concurrency
status: final
---

# Design: Harden PDF State Concurrency

## Problem

`AppState`（`state.py`）的审查发现两处真实缺陷：

1. **渲染竞态**：`render_page` 调 `get_doc`（取锁返回 doc 释放锁）后锁外渲染。并发 `replace_page` 的 `close`/`reopen` 会让渲染读到已关闭 doc → 段错误/脏数据。
2. **无页码校验**：`/api/translate/<page>` 不校验范围，越界页触发 `pymupdf.insert_pdf` 底层异常（500）。

## Debug Gate Revision

初始设计还假设 `replace_page` 存在"锁内慢 IO 阻塞"与"并发翻译不同页损坏 right.pdf"问题，提出双层锁分离（`_lock` + `_write_lock`）。实现阶段的 systematic-debugging 调查发现：

1. **原代码 `replace_page` 已全程持 `_lock`**，已是并发安全的串行实现——T2 必须等 T1 完整完成，不会交错损坏。`test_concurrent_replace_different_pages` 在原代码上即 PASS。
2. **Windows 上 `os.replace` 无法替换被 pymupdf Document 句柄打开的文件**（`[WinError 5] 拒绝访问`）。Design doc 的"`_right_doc` 在 os.replace 期间保持打开"决策在 Windows 上不可行。
3. **`os.replace` 是原子 syscall（微秒级）**，实践中不会真正慢；`save(tmp)` 是主要 IO 但必须在主锁内保护 doc。"慢 IO 移出临界区"目标在 Windows 上不可实现且不必要。

结论：回退 `replace_page` 到原实现（全程持主锁），删除 `_write_lock` 与慢 IO 测试。变更范围简化为**渲染竞态修复 + 页码校验**两项。`test_concurrent_replace_different_pages` 保留作为回归保护。

## Architecture: Single Lock (Corrected)

```
AppState
└── _lock (主锁, threading.Lock)  保护 _left_doc/_right_doc 内存状态与全部 IO
```

原代码的 `replace_page` 全程持 `_lock` 已正确——主锁串行化 delete+insert+save+close+os.replace+reopen 全过程，T2 必须等 T1 完整完成，无丢失更新、无文件损坏。无需额外锁。

### render_page（渲染竞态修复）

```python
def render_page(self, side, page_num, render_func, dpi):
    with self._lock:                          # 全过程持主锁（修复）
        doc = self._left_doc if side == "left" else self._right_doc
        if doc is None:
            raise ValueError("no document opened")
        return render_func(doc, page_num, dpi)  # doc 不会被并发 close/replace
```

主锁保证渲染期间 doc 对象不会被 `replace_page` 的 `close`/`reopen` 失效。原代码的 `get_doc` 取锁返回 doc 后释放锁，render 在锁外执行——这是竞态根源。修复后 render 全过程持锁。

### replace_page（保留原实现）

原代码已正确：全程持 `_lock` 串行化 delete+insert+save+close+os.replace+reopen。无需修改。

### 页码校验

```python
@bp.route("/api/translate/<int:page>", methods=["POST"])
def translate_page(page: int):
    state = _get_state()
    if state.left_doc is None:
        return error_response("no document opened", 400)
    if page < 0 or page >= state.page_count:
        return error_response("page out of range", 400)
    # ... 原有翻译逻辑
```

## Testing Strategy

TDD + 屏障强制交错：

1. **渲染竞态测试**（`test_render_page_concurrent_replace_no_crash`）：mock `render_func` 内置 Event 屏障，强制渲染中途暂停；并发 `replace_page`；释放屏障；断言不抛异常、返回有效 PNG。TDD RED 确认原代码失败，GREEN 确认修复通过。
2. **并发 replace 回归测试**（`test_concurrent_replace_different_pages`）：两线程 + Barrier 同步，各自 replace 不同页；断言 `right.pdf` 有效且两页均替换。原代码已 PASS，保留作回归保护。
3. **越界页 400 测试**（`test_translate_page_out_of_range`）：`/api/translate/<page_count>` 与 `/api/translate/999` 返回 400。TDD RED 确认原代码返回 200（进入翻译流程），GREEN 确认校验通过。
4. **回归**：现有 45 测试保持绿。

## Spec Patches

Debug gate 调整后需更新 delta spec：
- `code-quality-foundations`: 删除"分离 write lock"需求，保留"渲染持锁全程"需求
- `page-translation`: 删除"Serialized page replacement"需求（原代码已满足，非新修复），保留"页码范围校验"需求
- `translation-output-isolation`: 回退到原需求（无并发损坏问题）
- `pdf-rendering`: 保留"并发安全渲染"需求（render_page 修复有效）

## Risks / Trade-offs

- [主锁内 `save`+`os.replace`+`reopen` 阻塞渲染] → save 10-50ms，os.replace 微秒级，reopen 几 ms；总阻塞 10-50ms，单用户场景可接受
- [渲染持锁阻塞 replace] → 渲染 10-50ms，replace 等同时间；单用户场景可接受
- [无"慢 IO 不阻塞"优化] → Windows 限制 + 无丢失更新要求使此目标不可行；实践中 os.replace 不慢，不值得追求
