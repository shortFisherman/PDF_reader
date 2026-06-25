# Task 3 Report: finish_translation 移除 tmpdir/output_dir 参数和 rmtree 调用

## Status: COMPLETE

## Summary

Removed `tmpdir: Path` and `output_dir: str` parameters from `finish_translation()`, along with the two `shutil.rmtree()` lines and the `import shutil` statement. Cleanup responsibility is now fully consolidated in `sse_stream.generate()`'s `finally` block (Task 2).

## Changes Made

**File**: `translation_lifecycle.py`

| Change | Detail |
|--------|--------|
| Removed import | `import shutil` |
| Removed parameters | `tmpdir: Path`, `output_dir: str` |
| Removed cleanup lines | `shutil.rmtree(tmpdir, ignore_errors=True)` |
| | `shutil.rmtree(output_dir, ignore_errors=True)` |
| Function signature | 5 params -> 3 params |

## TDD Evidence

- Ran `pytest tests/test_services.py -q` **after** the change: **24 passed**
- The call site in `sse_stream.py:115-119` already passes only 3 arguments (confirming Task 2 is complete)
- No new tests needed — this is a pure removal of dead code; existing tests cover `finish_translation` behavior and continue to pass

## Test Results

```
24 passed in 0.09s
```

No regressions.

## Commit

```
f634234 refactor(translation_lifecycle): remove tmpdir/output_dir cleanup, now in generate() finally
```

## Concerns

None.
