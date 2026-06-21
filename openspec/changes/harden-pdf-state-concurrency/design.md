## Context

`AppState`（`state.py`）用一把 `threading.Lock` 保护左右栏 `pymupdf.Document` 与元数据。当前实现存在三处缺陷：

1. **渲染竞态**：`render_page` 调用 `get_doc`（取锁、返回 doc、释放锁）后在锁外执行 `render_func(doc, ...)`。若此时 `replace_page` 并发执行 `delete_page`/`save`/`close`/reopen，渲染线程会读到被关闭或半保存的 doc，触发段错误或脏数据。
2. **锁内慢 IO**：`replace_page` 在锁内执行 `save` → `os.replace` → `close` → `reopen`，慢磁盘 IO 期间阻塞所有渲染/打开请求；两个翻译线程并发替换不同页时，save/replace 交错会损坏 `right.pdf`。
3. **无页码校验**：`/api/translate/<page>` 不校验页码范围，越界页让 `pymupdf.insert_pdf` 抛底层异常（500）。

约束：保守边界——`/api/*` 契约不变（仅越界页从 500 改为 400），不引入新依赖，现有 45 测试保持绿。TDD：先补特征测试再修复。

## Goals / Non-Goals

**Goals:**
- 消除渲染与页替换间的竞态，并发渲染不读到半保存/已关闭 doc
- 将磁盘 IO 移出临界区，临界区只做内存状态切换
- 原子化 `right.pdf` 写入，并发翻译不同页不互相损坏
- `/api/translate/<page>` 越界页返回 400
- 每项缺陷有可复现的并发/边界测试

**Non-Goals:**
- 不拆分 `routes.py` 巨函数（变更 B 负责）
- 不改 SSE 事件契约与前端交互
- 不引入多文档/多会话支持
- 不替换 `pymupdf` 或 `pdf2zh-next`

## Decisions

### 决策 1：渲染持锁改为临界区内完成渲染

**选择**：`render_page` 在锁内完成 `get_doc` + `render_func` 全过程。

**备选**：
- (a) 锁内对 doc 取 pymupdf 快照（`tobytes` 拷贝）再锁外渲染——增加内存拷贝，且 pymupdf Document 不可廉价快照
- (b) 读写锁（读多写少）——`pymupdf` 渲染期间 doc 被写者 close 仍是 C 层崩溃风险，读写锁不能保证 doc 指针生命周期，复杂度高收益低

**理由**：渲染单页 200 DPI PNG 约 10-50ms，持锁期间阻塞的是同 PDF 的并发渲染/翻译；但当前已是单 PDF 单用户场景，简单互斥足够。临界区缩小后（见决策 2）写者不再持锁做 IO，读者持锁渲染的阻塞时间可接受。

### 决策 2：`replace_page` 临界区只切换内存状态，磁盘 IO 移出

**选择**：在锁内对内存 `_right_doc` 做 `delete_page` + `insert_pdf`，然后**在锁内**将 doc 保存到临时文件路径，`os.replace` 与 reopen 移出锁外——但 `os.replace` 必须与下一次 replace 串行。采用**页替换串行锁**（单独的 `_write_lock`）保证同一 `right.pdf` 的 save/replace 串行。

具体：`_right_doc.save(tmp)` 在主锁内完成（pymupdf 的 save 是内存→磁盘写，需保护 doc 不被并发改）；`os.replace(tmp, right_pdf_path)` + `close` + `reopen` 在 `_write_lock` 内、主锁外完成。这样主锁保护 doc 内存结构，`_write_lock` 串行化磁盘原子替换。

**备选**：
- (a) 全程主锁——回到锁内慢 IO 问题
- (b) 写时复制整份 right.pdf——1000 页 PDF 拷贝代价高
- (c) 每页独立文件 + 合并——改变持久化模型，超出保守边界

**理由**：分离"保护 doc 内存"与"串行化磁盘替换"两个关注点；`os.replace` 是原子的，串行化后并发翻译不同页不会交错损坏文件。

### 决策 3：页码范围校验前置

**选择**：`/api/translate/<page>` 入口检查 `0 <= page < state.page_count`，越界返回 `error_response("page out of range", 400)`。

**理由**：与 `/api/page` 的 404 处理对齐；避免底层 `pymupdf` 异常泄露为 500。

### 决策 4：TDD 顺序

**选择**：先写失败测试（并发渲染不崩溃、并发翻译不损坏文件、越界页 400），再改实现使其通过。

**理由**：竞态测试用 mock 的 `render_func`/`replace_func` 注入屏障（`threading.Event`）强制交错，确定性复现而非靠睡眠时序。

## Risks / Trade-offs

- [读者持锁渲染阻塞写者] → 渲染 10-50ms 可接受；若未来多用户并发需升级读写锁
- [`_write_lock` 与主锁顺序固定避免死锁] → 统一加锁顺序：始终先主锁后 `_write_lock`，`replace_page` 遵循此序
- [并发竞态测试靠 mock 屏障，可能漏掉真实时序] → mock 屏障强制最坏交错，覆盖核心路径；辅以现有真实测试回归
- [`os.replace` 跨卷失败] → `right.pdf` 在 `cache_dir` 内，临时文件同目录写，同卷替换保证原子
