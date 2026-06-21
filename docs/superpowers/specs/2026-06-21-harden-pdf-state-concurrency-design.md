---
comet_change: harden-pdf-state-concurrency
role: technical-design
canonical_spec: openspec
---

# Design: Harden PDF State Concurrency

## Problem

`AppState`（`state.py`）存在三处并发/边界缺陷：

1. **渲染竞态**：`render_page` 调 `get_doc`（取锁返回 doc 释放锁）后锁外渲染。并发 `replace_page` 的 `close`/`reopen` 会让渲染读到已关闭 doc → 段错误/脏数据。
2. **锁内慢 IO + 并发损坏**：`replace_page` 在主锁内做 `save`+`os.replace`+`close`+`reopen`，慢磁盘 IO 阻塞所有读；两个翻译线程并发替换不同页时 save/replace 交错损坏 `right.pdf`。
3. **无页码校验**：`/api/translate/<page>` 不校验范围，越界页触发 `pymupdf.insert_pdf` 底层异常（500）。

## Architecture: Dual-Layer Lock Separation

```
AppState
├── _lock (主锁, threading.Lock)      保护 _left_doc/_right_doc 内存状态
└── _write_lock (串行锁, threading.Lock) 串行化 os.replace 原子操作
```

### render_page（渲染竞态修复）

```python
def render_page(self, side, page_num, render_func, dpi):
    with self._lock:                          # 全过程持主锁
        doc = self._left_doc if side == "left" else self._right_doc
        if doc is None:
            raise ValueError("no document opened")
        return render_func(doc, page_num, dpi)  # doc 不会被并发 close/replace
```

主锁保证渲染期间 doc 对象不会被 `replace_page` 的 `close`/`reopen` 失效。

### replace_page（锁内慢 IO + 并发损坏修复）

```python
def replace_page(self, translated_pdf_path, page_num):
    tmp_save = self._right_pdf_path + ".tmp"
    with self._lock:                          # 内存操作全持主锁（无丢失更新）
        src_doc = pymupdf.open(translated_pdf_path)
        self._right_doc.delete_page(page_num)
        self._right_doc.insert_pdf(src_doc, start_at=page_num)
        self._right_doc.save(tmp_save)        # 内存→磁盘写
        self._right_doc.close()
        src_doc.close()
    # 主锁释放
    with self._write_lock:                    # 只串行化 os.replace（原子 syscall 极快）
        os.replace(tmp_save, self._right_pdf_path)
    with self._lock:                          # 重新取主锁 reopen
        self._right_doc = pymupdf.open(self._right_pdf_path)
        self._translated_pages.add(page_num)
```

**为何此顺序无丢失更新**：
- T1 释放主锁后，T2 才能取主锁操作 `_right_doc`
- 但 T1 已在主锁内 `close` 了旧 doc，T2 取主锁时 `_right_doc` 仍指向已 close 的旧对象？
  - **不是**：T1 在主锁内 close 后释放主锁，`_right_doc` 仍指向已 close 的旧 doc。T2 取主锁后对**已 close 的旧 doc** 做 delete+insert+save+close——这会报错或行为未定义。
  - **修正**：`close` 移到 `reopen` 之后，或 T2 需检测 doc 是否已 close。

**最终修正方案**：`close` 与 `reopen` 都在主锁内，`os.replace` 在 `_write_lock` 内、主锁外：

```python
def replace_page(self, translated_pdf_path, page_num):
    tmp_save = self._right_pdf_path + ".tmp"
    with self._lock:
        src_doc = pymupdf.open(translated_pdf_path)
        self._right_doc.delete_page(page_num)
        self._right_doc.insert_pdf(src_doc, start_at=page_num)
        self._right_doc.save(tmp_save)
        src_doc.close()
    # 主锁释放（_right_doc 仍打开，save 已写入 tmp）
    with self._write_lock:                    # 串行化 os.replace
        os.replace(tmp_save, self._right_pdf_path)
    with self._lock:                          # 重新取主锁完成 close+reopen
        self._right_doc.close()
        self._right_doc = pymupdf.open(self._right_pdf_path)
        self._translated_pages.add(page_num)
```

