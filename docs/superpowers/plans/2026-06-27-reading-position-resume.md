---
change: reading-position-resume
design-doc: docs/superpowers/specs/2026-06-27-reading-position-resume-design.md
base-ref: c3107ab04dd0ea62e76de151b5303c9f9b7ae369
---

# reading-position-resume 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让本地 Flask PDF 阅读器在重新打开曾阅读的 PDF 时自动跳回上次页码，并在页面卸载时通过 `navigator.sendBeacon` 落盘当前页码。

**Architecture:** 进度按 PDF 内容哈希 (`pdf_hash`) 存放于服务端 `cache_dir/<pdf_hash>/reading_progress.json`（`{"page": <0-based int>}`），随文档缓存同目录、同生命周期。后端在 `AppState` 内新增读写方法（复用 `self._lock`）；`open_pdf` 响应追加 `saved_page`；新增 `POST /api/reading-progress` 接收前端卸载期上报。前端 `openPdf` 在 DOM 占位构建/Observer/PageDetection 装配后用 `requestAnimationFrame + scrollIntoView` 恢复定位；`pagehide`（主）+`visibilitychange`（兜底）触发 `navigator.sendBeacon` 上报；重开新文档时先解绑旧监听再注册新监听。

**Tech Stack:** Python 3 / Flask / pymupdf（后端 `state.py`、`routes.py`）；原生 ES Module JS（前端 `static/app.js`）；pytest（后端测试）；无前端测试框架（手动验证脚本）。

## Global Constraints

- 进度页码为 **0 基索引**，对应当前 `page_count`；越界 `>= page_count` 一律钳制/拒绝为 0。
- 进度文件路径固定为 `cache_dir/<pdf_hash>/reading_progress.json`，单字段 `{"page": int}`，无 schema 版本号。
- 日志沿用 `getLogger("pdf_reader.state")` / `getLogger("pdf_reader.routes")` 既有命名空间，不输出 api_key，`[progress]` 前缀内联拼入消息。
- 写进度必须在 `AppState._lock` 内、用 `tmp` + `os.replace` 原子替换，失败清理 tmp（与 `replace_page` 一致）。
- 仅页码粒度；不恢复缩放/页内偏移；不弹询问弹窗；仅卸载保存，切换文档不主动保存旧文档进度。
- 前端上报仅当 `pageCount > 0` 且 `currentPage ∈ [0, pageCount)` 时发起；后端再次校验文档已开 + 越界，双层守卫。
- `POST /api/reading-progress` 解析 `page` 非整数 → 400；文档未开 → 400 `"no document opened"`；越界 → 400 `"page out of range"`；成功 → `{"ok": true}` 200。
- 不新增 `GET /api/reading-progress`：`/api/open` 响应已携带 `saved_page`。

---

## 文件结构（新增/修改一览）

| 文件 | 职责 | 动作 |
|------|------|------|
| `state.py` | `AppState` 进度持久化读写 | Modify（新增 `_reading_progress_path`、`save_reading_progress`、`load_reading_progress`；修改 `open_pdf` 返回 dict） |
| `routes.py` | HTTP 接口 | Modify（新增 `POST /api/reading-progress`） |
| `static/app.js` | 打开后恢复定位 + 卸载期上报 + 监听 teardown | Modify（`openPdf` 内插入；新增 `scrollToPage`、`saveProgress`、监听注册/解绑） |
| `tests/test_state.py` | `AppState` 进度读写测试 | Modify（新增测试用例） |
| `tests/test_routes.py` | 路由接口测试 | Modify（新增测试用例） |
| `docs/superpowers/specs/2026-06-27-reading-position-resume-design.md` | 手动验证脚本归档 | Modify（第 7 节补"手动验证脚本已记录"备注，见 Task 5.3） |

**接口契约（跨任务约定）：**

- `state.py:AppState._reading_progress_path` → `Path | None`：私有方法，`self._pdf_hash is None` 时返回 `None`，否则返回 `self._cache_dir / self._pdf_hash / "reading_progress.json"`。
- `state.py:AppState.save_reading_progress(self, page: int) -> None`：抛 `ValueError("no document opened")` 或 `ValueError("page out of range")`。
- `state.py:AppState.load_reading_progress(self) -> int | None`：钳制后 int 或 `None`。
- `state.py:AppState.open_pdf(...)` 返回 dict 新增键 `saved_page: int | None`。
- `routes.py`：`POST /api/reading-progress`，body `{"page": int}`，成功 `{"ok": true}` 200；失败 400 `{"error": "no document opened" | "page out of range" | "invalid page"}`。
- 前端：`openPdf` 读取 `data.saved_page`；模块级 `let progressCleanup = null;`（或等价闭包）持有当前文档的卸载监听解绑函数；`scrollToPage(index)`、`saveProgress()` 为模块内函数。

---

## Task 1: 后端 state — 进度读写与 open_pdf 集成

**对应 spec requirement:** "服务端按 PDF 内容哈希持久化阅读页码"（全部三条 Scenario：自动恢复 / 越界降级 / 首次打开无默认页码）。

**对应 tasks.md:** 1.1 / 1.2 / 1.3 / 1.4 / 1.5 / 1.6。

