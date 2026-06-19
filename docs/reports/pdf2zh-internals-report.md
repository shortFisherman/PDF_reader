# pdf2zh v1 内部运作报告

> 基于对 `C:\Users\Couper\PDFMathTranslate\` 源码的完整阅读，版本 v1.9.x

---

## 一、目录结构与职责

```
PDFMathTranslate/
├── pdf2zh/
│   ├── high_level.py      # 公开 API：translate() / translate_stream()
│   ├── converter.py       # 核心管道：解析→分段→翻译→PDF 重写
│   ├── translator.py      # 25+ 翻译后端（含 DeepSeek）
│   ├── doclayout.py       # ONNX YOLO 文档版面检测模型
│   ├── pdfinterp.py       # 扩展的 PDF 页面解释器（pdfminer 子类）
│   ├── config.py          # 持久化配置管理器（~/.config/PDFMathTranslate/config.json）
│   ├── cache.py           # SQLite 翻译缓存（避免重复 API 调用）
│   ├── converter_docx.py  # .doc/.docx → PDF 转换
│   ├── pdf2zh.py          # CLI 入口
│   ├── gui.py             # Gradio Web UI
│   ├── backend.py         # Flask + Celery HTTP API
│   ├── mcp_server.py      # MCP 服务器
│   └── kernel/            # 内核抽象层
│       ├── protocol.py    # TranslateRequest / TranslateResult / KernelProtocol
│       ├── legacy.py      # "fast" 内核：封装 high_level.translate()
│       ├── precise.py     # "precise" 内核：调用 pdf2zh_next 子进程
│       ├── registry.py    # 线程安全的内核注册表
│       ├── v2_bridge.py   # v1 ↔ v2 参数转换
│       └── v2_worker.py   # v2 子进程 worker
└── test/
```

---

## 二、核心管道：从 PDF 到翻译后 PDF 的四阶段

### 阶段 1：版面检测（ONNX YOLO 模型）

**入口**：`high_level.py:translate_patch()` 第 134 行

```python
page_layout = model.predict(image, imgsz=int(pix.height / 32) * 32)[0]
```

- 用 pymupdf 把当前页渲染为 RGB 位图（`get_pixmap()`）
- 送入 ONNX DocLayout YOLO 模型
- 模型输出每页的分类掩码（cls），类别包括：

| 类别名 | 含义 | 处理方式 |
|--------|------|----------|
| `abandon` | 放弃区域 | 保留（不翻译） |
| `figure` | 图表 | 保留 |
| `table` | 表格 | 保留 |
| `isolate_formula` | 独立公式 | 保留 |
| `formula_caption` | 公式标题 | 保留 |
| 其他（text body） | 正文区域 | 标记为可翻译 |

- 保留区域在 numpy 掩码中设为 `0`，正文区域设为 `i+2`（i 是区域编号）
- 掩码尺寸 = 原始页面的像素尺寸，做到逐像素分类

**性能**：模型加载约 2-5 秒（首次含优化缓存），之后缓存到 `*.optimized` 文件。模型实例 `ModelInstance.value` 是模块级单例，可跨调用复用。

### 阶段 2：字符提取 + 公式识别 + 段落分割

**入口**：`converter.py:TranslateConverter.receive_layout()` 第 170 行

#### 2a. 字符遍历

pdfminer 迭代页面上每个 `LTChar`（字符），同时查询 ONNX 掩码中该字符坐标的分类（`cls`）。

#### 2b. 公式判定（6 层叠加）

```python
# converter.py 第 242-256 行
cur_v = (
    cls == 0                                                    # 1. 掩码为保留区域
    or (cls == xt_cls and size < pstk[-1].size * 0.79)         # 2. 角标字体（字号比 0.79）
    or vflag(child.fontname, child.get_text())                  # 3. 公式字体/字符集规则
    or (child.matrix[0] == 0 and child.matrix[3] == 0)          # 4. 垂直字体
)
# 5. 括号分组：公式组后紧跟 '(' 视为公式一部分
# 6. Unicode 类别：Lm, Mn, Sk, Sm 修饰符和数学符号
```

公式字体默认正则（LaTeX 字体）：
```
CM[^R]|MS.M|XY|MT|BL|RM|EU|LA|RS|LINE|LCIRCLE|TeX-|rsfs|txsy|wasy|stmary|.*Mono|.*Code|.*Ital|.*Sym|.*Math
```

#### 2c. 段落分割

- 字符按分类（`cls`）和坐标连续性分组
- 公式组被替换为占位符 `{v0}`, `{v1}`, `{v2}`...
- 公式的原始字符、线条、纵向偏移分别存入 `var`, `varl`, `varf` 栈
- 图表（`LTFigure`）**完全跳过**（`pass` at line 317），保留在基础 PDF 中不动
- 非公式/非表格区域的黑色水平线被标记为「全局线条」，在最终输出中重新绘制

#### 2d. 输出

```
sstk = ["段落0的文本 {v0} 更多文本", "段落1的文本", "{v2}"]
var  = [[公式0的字符列表], [公式1的字符列表], [公式2的字符列表]]
pstk = [段落0的坐标属性, 段落1的坐标属性, 段落2的坐标属性]
```

### 阶段 3：LLM 翻译

**入口**：`converter.py` 第 348-364 行

#### 3a. 并行翻译

```python
with concurrent.futures.ThreadPoolExecutor(max_workers=self.thread) as executor:
    news = list(executor.map(worker, sstk))
