# pdf2zh-next 开发参考

> [!IMPORTANT]
> **版本适用范围。** 本文主体是 2026-06-19 对 pdf2zh-next 2.8.2 的源码研究快照；当前项目锁定 pdf2zh-next 2.9.0 和 BabelDOC 0.6.2。本文用于理解上游接口与内部机制，不是本项目当前架构的事实源。涉及集成改动时，必须同时核对 `requirements.lock`、当前安装源码和 [项目当前架构](architecture.md)。

> 基于 pdf2zh-next v2.8.2 源码阅读。pdf2zh-next 是 BabelDOC 的官方参考实现和公开包装层，把 BabelDOC 的 Internal API 封装为稳定、可取消、带缓存的 Python 接口。
>
> 仓库：`C:\Users\Couper\project_from_git\pdf2zh-next`

---

## 一、它是什么

pdf2zh-next 是一层薄封装，自己不实现翻译管道。它做的事：

1. **翻译引擎适配** — 22 种 LLM/翻译服务统一为 `BaseTranslator` 接口，多数通过 OpenAI 兼容协议桥接
2. **进程隔离** — 默认在子进程运行 BabelDOC，崩溃不拖垮主进程，支持取消
3. **翻译缓存** — 段落级 SQLite 缓存，避免重复 API 调用
4. **配置分层** — TOML 文件 → 环境变量 → CLI 参数 → Python API 参数，四层优先级
5. **进度流** — 异步生成器逐事件推送翻译进度
6. **术语表 / 自动术语提取** — 交给 BabelDOC 执行，自己只管传参

依赖关系：
```
pdf2zh-next (本仓库)
    ├── babeldoc >= 0.5.20, < 0.6.0    # 底层翻译引擎
    ├── pymupdf < 1.25.3                # PDF 读写
    ├── openai >= 1.0.0                 # LLM 调用
    ├── peewee >= 3.17.8                # SQLite ORM（缓存）
    ├── pydantic >= 2.10.6              # 配置模型
    ├── gradio < 5.36                   # WebUI
    ├── tenacity                        # 重试策略
    └── ...
```

---

## 二、包结构

```
pdf2zh_next/
├── __init__.py          # 公开 API 导入点
├── high_level.py        # ★ 核心：do_translate_async_stream / do_translate_file / do_translate_file_async
├── main.py              # CLI 入口（pdf2zh 命令）
├── gui.py               # Gradio WebUI ~2000 行
├── http_api.py          # 空文件（未实现）
├── i18n.py              # Gradio 多语言钩子
├── const.py             # 配置路径常量
│
├── config/
│   ├── model.py                    # SettingsModel + 子模型（PDF/Translation/Basic/GUI）
│   ├── translate_engine_model.py   # 22 种翻译引擎的 Pydantic Settings（1104 行，核心复杂性所在）
│   ├── cli_env_model.py            # CLI/ENV 参数的中间 Pydantic 模型
│   ├── main.py                     # ConfigManager 单例，CLI+ENV+TOML 三层合并
│   └── __init__.py                 # 重导出
│
├── translator/
│   ├── base_translator.py          # BaseTranslator 抽象基类
│   ├── base_rate_limiter.py        # BaseRateLimiter 抽象基类
│   ├── cache.py                    # TranslationCache（SQLite + peewee）
│   ├── utils.py                    # get_translator() / get_term_translator() 工厂
│   ├── rate_limiter/
│   │   └── qps_rate_limiter.py     # QPSRateLimiter 令牌桶
│   └── translator_impl/            # 16 个具体 Translator 实现
│       ├── openai.py               # OpenAITranslator（★ 多数后端的最终执行者）
│       ├── google.py / deepl.py / bing.py / ollama.py / xinference.py
│       ├── azure.py / azureopenai.py / gemini.py / grok.py / groq.py
│       ├── tencentmechinetranslation.py / siliconflow.py / siliconflowfree.py
│       ├── anythingllm.py / dify.py / qwenmt.py
│       ├── claudecode.py           # 调用 claude CLI
│       └── clitranslator.py        # 调用任意外部命令
│
└── utils/
    └── asynchronize/
        └── __init__.py             # AsyncCallback（同步 Pipe → AsyncGenerator 桥）
```

