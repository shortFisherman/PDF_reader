# Comet Design Handoff

- Change: fix-concurrency-resource-cleanup
- Phase: design
- Mode: compact
- Context hash: b93fbc2a934351d11fd300d25007e98a03b62403e8cba03369019ba2ea46f989

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/fix-concurrency-resource-cleanup/proposal.md

- Source: openspec/changes/fix-concurrency-resource-cleanup/proposal.md
- Lines: 1-34
- SHA256: c350cd8a31a3543a8cac12e6bfd0be1f750c54fcf0f8a32e672a519f68ebf558

```md
# Proposal: fix-concurrency-resource-cleanup

## Why

代码审查发现两个真实缺陷：
1. **tempdir 泄漏**：`routes.py:91-92` 在路由层创建 `tmpdir`/`output_dir`，清理却放在 `sse_stream.generate` 末尾 `finish_translation`。当 SSE 在 `sse_stream.py:87`（error 事件 `return`）、`:91`（无翻译结果 `return`）早退，或客户端中途断开流时，两个临时目录永远不会被删除。
2. **extract 未持锁竞态**：`routes.py:93` 调用 `pdf_extraction.extract_single_page(state.left_doc, ...)` 直接读 `_left_doc`，绕过 `AppState` 锁；而 `render_page`（`state.py:90`）在锁内 `get_pixmap`。两者并发操作同一 `pymupdf.Document`，存在数据竞争。

本变更修复这两个问题，确保资源在任意退出路径都被清理、并发读文档被锁保护。

## What Changes

- 在 `sse_stream.generate` 用 `try/finally`（或 `ExitStack` 回调）包裹，保证任意早退/异常/断连路径都清理 `tmpdir` 与 `output_dir`。
- 将 `finish_translation` 中的清理职责收敛为「总在 generate 退出时执行的兜底」，避免成功路径重复清理。
- 在 `AppState` 新增 `extract_page(page, tmpdir, extract_func)` 方法，在状态锁内执行单页抽取，与 `render_page` 同模式。
- `routes.py` 改用 `state.extract_page(...)` 替代直接传 `state.left_doc` 给 `pdf_extraction`，消除裸文档读访问。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `translation-lifecycle`: 临时目录清理 SHALL 在任意退出路径（成功/错误/无结果/客户端断连）执行，而非仅在成功路径。
- `page-translation`: 单页抽取 SHALL 在状态锁内完成，与渲染共用同一锁，杜绝并发读竞态。
- `code-quality-foundations`: 新增「extract 在状态锁内执行」的线程安全要求（thread-safe global state access 已覆盖 render/replace，扩展到 extract）。

## Impact

- **代码**：`sse_stream.py`、`translation_lifecycle.py`、`state.py`、`routes.py`、`pdf_extraction.py`（签名可能调整）。
- **依赖**：无新增。
- **测试**：新增早退/断连清理测试、并发 extract+render 测试。
- **风险**：锁内执行 IO（写临时 PDF）会扩大锁持有时长，需评估是否阻塞渲染；通过让 extract 与 render 共锁来串行化，权衡是翻译启动期间渲染短暂等待（可接受，翻译端点本就非频繁）。```

## openspec/changes/fix-concurrency-resource-cleanup/design.md

- Source: openspec/changes/fix-concurrency-resource-cleanup/design.md
- Lines: 1-37
- SHA256: bb9bf4cb63d4062c067d5d7c7aa578ec38928c27ccdd4999ee2fd9d76afd2a8e

