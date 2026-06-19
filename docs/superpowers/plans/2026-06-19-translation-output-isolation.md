---
change: organize-translation-byproducts
design-doc: docs/superpowers/specs/2026-06-19-translation-output-isolation-design.md
base-ref: e2c40df0ebaa4addbe296c8ea42bece96d9d926b
---

# 翻译输出隔离 实施方案

> **致自动化执行者：** 必须使用的子技能：使用 superpowers:subagent-driven-development（推荐）�?superpowers:executing-plans 按任务逐步实施。各步骤使用 checkbox（`- [ ]`）语法追踪进度�?
**目标�?* �?PDF 翻译过程�?pdf2zh_next 生成的副产物文件（`*.glossary.csv`、`*.mono.pdf` 等）隔离�?`cache/` 下的临时目录，翻译结束后自动清理，避免污染项目根目录�?
**架构�?* �?`services.py:build_settings()` 新增可选参�?`output_dir`，用于向 `SettingsModel` �?`translation.output` 写入路径；在 `routes.py:translate_page()` �?SSE 生成器函数中创建临时输出目录并传入，`finally` 块负责清理�?
**技术栈�?* Python 3.11+, Flask, pdf2zh_next, pymupdf, tempfile, shutil

## 全局约束

- Python 版本 >= 3.11（`str | None` 联合类型语法�?- 不引入新的第三方依赖
- 清理操作使用 `ignore_errors=True` 兜底，确保不影响主流�?- 并行翻译多页时每次调用创建独立临时目录，互不干扰

---

### Task 1: services.py �?build_settings() 新增 output_dir 参数

**文件�?*
- 修改：`services.py:28-51`

**接口�?*
- 提供：`build_settings(single_page_pdf: str, user_prompt: str | None = None, output_dir: str | None = None) -> SettingsModel`
- �?`output_dir` 不为 `None` 时，�?`translation_kwargs` 中设�?`"output": output_dir`

- [x] **Step 1: 修改 build_settings 签名和逻辑**

�?`services.py` �?28 行的函数签名替换为：

```python
def build_settings(single_page_pdf: str, user_prompt: str | None = None, output_dir: str | None = None) -> SettingsModel:
    translation_kwargs = {
        "lang_in": config.TRANSLATION_LANG_IN,
        "lang_out": config.TRANSLATION_LANG_OUT,
        "ignore_cache": True,
    }
    if user_prompt and user_prompt.strip():
        translation_kwargs["custom_system_prompt"] = user_prompt.strip()
    if config.GLOSSARY_PATH.exists() and config.GLOSSARY_PATH.stat().st_size > 0:
        translation_kwargs["glossaries"] = str(config.GLOSSARY_PATH)
    if output_dir is not None:
        translation_kwargs["output"] = output_dir
    return SettingsModel(
        translation=Pdf2zhTranslationSettings(**translation_kwargs),
        pdf=Pdf2zhPDFSettings(
            pages="1",
            no_dual=True,
            only_include_translated_page=True,
            watermark_output_mode="no_watermark",
        ),
        translate_engine_settings=DeepSeekSettings(
            deepseek_api_key=config.DEEPSEEK_API_KEY,
            deepseek_model=config.DEEPSEEK_MODEL,
            deepseek_base_url=config.DEEPSEEK_BASE_URL,
        ),
    )
```

- [x] **Step 2: 提交**

```powershell
git add services.py
git commit -m "feat: add output_dir parameter to build_settings"
```

---

### Task 2: 测试 �?build_settings �?output_dir 参数

**文件�?*
- 修改：`tests/test_services.py:45-52`（在现有测试末尾追加�?
**接口�?*
- 使用：`build_settings(single_page_pdf: str, user_prompt: str | None = None, output_dir: str | None = None) -> SettingsModel`

- [x] **Step 1: 编写测试用例**

�?`tests/test_services.py` 末尾追加�?
```python
def test_build_settings_with_output_dir():
    settings = build_settings("dummy.pdf", output_dir="/tmp/translate_output")
    assert settings.translation.output == "/tmp/translate_output"

def test_build_settings_without_output_dir():
    settings = build_settings("dummy.pdf")
    assert getattr(settings.translation, "output", None) is None
```

