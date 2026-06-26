<!-- CODEGRAPH_START -->
## CodeGraph

In repositories indexed by CodeGraph (a `.codegraph/` directory exists at the repo root), reach for it BEFORE grep/find or reading files when you need to understand or locate code:

- **MCP tools** (when available): `codegraph_explore` answers most code questions in one call — the relevant symbols' verbatim source plus the call paths between them. `codegraph_node` returns one symbol's source + callers, or reads a whole file with line numbers. If the tools are listed but deferred, load them by name via tool search.
- **Shell** (always works): `codegraph explore "<symbol names or question>"` and `codegraph node <symbol-or-file>` print the same output.

If there is no `.codegraph/` directory, skip CodeGraph entirely — indexing is the user's decision.
<!-- CODEGRAPH_END -->

## 日志约定 (Logging Conventions)

新模块写日志前先看 `logging_config.py` / `debug_trace.py` 顶部的 `getLogger("pdf_reader.<concern>")` 命名空间分配，沿用同款命名。

### 级别策略
- **ERROR**: 请求级失败，带 exc_info
- **WARNING**: 可恢复降级（超时、文件缺失）
- **INFO**: 流程里程碑常驻（开启、翻译、替换、合并完成）
- **DEBUG**: 高频/细节（渲染、抽取、token 用量、端点入口）

### page 关联前缀
- 翻译流日志自带 `[page=N]` 或 `[batch=from-to]` 前缀
- 由调用点在消息文本中内联拼入，formatter 不注入

### 安全
- 日志中不输出 api_key 原值
- settings 摘要只取 provider/model/lang/path 等安全字段
- API Key 用 `config.MODEL_API_KEY` 访问，不在日志中插值

### 命令
```powershell
ruff check .          # lint
ruff format --check . # 格式检查
pytest -q             # 全量测试
```