```md
# Design: fix-concurrency-resource-cleanup

## Context

`state.py` 用单 `threading.Lock` 保护所有文档操作。`render_page` 与 `replace_page` 已持锁，但 `extract_single_page` 由路由直接把 `state.left_doc` 传给 `pdf_extraction`，绕过锁。`sse_stream.generate` 在 error/无结果时 `return`，跳过 `finish_translation` 末尾的 `shutil.rmtree`，泄漏 `tmpdir`（`tempfile.mkdtemp()`）与 `output_dir`。

## Goals / Non-Goals

**Goals:**
- 任意退出路径（成功、error 事件、无翻译结果、异常、客户端断连）都清理 `tmpdir` 与 `output_dir`。
- 单页抽取在 `AppState` 锁内执行，与渲染串行化。
- 不改变成功路径的外部可观察行为。

**Non-Goals:**
- 不引入读写锁或更细粒度并发模型（保持单锁简单性）。
- 不解决单例 AppState 的多文档限制（属架构演进变更）。
- 不改 `pdf_extraction.extract_single_page` 的抽取算法本身。

## Decisions

### 决策 1：清理用 `try/finally` 而非 ExitStack
在 `sse_stream.generate` 主体包 `try/finally`，`finally` 里 `shutil.rmtree(tmpdir)` 与 `shutil.rmtree(output_dir)`（均 `ignore_errors=True`）。从 `finish_translation` 移除清理调用，使清理职责单一在 generate 兜底。
- 替代方案：路由层用 `contextlib.ExitStack` 注册清理回调 → 可行但栈需要在 async 生成生命周期内有效，generate 是 generator，跨 yield 的 ExitStack 管理复杂；`try/finally` 在 generator 中也正确触发（GeneratorExit/Close 也会进 finally），更直观。

### 决策 2：generator 的 finally 在客户端断连时执行
Flask `stream_with_context` 在客户端断开时会向 generator 抛 `GeneratorExit`，进入 `finally`。验证此行为并为此新增一个测试（用生成器提前 close 模拟）。

### 冺策 3：`AppState.extract_page` 同 `render_page` 模式
新增 `extract_page(self, page, tmpdir, extract_func)`：锁内取 `_left_doc`，校验非空后调 `extract_func(doc, page, tmpdir)`。`render_func`/`extract_func` 约定同 `render_page`——不得回调 AppState（非可重入锁）。`routes.py` 改传 `state.extract_page(page, tmpdir, pdf_extraction.extract_single_page)`。

### 决策 4：锁内写临时 PDF 的可接受性
`extract_single_page` 做一次 `insert_pdf` + `save`，IO 较轻（单页）。翻译端点非高频，且必须与渲染串行以保证文档句柄稳定，故接受短暂锁占用。

## Risks / Trade-offs

- **[风险] finally 在 generator 异常吞没时静默失败** → 缓解：清理用 `ignore_errors=True` 并 `logger.debug` 记录失败，不抛出掩盖业务错误。
- **[风险] 锁内 save 临时文件慢导致渲染延迟** → 缓解：单页抽取耗时可控；如有性能问题后续可分离只读快照，但本变更优先正确性。
- **[风险] 改 finish_signature 影响现有测试** → 缓解：`test_services.py` 等若断言 finish_translation 内清理，需同步调整；新增测试覆盖 finally 路径。```

## openspec/changes/fix-concurrency-resource-cleanup/tasks.md

- Source: openspec/changes/fix-concurrency-resource-cleanup/tasks.md
- Lines: 1-29
- SHA256: 40acb2cb7ac693fc1dcc00a10b536193b1e4390654bbbb97900eed9f4edacef9

