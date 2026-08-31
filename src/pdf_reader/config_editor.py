"""前端配置中心后端：schema、脱敏读取、白名单校验与原子保存。

职责边界（与 ``config.py`` 的关系）：

- 本模块不修改 ``config.CONFIG``、``config.MODEL_API_KEY`` 或运行中的
  ``AppSettings``；保存只写 config.toml，并返回 ``restart_required=true``。
- 校验完全复用 ``config.validate_startup_requirements`` 与
  ``config.resolve_server_config``（同一套类型/范围/枚举/条件依赖规则），
  本模块只做：schema 白名单、请求结构检查、TOML 应用与序列化。
- API Key 永不进入日志、异常消息或响应体；GET 只返回 configured/source 状态。
- 写入使用 tomlkit 保留注释、字段顺序与未知字段；同进程写锁 +
  同目录临时文件 + ``os.replace`` 原子替换，并保留原文件权限。
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
import stat
import tempfile
import threading
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomlkit
from tomlkit.exceptions import ParseError

from pdf_reader import config

logger = logging.getLogger("pdf_reader.config_editor")

_write_lock = threading.RLock()

PROVIDER_OPTIONS: tuple[tuple[str, str], ...] = (
    ("deepseek", "DeepSeek"),
    ("zhipu", "智谱"),
    ("siliconflow", "硅基流动"),
    ("aliyun", "阿里云百炼"),
    ("gemini", "Gemini"),
    ("groq", "Groq"),
    ("grok", "Grok"),
    ("modelscope", "ModelScope"),
    ("openai", "OpenAI"),
    ("openai_compatible", "自定义 OpenAI 兼容接口"),
)


@dataclass(frozen=True)
class FieldSpec:
    """配置中心单个字段的展示与约束描述。"""

    path: str
    name: str
    group: str  # required | optional | advanced
    control: str  # select | bool | int | float | string | password
    description: str
    default: Any = None
    suggestions: tuple[str, ...] = ()
    options: tuple[tuple[str, str], ...] = ()
    providers: tuple[str, ...] | None = None
    required_for: tuple[str, ...] = ()
    secret: bool = False
    minimum: float | None = None
    maximum: float | None = None

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "name": self.name,
            "group": self.group,
            "control": self.control,
            "description": self.description,
            "default": self.default,
            "suggestions": list(self.suggestions),
            "options": [{"value": value, "label": label} for value, label in self.options],
            "providers": list(self.providers) if self.providers is not None else None,
            "required_for": list(self.required_for),
            "secret": self.secret,
            "minimum": self.minimum,
            "maximum": self.maximum,
        }


_BOOL_OPTIONS: tuple[tuple[str, str], ...] = (
    ("true", "开启"),
    ("false", "关闭"),
)


FIELD_SPECS: list[FieldSpec] = [
    FieldSpec(
        path="model.provider",
        name="模型服务商",
        group="required",
        control="select",
        description="选择翻译使用的模型服务商；最后一项可对接任意兼容 OpenAI 接口的服务。",
        default="openai_compatible",
        options=PROVIDER_OPTIONS,
    ),
    FieldSpec(
        path="model.api_key",
        name="API Key",
        group="required",
        control="password",
        description="服务商的 API Key。仅保存在 config.toml，页面与接口均不回显明文；"
        "环境变量 MODEL_API_KEY 优先于文件值。",
        default="",
        secret=True,
    ),
    FieldSpec(
        path="model.model",
        name="模型名称",
        group="required",
        control="string",
        description="服务商下实际调用的模型名。",
        default="",
        suggestions=(
            "deepseek-chat",
            "deepseek-reasoner",
            "deepseek-v4-flash",
            "glm-4-plus",
            "glm-4-flash",
            "Qwen/Qwen2.5-7B-Instruct",
            "qwen-plus",
            "qwen-turbo",
            "gemini-2.0-flash",
            "grok-2-latest",
            "llama-3.3-70b-versatile",
            "gpt-4o-mini",
            "gpt-4o",
        ),
    ),
    FieldSpec(
        path="model.base_url",
        name="Base URL",
        group="optional",
        control="string",
        description="服务接口地址。选择“自定义 OpenAI 兼容接口”时必填，其他适用服务商可留空使用官方默认。",
        default="",
        suggestions=(
            "https://api.deepseek.com/v1",
            "https://open.bigmodel.cn/api/paas/v4",
            "https://api.siliconflow.cn/v1",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "https://generativelanguage.googleapis.com/v1beta/openai",
            "https://api.groq.com/openai/v1",
            "https://api.x.ai/v1",
            "https://api-inference.modelscope.cn/v1",
            "https://api.openai.com/v1",
        ),
        providers=("siliconflow", "aliyun", "openai", "openai_compatible"),
        required_for=("openai_compatible",),
    ),
    FieldSpec(
        path="model.thinking_mode",
        name="思考模式",
        group="optional",
        control="select",
        description="DeepSeek 思考模式开关（enabled/disabled）。",
        default=None,
        options=(("enabled", "启用"), ("disabled", "关闭")),
        providers=("deepseek",),
    ),
    FieldSpec(
        path="model.reasoning_effort",
        name="推理强度",
        group="optional",
        control="string",
        description="推理强度：OpenAI 兼容接口支持 minimal/low/medium/high；DeepSeek 支持 high/max。",
        default="",
        suggestions=("minimal", "low", "medium", "high", "max"),
        providers=("deepseek", "openai", "openai_compatible"),
    ),
    FieldSpec(
        path="model.send_reasoning_effort",
        name="发送推理强度",
        group="optional",
        control="bool",
        description="是否把 reasoning_effort 随请求发送（仅 OpenAI 与 OpenAI 兼容接口）。",
        default=False,
        options=_BOOL_OPTIONS,
        providers=("openai", "openai_compatible"),
    ),
    FieldSpec(
        path="model.enable_json_mode",
        name="JSON 模式",
        group="optional",
        control="bool",
        description="启用服务商 JSON 输出模式（按服务商能力决定是否生效）。",
        default=None,
        options=_BOOL_OPTIONS,
    ),
    FieldSpec(
        path="model.temperature",
        name="温度",
        group="optional",
        control="string",
        description='采样温度，以字符串形式写入 TOML（例如 "0.7"）；'
        "仅 aliyun/openai/openai_compatible 使用，需配合“发送温度”开关。",
        default="",
        suggestions=("0.1", "0.3", "0.5", "0.7", "1.0"),
        providers=("aliyun", "openai", "openai_compatible"),
    ),
    FieldSpec(
        path="model.send_temperature",
        name="发送温度",
        group="optional",
        control="bool",
        description="是否把 temperature 随请求发送（仅 aliyun/openai/openai_compatible）。",
        default=False,
        options=_BOOL_OPTIONS,
        providers=("aliyun", "openai", "openai_compatible"),
    ),
    FieldSpec(
        path="model.timeout",
        name="超时（秒）",
        group="optional",
        control="string",
        description='请求超时，以正数字符串形式写入 TOML（例如 "500"）。',
        default="",
        suggestions=("30", "60", "120", "300", "500"),
        providers=("aliyun", "openai", "openai_compatible"),
    ),
    FieldSpec(
        path="pdf_reader.dpi",
        name="页面渲染 DPI",
        group="optional",
        control="int",
        description="PDF 页面转图片的分辨率，数值越高越清晰但越慢。",
        default=200,
        suggestions=("150", "200", "300", "400"),
        minimum=1,
    ),
    FieldSpec(
        path="pdf_reader.cache_dir",
        name="缓存目录",
        group="optional",
        control="string",
        description="渲染缓存与临时文件目录；相对路径以运行数据根为基准。",
        default="cache",
        suggestions=("cache",),
    ),
    FieldSpec(
        path="translation.lang_in",
        name="源语言",
        group="optional",
        control="string",
        description="翻译源语言代码。",
        default="en",
        suggestions=("en", "zh", "ja", "ko", "fr", "de", "es", "ru"),
    ),
    FieldSpec(
        path="translation.lang_out",
        name="目标语言",
        group="optional",
        control="string",
        description="翻译目标语言代码。",
        default="zh",
        suggestions=("zh", "en", "ja", "ko", "fr", "de", "es", "ru"),
    ),
    FieldSpec(
        path="translation.min_text_length",
        name="最小翻译文本长度",
        group="optional",
        control="int",
        description="短于该长度的文本不参与翻译。",
        default=5,
        suggestions=("0", "5", "10", "20"),
        minimum=0,
    ),
    FieldSpec(
        path="translation.qps",
        name="主翻译每秒启动请求数",
        group="optional",
        control="int",
        description="主翻译每秒最多启动的请求数（不是并发数）；调高可能提速，也会增加 API 消耗与限流概率，"
        "实际吞吐还受线程池与响应耗时影响；>100 可保存，但请确认服务商配额。",
        default=4,
        suggestions=("1", "2", "4", "8", "16"),
        minimum=1,
    ),
    FieldSpec(
        path="translation.pool_max_workers",
        name="主翻译最大线程数",
        group="optional",
        control="int",
        description="主翻译最多同时工作的线程/worker 数；留空（推荐）时自动跟随 qps；增大只在请求较慢且 QPS "
        "允许时可能提高吞吐；>100 可保存，但风险较高。",
        default=None,
        suggestions=("2", "4", "8"),
        minimum=1,
    ),
    FieldSpec(
        path="translation.primary_font_family",
        name="主要字体",
        group="optional",
        control="select",
        description="翻译文本使用的主要字体族；auto 表示自动选择。",
        default="auto",
        options=(
            ("auto", "自动"),
            ("serif", "衬线"),
            ("sans-serif", "无衬线"),
            ("script", "手写体"),
        ),
    ),
    FieldSpec(
        path="translation.default_system_prompt",
        name="默认系统提示词",
        group="optional",
        control="string",
        description="可选；未提供自定义提示词时使用的系统提示词。",
        default="",
        suggestions=("/no_think default",),
    ),
    FieldSpec(
        path="term_extraction.enabled",
        name="候选术语旁路提取",
        group="optional",
        control="bool",
        description="开启后，正文翻译成功提交后会额外调用模型提取候选术语；"
        "候选不会自动影响正文，只进入 term_candidates.json，接受后才会进入有效词表。"
        "严格正文约束始终开启，本开关不能关闭它。兼容说明：未配置 [term_extraction] "
        "段时，本键跟随旧 translation.auto_extract_glossary 的显式值（1.x 兼容键，"
        "计划 2.0.0 移除，默认开启）；已配置本段时以本段为准。",
        default=True,
        options=_BOOL_OPTIONS,
    ),
    FieldSpec(
        path="term_extraction.timeout",
        name="候选提取超时（秒）",
        group="optional",
        control="float",
        description="单次候选提取请求的超时上限（1-120 秒）；只影响旁路候选，不影响正文。",
        default=30.0,
        suggestions=("10", "30", "60"),
        minimum=1.0,
        maximum=120.0,
    ),
    FieldSpec(
        path="term_extraction.qps",
        name="候选提取每秒请求数",
        group="optional",
        control="int",
        description="候选提取每秒最多启动的请求数（1-100），与正文 qps 完全独立；"
        "这是旧 translation.term_qps（1.x 兼容键，2.0.0 移除）的规范替代，"
        "旧键不再在配置中心展示或写入。",
        default=2,
        suggestions=("1", "2", "4"),
        minimum=1,
        maximum=100,
    ),
    FieldSpec(
        path="term_extraction.max_workers",
        name="候选提取并发上限",
        group="optional",
        control="int",
        description="候选提取同时进入提取的最大调用数（1-8）。首版同步执行，该值作为信号量上限；"
        "这是旧 translation.term_pool_max_workers（1.x 兼容键，2.0.0 移除）的规范替代，"
        "旧键不再在配置中心展示或写入。",
        default=1,
        suggestions=("1", "2", "4"),
        minimum=1,
        maximum=8,
    ),
    FieldSpec(
        path="term_extraction.retry_count",
        name="候选提取网络重试次数",
        group="optional",
        control="int",
        description="网络可重试次数（0-3）。只对超时/429/5xx 重试；连接类错误、4xx、响应格式错误与超限不重试。",
        default=1,
        suggestions=("0", "1", "2"),
        minimum=0,
        maximum=3,
    ),
    FieldSpec(
        path="term_extraction.max_input_chars",
        name="候选提取源文本上限",
        group="optional",
        control="int",
        description="送入候选提取模型的源文本最大字符数（1000-1000000）；超出后按前缀确定性截断。",
        default=80000,
        suggestions=("40000", "80000", "160000"),
        minimum=1000,
        maximum=1000000,
    ),
    FieldSpec(
        path="term_extraction.prompt",
        name="候选提取提示词",
        group="optional",
        control="string",
        description="候选提取使用的系统提示词；留空使用内置默认（要求领域术语、最小名词"
        "短语、排除普通词、JSON schema）。Prompt 原文不进入日志或错误响应。",
        default="",
    ),
    FieldSpec(
        path="server.host",
        name="监听地址",
        group="optional",
        control="string",
        description="服务监听地址；仅 loopback 会提示本地安全边界。",
        default="127.0.0.1",
        suggestions=("127.0.0.1", "0.0.0.0", "::1"),
    ),
    FieldSpec(
        path="server.port",
        name="监听端口",
        group="optional",
        control="int",
        description="服务监听端口（1-65535）。",
        default=5000,
        suggestions=("5000", "8000", "8080"),
        minimum=1,
        maximum=65535,
    ),
    FieldSpec(
        path="server.debug",
        name="调试模式",
        group="optional",
        control="bool",
        description="Flask 调试/热重载开关；生产使用请关闭。",
        default=False,
        options=_BOOL_OPTIONS,
    ),
    FieldSpec(
        path="pdf2zh.split_short_lines",
        name="拆分短行",
        group="advanced",
        control="bool",
        description="PDF 高级处理：按短行因子拆分短行。",
        default=False,
        options=_BOOL_OPTIONS,
    ),
    FieldSpec(
        path="pdf2zh.short_line_split_factor",
        name="短行拆分因子",
        group="advanced",
        control="float",
        description="短行判定因子（>= 0.1）。",
        default=0.8,
        suggestions=("0.6", "0.8", "0.9"),
        minimum=0.1,
    ),
    FieldSpec(
        path="pdf2zh.skip_clean",
        name="跳过清洗",
        group="advanced",
        control="bool",
        description="跳过 PDF 预处理清洗步骤。",
        default=False,
        options=_BOOL_OPTIONS,
    ),
    FieldSpec(
        path="pdf2zh.disable_rich_text_translate",
        name="禁用富文本翻译",
        group="advanced",
        control="bool",
        description="关闭富文本（样式）翻译能力。",
        default=False,
        options=_BOOL_OPTIONS,
    ),
    FieldSpec(
        path="pdf2zh.enhance_compatibility",
        name="增强兼容性",
        group="advanced",
        control="bool",
        description="启用兼容性更强的处理路径（可能更慢）。",
        default=False,
        options=_BOOL_OPTIONS,
    ),
    FieldSpec(
        path="pdf2zh.translate_table_text",
        name="翻译表格文本",
        group="advanced",
        control="bool",
        description="是否翻译表格内的文本。",
        default=True,
        options=_BOOL_OPTIONS,
    ),
    FieldSpec(
        path="pdf2zh.skip_scanned_detection",
        name="跳过扫描件检测",
        group="advanced",
        control="bool",
        description="跳过扫描件/OCR 场景检测。",
        default=False,
        options=_BOOL_OPTIONS,
    ),
    FieldSpec(
        path="pdf2zh.ocr_workaround",
        name="OCR 替代方案",
        group="advanced",
        control="bool",
        description="启用 OCR 替代处理路径。",
        default=False,
        options=_BOOL_OPTIONS,
    ),
    FieldSpec(
        path="pdf2zh.auto_enable_ocr_workaround",
        name="自动启用 OCR 替代方案",
        group="advanced",
        control="bool",
        description="检测到扫描件时自动启用 OCR 替代方案。",
        default=False,
        options=_BOOL_OPTIONS,
    ),
    FieldSpec(
        path="pdf2zh.no_merge_alternating_line_numbers",
        name="不合并交替行号",
        group="advanced",
        control="bool",
        description="禁止合并排版中的交替行号。",
        default=False,
        options=_BOOL_OPTIONS,
    ),
    FieldSpec(
        path="pdf2zh.skip_formula_offset_calculation",
        name="跳过公式偏移计算",
        group="advanced",
        control="bool",
        description="跳过公式与正文偏移计算。",
        default=False,
        options=_BOOL_OPTIONS,
    ),
    FieldSpec(
        path="pdf2zh.non_formula_line_iou_threshold",
        name="非公式行 IoU 阈值",
        group="advanced",
        control="float",
        description="非公式行判定阈值（0.0-1.0）。",
        default=0.9,
        suggestions=("0.7", "0.8", "0.9", "1.0"),
        minimum=0.0,
        maximum=1.0,
    ),
    FieldSpec(
        path="pdf2zh.figure_table_protection_threshold",
        name="图表保护阈值",
        group="advanced",
        control="float",
        description="图表区域保护判定阈值（0.0-1.0）。",
        default=0.9,
        suggestions=("0.7", "0.8", "0.9", "1.0"),
        minimum=0.0,
        maximum=1.0,
    ),
    FieldSpec(
        path="pdf2zh.formula_font_pattern",
        name="公式字体正则",
        group="advanced",
        control="string",
        description="可选；匹配公式字体的正则表达式。",
        default="",
    ),
    FieldSpec(
        path="pdf2zh.formula_char_pattern",
        name="公式字符正则",
        group="advanced",
        control="string",
        description="可选；匹配公式字符的正则表达式。",
        default="",
    ),
]

FIELDS_BY_PATH: dict[str, FieldSpec] = {spec.path: spec for spec in FIELD_SPECS}
SECTIONS: tuple[str, ...] = ("model", "pdf_reader", "translation", "server", "term_extraction", "pdf2zh")


class ConfigEditError(ValueError):
    """配置中心可安全展示的错误；message 绝不包含 API Key。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class RevisionConflictError(ConfigEditError):
    def __init__(self) -> None:
        super().__init__("revision_conflict", "配置已被其他会话修改，请刷新后重试")


