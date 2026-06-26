---
change: batch-translation
design-doc: docs/superpowers/specs/2026-06-26-batch-translation-design.md
base-ref: 3eab6b9178e4bd1a3809320558dda9ab507cf375
---

# 批量翻译（Batch Translation）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在保留单页翻译链路稳定的前提下，新增"范围翻译/全文翻译"批量入口：把范围内全部页（含已翻译页）抽取为单一多页 PDF 一次性喂入 pdf2zh-next，再用多页译文批量回填 right.pdf，并获得跨页文本连贯的译文。

**Architecture:** 新增 `POST /api/translate-batch` SSE 端点；`sse_stream.generate_batch(ctx)` 编排：锁内 `extract_pages` → 发 `batch_info` → 锁外 `run_translation`（`pages="1-K"`）→ 锁内 `replace_pages`（升序逐页 `delete_page(idx)`+`insert_pdf(from_page=j,to_page=j)`）→ `merge_glossary_only` 合并术语表 → 发 `finish`。前端 `translator.translateBatch` 解析批量 SSE，`app.onBatchTranslateClick`/`onFullTranslateClick` 负责校验、>10 页 `confirm()`、进度展示与范围内译图批量刷新。

**Tech Stack:** Python 3.12 / Flask / pymupdf (PyMuPDF) / pdf2zh-next / pytest + ruff（后端）；原生 ES Module JS + JSDOM（前端测试，`node tests/run-translator-tests.mjs`）；HTML/CSS。

## Global Constraints

- 目标 Python 版本：`py312`（见 `ruff.toml`）。Ruff 行宽 120，启用 `E,F,I,UP,ANN`。
- 后端测试：`pytest`；前端测试：`node tests/run-translator-tests.mjs`；lint：`ruff check`。
- 页码语义：用户输入 1-based；内部 0-based。`target_pages = range(from-1, to)`（连续闭区间，**不跳过已翻译页**，全量重译覆盖）。
- 串行模型：`extract_pages`/`replace_pages` 各持 `AppState._lock`（非重入锁，回调内不得回入 AppState）；翻译执行在锁外（同单页链路）。
- 确认阈值按**范围页数** `to-from+1` 判断，>10 弹 `confirm("通常十页约需 300–400 秒")`（与已翻译页数无关）。
- 进度复用引擎整体流（`progress`/`finish`/`error`），仅追加一次性 `batch_info`；不引入逐页计数事件。
- 多页回填与术语表合并解耦：`generate_batch` 显式调 `replace_pages` + `merge_glossary_only`，不复用 `finish_translation` 的单页 replace 分支。
- 不引入取消；不改引擎、配置、术语表合并单页行为；不改单页 `Translate` 按钮既有行为。
- 参考设计文档：`docs/superpowers/specs/2026-06-26-batch-translation-design.md`（§4 架构、§5 单元、§7 决策、§11 Open Items）。

---

## 文件结构

**新增/修改的文件及职责：**

| 文件 | 操作 | 职责 |
|------|------|------|
| `pdf_extraction.py` | 修改 | 新增 `extract_pages(src_doc, page_indices, tmpdir)` 多页抽取 |
| `state.py` | 修改 | 新增 `AppState.extract_pages`/`AppState.replace_pages`（批量化、持锁） |
| `translation_settings.py` | 修改 | `build_settings` 参数化 `pages`/显式 `input_pdf` |
| `translation_lifecycle.py` | 修改 | 新增 `merge_glossary_only`（仅术语表合并） |
| `sse_stream.py` | 修改 | 新增 `GenerateBatchContext`/`format_batch_info`/`generate_batch` |
| `routes.py` | 修改 | 新增 `POST /api/translate-batch`（页码校验→SSE） |
| `templates/index.html` | 修改 | 工具栏新增起/止页输入 + 范围/全文翻译按钮 |
| `static/modules/dom.js` | 修改 | `getElements()` 注册新元素引用 |
| `static/style.css` | 修改 | 新输入框/按钮样式 |
| `static/modules/translator.js` | 修改 | 新增 `translateBatch(from, to, callbacks)` |
| `static/app.js` | 修改 | 新增 `onBatchTranslateClick`/`onFullTranslateClick`、批量进度、互斥、init 接线 |
| `tests/test_pdf_extraction.py` | 修改 | `extract_pages` 多页顺序/页数测试 |
| `tests/test_state.py` | 修改 | `replace_pages` 批量回填与 `translated_pages` 测试 |
| `tests/test_routes.py` | 修改 | 批量端点校验（非法→400）+ finish 测试 |
| `tests/test_sse_stream.py` | 修改 | `generate_batch` 发 `batch_info`/转发 `progress`/`finish` 测试 |
| `tests/run-translator-tests.mjs` | 修改 | `translateBatch` 解析 `batch_info`/`progress`/`finish`/`error` 测试 |

---

## 任务分组总览

- **Group 0 — 前置验证（spike）**：1 个任务
- **Group 1 — 后端抽取与回填原语**：3 个任务（Task 1–3）
- **Group 2 — 后端批量翻译编排**：3 个任务（Task 4–6）
- **Group 3 — 前端工具栏 UI**：3 个任务（Task 7–9）
- **Group 4 — 前端批量翻译逻辑**：3 个任务（Task 10–12）
- **Group 5 — 集成验证与回归**：1 个任务（Task 13）

---

## Group 0 — 前置验证（spike）

### Task 0: 验证 pdf2zh-next 多页输出顺序假设（spike）

**Files:**
- 临时脚本：手动编写并运行后丢弃（不提交）

**目的：** 确认 pdf2zh-next 在 `pages="1-K"` + `only_include_translated_page=True` 下，`mono_pdf_path` 的页数与顺序是否严格等于子集输入顺序（输出第 j 页 ↔ 原 `target_pages[j-1]`）。结果回写本计划"实现期校验结论"一节。

- [ ] **Step 1: 准备 6 页合成 PDF，每页含可区分文本 "P0"…"P5"**

```python
import pymupdf
doc = pymupdf.open()
for i in range(6):
    p = doc.new_page(width=612, height=792)
    p.insert_text((72, 72), f"P{i}", fontsize=48)
doc.save("spike_src.pdf"); doc.close()
```

- [ ] **Step 2: 用 `extract_pages` 抽取子集 [1,2,3]（即第 2–4 页），喂入引擎 `pages="1-3"`**

用 `build_settings(input_pdf="spike_subset.pdf", pages="1-3")` 调 `do_translate_async_stream`（参照 `translation_orchestrator.run_translation`）。

- [ ] **Step 3: 断言输出 PDF 页数 == 3 且页面顺序对应 P1→P2→P3**

```python
out = pymupdf.open(str(translate_result.mono_pdf_path))
assert out.page_count == 3
# 按可区分内容/页码映射验证（译文文本可变，用页面尺寸或渲染像素差异辅助判断顺序）
```

- [ ] **Step 4: 验证 `insert_pdf(from_page=j, to_page=j)` 单页插入在本机 pymupdf 版本受支持**

```python
import pymupdf
dst = pymupdf.open(); src = pymupdf.open("spike_out.pdf")
for j in range(3):
    dst.insert_pdf(src, start_at=j, from_page=j, to_page=j)
dst.save("spike_filled.pdf")
```

- [ ] **Step 5: 将结论写入本计划"实现期校验结论"节并提交**

仅在 spike 失败/退化时需调整 Task 2/5 算法；通过则直接进入 Group 1。

---

## Group 1 — 后端抽取与回填原语

### Task 1: `pdf_extraction.extract_pages` 多页抽取

**Files:**
- 修改: `pdf_extraction.py`（在 `extract_single_page` 之后新增）
- 测试: `tests/test_pdf_extraction.py`

**Interfaces:**
- 消费: `pymupdf.Document`（源文档）、`Path`（tmpdir）
- 产出: `extract_pages(src_doc: pymupdf.Document, page_indices: list[int], tmpdir: Path) -> Path`；返回 `tmpdir / "pages.pdf"`，含按 `page_indices` 顺序排列的 K 页。

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_pdf_extraction.py`）

```python
def test_extract_pages_produces_multi_page_pdf_in_order():
    src_doc = pymupdf.open()
    for i in range(4):
        p = src_doc.new_page(width=612, height=792)
        p.insert_text((72, 72), f"Page{i}", fontsize=24)

    tmpdir = Path(tempfile.mkdtemp())
    result_path = extract_pages(src_doc, [0, 1, 2], tmpdir)

    assert result_path.exists()
    assert result_path.name == "pages.pdf"
    out_doc = pymupdf.open(str(result_path))
    assert out_doc.page_count == 3
    assert "Page0" in out_doc[0].get_text()
    assert "Page1" in out_doc[1].get_text()
    assert "Page2" in out_doc[2].get_text()
    out_doc.close()
    src_doc.close()