```md
# Tasks: fix-concurrency-resource-cleanup

## 1. tempdir 清理兜底

- [ ] 1.1 在 `sse_stream.generate` 主体包裹 `try/finally`，`finally` 清理 `ctx.tmpdir` 与 `ctx.output_dir`（`shutil.rmtree ignore_errors=True`，失败 `logger.debug`）
- [ ] 1.2 从 `translation_lifecycle.finish_translation` 移除末尾 `shutil.rmtree` 两行，使清理职责收敛到 SSE 层兜底
- [ ] 1.3 验证 `finally` 在 generator 提前 `return`（error/无结果）、抛异常、`GeneratorExit`（close）三种情形都执行

## 2. extract 持锁

- [ ] 2.1 在 `state.py` `AppState` 新增 `extract_page(self, page, tmpdir, extract_func)` 方法，锁内取 `_left_doc`、非空校验、调 `extract_func(doc, page, tmpdir)`
- [ ] 2.2 在方法文档化约束：`extract_func` 不得回调 AppState（非可重入锁），与 `render_page` 同模式
- [ ] 2.3 `routes.py:93` 改用 `state.extract_page(page, tmpdir, pdf_extraction.extract_single_page)`，移除直接传 `state.left_doc`
- [ ] 2.4 评估 `extract_single_page` 签名是否需调整以接受 `(doc, page, tmpdir)`（保持现有签名兼容）

## 3. 测试

- [ ] 3.1 新增测试：generate 在 error 事件早退后 `tmpdir`/`output_dir` 被删
- [ ] 3.2 新增测试：generate 在无 translate_result 早退后被删
- [ ] 3.3 新增测试：generator 被 `close()`（GeneratorExit）后被删（模拟客户端断连）
- [ ] 3.4 新增测试：成功路径清理只发生一次且目录被删
- [ ] 3.5 新增测试：`AppState.extract_page` 在锁内执行（用 mock 断言 `_lock` 被持有/串行）
- [ ] 3.6 新增测试：extract 与 render 并发调用经锁串行，无竞态（线程化测试）
- [ ] 3.7 调整 `tests/test_sse_stream.py` / `test_services.py` 中受 finish 签名变化影响的断言
- [ ] 3.8 运行 `ruff check .` 与 `pytest -q` 全过

## 4. 验证

- [ ] 4.1 手动触发一次翻译中断（如停止浏览器请求），确认 tempdir 被清理
- [ ] 4.2 手动并发：翻译某页同时滚动渲染其他页，确认无错误```

## openspec/changes/fix-concurrency-resource-cleanup/specs/code-quality-foundations/spec.md

- Source: openspec/changes/fix-concurrency-resource-cleanup/specs/code-quality-foundations/spec.md
- Lines: 1-31
- SHA256: ccded664d2f33c2e398e4809f4e5451ce8655dcb65ee11b620cbd12459d618c1

```md
# code-quality-foundations Delta: fix-concurrency-resource-cleanup

## MODIFIED Requirements

### Requirement: Thread-safe global state access

The system SHALL protect all read and write access to the global application state with locking to prevent race conditions under concurrent Flask requests. `replace_page` SHALL hold the state lock for its entire duration (delete, insert, save, close, os.replace, reopen) so concurrent translations serialize and cannot corrupt `right.pdf`. `render_page` SHALL hold the state lock for the entire duration of the render call so the underlying `pymupdf.Document` cannot be closed or replaced mid-render. Single-page extraction (`extract_page`) SHALL hold the state lock for its full duration so the shared `pymupdf.Document` is never read concurrently with rendering or replacement.

#### Scenario: Concurrent page requests

- **WHEN** two HTTP requests read from or write to the global state simultaneously
- **THEN** the state SHALL remain consistent with no corrupted data or KeyError exceptions

#### Scenario: Translation updates translated_pages set

- **WHEN** a translation completes and adds a page number to the translated_pages set
- **THEN** the operation SHALL be atomic and visible to concurrent readers

#### Scenario: Rendering holds lock for full duration

- **WHEN** a render request runs concurrently with a page replacement on the same document
- **THEN** the render SHALL complete against a stable document handle that is not closed or half-saved, and SHALL NOT raise due to a closed/invalid document

#### Scenario: Concurrent translations serialize via state lock

- **WHEN** two translation requests for different pages run concurrently and both attempt to replace pages in right.pdf
- **THEN** the state lock SHALL serialize the full replace_page operations, and the resulting right.pdf SHALL contain both translated pages without corruption

#### Scenario: Extraction serializes with rendering via state lock

- **WHEN** a single-page extraction request runs concurrently with a render request on the same opened document
- **THEN** the extraction and render SHALL be serialized by the state lock, and neither SHALL observe a document handle that is closed or being replaced```

