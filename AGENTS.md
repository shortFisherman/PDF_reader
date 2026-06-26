<!-- CODEGRAPH_START -->
## CodeGraph

In repositories indexed by CodeGraph (a `.codegraph/` directory exists at the repo root), reach for it BEFORE grep/find or reading files when you need to understand or locate code:

- **MCP tools** (when available): `codegraph_explore` answers most code questions in one call — the relevant symbols' verbatim source plus the call paths between them. `codegraph_node` returns one symbol's source + callers, or reads a whole file with line numbers. If the tools are listed but deferred, load them by name via tool search.
- **Shell** (always works): `codegraph explore "<symbol names or question>"` and `codegraph node <symbol-or-file>` print the same output.

If there is no `.codegraph/` directory, skip CodeGraph entirely — indexing is the user's decision.
<!-- CODEGRAPH_END -->

## 日志约定 (Logging Conventions)

### Logger 命名空间
| Namespace | Module | Level Strategy |
|-----------|--------|---------------|
| `pdf_reader.app` | app.py | INFO startup summary |
| `pdf_reader.state` | state.py | INFO success / ERROR failure |
| `pdf_reader.render` | pdf_renderer.py | DEBUG only |
| `pdf_reader.extract` | pdf_extraction.py | DEBUG only |
| `pdf_reader.translate` | translation_orchestrator.py, sse_stream.py | INFO flow / ERROR exceptions / WARNING timeout / DEBUG token |
| `pdf_reader.lifecycle` | translation_lifecycle.py | INFO |
| `pdf_reader.glossary` | glossary_service.py | DEBUG resolve / WARNING failure |
| `pdf_reader.routes` | routes.py | DEBUG only |
| `pdf_reader.engine` | engine_resolver.py, translation_settings.py | INFO engine / DEBUG settings |
| `pdf_reader.debug_trace` | debug_trace.py | INFO flow skeleton / DEBUG details |

### 日志级别策略
- **ERROR**: 请求级失败，带 exc_info
- **WARNING**: 可恢复降级（超时、文件缺失）
- **INFO**: 流程里程碑常驻（开启、翻译、替换、合并完成）
- **DEBUG**: 高频/细节（渲染、抽取、token 用量、端点入口）

### page 关联前缀
- 翻译流日志自带 `[page=N]` 或 `[batch=from-to]` 前缀
- 由调用点在消息文本中内联拼入，formatter 不注入

### 配置入口
- `logging_config.setup_logging(debug)` 统一配置，替代以往的 `logging.basicConfig`
- `debug=True` → 根 logger 为 DEBUG，第三方 logger 降级为 DEBUG
- `debug=False` → 根 logger 为 INFO，第三方 logger 降级为 DEBUG

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