```

- 每个段落作为独立翻译请求发送
- 空字符串和纯公式段落（`{vN}`）跳过翻译
- 翻译失败时默认重试 1 次（`@retry(wait=wait_fixed(1))`）

#### 3b. 默认 Prompt

```
"You are a professional, authentic machine translation engine."
"Only Output the translated text, do not include any other text."
"Translate the following markdown source text to {lang_out}."
"Keep the formula notation {v*} unchanged."
"Output translation directly without any additional text."
"Source Text: {text}"
"Translated Text:"
```

- 公式占位符 `{vN}` 在 prompt 中明确要求保留
- temperature = 0（避免随机解码打断公式标记）

#### 3c. 翻译缓存

- SQLite 数据库（`~/.cache/pdf2zh/cache.v1.db`）
- 以 `(engine, params, original_text)` 为唯一键
- 翻译前先查缓存，命中即返回
- `ignore_cache=True` 可跳过

#### 3d. 上下文隔离问题（重要！）

**每个段落是独立的翻译请求，没有文档级上下文。** 这意味着：

- 第 5 页和第 8 页的同一术语可能被翻译成不同中文
- 跨页段落会被硬切断（页边界处无上下文）
- 没有 "翻译记忆库" 或 "术语表" 机制

### 阶段 4：PDF 内容流重写

**入口**：`converter.py` 第 367-528 行 + `pdfinterp.py` 第 254-276 行

#### 4a. 核心机制：不是替换文字图层，而是修改 PDF 内容流操作符

pdf2zh 不创建新的 PDF——它**修改原始 PDF 的 content stream**。具体做法：

```
原始 content stream:
  BT /F1 12 Tf 1 0 0 1 72 700 Tm (Hello world) Tj ET   ← 原文文字

修改后的 content stream:
  q                                                       ← 保存图形状态
  BT /F1 12 Tf 1 0 0 1 72 700 Tm (Hello world) Tj ET     ← 原文（保留但隐藏）
  Q                                                       ← 恢复图形状态
  1 0 0 1 72 700 cm                                       ← 偏移回原文位置
  BT /noto 12 Tf 1 0 0 1 0 0 Tm (<4f60597d>) Tj ET       ← 译文（叠加显示）
```

- 原文指令被 `q/Q` 包裹（相当于 "先画后擦"，视觉上被译文覆盖）
- 译文以新指令追加在末尾
- 图形、图片、公式字符的操作符完全不动——只有文字操作符被处理
- XObject（嵌入的图形/Form）递归处理，保留原始基础指令 + 追加翻译层

#### 4b. 公式重排

公式字符按其**原始屏幕坐标**重新放置，保留精确位置。公式内的黑色水平线也按原始坐标重绘。

#### 4c. 文字排版

- 译文字符按目标字体（SourceHanSerif / GoNotoKurrent）的字符宽度计算水平位置
- 到达右边界自动换行
- 行高根据目标语言调整：
  - 中文：1.4 倍字号
  - 日文：1.1 倍
  - 英文：1.2 倍
  - 阿拉伯文：1.0 倍

#### 4d. 双语文档生成

```python
# high_level.py 第 243-245 行
doc_en.insert_file(doc_zh)                          # 把翻译版插入原文之后
for id in range(page_count):
    doc_en.move_page(page_count + id, id * 2 + 1)   # 交错排列：原文0, 译文0, 原文1, 译文1...