def test_extract_pages_non_contiguous_indices():
    src_doc = pymupdf.open()
    for i in range(5):
        p = src_doc.new_page(width=612, height=792)
        p.insert_text((72, 72), f"P{i}", fontsize=24)

    tmpdir = Path(tempfile.mkdtemp())
    result_path = extract_pages(src_doc, [0, 2, 4], tmpdir)

    out_doc = pymupdf.open(str(result_path))
    assert out_doc.page_count == 3
    assert "P0" in out_doc[0].get_text()
    assert "P2" in out_doc[1].get_text()
    assert "P4" in out_doc[2].get_text()
    out_doc.close()
    src_doc.close()
```

文件头新增 `from pdf_extraction import extract_pages`（与既有 `extract_single_page` 并列）。

- [ ] **Step 2: 运行测试确认失败**

运行：`pytest tests/test_pdf_extraction.py::test_extract_pages_produces_multi_page_pdf_in_order -v`
预期：FAIL — `ImportError: cannot import name 'extract_pages'`

- [ ] **Step 3: 实现 `extract_pages`**（追加到 `pdf_extraction.py`）

```python
def extract_pages(src_doc: pymupdf.Document, page_indices: list[int], tmpdir: Path) -> Path:
    multi_page_pdf = tmpdir / "pages.pdf"
    out_doc = pymupdf.open()
    for idx in page_indices:
        out_doc.insert_pdf(src_doc, from_page=idx, to_page=idx)
    out_doc.save(str(multi_page_pdf))
    out_doc.close()
    return multi_page_pdf
```

> 说明：设计文档 §5.1 采用"连续区间一次 `insert_pdf` 整段"的写法；这里采用**逐页 `insert_pdf(from_page=idx,to_page=idx)`** 以同时支持连续与非连续索引（spike Task 0 已验证单页 `insert_pdf` 受支持，且与 `extract_single_page` 风格一致）。若未来确知永远是连续区间且需省调用，可优化为单次 `insert_pdf`。

- [ ] **Step 4: 运行测试确认通过**

运行：`pytest tests/test_pdf_extraction.py -v`
预期：PASS（含既有 `extract_single_page` 测试）

- [ ] **Step 5: lint + 提交**

```bash
ruff check pdf_extraction.py tests/test_pdf_extraction.py
git add pdf_extraction.py tests/test_pdf_extraction.py
git commit -m "feat: add pdf_extraction.extract_pages for multi-page subset"
```

---

### Task 2: `AppState.replace_pages` 与 `AppState.extract_pages` 锁内批量原语

**Files:**
- 修改: `state.py`（在 `AppState` 内新增两个方法）
- 测试: `tests/test_state.py`

**Interfaces:**
- 消费: Task 1 的 `pdf_extraction.extract_pages`
- 产出:
  - `AppState.extract_pages(page_indices: list[int], tmpdir: Path, extract_func) -> Path`（仿 `AppState.extract_page`，持锁）
  - `AppState.replace_pages(translated_pdf_path: str, page_indices: list[int]) -> None`（持锁；升序逐页回填；`translated_pages.update(page_indices)`）

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_state.py`）

```python
def test_replace_pages_batch_backfill_and_tracking(app_state, sample_pdf, tmp_path):
    from file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    page_count = app_state.page_count
    assert page_count == 2

    # 合成 2 页译文 PDF，每页含可区分内容
    translated_pdf = tmp_path / "translated.pdf"
    doc = pymupdf.open()
    for i in range(page_count):
        p = doc.new_page(width=612, height=792)
        p.insert_text((50, 100), f"TRANSLATED_{i}", fontsize=24)
    doc.save(str(translated_pdf))
    doc.close()

    app_state.replace_pages(str(translated_pdf), list(range(page_count)))

    out = pymupdf.open(app_state._right_pdf_path)
    assert out.page_count == page_count
    assert "TRANSLATED_0" in out[0].get_text()
    assert "TRANSLATED_1" in out[1].get_text()
    out.close()

    assert set(app_state.translated_pages) == {0, 1}


def test_replace_pages_ascending_preserves_other_indices(app_state, sample_pdf, tmp_path):
    from file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)

    # 只替换第 1 页（0-based idx=1）
    translated_pdf = tmp_path / "t1.pdf"
    doc = pymupdf.open()
    p = doc.new_page(width=612, height=792)
    p.insert_text((50, 100), "ONLY_PAGE1", fontsize=24)
    doc.save(str(translated_pdf)); doc.close()

    app_state.replace_pages(str(translated_pdf), [1])
    out = pymupdf.open(app_state._right_pdf_path)
    assert out.page_count == 2
    assert "ONLY_PAGE1" in out[1].get_text()
    assert 1 in app_state.translated_pages
    assert 0 not in app_state.translated_pages
    out.close()


def test_replace_pages_holds_lock(app_state, sample_pdf, tmp_path):
    import threading
    from file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    translated_pdf = tmp_path / "t.pdf"
    doc = pymupdf.open(); doc.new_page(width=612, height=792); doc.save(str(translated_pdf)); doc.close()

    lock_held = [False]

    class Tracker:
        def __getattr__(self, name):
            return lambda *a, **k: None

    # 用一个对 delete_page 代理验证锁；这里直接断言 _lock.locked() 在 with 块内为 True
    # 通过子线程间接触发：主线程持锁时子线程尝试 replace 应阻塞
    started = threading.Event()
    can_finish = threading.Event()
    original_delete = app_state._right_doc.delete_page

    def slow_delete(idx):
        lock_held[0] = app_state._lock.locked()
        started.set()
        can_finish.wait(timeout=5)
        original_delete(idx)

    app_state._right_doc.delete_page = slow_delete  # type: ignore[method-assign]

    def replacer():
        app_state.replace_pages(str(translated_pdf), [0])

    t = threading.Thread(target=replacer)
    t.start()
    started.wait(timeout=5)
    can_finish.set()
    t.join(timeout=10)
    assert lock_held[0] is True
```

> 注意：第三个锁测试方法对 `app_state._right_doc.delete_page` 做 monkeypatch 仅用于断言持锁；实现完成后该 monkeypatch 仍有效（method-assign 警告按 `ruff.toml` per-file-ignores 已对 `tests/*.py` 放宽 ANN，但 B008/方法重绑需加 `# noqa` 注释——按既有测试风格（见 `test_state.py` 中 `# noqa: ANN001, ANN202` 注释）补充 `# noqa` 即可）。
> 若该 monkeypatch 测试过于脆弱，可退化为与 `test_extract_page_holds_lock` 同构的"包一层 extract_func 但 replace 不回调"模型——此处保留实现者按实际 pymupdf 行为选择稳健写法。

- [ ] **Step 2: 运行测试确认失败**

运行：`pytest tests/test_state.py::test_replace_pages_batch_backfill_and_tracking -v`
预期：FAIL — `AttributeError: 'AppState' object has no attribute 'replace_pages'`

- [ ] **Step 3: 实现 `extract_pages` 与 `replace_pages`**（在 `state.py` 的 `AppState` 内，紧跟 `replace_page` 之后追加）

```python
    def extract_pages(self, page_indices: list[int], tmpdir: Path, extract_func) -> Path:
        """Extract multiple pages under the state lock.
        extract_func must not reenter AppState (non-reentrant lock)."""
        with self._lock:
            if self._left_doc is None:
                raise ValueError("no document opened")
            return extract_func(self._left_doc, page_indices, tmpdir)

    def replace_pages(self, translated_pdf_path: str, page_indices: list[int]) -> None:
        with self._lock:
            src_doc = pymupdf.open(translated_pdf_path)
            # 升序逐页 delete+insert：delete(idx) 与 insert_pdf(start_at=idx) 同位进出，
            # 其他索引保持稳定；升序推进时后续目标索引不受扰动（见设计文档 §5.2）。
            for j, idx in enumerate(page_indices):
                self._right_doc.delete_page(idx)
                self._right_doc.insert_pdf(src_doc, start_at=idx, from_page=j, to_page=j)
            tmp_save = self._right_pdf_path + ".tmp"
            self._right_doc.save(tmp_save)
            src_doc.close()
            self._right_doc.close()
            os.replace(tmp_save, self._right_pdf_path)
            self._right_doc = pymupdf.open(self._right_pdf_path)
            self._translated_pages.update(page_indices)
```

