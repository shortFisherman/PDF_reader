---
comet_change: extract-translation-service-layer
role: technical-design
canonical_spec: openspec
---

# Design: Extract Translation Service Layer

## Problem

`routes.py:translate_page`（102-336 行）是 230 行巨函数，揉合 6 类职责：请求解析、单页 PDF 抽取（pymupdf）、翻译编排（asyncio 线程 + 事件队列）、SSE 事件格式化、调试追踪日志（`if config.DEBUG` 散落 20+ 处）、术语表路径解析与合并、临时目录清理。路由层本应薄，现在却承担业务编排，导致难以测试、难以扩展、难以阅读。

## Architecture: Function-Oriented Service Modules

5 个顶层平铺 service 模块（与现有 `services.py`、`glossary_merger.py`、`state.py` 同级），每个模块暴露纯函数，无类样板代码。`sse_stream.generate` 作为组合中心，接收 `GenerateContext` dataclass 打包参数。

### 模块接口

#### `pdf_extraction.py`

```python
def extract_single_page(src_doc: pymupdf.Document, page_num: int, tmpdir: Path) -> Path:
    """从 src_doc 抽取 page_num 页为 tmpdir/page.pdf，返回路径。
    调用方负责 tmpdir 清理。迁移 routes.py:117-120 的 pymupdf.open + insert_pdf + save 逻辑。"""
```

#### `translation_orchestrator.py`

```python
class TranslationError(Exception):
    """翻译过程中发生的错误。"""

def run_translation(settings, pdf_path: str) -> Iterator[dict]:
    """在后台 asyncio 线程中运行翻译，同步迭代器产出事件。
    封装 asyncio 线程 + 事件队列（routes.py:172-204）。
    _done 信号变为内部实现细节，不再暴露给调用方。
    线程异常在迭代结束后通过 raise TranslationError 传播（替代 error_info 字符串）。"""
```

关键实现细节：
- 后台线程创建 `asyncio.new_event_loop()`，运行 `do_translate_async_stream`，事件放入 `queue.Queue`
- 主线程同步迭代从队列取事件，`timeout=1.0` 时 yield 空字符串保持连接
- 线程结束后队列放入 `{"type": "_done"}` 内部信号，迭代器检测到后停止
- 若线程设置了 `error_info`，迭代器在停止前 `raise TranslationError(error_info)`
- `finally` 块确保 loop 正确关闭（cancel pending tasks + close）

#### `sse_stream.py`

```python
STAGE_LABELS = {
    "layout_analysis": "正在分析版面…",
    "translating": "正在翻译…",
    "generating_pdf": "正在生成译文…",
    "generating_pdf_bilingual": "正在生成译文…",
    "finish": "翻译完成",
}  # 从 routes.py:32-38 迁移

@dataclass
class GenerateContext:
    settings: SettingsModel
    single_page_pdf: Path
    state: AppState
    page: int
    glossary_paths: list[str] | None
    tmpdir: Path
    output_dir: str

def format_sse_event(evt: dict) -> str | None:
    """纯函数：将翻译事件 dict 转为 data: {json}\\n\\n 字符串。
    返回 None 表示无 SSE 输出（如 _done 内部信号）。
    事件类型映射：
      progress_start  → data: {"type":"progress","progress":0,...}\\n\\n
      progress_update → data: {"type":"progress","progress":overall_progress,...}\\n\\n
      finish          → data: {"type":"progress","progress":95,...}\\n\\n
      error           → data: {"type":"error","error":...}\\n\\n
      _done           → None
    字节级兼容现状输出。"""

def generate(ctx: GenerateContext) -> Iterator[str]:
    """组合中心：orchestrator 事件 → SSE 格式化 → 后处理 → finish。
    统一错误捕获 + 临时文件清理。"""
```