- [x] **Step 2: 运行测试，确认通过**

```powershell
pytest tests/test_services.py -v
```

预期结果：`test_build_settings_with_output_dir` �?`test_build_settings_without_output_dir` 两个新测试均 PASS�?
- [x] **Step 3: 确认原有测试未被破坏**

```powershell
pytest tests/test_services.py -v
```

预期结果：所�?7 个测�?PASS�? 个已�?+ 2 个新增）�?
- [x] **Step 4: 提交**

```powershell
git add tests/test_services.py
git commit -m "test: add tests for build_settings output_dir parameter"
```

---

### Task 3: routes.py �?translate_page() 创建临时输出目录并在 finally 中清�?
**文件�?*
- 修改：`routes.py:99-215`

**接口�?*
- 使用：`build_settings(single_page_pdf: str, user_prompt: str | None = None, output_dir: str | None = None) -> SettingsModel`
- 提供：`tempfile.mkdtemp(dir=str(config.CACHE_DIR))` 创建的临时目录路�?
- [x] **Step 1: �?translate_page() 中创建输出临时目�?*

�?`routes.py` �?99 �?`tmpdir = tempfile.mkdtemp()` 之后添加一行：

```python
output_dir = tempfile.mkdtemp(dir=str(config.CACHE_DIR))
```

修改后第 99-100 行区域应为：

```python
    tmpdir = tempfile.mkdtemp()
    output_dir = tempfile.mkdtemp(dir=str(config.CACHE_DIR))
    tmpdir_path = Path(tmpdir)
```

- [x] **Step 2: �?output_dir 传入 build_settings 调用**

�?`routes.py` �?109 行：

```python
            settings = build_settings(str(single_page_pdf), user_prompt)
```

替换为：

```python
            settings = build_settings(str(single_page_pdf), user_prompt, output_dir=output_dir)
```

- [x] **Step 3: �?finally 块中清理输出临时目录**

�?`routes.py` �?215 行：

```python
            shutil.rmtree(tmpdir, ignore_errors=True)
```

替换为：

```python
            shutil.rmtree(tmpdir, ignore_errors=True)
            shutil.rmtree(output_dir, ignore_errors=True)
```

- [x] **Step 4: 提交**

```powershell
git add routes.py
git commit -m "feat: isolate translation byproducts to temp dir in cache/"
```

---

### Task 4: 手动验证

- [x] **Step 1: 正常翻译验证**

1. 启动应用：`python app.py`
2. 打开一�?PDF 文件
3. 翻译任意一�?4. 检查项目根目录，确认没�?`*.glossary.csv` �?`*.mono.pdf` 等副产物文件
5. 检�?`cache/` 目录，确认翻译过程中创建的临时子目录已被删除

- [x] **Step 2: 翻译成功后的视图验证**

1. 翻译一页后，右侧面板能正确显示译文 PDF
2. 页码正确、内容可�?
- [x] **Step 3: 翻译失败场景验证（可选）**

1. 可以通过设置无效�?API Key 来模拟翻译失�?2. 确认 `cache/` 下的临时目录已被 `finally` 块中�?`shutil.rmtree(output_dir, ignore_errors=True)` 清理
3. 检�?`cache/` 下无残留临时目录

---

## 自审清单

**1. 设计文档覆盖�?*
- design doc �?35-45 行（services.py 修改）→ Task 1
- design doc �?47-70 行（routes.py 修改）→ Task 3
- design doc �?73-88 行（边界条件 & 测试）→ Task 2（单元测试）+ Task 4（手动验证）

**2. 无占位符�?* 已检查，所有步骤均含实际代码、命令和预期输出�?
**3. 类型一致性：**
- `build_settings()` �?`output_dir: str | None = None` 签名�?Task 1 定义，Task 2 测试�?Task 3 调用中保持一致�?- Task 3 �?`output_dir` 变量名在创建、传入、清理三个位置一致�?