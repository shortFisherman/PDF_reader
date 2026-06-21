# Comet Design Handoff

- Change: harden-pdf-state-concurrency
- Phase: design
- Mode: compact
- Context hash: b4502fa5041832a416448d3724c083758fb32760cc87df4d50e0a83676dc3ea0

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/harden-pdf-state-concurrency/proposal.md

- Source: openspec/changes/harden-pdf-state-concurrency/proposal.md
- Lines: 1-32
- SHA256: ca11d15381c101769ecb2ee269529eb06b0b59a23292b5ef88f4459665232742

```md
## Why

`AppState` 的线程安全存在三处竞态/阻塞缺陷：`render_page` 在锁外渲染（`get_doc` 取锁返回 doc 后才 render，与 `replace_page` 并发会读到被关闭/替换的 doc）；`replace_page` 在锁内做 `save`/`os.replace`/reopen 慢磁盘 IO，阻塞所有读操作且并发翻译不同页会互相破坏 `right.pdf`；`/api/translate/<page>` 无页码范围校验，越界页会触发 `pymupdf` 异常。这些是逻辑正确性缺陷，应在重构结构前先修复，并以此建立 TDD 安全网。

## What Changes

- 修复 `state.py:render_page` 竞态：渲染全过程持有锁（或对 doc 取稳定快照），确保翻译替换页面期间并发渲染不会读到半保存/已关闭的 `pymupdf.Document`
- 修复 `state.py:replace_page` 锁内慢 IO 阻塞：将 `save`/`os.replace`/reopen 的磁盘 IO 移出临界区，临界区只保护内存状态切换；采用原子替换（写临时文件 → `os.replace`）保证 `right.pdf` 不会因并发翻译不同页而损坏
- 为并发翻译不同页提供隔离：同一 `right.pdf` 的页替换串行化，避免两个翻译线程同时 save/replace 导致文件交错损坏
- 为 `/api/translate/<int:page>` 增加页码范围校验：越界页返回 400 而非触发底层异常
- 为以上每项缺陷先补特征测试（TDD），再修复使测试通过；现有 45 个测试保持全绿

## Capabilities

### New Capabilities

无。本变更是对现有行为的正确性加固，不引入新能力。

### Modified Capabilities

- `code-quality-foundations`: 强化"线程安全全局状态访问"需求——当前 `render_page` 在锁外渲染违反了该需求；需明确渲染与页替换的并发安全契约，并禁止锁内执行慢磁盘 IO
- `pdf-rendering`: 新增并发安全渲染需求——翻译替换某页期间，对其他页（或同页）的并发渲染请求 SHALL 不读到被关闭或半保存的文档
- `page-translation`: 新增页码范围校验需求——翻译越界页 SHALL 返回 400 错误而非底层异常；新增并发翻译隔离需求——同一 `right.pdf` 的页替换 SHALL 串行化
- `translation-output-isolation`: 强化 `right.pdf` 写入需求——页替换 SHALL 使用原子写（临时文件 + `os.replace`），并发翻译不同页 SHALL 不互相损坏 `right.pdf`

## Impact

- **代码**：`state.py`（`render_page`/`replace_page`/可能新增页级锁或读写锁）、`routes.py`（`translate_page` 增加页码校验）
- **API**：`/api/translate/<page>` 对越界页返回 400（此前是 500/异常）；其余 `/api/*` 契约不变
- **依赖**：无新增第三方依赖
- **测试**：新增并发渲染、并发翻译隔离、页码校验测试；现有测试保持通过
- **风险**：锁粒度调整需避免死锁；临界区缩小后需保证内存状态与磁盘文件一致性
```

## openspec/changes/harden-pdf-state-concurrency/design.md

- Source: openspec/changes/harden-pdf-state-concurrency/design.md
- Lines: 1-68
- SHA256: 7c1e4d17ca28b70e43aef978dcb815ae7242c25c5e8aba51e85bed84b38b3e9f

```md
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
```

## openspec/changes/harden-pdf-state-concurrency/tasks.md

- Source: openspec/changes/harden-pdf-state-concurrency/tasks.md
- Lines: 1-32
- SHA256: 0d9cd558e012739baabbf8fb9ac58b792182805076c01c3df8eaaa9191af09c7

```md
## 1. TDD 安全网 — 失败特征测试先行

- [ ] 1.1 在 `tests/test_state.py` 增加测试：用 `threading.Event` 屏障强制 `render_page` 与 `replace_page` 交错，断言渲染不抛异常、返回有效 PNG（当前应失败）
- [ ] 1.2 在 `tests/test_state.py` 增加测试：两个线程并发 `replace_page` 不同页，断言 `right.pdf` 保持有效且两页均替换成功（当前应失败或损坏）
- [ ] 1.3 在 `tests/test_state.py` 增加测试：`replace_page` 执行期间 mock 慢磁盘 IO，断言主锁未被阻塞（并发 `get_doc` 立即返回）
- [ ] 1.4 在 `tests/test_routes.py` 增加测试：`/api/translate/<page>` 越界页（负数、>=page_count）返回 400 而非 500（当前应失败）
- [ ] 1.5 运行 `pytest tests/ -v` 确认新测试失败、旧 45 测试仍绿

## 2. 修复渲染竞态

- [ ] 2.1 修改 `state.py:render_page`：将 `get_doc` + `render_func` 全过程纳入 `_lock` 临界区
- [ ] 2.2 确认 `tests/test_state.py` 渲染竞态测试通过
- [ ] 2.3 运行 `pytest tests/test_state.py -v` 全绿

## 3. 修复 replace_page 锁内慢 IO 与并发损坏

- [ ] 3.1 在 `AppState.__init__` 新增 `_write_lock = threading.Lock()`（页替换串行锁）
- [ ] 3.2 重构 `state.py:replace_page`：主锁内做 `delete_page`+`insert_pdf`+`save(tmp)`；主锁外、`_write_lock` 内做 `close`+`os.replace(tmp, right_pdf_path)`+`reopen`+更新 `_right_doc`
- [ ] 3.3 统一加锁顺序：始终先 `_lock` 后 `_write_lock`，确保无死锁
- [ ] 3.4 确认并发 replace 与慢 IO 测试通过
- [ ] 3.5 运行 `pytest tests/test_state.py -v` 全绿

## 4. 修复页码范围校验

- [ ] 4.1 修改 `routes.py:translate_page`：入口处校验 `0 <= page < state.page_count`，越界返回 `error_response("page out of range", 400)`
- [ ] 4.2 确认 `tests/test_routes.py` 越界页测试通过

## 5. 全量回归与 lint

- [ ] 5.1 运行 `pytest tests/ -v`，确认全部测试（旧 45 + 新增）通过
- [ ] 5.2 运行 `ruff check`，零错误
- [ ] 5.3 更新 `requirements.lock` 若有变更（预期无）
```

## openspec/changes/harden-pdf-state-concurrency/specs/code-quality-foundations/spec.md

- Source: openspec/changes/harden-pdf-state-concurrency/specs/code-quality-foundations/spec.md
- Lines: 1-25
- SHA256: 63ed541a5d21a5e7d26c367e73577e92e5d96ec97ab172a26034005ed2c16f6f

```md
## MODIFIED Requirements

### Requirement: Thread-safe global state access

The system SHALL protect all read and write access to the global application state with locking to prevent race conditions under concurrent Flask requests. Critical sections SHALL be minimized: disk IO (file save, os.replace, reopen) SHALL NOT execute while holding the state lock; a separate write lock SHALL serialize atomic file replacement so concurrent translation of different pages cannot corrupt `right.pdf`. Rendering a page SHALL hold the state lock for the entire duration of the render call so the underlying `pymupdf.Document` cannot be closed or replaced mid-render.

#### Scenario: Concurrent page requests

- **WHEN** two HTTP requests read from or write to the global state simultaneously
- **THEN** the state SHALL remain consistent with no corrupted data or KeyError exceptions

#### Scenario: Translation updates translated_pages set

- **WHEN** a translation completes and adds a page number to the translated_pages set
- **THEN** the operation SHALL be atomic and visible to concurrent readers

#### Scenario: Rendering holds lock for full duration

- **WHEN** a render request runs concurrently with a page replacement on the same document
- **THEN** the render SHALL complete against a stable document handle that is not closed or half-saved, and SHALL NOT raise due to a closed/invalid document

#### Scenario: Slow disk IO does not block all state access

- **WHEN** a page replacement performs file save, os.replace, and reopen
- **THEN** the state lock SHALL be released before os.replace and reopen, so concurrent render/open requests are not blocked by disk IO
```

## openspec/changes/harden-pdf-state-concurrency/specs/page-translation/spec.md

- Source: openspec/changes/harden-pdf-state-concurrency/specs/page-translation/spec.md
- Lines: 1-29
- SHA256: 6ae873ef97a663c947915ecf8fb49df94525371fba21f871d236f314ed555888

```md
## ADDED Requirements

### Requirement: Translation page range validation

The system SHALL validate that the requested page index is within the opened document's page range before initiating translation. Out-of-range pages SHALL return a 400 error with a clear message, rather than triggering a low-level PDF engine exception.

#### Scenario: Translate page below range

- **WHEN** a translation is requested for a negative page index
- **THEN** the system SHALL return HTTP 400 with an error response, without invoking the translation engine

#### Scenario: Translate page above range

- **WHEN** a translation is requested for a page index greater than or equal to the document's page count
- **THEN** the system SHALL return HTTP 400 with an error response, without invoking the translation engine

### Requirement: Serialized page replacement for concurrent translations

The system SHALL serialize file replacement operations on the same `right.pdf` so that concurrent translation of different pages cannot corrupt the persisted file. Atomic file replacement (temporary file + `os.replace`) SHALL be used.

#### Scenario: Concurrent translation of different pages

- **WHEN** two translation requests for different pages run concurrently and both attempt to replace their respective pages in right.pdf
- **THEN** the file replacements SHALL be serialized, and the resulting right.pdf SHALL contain both translated pages without corruption

#### Scenario: Atomic write on replace

- **WHEN** a page replacement writes the updated right.pdf
- **THEN** the system SHALL write to a temporary file in the same directory and atomically replace right.pdf via os.replace, so a crash mid-write never leaves a partial right.pdf
```

## openspec/changes/harden-pdf-state-concurrency/specs/pdf-rendering/spec.md

- Source: openspec/changes/harden-pdf-state-concurrency/specs/pdf-rendering/spec.md
- Lines: 1-15
- SHA256: 2d9ffe759b178fc05282d9616b4493e5bd83b15500c6beff1ad2e83c6751345b

```md
## ADDED Requirements

### Requirement: Concurrent-safe page rendering

The system SHALL render pages in a way that is safe under concurrent page replacement. While a page is being replaced (deleted, inserted, saved), concurrent render requests for any page of the same document SHALL NOT observe a closed or half-saved `pymupdf.Document`.

#### Scenario: Render during concurrent page replacement

- **WHEN** a render request for page A is in progress and a concurrent request triggers replacement of page B (or page A) on the same document
- **THEN** the render SHALL complete successfully and return a valid PNG, and SHALL NOT raise an exception or return corrupted bytes

#### Scenario: Document handle not closed mid-render

- **WHEN** a page replacement closes and reopens the right document while a render holds the document handle
- **THEN** the render SHALL have completed before the document is closed, because rendering holds the state lock for its full duration
```

## openspec/changes/harden-pdf-state-concurrency/specs/translation-output-isolation/spec.md

- Source: openspec/changes/harden-pdf-state-concurrency/specs/translation-output-isolation/spec.md
- Lines: 1-16
- SHA256: 73bf030e099d7cb3ad04a945df764f916529aea360aadd20e81651ea8f75b5fb

```md
## MODIFIED Requirements

### Requirement: Translation output is written to a temporary directory
The system SHALL write all translation byproduct files to a dedicated temporary directory instead of the project root directory. Page replacement into `right.pdf` SHALL use atomic write (temporary file in the same directory + `os.replace`), and concurrent page replacements on the same `right.pdf` SHALL be serialized so they cannot corrupt each other.

#### Scenario: Successful translation does not pollute root
- **WHEN** a page translation is triggered via `/api/translate/<page>`
- **THEN** no `*.glossary.csv`, `*.mono.pdf`, or other byproduct files are created in the project root directory

#### Scenario: Translated content is correctly integrated
- **WHEN** a page translation completes successfully
- **THEN** the translated PDF content is correctly inserted into the right-side document

#### Scenario: Concurrent translations do not corrupt right.pdf
- **WHEN** two page translations complete concurrently and both replace pages in right.pdf
- **THEN** right.pdf SHALL remain a valid PDF containing both translated pages, with no interleaved or truncated writes
```