- [ ] **Step 4: 运行测试确认通过**

运行：`pytest tests/test_state.py -v`
预期：PASS（含既有 replace_page/extract_page 测试无回归）

- [ ] **Step 5: lint + 提交**

```bash
ruff check state.py tests/test_state.py
git add state.py tests/test_state.py
git commit -m "feat: add AppState.extract_pages/replace_pages batch primitives"
```

---

### Task 3: `build_settings` 参数化（`pages` / 显式 `input_pdf`）

**Files:**
- 修改: `translation_settings.py:14-50`
- 测试: `tests/test_services.py`（若已含 `build_settings` 测试则追加；否则在该文件新增）

**Interfaces:**
- 消费: `config`、`engine_resolver`
- 产出: `build_settings(input_pdf: str, user_prompt=None, output_dir=None, glossary_paths=None, pages: str = "1") -> SettingsModel`
  - 第一参数语义从"单页 PDF"放宽为"输入 PDF"；保持默认 `pages="1"` 以不破坏单页调用方。
  - 单页调用方（`routes.translate_page`）无需改动（仍传 `""`+默认 `pages="1"`）；批量调用方传多页 PDF + `pages="1-K"`。`no_dual=True`、`only_include_translated_page=True`、`ignore_cache=True` 沿用。

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_services.py`；若文件已 mock `config`/`engine_resolver` 则复用其 fixture 风格）

```python
def test_build_settings_multi_page_pages_param(monkeypatch):
    import translation_settings as ts

    monkeypatch.setattr(ts.config, "MODEL_PROVIDER", "deepseek")
    monkeypatch.setattr(ts.config, "TRANSLATION_LANG_IN", "en")
    monkeypatch.setattr(ts.config, "TRANSLATION_LANG_OUT", "zh")
    monkeypatch.setattr(ts.config, "GLOSSARY_PATH", __import__("pathlib").Path("/nonexistent"))

    settings = ts.build_settings("/tmp/multi.pdf", None, pages="1-4")
    assert settings.pdf.pages == "1-4"
    assert settings.pdf.only_include_translated_page is True
    assert settings.pdf.no_dual is True


def test_build_settings_default_pages_is_one(monkeypatch):
    import translation_settings as ts

    monkeypatch.setattr(ts.config, "MODEL_PROVIDER", "deepseek")
    monkeypatch.setattr(ts.config, "TRANSLATION_LANG_IN", "en")
    monkeypatch.setattr(ts.config, "TRANSLATION_LANG_OUT", "zh")
    monkeypatch.setattr(ts.config, "GLOSSARY_PATH", __import__("pathlib").Path("/nonexistent"))

    settings = ts.build_settings("/tmp/single.pdf", None)
    assert settings.pdf.pages == "1"
```

- [ ] **Step 2: 运行测试确认失败**

运行：`pytest tests/test_services.py::test_build_settings_multi_page_pages_param -v`
预期：FAIL — `TypeError: build_settings() got an unexpected keyword argument 'pages'`

- [ ] **Step 3: 实现**（修改 `translation_settings.py:14` 签名与第 45 行 `pages="1"`）

```python
def build_settings(
    input_pdf: str,
    user_prompt: str | None = None,
    output_dir: str | None = None,
    glossary_paths: list[str] | None = None,
    pages: str = "1",
) -> SettingsModel:
```

将 `Pdf2zhPDFSettings(pages="1", ...)` 改为 `Pdf2zhPDFSettings(pages=pages, ...)`，其余不变。

> 说明：参数名从 `single_page_pdf` 改为 `input_pdf`，因为现可接受多页 PDF。所有既有调用方仍按位置传首个字符串参数，语义兼容（`routes.translate_page` 传 `""` 占位）。grep 确认无其他位置参数名依赖：`routes.py:90`、`tests/test_routes.py:91` 调用均按位置传首参，不受重命名影响。

- [ ] **Step 4: 运行测试确认通过**

运行：`pytest tests/test_services.py tests/test_routes.py -v`
预期：PASS（既有 build_settings 路径无回归）

- [ ] **Step 5: lint + 提交**

```bash
ruff check translation_settings.py tests/test_services.py
git add translation_settings.py tests/test_services.py
git commit -m "feat: parameterize build_settings pages/input_pdf for batch translation"
```

---

## Group 2 — 后端批量翻译编排

### Task 4: `translation_lifecycle.merge_glossary_only` 仅术语表合并

**Files:**
- 修改: `translation_lifecycle.py`（在 `finish_translation` 之后新增）
- 测试: `tests/test_translation_lifecycle.py`（若存在则追加；否则新建）

**Interfaces:**
- 消费: `glossary_service.merge_after_translate`
- 产出: `merge_glossary_only(translate_result, glossary_cache_path: Path | None) -> None`——仅合并术语表，**不**调用 replace_page（多页已在 `generate_batch` 内通过 `replace_pages` 回填）。

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_translation_lifecycle.py`；参照 `sse_stream` 术语表合测试风格）

```python
def test_merge_glossary_only_does_not_replace(tmp_path, monkeypatch):
    import csv
    from unittest.mock import MagicMock
    from translation_lifecycle import merge_glossary_only

    glossary_cache = tmp_path / "cache"
    glossary_cache.mkdir()
    cumulative_file = glossary_cache / "cumulative_glossary.csv"
    with open(cumulative_file, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["source", "target"])
        w.writerow(["alpha", "阿尔法"])

    auto_file = glossary_cache / "auto.csv"
    with open(auto_file, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["source", "target"])
        w.writerow(["beta", "贝塔"])

    mock_result = MagicMock()
    mock_result.mono_pdf_path = str(tmp_path / "should_not_be_used.pdf")
    mock_result.dual_pdf_path = None
    mock_result.auto_extracted_glossary_path = str(auto_file)

    replace_calls = []
    monkeypatch.setattr(
        "translation_lifecycle.merge_after_translate",
        lambda cumulative, auto: None,
    )

    # 传一个会爆炸的 replace 以证明未被调用
    def explode(_path):
        replace_calls.append(1)

    merge_glossary_only(mock_result, glossary_cache)
    assert replace_calls == []  # 不应触发任何 replace
```

> 注：`merge_glossary_only` 签名不含 `replace_page` 参数，因此上面 `explode` 仅用于说明语义；实际断言通过"不调用 merge_glossary_only 之外的 replace"即可。测试可改为直接断言 `cumulative_glossary.csv` 在调用后包含 beta（真实合并发生）。修订版：

```python
    with open(cumulative_file, newline="", encoding="utf-8") as f:
        rows = {r["source"]: r["target"] for r in csv.DictReader(f)}
    assert rows.get("alpha") == "阿尔法"
    assert rows.get("beta") == "贝塔"
```

- [ ] **Step 2: 运行测试确认失败**

运行：`pytest tests/test_translation_lifecycle.py::test_merge_glossary_only_does_not_replace -v`
预期：FAIL — `ImportError: cannot import name 'merge_glossary_only'`

- [ ] **Step 3: 实现 `merge_glossary_only`**（在 `translation_lifecycle.py` 追加）

```python
def merge_glossary_only(
    translate_result: TranslateResult,
    glossary_cache_path: Path | None,
) -> None:
    """Only merge the auto-extracted glossary into the cumulative glossary.

    Multi-page batch translate already backfilled right.pdf via replace_pages
    in generate_batch; this path deliberately does NOT replace any page.
    """
    cumulative_glossary_file: Path | None = None
    if glossary_cache_path is not None:
        cumulative_glossary_file = glossary_cache_path / "cumulative_glossary.csv"
    merge_start = time.time()
    merge_after_translate(
        cumulative_glossary_file,
        translate_result.auto_extracted_glossary_path,
    )
    elapsed = time.time() - merge_start
    debug_trace.log_glossary_merge("merge_done", page=-1, elapsed=f"{elapsed:.2f}")
```

- [ ] **Step 4: 运行测试确认通过**

运行：`pytest tests/test_translation_lifecycle.py -v`
预期：PASS

- [ ] **Step 5: lint + 提交**

```bash
ruff check translation_lifecycle.py tests/test_translation_lifecycle.py
git add translation_lifecycle.py tests/test_translation_lifecycle.py
git commit -m "feat: add merge_glossary_only for batch translation glo(batch)ssary merge"
```

