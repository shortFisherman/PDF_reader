---
change: harden-pdf-state-concurrency
design-doc: docs/superpowers/specs/2026-06-21-harden-pdf-state-concurrency-design.md
base-ref: cb737e1477364beeaa6fa1945688e1676ef7f656
---

# Harden PDF State Concurrency 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 AppState 的渲染竞态、replace_page 锁内慢 IO 与并发损坏、以及 translate_page 无页码校验三处缺陷。

**Architecture:** 双层锁分离——`_lock`（主锁）保护 doc 内存状态，`_write_lock`（串行锁）仅串行化 `os.replace` 原子操作。`render_page` 全程持主锁；`replace_page` 在主锁内完成内存操作 + save(tmp)，释放主锁后在 `_write_lock` 内做 os.replace，再重新取主锁 close + reopen。`translate_page` 入口校验页码范围。

**Tech Stack:** Python 3, threading.Lock/Event/Barrier, PyMuPDF (pymupdf), Flask, pytest, ruff

## Global Constraints

- 不引入新依赖；仅使用标准库 `threading` + 已有 `pymupdf`
- 现有 45 个测试必须始终保持绿色（任何修复不得破坏既有行为）
- TDD 顺序：先写失败特征测试 → 确认失败 → 修复 → 确认通过
- `os.replace` 原子操作必须串行化（`_write_lock`），且不得在持有 `_lock` 时执行
- 加锁顺序始终为 `_lock` → `_write_lock`（从不反向），确保无死锁
- `_right_doc` 在 `os.replace` 期间保持打开（design doc 关键决策）
- 单一 tmp 文件名 `self._right_pdf_path + ".tmp"`；并发 os.replace 需 `try/except FileNotFoundError` 容忍（另一线程已消费 tmp，此时 right.pdf 已含最新内容）
- 页码校验：`0 <= page < state.page_count`，越界返回 `error_response("page out of range", 400)`
- 不添加任何注释（遵循项目代码风格约定）

## File Structure

| 文件 | 职责 | 变更类型 |
|------|------|----------|
| `state.py` | AppState 并发状态管理 | 修改 `__init__`、`render_page`、`replace_page` |
| `routes.py` | Flask 路由 | 修改 `translate_page` 增加页码校验 |
| `tests/test_state.py` | State 并发测试 | 新增 3 个测试函数 |
| `tests/test_routes.py` | 路由测试 | 新增 1 个测试函数 |

无新文件创建。所有变更在现有文件内完成。

---

### Task 1: TDD 安全网 — 编写四个失败特征测试

**Files:**
- Modify: `tests/test_state.py`（顶部增加 import；文件末尾追加 3 个测试函数）
- Modify: `tests/test_routes.py`（文件末尾追加 1 个测试函数）

**Interfaces:**
- Consumes: `AppState`（state.py）、`sample_pdf`/`app_state`/`tmp_path` fixtures（conftest.py）、`sha256`（services.py）、Flask test client
- Produces: 4 个新测试函数，用于验证 Task 2-4 的修复

- [ ] **Step 1: 在 `tests/test_state.py` 顶部增加 import**

将文件头部从：

```python
from pathlib import Path

from state import AppState
```

改为：

```python
import os
import threading
import time

import pymupdf
from pathlib import Path

from state import AppState
```

- [ ] **Step 2: 在 `tests/test_state.py` 末尾追加渲染竞态测试**

```python
def test_render_page_concurrent_replace_no_crash(app_state, sample_pdf, tmp_path):
    """render_page 渲染期间并发 replace_page 不得导致段错误或异常。"""
    from services import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)

    translated_pdf = tmp_path / "translated.pdf"
    doc = pymupdf.open()
    doc.new_page(width=612, height=792)
    doc.save(str(translated_pdf))
    doc.close()

    render_started = threading.Event()
    render_can_finish = threading.Event()

    def slow_render_func(doc, page_num, dpi):
        render_started.set()
        render_can_finish.wait(timeout=5)
        page = doc[page_num]
        pix = page.get_pixmap(dpi=dpi)
        return pix.tobytes(output="png")

    render_result = [None]
    render_error = [None]

    def render_thread():
        try:
            render_result[0] = app_state.render_page(
                "right", 0, slow_render_func, 72
            )
        except Exception as e:
            render_error[0] = e

    def replace_thread():
        render_started.wait(timeout=5)
        app_state.replace_page(str(translated_pdf), 0)

    t1 = threading.Thread(target=render_thread)
    t2 = threading.Thread(target=replace_thread)
    t1.start()
    t2.start()

    time.sleep(0.2)
    render_can_finish.set()

    t1.join(timeout=10)
    t2.join(timeout=10)

    assert render_error[0] is None, f"render crashed: {render_error[0]}"
    assert render_result[0] is not None
    assert render_result[0][:4] == b"\x89PNG"
```