---

## 三、公开 Python API

### 3.1 三个入口函数

全部在 `pdf2zh_next/__init__.py` 中导出，也是 `pdf2zh_next/high_level.py` 中定义的。

| 函数 | 签名 | 用途 |
|------|------|------|
| `do_translate_async_stream` | `async (settings: SettingsModel, file: Path\|str) -> AsyncGenerator[dict, None]` | **最底层 API**，逐事件流式返回，翻译单个文件 |
| `do_translate_file_async` | `async (settings: SettingsModel, ignore_error: bool = False) -> int` | 批量翻译 `settings.basic.input_files` 中全部文件，内置 rich 进度条，返回错误数 |
| `do_translate_file` | `(settings: SettingsModel, ignore_error: bool = False) -> int` | `do_translate_file_async` 的同步包装（内部 `asyncio.run`） |

另有辅助函数 `create_babeldoc_config(settings, file) -> BabelDOCConfig`，将 `SettingsModel` 转换为 BabelDOC 能识别的配置对象，在需要调试或直接调用 BabelDOC 时使用。

### 3.2 事件协议

`do_translate_async_stream` 的 `AsyncGenerator` 逐次 yield 以下事件 dict：

```python
# 阶段开始
{"type": "progress_start", "stage": "layout_analysis", "overall_progress": 0.0,
 "part_index": 1, "total_parts": 1, "stage_current": 0, "stage_total": 10}

# 进度更新
{"type": "progress_update", "stage": "translating", "overall_progress": 45.0,
 "part_index": 1, "total_parts": 1, "stage_current": 5, "stage_total": 10}

# 阶段结束
{"type": "progress_end", "stage": "layout_analysis", "overall_progress": 20.0}

# 翻译完成（★ 最后且最重要的事件）
{"type": "finish", "translate_result": TranslateResult(...), "token_usage": {...}}
# TranslateResult 属性：
#   .mono_pdf_path: str | None     纯译文 PDF
#   .dual_pdf_path: str | None     双语对照 PDF
#   .original_pdf_path: str
#   .total_seconds: float          耗时
#   .auto_extracted_glossary_path: str | None  自动提取的术语表 CSV

# 错误
{"type": "error", "error": "描述信息", "error_type": "BabeldocError", "details": "..."}
```

### 3.3 异常体系

```python
TranslationError (基类，pickleable)
├── BabeldocError(TranslationError)
│       .original_error   # 原始错误信息
│       # 子进程中 BabelDOC 内部抛出的异常
├── SubprocessError(TranslationError)
│       .raw_message      # 错误消息
│       .traceback_str    # 完整 traceback 字符串
│       # 子进程中 BabelDOC 之外的 Python 异常
├── IPCError(TranslationError)
│       .details          # 额外细节
│       # Pipe 通信中断、意外消息类型
└── SubprocessCrashError(TranslationError)
        .exit_code        # 退出码
        # 子进程非零退出，且未通过 Pipe 发送错误
```

### 3.4 最基本调用示例

```python
import asyncio
from pdf2zh_next import SettingsModel, PDFSettings, TranslationSettings, do_translate_async_stream
from pdf2zh_next.config.translate_engine_model import DeepSeekSettings

async def main():
    settings = SettingsModel(
        translation=TranslationSettings(
            lang_in="en",
            lang_out="zh",
        ),
        pdf=PDFSettings(),
        translate_engine_settings=DeepSeekSettings(
            deepseek_api_key="sk-xxx",
        ),
    )
    async for event in do_translate_async_stream(settings, "document.pdf"):
        if event["type"] == "finish":
            print(event["translate_result"].mono_pdf_path)
        elif event["type"] == "error":
            print(f"Error: {event['error']}")

asyncio.run(main())
```

---