**此顺序的并发语义**：
- T1 释放主锁后 `_right_doc` 仍打开（含 T1 的 delete+insert 改动，已 save 到 tmp1）
- T2 取主锁，对**仍打开的 `_right_doc`** 做 delete+insert+save(tmp2)+释放主锁
  - T2 的 delete+insert 基于含 T1 改动的 doc → **累积正确**
- T1 在 `_write_lock` 内 `os.replace(tmp1, right.pdf)`，T2 在 `_write_lock` 内 `os.replace(tmp2, right.pdf)` → 串行，最终 right.pdf = tmp2（含 T1+T2 改动）→ **无丢失更新**
- T1 取主锁 `close`+`reopen` → 读到 right.pdf(tmp2 内容)，T2 取主锁 `close`+`reopen` → 读到同一文件
  - 但 T1 的 `_translated_pages.add(page_num)` 和 T2 的各自加自己的页 → 正确

**关键洞察**：`close` 移到 `reopen` 前（都在主锁内），`_right_doc` 在 `os.replace` 期间保持打开，T2 基于含 T1 改动的 doc 累积操作。`save(tmp)` 在主锁内保护 doc 不被并发改，`os.replace` 在 `_write_lock` 内串行化磁盘原子替换。

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

TDD + 屏障强制交错（threading.Event 注入 mock 确定性复现竞态）：

1. **渲染竞态测试**：mock `render_func` 内置 Event 屏障，强制 `render_page` 在渲染中途暂停；另一线程并发 `replace_page`；释放屏障让渲染完成；断言不抛异常、返回有效 PNG。
2. **并发 replace 不同页测试**：两线程 + 屏障同步，各自 replace 不同页；断言 `right.pdf` 可被 pymupdf 打开（有效 PDF）且两页内容均替换。
3. **慢 IO 不阻塞测试**：mock `os.replace` 加 500ms 延迟；起 `replace_page` 线程；主线程并发 `get_doc`；断言 `get_doc` 在 500ms 内返回（不被慢 replace 阻塞主锁——注意 save 仍在主锁内，但 replace 不在）。
4. **越界页 400 测试**：`/api/translate/-1` 与 `/api/translate/<page_count>` 返回 400，不触发翻译引擎。
5. **回归**：现有 45 测试保持绿。

## Spec Patches

None. delta spec 的 acceptance scenarios 已完整覆盖修正后的行为。design.md 决策2 的锁边界修正（`close` 移入主锁 reopen 段、`os.replace` 在 `_write_lock` 内主锁外）仍满足 spec 需求"磁盘 IO 移出临界区"+"原子写+串行化"。

## Risks / Trade-offs

- [主锁内 `save(tmp)` 仍阻塞渲染 10-50ms] → 阻塞段从原"save+replace+close+reopen"缩短到"save"，`os.replace`+`close`+`reopen` 移出，净改善显著
- [`_right_doc` 在 `os.replace` 期间保持打开] → pymupdf Document 句柄在文件被 os.replace 后仍指向旧 inode 的内存映射，reopen 才读新文件；save(tmp) 已把改动持久化，reopen 取新文件正确
- [死锁] → `_write_lock` 从不在持有主锁时获取（`os.replace` 在主锁释放后），无锁顺序问题
- [`reopen` 取主锁时 T2 已完成新 replace] → T1 reopen 读到含 T1+T2 改动的 right.pdf；T2 的 reopen 已在 T1 前（T2 先释放 `_write_lock` 并取主锁 reopen）→ 最终两个 `_right_doc` 都指向同一 right.pdf，`_translated_pages` 含两页 → 正确