- [ ] **Step 3: 在 `tests/test_state.py` 末尾追加并发 replace 不同页测试**

```python
def test_concurrent_replace_different_pages(app_state, sample_pdf, tmp_path):
    """两线程并发 replace_page 不同页，right.pdf 保持有效且两页均替换。"""
    from services import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    page_count = app_state.page_count
    assert page_count == 2

    translated_pdfs = []
    for i in range(page_count):
        path = tmp_path / f"translated_{i}.pdf"
        doc = pymupdf.open()
        page = doc.new_page(width=612, height=792)
        page.insert_text((50, 100), f"TRANSLATED_{i}", fontsize=24)
        doc.save(str(path))
        doc.close()
        translated_pdfs.append(path)

    barrier = threading.Barrier(2)
    errors = [None, None]

    def replace_page(idx):
        try:
            barrier.wait(timeout=5)
            app_state.replace_page(str(translated_pdfs[idx]), idx)
        except Exception as e:
            errors[idx] = e

    threads = [
        threading.Thread(target=replace_page, args=(i,))
        for i in range(page_count)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert errors[0] is None, f"replace page 0 failed: {errors[0]}"
    assert errors[1] is None, f"replace page 1 failed: {errors[1]}"

    doc = pymupdf.open(app_state._right_pdf_path)
    assert doc.page_count == 2
    assert "TRANSLATED_0" in doc[0].get_text()
    assert "TRANSLATED_1" in doc[1].get_text()
    doc.close()

    assert 0 in app_state.translated_pages
    assert 1 in app_state.translated_pages
```

- [ ] **Step 4: 在 `tests/test_state.py` 末尾追加慢 IO 不阻塞测试**

```python
def test_slow_os_replace_does_not_block_reads(app_state, sample_pdf, tmp_path, monkeypatch):
    """os.replace 慢 IO 不得阻塞 get_doc（主锁在 os.replace 期间已释放）。"""
    from services import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)

    translated_pdf = tmp_path / "translated.pdf"
    doc = pymupdf.open()
    doc.new_page(width=612, height=792)
    doc.save(str(translated_pdf))
    doc.close()

    delay = 0.5
    original_replace = os.replace
    replace_started = threading.Event()

    def slow_replace(src, dst):
        replace_started.set()
        time.sleep(delay)
        return original_replace(src, dst)

    monkeypatch.setattr("state.os.replace", slow_replace)

    def do_replace():
        app_state.replace_page(str(translated_pdf), 0)

    t = threading.Thread(target=do_replace)
    t.start()

    replace_started.wait(timeout=5)

    start = time.time()
    doc = app_state.get_doc("right")
    elapsed = time.time() - start

    assert elapsed < delay, f"get_doc blocked for {elapsed:.2f}s (should be < {delay}s)"
    assert doc is not None

    t.join(timeout=10)
```

- [ ] **Step 5: 在 `tests/test_routes.py` 末尾追加越界页码测试**

```python
def test_translate_page_out_of_range(app_state, sample_pdf):
    """越界页码返回 400 而非 500。"""
    from services import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)

    from flask import Flask
    from routes import register_routes

    app = Flask(__name__)
    app.config["app_state"] = app_state
    app.config["TESTING"] = True
    register_routes(app)

    with app.test_client() as client:
        resp = client.post(f"/api/translate/{app_state.page_count}", json={})
        assert resp.status_code == 400
        data = json.loads(resp.data)
        assert data["error"] == "page out of range"

        resp = client.post("/api/translate/999", json={})
        assert resp.status_code == 400
        data = json.loads(resp.data)
        assert data["error"] == "page out of range"
```

