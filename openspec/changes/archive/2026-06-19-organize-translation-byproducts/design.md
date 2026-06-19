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