---

### Task 5: `sse_stream` 批量编排（`GenerateBatchContext` / `format_batch_info` / `generate_batch`）

**Files:**
- 修改: `sse_stream.py`（新增 `@dataclass GenerateBatchContext`、`format_batch_info`、`generate_batch`）
- 测试: `tests/test_sse_stream.py`

**Interfaces:**
- 消费:
  - Task 1 `pdf_extraction.extract_pages`
  - Task 3 `build_settings(..., pages="1-K")`
  - Task 4 `merge_glossary_only`
  - `run_translation`、`debug_trace`、既有 `format_sse_event`
- 产出:
  - `GenerateBatchContext` dataclass：`settings`, `from_page:int`, `to_page:int`, `page_indices:list[int]`, `replace_pages: Callable[[str], None]`, `glossary_cache_path`, `glossary_paths`, `cache_dir`, `extract_pages: Callable[[list[int], Path, Callable], Path]`
  - `format_batch_info(from_page:int, to_page:int, total:int) -> str` → `data: {"type":"batch_info","from":...,"to":...,"total":...}\n\n`
  - `generate_batch(ctx: GenerateBatchContext) -> Iterator[str]`

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_sse_stream.py`）

```python
from sse_stream import GenerateBatchContext, format_batch_info, generate_batch


def test_format_batch_info_event():
    sse = format_batch_info(2, 5, 4)
    assert sse == (
        'data: {"type": "batch_info", "from": 2, "to": 5, "total": 4}\n\n'
    )


def _make_batch_ctx(
    settings=None,
    from_page=2,
    to_page=5,
    page_indices=None,
    replace_pages=None,
    glossary_cache_path=None,
    glossary_paths=None,
    cache_dir=None,
    extract_pages=None,
) -> GenerateBatchContext:
    if settings is None:
        settings = MagicMock()
    if replace_pages is None:
        replace_pages = MagicMock()
    if cache_dir is None:
        cache_dir = Path(tempfile.mkdtemp())
    if extract_pages is None:
        extract_pages = MagicMock(return_value=Path("/fake/pages.pdf"))
    if page_indices is None:
        page_indices = list(range(from_page - 1, to_page))
    return GenerateBatchContext(
        settings=settings,
        from_page=from_page,
        to_page=to_page,
        page_indices=page_indices,
        replace_pages=replace_pages,
        glossary_cache_path=glossary_cache_path,
        glossary_paths=glossary_paths,
        cache_dir=cache_dir,
        extract_pages=extract_pages,
    )


def test_generate_batch_emits_batch_info_then_progress_then_finish(tmp_path):
    mock_result = MagicMock()
    mock_result.mono_pdf_path = str(tmp_path / "translated.pdf")
    mock_result.dual_pdf_path = None
    mock_result.auto_extracted_glossary_path = None

    events = [
        {"type": "progress_start", "stage": "layout_analysis", "overall_progress": 0,
         "stage_current": 0, "stage_total": 0},
        {"type": "progress_update", "stage": "translating", "overall_progress": 40,
         "stage_current": 1, "stage_total": 2},
        {"type": "finish", "stage": "generating_pdf", "translate_result": mock_result, "token_usage": {}},
    ]

    replace_pages = MagicMock()
    cache_dir = tmp_path / "cache"; cache_dir.mkdir()
    ctx = _make_batch_ctx(replace_pages=replace_pages, cache_dir=cache_dir)

    with patch("sse_stream.run_translation", return_value=iter(events)):
        with patch("sse_stream.debug_trace"):
            with patch("sse_stream.merge_glossary_only") as mg:
                result = list(generate_batch(ctx))

    # batch_info present at head
    assert '"type": "batch_info", "from": 2, "to": 5, "total": 4' in result[0]
    # progress events forwarded
    assert any('"type": "progress", "progress": 40' in r for r in result)
    # finish tail present
    assert any('"type": "finish"' in r for r in result)
    # replace_pages called once with translated pdf path
    replace_pages.assert_called_once_with(str(tmp_path / "translated.pdf"))
    # merge_glossary_only called (no replace internally)
    mg.assert_called_once()


def test_generate_batch_includes_already_translated_pages(tmp_path):
    """范围内已翻译页也纳入（不跳过）：page_indices 应等于 range(from-1,to)，无过滤。"""
    mock_result = MagicMock()
    mock_result.mono_pdf_path = str(tmp_path / "t.pdf")
    mock_result.auto_extracted_glossary_path = None
    mock_result.dual_pdf_path = None

    captured_indices = []
    def extract_spy(indices, tmpdir, func):
        captured_indices.append(list(indices))
        return Path("/fake/pages.pdf")

    ctx = _make_batch_ctx(
        from_page=1, to_page=3,
        extract_pages=extract_spy,
        cache_dir=tmp_path / "c" and (tmp_path / "c").mkdir() or tmp_path / "c",
    )

    with patch("sse_stream.run_translation", return_value=iter([
        {"type": "finish", "stage": "generating_pdf",
         "translate_result": mock_result, "token_usage": {}}
    ])):
        with patch("sse_stream.debug_trace"):
            with patch("sse_stream.merge_glossary_only"):
                list(generate_batch(ctx))

    assert captured_indices == [[0, 1, 2]]


def test_generate_batch_error_event_stops_stream(tmp_path):
    events = [{"type": "error", "error": "boom"}]
    ctx = _make_batch_ctx(cache_dir=tmp_path / "c" and (tmp_path / "c").mkdir() or tmp_path / "c")
    with patch("sse_stream.run_translation", return_value=iter(events)):
        with patch("sse_stream.debug_trace"):
            result = list(generate_batch(ctx))
    assert any('"type": "error"' in r for r in result)
    # no finish tail when error
    assert not any('"type": "finish"' in r for r in result)
```

> 注意：`_make_batch_ctx` 中 `cache_dir`/`tmp_path / "c" and ... or ...` 是为避免短表达式副作用失真，实现者可改为 `cache_dir = tmp_path / "c"; cache_dir.mkdir(); _make_batch_ctx(cache_dir=cache_dir)` 之标准写法。保留测试意图清晰即可。

- [ ] **Step 2: 运行测试确认失败**

运行：`pytest tests/test_sse_stream.py::test_format_batch_info_event -v`
预期：FAIL — `ImportError: cannot import name 'GenerateBatchContext'`

- [ ] **Step 3: 实现**（在 `sse_stream.py` 顶部 import `merge_glossary_only`、新增 dataclass 与函数）

顶部 import 改为：
```python
from translation_lifecycle import finish_translation, merge_glossary_only
```

在 `GenerateContext` 之后追加：
```python
@dataclass
class GenerateBatchContext:
    settings: SettingsModel
    from_page: int
    to_page: int
    page_indices: list[int]
    replace_pages: Callable[[str], None]
    glossary_cache_path: Path | None
    glossary_paths: list[str] | None
    cache_dir: Path
    extract_pages: Callable[[list[int], Path, Callable], Path]


def format_batch_info(from_page: int, to_page: int, total: int) -> str:
    return (
        "data: "
        + json.dumps(
            {
                "type": "batch_info",
                "from": from_page,
                "to": to_page,
                "total": total,
            }
        )
        + "\n\n"
    )


