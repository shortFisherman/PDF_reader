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
