"""前端配置中心后端契约：GET 脱敏、PUT 校验/保存、原子性与并发保护。"""

import json
import os
from pathlib import Path
from typing import Any

import pytest
from flask import Flask

from pdf_reader import config, config_editor
from pdf_reader.routes import register_routes

VALID_TOML = """# 顶层注释：请保留
[pdf_reader]
# dpi 说明注释
dpi = 200
cache_dir = "cache"
legacy_extra = "keep-me"

[model]
provider = "deepseek"
api_key = "sk-file-secret"
model = "deepseek-chat"
base_url = "https://api.deepseek.com/v1"

[translation]
lang_in = "en"
lang_out = "zh"

[server]
host = "127.0.0.1"
port = 5000
debug = false

[pdf2zh]
split_short_lines = false
"""


@pytest.fixture
def editor_client(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(VALID_TOML, encoding="utf-8")
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    app = Flask(__name__)
    app.config["config_path"] = cfg_path
    app.config["TESTING"] = True
    register_routes(app)
    with app.test_client() as client:
        yield client, cfg_path


def _get(client, cfg_path) -> dict:
    resp = client.get("/api/config")
    assert resp.status_code == 200
    return resp.get_json()


def _put(client, cfg_path, values, revision, api_key=None, raw=False) -> Any:
    payload = {"values": values, "revision": revision}
    if api_key is not None:
        payload["api_key"] = api_key
    if raw:
        return client.put("/api/config", data=json.dumps(payload), content_type="application/json")
    return client.put("/api/config", json=payload)


def test_get_returns_schema_values_and_revision_without_api_key(editor_client):
    client, cfg_path = editor_client
    data = _get(client, cfg_path)

    assert isinstance(data["revision"], str) and len(data["revision"]) == 64
    assert len(data["schema"]) == 45
    assert {spec["group"] for spec in data["schema"]} == {"required", "optional", "advanced"}
    assert {spec["path"].split(".")[0] for spec in data["schema"]} == {
        "model",
        "pdf_reader",
        "translation",
        "server",
        "term_extraction",
        "pdf2zh",
    }
    schema_paths = {spec["path"] for spec in data["schema"]}
    for legacy in ("translation.term_qps", "translation.term_pool_max_workers", "translation.auto_extract_glossary"):
        assert legacy not in schema_paths
    assert "term_qps" not in data["values"]["translation"]
    assert "term_pool_max_workers" not in data["values"]["translation"]
    assert "auto_extract_glossary" not in data["values"]["translation"]
    assert data["values"]["model"]["provider"] == "deepseek"
    assert data["values"]["model"]["api_key"] == {"source": "file", "configured": True}
    assert data["values"]["pdf_reader"].get("legacy_extra") is None

    raw_body = client.get("/api/config").data.decode("utf-8")
    assert "sk-file-secret" not in raw_body
    assert data["env_overrides"] == {"MODEL_API_KEY": False}


def test_get_reports_environment_source(editor_client, monkeypatch):
    client, cfg_path = editor_client
    monkeypatch.setenv("MODEL_API_KEY", "sk-env-secret")
    data = _get(client, cfg_path)
    assert data["values"]["model"]["api_key"] == {"source": "environment", "configured": True}
    assert data["env_overrides"] == {"MODEL_API_KEY": True}
    assert "sk-env-secret" not in client.get("/api/config").data.decode("utf-8")


def test_get_missing_file_returns_defaults_and_missing_revision(tmp_path, monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    cfg_path = tmp_path / "absent.toml"
    app = Flask(__name__)
    app.config["config_path"] = cfg_path
    app.config["TESTING"] = True
    register_routes(app)
    with app.test_client() as client:
        data = client.get("/api/config").get_json()
    assert data["revision"] == "missing"
    assert data["values"]["model"]["api_key"] == {"source": "missing", "configured": False}
    assert data["values"]["pdf_reader"]["dpi"] == 200
    assert data["values"]["server"]["port"] == 5000


def test_get_malformed_toml_returns_safe_error_without_leaking_key(tmp_path, monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text('[model]\napi_key = "sk-top-secret"\nbroken', encoding="utf-8")
    app = Flask(__name__)
    app.config["config_path"] = cfg_path
    app.config["TESTING"] = True
    register_routes(app)
    with app.test_client() as client:
        resp = client.get("/api/config")
    assert resp.status_code == 500
    data = resp.get_json()
    assert data["code"] == "config_read_failed"
    assert "sk-top-secret" not in resp.data.decode("utf-8")


def test_put_saves_values_and_preserves_comments_unknown_fields(editor_client):
    client, cfg_path = editor_client
    before = _get(client, cfg_path)
    resp = _put(
        client,
        cfg_path,
        {
            "model": {"model": "deepseek-v4-flash", "reasoning_effort": "max"},
            "pdf_reader": {"dpi": 300},
            "translation": {"lang_out": "zh-CN"},
        },
        before["revision"],
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["restart_required"] is True
    assert len(data["revision"]) == 64

    text = cfg_path.read_text(encoding="utf-8")
    assert "# 顶层注释：请保留" in text
    assert "# dpi 说明注释" in text
    assert 'legacy_extra = "keep-me"' in text
    assert 'model = "deepseek-v4-flash"' in text
    assert "dpi = 300" in text
    assert 'lang_out = "zh-CN"' in text
    assert 'api_key = "sk-file-secret"' in text

    after = _get(client, cfg_path)
    assert after["revision"] == data["revision"]


def test_put_keeps_existing_key_when_omitted_and_writes_new_key_when_provided(editor_client):
    client, cfg_path = editor_client
    before = _get(client, cfg_path)

    resp = _put(client, cfg_path, {"model": {"model": "deepseek-v4"}}, before["revision"])
    assert resp.status_code == 200
    assert 'api_key = "sk-file-secret"' in cfg_path.read_text(encoding="utf-8")

    state = _get(client, cfg_path)
    resp = _put(
        client,
        cfg_path,
        {"model": {"model": "deepseek-v4"}},
        state["revision"],
        api_key="sk-replaced-key",
    )
    assert resp.status_code == 200
    text = cfg_path.read_text(encoding="utf-8")
    assert 'api_key = "sk-replaced-key"' in text
    assert "sk-file-secret" not in text
    assert "sk-replaced-key" not in client.get("/api/config").data.decode("utf-8")


def test_put_rejects_api_key_inside_values(editor_client):
    client, cfg_path = editor_client
    before = _get(client, cfg_path)
    resp = _put(client, cfg_path, {"model": {"api_key": "sk-nope"}}, before["revision"])
    assert resp.status_code == 400
    assert resp.get_json()["code"] == "api_key_via_values"
    assert "sk-nope" not in cfg_path.read_text(encoding="utf-8")


def test_put_rejects_unknown_field(editor_client):
    client, cfg_path = editor_client
    original = cfg_path.read_bytes()
    before = _get(client, cfg_path)
    resp = _put(client, cfg_path, {"model": {"bogus": 1}}, before["revision"])
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["code"] == "unknown_field"
    assert "model.bogus" in data["error"]
    assert cfg_path.read_bytes() == original


def test_put_rejects_unknown_section(editor_client):
    client, cfg_path = editor_client
    before = _get(client, cfg_path)
    resp = _put(client, cfg_path, {"mystery": {"x": 1}}, before["revision"])
    assert resp.status_code == 400
    assert resp.get_json()["code"] == "unknown_field"


@pytest.mark.parametrize(
    ("values", "message_fragment"),
    [
        ({"model": {"provider": "not-a-provider"}}, "provider"),
        ({"pdf_reader": {"dpi": "abc"}}, "dpi"),
        ({"pdf_reader": {"dpi": 0}}, "dpi"),
        ({"translation": {"qps": 0}}, "qps"),
        ({"translation": {"qps": "fast"}}, "qps"),
        ({"pdf2zh": {"non_formula_line_iou_threshold": 2.0}}, "non_formula_line_iou_threshold"),
        ({"model": {"send_temperature": True}}, "send_temperature"),
    ],
)
def test_put_rejects_invalid_type_range_and_conditional(editor_client, values, message_fragment):
    client, cfg_path = editor_client
    before = _get(client, cfg_path)
    resp = _put(client, cfg_path, values, before["revision"])
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["code"] == "invalid_config"
    assert message_fragment in data["error"]


def test_put_requires_base_url_for_openai_compatible(editor_client):
    client, cfg_path = editor_client
    before = _get(client, cfg_path)
    resp = _put(
        client,
        cfg_path,
        {
            "model": {
                "provider": "openai_compatible",
                "model": "custom-model",
                "base_url": None,
            }
        },
        before["revision"],
        api_key="sk-new",
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["code"] == "invalid_config"
    assert "base_url" in data["error"]


def test_put_accepts_openai_compatible_with_base_url(editor_client):
    client, cfg_path = editor_client
    before = _get(client, cfg_path)
    resp = _put(
        client,
        cfg_path,
        {
            "model": {
                "provider": "openai_compatible",
                "model": "custom-model",
                "base_url": "https://example.com/v1",
            }
        },
        before["revision"],
        api_key="sk-new",
    )
    assert resp.status_code == 200
    text = cfg_path.read_text(encoding="utf-8")
    assert 'provider = "openai_compatible"' in text
    assert 'base_url = "https://example.com/v1"' in text


def test_put_revision_conflict_rejected_and_file_untouched(editor_client):
    client, cfg_path = editor_client
    original = cfg_path.read_bytes()
    resp = _put(client, cfg_path, {"model": {"model": "changed"}}, "stale-revision")
    assert resp.status_code == 409
    assert resp.get_json()["code"] == "revision_conflict"
    assert cfg_path.read_bytes() == original


def test_put_atomic_failure_keeps_original_file(editor_client, monkeypatch):
    client, cfg_path = editor_client
    original = cfg_path.read_bytes()
    before = _get(client, cfg_path)

    def boom(src, dst) -> None:  # noqa: ANN001, ANN002
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    resp = _put(client, cfg_path, {"model": {"model": "changed"}}, before["revision"])
    assert resp.status_code == 500
    assert resp.get_json()["code"] == "config_write_failed"
    assert cfg_path.read_bytes() == original
    assert not list(cfg_path.parent.glob(f".{cfg_path.name}.*.tmp"))


def test_put_creates_missing_config_file(tmp_path, monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    cfg_path = tmp_path / "config.toml"
    app = Flask(__name__)
    app.config["config_path"] = cfg_path
    app.config["TESTING"] = True
    register_routes(app)
    with app.test_client() as client:
        resp = _put(
            client,
            cfg_path,
            {
                "model": {
                    "provider": "deepseek",
                    "model": "deepseek-chat",
                    "base_url": "https://api.deepseek.com/v1",
                }
            },
            "missing",
            api_key="sk-first-key",
        )
        assert resp.status_code == 200
        assert 'api_key = "sk-first-key"' in cfg_path.read_text(encoding="utf-8")
        data = client.get("/api/config").get_json()
        assert data["values"]["model"]["api_key"] == {"source": "file", "configured": True}


def test_save_does_not_mutate_running_config(editor_client):
    client, cfg_path = editor_client
    before_config = dict(config.CONFIG)
    before_key = config.MODEL_API_KEY
    before_provider = config.MODEL_PROVIDER
    state = _get(client, cfg_path)
    resp = _put(client, cfg_path, {"model": {"provider": "zhipu"}}, state["revision"], api_key="sk-x")
    assert resp.status_code == 200
    assert config.CONFIG == before_config
    assert config.MODEL_API_KEY == before_key
    assert config.MODEL_PROVIDER == before_provider


def test_provider_options_last_item_is_openai_compatible():
    specs = {spec.path: spec for spec in config_editor.FIELD_SPECS}
    provider_spec = specs["model.provider"]
    assert provider_spec.options[-1] == ("openai_compatible", "自定义 OpenAI 兼容接口")


def test_term_extraction_schema_fields_are_well_formed():
    paths = {spec.path for spec in config_editor.FIELD_SPECS}
    assert {
        "term_extraction.enabled",
        "term_extraction.timeout",
        "term_extraction.qps",
        "term_extraction.max_workers",
        "term_extraction.retry_count",
        "term_extraction.max_input_chars",
        "term_extraction.prompt",
    } <= paths
    timeout = config_editor.FIELDS_BY_PATH["term_extraction.timeout"]
    retry = config_editor.FIELDS_BY_PATH["term_extraction.retry_count"]
    assert timeout.minimum == 1.0 and timeout.maximum == 120.0
    assert retry.minimum == 0 and retry.maximum == 3
    assert "候选" in config_editor.FIELDS_BY_PATH["term_extraction.enabled"].description
    enabled = config_editor.FIELDS_BY_PATH["term_extraction.enabled"]
    assert "候选不会自动影响正文" in enabled.description
    assert "严格正文约束始终开启" in enabled.description
    qps = config_editor.FIELDS_BY_PATH["term_extraction.qps"]
    max_workers = config_editor.FIELDS_BY_PATH["term_extraction.max_workers"]
    assert "translation.term_qps" in qps.description
    assert "translation.term_pool_max_workers" in max_workers.description


def test_legacy_translation_term_keys_hidden_from_config_center():
    paths = {spec.path for spec in config_editor.FIELD_SPECS}
    for legacy in ("translation.term_qps", "translation.term_pool_max_workers", "translation.auto_extract_glossary"):
        assert legacy not in paths
        assert legacy not in config_editor.FIELDS_BY_PATH


def test_schema_qps_and_pool_max_workers_allow_large_values():
    qps = config_editor.FIELDS_BY_PATH["translation.qps"]
    pool = config_editor.FIELDS_BY_PATH["translation.pool_max_workers"]
    assert qps.maximum is None
    assert pool.maximum is None
    assert qps.minimum == 1
    assert pool.minimum == 1
    assert "每秒" in qps.description and "不是并发数" in qps.description
    assert ">100 可保存" in qps.description
    assert "同时工作" in pool.description and "跟随 qps" in pool.description
    assert ">100 可保存" in pool.description
    assert "留空（推荐）" in pool.description and "自动跟随 qps" in pool.description


def test_put_rejects_legacy_translation_keys(editor_client):
    client, cfg_path = editor_client
    original = cfg_path.read_bytes()
    before = _get(client, cfg_path)
    for values in (
        {"term_qps": 2},
        {"term_pool_max_workers": 0},
        {"auto_extract_glossary": False},
    ):
        resp = _put(client, cfg_path, {"translation": values}, before["revision"])
        assert resp.status_code == 400
        assert resp.get_json()["code"] == "unknown_field"
        assert cfg_path.read_bytes() == original


def test_put_preserves_legacy_keys_on_disk(tmp_path, monkeypatch):
    """配置中心保存必须原样保留磁盘上的 1.x 兼容键，不删除、不改写。"""
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    cfg_path = tmp_path / "config.toml"
    legacy_translation = (
        "[translation]\n"
        'lang_in = "en"\n'
        'lang_out = "zh"\n'
        "term_qps = 2\n"
        "term_pool_max_workers = 0\n"
        "auto_extract_glossary = false\n"
    )
    cfg_path.write_text(
        VALID_TOML.replace(
            '[translation]\nlang_in = "en"\nlang_out = "zh"\n',
            "# 1.x 兼容别名（配置中心不展示/写入；保存时原样保留）\n" + legacy_translation,
        ),
        encoding="utf-8",
    )
    app = Flask(__name__)
    app.config["config_path"] = cfg_path
    app.config["TESTING"] = True
    register_routes(app)
    with app.test_client() as client:
        data = client.get("/api/config").get_json()
        assert "term_qps" not in data["values"]["translation"]
        assert "term_pool_max_workers" not in data["values"]["translation"]
        assert "auto_extract_glossary" not in data["values"]["translation"]
        resp = client.put(
            "/api/config",
            json={"values": {"translation": {"qps": 6}}, "revision": data["revision"]},
        )
        assert resp.status_code == 200
    text = cfg_path.read_text(encoding="utf-8")
    assert "term_qps = 2" in text
    assert "term_pool_max_workers = 0" in text
    assert "auto_extract_glossary = false" in text
    assert "qps = 6" in text


def test_qps_and_pool_max_workers_148_can_be_saved(editor_client):
    client, cfg_path = editor_client
    state = _get(client, cfg_path)
    resp = _put(
        client,
        cfg_path,
        {"translation": {"qps": 148, "pool_max_workers": 148}},
        state["revision"],
    )
    assert resp.status_code == 200
    text = cfg_path.read_text(encoding="utf-8")
    assert "qps = 148" in text
    assert "pool_max_workers = 148" in text
    data = _get(client, cfg_path)
    assert data["values"]["translation"]["qps"] == 148
    assert data["values"]["translation"]["pool_max_workers"] == 148


def test_schema_thinking_mode_default_is_none():
    spec = config_editor.FIELDS_BY_PATH["model.thinking_mode"]
    assert spec.default is None


def test_thinking_mode_missing_stays_blank_and_null_clears_key(editor_client):
    client, cfg_path = editor_client
    text = cfg_path.read_text(encoding="utf-8")
    text = text.replace(
        'base_url = "https://api.deepseek.com/v1"',
        'base_url = "https://api.deepseek.com/v1"\nthinking_mode = "enabled"',
    )
    cfg_path.write_text(text, encoding="utf-8")

    state = _get(client, cfg_path)
    assert state["values"]["model"]["thinking_mode"] == "enabled"
    schema_entry = next(s for s in state["schema"] if s["path"] == "model.thinking_mode")
    assert schema_entry["default"] is None

    resp = _put(client, cfg_path, {"model": {"thinking_mode": None}}, state["revision"])
    assert resp.status_code == 200
    assert "thinking_mode" not in cfg_path.read_text(encoding="utf-8")

    state = _get(client, cfg_path)
    assert state["values"]["model"]["thinking_mode"] == ""


def test_read_raw_oserror_message_sanitized(tmp_path, monkeypatch):
    secret_text = r"C:\Users\SecretUser\app\config.toml (Access is denied)"

    def boom(self) -> None:  # noqa: ANN001
        raise OSError(secret_text)

    monkeypatch.setattr(Path, "read_bytes", boom)
    with pytest.raises(config_editor.ConfigEditError) as excinfo:
        config_editor._read_raw(tmp_path / "config.toml")
    assert excinfo.value.code == "config_read_failed"
    assert secret_text not in excinfo.value.message
    assert "无法读取配置文件" in excinfo.value.message


def test_get_config_read_oserror_does_not_leak_internal_path(editor_client, monkeypatch):
    client, cfg_path = editor_client
    secret_path = str(cfg_path.resolve())

    def boom(self) -> None:  # noqa: ANN001
        raise OSError(f"{secret_path} (Permission denied)")

    monkeypatch.setattr(Path, "read_bytes", boom)
    resp = client.get("/api/config")
    assert resp.status_code == 500
    assert secret_path not in resp.data.decode("utf-8")
    assert resp.get_json()["code"] == "config_read_failed"


def test_config_local_get_put_allowed_on_loopback(editor_client):
    client, cfg_path = editor_client
    for addr in ("127.0.0.1", "127.8.9.10", "::1", "::ffff:127.0.0.1"):
        resp = client.get("/api/config", environ_base={"REMOTE_ADDR": addr})
        assert resp.status_code == 200

    before = _get(client, cfg_path)
    resp = client.put(
        "/api/config",
        json={"values": {"model": {"model": "loopback-ok"}}, "revision": before["revision"]},
        environ_base={"REMOTE_ADDR": "::1"},
    )
    assert resp.status_code == 200
    assert 'model = "loopback-ok"' in cfg_path.read_text(encoding="utf-8")


def test_config_remote_get_put_rejected_and_never_writes(editor_client):
    client, cfg_path = editor_client
    original = cfg_path.read_bytes()
    for addr in ("192.168.1.23", "10.0.0.2", "::ffff:192.168.1.1"):
        resp = client.get("/api/config", environ_base={"REMOTE_ADDR": addr})
        assert resp.status_code == 403
        data = resp.get_json()
        assert data["code"] == "config_local_only"
        assert "本机" in data["error"]

    resp = client.put(
        "/api/config",
        json={"values": {"model": {"model": "remote-write"}}, "revision": "whatever"},
        environ_base={"REMOTE_ADDR": "192.168.1.23"},
    )
    assert resp.status_code == 403
    assert resp.get_json()["code"] == "config_local_only"
    assert cfg_path.read_bytes() == original


def test_config_remote_put_does_not_create_missing_file(tmp_path, monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    cfg_path = tmp_path / "config.toml"
    app = Flask(__name__)
    app.config["config_path"] = cfg_path
    app.config["TESTING"] = True
    register_routes(app)
    with app.test_client() as client:
        resp = client.put(
            "/api/config",
            json={
                "values": {"model": {"provider": "deepseek", "model": "deepseek-chat"}},
                "revision": "missing",
                "api_key": "sk-remote",
            },
            environ_base={"REMOTE_ADDR": "10.0.0.5"},
        )
    assert resp.status_code == 403
    assert resp.get_json()["code"] == "config_local_only"
    assert not cfg_path.exists()


def test_config_rejects_host_spoofing_and_invalid_remote_addr(editor_client):
    client, cfg_path = editor_client
    original = cfg_path.read_bytes()
    resp = client.get(
        "/api/config",
        headers={"Host": "127.0.0.1:5000"},
        environ_base={"REMOTE_ADDR": "192.168.1.23"},
    )
    assert resp.status_code == 403
    assert resp.get_json()["code"] == "config_local_only"

    for bad_addr in ("", "not-an-ip", "127.0.0.1.evil.example"):
        resp = client.get("/api/config", environ_base={"REMOTE_ADDR": bad_addr})
        assert resp.status_code == 403
        assert resp.get_json()["code"] == "config_local_only"
    assert cfg_path.read_bytes() == original