def generate_batch(ctx: GenerateBatchContext) -> Iterator[str]:
    tmpdir = Path(tempfile.mkdtemp())
    output_dir = Path(tempfile.mkdtemp(dir=str(ctx.cache_dir)))
    ctx.settings.translation.output = str(output_dir)
    try:
        with debug_trace.debug_session(ctx.glossary_cache_path, ctx.from_page):
            debug_trace.log_step("submit translate batch %d-%d", ctx.from_page, ctx.to_page)

            translate_start = time.time()
            translate_result = None
            token_usage_finish = None

            # 1. 锁内抽取多页 PDF（page_indices 含范围内已翻译页，不跳过）
            multi_page_pdf = ctx.extract_pages(ctx.page_indices, tmpdir, pdf_extraction.extract_pages)

            # 2. 发出 batch_info
            yield format_batch_info(ctx.from_page, ctx.to_page, len(ctx.page_indices))

            # 3. 锁外一次性翻译整段多页 PDF
            for evt in run_translation(ctx.settings, str(multi_page_pdf)):
                if not isinstance(evt, dict):
                    yield ""
                    continue
                if evt.get("type") == "finish":
                    translate_result = evt.get("translate_result")
                    token_usage_finish = evt.get("token_usage", {})

                sse = format_sse_event(evt)
                if sse is not None:
                    yield sse

                if evt.get("type") == "error":
                    return

            if translate_result is None:
                yield f"data: {json.dumps({'type': 'error', 'error': 'no translation result'})}\n\n"
                return

            debug_trace.log_step("translate batch %d-%d done (%.2fs)", ctx.from_page, ctx.to_page, time.time() - translate_start)
            if token_usage_finish:
                debug_trace.log_token_usage(token_usage_finish)

            # 4. 锁内批量回填 right.pdf（多页译文，升序逐页 delete+insert）
            translated_pdf = translate_result.mono_pdf_path
            if translated_pdf is None and translate_result.dual_pdf_path is not None:
                translated_pdf = translate_result.dual_pdf_path
            if translated_pdf is not None:
                ctx.replace_pages(str(translated_pdf))

            # 5. 仅合并术语表（不在 finish_translation 内重复 replace）
            merge_glossary_only(translate_result, ctx.glossary_cache_path)

            # 6. 发出 finish
            yield (
                "data: "
                + json.dumps(
                    {"type": "progress", "progress": 100, "stage": "finish",
                     "stage_current": 0, "stage_total": 0}
                )
                + "\n\n"
            )
            yield f"data: {json.dumps({'type': 'finish', 'progress': 100})}\n\n"

    except TranslationError as e:
        yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
    except Exception as e:
        logging.getLogger("pdf_reader").warning("translate_batch generate error", exc_info=True)
        yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
    finally:
        _safe_rmtree(tmpdir)
        _safe_rmtree(output_dir)
```

- [ ] **Step 4: 运行测试确认通过**

运行：`pytest tests/test_sse_stream.py -v`
预期：PASS（含既有 `generate` 测试无回归）

- [ ] **Step 5: lint + 提交**

```bash
ruff check sse_stream.py tests/test_sse_stream.py
git add sse_stream.py tests/test_sse_stream.py
git commit -m "feat: add generate_batch SSE orchestration with batch_info event"
```

---

### Task 6: `routes.POST /api/translate-batch` 端点（页码校验→SSE）

**Files:**
- 修改: `routes.py`（在 `translate_page` 路由之后新增）
- 测试: `tests/test_routes.py`

**Interfaces:**
- 消费:
  - Task 3 `build_settings(..., pages="1-K")`
  - Task 5 `sse_stream.GenerateBatchContext`/`generate_batch`
  - Task 2 `state.extract_pages`/`state.replace_pages`
- 产出: 路由 `POST /api/translate-batch`，请求 body `{from:int, to:int, prompt?:str}`（1-based），返回 SSE 流；非法页码→HTTP 400。

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_routes.py`）

```python
def test_translate_batch_validation_errors(app_state, sample_pdf):
    from file_hash import sha256 as sha256_func
    from flask import Flask
    from routes import register_routes

    app_state.open_pdf(str(sample_pdf), sha256_func)
    app = Flask(__name__); app.config["app_state"] = app_state; app.config["TESTING"] = True
    register_routes(app)

    with app.test_client() as client:
        # 起 > 止
        resp = client.post("/api/translate-batch", json={"from": 5, "to": 2})
        assert resp.status_code == 400
        assert "error" in json.loads(resp.data)

        # 超出范围
        resp = client.post("/api/translate-batch", json={"from": 0, "to": 1})
        assert resp.status_code == 400
        resp = client.post("/api/translate-batch", json={"from": 1, "to": 99})
        assert resp.status_code == 400

        # 非数字 / 缺失
        resp = client.post("/api/translate-batch", json={"from": None, "to": 1})
        assert resp.status_code == 400


def test_translate_batch_no_doc(test_client):
    resp = test_client.post("/api/translate-batch", json={"from": 1, "to": 1})
    assert resp.status_code == 400
    assert "error" in json.loads(resp.data)


def test_translate_batch_emits_batch_info_and_finish(app_state, sample_pdf, monkeypatch):
    from file_hash import sha256 as sha256_func
    from flask import Flask
    from routes import register_routes
    from unittest.mock import MagicMock
    from pathlib import Path

    app_state.open_pdf(str(sample_pdf), sha256_func)
    page_count = app_state.page_count  # 2

    def fake_build_settings(input_pdf, user_prompt=None, output_dir=None, glossary_paths=None, pages="1"):
        return MagicMock()

    async def fake_translate_stream(settings, file):
        yield {"type": "progress_start", "stage": "layout_analysis", "overall_progress": 0,
               "stage_current": 0, "stage_total": 0}
        mock_result = MagicMock()
        mock_result.mono_pdf_path = Path(str(sample_pdf))
        mock_result.dual_pdf_path = None
        mock_result.auto_extracted_glossary_path = None
        yield {"type": "finish", "stage": "generating_pdf", "translate_result": mock_result, "token_usage": {}}

    monkeypatch.setattr("routes.build_settings", fake_build_settings)
    monkeypatch.setattr("translation_orchestrator.do_translate_async_stream", fake_translate_stream)
    monkeypatch.setattr("glossary_service.merge_glossary_csvs", lambda c, a: None)

    app = Flask(__name__); app.config["app_state"] = app_state; app.config["TESTING"] = True
    register_routes(app)

    with app.test_client() as client:
        resp = client.post("/api/translate-batch", json={"from": 1, "to": page_count})
        assert resp.status_code == 200
        body = resp.data.decode("utf-8")
        assert '"type": "batch_info"' in body
        assert '"from": 1' in body and f'"to": {page_count}' in body
        assert '"type": "finish"' in body
```

- [ ] **Step 2: 运行测试确认失败**

运行：`pytest tests/test_routes.py::test_translate_batch_validation_errors -v`
预期：FAIL — `404`（路由不存在）

- [ ] **Step 3: 实现端点**（在 `routes.py` 的 `translate_page` 路由之后追加）

```python
@bp.route("/api/translate-batch", methods=["POST"])
def translate_batch():
    state = _get_state()
    if state.left_doc is None:
        return error_response("no document opened", 400)

    data = request.get_json(silent=True) or {}
    from_page = data.get("from")
    to_page = data.get("to")
    page_count = state.page_count

    if not isinstance(from_page, int) or not isinstance(to_page, int):
        return error_response("invalid page numbers", 400)
    if from_page < 1 or to_page < 1 or from_page > page_count or to_page > page_count:
        return error_response("page out of range", 400)
    if from_page > to_page:
        return error_response("invalid page range", 400)

    user_prompt = (data.get("prompt") or "").strip() or None
    page_indices = list(range(from_page - 1, to_page))
    k = len(page_indices)
    pages_str = f"1-{k}" if k > 1 else "1"

    glossary_paths = glossary_service.resolve_glossary_paths(state.glossary_cache_path)
    settings = build_settings(
        "",
        user_prompt,
        glossary_paths=glossary_paths,
        pages=pages_str,
    )
    ctx = sse_stream.GenerateBatchContext(
        settings=settings,
        from_page=from_page,
        to_page=to_page,
        page_indices=page_indices,
        replace_pages=lambda path: state.replace_pages(path, page_indices),
        glossary_cache_path=state.glossary_cache_path,
        glossary_paths=glossary_paths,
        cache_dir=config.CACHE_DIR,
        extract_pages=lambda indices, tmpdir, func: state.extract_pages(indices, tmpdir, func),
    )
    return Response(
        stream_with_context(sse_stream.generate_batch(ctx)),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

- [ ] **Step 4: 运行测试确认通过**

运行：`pytest tests/test_routes.py -v`
预期：PASS（含既有路由测试无回归）

- [ ] **Step 5: lint + 提交**

```bash
ruff check routes.py tests/test_routes.py
git add routes.py tests/test_routes.py
git commit -m "feat: add POST /api/translate-batch endpoint with page validation"
```

---

## Group 3 — 前端工具栏 UI

### Task 7: `templates/index.html` 工具栏新元素

**Files:**
- 修改: `templates/index.html:22-30`（`#toolbar` 内）

**Interfaces:**
- 产出: 新增 `input#from-page`、`input#to-page`（`type="number" min="1"`）、`button#range-translate-btn`（"范围翻译"）、`button#full-translate-btn`（"全文翻译"）

- [ ] **Step 1: 修改 `index.html` 的 `#toolbar`**

