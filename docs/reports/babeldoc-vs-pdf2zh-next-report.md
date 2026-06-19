# BabelDOC vs PDFMathTranslate-next 对比报告

> 基于对两个仓库源码的完整阅读与比较
> BabelDOC: v0.6.3 | pdf2zh-next: v2.8.2

---

## 一、一句话说清关系

```
BabelDOC                pdf2zh-next
   │                        │
   │  翻译引擎（底层）        │  包装层（上层）
   │  - 自定义 PDF 解析器     │  - 22 种翻译服务适配
   │  - Document IL 管道      │  - TOML + CLI + ENV 配置
   │  - 术语表 + 自动提取      │  - Gradio WebUI
   │  - LLM 批量翻译          │  - 子进程隔离 + AsyncGenerator API
   │  - PDF 重建              │  - 翻译缓存（SQLite）
   │                        │
   └────────┬───────────────┘
            │
    pdf2zh-next 把 BabelDOC 封装在子进程中运行
    通过 multiprocessing.Pipe 传递事件
    对外暴露 AsyncGenerator API
```

pypi 依赖声明：`babeldoc>=0.5.20, <0.6.0`

**pdf2zh-next 不包含自己的翻译管道**——它的 `do_translate_async_stream()` 最终调用的是 `babeldoc.format.pdf.high_level.async_translate()`。

---

## 二、管道对比：BabelDOC vs pdf2zh v1

| 阶段 | pdf2zh v1 | BabelDOC |
|------|-----------|----------|
| PDF 解析 | pdfminer.six | **自研纯 Python 解析器**（`new_parser/`），更好的字体/CID/CMap 处理 |
| 中间表示 | pdfminer LT 对象直接操作 | **Document IL** — 类型化的 dataclass IR，可序列化为 XML/JSON |
| 版面检测 | ONNX DocLayout-YOLO | 同，也支持远程 RPC 模型 |
| 段落查找 | 基础按行分组 | 多轮：跨页检测、跨栏检测、公式排除、字号聚类 |
| 公式处理 | 6 层判定 + 坐标排布 | 模板占位符（`{vN}`）+ 富文本样式包裹（`<style id='N'>`） |
| 翻译模式 | 逐段串行 | **LLM 批量 JSON 模式**：多段合并为一个 JSON 数组发 LLM，失败自动降级 |
| 术语提取 | 无 | **LLM 自动提取** + 多数投票去重 |
| 术语表 | 无 | Hyperscan 高性能匹配 + LLM prompt 注入 |
| 并行 | ThreadPoolExecutor | PriorityThreadPoolExecutor（长段落优先翻译） |
| 大 PDF | 不支持 | `--max-pages-per-part` 切片翻译 + 合并 |
| PDF 输出 | 修改原始 content stream | **完整重建**：PDFCreater 通过 PyMuPDF 生成全新内容流 |
| 扫描件 | 不支持 | SSIM 检测 + OCR 覆盖模式 |
| 进度 | tqdm | 加权阶段进度 + 异步事件流 |
| 缓存 | SQLite（段落级） | 无（由 pdf2zh-next 提供 SQLite 缓存） |

**结论：BabelDOC 的管道在各方面都更先进。** 特别是跨页段落检测、LLM 批量 JSON 翻译、自动术语提取这三项，直接解决教材翻译的核心痛点。

---

## 三、Python API 对比

### BabelDOC 直接调用

```python
from babeldoc.format.pdf.translation_config import TranslationConfig
from babeldoc.format.pdf.high_level import async_translate

config = TranslationConfig(
    input_file="doc.pdf",
    pages="5",                          # 第 5 页
    lang_in="en",
    lang_out="zh",
    openai_model="deepseek-chat",
    openai_base_url="https://api.deepseek.com/v1",
    openai_api_key="sk-xxx",
    custom_system_prompt="翻译要专业，保留公式",
    glossaries=[glossary_obj],
    ignore_cache=True,
    only_include_translated_page=True,  # ← 关键：只输出指定页
    no_mono=False,
    no_dual=True,
)

async for event in async_translate(config):
    if event["type"] == "finish":
        result = event["translate_result"]
```

⚠️ BabelDOC 官方声明：*"All APIs of BabelDOC should be considered as internal APIs, and any direct use of BabelDOC is not supported."*

### pdf2zh-next 调用（推荐方式）

```python
from pdf2zh_next import SettingsModel, do_translate_async_stream

settings = SettingsModel(
    translation=TranslationSettings(
        lang_in="en",
        lang_out="zh",
        custom_system_prompt="翻译要专业，保留公式",
        glossaries="/path/to/terms.csv",
    ),
    pdf=PDFSettings(
        pages="5",
        no_dual=True,
    ),
    translate_engine_settings=DeepSeekSettings(
        api_key="sk-xxx",
    ),
)

async for event in do_translate_async_stream(settings, "doc.pdf"):
    if event["type"] == "finish":
        result = event["translate_result"]
```

### 关键差异

| 维度 | BabelDOC 直接 | pdf2zh-next 包装 |
|------|--------------|------------------|
| API 稳定性 | ❌ Internal，随时可改 | ✅ 公开 API，语义化版本 |
| 子进程隔离 | ❌ 直接运行在调用进程 | ✅ 默认子进程运行，崩溃不拖垮主进程 |
| 翻译缓存 | ❌ 无（v1 有，BabelDOC 没有） | ✅ SQLite 缓存 |
| 翻译后端 | 仅 OpenAI 兼容 LLM | 22 种（含 Google、DeepL、Ollama 等） |
| 进度事件 | 直接生成器 | 包装为统一的 dict 事件流 |
| 额外开销 | 无 | 子进程启动 ~1s + Pipe 通信 |
| 异常处理 | 基础 | 5 种自定义异常类 + 结构化错误信息 |