## 四、配置模型

### 4.1 SettingsModel 结构

```python
SettingsModel(
    basic: BasicSettings                     # 基础设置
    translation: TranslationSettings         # 翻译设置
    pdf: PDFSettings                         # PDF 处理设置
    gui_settings: GUISettings                # GUI 设置
    translate_engine_settings: Union[22种引擎Setting]  # 翻译引擎
    term_extraction_engine_settings: Union[|None]      # 术语提取引擎（可选，默认跟随主引擎）
    report_interval: float = 0.1             # 进度上报间隔（秒）
    config_file: str | None = None           # 指定配置文件的路径
)
```

### 4.2 TranslationSettings 字段

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `lang_in` | `str` | `"en"` | 源语言代码 |
| `lang_out` | `str` | `"zh"` | 目标语言代码 |
| `output` | `str\|None` | `None` | 输出目录，None=当前工作目录 |
| `qps` | `int` | `4` | 翻译 QPS 限制 |
| `ignore_cache` | `bool` | `False` | 为 True 时跳过 SQLite 缓存，强制重新调用 API |
| `custom_system_prompt` | `str\|None` | `None` | 自定义系统提示词，替换 LLM system prompt |
| `glossaries` | `str\|None` | `None` | 术语表 CSV 路径，逗号分隔多个文件 |
| `min_text_length` | `int` | `5` | 短于此字符数的文本不翻译 |
| `pool_max_workers` | `int\|None` | `None` | 翻译线程池大小，None 时自动跟随 qps |
| `no_auto_extract_glossary` | `bool` | `False` | True=禁用 LLM 自动术语提取 |
| `save_auto_extracted_glossary` | `bool` | `False` | True=保存自动提取的术语表 CSV |
| `primary_font_family` | `str\|None` | `None` | 强制字体族：`"serif"` / `"sans-serif"` / `"script"` |
| `term_qps` | `int\|None` | `None` | 术语提取引擎 QPS，None 时跟随 `qps` |
| `term_pool_max_workers` | `int\|None` | `None` | 术语提取线程池，None 时跟随 `pool_max_workers` |
| `rpc_doclayout` | `str\|None` | `None` | 远程版面检测 RPC 服务地址 |

### 4.3 PDFSettings 字段

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `pages` | `str\|None` | `None` | 页码范围，如 `"1,3,5-10"`，None=全部 |
| `no_dual` | `bool` | `False` | 不输出双语对照 PDF |
| `no_mono` | `bool` | `False` | 不输出纯译文 PDF |
| `only_include_translated_page` | `bool` | `False` | ★ 输出 PDF 只包含翻译过的页（不包含未翻译页） |
| `watermark_output_mode` | `str` | `"watermarked"` | `"watermarked"` / `"no_watermark"` / `"both"` |
| `max_pages_per_part` | `int\|None` | `None` | 大 PDF 切片翻译，每份最多 N 页 |
| `translate_table_text` | `bool` | `True` | 是否翻译表格内的文本（会加载 RapidOCR） |
| `skip_clean` | `bool` | `False` | 跳过 PDF 清理步骤 |
| `disable_rich_text_translate` | `bool` | `False` | 禁用富文本样式保留 |
| `enhance_compatibility` | `bool` | `False` | 开启所有兼容性选项（=skip_clean + disable_rich_text） |
| `split_short_lines` | `bool` | `False` | 强制把短行分割为独立段落 |
| `short_line_split_factor` | `float` | `0.8` | 短行分割阈值 |
| `dual_translate_first` | `bool` | `False` | 双语模式下译文页放前面 |
| `use_alternating_pages_dual` | `bool` | `False` | 双语模式使用交替页面 |
| `formular_font_pattern` | `str\|None` | `None` | 公式字体名称正则 |
| `formular_char_pattern` | `str\|None` | `None` | 公式字符正则 |
| `ocr_workaround` | `bool` | `False` | 扫描件：译文强制黑色文字 + 白色背景 |
| `auto_enable_ocr_workaround` | `bool` | `False` | 自动检测扫描件并启用 OCR |
| `skip_scanned_detection` | `bool` | `False` | 跳过扫描件检测 |

