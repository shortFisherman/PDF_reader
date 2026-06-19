# Comet Design Handoff

- Change: organize-translation-byproducts
- Phase: design
- Mode: compact
- Context hash: f381ae21bed52dfa4eb61b069de1514b06dfd692f71e7a9db95f823f59e6e33a

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/organize-translation-byproducts/proposal.md

- Source: openspec/changes/organize-translation-byproducts/proposal.md
- Lines: 1-25
- SHA256: 1561fd4760f852b3b478a720bac691917ba34288ba0480373c213e01d2e4d099

```md
## Why

PDF 翻译过程中，pdf2zh_next/babeldoc 在 `translation.output` 未配置时默认将输出文件写入当前工作目录（即项目根目录），导致 `*.glossary.csv`、`*.mono.pdf` 等副产物文件散落在根目录，污染项目结构。

## What Changes

- 在 `services.py` 的 `build_settings()` 中为翻译设置一个临时输出目录，使副产物不再写入根目录
- 在 `routes.py` 的 SSE stream `finally` 块中增加对该临时输出目录的清理逻辑
- 确保翻译成功后右侧视图正确展示译文 PDF，翻译失败后无残留文件

## Capabilities

### New Capabilities

- `translation-output-isolation`: 翻译副产物隔离到临时目录，翻译结束时自动清理

### Modified Capabilities

_（无现有 spec 受影响）_

## Impact

- `services.py`: `build_settings()` 新增临时输出目录参数 / 逻辑
- `routes.py`: `translate_page()` 的 `generate()` 内部函数增加临时输出目录清理
- 不改变翻译结果的质量或内容
```

## openspec/changes/organize-translation-byproducts/design.md

- Source: openspec/changes/organize-translation-byproducts/design.md
- Lines: 1-57
- SHA256: 197b7ba36fff711346fc758c8c5b976fa8c6987875345004eadd47337393beb3

```md
## Context

当前翻译流程：
```
routes.py:translate_page()
  ├── mkdtemp() → tmpdir (存放单页 PDF)
  ├── build_settings(pdf_path)     ← 未设置 output
  ├── pdf2zh_next 翻译             ← 输出写入 cwd（根目录）
  ├── translate_result.mono_pdf_path → 读回译文 PDF
  ├── state.replace_page()          ← 合入右侧文档
  └── finally: rmtree(tmpdir)       ← 只清理单页 PDF 目录
```

`SettingsModel.get_output_dir()` 在 `translation.output=None` 时回退到 `Path.cwd()`，导致副产物写入项目根目录。

## Goals / Non-Goals

**Goals:**
- 翻译副产物写入一个临时目录而非项目根目录
- 翻译结束后（成功或失败）自动清理该临时目录

**Non-Goals:**
- 不修改 pdf2zh_next / babeldoc 源码
- 不改变翻译流程的正确性
- 不永久保存副产物

## Decisions

### 1. 在 `build_settings()` 中接受 `output_dir` 参数

`services.py:build_settings()` 新增可选参数 `output_dir: str | None = None`，当传入时设置 `translation.output` 字段。

**备选方案**：在 `build_settings()` 内部自行创建临时目录
- **拒绝理由**：临时目录生命周期应由调用方（routes.py）控制，`build_settings()` 是纯配置构建函数，不应有副作用

### 2. 在 `routes.py` 中管理输出目录生命周期

在 `translate_page()` 的 `generate()` 内部：
- 创建一个专用临时目录用于翻译输出（可与现有 `tmpdir` 并列）
- 传入 `build_settings()` 作为 `output_dir`
- 在 `finally` 块中清理（与现有 `tmpdir` 清理并列）

**备选方案**：使用 `tempfile.TemporaryDirectory` 上下文管理器
- **拒绝理由**：`generate()` 是一个生成器函数，生命周期跨越多次 `yield`，不适合 `with` 语句；在 `finally` 中显式清理更可控

### 3. 使用 `tempfile.mkdtemp(dir=config.CACHE_DIR)` 创建输出目录

在 `cache/` 目录下创建随机临时子目录，与现有 `tmpdir` 保持一致的 `tempfile.mkdtemp()` 技术选型，确保跨平台兼容。选择 `cache/` 而非系统临时目录是为了便于调试时查看中间文件。

### 4. 不修改 state.py 和缓存逻辑

翻译输出目录清理不影响 `replace_page()` 的执行——该方法在清理前已从该目录读取译文 PDF 并合入右侧文档。

## Risks / Trade-offs

- **babeldoc 在子进程中写入文件** → 子进程结束后文件锁释放，主进程的 `rmtree` 可以正常删除；如偶遇权限问题，`shutil.rmtree(ignore_errors=True)` 可兜底
- **极端情况：清理失败导致磁盘积累** → `tempfile.mkdtemp()` 创建在系统临时目录下，重启后由系统清理；风险可控
```

## openspec/changes/organize-translation-byproducts/tasks.md

- Source: openspec/changes/organize-translation-byproducts/tasks.md
- Lines: 1-16
- SHA256: 72895be17f5f95adcc1406a2076f1187337a708cfa51af0491b08f1588001884

```md
## 1. 修改 services.py

- [ ] 1.1 `build_settings()` 新增 `output_dir: str | None = None` 可选参数
- [ ] 1.2 当 `output_dir` 不为 `None` 时，设置 `translation_kwargs["output"] = output_dir`

## 2. 修改 routes.py

- [ ] 2.1 在 `translate_page()` 的 `generate()` 中创建一个专用临时目录用于翻译输出
- [ ] 2.2 将该临时目录路径传入 `build_settings()` 的 `output_dir` 参数
- [ ] 2.3 在 `finally` 块中清理该临时输出目录（与现有 `tmpdir` 清理并列，使用 `ignore_errors=True`）

## 3. 验证

- [ ] 3.1 手动测试：翻译一张页面后确认根目录无副产物文件
- [ ] 3.2 手动测试：翻译失败场景下确认临时输出目录已清理
- [ ] 3.3 手动测试：翻译成功后右侧视图正确显示译文 PDF
```

## openspec/changes/organize-translation-byproducts/specs/translation-output-isolation/spec.md

- Source: openspec/changes/organize-translation-byproducts/specs/translation-output-isolation/spec.md
- Lines: 1-23
- SHA256: 95721a8621c3b773aa0e1ffc467fc353d1d5e4d6c021ecabb60065537c044d7c

```md
## ADDED Requirements

### Requirement: Translation output is written to a temporary directory
The system SHALL write all translation byproduct files to a dedicated temporary directory instead of the project root directory.

#### Scenario: Successful translation does not pollute root
- **WHEN** a page translation is triggered via `/api/translate/<page>`
- **THEN** no `*.glossary.csv`, `*.mono.pdf`, or other byproduct files are created in the project root directory

#### Scenario: Translated content is correctly integrated
- **WHEN** a page translation completes successfully
- **THEN** the translated PDF content is correctly inserted into the right-side document

### Requirement: Temporary output directory is cleaned up after translation
The system SHALL remove the temporary output directory and all its contents when the translation operation completes, regardless of success or failure.

#### Scenario: Cleanup after successful translation
- **WHEN** a page translation completes successfully
- **THEN** the temporary output directory no longer exists

#### Scenario: Cleanup after failed translation
- **WHEN** a page translation fails with an error
- **THEN** the temporary output directory no longer exists
```