**Files:**
- Modify: `state.py:9`（logger 已存在）、`state.py:58-62`（`glossary_cache_path` 之后插入新方法）、`state.py:64-96`（`open_pdf` 返回 dict 追加 `saved_page`）
- Test: `tests/test_state.py`（新增用例）
- 依赖：`tests/conftest.py` 既有 `sample_pdf`（2 页 PDF）、`app_state` fixtures，无需改动。

**Interfaces:**
- Consumes: `self._lock`、`self._pdf_hash`、`self._page_count`、`self._cache_dir`、`self._left_doc`（既有）。
- Produces: `_reading_progress_path() -> Path | None`、`save_reading_progress(page: int) -> None`、`load_reading_progress() -> int | None`；`open_pdf` 返回 dict 新增键 `saved_page: int | None`。

**完成判据：**
1. `AppState` 暴露上述三个方法，签名与契约一致。
2. `save_reading_progress(page)` 正常写入 `reading_progress.json`，内容 `{"page": <int>}`，写失败时 tmp 被清理且不残留半写。
3. `load_reading_progress()` 在文件缺失/JSON 损坏/缺 `page` 键/类型错误时返回 `None`（吞异常记 DEBUG），越界 `>= page_count` 钳制为 0，负值钳制为 0。
4. `open_pdf` 返回 dict 含 `saved_page`（无记录为 `None`，有记录为钳制后 int）。
5. `_close_docs` 不删除 `reading_progress.json`（进度文件与 `right.pdf` 独立）。
6. 日志命中 `[progress] save` / `[progress] load` 前缀，不输出敏感信息。
7. 新增测试全绿（`pytest tests/test_state.py -q`）。

- [x] **Step 1.1: 写失败测试（`save_reading_progress` 正常落盘）**

在 `tests/test_state.py` 末尾追加：

```python
def test_save_reading_progress_writes_file(app_state, sample_pdf):
    from file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)

    app_state.save_reading_progress(1)

    progress_file = app_state._reading_progress_path()
    assert progress_file is not None
    assert progress_file.exists()
    import json
    data = json.loads(progress_file.read_text(encoding="utf-8"))
    assert data == {"page": 1}
    app_state._close_docs()
```

- [x] **Step 1.2: 运行测试，确认失败**

Run: `pytest tests/test_state.py::test_save_reading_progress_writes_file -q`
Expected: FAIL — `AttributeError: 'AppState' object has no attribute '_reading_progress_path'`（或 `save_reading_progress`）。

- [x] **Step 1.3: 写失败测试（文档未开抛错 + 越界抛错 + 原子写 tmp 不残留）**

继续追加：

```python
def test_save_reading_progress_no_doc_raises(app_state):
    with pytest.raises(ValueError, match="no document opened"):
        app_state.save_reading_progress(0)


def test_save_reading_progress_out_of_range_raises(app_state, sample_pdf):
    from file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    page_count = app_state.page_count

    with pytest.raises(ValueError, match="page out of range"):
        app_state.save_reading_progress(-1)
    with pytest.raises(ValueError, match="page out of range"):
        app_state.save_reading_progress(page_count)
    app_state._close_docs()


def test_save_reading_progress_leaves_no_tmp_on_failure(app_state, sample_pdf):
    from file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)

    # 触发越界失败前/后，hash 目录下应无残留 .tmp 文件
    with pytest.raises(ValueError):
        app_state.save_reading_progress(9999)

    cache_subdir = app_state.glossary_cache_path
    tmp_files = list(cache_subdir.glob("reading_progress.json*"))
    assert all("tmp" not in str(p) for p in tmp_files)
    app_state._close_docs()
```

- [x] **Step 1.4: 运行测试，确认失败**

Run: `pytest tests/test_state.py -q -k save_reading_progress`
Expected: 4 个 FAIL（方法未实现）。

- [x] **Step 1.5: 写失败测试（`load_reading_progress`：命中/缺失/损坏/越界钳制/负值钳制）**

继续追加：

```python
def test_load_reading_progress_hit(app_state, sample_pdf):
    import json
    from file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)

    progress_file = app_state._reading_progress_path()
    progress_file.write_text(json.dumps({"page": 1}), encoding="utf-8")

    assert app_state.load_reading_progress() == 1
    app_state._close_docs()


def test_load_reading_progress_missing_returns_none(app_state, sample_pdf):
    from file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    assert app_state.load_reading_progress() is None
    app_state._close_docs()


def test_load_reading_progress_corrupt_returns_none(app_state, sample_pdf):
    from file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    progress_file = app_state._reading_progress_path()
    progress_file.write_text("{not valid json", encoding="utf-8")

    assert app_state.load_reading_progress() is None
    app_state._close_docs()


def test_load_reading_progress_missing_page_key_returns_none(app_state, sample_pdf):
    import json
    from file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    progress_file = app_state._reading_progress_path()
    progress_file.write_text(json.dumps({"other": 1}), encoding="utf-8")

    assert app_state.load_reading_progress() is None
    app_state._close_docs()


def test_load_reading_progress_out_of_range_clamped_to_zero(app_state, sample_pdf):
    import json
    from file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    page_count = app_state.page_count

    progress_file = app_state._reading_progress_path()
    progress_file.write_text(json.dumps({"page": page_count + 3}), encoding="utf-8")

    assert app_state.load_reading_progress() == 0
    app_state._close_docs()


def test_load_reading_progress_negative_clamped_to_zero(app_state, sample_pdf):
    import json
    from file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    progress_file = app_state._reading_progress_path()
    progress_file.write_text(json.dumps({"page": -5}), encoding="utf-8")

    assert app_state.load_reading_progress() == 0
    app_state._close_docs()
```