def _read_raw(config_path: Path) -> bytes:
    try:
        return config_path.read_bytes()
    except FileNotFoundError:
        return b""
    except OSError:
        # 不把底层 OSError 文本（可能包含内部绝对路径）拼进响应/异常消息；
        # 服务端日志保留 traceback 供排查，但日志不包含文件内容与密钥。
        logger.exception("config read failed: path=%s", config_path)
        raise ConfigEditError("config_read_failed", "无法读取配置文件，请检查文件权限或磁盘状态") from None


def _bytes_revision(raw: bytes) -> str:
    if not raw:
        return "missing"
    return hashlib.sha256(raw).hexdigest()


def _parse_document(raw: bytes, config_path: Path) -> tomlkit.TOMLDocument:
    if not raw:
        return tomlkit.document()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ConfigEditError("config_read_failed", "配置文件不是有效的 UTF-8 文本") from exc
    try:
        parsed = tomlkit.parse(text)
    except ParseError as exc:
        # 不把解析器原文（可能包含 API Key 的片段）写入响应或日志。
        logger.warning("config parse failed: %s", type(exc).__name__)
        raise ConfigEditError(
            "config_read_failed",
            "配置文件 TOML 语法错误，请手动修复后重试",
        ) from exc
    if not isinstance(parsed, tomlkit.TOMLDocument):
        raise ConfigEditError("config_read_failed", "配置文件内容不是 TOML 文档")
    return parsed