`generate` 的执行流程：
1. `debug_trace.setup_file_handler(state.glossary_cache_path, page)` 设置调试日志
2. `orchestrator = translation_orchestrator.run_translation(ctx.settings, str(ctx.single_page_pdf))`
3. 迭代 orchestrator 事件：
   - `finish` 事件：收集 `translate_result` 和 `token_usage`
   - `format_sse_event(evt)` 格式化，非 None 则 yield
   - `error` 事件：yield 后 return
4. 后处理：
   - `translated_pdf = translate_result.mono_pdf_path or translate_result.dual_pdf_path`
   - `state.replace_page(translated_pdf, page)`
   - `glossary_service.merge_after_translate(state.glossary_cache_path, translate_result.auto_extracted_glossary_path)`
   - `debug_trace.log_step("translate page %d done", page)` + `debug_trace.log_token_usage(token_usage)`
5. yield progress 100 + finish 事件
6. `except TranslationError as e`: yield error 事件
7. `except Exception as e`: yield error 事件
8. `finally`: `debug_trace.cleanup_file_handler(handler)` + `shutil.rmtree(tmpdir)` + `shutil.rmtree(output_dir)`

#### `glossary_service.py`

```python
def resolve_glossary_paths(state: AppState) -> list[str] | None:
    """翻译前解析累积术语表路径。
    若 state.glossary_cache_path / "cumulative_glossary.csv" 存在且非空，返回 [path]；
    否则返回 None。迁移 routes.py:124-129。"""

def merge_after_translate(cumulative_path: Path | None, auto_extracted_path: Path | None) -> None:
    """翻译后合并自动提取的术语表到累积术语表。
    委托 glossary_merger.merge_glossary_csvs。
    失败仅记日志不抛异常（保持 routes.py:303-310 现状行为）。"""
```

#### `debug_trace.py`

```python
trace_logger = logging.getLogger("pdf_reader.debug_trace")
trace_logger.setLevel(logging.INFO)
# handler 初始化保持现状

def log_step(step: str, *args) -> None:
    """if config.DEBUG: trace_logger.info(f"[step] {step}", *args)
    骨架委托，变更 D 优化。"""

def setup_file_handler(glossary_path: Path | None, page: int) -> logging.FileHandler | None:
    """创建/轮转 debug_trace.log，返回 handler 供清理。
    迁移 routes.py:134-152 的 FileHandler 逻辑。
    骨架实现保持现状行为，变更 D 优化。"""

def cleanup_file_handler(handler: logging.FileHandler | None) -> None:
    """移除并关闭 file handler。迁移 routes.py:318-324。"""

def log_token_usage(token_usage: dict) -> None:
    """记录 token 用量。迁移 routes.py:265-271。骨架委托。"""
```

### 路由层薄化

```python
@bp.route("/api/translate/<int:page>", methods=["POST"])
def translate_page(page: int):
    state = _get_state()
    if state.left_doc is None:
        return error_response("no document opened", 400)
    if page < 0 or page >= state.page_count:
        return error_response("page out of range", 400)

    data = request.get_json(silent=True) or {}
    user_prompt = (data.get("prompt") or "").strip() or None

    tmpdir = Path(tempfile.mkdtemp())
    output_dir = tempfile.mkdtemp(dir=str(config.CACHE_DIR))
    single_page_pdf = pdf_extraction.extract_single_page(state.left_doc, page, tmpdir)
    glossary_paths = glossary_service.resolve_glossary_paths(state)
    settings = build_settings(str(single_page_pdf), user_prompt, output_dir=output_dir, glossary_paths=glossary_paths, debug=config.DEBUG)

    ctx = sse_stream.GenerateContext(
        settings=settings, single_page_pdf=single_page_pdf, state=state,
        page=page, glossary_paths=glossary_paths, tmpdir=tmpdir, output_dir=output_dir,
    )
    return Response(stream_with_context(sse_stream.generate(ctx)), mimetype="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
```

函数体 ≤ 20 行（不含装饰器和签名），远低于 40 行目标。`STAGE_LABELS` 和 `trace_logger` 从 routes.py 迁移到各自模块。

