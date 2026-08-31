"""P1-01 候选提取客户端：fake local HTTP server，不联网、无真实 API Key。"""

from __future__ import annotations

import io
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Never
from urllib.error import HTTPError, URLError

import pytest

from pdf_reader.config import CandidateExtractionRuntimeConfig, ModelRuntimeConfig
from pdf_reader.term_extraction import (
    MAX_RESPONSE_BYTES,
    MAX_TERMS,
    TermCandidate,
    TermExtractionClient,
    TermExtractionError,
    TermExtractionParseError,
    TermExtractionRequestError,
    UnsupportedProviderError,
    _build_chat_completions_url,
    _RateLimiter,
)


class _FakeHandler(BaseHTTPRequestHandler):
    responses: list[tuple[int, bytes, dict[str, str]]] = []
    requests: list[tuple[str, bytes, dict[str, str]]] = []
    sleep_seconds: float = 0.0

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        type(self).requests.append((self.path, body, dict(self.headers)))
        if self.sleep_seconds:
            time.sleep(self.sleep_seconds)
        status, payload, extra_headers = type(self).responses.pop(0)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        for key, value in extra_headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        try:
            self.wfile.write(payload)
        except OSError:
            return

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return


@pytest.fixture
def fake_server():
    _FakeHandler.responses = []
    _FakeHandler.requests = []
    _FakeHandler.sleep_seconds = 0.0
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeHandler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _model(
    provider: str = "openai_compatible",
    *,
    base_url: str | None = None,
    api_key: str = "sk-test-key",
    model: str = "test-model",
) -> ModelRuntimeConfig:
    return ModelRuntimeConfig(provider=provider, api_key=api_key, model=model, base_url=base_url)


def _cfg(**overrides: object) -> CandidateExtractionRuntimeConfig:
    values: dict[str, object] = {
        "enabled": True,
        "timeout": 30.0,
        "qps": 100,
        "max_workers": 1,
        "retry_count": 1,
        "max_input_chars": 80_000,
        "prompt": None,
    }
    values.update(overrides)
    return CandidateExtractionRuntimeConfig(**values)  # type: ignore[arg-type]


def _ok_response(terms: list[dict[str, str]]) -> tuple[int, bytes, dict[str, str]]:
    content = json.dumps({"terms": terms}, ensure_ascii=False)
    payload = json.dumps({"choices": [{"message": {"content": content}}]}, ensure_ascii=False).encode("utf-8")
    return 200, payload, {}


def _client(
    fake_server: str,
    *,
    provider: str = "openai_compatible",
    retry_count: int = 1,
    timeout: float = 30.0,
    qps: int = 100,
    max_input_chars: int = 80_000,
    sleep: object | None = None,
) -> TermExtractionClient:
    model = _model(provider, base_url=fake_server)
    kwargs: dict[str, object] = {
        "retry_count": retry_count,
        "timeout": timeout,
        "qps": qps,
        "max_input_chars": max_input_chars,
    }
    client_kwargs: dict[str, object] = {}
    if sleep is not None:
        client_kwargs["sleep"] = sleep
    return TermExtractionClient(model, _cfg(**kwargs), **client_kwargs)  # type: ignore[arg-type]