def _section_value(data: dict, section: str) -> dict:
    raw = data.get(section, {})
    return raw if isinstance(raw, dict) else {}


def _api_key_status(data: dict) -> dict:
    env_key = os.environ.get("MODEL_API_KEY")
    if env_key is not None:
        return {"source": "environment", "configured": bool(env_key.strip())}
    file_key = _section_value(data, "model").get("api_key", "")
    if isinstance(file_key, str) and file_key.strip():
        return {"source": "file", "configured": True}
    return {"source": "missing", "configured": False}


def load_config_state(config_path: Path | None = None) -> dict:
    """返回 schema + 脱敏当前值 + revision + 环境变量覆盖状态。"""
    path = Path(config_path) if config_path is not None else config.CONFIG_PATH
    raw = _read_raw(path)
    doc = _parse_document(raw, path)
    data = tomllib.loads(tomlkit.dumps(doc))
    values: dict[str, dict] = {}
    for spec in FIELD_SPECS:
        section, key = spec.path.split(".", 1)
        section_data = _section_value(data, section)
        if spec.secret:
            value: Any = _api_key_status(data)
        else:
            value = section_data.get(key, spec.default if spec.default is not None else "")
        values.setdefault(section, {})[key] = value
    return {
        "schema": [spec.to_dict() for spec in FIELD_SPECS],
        "values": values,
        "revision": _bytes_revision(raw),
        "env_overrides": {"MODEL_API_KEY": os.environ.get("MODEL_API_KEY") is not None},
    }


