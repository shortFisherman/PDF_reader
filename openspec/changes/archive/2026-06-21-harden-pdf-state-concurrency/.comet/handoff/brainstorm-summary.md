# Brainstorm Summary

- Change: harden-pdf-state-concurrency
- Date: 2026-06-21

## Confirmed Technical Approach

双层锁分离架构：
- `_lock`（主锁，threading.Lock）：保护 `_left_doc`/`_right_doc` 内存状态
- `_write_lock`（串行锁，threading.Lock）：串行化 `os.replace` 原子操作

`render_page`：全过程持主锁（get_doc + render_func），确保 doc 不会被并发 close/replace。

`replace_page`（修正后的锁边界）：
1. 主锁内：`delete_page` + `insert_pdf` + `save(tmp)` + `close`
2. 主锁释放
3. `_write_lock` 内：`os.replace(tmp, right_pdf_path)`
4. 主锁重新获取：`reopen` + 更新 `_right_doc` + `_translated_pages.add(page)`

修正了 design.md 决策2 的丢失更新问题：`close` 移入主锁内（而非 `_write_lock`），确保 T2 必须等 T1 完整 reopen 后才能操作含 T1 改动的新 doc。

三项修复：
1. 渲染竞态 → render_page 全程持主锁
2. replace_page 锁内慢 IO + 并发损坏 → 双层锁分离，os.replace 串行化
3. 页码校验 → /api/translate/<page> 入口校验 0<=page<page_count，越界返回 400

## Key Trade-offs and Risks

- 主锁内 `save(tmp)` 仍阻塞渲染（10-50ms），但阻塞段从原"save+replace+close+reopen"缩短到"save+close"，可接受
- `os.replace` 是原子 syscall 很快，`_write_lock` 串行化它不构成瓶颈
- 死锁风险：`_write_lock` 从不在持有主锁时获取（os.replace 在主锁释放后），单一加锁顺序无锁顺序问题
- `reopen` 取主锁时 T2 已开始新 replace 不会读到中间状态——T2 需取主锁才能改 doc，T1 的 reopen 持主锁，T2 阻塞等

## Testing Strategy

TDD + 屏障强制交错：
- mock render_func/pymupdf.open 注入 threading.Event 屏障，强制渲染与 replace 交错，确定性复现竞态
- 两线程并发 replace 不同页 + 屏障，断言 right.pdf 有效且两页均替换
- mock os.replace 加延迟，断言并发 get_doc 立即返回（慢 IO 不阻塞主锁）
- 越界页 400（负数、>=page_count）
- 现有 45 测试保持绿作为回归基线

## Spec Patches

None. delta spec 的 acceptance scenarios 已足够完整，修正后的锁边界仍满足 spec 需求（"磁盘 IO 移出临界区"+"原子写+串行化"）。design.md 决策2 的内部修正不影响 delta spec 描述。