### 4.4 BasicSettings 字段

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `input_files` | `set[str]` | `set()` | 输入 PDF 文件路径集合（批量翻译用） |
| `debug` | `bool` | `False` | ★ True=在主进程运行 BabelDOC，不用子进程 |
| `gui` | `bool` | `False` | True=启动 Gradio WebUI |
| `warmup` | `bool` | `False` | True=下载并校验所需资源后退出 |
| `version` | `bool` | `False` | 打印版本号后退出 |

### 4.5 翻译引擎 Settings

22 种引擎各有自己的 Settings 类，全部定义在 `config/translate_engine_model.py`，统一接口：

```python
class SomeEngineSettings(BaseModel):
    translate_engine_type: Literal["SomeEngine"]  # 必需，pydantic discriminator
    # ... 引擎专属字段 ...

    def validate_settings(self) -> None:
        """校验字段合法性，清洗字符串"""
        # 内部调用 _clean_string(), _clean_url(), _check_if_positive_float()

    def transform(self) -> OpenAISettings:
        """将自身转为 OpenAISettings（大多数 OpenAI 兼容后端实现此方法）"""
        return OpenAISettings(
            openai_model=self.some_model,
            openai_api_key=self.some_api_key,
            openai_base_url="https://some-api.com/v1",
        )
```

**引擎列表**：

| 类型标识 | Settings 类 | LLM 支持 | OpenAI 兼容 | 说明 |
|----------|------------|----------|-------------|------|
| `OpenAI` | OpenAISettings | ✓ | 原生 | |
| `DeepSeek` | DeepSeekSettings | ✓ | transform | base_url 已内置 |
| `Gemini` | GeminiSettings | ✓ | transform | |
| `SiliconFlow` | SiliconFlowSettings | ✓ | translate_engine_model.py | |
| `SiliconFlowFree` | SiliconFlowFreeSettings | ✓ | 无需 key | 免费 SiliconFlow |
| `Zhipu` | ZhipuSettings | ✓ | transform | 智谱 GLM |
| `ModelScope` | ModelScopeSettings | ✓ | transform | 魔搭社区 |
| `AzureOpenAI` | AzureOpenAISettings | ✓ | 原生 | |
| `Ollama` | OllamaSettings | ✓ | 本地 | |
| `Xinference` | XinferenceSettings | ✓ | 本地 | |
| `Groq` | GroqSettings | ✓ | transform | |
| `Grok` | GrokSettings | ✓ | transform | xAI |
| `AliyunDashScope` | AliyunDashScopeSettings | ✓ | transform | 阿里云 |
| `OpenAICompatible` | OpenAICompatibleSettings | ✓ | transform | 通用兼容模式 |
| `ClaudeCode` | ClaudeCodeSettings | ✓ | 文件交互 | 通过 claude CLI |
| `Bing` | BingSettings | ✗ | - | 微软翻译 |
| `Google` | GoogleSettings | ✗ | - | 谷歌翻译 |
| `DeepL` | DeepLSettings | ✗ | - | DeepL |
| `Azure` | AzureSettings | ✗ | - | Azure 翻译 |
| `TencentMechineTranslation` | TencentSettings | ✗ | - | 腾讯机器翻译 |
| `QwenMt` | QwenMtSettings | ✗ | - | 通义千问 MT |
| `AnythingLLM` | AnythingLLMSettings | - | - | |
| `Dify` | DifySettings | - | - | |
| `CLITranslator` | CLISettings | ✗ | - | 任意外部命令 |

引擎的 `support_llm` 字段决定它能否用于术语提取。

---

## 五、执行流程

### 5.1 两种执行模式