- [x] **Step 1.6: 运行测试，确认失败**

Run: `pytest tests/test_state.py -q -k load_reading_progress`
Expected: 6 个 FAIL（方法未实现）。

- [x] **Step 1.7: 写失败测试（`open_pdf` 响应含 `saved_page`）**

继续追加：

```python
def test_open_pdf_response_includes_saved_page_none(app_state, sample_pdf):
    from file_hash import sha256 as sha256_func

    result = app_state.open_pdf(str(sample_pdf), sha256_func)
    assert "saved_page" in result
    assert result["saved_page"] is None
    app_state._close_docs()


def test_open_pdf_response_includes_saved_page_value(app_state, sample_pdf):
    import json
    from file_hash import sha256 as sha256_func

    # 先打开写入进度
    app_state.open_pdf(str(sample_pdf), sha256_func)
    app_state.save_reading_progress(1)
    app_state._close_docs()

    # 重新打开，应读到保存的页
    result = app_state.open_pdf(str(sample_pdf), sha256_func)
    assert result["saved_page"] == 1
    app_state._close_docs()


def test_open_pdf_does_not_delete_progress_file(app_state, sample_pdf):
    import json
    from file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    app_state.save_reading_progress(1)
    progress_file = app_state._reading_progress_path()
    app_state._close_docs()

    # 再次打开（会 _close_docs 重置）后进度文件应仍在
    assert progress_file.exists()
    app_state.open_pdf(str(sample_pdf), sha256_func)
    assert progress_file.exists()
    app_state._close_docs()
```

- [x] **Step 1.8: 运行测试，确认失败**

Run: `pytest tests/test_state.py -q -k "open_pdf and saved_page or open_pdf does_not"`
Expected: 3 个 FAIL（`saved_page` 键不存在）。

- [x] **Step 1.9: 实现 `_reading_progress_path` / `save_reading_progress` / `load_reading_progress`**

在 `state.py` 的 `glossary_cache_path` property（第 58-62 行）之后、`open_pdf`（第 64 行）之前插入：

```python
    def _reading_progress_path(self) -> Path | None:
        if self._pdf_hash is None:
            return None
        return self._cache_dir / self._pdf_hash / "reading_progress.json"

    def save_reading_progress(self, page: int) -> None:
        with self._lock:
            if self._left_doc is None or self._pdf_hash is None:
                raise ValueError("no document opened")
            if not isinstance(page, int) or isinstance(page, bool):
                raise ValueError("page out of range")
            if page < 0 or page >= self._page_count:
                raise ValueError("page out of range")
            path = self._reading_progress_path()
            if path is None:
                raise ValueError("no document opened")
            tmp = path.with_suffix(path.suffix + ".tmp")
            try:
                import json
                tmp.write_text(json.dumps({"page": page}), encoding="utf-8")
                os.replace(tmp, path)
                logger.info("[progress] save hash=%s page=%d", self._pdf_hash, page)
            except Exception:
                if tmp.exists():
                    try:
                        tmp.unlink()
                    except OSError:
                        pass
                logger.error("[progress] save failed hash=%s page=%d", self._pdf_hash, page, exc_info=True)
                raise

    def load_reading_progress(self) -> int | None:
        with self._lock:
            path = self._reading_progress_path()
            if path is None or not path.exists():
                logger.debug("[progress] load hash=%s none", self._pdf_hash)
                return None
            try:
                import json
                data = json.loads(path.read_text(encoding="utf-8"))
                page = data["page"]
                if not isinstance(page, int) or isinstance(page, bool):
                    logger.debug("[progress] load hash=%s none (bad type)", self._pdf_hash)
                    return None
                if page >= self._page_count or page < 0:
                    logger.debug("[progress] load hash=%s clamp=%d", self._pdf_hash, page)
                    return 0
                logger.debug("[progress] load hash=%s page=%d", self._pdf_hash, page)
                return page
            except Exception:
                logger.debug("[progress] load hash=%s none (corrupt)", self._pdf_hash, exc_info=True)
                return None
```

> 注：`import json` 已在文件顶部需要；若文件顶部未 import json，请将其上提至 `import logging` 之后（见 Step 1.11）。`os` 已在顶部 import（第 2 行）。

- [x] **Step 1.10: 修改 `open_pdf` 返回 dict 追加 `saved_page`**

在 `state.py` 的 `open_pdf`（第 64-96 行）logger.info 调用之后、`return` 之前插入读取并入响应：

将现有 return 块（第 91-96 行）替换为：

```python
            saved_page = self.load_reading_progress()
            return {
                "page_count": self._page_count,
                "page_height": self._page_height,
                "page_width": self._page_width,
                "hash": pdf_hash,
                "saved_page": saved_page,
            }
```