- [ ] **Step 6: 运行全部测试，确认新测试失败、旧测试仍绿**

Run: `pytest tests/ -v`
Expected: 新增 4 个测试中至少 3 个 FAIL（渲染竞态、慢 IO 阻塞、越界页码 500）；并发 replace 测试可能 PASS（当前代码主锁覆盖全操作，序列化了并发）。旧 45 测试全部 PASS。

- [ ] **Step 7: Commit 失败特征测试**

```bash
git add tests/test_state.py tests/test_routes.py
git commit -m "test: add failing characterization tests for pdf state concurrency bugs"
```

---

### Task 2: 修复 render_page 渲染竞态

**Files:**
- Modify: `state.py:90-94`（`render_page` 方法）

**Interfaces:**
- Consumes: Task 1 的 `test_render_page_concurrent_replace_no_crash`
- Produces: `render_page` 全程持 `_lock`，渲染期间 doc 不会被并发 close/replace

- [ ] **Step 1: 修改 `state.py` 的 `render_page` 方法**

将 `state.py:90-94` 从：

```python
    def render_page(self, side: str, page_num: int, render_func, dpi: int) -> bytes:
        doc = self.get_doc(side)
        if doc is None:
            raise ValueError("no document opened")
        return render_func(doc, page_num, dpi)
```

改为：

```python
    def render_page(self, side: str, page_num: int, render_func, dpi: int) -> bytes:
        with self._lock:
            doc = self._left_doc if side == "left" else self._right_doc
            if doc is None:
                raise ValueError("no document opened")
            return render_func(doc, page_num, dpi)
```

- [ ] **Step 2: 运行渲染竞态测试，确认通过**

Run: `pytest tests/test_state.py::test_render_page_concurrent_replace_no_crash -v`
Expected: PASS

- [ ] **Step 3: 运行全部 state 测试，确认全绿**

Run: `pytest tests/test_state.py -v`
Expected: 全部 PASS（旧 6 个 + 新 3 个）

- [ ] **Step 4: Commit**

```bash
git add state.py
git commit -m "fix: hold _lock for entire render_page to prevent concurrent close race"
```

---

### Task 3: 修复 replace_page 锁内慢 IO 与并发损坏

**Files:**
- Modify: `state.py:11`（`__init__` 新增 `_write_lock`）
- Modify: `state.py:96-107`（`replace_page` 方法重构为双层锁）

**Interfaces:**
- Consumes: Task 1 的 `test_concurrent_replace_different_pages` 和 `test_slow_os_replace_does_not_block_reads`；Task 2 的 `render_page` 修复（确保 replace 期间 render 阻塞而非崩溃）
- Produces: `AppState._write_lock`（threading.Lock），`replace_page` 双层锁架构

- [ ] **Step 1: 在 `AppState.__init__` 新增 `_write_lock`**

将 `state.py:11` 从：

```python
        self._lock = threading.Lock()
```

改为：

```python
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
```

- [ ] **Step 2: 重构 `state.py` 的 `replace_page` 方法**

将 `state.py:96-107` 从：

```python
    def replace_page(self, translated_pdf_path: str, page_num: int) -> None:
        with self._lock:
            src_doc = pymupdf.open(translated_pdf_path)
            self._right_doc.delete_page(page_num)
            self._right_doc.insert_pdf(src_doc, start_at=page_num)
            tmp_save = self._right_pdf_path + ".tmp"
            self._right_doc.save(tmp_save)
            src_doc.close()
            self._right_doc.close()
            os.replace(tmp_save, self._right_pdf_path)
            self._right_doc = pymupdf.open(self._right_pdf_path)
            self._translated_pages.add(page_num)
```

改为：

