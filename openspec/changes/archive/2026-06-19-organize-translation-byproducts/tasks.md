## 1. 修改 services.py

- [x] 1.1 `build_settings()` 新增 `output_dir: str | None = None` 可选参数
- [x] 1.2 当 `output_dir` 不为 `None` 时，设置 `translation_kwargs["output"] = output_dir`

## 2. 修改 routes.py

- [x] 2.1 在 `translate_page()` 的 `generate()` 中创建一个专用临时目录用于翻译输出
- [x] 2.2 将该临时目录路径传入 `build_settings()` 的 `output_dir` 参数
- [x] 2.3 在 `finally` 块中清理该临时输出目录（与现有 `tmpdir` 清理并列，使用 `ignore_errors=True`）

## 3. 验证

- [x] 3.1 手动测试：翻译一张页面后确认根目录无副产物文件
- [x] 3.2 手动测试：翻译失败场景下确认临时输出目录已清理
- [x] 3.3 手动测试：翻译成功后右侧视图正确显示译文 PDF

<!-- code review: Ready to merge, no critical issues. 2 important (test gap per plan, unix path in test) — deferred/non-blocking. -->