| 模式 | 触发条件 | BabelDOC 运行位置 | 开销 | 适用场景 |
|------|----------|-------------------|------|----------|
| 子进程模式（默认） | `debug=False` | `multiprocessing.Process` | 启动 ~3-6s | 生产（崩溃隔离） |
| debug 模式 | `debug=True` | 主进程 asyncio 事件循环 | 无额外开销 | 调试、warmup |

### 5.2 子进程模式的通信拓扑

```
主进程                                    子进程 (BabelDOC Worker)
──────                                    ────────────────────────
do_translate_async_stream()
  │
  ├─ 构建 SettingsModel → create_babeldoc_config()
  │
  └─ _translate_in_subprocess()
       │
       ├─ Pipe A (progress) ←─────────── pipe_progress_send.send(event)
       │    单向：子进程写，主进程读
       │
       ├─ Pipe B (cancel) ──────────────→ pipe_cancel_message_recv.recv()
       │    单向：主进程写，子进程读
       │
       ├─ Queue (logger) ←─────────────── logger_queue.put(record)
       │    子进程日志桥接到主进程
       │
       ├─ Process (translate_process)     _translate_wrapper()
       │    spawn / start                   └─ create_babeldoc_config()
       │                                      └─ babeldoc.async_translate(config)
       │                                          └─ async for event: pipe.send(event)
       │
       └─ recv_thread (读 Pipe A) → AsyncCallback.step_callback()
          log_thread    (读 Queue) → logger.handle()
                                   async for event in AsyncCallback:
                                     yield event
```

**取消机制**：
1. 外部 `async for` 被取消（`CancelledError`）
2. `Pipe B` 发送 `True` 给子进程的 `cancel_recv_thread`
3. 子进程 `cancel_event.set()` + `config.cancel_translation()`
4. 主进程 `translate_process.join(timeout=2)` → 超时则 `terminate()` → 超时则 `kill()`

### 5.3 create_babeldoc_config

这是 pdf2zh-next 最核心的编排函数（`high_level.py:506-606`）。它做的事：

1. 调用 `get_translator(settings)` 获取主翻译器实例
2. 根据 `term_extraction_engine_settings` 决定术语提取翻译器（可不同于主翻译器）
3. 处理所有 `PDFSettings` / `TranslationSettings` 字段到 `BabelDOCConfig` 的映射
4. 特殊处理：
   - `translate_table_text=True` → 加载 `RapidOCRModel`
   - `watermark_output_mode` → 枚举映射
   - `max_pages_per_part` → 创建 split strategy
   - `glossaries` → 多文件 CSV → `Glossary.from_csv()`
   - `custom_system_prompt` → 透传
   - `only_include_translated_page` → 透传（BabelDOC v0.5.1+ 支持）
   - 按需自动提取 glossary 和 OCR workaround 检测

### 5.4 事件生成链路

```
babeldoc.async_translate(config)
  → event (dict) 直接 y
```

 (dict) 直接 yield
      │
      ├─ type="progress_start" / "progress_update" / "progress_end"
      │    直接透传，不修改
      │
      └─ type="finish"
           _translate_wrapper 注入 token_usage:
           ├─ config.translator.token_count / prompt_token_count / completion_token_count
           ├─ config.term_extraction_translator 的同上
            └─ event["token_usage"] = {"main": {...}, "term": {...}}

---

## 六、翻译器体系

### 6.1 BaseTranslator 接口

```python
class BaseTranslator(ABC):
    name: str                              # 引擎名（<=20 字符，受缓存表字段长度限制）

    def __init__(self, settings: SettingsModel, rate_limiter: BaseRateLimiter):
        # 从 settings 取 lang_in / lang_out / ignore_cache
        # 初始化 self.cache = TranslationCache(self.name, params)

    @abstractmethod
    def do_translate(self, text, rate_limit_params=None) -> str:
        """实际翻译逻辑，子类必须实现"""

    def translate(self, text, ignore_cache=False, rate_limit_params=None) -> str:
        """带缓存 + 限速的翻译入口，所有调用方通过此方法"""

    def do_llm_translate(self, text, rate_limit_params=None) -> str:
        """LLM 原生对话式翻译（非模板 prompt），术语提取用"""

    def llm_translate(self, text, ignore_cache=False, rate_limit_params=None) -> str:
        """带缓存 + 限速的 llm_translate 入口"""

    def prompt(self, text) -> list[dict]:
        """构建翻译 prompt，返回 messages 列表"""

    def get_formular_placeholder(self, placeholder_id) -> tuple[str, str]:
        """公式占位符: ("{v3}", "{v3}" 的 regex)"""

    def get_rich_text_left_placeholder(self, id) -> tuple[str, str]:
        """富文本开始标签: ("<style id='N'>", regex)"""

    def get_rich_text_right_placeholder(self, id) -> tuple[str, str]:
        """富文本结束标签: ("</style>", regex)"""
```