```python
    def replace_page(self, translated_pdf_path: str, page_num: int) -> None:
        tmp_save = self._right_pdf_path + ".tmp"
        with self._lock:
            src_doc = pymupdf.open(translated_pdf_path)
            self._right_doc.delete_page(page_num)
            self._right_doc.insert_pdf(src_doc, start_at=page_num)
            self._right_doc.save(tmp_save)
            src_doc.close()
        with self._write_lock:
            try:
                os.replace(tmp_save, self._right_pdf_path)
            except FileNotFoundError:
                pass
        with self._lock:
            self._right_doc.close()
            self._right_doc = pymupdf.open(self._right_pdf_path)
            self._translated_pages.add(page_num)
```

> **设计说明**：`_right_doc` 在 `os.replace` 期间保持打开（design doc 关键决策）。`try/except FileNotFoundError` 处理并发场景：当 T2 的 `save(tmp)` 覆盖了 T1 的 tmp 后，T1 的 `os.replace` 消费 tmp，T2 的 `os.replace` 发现 tmp 已不存在——此时 right.pdf 已含最新内容（T2 的 save 写入了累积改动），跳过即可。加锁顺序始终 `_lock` → `_write_lock`，无反向获取，无死锁风险。

- [ ] **Step 3: 运行并发 replace 测试，确认通过**

Run: `pytest tests/test_state.py::test_concurrent_replace_different_pages -v`
Expected: PASS

- [ ] **Step 4: 运行慢 IO 不阻塞测试，确认通过**

Run: `pytest tests/test_state.py::test_slow_os_replace_does_not_block_reads -v`
Expected: PASS

- [ ] **Step 5: 运行全部 state 测试，确认全绿**

Run: `pytest tests/test_state.py -v`
Expected: 全部 PASS

- [ ] **Step 6: Commit**

```bash
git add state.py
git commit -m "fix: dual-layer lock for replace_page, move os.replace out of main lock"
```

---

### Task 4: 修复 translate_page 页码范围校验

**Files:**
- Modify: `routes.py:102-106`（`translate_page` 函数入口增加页码校验）

**Interfaces:**
- Consumes: Task 1 的 `test_translate_page_out_of_range`；`AppState.page_count` 属性（state.py:40-41）
- Produces: `translate_page` 入口校验 `0 <= page < state.page_count`

- [ ] **Step 1: 在 `routes.py` 的 `translate_page` 增加页码校验**

将 `routes.py:102-106` 从：

```python
@bp.route("/api/translate/<int:page>", methods=["POST"])
def translate_page(page: int):
    state = _get_state()
    if state.left_doc is None:
        return error_response("no document opened", 400)
```

改为：

```python
@bp.route("/api/translate/<int:page>", methods=["POST"])
def translate_page(page: int):
    state = _get_state()
    if state.left_doc is None:
        return error_response("no document opened", 400)
    if page < 0 or page >= state.page_count:
        return error_response("page out of range", 400)
```

- [ ] **Step 2: 运行越界页码测试，确认通过**

Run: `pytest tests/test_routes.py::test_translate_page_out_of_range -v`
Expected: PASS

- [ ] **Step 3: 运行全部 routes 测试，确认全绿**

Run: `pytest tests/test_routes.py -v`
Expected: 全部 PASS（旧 8 个 + 新 1 个）

- [ ] **Step 4: Commit**

```bash
git add routes.py
git commit -m "fix: validate page range in translate_page, return 400 for out-of-range"
```

---

### Task 5: 全量回归与 lint

**Files:**
- 无文件修改（仅验证）

**Interfaces:**
- Consumes: Task 2-4 的全部修复
- Produces: 全量验证通过

- [ ] **Step 1: 运行全部测试**

Run: `pytest tests/ -v`
Expected: 全部 PASS（旧 45 + 新 4 = 49 个测试）

- [ ] **Step 2: 运行 ruff lint**

Run: `ruff check`
Expected: 零错误

- [ ] **Step 3: 确认 requirements.lock 无变更**

Run: `git diff --name-only`
Expected: 无 `requirements.lock` 变更（本次未引入新依赖）

- [ ] **Step 4: 如有 lint 修复则提交**

```bash
git add -A
git commit -m "chore: lint cleanup for concurrency hardening"
```

（仅在有 lint 修复时执行；如 `ruff check` 已零错误则跳此步）
