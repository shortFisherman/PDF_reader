---
comet_change: organize-translation-byproducts
role: technical-design
canonical_spec: openspec
archived-with: 2026-06-19-organize-translation-byproducts
status: final
---

# Translation Output Isolation Design

## Context

PDF 翻译使用 pdf2zh_next（封装 babeldoc）。当前 `build_settings()` 未设置 `translation.output`，导致 `SettingsModel.get_output_dir()` 回退到 `Path.cwd()`——即项目根目录。翻译过程中 babeldoc 在根目录生成 `*.glossary.csv`、`*.mono.pdf` 等副产物。

## Approach

在 `services.py:build_settings()` 新增可选参数 `output_dir`；在 `routes.py:translate_page()` 的 SSE 生成器函数中创建临时输出目录并传入，翻译结束后在 `finally` 块中清理。

```
routes.py:translate_page()                          services.py
┌──────────────────────────────────────┐           ┌──────────────────┐
│ generate():                          │           │ build_settings() │
│   output_dir = mkdtemp(dir=cache/)   │──path──▶ │  output_dir=NONE?│
│                                       │           │    yes → 默认   │
│   build_settings(                    │           │    no  → 写 output│
│     pdf,                             │           └──────────────────┘
│     output_dir=str(output_dir)  ◀ NEW│
│   )                                  │
│   ...translate...                    │
│ finally:                             │
│   rmtree(output_dir)        ◀ NEW    │
└──────────────────────────────────────┘
```

## Implementation

### services.py

`build_settings()` 签名扩展为:

```python
def build_settings(
    single_page_pdf: str,
    user_prompt: str | None = None,
    output_dir: str | None = None,
) -> SettingsModel:
```

当 `output_dir` 非 `None` 时:

```python
translation_kwargs["output"] = output_dir
```

### routes.py

在 `generate()` 函数开头（与现有 `tmpdir` 并列）:

```python
output_dir = tempfile.mkdtemp(dir=str(config.CACHE_DIR))
```

调用 `build_settings()` 时传入:

```python
settings = build_settings(str(single_page_pdf), user_prompt, output_dir=str(output_dir))
```

在 `finally` 块末尾:

```python
shutil.rmtree(output_dir, ignore_errors=True)
```

## Boundary Conditions

| Scenario | Behavior |
|----------|----------|
| 翻译成功 | 副产物写入 `cache/<random>/`，清理后无残留 |
| 翻译失败（网络/API 异常） | `finally` 块执行，清理临时目录 |
| 子进程崩溃 (exitcode != 0) | 主进程 `finally` 块仍执行，`ignore_errors=True` 兜底 |
| 清理失败（权限等） | `ignore_errors=True` 静默忽略，系统重启或手动清理 `cache/` 目录即可 |
| 并行翻译多页 | 每次调用创建独立临时目录，互不干扰 |

## Testing

手动验证三个场景（无自动化测试覆盖翻译流程）:
1. 正常翻译一页 → 根目录无 `*.glossary.csv` 或 `*.mono.pdf`
2. 模拟翻译失败 → `cache/<random>/` 被删除
3. 翻译成功后右侧面板显示译文 PDF
