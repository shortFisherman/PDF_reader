# Verification Report: reading-position-resume

- Date: 2026-06-27
- Phase: verify
- Mode: full

## Summary

| Dimension    | Status           |
|--------------|------------------|
| Completeness | 22/22 tasks, 4 reqs, 11 scenarios |
| Correctness  | 4/4 reqs covered, 11/11 scenarios covered |
| Coherence    | Design followed |

## Completeness

### Task Completion

- tasks.md: 22/22 checkboxes ✅ (5 groups: state/routes/frontend-restore/frontend-save/quality)
- plan: all 5 task groups checked ✅

### Spec Coverage

4 requirements, 11 scenarios — all covered:

1. **Requirement: 服务端按 PDF 内容哈希持久化阅读页码** (3 scenarios) ✅
   - `state.py:65-142`: `_reading_progress_path`, `save_reading_progress`, `load_reading_progress`, `open_pdf` → `saved_page`
   - Scenario 自动恢复: `routes.py:36-47` + `static/app.js:114` ✅
   - Scenario 越界降级: `state.py:107-109` (clamp to 0) ✅  
   - Scenario 首次打开无默认: `state.py:96-100` (returns None) ✅

2. **Requirement: 前端在页面隐藏/卸载时上报当前页码** (3 scenarios) ✅
   - `static/app.js:118-119,122-125`: pagehide + visibilitychange listeners
   - `static/app.js:192-208`: saveProgress with guards
   - Scenario 关闭标签保存: sendBeacon + fetch keepalive ✅
   - Scenario 未开不发起: `!pageCount` guard ✅
   - Scenario 仅保存有效页码: `Number.isInteger + range check` ✅

3. **Requirement: 保存进度接口按 hash 越界校验** (3 scenarios) ✅
   - `routes.py:50-68`: POST /api/reading-progress with validation
   - Scenario 保存有效: 200, file written ✅
   - Scenario 未开拒绝: 400 "no document opened" ✅
   - Scenario 越界拒绝: 400 "page out of range" ✅

4. **Requirement: 恢复粒度与方式限定** (2 scenarios) ✅
   - Scenario 不重放缩放: zoom stays at 100% ✅
   - Scenario 无确认弹窗: auto-scroll, no dialog ✅

## Correctness

### Quality Gate

- `pytest -q`: **193 passed**, 0 failures
- `ruff check .`: **All checks passed**
- `ruff format --check .`: **33 files already formatted**

### Implementation Evidence

- Backend: `state.py` (3 new methods, `open_pdf` modified), `routes.py` (1 new route)
- Frontend: `static/app.js` (2 new functions, teardown integration)
- Tests: `tests/test_state.py` (+13 cases), `tests/test_routes.py` (+6 cases)
- Design doc manual verification notes archived ✅

## Coherence

### Design Adherence

| Decision | Implementation | Status |
|----------|---------------|--------|
| Storage: `cache_dir/<hash>/reading_progress.json` | `state.py:65-67` | ✅ |
| Atomic write: `.tmp` + `os.replace` | `state.py:82-89` | ✅ |
| load caller holds lock (non-reentrant) | `state.py:95-96` (no with self._lock) | ✅ |
| save self-locks | `state.py:70-71` (with self._lock) | ✅ |
| scrollIntoView for restore | `static/app.js:186-189` | ✅ |
| sendBeacon + fetch keepalive fallback | `static/app.js:192-208` | ✅ |
| pagehide + visibilitychange dual listener | `static/app.js:118-125` | ✅ |

### Cross-task Integration

- Task 1 → Task 2: `save_reading_progress` consumed by routes ✅
- Task 1 → Task 3: `saved_page` consumed by frontend ✅
- Task 2 → Task 4: `POST /api/reading-progress` consumed by saveProgress ✅
- All contracts matching (under_score field names, 0-based indices) ✅

## Assessment

**All checks passed. Ready for archive.**

- No CRITICAL or IMPORTANT issues
- Pre-existing SwigPy deprecation warnings only (not from this change)
- Final whole-branch review approved with minor style notes accepted