> 注意：`load_reading_progress` 内部也 `with self._lock`，而 `open_pdf` 已持锁。`threading.Lock` 不可重入。因此需把 `load_reading_progress` 改为**不自行加锁**，由调用方持锁；或在 `open_pdf` 内内联读取逻辑。采用前者：见 Step 1.11 调整。

- [x] **Step 1.11: 调整锁策略（`load_reading_progress` 不自持锁，文档化调用方持锁）**

将 Step 1.9 中 `load_reading_progress` 的 `with self._lock:` 移除，改为在 docstring/调用约定说明"调用方必须持有 `self._lock`"：

```python
    def load_reading_progress(self) -> int | None:
        # Caller MUST hold self._lock (called from open_pdf which is already locked).
        path = self._reading_progress_path()
        if path is None or not path.exists():
            logger.debug("[progress] load hash=%s none", self._pdf_hash)
            return None
        try:
            import json
            data = json.loads(path.read_text(encoding="utf-8"))
            page = data["page"]
            if not isinstance(page, int) or isinstance(page, bool):
                logger.debug("[progress] load hash=%s none (bad type)", self._pdf_hash)
                return None
            if page >= self._page_count or page < 0:
                logger.debug("[progress] load hash=%s clamp=%d", self._pdf_hash, page)
                return 0
            logger.debug("[progress] load hash=%s page=%d", self._pdf_hash, page)
            return page
        except Exception:
            logger.debug("[progress] load hash=%s none (corrupt)", self._pdf_hash, exc_info=True)
            return None
```

并确保 `state.py` 顶部 import 区已含 `import json`（当前未 import，需加；放在 `import os` 之后）。

- [x] **Step 1.12: 运行全部新测试，确认通过**

Run: `pytest tests/test_state.py -q -k "reading_progress or saved_page or does_not_delete"`
Expected: PASS（13 个新增用例全绿）。

- [x] **Step 1.13: 运行整个 test_state.py 确认无回归**

Run: `pytest tests/test_state.py -q`
Expected: 全绿。

- [x] **Step 1.14: 提交**

```bash
git add state.py tests/test_state.py
git commit -m "feat(state): 按 pdf_hash 持久化阅读页码读写与 open_pdf 集成"
```

---

## Task 2: 后端 routes — `POST /api/reading-progress`

**对应 spec requirement:** "保存进度接口按 hash 越界校验"（全部三条 Scenario：保存有效 / 未打开文档拒绝 / 越界拒绝）。

**对应 tasks.md:** 2.1 / 2.2 / 2.3。

**Files:**
- Modify: `routes.py:36`（在 `open_pdf` 路由之后插入新路由）。logger 已在 `routes.py:23` 定义为 `logging.getLogger("pdf_reader.routes")`，沿用。
- Test: `tests/test_routes.py`（新增用例）。
- 依赖 Task 1 的 `AppState.save_reading_progress`。

**Interfaces:**
- Consumes: `state.save_reading_progress(page: int)`（抛 `ValueError`），`error_response(msg, code)`，`_get_state()`（既有）。
- Produces: `POST /api/reading-progress`，body `{"page": int}` → `{"ok": true}` 200；失败 400。

**完成判据：**
1. 路由解析 `request.get_json(silent=True)` 的 `page`；非整数（含缺失、bool、字符串）→ 400 `{"error": "invalid page"}`，**不写文件**。
2. `ValueError("no document opened")` → 400 `{"error": "no document opened"}`。
3. `ValueError("page out of range")` → 400 `{"error": "page out of range"}`。
4. 成功 → `{"ok": true}` 200，文件落盘且格式 `{"page": int}`。
5. 日志 `logger.debug("[route] save-reading-progress page=%d", page)`。
6. 不新增 `GET /api/reading-progress`。
7. `/api/open` 响应 schema 含 `saved_page`（随 Task 1 落地，本任务加断言固化）。
8. 新增测试全绿。

- [x] **Step 2.1: 写失败测试（成功 / 未开文档 / 越界 / 非整数 / 文件落盘）**

在 `tests/test_routes.py` 末尾追加：