def _ensure_table(doc: tomlkit.TOMLDocument, section: str) -> tomlkit.items.Table:
    existing = doc.get(section)
    if existing is None:
        table = tomlkit.table()
        doc[section] = table
        return table
    if not isinstance(existing, tomlkit.items.Table):
        raise ConfigEditError("invalid_section", f"[{section}] 必须是 TOML table，无法写入配置字段")
    return existing


def _coerce_value(path: str, spec: FieldSpec, value: Any) -> Any:
    if spec.control == "bool":
        if not isinstance(value, bool):
            raise ConfigEditError("invalid_config", f"{path} 必须是布尔值 true 或 false")
        return value
    if spec.control == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigEditError("invalid_config", f"{path} 必须是非布尔整数")
        if spec.minimum is not None and value < spec.minimum:
            raise ConfigEditError("invalid_config", f"{path} 必须不小于 {spec.minimum:g}")
        if spec.maximum is not None and value > spec.maximum:
            raise ConfigEditError("invalid_config", f"{path} 必须不大于 {spec.maximum:g}")
        return value
    if spec.control == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigEditError("invalid_config", f"{path} 必须是非布尔数值")
        number = float(value)
        if not math.isfinite(number):
            raise ConfigEditError("invalid_config", f"{path} 必须是有限数值")
        if spec.minimum is not None and number < spec.minimum:
            raise ConfigEditError("invalid_config", f"{path} 必须不小于 {spec.minimum:g}")
        if spec.maximum is not None and number > spec.maximum:
            raise ConfigEditError("invalid_config", f"{path} 必须不大于 {spec.maximum:g}")
        return number
    if spec.control in ("select", "string", "password"):
        if not isinstance(value, str):
            raise ConfigEditError("invalid_config", f"{path} 必须是非空字符串")
        return value
    raise ConfigEditError("invalid_config", f"{path} 使用了未知控件类型")


