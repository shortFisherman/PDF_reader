"""P1-01 项目自有候选术语提取客户端。

边界：
- 只走 OpenAI-compatible ``POST /chat/completions`` 受控请求，使用标准库
  ``urllib``，不新增依赖，不修改/复制/依赖 BabelDOC 深层私有类；
- 首版支持 provider：``deepseek`` / ``openai`` / ``openai_compatible``；
  其余 provider 由调用方稳定降级为 unsupported，不影响正文翻译；
- 网络重试只针对超时/429/5xx；连接类错误、4xx 与响应解析/schema 错误不重试；
- 请求体、响应正文、Prompt、源文本与 API Key 永不进入日志或异常消息。
"""

from __future__ import annotations

import json
import logging
import socket
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from pdf_reader.config import CandidateExtractionRuntimeConfig, ModelRuntimeConfig
from pdf_reader.term_model import TermStoreError, normalize_source_key, validate_term_text

logger = logging.getLogger("pdf_reader.term_extraction")

SUPPORTED_PROVIDERS = frozenset({"deepseek", "openai", "openai_compatible"})
DEFAULT_BASE_URLS: dict[str, str] = {
    "deepseek": "https://api.deepseek.com/v1",
    "openai": "https://api.openai.com/v1",
}
CHAT_COMPLETIONS_PATH = "/chat/completions"
MAX_RESPONSE_BYTES = 256 * 1024
MAX_TERMS = 50
MAX_TERM_LENGTH = 200
STRATEGY_VERSION = "term-extraction-client/1"
_READ_CHUNK_BYTES = 64 * 1024

DEFAULT_EXTRACTION_PROMPT = (
    "你是 PDF 领域术语提取助手。从给定的英文 PDF 文本中提取专业领域术语，"
    "只输出一个 JSON 对象，不要输出任何其他文本、解释或 Markdown 代码块。\n"
    'JSON 结构：{"terms": [{"source": "...", "target": "..."}]}\n'
    "要求：\n"
    "1. source 必须是文本中真实出现的英文领域术语或最小名词短语，保留原文大小写；\n"
    "2. target 是简体中文领域译法，必须非空；\n"
    "3. 优先提取医学/专业技术术语、专有名词、缩写、疾病/药物/指南/学科术语；\n"
    "4. 排除普通词、功能词、完整句子和上下文短语；\n"
    "5. 最多返回 30 条；不得编造文本中不存在的 source。"
)

UrlOpen = Callable[..., Any]
Sleep = Callable[[float], None]


class TermExtractionError(RuntimeError):
    """候选提取失败基类；消息只含稳定原因，不包含正文/Prompt/响应/凭据。"""


class UnsupportedProviderError(TermExtractionError):
    """当前 provider 不支持候选提取；调用方降级且不影响正文。"""


class TermExtractionRequestError(TermExtractionError):
    """网络/超时/HTTP 状态错误。"""


class TermExtractionParseError(TermExtractionError):
    """响应正文过大、非 JSON 或不符合受控 schema。"""


@dataclass(frozen=True)
class TermCandidate:
    """一条通过受控 schema 校验的候选术语（页码由服务层附加）。"""

    source: str
    target: str


@dataclass(frozen=True)
class TokenUsage:
    """chat completions 响应中的 token 用量。

    契约：三个字段全部为非负 int 才视为可用（``available`` 三者全真）；
    解析器只在该条件下构造对象，缺失/部分/非法一律返回 ``None``。
    """

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None

    @property
    def available(self) -> bool:
        return all(
            value is not None and not isinstance(value, bool) and isinstance(value, int) and value >= 0
            for value in (self.prompt_tokens, self.completion_tokens, self.total_tokens)
        )


@dataclass(frozen=True)
class TermExtractionResult:
    """一次候选提取的完整结果：受控术语列表 + 可选 token 用量。"""

    terms: list[TermCandidate]
    usage: TokenUsage | None = None


class _RateLimiter:
    """进程内简单令牌间隔限速：两次请求之间至少间隔 ``1 / qps`` 秒。"""

    def __init__(self, qps: int, sleep: Sleep = time.sleep) -> None:
        self._interval = 1.0 / max(1, qps)
        self._lock = threading.Lock()
        self._next_at = 0.0
        self._sleep = sleep

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            target = max(now, self._next_at)
            delay = target - now
            self._next_at = target + self._interval
        if delay > 0:
            self._sleep(delay)