```python
def test_open_response_includes_saved_page_key(app_state, sample_pdf):
    from file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    from flask import Flask
    from routes import register_routes

    app = Flask(__name__)
    app.config["app_state"] = app_state
    app.config["TESTING"] = True
    register_routes(app)

    with app.test_client() as client:
        # 重新打开（同 hash、同 state）读取 saved_page
        resp = client.post("/api/open", json={"path": str(sample_pdf)})
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "saved_page" in data
    app_state._close_docs()


def test_save_reading_progress_route_success(app_state, sample_pdf, tmp_path):
    from file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    from flask import Flask
    from routes import register_routes

    app = Flask(__name__)
    app.config["app_state"] = app_state
    app.config["TESTING"] = True
    register_routes(app)

    with app.test_client() as client:
        resp = client.post("/api/reading-progress", json={"page": 1})
        assert resp.status_code == 200
        assert json.loads(resp.data) == {"ok": True}

    progress_file = app_state._reading_progress_path()
    assert progress_file is not None and progress_file.exists()
    assert json.loads(progress_file.read_text(encoding="utf-8")) == {"page": 1}
    app_state._close_docs()


def test_save_reading_progress_route_no_doc():
    from flask import Flask
    from state import AppState
    from routes import register_routes

    app = Flask(__name__)
    app.config["app_state"] = AppState(Path("/tmp/cache_no_doc_routes"))
    app.config["TESTING"] = True
    register_routes(app)

    with app.test_client() as client:
        resp = client.post("/api/reading-progress", json={"page": 0})
        assert resp.status_code == 400
        assert json.loads(resp.data)["error"] == "no document opened"


def test_save_reading_progress_route_out_of_range(app_state, sample_pdf):
    from file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    page_count = app_state.page_count
    from flask import Flask
    from routes import register_routes

    app = Flask(__name__)
    app.config["app_state"] = app_state
    app.config["TESTING"] = True
    register_routes(app)

    with app.test_client() as client:
        resp = client.post("/api/reading-progress", json={"page": page_count})
        assert resp.status_code == 400
        assert json.loads(resp.data)["error"] == "page out of range"

        # 越界失败不应写文件
        assert not app_state._reading_progress_path().exists()
    app_state._close_docs()


def test_save_reading_progress_route_non_integer(app_state, sample_pdf):
    from file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    from flask import Flask
    from routes import register_routes

    app = Flask(__name__)
    app.config["app_state"] = app_state
    app.config["TESTING"] = True
    register_routes(app)

    with app.test_client() as client:
        for bad in [{"page": "x"}, {"page": True}, {}, {"page": 1.5}]:
            resp = client.post("/api/reading-progress", json=bad)
            assert resp.status_code == 400
            assert "error" in json.loads(resp.data)
        assert not app_state._reading_progress_path().exists()
    app_state._close_docs()
```

> 注：`test_save_reading_progress_route_no_doc` 用独立 `AppState`，cache 目录在测试中不会真创建；只要 `_left_doc is None` 即在 `save_reading_progress` 抛 `ValueError("no document opened")`，无需真实目录。

- [x] **Step 2.2: 运行测试，确认失败**

Run: `pytest tests/test_routes.py -q -k "save_reading_progress or open_response_includes_saved"`
Expected: FAIL — `404 Not Found`（路由未注册）或 `saved_page` 缺失。

- [x] **Step 2.3: 实现路由**

在 `routes.py` 的 `open_pdf` 路由函数（第 36-47 行）之后插入新路由：

```python
@bp.route("/api/reading-progress", methods=["POST"])
def save_reading_progress():
    data = request.get_json(silent=True) or {}
    page = data.get("page")
    if not isinstance(page, int) or isinstance(page, bool):
        logger.debug("[route] save-reading-progress invalid page=%r", page)
        return error_response("invalid page", 400)

    state = _get_state()
    try:
        state.save_reading_progress(page)
    except ValueError as e:
        msg = str(e)
        logger.debug("[route] save-reading-progress page=%d rejected: %s", page, msg)
        code = 400 if msg in ("no document opened", "page out of range") else 400
        return error_response(msg, code)

    logger.debug("[route] save-reading-progress page=%d", page)
    return jsonify({"ok": True})
```

> 注：`ValueError` 仅可能抛 `"no document opened"` 或 `"page out of range"`（Task 1 已保证），两者都映射 400；`ModelStateError` 分支保持简洁。非整数/bool 在进入 `state` 前已被拦截，仍返回 400 `"invalid page"`，避免写文件侧再校验 bool。

- [x] **Step 2.4: 运行测试，确认通过**

Run: `pytest tests/test_routes.py -q -k "save_reading_progress or open_response_includes_saved"`
Expected: PASS（5 个用例全绿）。

- [x] **Step 2.5: 运行整个 test_routes.py 确认无回归**

Run: `pytest tests/test_routes.py -q`
Expected: 全绿。

- [x] **Step 2.6: 提交**

```bash
git add routes.py tests/test_routes.py
git commit -m "feat(routes): 新增 POST /api/reading-progress 卸载期进度上报接口"
```

---

## Task 3: 前端 — 打开后恢复定位

**对应 spec requirement:** "服务端按 PDF 内容哈希持久化阅读页码" Scenario「打开曾阅读过的文档自动恢复页码」+「恢复粒度与方式限定」两条 Scenario（不重放缩放、无确认弹窗）。

**对应 tasks.md:** 3.1 / 3.2 / 3.3 / 3.4 / 3.5。

**Files:**
- Modify: `static/app.js:50-114`（`openPdf` 内，在 `setupPageDetection` 装配之后、`zoomInst = setupZoom(...)` 之前插入恢复定位调用）。
- Modify: `static/app.js`（新增模块级 `scrollToPage` 函数；建议放在 `onPageChange` 函数附近，第 170 行前后）。
- 无前端测试框架；手动验证脚本归档至 design.md（见 Task 5.3）。

**Interfaces:**
- Consumes: `data.saved_page`（来自 `/api/open` 响应，Task 1 产出）、`els.leftCol`、`pageCount`、既有 `setupPageDetection` 回调 `onPageChange`。
- Produces: 模块级 `scrollToPage(index: number): void`。

