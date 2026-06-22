# Brainstorm Summary

- Change: refactor-module-cohesion
- Date: 2026-06-22

## Confirmed Technical Approach

方案 A — 精准手术，逐组推进 + 逐组测试。

1. **拆分 services.py**：创建 file_hash.py、engine_resolver.py、pdf_renderer.py，删除 services.py
2. **抽取 translation_lifecycle.py**：从 sse_stream.generate() 分离后处理逻辑
3. **缩小接口**：GenerateContext 不传 AppState（改传 replace_page 回调 + glossary_cache_path），glossary_service 参数从 AppState 缩小为 Path
4. **消除 debug_trace.py 重复**：setup_file_handler/cleanup_file_handler 合并入 debug_session

## Key Trade-offs and Risks

- 风险：循环导入 → 缓解：单向依赖链（routes → lifecycle → state）
- 风险：测试 import 变化 → 缓解：逐组跑测试
- 权衡：render_page + build_settings 放同一个文件 vs 拆开 → 选了放一起（都依赖 pymupdf + pdf2zh_next）

## Testing Strategy

逐组验证：每完成一组任务后运行 pytest tests/ -v，全部通过才进入下一组。
最后运行 ruff check . 确认零错误。

## Spec Patches

None

## Confirmed Decisions

- 执行策略：逐组完成，每组跑测试
- 方案选择：方案 A（精准手术），而非方案 B（core/ 包结构）或 C（不拆文件）