## Error Handling Strategy

| 错误来源 | 处理方式 |
|---------|---------|
| 翻译线程异常 | orchestrator 在迭代结束后 `raise TranslationError`，generate 捕获 → SSE error 事件 |
| 翻译引擎 yield error 事件 | `format_sse_event` 格式化为 SSE error，generate yield 后 return |
| `translate_result is None` | generate 检查后 yield error 事件 |
| `translated_pdf is None` | generate 检查后 yield error 事件 |
| `replace_page` 异常 | generate `except Exception` 捕获 → SSE error 事件 |
| glossary merge 异常 | `glossary_service.merge_after_translate` 内部捕获，仅记日志（保持现状，不抛异常） |

错误传播模式：service 层抛异常，`generate` 统一捕获并格式化为 SSE error 事件。glossary merge 是唯一例外（吞掉仅记日志，保持现状行为）。

## Testing Strategy

| 模块 | 测试方式 |
|-----|---------|
| `sse_stream.format_sse_event` | 纯函数测试：给定事件 dict，断言输出字节匹配黄金样本 |
| `translation_orchestrator.run_translation` | mock `do_translate_async_stream` 返回事件序列，断言迭代器顺序、TranslationError 传播、loop 正确关闭 |
| `pdf_extraction.extract_single_page` | 真实小 PDF，断言产出 PDF 页数=1 |
| `glossary_service.resolve_glossary_paths` | 路径解析（有/无累积文件） |
| `glossary_service.merge_after_translate` | 合并调用委托 `merge_glossary_csvs`，异常不抛出 |
| `debug_trace.log_step` | DEBUG=True/False 时的行为 |
| `debug_trace.setup_file_handler`/`cleanup_file_handler` | FileHandler 创建/清理 |
| `sse_stream.generate` | mock orchestrator + state，断言 SSE 流字节级匹配黄金样本 |
| `translate_page` 路由 | mock 各 service，断言 SSE 流字节级匹配 + 路由 ≤ 40 行 |

**黄金样本基线**（tasks.md 步骤 1）：先在现状代码上捕获 `translate_page` SSE 输出（progress_start/update/finish/error 各类事件）的期望字节串作为黄金样本，拆分后验证字节级一致。

**回归保护**：现有测试（`test_routes.py`、`test_state.py`、`test_services.py`、`test_glossary_merger.py`）保持通过。`test_translate_page_integrates_cumulative_glossary` 需更新 mock 路径（从 `routes.build_settings` 改为 mock 新模块）。

## Dependencies

- 依赖变更 A（harden-pdf-state-concurrency）已归档完成的并发修复（`state.replace_page` 全程持锁 + 页码校验）
- `debug_trace` 骨架接口与变更 D（isolate-debug-tracing）协同：本变更建骨架，变更 D 负责实现优化
- `STAGE_LABELS` 与变更 E（modularize-frontend）共享对齐：前端和后端不重复定义 stage 标签

## Risks / Trade-offs

- [SSE 事件顺序错位] → `format_sse_event` 字节级回归测试 + 黄金样本捕获
- [asyncio 线程边界事件丢失] → orchestrator 测试覆盖 TranslationError 传播 + loop 正确关闭
- [generate 参数较多] → `GenerateContext` dataclass 打包，避免函数签名过长
- [debug_trace 骨架与变更 D 耦合] → 本变更建骨架接口 + 简单委托，变更 D 负责优化
- [临时文件清理] → generate 的 finally 块统一清理 tmpdir + output_dir（与现状一致）
- [现有测试 mock 路径失效] → 更新 `test_translate_page_integrates_cumulative_glossary` 的 mock 路径

## Spec Patches

补充 `translation-service-layer/spec.md` 一个 scenario：

```markdown
#### Scenario: Translation error propagation
- **WHEN** the translation engine raises an exception or yields an error event
- **THEN** the orchestrator SHALL propagate the error to the SSE stream as an error event, and the route SHALL NOT crash
```