**完成判据：**
1. `openPdf` 在页占位 DOM 构建 + `setupIntersectionObserver` + `setupScrollSync` + `setupPageDetection` 装配完成后，读取 `data.saved_page`；为有效整数且 `> 0` 且 `< pageCount` 时，经由 `requestAnimationFrame` 调用 `scrollToPage(saved)` 定位左列。
2. `scrollToPage(index)` 取 `els.leftCol.querySelector('.page-container[data-page="<index>"]')`，命中则 `el.scrollIntoView({block:'start'})`；未命中静默返回不报错。
3. 定位后由现有 `setupPageDetection` settle 回调刷新 `currentPage` 与 `els.pageIndicator`，不手动设指示。
4. `saved_page` 为 `null` / `0` / 非整数 / 越界时不主动定位（停顶部首页），不报错、不弹窗。
5. 不恢复缩放（沿用 `zoomLevel.textContent = '100%'` 既有逻辑）。
6. 手动验证脚本通过（Task 5.3 执行）。

- [ ] **Step 3.1: 新增 `scrollToPage` 函数**

在 `static/app.js` 的 `onPageChange`（第 170 行）之前插入：

```javascript
function scrollToPage(index) {
    const el = els.leftCol.querySelector(`.page-container[data-page="${index}"]`);
    if (!el) return;
    el.scrollIntoView({ block: 'start' });
    // 页码指示由 setupPageDetection 的 settle 回调 onPageChange 刷新，无需手动设
}
```

- [ ] **Step 3.2: 在 `openPdf` 内装配恢复定位**

在 `static/app.js` 的 `openPdf` 中，把现有的装配序列尾部（第 100-108 行）

```javascript
        setupScrollSync({ left: els.leftCol, right: els.rightCol });
        setupPageDetection({ container: els.leftCol, settle }, onPageChange);
        zoomInst = setupZoom({
            columns: [els.leftCol, els.rightCol],
            appEl: els.appView,
            onZoomChange: z => { els.zoomLevel.textContent = Math.round(z * 100) + '%'; }
        });
        els.zoomLevel.textContent = '100%';
        loadTranslatedState();
```

替换为：

```javascript
        setupScrollSync({ left: els.leftCol, right: els.rightCol });
        setupPageDetection({ container: els.leftCol, settle }, onPageChange);
        zoomInst = setupZoom({
            columns: [els.leftCol, els.rightCol],
            appEl: els.appView,
            onZoomChange: z => { els.zoomLevel.textContent = Math.round(z * 100) + '%'; }
        });
        els.zoomLevel.textContent = '100%';
        loadTranslatedState();

        // 恢复定位：仅当 saved_page 为有效整数且 > 0（0 即首页，已在顶部无需滚动）
        const saved = Number.isInteger(data.saved_page) ? data.saved_page : null;
        if (saved !== null && saved > 0 && saved < pageCount) {
            requestAnimationFrame(() => scrollToPage(saved));
        }
```

> 注意命名：响应字段为 `data.saved_page`（下划线，与后端 dict 键一致），不是 `data.savedPage`。
> 关于 tasks.md 3.1 的 `[1, pageCount]` 描述：spec 为 0 基，恢复到首页（index=0）本身即在顶部，无需滚动；故判据采用 `saved > 0 && saved < pageCount`，等价于"定位到非首页的有效 0 基页码"。越界（`>= pageCount`）已由后端钳制，前端再守一道。

- [ ] **Step 3.3: 手动冒烟验证（先确认无语法错误）**

Run: 在浏览器开发者工具 Console 加载页面后，确认 `openPdf` 可正常打开一本首次打开的 PDF（`saved_page` 为 `null`），停在首页，无控制台报错；再打开一本此前已保存进度的 PDF（由 Task 4 写入），确认自动滚到该页、`page-indicator` 显示 `Page (saved+1)`。
（自动化留待 Task 5.3 手动脚本归档。）

- [ ] **Step 3.4: 提交**

```bash
git add static/app.js
git commit -m "feat(frontend): 打开后按 saved_page 自动恢复定位"
```

---

## Task 4: 前端 — 卸载期上报 + 监听 teardown

**对应 spec requirement:** "前端在页面隐藏/卸载时上报当前页码"全部三条 Scenario（关闭标签保存 / 未打开不发起 / 仅保存有效页码）。

**对应 tasks.md:** 4.1 / 4.2 / 4.3 / 4.4 / 4.5。

**Files:**
- Modify: `static/app.js:9-14`（新增模块级 `let progressCleanup = null;`）、`static/app.js:50-53`（`openPdf` 入口先解绑旧监听）、`static/app.js:108` 之后（装配完成后注册新监听）、`static/app.js` 新增 `saveProgress` 函数。
- 依赖 Task 2 的 `POST /api/reading-progress`。

**Interfaces:**
- Consumes: `currentPage`、`pageCount`（既有模块级变量）、`API`（既有 `/api`）、`navigator.sendBeacon`、`fetch`。
- Produces: 模块级 `progressCleanup: (() => void) | null`、`saveProgress()`。