### 6.2 OpenAITranslator — 大多数后端的最终形态

因为大部分 LLM 服务都兼容 OpenAI 协议，pdf2zh-next 把 `OpenAITranslator` 作为实际的翻译执行者。许多引擎 Settings 的 `transform()` 方法把自己转成 `OpenAISettings`，然后工厂函数为它创建 `OpenAITranslator` 实例。

```python
class OpenAITranslator(BaseTranslator):
    name = "openai"

    def __init__(self, settings, rate_limiter):
        self.client = openai.OpenAI(
            base_url=settings.translate_engine_settings.openai_base_url,
            api_key=..., timeout=..., http_client=httpx.Client(...)
        )
        self.model = settings.translate_engine_settings.openai_model
        # token 计数器（线程安全的 AtomicInteger）
        self.token_count = AtomicInteger()
        self.prompt_token_count = AtomicInteger()
        self.completion_token_count = AtomicInteger()
        self.cache_hit_prompt_token_count = AtomicInteger()

    @retry(retry=retry_if_exception_type(RateLimitError), stop=stop_after_attempt(100), ...)
    def do_translate(self, text, rate_limit_params=None) -> str:
        response = self.client.chat.completions.create(
            model=self.model, messages=self.prompt(text), **self.options
        )
        # 累加 token 统计
        return response.choices[0].message.content.strip()
```

### 6.3 工厂函数 get_translator

```python
# translator/utils.py
def get_translator(settings) -> BaseTranslator:
    1. config = settings.translate_engine_settings
    2. 调用 config.validate_settings()
    3. 如果 config 实现了 transform() → config = config.transform() → 再 validate
    4. rate_limiter = QPSRateLimiter(settings.translation.qps)
    5. 遍历 TRANSLATION_ENGINE_METADATA，匹配 config 的类型
    6. importlib.import_module(f"pdf2zh_next.translator.translator_impl.{name.lower()}")
    7. 实例化 Translator 类
    8. 健康检查：translator.translate("Hello", ignore_cache=True)
    9. 如果 Translator 有 recommended_qps / recommended_pool_max_workers → 回写到 settings
    10. 返回 translator 实例
```

### 6.4 缓存

```python
# translator/cache.py
# SQLite 路径: ~/.cache/pdf2zh_next/cache.v1.db
# 表结构: (id, translate_engine, translate_engine_params, original_text, translation)
# 唯一约束: (engine, params, original_text) ON CONFLICT REPLACE
# 模式: WAL

class TranslationCache:
    def __init__(self, translate_engine: str, translate_engine_params: dict):
        # params 会被递归排序后 JSON 序列化，确保相同参数产生相同键

    def get(self, original_text: str) -> str | None:
        """查询缓存"""

    def set(self, original_text: str, translation: str):
        """写入缓存"""

    def add_cache_impact_parameters(self, k, v):
        """添加影响翻译质量的参数（如 model、temperature、prompt）"""
```

缓存的含义是 **段落级**——同一个原文在同一个引擎+参数下不重复调用 API。`ignore_cache=True` 时，`BaseTranslator.translate()` 会跳过 `cache.get()` 和 `cache.set()`。

### 6.5 如何新增翻译后端