def _is_retryable_transport_error(exc: BaseException) -> bool:
    """只有超时类传输错误可重试；连接类/其他 OSError/URLError 立即失败。"""
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return True
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        if isinstance(reason, BaseException):
            return _is_retryable_transport_error(reason)
        return isinstance(reason, str) and reason.lower() == "timed out"
    return False


def _build_chat_completions_url(base: str) -> str:
    """严格校验并拼接 OpenAI-compatible chat completions 端点。

    只允许 http/https 且带 netloc；拒绝 userinfo/query/fragment。路径规则：
    ``/v1``、``/v1/`` 均得到 ``/v1/chat/completions``；已是
    ``/chat/completions``（含尾斜杠）保持不变；无路径时补 ``/v1``。
    """
    parts = urlsplit(base.strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise TermExtractionError("invalid base_url")
    if parts.username is not None or parts.password is not None or parts.query or parts.fragment:
        raise TermExtractionError("invalid base_url")
    path = parts.path.rstrip("/") or "/v1"
    if not path.endswith(CHAT_COMPLETIONS_PATH):
        path = path + CHAT_COMPLETIONS_PATH
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


class TermExtractionClient:
    """项目自有候选提取客户端：受控 JSON 请求 + 严格响应解析 + 有界重试。"""

    def __init__(
        self,
        model_cfg: ModelRuntimeConfig,
        cfg: CandidateExtractionRuntimeConfig,
        *,
        urlopen: UrlOpen | None = None,
        sleep: Sleep = time.sleep,
    ) -> None:
        self._model_cfg = model_cfg
        self._cfg = cfg
        self._urlopen = urlopen or urllib.request.urlopen
        self._limiter = _RateLimiter(cfg.qps, sleep=sleep)
        self._sleep = sleep

    @property
    def supported(self) -> bool:
        return self._model_cfg.provider in SUPPORTED_PROVIDERS

    def extract_terms(self, text: str) -> list[TermCandidate]:
        """执行一次候选提取；失败抛 ``TermExtractionError`` 子类。"""
        return self.extract_terms_with_usage(text).terms

    def extract_terms_with_usage(self, text: str) -> TermExtractionResult:
        """执行一次候选提取并返回术语与可选 token 用量；失败抛 ``TermExtractionError`` 子类。"""
        if not self.supported:
            raise UnsupportedProviderError(f"unsupported provider: {self._model_cfg.provider}")
        # 客户端自身也强制确定性前缀截断（service 层同样截断，双保险），
        # 保证任何调用方都不会把超限文本送入请求。
        text = text[: self._cfg.max_input_chars]
        url = self._endpoint_url()
        payload = self._request_payload(text)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._model_cfg.api_key}",
            },
        )
        total_attempts = self._cfg.retry_count + 1
        last_error: TermExtractionRequestError | None = None
        for attempt in range(1, total_attempts + 1):
            self._limiter.wait()
            try:
                response = self._urlopen(request, timeout=self._cfg.timeout)
                try:
                    raw = self._read_bounded(response)
                    return parse_model_response_with_usage(raw)
                finally:
                    response.close()
            except TermExtractionParseError:
                # 响应不可用属于确定性错误，重试无意义，不重试。
                raise
            except urllib.error.HTTPError as exc:
                try:
                    exc.close()
                except Exception:
                    pass
                if exc.code != 429 and not 500 <= exc.code <= 599:
                    raise TermExtractionRequestError(f"http status {exc.code}") from exc
                last_error = TermExtractionRequestError(f"http status {exc.code}")
            except (urllib.error.URLError, OSError) as exc:
                # 只有超时类错误（TimeoutError/socket.timeout 或
                # URLError.reason 为超时）可重试；连接类/其他 OSError
                # 立即失败，避免对确定性故障做无意义重试。
                if _is_retryable_transport_error(exc):
                    last_error = TermExtractionRequestError("request timed out")
                else:
                    raise TermExtractionRequestError("request failed") from exc
            if attempt < total_attempts:
                self._sleep(self._backoff(attempt))
            else:
                assert last_error is not None
                raise last_error
        assert last_error is not None
        raise last_error

    def _endpoint_url(self) -> str:
        provider = self._model_cfg.provider
        base = self._model_cfg.base_url
        if provider == "openai_compatible" and not base:
            raise TermExtractionError("openai_compatible requires base_url for candidate extraction")
        if not base:
            base = DEFAULT_BASE_URLS.get(provider)
            if base is None:
                raise UnsupportedProviderError(f"unsupported provider: {provider}")
        return _build_chat_completions_url(base)

    def _request_payload(self, text: str) -> dict[str, object]:
        prompt = (self._cfg.prompt or DEFAULT_EXTRACTION_PROMPT).strip()
        return {
            "model": self._model_cfg.model,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": text},
            ],
            "stream": False,
        }

    def _read_bounded(self, response: Any) -> bytes:
        content_length = response.headers.get("Content-Length")
        if content_length is not None:
            try:
                length = int(content_length)
            except ValueError as exc:
                raise TermExtractionParseError("invalid content length") from exc
            if length > MAX_RESPONSE_BYTES:
                raise TermExtractionParseError("response too large")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = response.read(_READ_CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                raise TermExtractionParseError("response too large")
            chunks.append(chunk)
        return b"".join(chunks)

    def _extract_content(self, raw: bytes) -> str:
        return _extract_content(raw)

    def _parse_terms(self, content: str) -> list[TermCandidate]:
        return _parse_terms(content)

    @staticmethod
    def _backoff(attempt: int) -> float:
        return min(0.5 * float(2 ** (attempt - 1)), 4.0)


def parse_model_response(raw: bytes) -> list[TermCandidate]:
    """P2-01 公开纯解析入口：从受控 chat completions 响应体提取并解析术语。

    与 ``TermExtractionClient.extract_terms`` 共用同一套受控 JSON 解析，
    供离线黄金样本质量评测复用；不执行任何网络请求。
    """
    return _parse_terms(_extract_content(raw))


def parse_model_response_with_usage(raw: bytes) -> TermExtractionResult:
    """公开纯解析入口：术语 + 可选 token 用量。

    usage 属于可选诊断信息：缺失、非法或畸形时返回 ``None``（unavailable），
    绝不伪造计数，也绝不让 usage 问题影响术语解析。
    """
    return TermExtractionResult(
        terms=_parse_terms(_extract_content(raw)),
        usage=_extract_usage(raw),
    )


def _extract_content(raw: bytes) -> str:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise TermExtractionParseError("invalid JSON response") from exc
    if not isinstance(data, dict):
        raise TermExtractionParseError("invalid JSON response")
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise TermExtractionParseError("invalid choices")
    choice = choices[0]
    if not isinstance(choice, dict):
        raise TermExtractionParseError("invalid choices")
    message = choice.get("message")
    if not isinstance(message, dict):
        raise TermExtractionParseError("invalid message")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise TermExtractionParseError("empty message content")
    return content


def _extract_usage(raw: bytes) -> TokenUsage | None:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    usage = data.get("usage")
    if not isinstance(usage, dict):
        return None
    values: list[int] = []
    for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
        parsed = _non_negative_int(usage.get(name))
        if parsed is None:
            return None
        values.append(parsed)
    return TokenUsage(prompt_tokens=values[0], completion_tokens=values[1], total_tokens=values[2])


def _non_negative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _parse_terms(content: str) -> list[TermCandidate]:
    try:
        data = json.loads(content)
    except ValueError as exc:
        raise TermExtractionParseError("invalid terms JSON") from exc
    if not isinstance(data, dict):
        raise TermExtractionParseError("invalid terms JSON")
    raw_terms = data.get("terms")
    if not isinstance(raw_terms, list):
        raise TermExtractionParseError("invalid terms")
    if len(raw_terms) > MAX_TERMS:
        raise TermExtractionParseError("too many terms")
    result: list[TermCandidate] = []
    seen: set[tuple[str, str]] = set()
    for item in raw_terms:
        if not isinstance(item, dict):
            raise TermExtractionParseError("invalid term item")
        if set(item) != {"source", "target"}:
            raise TermExtractionParseError("invalid term item")
        source = item.get("source")
        target = item.get("target")
        if not isinstance(source, str) or not isinstance(target, str):
            raise TermExtractionParseError("invalid term fields")
        if len(source) > MAX_TERM_LENGTH or len(target) > MAX_TERM_LENGTH:
            raise TermExtractionParseError("term too long")
        try:
            source = validate_term_text(source, "source")
            target = validate_term_text(target, "target")
        except TermStoreError as exc:
            raise TermExtractionParseError("invalid term fields") from exc
        key = (normalize_source_key(source), target)
        if key in seen:
            continue
        seen.add(key)
        result.append(TermCandidate(source=source, target=target))
    return result