将：
```html
<div id="toolbar" class="hidden">
    <span class="page-indicator" id="page-indicator">Page --</span>
    <span id="zoom-level">100%</span>
    <button id="zoom-reset">重置缩放</button>
    <button id="prompt-toggle">+ Prompt</button>
    <input type="text" id="prompt-input" placeholder="Custom prompt..." style="display:none">
    <div id="progress-bar"><div id="progress-track"><div id="progress-fill"></div></div><span id="progress-status-text"></span></div>
    <button id="translate-btn">Translate</button>
</div>
```
改为：
```html
<div id="toolbar" class="hidden">
    <span class="page-indicator" id="page-indicator">Page --</span>
    <span id="zoom-level">100%</span>
    <button id="zoom-reset">重置缩放</button>
    <button id="prompt-toggle">+ Prompt</button>
    <input type="text" id="prompt-input" placeholder="Custom prompt..." style="display:none">
    <div id="batch-range-group">
        <label for="from-page">起</label>
        <input type="number" id="from-page" min="1" step="1">
        <label for="to-page">止</label>
        <input type="number" id="to-page" min="1" step="1">
    </div>
    <button id="range-translate-btn" type="button">范围翻译</button>
    <button id="full-translate-btn" type="button">全文翻译</button>
    <div id="progress-bar"><div id="progress-track"><div id="progress-fill"></div></div><span id="progress-status-text"></span></div>
    <button id="translate-btn">Translate</button>
</div>
```

- [ ] **Step 2: 验证**（在浏览器或 `test_index_route`）

`test_index_route` 已返回 200；新增元素应在 HTML 中可见。无需新增测试（静态结构），手动开页确认元素存在即可。

- [ ] **Step 3: 提交**

```bash
git add templates/index.html
git commit -m "feat: add batch range/full translate toolbar elements"
```

---

### Task 8: `static/modules/dom.js` 注册新元素引用

**Files:**
- 修改: `static/modules/dom.js`

**Interfaces:**
- 产出: `getElements()` 返回值新增 `fromPage`、`toPage`、`rangeTranslateBtn`、`fullTranslateBtn`

- [ ] **Step 1: 修改 `dom.js` 的 `getElements`**

在 `const pdfPathInput = document.getElementById('pdf-path');` 之后追加：
```javascript
    const fromPage = document.getElementById('from-page');
    const toPage = document.getElementById('to-page');
    const rangeTranslateBtn = document.getElementById('range-translate-btn');
    const fullTranslateBtn = document.getElementById('full-translate-btn');
```

并在 `_cache = { ... }` 对象中追加（与既有键风格一致）：
```javascript
        fromPage,
        toPage,
        rangeTranslateBtn,
        fullTranslateBtn,
```

- [ ] **Step 2: 验证**

`node tests/run-translator-tests.mjs` 仍 PASS（dom.js 未被 translator 测试加载，但保留绿态）。手动浏览器确认 `getElements().rangeTranslateBtn` 非 null。

- [ ] **Step 3: 提交**

```bash
git add static/modules/dom.js
git commit -m "feat: register batch toolbar element refs in dom.js"
```

---

### Task 9: `static/style.css` 工具栏新元素样式

**Files:**
- 修改: `static/style.css`（在 `#toolbar #translate-btn` 相关块之后追加）

- [ ] **Step 1: 追加样式**（保证工具栏 `gap` 布局协调，复用既有 `#48c78e` 绿、`#2a2a2a` 输入底色）

```css
#toolbar #batch-range-group {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 13px;
    color: #aaa;
}

#toolbar #from-page,
#toolbar #to-page {
    width: 56px;
    background: #2a2a2a;
    border: 1px solid #555;
    color: #ddd;
    padding: 6px 8px;
    border-radius: 6px;
    font-size: 13px;
    outline: none;
}

#toolbar #from-page:focus,
#toolbar #to-page:focus {
    border-color: #48c78e;
}

#toolbar #range-translate-btn,
#toolbar #full-translate-btn {
    background: #48c78e;
    color: #1a1a1a;
    border: none;
    padding: 8px 18px;
    border-radius: 8px;
    cursor: pointer;
    font-size: 13px;
    font-weight: 600;
    white-space: nowrap;
    transition: background 0.2s;
}

#toolbar #range-translate-btn:hover:not(:disabled),
#toolbar #full-translate-btn:hover:not(:disabled) {
    background: #3bb87a;
}

#toolbar #range-translate-btn:disabled,
#toolbar #full-translate-btn:disabled {
    background: #555;
    color: #888;
    cursor: not-allowed;
}
```

- [ ] **Step 2: 验证**

手动浏览器开 PDF，确认工具栏不溢出、新输入/按钮可见且 disabled 态样式生效（批量进行中会用到）。

- [ ] **Step 3: 提交**

```bash
git add static/style.css
git commit -m "feat: style batch range/full translate toolbar elements"
```

---

## Group 4 — 前端批量翻译逻辑

### Task 10: `static/modules/translator.js` 新增 `translateBatch`

**Files:**
- 修改: `static/modules/translator.js`
- 测试: `tests/run-translator-tests.mjs`

**Interfaces:**
- 消费: `./sse-client.js` 的 `readSSEStream`、`./stages.js` 的 `getStageLabel`
- 产出: `translateBatch(from:int, to:int, callbacks) -> Promise<void>`，请求 `/api/translate-batch` body `{from, to, prompt}`，解析 `batch_info`/`progress`/`finish`/`error`，回调：`onBatchInfo(from, to, total)`、`onProgress(percent)`、`onStageChange(stage, label)`、`onFinish()`、`onError(msg)`，`callbacks.prompt` 可选。

- [ ] **Step 1: 写失败测试**（追加到 `tests/run-translator-tests.mjs`）

更新 `wrappedCode` 的 `stripExports` 列表与返回对象以包含 `translateBatch`：

```javascript
// 在 allCode 数组后追加 translator.js 已被加载，确保 wrappedCode return 含 translateBatch
const wrappedCode = `\n${allCode}\nreturn { readSSEStream, translateCurrentPage, translateBatch, getStageLabel };\n`;
```

> 由于 `translator.js` 已在 `allCode` 中，仅需在返回语句加入 `translateBatch`；新增的 `translateBatch` 与 `translateCurrentPage` 同文件，`stripExports` 会把其 `export async function` 转为 `async function`。

追加测试块：
```javascript
// Test 4.1: translateBatch emits batch_info -> progress -> finish
console.log('--- Test 4.1: translateBatch batch_info/progress/finish ---');
{
    const record = [];
    const sseBody = [
        'data: {"type":"batch_info","from":2,"to":5,"total":4}\n',
        '\n',
        'data: {"type":"progress","progress":10,"stage":"layout_analysis","stage_current":0,"stage_total":0}\n',
        '\n',
        'data: {"type":"progress","progress":60,"stage":"translating","stage_current":1,"stage_total":2}\n',
        '\n',
        'data: {"type":"finish"}\n',
        '\n',
    ].join('');
    const stream = makeSSEStream(sseBody);
    const mockFetchResp = createMockResponse({ ok: true, body: stream });
    globalThis.fetch = async (url, init) => mockFetchResp;

    const callbacks = {
        onBatchInfo: (f, t, total) => record.push({ type: 'batchInfo', f, t, total }),
        onStageChange: (stage, label) => record.push({ type: 'stage', stage, label }),
        onProgress: (p) => record.push({ type: 'progress', p }),
        onFinish: () => record.push({ type: 'finish' }),
        onError: (msg) => record.push({ type: 'error', msg }),
        prompt: null,
    };

    await translateBatch(2, 5, callbacks);

    assert(record[0].type === 'batchInfo' && record[0].f === 2 && record[0].t === 5 && record[0].total === 4, 'Test 4.1.1: onBatchInfo first');
    assert(record.some(r => r.type === 'progress' && r.p === 60), 'Test 4.1.2: onProgress(60) called');
    assert(record.some(r => r.type === 'stage' && r.label.includes('正在翻译')), 'Test 4.1.3: onStageChange translating');
    assert(record.some(r => r.type === 'stage' && r.label.includes('第 1/2 段')), 'Test 4.1.4: stage suffix');
    assert(record[record.length - 1].type === 'finish', 'Test 4.1.5: onFinish last');
    assert(!record.some(r => r.type === 'error'), 'Test 4.1.6: no onError');
}

// Test 4.2: translateBatch HTTP !ok -> onError
console.log('--- Test 4.2: translateBatch HTTP not ok -> onError ---');
{
    const record = [];
    const mockFetchResp = createMockResponse({ ok: false, jsonData: { error: 'page out of range' } });
    globalThis.fetch = async (url, init) => mockFetchResp;

    await translateBatch(0, 1, {
        onBatchInfo: () => {}, onStageChange: () => {}, onProgress: () => {},
        onFinish: () => record.push('finish'),
        onError: (msg) => record.push({ type: 'error', msg }),
        prompt: null,
    });

    assert(record.length === 1, 'Test 4.2.1: exactly 1 callback');
    assert(record[0].type === 'error' && record[0].msg === 'page out of range', 'Test 4.2.2: onError(msg)');
    assert(!record.includes('finish'), 'Test 4.2.3: no onFinish');
}

// Test 4.3: translateBatch prompt forwarded in body
console.log('--- Test 4.3: translateBatch prompt forwarding ---');
{
    let capturedBody = null;
    const stream = makeSSEStream('data: {"type":"batch_info","from":1,"to":1,"total":1}\n\ndata: {"type":"finish"}\n\n');
    const mockFetchResp = createMockResponse({ ok: true, body: stream });
    globalThis.fetch = async (url, init) => { capturedBody = init.body; return mockFetchResp; };

    await translateBatch(1, 1, {
        onBatchInfo: () => {}, onStageChange: () => {}, onProgress: () => {},
        onFinish: () => {}, onError: () => {}, prompt: '正式语气',
    });
    assert(capturedBody === '{"from":1,"to":1,"prompt":"正式语气"}', `Test 4.3.1: body has from/to/prompt, got "${capturedBody}"`);
}
```