1. 在 `config/translate_engine_model.py` 顶部（`## Please add...above this location` 之间）添加 Settings 类：
   ```python
   class MyEngineSettings(BaseModel):
       translate_engine_type: Literal["MyEngine"] = Field(default="MyEngine")
       my_engine_model: str = Field(default="my-model")
       my_engine_api_key: str | None = Field(default=None)

       def validate_settings(self):
           # 清洗/校验字段
       def transform(self) -> OpenAISettings:
           return OpenAISettings(openai_model=self.my_engine_model, ...)
   ```
2. 加到 `TRANSLATION_ENGINE_SETTING_TYPE` — 这行 TypeAlias 遍历所有类型生成 metadata
3. 如果非 OpenAI 兼容，在 `translator/translator_impl/` 创建 `myengine.py`，实现 `MyEngineTranslator(BaseTranslator)`
4. 如果是 OpenAI 兼容，`transform()` 返回 `OpenAISettings` 后工厂会自动用 `OpenAITranslator`
5. 在 `config/__init__.py` 和 `pdf2zh_next/__init__.py` 中导出

---

## 七、配置加载机制

### 7.1 ConfigManager 三层合并

```
优先级（高→低）：
  1. CLI 参数     (--pages "5" --lang-in en)
  2. 环境变量     (PDF2ZH_LANG_IN=en)
  3. 用户 TOML    (~/.config/pdf2zh/config.v3.toml)
  4. 默认值       (SettingsModel 的 Field(default=...))
```

```python
# config/main.py
class ConfigManager:
    """单例"""
    def initialize_config() -> SettingsModel:
        # 1. parse CLI
        # 2. parse ENV (prefix: PDF2ZH_)
        # 3. read ~/.config/pdf2zh/config.v3.toml
        # 4. 找第一个被启用的引擎 flag（如 --deepseek → deepseek=True）
        # 5. 按优先级合并（底层 map 先放入，上层覆盖）
        # 6. SettingsModel(**merged_dict)
        # 7. validate_settings()
        # return settings
```

### 7.2 环境变量命名规则

所有设置被转换为大写 + `PDF2ZH_` 前缀：
```
PDF2ZH_LANG_IN=en
PDF2ZH_LANG_OUT=zh
PDF2ZH_DEEPSEEK_API_KEY=sk-xxx
PDF2ZH_DEEPSEEK_MODEL=deepseek-chat
PDF2ZH_DEBUG=true
PDF2ZH_IGNORE_CACHE=true
```

嵌套字段用下划线连接：`translation.lang_in` → `PDF2ZH_LANG_IN`。

### 7.3 不使用 ConfigManager 的方式（直接 Python 代码）

ConfigManager 是为 CLI 场景设计的。在库中直接创建 `SettingsModel` 实例是更常见的方式：

```python
settings = SettingsModel(
    translation=TranslationSettings(lang_in="en", lang_out="zh"),
    pdf=PDFSettings(pages="1"),
    translate_engine_settings=DeepSeekSettings(deepseek_api_key="sk-xxx"),
)
settings.validate_settings()  # 手动校验
```

---

## 八、CLI 与 WebUI

### 8.1 CLI

```bash
pdf2zh document.pdf --pages "1-10" --lang-in en --lang-out zh --deepseek "sk-xxx"
```

- 入口：`main.py:cli()` → `asyncio.run(main())`
- 自动 warmup BabelDOC 资源（字体、ONNX 模型）
- 如果 `--gui` 则启动 Gradio
- 否则调用 `do_translate_file_async` → 内置 rich 进度条
- 引擎通过 `--deepseek`、`--openai` 等 flag 选择，细节参数如 `--deepseek-model`

### 8.2 Gradio WebUI

`gui.py`（~2000 行）提供完整的图形界面：
- 文件上传 / URL 下载
- 翻译引擎选择（下拉框动态切换参数面板）
- 术语表 CSV 上传
- 进度条 + 取消按钮
- 结果预览（PDF 查看器）+ ZIP 下载
- 多语言界面（i18n）