**完成判据：**
1. `openPdf` 成功初始化后注册 `pagehide`（主）与 `visibilitychange`（`document.hidden` 兜底）两个监听，二者共用 `saveProgress`。
2. `saveProgress()`：仅当 `pageCount > 0` 且 `Number.isInteger(currentPage)` 且 `currentPage ∈ [0, pageCount)` 时上报；否则静默不发。
3. 上报优先 `navigator.sendBeacon('/api/reading-progress', json Blob)`；不可用时 `fetch(... {keepalive:true})` 兜底，`.catch(()=>{})` 吞错，不阻塞卸载、不依赖 Promise 解析。
4. 重开新文档（`openPdf` 入口）时先调用上一份 `progressCleanup` 解绑 `pagehide`/`visibilitychange`，避免累积绑定写旧 hash（**不**保存旧文档进度——解绑不触发 save）。
5. 无打开文档时触发卸载事件不发起请求（`pageCount === 0` 守卫）。
6. 当前页码非整数或越界时不发起请求。
7. 手动验证脚本通过（Task 5.3 执行）。

- [ ] **Step 4.1: 新增模块级 teardown 变量**

在 `static/app.js` 第 13 行 `let isTranslating = false;` 之后、第 17 行 `let els;` 区域内插入（与 `let io = null; let settle = null; let zoomInst = null;` 同组）：

```javascript
let progressCleanup = null;
```

具体：把第 17-20 行块

```javascript
let els;
let io = null;
let settle = null;
let zoomInst = null;
```

改为：

```javascript
let els;
let io = null;
let settle = null;
let zoomInst = null;
let progressCleanup = null;
```

- [ ] **Step 4.2: 新增 `saveProgress` 函数**

在 `static/app.js` 的 `scrollToPage`（Task 3.1 新增）之后插入：

```javascript
function saveProgress() {
    if (!pageCount || !Number.isInteger(currentPage)) return;
    if (currentPage < 0 || currentPage >= pageCount) return;
    const body = JSON.stringify({ page: currentPage });
    if (navigator.sendBeacon) {
        const blob = new Blob([body], { type: 'application/json' });
        navigator.sendBeacon(`${API}/reading-progress`, blob);
    } else {
        fetch(`${API}/reading-progress`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body,
            keepalive: true,
        }).catch(() => {});
    }
}
```

- [ ] **Step 4.3: `openPdf` 入口先解绑旧监听**

在 `static/app.js` 的 `openPdf` 入口（第 51-53 行）现有 teardown 序列

```javascript
    if (zoomInst) { zoomInst.dispose(); zoomInst = null; }
    if (io) { io.observer.disconnect(); io = null; }
    if (settle) { settle.dispose(); settle = null; }
```

之后追加：

```javascript
    if (progressCleanup) { progressCleanup(); progressCleanup = null; }
```

> 注：顺序上先解绑 progress 监听再走打开流程；此解绑**不**发起 save（仅 removeEventListener），符合"切档不保存"。

- [ ] **Step 4.4: `openPdf` 初始化完成后注册新监听**

在 `static/app.js` 的 `openPdf` 末尾（Task 3.2 新增的恢复定位块之后、函数 `} catch (e) {` 之前）插入：

```javascript
        // 卸载期上报：pagehide（主）+ visibilitychange hidden（兜底）
        function onPageHide() { saveProgress(); }
        function onVisibility() { if (document.hidden) saveProgress(); }
        window.addEventListener('pagehide', onPageHide);
        document.addEventListener('visibilitychange', onVisibility);
        progressCleanup = () => {
            window.removeEventListener('pagehide', onPageHide);
            document.removeEventListener('visibilitychange', onVisibility);
        };
```

- [ ] **Step 4.5: 手动冒烟验证**

1. 启动 app，打开一本 PDF，滚到第 8 页（0 基 index=7）。
2. 关闭标签页 → 观察 Network 面板有一次 `POST /api/reading-progress`（`sendBeacon` 类型，逐出后仍发送），body `{"page":7}`。
3. 重新打开 app，打开同一 PDF → 应自动滚到第 8 页，指示 `Page 8`。
4. 切换打开另一本 PDF → 不应出现旧文档的额外 save 请求（解绑不触发 save）。
5. 未打开文档时关闭标签 → 不发起请求。
6. 自动化归档见 Task 5.3。

- [ ] **Step 4.6: 提交**

```bash
git add static/app.js
git commit -m "feat(frontend): pagehide/visibilitychange 卸载期 sendBeacon 上报页码与监听 teardown"
```

---

## Task 5: 测试与质量校验

**对应 spec requirement:** 全部 4 条 requirement 的测试策略 + 第 7 节质量门。

**对应 tasks.md:** 5.1 / 5.2 / 5.3 / 5.4。

**Files:**
- `tests/test_state.py`（Task 1 已补全用例，本任务做全量回归确认）。
- `tests/test_routes.py`（Task 2 已补全用例，本任务做全量回归确认）。
- `docs/superpowers/specs/2026-06-27-reading-position-resume-design.md` 第 7 节（归档手动验证脚本）。