- [ ] **Step 2: 运行测试确认失败**

运行：`node tests/run-translator-tests.mjs`
预期：FAIL — `ReferenceError: translateBatch is not defined`（wrappedCode 未导出，因实现尚未添加）

- [ ] **Step 3: 实现 `translateBatch`**（在 `translator.js` 的 `translateCurrentPage` 之后追加）

```javascript
export async function translateBatch(from, to, callbacks) {
    const { onBatchInfo, onStageChange, onProgress, onFinish, onError } = callbacks;

    try {
        const resp = await fetch('/api/translate-batch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ from, to, prompt: callbacks.prompt || null }),
        });

        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.error || 'Batch translation failed');
        }

        await readSSEStream(resp, (evt) => {
            if (evt.type === 'batch_info') {
                onBatchInfo(evt.from, evt.to, evt.total);
            } else if (evt.type === 'progress') {
                onProgress(evt.progress);
                if (evt.stage) {
                    let label = getStageLabel(evt.stage);
                    if (evt.stage_current > 0 && evt.stage_total > 0) {
                        label += ` 第 ${evt.stage_current}/${evt.stage_total} 段`;
                    }
                    onStageChange(evt.stage, label);
                }
            } else if (evt.type === 'finish') {
                onFinish();
            } else if (evt.type === 'error') {
                onError(evt.error);
            }
        });
    } catch (e) {
        onError(e.message || '批量翻译出错');
    }
}
```

- [ ] **Step 4: 运行测试确认通过**

运行：`node tests/run-translator-tests.mjs`
预期：`PASS`（含既有 3.x 测试与新 4.x 测试）

- [ ] **Step 5: 提交**

```bash
git add static/modules/translator.js tests/run-translator-tests.mjs
git commit -m "feat: add translateBatch SSE client in translator.js"
```

---

### Task 11: `static/app.js` 新增 `onBatchTranslateClick` / `onFullTranslateClick` 与批量进度

**Files:**
- 修改: `static/app.js`

**Interfaces:**
- 消费:
  - Task 10 `translator.translateBatch`（import 在顶部 `import { translateCurrentPage }` 处并列）
  - Task 8 `getElements()` 的 `fromPage`/`toPage`/`rangeTranslateBtn`/`fullTranslateBtn`
- 产出: `onBatchTranslateClick()`、`onFullTranslateClick()`、`runBatchTranslate(from, to)`（共享校验/确认/进度/刷新逻辑）、批量进度区文字「翻译第 from-to 页（共 N 页）· 」+ 百分比/阶段标签；`finish` 后批量刷新范围内右侧译图 + `loadTranslatedState()`；批量进行中 `isTranslating` 互斥禁用单页 Translate、范围/全文按钮、起/止输入框。

- [ ] **Step 1: 修改 `app.js` 顶部 import**

将：
```javascript
import { translateCurrentPage } from './modules/translator.js';
```
改为：
```javascript
import { translateCurrentPage, translateBatch } from './modules/translator.js';
```

- [ ] **Step 2: 在 `init()` 内追加事件绑定**

在 `els.translateBtn.addEventListener('click', onTranslateClick);` 之后追加：
```javascript
    els.rangeTranslateBtn.addEventListener('click', onBatchTranslateClick);
    els.fullTranslateBtn.addEventListener('click', onFullTranslateClick);
```

- [ ] **Step 3: 实现 `runBatchTranslate` 共享逻辑**（在 `onTranslateClick` 之后追加）

```javascript
const BATCH_CONFIRM_THRESHOLD = 10;
const BATCH_CONFIRM_HINT = '通常十页约需 300–400 秒';

async function runBatchTranslate(from, to) {
    if (isTranslating) return;

    const pageCnt = pageCount;
    if (!Number.isInteger(from) || !Number.isInteger(to)) {
        els.progressStatusText.textContent = '请输入有效页码';
        els.progressStatusText.classList.add('error');
        return;
    }
    if (from < 1 || to < 1 || from > pageCnt || to > pageCnt) {
        els.progressStatusText.textContent = '页码超出范围';
        els.progressStatusText.classList.add('error');
        return;
    }
    if (from > to) {
        els.progressStatusText.textContent = '起页不能大于止页';
        els.progressStatusText.classList.add('error');
        return;
    }

    const rangeCount = to - from + 1;
    if (rangeCount > BATCH_CONFIRM_THRESHOLD) {
        if (!window.confirm(BATCH_CONFIRM_HINT)) return;
    }

    isTranslating = true;
    setBatchControlsDisabled(true);
    els.translateBtn.disabled = true;
    els.translateBtn.textContent = 'Translating...';
    els.progressBar.classList.add('active');
    els.progressFill.style.width = '0%';
    els.progressStatusText.textContent = `翻译第 ${from}-${to} 页（共 ${rangeCount} 页）· `;
    els.progressStatusText.classList.remove('error', 'done');
    if (statusTimer) { clearTimeout(statusTimer); statusTimer = null; }

    try {
        await translateBatch(from, to, {
            prompt: els.promptInput.value.trim() || null,
            onBatchInfo(f, t, total) {
                els.progressStatusText.textContent = `翻译第 ${f}-${t} 页（共 ${total} 页）· `;
            },
            onStageChange(stage, labelText) {
                const base = `翻译第 ${from}-${to} 页（共 ${rangeCount} 页）· `;
                els.progressStatusText.textContent = base + labelText;
                if (stage === 'finish') {
                    els.progressStatusText.classList.add('done');
                    els.progressStatusText.classList.remove('error');
                } else {
                    els.progressStatusText.classList.remove('done', 'error');
                }
            },
            onProgress(percent) {
                els.progressFill.style.width = `${percent}%`;
            },
            onFinish() {
                els.progressFill.style.width = '100%';
                els.progressStatusText.textContent = getStageLabel('finish');
                els.progressStatusText.classList.add('done');
                els.progressStatusText.classList.remove('error');
                statusTimer = setTimeout(() => {
                    els.progressBar.classList.remove('active');
                    els.progressStatusText.textContent = '';
                    els.progressStatusText.classList.remove('done', 'error');
                }, 2000);

                // 批量刷新范围内右侧译图
                for (let p = from - 1; p <= to - 1; p++) {
                    const rightEl = els.rightCol.querySelector(`.page-container[data-page="${p}"]`);
                    if (rightEl) {
                        if (rightEl.dataset.loaded === 'true') {
                            unloadPageImage(rightEl);
                            loadPageImage(rightEl);
                        }
                        rightEl.classList.add('translated');
                    }
                }
                loadTranslatedState();
            },
            onError(message) {
                els.progressBar.classList.remove('active');
                els.progressStatusText.textContent = message;
                els.progressStatusText.classList.add('error');
                els.progressStatusText.classList.remove('done');
                statusTimer = setTimeout(() => {
                    els.progressStatusText.textContent = '';
                    els.progressStatusText.classList.remove('error', 'done');
                }, 3000);
            },
        });
    } finally {
        isTranslating = false;
        setBatchControlsDisabled(false);
        els.translateBtn.disabled = false;
        els.translateBtn.textContent = 'Translate';
    }
}

function setBatchControlsDisabled(disabled) {
    els.rangeTranslateBtn.disabled = disabled;
    els.fullTranslateBtn.disabled = disabled;
    els.fromPage.disabled = disabled;
    els.toPage.disabled = disabled;
}

async function onBatchTranslateClick() {
    const from = parseInt(els.fromPage.value, 10);
    const to = parseInt(els.toPage.value, 10);
    await runBatchTranslate(from, to);
}

async function onFullTranslateClick() {
    await runBatchTranslate(1, pageCount);
}
```