WebUI 通过 `_build_translate_settings()` 将 UI 组件值转为 `SettingsModel`，内部仍调用 `do_translate_async_stream`。

---

## 九、关键技术细节

### 9.1 AsyncCallback — Pipe 到 AsyncGenerator 的桥

`utils/asynchronize/__init__.py:AsyncCallback` 是 pdf2zh-next 的关键工具类：

```python
class AsyncCallback:
    def __init__(self, timeout=None):
        self.queue = asyncio.Queue()   # 跨线程安全的消息队列

    def step_callback(self, *args, **kwargs):
        # 由 recv_thread 调用（同步线程），把事件放入 asyncio 队列
        self.loop.call_soon_threadsafe(self.queue.put_nowait, Args(args, kwargs))

    def finished_callback_without_args(self):
        self.finished = True
        self.step_callback(MAGIC_MESSAGE_FINISHED)

    async def __anext__(self):
        # 被主协程的 async for 消费
        if self.finished and self.queue.empty():
            raise StopAsyncIteration
        item = await self.queue.get()
        if item.args[0] == MAGIC_MESSAGE_ERROR:
            raise self.error
        return item
```

这实现了「同步线程写、异步协程读」的模式。

### 9.2 Translator 命令约定

每个前端 Settings 类向 CLI 暴露 flag 的规则：
- 类名 `XxxSettings` → CLI flag `--xxx`（全小写）
- 细节字段 `xxx_model` → CLI `--xxx-model`
- 如果类只有 `translate_engine_type` 一个字段（无细节参数），则只是一个 boolean flag，无 `--xxx-detail` 子参数

Metadata 由 `translate_engine_model.py` 中的 `@dataclass TranslationEngineMetadata` 自动生成：

```python
@dataclass
class TranslationEngineMetadata:
    translate_engine_type: str        # e.g. "DeepSeek"
    cli_flag_name: str               # "deepseek"
    cli_detail_field_name: str|None  # "deepseek_detail" or None
    setting_model_type: type[BaseModel]  # DeepSeekSettings
    support_llm: bool                # 是否支持 LLM（用于术语提取）
```

### 9.3 Token 用量统计

在 `_translate_wrapper()` 中，`finish` 事件被增强：
- `config.translator.token_count` / `prompt_token_count` / `completion_token_count` / `cache_hit_prompt_token_count`
- `config.term_extraction_translator` 的同上
- 如果主翻译器和术语提取器是同一实例 → 减去术语提取部分以避免重复

### 9.4 健康检查翻译

`get_translator()` 在返回前会执行一次 `translator.translate("Hello", ignore_cache=True)`。如果失败（例如 API key 错误），会在初始化阶段就报错，而不是翻译到一半才报错。

---

## 十、核心文件速查

| 文件 | 行数 | 为何重要 |
|------|------|----------|
| `high_level.py` | 796 | 三个公开 API + 子进程管理 + BabelDOC 配置桥接 |
| `config/model.py` | 483 | SettingsModel + 子模型定义 + parse_pages() + validate_settings() |
| `config/translate_engine_model.py` | 1104 | 22 个引擎 Settings + 元数据自动生成 + transform 链路 |
| `translator/utils.py` | 128 | get_translator / get_term_translator 工厂 |
| `translator/base_translator.py` | 188 | BaseTranslator 基类 + prompt 模板 + 占位符方法 |
| `translator/cache.py` | 152 | SQLite 翻译缓存（peewee ORM） |
| `translator/translator_impl/openai.py` | 167 | OpenAITranslator — 大多数后端的实际执行者 |
| `utils/asynchronize/__init__.py` | 93 | AsyncCallback — Pipe→AsyncGenerator 桥 |
| `config/main.py` | 665 | ConfigManager 单例 + CLI/ENV/TOML 解析与合并 |
| `gui.py` | ~2000 | Gradio WebUI |
| `main.py` | 111 | CLI 入口 |

---

*基于 pdf2zh-next v2.8.2 源码，2026-06-19*