**完成判据：**
1. `tests/test_state.py` 涵盖 `save_reading_progress`（正常/未开/越界/原子）、`load_reading_progress`（命中/缺失/损坏/缺键/越界钳制/负值钳制）、`open_pdf`（响应含 `saved_page` / 不删进度文件）。
2. `tests/test_routes.py` 涵盖 `POST /api/reading-progress`（成功/未开/越界/非整数/文件落盘）、`/api/open` 响应含 `saved_page`。
3. 手动验证脚本已写入 design.md 第 7 节备注。
4. 质量门全绿：`ruff check .`、`ruff format --check .`、`pytest -q`。

- [ ] **Step 5.1: 确认 test_state.py 覆盖完整（已在 Task 1 写入）**

Run: `pytest tests/test_state.py -q -k "reading_progress or saved_page or does_not_delete"`
Expected: 全部 PASS（13 个用例）。

- [ ] **Step 5.2: 确认 test_routes.py 覆盖完整（已在 Task 2 写入）**

Run: `pytest tests/test_routes.py -q -k "save_reading_progress or open_response_includes_saved"`
Expected: 全部 PASS（5 个用例 + 1 个 open schema 用例 = 6 个）。

- [ ] **Step 5.3: 归档前端手动验证脚本至 design.md**

在 `docs/superpowers/specs/2026-06-27-reading-position-resume-design.md` 第 7 节"前端"小节的现有手动验证脚本列表之后追加一行备注：

```
> 已执行验证（实现期）：见 `docs/superpowers/plans/2026-06-27-reading-position-resume.md` Task 3.3 / Task 4.5 步骤；通过判定为左右列自动滚到目标页顶部、`page-indicator` 显示 `Page (saved_page+1)`；首次打开新 PDF 停首页；越界降级首页；切换文档无额外 save 请求、无控制台报错。
```

- [ ] **Step 5.4: 运行质量门**

Run（按 AGENTS.md 约定命令）：

```
ruff check .
ruff format --check .
pytest -q
```

Expected:
- `ruff check .` → All checks passed.
- `ruff format --check .` → 无需格式改动（若提示文件需格式化，执行 `ruff format <file>` 后重新 check，再 amend 提交或新提交）。
- `pytest -q` → 全绿（既有用例 + 19 个新增用例）。

- [ ] **Step 5.5: 提交**

```bash
git add docs/superpowers/specs/2026-06-27-reading-position-resume-design.md
git commit -m "docs(design): 归档断点恢复前端手动验证脚本执行备注"
```

若 Step 5.4 触发了格式化修复：

```bash
git add -A
git commit -m "style: ruff format 修正"
```

---

## Self-Review

**1. Spec 覆盖核对：**

- requirement「服务端按 PDF 内容哈希持久化阅读页码」→ 三 Scenario 由 Task 1（自动恢复=`open_pdf` 含 `saved_page` + `load_reading_progress` 命中）、Task 1（越界降级=`load_reading_progress` 钳制 0）、Task 1（首次打开无默认=`load_reading_progress` 缺失返回 `None` + `open_pdf` 返回 `None`）、Task 3（前端自动滚动 + 页码指示）覆盖。✅
- requirement「前端在页面隐藏/卸载时上报当前页码」→ 三 Scenario 由 Task 4（`pagehide`+`sendBeacon`）、Task 4（`pageCount===0` 守卫未开不发起）、Task 4（`currentPage ∈ [0,pageCount)` 守卫仅有效页码）覆盖。✅
- requirement「保存进度接口按 hash 越界校验」→ 三 Scenario 由 Task 2（成功 200 + 落盘）、Task 2（未开 400 `"no document opened"`）、Task 2（越界 400 `"page out of range"`）覆盖。✅
- requirement「恢复粒度与方式限定」→ 两 Scenario 由 Task 3（`scrollToPage` 仅滚动、不恢复缩放——`zoomLevel` 仍走既有 `100%`）、Task 3（无确认弹窗、可选短暂提示由既有 `pageIndicator` 承载）覆盖。✅

**2. 占位符扫描：** 无 "TODO/TBD/后续补" 等占位；前端手动验证脚本已在 Task 5.3 显式归档（项目无前端测试框架，符合 design 第 7 节既定策略，非占位）。✅

**3. 类型/命名一致性：**
- 后端：`save_reading_progress(page: int) -> None`、`load_reading_progress() -> int | None`、`_reading_progress_path() -> Path | None`、`open_pdf` 返回键 `saved_page`（下划线，全链一致）。✅
- 前端：响应字段读 `data.saved_page`（与后端 dict 键一致，非 camelCase）；函数 `scrollToPage`、`saveProgress`、变量 `progressCleanup` 在 Task 3/4 间一致。✅
- 路由路径：后端 `POST /api/reading-progress`、前端 `${API}/reading-progress`，一致。✅
- 锁约定：`load_reading_progress` 调用方持锁（`open_pdf` 内），`save_reading_progress` 自持锁——`threading.Lock` 不可重入，Task 1.11 已显式处理。✅

**4. 边界对齐：** tasks.md 3.1 写 `[1, pageCount]` 与 spec 0 基语义有歧义；Task 3.2 注释已说明采用 `saved > 0 && saved < pageCount`（0 即首页已在顶部无需滚动），等价覆盖且不违反 spec。✅

无遗漏，计划就绪。