def _apply_values(
    doc: tomlkit.TOMLDocument,
    values: dict,
    api_key: str | None,
) -> None:
    for section_name, section_values in values.items():
        if section_name not in SECTIONS:
            raise ConfigEditError("unknown_field", f"配置中心不支持的字段: {section_name}")
        if not isinstance(section_values, dict):
            raise ConfigEditError("invalid_payload", f"{section_name} 必须是字段对象")
        for key, value in section_values.items():
            path = f"{section_name}.{key}"
            spec = FIELDS_BY_PATH.get(path)
            if spec is None:
                raise ConfigEditError("unknown_field", f"配置中心不支持的字段: {path}")
            if spec.secret:
                raise ConfigEditError(
                    "api_key_via_values",
                    "API Key 请通过请求顶层 api_key 字段提交",
                )
            table = _ensure_table(doc, section_name)
            if value is None:
                if spec.group == "required":
                    raise ConfigEditError("invalid_payload", f"{path} 不能为空（必填）")
                if key in table:
                    table.remove(key)
                continue
            table[key] = _coerce_value(path, spec, value)

    if api_key is not None:
        if not isinstance(api_key, str):
            raise ConfigEditError("invalid_payload", "api_key 必须是字符串")
        stripped = api_key.strip()
        if stripped:
            table = _ensure_table(doc, "model")
            table["api_key"] = stripped