class _SpyResponse:
    """可注入 urlopen 的受控响应，记录 close 调用。"""

    def __init__(self, payload: bytes, *, content_length: int | None = None) -> None:
        self._payload = payload
        self._offset = 0
        self.closed = False
        self.headers = {"Content-Length": str(content_length if content_length is not None else len(payload))}

    def read(self, size: int = -1) -> bytes:
        if self.closed:
            raise ValueError("read after close")
        if size is None or size < 0:
            size = len(self._payload) - self._offset
        chunk = self._payload[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk

    def close(self) -> None:
        self.closed = True


def _client_with_urlopen(
    urlopen: object,
    *,
    retry_count: int = 1,
    max_input_chars: int = 80_000,
) -> TermExtractionClient:
    return TermExtractionClient(
        _model(base_url="http://127.0.0.1:1/v1"),
        _cfg(retry_count=retry_count, max_input_chars=max_input_chars),
        urlopen=urlopen,  # type: ignore[arg-type]
        sleep=lambda _seconds: None,
    )


def test_request_schema_endpoint_and_auth_header(fake_server):
    _FakeHandler.responses.append(_ok_response([{"source": "AD", "target": "阿尔茨海默病"}]))
    client = _client(fake_server)
    result = client.extract_terms("AD appears in the guideline.")

    assert result == [TermCandidate(source="AD", target="阿尔茨海默病")]
    path, body, headers = _FakeHandler.requests[0]
    assert path == "/v1/chat/completions"
    assert headers["Authorization"] == "Bearer sk-test-key"
    assert headers["Content-Type"] == "application/json"
    payload = json.loads(body)
    assert payload["model"] == "test-model"
    assert payload["stream"] is False
    assert payload["messages"][0]["role"] == "system"
    assert "JSON" in payload["messages"][0]["content"]
    assert payload["messages"][1] == {"role": "user", "content": "AD appears in the guideline."}
    assert "sk-test-key" not in body.decode("utf-8") or "Authorization" not in json.dumps(payload)


def test_default_base_urls_and_duplicate_v1_protection():
    deepseek = TermExtractionClient(_model("deepseek"), _cfg())
    openai = TermExtractionClient(_model("openai"), _cfg())
    assert deepseek._endpoint_url() == "https://api.deepseek.com/v1/chat/completions"
    assert openai._endpoint_url() == "https://api.openai.com/v1/chat/completions"

    trailing = TermExtractionClient(_model("openai_compatible", base_url="http://x.example/v1/"), _cfg())
    assert trailing._endpoint_url() == "http://x.example/v1/chat/completions"
    already = TermExtractionClient(
        _model("openai_compatible", base_url="http://x.example/v1/chat/completions"),
        _cfg(),
    )
    assert already._endpoint_url() == "http://x.example/v1/chat/completions"


def test_openai_compatible_missing_base_url_raises():
    client = TermExtractionClient(_model("openai_compatible", base_url=None), _cfg())
    with pytest.raises(TermExtractionError, match="base_url"):
        client._endpoint_url()


def test_parse_dedupes_and_strips():
    client = TermExtractionClient(
        _model("openai_compatible", base_url="http://localhost:1/v1"),
        _cfg(),
    )
    terms = client._parse_terms(
        json.dumps(
            {
                "terms": [
                    {"source": " AD ", "target": " 特应性皮炎 "},
                    {"source": "ad", "target": "特应性皮炎"},
                    {"source": "TCS", "target": "外用糖皮质激素"},
                ]
            }
        )
    )
    assert terms == [
        TermCandidate(source="AD", target="特应性皮炎"),
        TermCandidate(source="TCS", target="外用糖皮质激素"),
    ]


def test_unsupported_provider_raises():
    client = TermExtractionClient(_model("zhipu", base_url=None), _cfg())
    assert client.supported is False
    with pytest.raises(UnsupportedProviderError):
        client.extract_terms("text")


def test_429_retries_then_succeeds(fake_server):
    _FakeHandler.responses.append((429, b"", {}))
    _FakeHandler.responses.append(_ok_response([{"source": "AD", "target": "阿尔茨海默病"}]))
    client = _client(fake_server, sleep=lambda _seconds: None)
    result = client.extract_terms("AD text")
    assert result == [TermCandidate(source="AD", target="阿尔茨海默病")]
    assert len(_FakeHandler.requests) == 2


def test_5xx_retries_then_succeeds(fake_server):
    _FakeHandler.responses.append((503, b"", {}))
    _FakeHandler.responses.append(_ok_response([{"source": "TCS", "target": "外用糖皮质激素"}]))
    client = _client(fake_server, sleep=lambda _seconds: None)
    result = client.extract_terms("TCS text")
    assert result[0].source == "TCS"
    assert len(_FakeHandler.requests) == 2


def test_4xx_does_not_retry(fake_server):
    _FakeHandler.responses.append((400, b'{"error":"bad request"}', {}))
    _FakeHandler.responses.append(_ok_response([{"source": "AD", "target": "阿尔茨海默病"}]))
    client = _client(fake_server, sleep=lambda _seconds: None)
    with pytest.raises(TermExtractionRequestError, match="400"):
        client.extract_terms("AD text")
    assert len(_FakeHandler.requests) == 1


def test_timeout_retries_within_bounds(fake_server):
    _FakeHandler.sleep_seconds = 0.25
    _FakeHandler.responses.append(_ok_response([{"source": "AD", "target": "阿尔茨海默病"}]))
    _FakeHandler.responses.append(_ok_response([{"source": "AD", "target": "阿尔茨海默病"}]))
    client = _client(fake_server, timeout=0.05, sleep=lambda _seconds: None)
    with pytest.raises(TermExtractionRequestError, match="request timed out"):
        client.extract_terms("AD text")
    assert len(_FakeHandler.requests) == 2


def test_malformed_content_no_retry(fake_server):
    _FakeHandler.responses.append((200, b'{"choices":[{"message":{"content":"not-json"}}]}', {}))
    _FakeHandler.responses.append(_ok_response([{"source": "AD", "target": "阿尔茨海默病"}]))
    client = _client(fake_server)
    with pytest.raises(TermExtractionParseError, match="terms JSON"):
        client.extract_terms("text")
    assert len(_FakeHandler.requests) == 1


def test_invalid_top_level_json_no_retry(fake_server):
    _FakeHandler.responses.append((200, b"not json at all", {}))
    client = _client(fake_server)
    with pytest.raises(TermExtractionParseError, match="JSON"):
        client.extract_terms("text")
    assert len(_FakeHandler.requests) == 1


def test_oversize_response_no_retry(fake_server):
    payload = json.dumps({"choices": [{"message": {"content": "x" * (MAX_RESPONSE_BYTES + 1)}}]}).encode("utf-8")
    _FakeHandler.responses.append((200, payload, {}))
    client = _client(fake_server)
    with pytest.raises(TermExtractionParseError, match="too large"):
        client.extract_terms("text")
    assert len(_FakeHandler.requests) == 1


@pytest.mark.parametrize(
    "terms",
    [
        "not-a-list",
        [{"source": "AD", "target": "阿尔茨海默病", "extra": 1}],
        [{"source": "AD"}],
        [{"source": 1, "target": "阿尔茨海默病"}],
        [{"source": "AD", "target": 2}],
        [{"source": "AD\nX", "target": "阿尔茨海默病"}],
        [{"source": "AD", "target": "阿尔茨海默病"}, {"source": "TCS"}],
        [{"source": "A" * 201, "target": "阿尔茨海默病"}],
        [{"source": "AD", "target": "B" * 201}],
    ],
)
def test_invalid_term_schema_rejected(fake_server, terms):
    content = json.dumps({"terms": terms}, ensure_ascii=False)
    payload = json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8")
    _FakeHandler.responses.append((200, payload, {}))
    client = _client(fake_server)
    with pytest.raises(TermExtractionParseError):
        client.extract_terms("text")
    assert len(_FakeHandler.requests) == 1


def test_too_many_terms_rejected(fake_server):
    terms = [{"source": f"T{i}", "target": "译法"} for i in range(MAX_TERMS + 1)]
    _FakeHandler.responses.append(_ok_response(terms))
    client = _client(fake_server)
    with pytest.raises(TermExtractionParseError, match="too many"):
        client.extract_terms("text")
    assert len(_FakeHandler.requests) == 1


def test_http_error_message_never_leaks_key_or_body(fake_server):
    _FakeHandler.responses.append((400, b'{"error":"sk-super-secret-body"}', {}))
    client = _client(fake_server)
    with pytest.raises(TermExtractionError) as excinfo:
        client.extract_terms("text")
    assert "sk-test-key" not in str(excinfo.value)
    assert "sk-super-secret-body" not in str(excinfo.value)
    assert "400" in str(excinfo.value)


def test_rate_limiter_intervals():
    slept: list[float] = []
    limiter = _RateLimiter(qps=2, sleep=slept.append)
    limiter.wait()
    limiter.wait()
    assert len(slept) == 1
    assert slept[0] >= 0.49


def _ok_payload() -> bytes:
    content = json.dumps({"terms": [{"source": "AD", "target": "阿尔茨海默病"}]}, ensure_ascii=False)
    return json.dumps({"choices": [{"message": {"content": content}}]}, ensure_ascii=False).encode("utf-8")


def test_success_response_is_closed():
    response = _SpyResponse(_ok_payload())
    calls: list[int] = []

    def urlopen(request, timeout) -> _SpyResponse:  # noqa: ANN001, ANN002
        calls.append(1)
        return response

    client = _client_with_urlopen(urlopen)
    result = client.extract_terms("AD text")

    assert result == [TermCandidate(source="AD", target="阿尔茨海默病")]
    assert len(calls) == 1
    assert response.closed is True


def test_parse_failure_response_is_closed():
    response = _SpyResponse(b'{"choices":[{"message":{"content":"not-json"}}]}')
    client = _client_with_urlopen(lambda request, timeout: response)  # type: ignore[arg-type]
    with pytest.raises(TermExtractionParseError):
        client.extract_terms("text")
    assert response.closed is True


def test_oversize_response_is_closed():
    response = _SpyResponse(b"{}", content_length=MAX_RESPONSE_BYTES + 1)
    client = _client_with_urlopen(lambda request, timeout: response)  # type: ignore[arg-type]
    with pytest.raises(TermExtractionParseError, match="too large"):
        client.extract_terms("text")
    assert response.closed is True


def test_http_error_response_is_closed():
    fp = io.BytesIO(b'{"error":"secret-body"}')
    headers = {"Content-Type": "application/json"}

    def urlopen(request, timeout) -> Never:  # noqa: ANN001, ANN002
        raise HTTPError("http://example.invalid/v1/chat/completions", 400, "Bad Request", headers, fp)

    client = _client_with_urlopen(urlopen, retry_count=1)
    with pytest.raises(TermExtractionRequestError, match="400"):
        client.extract_terms("text")
    assert fp.closed


def test_timeout_errors_retry_and_recover():
    cases = [
        TimeoutError("timed out"),
        URLError(TimeoutError("timed out")),
        URLError("timed out"),
    ]
    for error in cases:
        calls: list[int] = []

        def urlopen(request, timeout) -> _SpyResponse:  # noqa: ANN001, ANN002
            calls.append(1)
            if len(calls) == 1:
                raise error
            return _SpyResponse(_ok_payload())

        client = _client_with_urlopen(urlopen)
        result = client.extract_terms("AD text")
        assert len(calls) == 2
        assert result[0].source == "AD"


def test_connection_errors_do_not_retry():
    cases = [
        ConnectionResetError("reset"),
        URLError(ConnectionResetError("reset")),
        OSError("broken pipe"),
    ]
    for error in cases:
        calls: list[int] = []

        def urlopen(request, timeout) -> Never:  # noqa: ANN001, ANN002
            calls.append(1)
            raise error

        client = _client_with_urlopen(urlopen, retry_count=3)
        with pytest.raises(TermExtractionRequestError, match="request failed"):
            client.extract_terms("text")
        assert len(calls) == 1


def test_client_truncates_input_to_max_input_chars(fake_server):
    _FakeHandler.responses.append(_ok_response([{"source": "AD", "target": "阿尔茨海默病"}]))
    client = _client(fake_server, max_input_chars=50)
    result = client.extract_terms("AD " * 100)

    assert result[0].source == "AD"
    _, body, _ = _FakeHandler.requests[0]
    user_content = json.loads(body)["messages"][1]["content"]
    assert len(user_content) <= 50
    assert user_content.startswith("AD ")


def test_build_chat_completions_url_paths():
    cases = {
        "http://127.0.0.1:8123/v1": "http://127.0.0.1:8123/v1/chat/completions",
        "http://127.0.0.1:8123/v1/": "http://127.0.0.1:8123/v1/chat/completions",
        "http://127.0.0.1:8123/chat/completions": "http://127.0.0.1:8123/chat/completions",
        "http://127.0.0.1:8123/v1/chat/completions/": "http://127.0.0.1:8123/v1/chat/completions",
        "http://127.0.0.1:8123": "http://127.0.0.1:8123/v1/chat/completions",
        "https://api.example.com/v1": "https://api.example.com/v1/chat/completions",
    }
    for base, expected in cases.items():
        assert _build_chat_completions_url(base) == expected


@pytest.mark.parametrize(
    "base",
    [
        "ftp://example.com/v1",
        "example.com/v1",
        "http://user:pass@example.com/v1",
        "http://example.com/v1?query=1",
        "http://example.com/v1#fragment",
        "http:///v1",
    ],
)
def test_build_chat_completions_url_rejects_invalid(base):
    with pytest.raises(TermExtractionError, match="invalid base_url") as excinfo:
        _build_chat_completions_url(base)
    assert base not in str(excinfo.value)
    assert "sk-test-key" not in str(excinfo.value)