```

返回两个文件：
- `{filename}-mono.pdf`：纯译文版
- `{filename}-dual.pdf`：双语对照版（原文页 + 译文页交替）

---

## 三、公开 API

### `translate()`（文件路径版本）

```python
translate(
    files: list[str],                    # PDF 文件路径列表
    output: str = "",                    # 输出目录
    pages: Optional[list[int]] = None,   # 0-indexed 页码范围
    lang_in: str = "",                   # 源语言
    lang_out: str = "",                  # 目标语言
    service: str = "",                   # "deepseek", "openai:gpt-4o", "google" 等
    thread: int = 0,                     # 翻译线程数（0=串行）
    model: OnnxModel = None,             # 预加载的 ONNX 模型（复用！）
    envs: Dict = None,                   # 环境变量覆盖
    prompt: Template = None,             # 自定义翻译 prompt
    ignore_cache: bool = False,          # 跳过 SQLite 翻译缓存
    ...
) -> list[tuple[str, str]]              # [(mono_pdf_path, dual_pdf_path), ...]
```

### `translate_stream()`（字节流版本）

```python
translate_stream(
    stream: bytes,                       # PDF 原始字节
    pages: Optional[list[int]] = None,   # 0-indexed 页码范围
    ...
) -> tuple[bytes, bytes]                # (mono_pdf_bytes, dual_pdf_bytes)
```

### DeepSeek 使用方式

```python
translate(
    files=["doc.pdf"],
    lang_in="en",
    lang_out="zh",
    service="deepseek",                          # 或 "deepseek:deepseek-reasoner"
    envs={"DEEPSEEK_API_KEY": "sk-xxx"}          # 或依赖环境变量
)
```

DeepSeek 后端（`translator.py:1002-1026`）继承自 `OpenAITranslator`：
- Base URL: `https://api.deepseek.com/v1`
- 默认模型: `deepseek-chat`
- API Key: `DEEPSEEK_API_KEY` 环境变量

---

## 四、配置系统

### 三层优先级

```
1. translate() 的 envs 参数       ← 最高优先级（per-call）
2. 系统环境变量                    ← 中优先级
3. ~/.config/PDFMathTranslate/config.json  ← 最低优先级（持久化）
```

### config.json 格式

```json
{
    "translators": [
        {
            "name": "deepseek",
            "envs": {
                "DEEPSEEK_API_KEY": "sk-xxx",
                "DEEPSEEK_MODEL": "deepseek-chat"
            }
        }
    ],
    "NOTO_FONT_PATH": "/path/to/SourceHanSerifCN-Regular.ttf"
}
```

配置是线程安全的（`RLock`），读写时自动与 JSON 文件同步。

---

## 五、翻译缓存

- SQLite 数据库：`~/.cache/pdf2zh/cache.v1.db`
- WAL 模式（支持并发读写）
- 表结构：`(id, translate_engine, translate_engine_params, original_text, translation)`
- 唯一约束：`(engine, params, original_text)` — 相同文本用相同引擎/参数不重复调用 API
- 当前版本 v1，数据库文件包含版本号 `cache.v1.db`

---

## 六、内核抽象层（Kernel System）

pdf2zh 支持热切换翻译内核：

| 内核 | 类型 | 说明 |
|------|------|------|
| `fast` | LegacyKernel | 封装 v1 原文管道，所有功能在进程内 |
| `precise` | PreciseKernel | 启动 pdf2zh_next 子进程，通过 env vars 传参 |

内核注册表（`KernelRegistry`）是线程安全的，支持运行时切换。默认使用 `fast` 内核。

---