## openspec/changes/fix-concurrency-resource-cleanup/specs/page-translation/spec.md

- Source: openspec/changes/fix-concurrency-resource-cleanup/specs/page-translation/spec.md
- Lines: 1-21
- SHA256: cb4a6f6698e9ccedcb0f8afa12e14d93e1435021572182ae733f093f99bfc1db

```md
# page-translation Delta: fix-concurrency-resource-cleanup

## MODIFIED Requirements

### Requirement: Single-page translation output

The system SHALL configure the translation engine to output only the translated page, not the entire document. The single-page PDF extraction SHALL be performed under the AppState lock via a dedicated `extract_page` entry point, so that extraction and rendering share the same lock and cannot race on the underlying `pymupdf.Document` handle.

#### Scenario: Single page output

- **WHEN** translating page N
- **THEN** the translation engine SHALL be configured with `pages=N` and `only_include_translated_page=True`, returning a PDF containing only page N's translation

#### Scenario: Extraction holds the state lock

- **WHEN** a single-page extraction runs concurrently with a render request on the same document
- **THEN** the extraction SHALL hold the AppState lock for its full duration, serializing against rendering so the shared document handle is not used concurrently

#### Scenario: No raw document handle escapes AppState

- **WHEN** the translate route needs a single-page PDF
- **THEN** it SHALL obtain it via `AppState.extract_page` and SHALL NOT pass `state.left_doc` directly to `pdf_extraction`, so all document reads occur under the lock```

## openspec/changes/fix-concurrency-resource-cleanup/specs/translation-lifecycle/spec.md

- Source: openspec/changes/fix-concurrency-resource-cleanup/specs/translation-lifecycle/spec.md
- Lines: 1-36
- SHA256: 356d66e2bb2fd4e2590cd1968e07718718728bbb3251b3672079b84927323a8e

```md
# translation-lifecycle Delta: fix-concurrency-resource-cleanup

## MODIFIED Requirements

### Requirement: Translation lifecycle module

The system SHALL provide a `translation_lifecycle` module that encapsulates all post-translation operations: persisting the translated page into right.pdf and merging auto-extracted terminology into the cumulative glossary. Temporary directory cleanup SHALL NOT be the responsibility of the lifecycle module's success path alone; the SSE streaming layer SHALL guarantee cleanup of the temporary directories (`tmpdir` and `output_dir`) on every exit path from the translation stream — success, error event, missing translation result, raised exception, or client disconnect. The SSE streaming module SHALL delegate page-replacement and glossary-merge to the lifecycle module rather than calling state.replace_page and glossary merging directly.

#### Scenario: Translation completion triggers lifecycle

- **WHEN** a translation completes successfully (translate_result is available)
- **THEN** the translation lifecycle module SHALL replace the translated page in right.pdf via AppState.replace_page and merge auto-extracted glossary terms

#### Scenario: Lifecycle handles missing output

- **WHEN** translate_result has no mono_pdf_path and no dual_pdf_path
- **THEN** the translation lifecycle module SHALL raise an error that propagates as an SSE error event

#### Scenario: Cleanup on successful translation

- **WHEN** a translation completes successfully and the stream exits normally
- **THEN** the temporary directories created for single-page extraction and translation output SHALL be removed

#### Scenario: Cleanup on error event early return

- **WHEN** the translation stream yields an error event and the generator returns early before invoking the lifecycle module
- **THEN** the temporary directories SHALL still be removed

#### Scenario: Cleanup on missing translation result

- **WHEN** the translation stream finishes without producing a translate_result (no translation result) and the generator returns early
- **THEN** the temporary directories SHALL still be removed

#### Scenario: Cleanup on client disconnect

- **WHEN** the client disconnects mid-stream, causing the generator to be closed (GeneratorExit)
- **THEN** the temporary directories SHALL still be removed```

