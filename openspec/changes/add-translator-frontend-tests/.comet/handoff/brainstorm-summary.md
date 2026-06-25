# Brainstorm Summary

- Change: add-translator-frontend-tests
- Date: 2026-06-25

## Confirmed Technical Approach

方案 A：单文件运行器 `tests/run-translator-tests.mjs`，用 Node 动态 `import()` 加载被测 ES Module，依赖链（sse-client.js、stages.js）自然解析。从 `node:stream/web` 导入 `ReadableStream`/`TextDecoder` 并挂载到 `globalThis`。`fetch` 和 `Response` 用手写 mock。`stages.js` 的 `getStageLabel` 因 `_cache=null` 自动使用 `FALLBACK_LABELS` 兜底，无需额外 mock。手写 `assert()` + `passed/failed` 计数器 + 非零退出码。

Polyfill 清单：
- `ReadableStream` ← `node:stream/web`
- `TextDecoder` ← `node:stream/web`
- `fetch` ← 手写 mock（支持 body 验证 + 可控 ok/json）
- `Response` ← 手写 mock（包装 ReadableStream 作为 body）

## Key Trade-offs and Risks

- **跨 chunk 测试**：需要精确控制 chunk 边界，split 时有边界情况。测试通过分两次 enqueue 实现
- **stages.js _cache 访问**：不直接访问 `_cache`（模块私有）→ 依赖 `getStageLabel` 的 FALLBACK_LABELS 回退行为
- **SyntaxError 检测**：`readSSEStream` 的 catch 分支 `e instanceof SyntaxError` 在 jsdom vs Node 环境下行为一致（均使用原生 SyntaxError）
- **单文件长度**：预计 ~250 行，可读性可控

## Testing Strategy

- sse-client 4 测试：单 chunk 多事件、跨 chunk 拼接、非法 JSON 跳过、done 结束
- translator 5 测试：progress→finish 回调顺序、stage 无分段后缀、SSE error→onError、HTTP 非 ok→onError、prompt 透传 body
- 验证：退出码 0/1 语义、confirm 源码未改

## Spec Patches

为 delta spec 补充两个场景（边界条件）：
1. `readSSEStream` terminates gracefully when stream ends with no events
2. `translateCurrentPage` appends page segment suffix to stage label only when `stage_current > 0 && stage_total > 0`