def _known_subset(data: dict) -> dict:
    """只把已知 section/字段交给既有校验器，文件中的未知字段原样保留。"""
    subset: dict[str, dict] = {}
    for section, known_keys in config._KNOWN_SECTION_KEYS.items():
        raw = data.get(section)
        if isinstance(raw, dict):
            subset[section] = {k: v for k, v in raw.items() if k in known_keys}
    return subset


def _validate_merged(doc: tomlkit.TOMLDocument) -> None:
    plain = tomllib.loads(tomlkit.dumps(doc))
    subset = _known_subset(plain)
    try:
        config.validate_startup_requirements(subset)
        config.resolve_server_config(subset)
    except config.ConfigError as exc:
        raise ConfigEditError("invalid_config", str(exc)) from exc


def _atomic_write(config_path: Path, content: bytes) -> None:
    mode = None
    try:
        mode = stat.S_IMODE(config_path.stat().st_mode)
    except FileNotFoundError:
        pass
    directory = config_path.parent
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{config_path.name}.",
        suffix=".tmp",
        dir=directory,
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        if mode is not None:
            os.chmod(tmp_path, mode)
        os.replace(tmp_path, config_path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def save_config(payload: dict, config_path: Path | None = None) -> dict:
    """校验并原子保存白名单配置；成功返回 restart_required=true 与新 revision。"""
    if not isinstance(payload, dict):
        raise ConfigEditError("invalid_payload", "请求体必须是 JSON 对象")
    values = payload.get("values")
    revision = payload.get("revision")
    api_key = payload.get("api_key")
    if not isinstance(values, dict):
        raise ConfigEditError("invalid_payload", "values 必须是字段对象")
    if not isinstance(revision, str) or not revision:
        raise ConfigEditError("invalid_payload", "revision 必须是非空字符串")
    if api_key is not None and not isinstance(api_key, str):
        raise ConfigEditError("invalid_payload", "api_key 必须是字符串")

    path = Path(config_path) if config_path is not None else config.CONFIG_PATH
    with _write_lock:
        raw = _read_raw(path)
        if revision != _bytes_revision(raw):
            raise RevisionConflictError()
        doc = _parse_document(raw, path)
        _apply_values(doc, values, api_key)
        _validate_merged(doc)
        content = tomlkit.dumps(doc).encode("utf-8")
        try:
            _atomic_write(path, content)
        except OSError as exc:
            logger.error("config write failed: %s", exc)
            raise ConfigEditError(
                "config_write_failed",
                "配置文件写入失败，原文件未被修改",
            ) from exc
    logger.info("config.toml saved via config center (restart_required=true)")
    return {
        "ok": True,
        "restart_required": True,
        "revision": _bytes_revision(content),
    }