## 七、与 PDF_reader 项目直接相关的能力边界

### 可以做到的

| 能力 | 详情 |
|------|------|
| 单页翻译 | `pages=[N]` 参数，但输出仍是完整 PDF |
| ONNX 模型复用 | 传 `model=OnnxModel.load_available()` 给 translate()，后续调用不重新加载 |
| DeepSeek 原生支持 | 零配置，有 API key 即可 |
| 图表保留 | `LTFigure` 完全跳过，图形操作符不动 |
| 公式保留 | 6 层检测 + 坐标级重排 |
| 翻译缓存 | 跨调用共享，避免重复 API 费用 |
| 配置持久化 | config.json 管理，不依赖环境变量 |

### 做不到的 / 需要注意的

| 限制 | 影响 |
|------|------|
| 无跨页上下文 | 同一术语在不同页可能翻译不一致 |
| 无跨段落上下文 | 段落间无记忆，LLM 每次都是全新对话 |
| 只输出 PDF | 无法获取中间文本（翻译前后的纯文本） |
| 同步阻塞 | `translate()` 是同步函数，整个 PDF 处理完才返回 |
| 无流式输出 | 不能逐页获取结果，必须等全部完成 |
| 单页处理仍跑完整管道 | `pages=[5]` 仍然会加载 ONNX 模型、下载字体、初始化 translator |
| 字体依赖 | 译文中文需要 SourceHanSerif，首次使用自动下载 ~15-20 MB |
| 线条过滤 | 只保留黑色水平线，彩色/斜线/非水平线被丢弃 |

### 对本项目的关键启示

1. **ONNX 模型应预加载一次**：不要在每次翻译时重新加载。在 Flask 应用启动时加载，然后通过 `model=` 参数传入。

2. **`pages=[N]` 不会只输出第 N 页**：它输出完整 PDF，只是只有第 N 页文字被翻译。对这个项目来说，正确的做法是：
   - 用 pymupdf 提取目标页为单页 PDF
   - 喂给 pdf2zh（不带 pages 参数，因为只有 1 页）
   - 用 pymupdf 把翻译结果插入 right.pdf
   
   或者直接研究 `translate()` 对 `pages=[N]` 时输出的其他页是什么状态，看能否直接提取。

3. **翻译缓存很有价值**：同一个段落如果在不同页出现（比如页眉页脚、引用），不会重复调用 API。

4. **术语不一致问题**：对教材翻译来说，这是最需要关注的问题。没有内置的术语表或翻译记忆，全靠 LLM 的记忆——但 DeepSeek 是 stateless API，没有跨请求记忆。

5. **`translate_stream()` 更适合本项目**：它接受 bytes 返回 bytes，避免了文件 I/O 的一部分开销。

---

## 八、管道示意图

```
                          ┌──────────────────────┐
                          │   原始 PDF 文件       │
                          └──────────┬───────────┘
                                     │
                    ┌────────────────┼────────────────┐
                    │                │                │
                    ▼                ▼                ▼
             pymupdf          pdfminer           pymupdf
           渲染为位图        提取字符/图形        PDF 构造
                    │                │                │
                    ▼                │                │
            ONNX YOLO 模型          │                │
           版面检测 → 分类掩码       │                │
                    │                │                │
                    └────────┬───────┘                │
                             │                        │
                             ▼                        │
                    字符分类 + 公式判定               │
                    （掩码 × 字体 × Unicode）          │
                             │                        │
                    ┌────────┴────────┐               │
                    ▼                 ▼                │
              文字段落             公式组              │
           "text {v0} text"    [字符坐标+线条]         │
                    │                 │                │
                    ▼                 │                │
            LLM API 翻译              │                │
           "文本 {v0} 文本"           │                │
                    │                 │                │
                    └────────┬────────┘                │
                             │                        │
                             ▼                        │
                     PDF content stream 重写           │
                  q (原始指令) Q → 追加翻译指令         │
                             │                        │
                             ▼                        │
                    ┌────────────────┐                │
                    │  翻译后 PDF     │◄───────────────┘
                    └────────────────┘
```

---

*报告生成时间：2026-06-18，基于 pdf2zh v1.9.x 源码分析*