---

## 四、你的三个核心需求：对照

### 4.1 按页翻译 + 重译

**BabelDOC**：
```
配置                         行为
───────────────────────────────────────────
pages="5"                    只处理第 5 页
only_include_translated_page 输出 PDF 只含第 5 页译文
ignore_cache=True            强制重新翻译
```

完美匹配。`only_include_translated_page=True` 是 pdf2zh v1 不具备的功能。

**pdf2zh-next**：同上，通过 `PDFSettings.pages` + `no_dual` 等配置传递。

### 4.2 每次翻译传入自定义提示词

**BabelDOC**：`custom_system_prompt` 直接替换 LLM prompt 中的 role block。支持 per-call。

**pdf2zh-next**：`TranslationSettings.custom_system_prompt`，同样 per-call。

都内置支持。比 pdf2zh v1 的 Template 参数方式更自然。

### 4.3 翻译结果持久化 + 术语管理

**BabelDOC 的术语表系统**（这是决定性优势）：

```
CSV 格式（docs/example/demo_glossary.csv）:
source,target,tgt_lng
waveguide,波导,zh-CN
manifold,流形,zh-CN

工作原理：
1. 加载 CSV，Hyperscan（Intel 高性能正则会引擎）匹配原文
2. 匹配到的术语自动注入 LLM prompt：
   ### Glossary: terms
   | Source Term | Target Term |
   | waveguide | 波导 |
   
3. LLM 指令："Always use the exact target term..."
4. 后续调用只需更新 CSV，无需改代码
```

**自动术语提取**（BabelDOC 独有功能）：

1. 翻译前，用独立 LLM 调用从全文抽取术语
2. 多数投票去重（同一术语在不同页抽取结果取众数）
3. 自动注入翻译 prompt
4. 可保存为 CSV 文件，供后续手工修正

这对你的场景意味着：第一次翻译自动抽术语，你翻到不准确的地方（比如 waveguide 被译为波导管），在 CSV 里改一项，下次重译自动生效。不需要每页手工写 prompt。

---

## 五、建议：选 pdf2zh-next，不选 BabelDOC 直接调用

### 理由

```
                    BabelDOC 直接        pdf2zh-next
API 稳定性          ❌ 正式声明 Internal   ✅ 公开 API，v2.8.2
子进程隔离          ❌ 需自己实现          ✅ 内置
翻译缓存            ❌ BabelDOC v0.6.3 无  ✅ SQLite 缓存
DeepSeek 支持       ⚠️ 需手动拼 OpenAI 参数 ✅ DeepSeekSettings 一等公民
翻译服务扩展性      ❌ 仅 OpenAI 兼容       ✅ 22 种，可随时切换
HTTP API（未来）    ❌ 无                  ⚠️ http_api.py 是空文件，未来计划
维护成本            高（API 可能 break）    低（版本化接口）
崩溃隔离            ❌ 翻译失败可能挂 Flask  ✅ 子进程崩溃不影响主进程
Token 使用量追踪    ❌ 无                  ✅ 聚合在 finish 事件中
```

推荐架构：

```
Flask 后端
    │
    ├── 启动时: 预加载 ONNX 模型、字体（一次 warmup）
    │
    ├── POST /translate
    │   ├── 接收: page, prompt, force=False
    │   ├── 构建: SettingsModel(pages=str(page), custom_system_prompt=prompt, ...)
    │   ├── 调用: do_translate_async_stream(settings, "left.pdf")
    │   ├── 监听: async for event → SSE push 到前端
    │   └── finish: 拿到 mono_pdf_path → 提取第 0 页 → 插入 right.pdf
    │
    └── POST /translate
        └── 同上，但 custom_system_prompt 可不同
```

### 唯一的代价

pdf2zh-next 默认在子进程中运行 BabelDOC。每次翻译：
- 子进程启动开销 ~1s
- BabelDOC 初始化（加载 ONNX 模型、字体）~2-5s

总计单次翻译启动 ~3-6 秒。但这个可以用 **debug 模式绕过子进程**：

```python
settings.basic.debug = True  # 此时在 Flask 进程内直接调用 BabelDOC
```

或者启动时做一次 warmup 翻译（翻译一个空页），让 ONNX 模型和字体加载到缓存中。

---

## 六、架构迁移对比

```
现在（Hermes 方案）                    建议（pdf2zh-next 方案）

Flask                                   Flask
  │                                       │
  ├─ pymupdf 提取第 N 页 -> page.pdf       ├─ pymupdf 提取第 N 页 -> page.pdf
  │                                       │
  ├─ subprocess: pdf2zh page.pdf          ├─ do_translate_async_stream(
  │   等待 PDF 写入硬盘                       settings=SettingsModel(
  │                                            pages="1",
  │                                             custom_system_prompt=prompt,
  ├─ pymupdf 读译文 -> 插入 right.pdf          translate_engine_settings=
  │                                              DeepSeekSettings(...),
  │                                       │   ),
  │                                       │   file="page.pdf",
  │                                       │ )
  │                                       │
  └─ 返回前端刷新指令                        ├─ async for event:
                                              │  yield SSE progress
                                              │
                                              ├─ event["type"] == "finish"
                                              │  → out.pdf 只有第 0 页译文
                                              │  → pymupdf 插入 right.pdf
                                              │
                                              └─ 返回前端刷新指令
```

迁移量很小——后端改动集中在翻译调用那一层。前端、pymupdf 图片渲染、right.pdf 管理逻辑全部复用。

---

*报告生成时间：2026-06-18*