> 注意：`onTranslateClick`（既有）已 `isTranslating=true` 并 `els.translateBtn.disabled=true`；为使单页进行中也会禁用批量按钮，需在 `onTranslateClick` 的 `isTranslating = true;` 之后追加 `setBatchControlsDisabled(true);`，并在其 `finally` 块的 `els.translateBtn.disabled = false;` 之后追加 `setBatchControlsDisabled(false);`。
> `parseInt` 对空/非法输入返回 `NaN`，`Number.isInteger(NaN)=false`，由 `runBatchTranslate` 的校验分支捕获为「请输入有效页码」（覆盖场景"空输入或非数字"）。

- [ ] **Step 4: 在 `onTranslateClick` 内补全互斥**

按上面注意项，在 `onTranslateClick` 的 `isTranslating = true;` 行之后插入 `setBatchControlsDisabled(true);`；在 `} finally {` 块内 `els.translateBtn.disabled = false;` 之后插入 `setBatchControlsDisabled(false);`。（`setBatchControlsDisabled` 已在 Task 11 Step 3 内定义。）

- [ ] **Step 5: lint/运行前端测试 + 提交**

`node tests/run-translator-tests.mjs` 应仍 PASS（app.js 不在 translator 测试加载范围，但确认无回归）。手动浏览器验证：起>止弹错、超 11 页弹 confirm、≤10 不弹、`finish` 后范围内译图刷新且标记已翻译、翻译中四类按钮/两输入框 disabled。

```bash
git add static/app.js
git commit -m "feat: add batch/full translate click handlers with confirm + progress"
```

---

### Task 12: 批量完成后刷新 `/api/translated-pages` 标记

**Files:**
- 修改: `static/app.js`（在 Task 11 已含 `loadTranslatedState()` 调用）

**说明：** Task 11 Step 3 的 `onFinish` 已调用 `loadTranslatedState()`（既有函数会拉 `/api/translated-pages` 并标记 `.translated`）。本任务为显式确认项，无额外代码；若想确保标记最及时，可在 `onFinish` 内先 `await loadTranslatedState()`（`loadTranslatedState` 已是 async）。实现者按既有同步调用风格保留即可。

- [ ] **Step 1: 确认 `loadTranslatedState` 被调用**

已在 Task 11 Step 3 `onFinish` 内调用。手动验证：批量完成后右栏范围内页出现 `.translated` 标记（样式上表现为已翻译态）。

- [ ] **Step 2: 提交**（若无需改动则跳过提交；如调整了 await 则单独提交）

```bash
# 仅当对 loadConvertedState 调用做了调整时
git add static/app.js
git commit -m "feat: refresh translated-pages state after batch finish"
```

---

## Group 5 — 集成验证与回归

### Task 13: 全量 lint / typecheck / 测试套件回归

**Files:**
- 无源码改动

- [ ] **Step 1: 运行后端全部测试与 ruff**

```bash
ruff check .
pytest -v
```
预期：所有测试 PASS（含 `tests/test_pdf_extraction.py`、`tests/test_state.py`、`tests/test_routes.py`、`tests/test_sse_stream.py`、`tests/test_translation_lifecycle.py`、`tests/test_services.py` 及既有测试），ruff 无新增告警。

- [ ] **Step 2: 运行前端测试**

```bash
node tests/run-translator-tests.mjs
```
预期：`PASS`。

- [ ] **Step 3: 手动端到端冒烟（可选）**

起 `python app.py`，开 PDF：
1. 范围翻译 2–5（≤4 页，不弹窗）→ 进度区显示「翻译第 2-5 页（共 4 页）· …」→ 完成后第 2–5 页右栏刷新并标记已翻译。
2. 范围翻译含已翻译页（如 3–3）→ 该页被重译覆盖。
3. 全文翻译（>10 页文档）→ 弹 confirm，取消则不开始。
4. 起 5 止 2 → 错误提示，不开始。
5. 翻译进行中单页 Translate/范围/全文/输入框 disabled。

- [ ] **Step 4: 提交与本计划完成确认**

无代码改动则无需提交；如发现回归按对应 Task 修补并补提交。最终 `git log` 应含本计划各 Task 提交。

---

## 实现期校验结论（Task 0 spike 结果回写）

- [x] pymupdf 本机版本对 `insert_pdf(from_page=j, to_page=j)` 单页插入：**支持**（pymupdf 1.25.2，已验证 3 页逐页 insert_pdf + start_at 到位插入，输出页数/内容正确）
- [x] pdf2zh-next `pages="1-K"` + `only_include_translated_page=True` 输出页数 == K 且顺序 == target_pages 顺序：**确认**
  - 输入：6 页合成 PDF（P0..P5），抽取子集 [1,2,3]（0-based，对应 P1,P2,P3）→ 3 页 subset PDF
  - 喂入：`pages="1-3"`, `only_include_translated_page=True`, `no_dual=True`
  - 结果：`mono_pdf_path` 输出 3 页，输出第 0 页对应 P1、第 1 页对应 P2、第 2 页对应 P3，顺序严格匹配子集输入顺序
  - 结论：`output_page[j] ↔ target_pages[j]` 映射成立，无需回填修正算法

---

## Self-Review

**Spec 覆盖核对（按 `specs/.../spec.md` Requirement → Task）：**
- 页码范围翻译（含"含已翻译页一并重译""范围仅一页""完成刷新译页"）→ Task 1/2/5/6 + Task 11（onFinish 范围内刷新）+ Task 13。
- 全文翻译 → Task 11 Step 3 `onFullTranslateClick`（复用 `runBatchTranslate(1, pageCount)`）。
- 大批量确认保护（>10 弹窗、≤10 直接、按范围页数判断不扣已翻译）→ Task 11 `BATCH_CONFIRM_THRESHOLD`/`window.confirm`。
- 批量翻译进度展示（「翻译第 from-to 页（共 N 页）」+ 整体%/阶段标签含段落级）→ Task 5 `batch_info` + Task 10 解析 + Task 11 进度区文字。
- 批量翻译页码范围校验（起>止/超出/非数字 → 阻断）→ Task 6 后端 400 + Task 11 前端 `runBatchTranslate` 校验。
- 批量翻译 SSE 端点（batch_info、纳入已翻译页重译、校验→400）→ Task 5/6，已翻译页不跳过由 `page_indices = range(from-1, to)` 保证（Task 6 + `test_generate_batch_includes_already_translated_pages`）。

**占位符扫描：** 无 TBD/TODO；所有 step 含完整代码或确切命令与预期。

**类型一致性核对：**
- `extract_pages(src_doc, page_indices, tmpdir)` 在 `pdf_extraction.py`、`AppState.extract_pages`、`sse_stream.generate_batch` 调用、`routes.translate_batch` 闭包签名一致。
- `replace_pages(translated_pdf_path: str, page_indices: list[int])` 在 `state.py`、`routes.translate_batch` 闭包 `lambda path: state.replace_pages(path, page_indices)`、`GenerateBatchContext.replace_pages: Callable[[str], None]` 一致。
- `build_settings(input_pdf, ..., pages="1")` 与 Task 6 调用 `build_settings("", user_prompt, glossary_paths=..., pages=pages_str)` 一致。
- `merge_glossary_only(translate_result, glossary_cache_path)` 在 `translation_lifecycle.py` 与 `sse_stream.generate_batch` 调用一致。
- 前端 `translateBatch(from, to, callbacks)` 与 `app.runBatchTranslate` 调用、`run-translator-tests.mjs` 测试签名一致；`onBatchInfo(from,to,total)` 与 `batch_info` 字段一致。
- `setBatchControlsDisabled` 在 `onTranslateClick`（Step 4）与 `runBatchTranslate`（Step 3）均引用，命名一致。

无遗漏项。