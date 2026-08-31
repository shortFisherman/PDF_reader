from pathlib import Path
from typing import Any

from pdf_reader.candidate_store import CandidateStore


def _open(client: Any, sample_pdf: Path) -> dict[str, object]:
    response = client.post("/api/open", json={"path": str(sample_pdf)})
    assert response.status_code == 200
    return response.get_json()


def _global_glossary(tmp_path: Path) -> Path:
    path = tmp_path / "global.csv"
    path.write_text("source,target\nGlobal,全局\n", encoding="utf-8")
    return path


def test_glossary_routes_crud_revision_and_csv_roundtrip(test_client, sample_pdf, tmp_path, monkeypatch):
    monkeypatch.setattr("pdf_reader.routes.paths.get_glossary_path", lambda: _global_glossary(tmp_path))
    opened = _open(test_client, sample_pdf)
    document_id = opened["document_id"]

    listing = test_client.get("/api/glossary", query_string={"document_id": document_id})
    assert listing.status_code == 200
    revision = listing.get_json()["revision"]

    created = test_client.post(
        "/api/glossary/terms",
        json={
            "document_id": document_id,
            "revision": revision,
            "source": "<b>TCS</b>",
            "target": "外用糖皮质激素",
            "note": "<img src=x onerror=alert(1)>",
        },
    )
    assert created.status_code == 201
    current = created.get_json()["revision"]

    stale = test_client.post(
        "/api/glossary/terms",
        json={
            "document_id": document_id,
            "revision": revision,
            "source": "AD",
            "target": "特应性皮炎",
        },
    )
    assert stale.status_code == 409
    assert stale.get_json()["code"] == "glossary_revision_conflict"
    assert stale.get_json()["revision"] == current

    listing = test_client.get(
        "/api/glossary",
        query_string={"document_id": document_id, "q": "TCS", "sort": "target"},
    ).get_json()
    item = listing["items"][0]
    assert item["source"] == "<b>TCS</b>"
    assert item["note"] == "<img src=x onerror=alert(1)>"
    assert item["origin"] == "user"

    exported = test_client.get("/api/glossary/export", query_string={"document_id": document_id})
    assert exported.status_code == 200
    assert exported.headers["Content-Disposition"] == 'attachment; filename="document-glossary.csv"'
    assert "<b>TCS</b>,外用糖皮质激素" in exported.get_data(as_text=True)

    imported = test_client.post(
        "/api/glossary/import",
        json={
            "document_id": document_id,
            "revision": current,
            "csv": "source,target\nAD,特应性皮炎\n",
        },
    )
    assert imported.status_code == 200
    assert imported.get_json()["imported"] == 1


def test_candidate_accept_reject_updates_effective_and_pagination(test_client, sample_pdf, tmp_path, monkeypatch):
    global_path = _global_glossary(tmp_path)
    monkeypatch.setattr("pdf_reader.routes.paths.get_glossary_path", lambda: global_path)
    opened = _open(test_client, sample_pdf)
    document_id = opened["document_id"]
    document_dir = test_client.application.config["app_state"].glossary_cache_path
    assert document_dir is not None
    CandidateStore(document_dir).record_observation(
        "AD",
        "特应性皮炎",
        pages=[0],
        evidence=["evidence must not enter errors"],
    )

    candidates = test_client.get(
        "/api/glossary",
        query_string={
            "document_id": document_id,
            "view": "candidates",
            "page": 1,
            "page_size": 1,
        },
    )
    payload = candidates.get_json()
    assert payload["items"][0]["targets"][0]["pages"] == [1]
    assert payload["total_pages"] == 1
    revision = payload["revision"]

    accepted = test_client.post(
        "/api/glossary/candidates/accept",
        json={
            "document_id": document_id,
            "revision": revision,
            "source": "AD",
            "target": "用户译法",
        },
    )
    assert accepted.status_code == 200
    revision = accepted.get_json()["revision"]
    effective = (document_dir / "effective_glossary.csv").read_text(encoding="utf-8")
    assert "AD,用户译法" in effective

    rejected = test_client.post(
        "/api/glossary/candidates/reject",
        json={"document_id": document_id, "revision": revision, "source": "AD"},
    )
    assert rejected.status_code == 200
    effective = (document_dir / "effective_glossary.csv").read_text(encoding="utf-8")
    assert "AD,用户译法" not in effective


def test_glossary_routes_local_only_identity_busy_and_safe_errors(
    test_client,
    sample_pdf,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr("pdf_reader.routes.paths.get_glossary_path", lambda: _global_glossary(tmp_path))
    opened = _open(test_client, sample_pdf)
    document_id = opened["document_id"]

    denied = test_client.get(
        "/api/glossary",
        query_string={"document_id": document_id},
        environ_overrides={"REMOTE_ADDR": "192.0.2.5"},
    )
    assert denied.status_code == 403
    assert denied.get_json()["code"] == "glossary_local_only"

    stale = test_client.get("/api/glossary", query_string={"document_id": "old-tab"})
    assert stale.status_code == 409
    assert stale.get_json()["code"] == "stale_document"

    listing = test_client.get("/api/glossary", query_string={"document_id": document_id}).get_json()
    unsafe = test_client.post(
        "/api/glossary/terms",
        json={
            "document_id": document_id,
            "revision": listing["revision"],
            "source": "=HYPERLINK(secret-evidence)",
            "target": "prompt-secret",
        },
    )
    assert unsafe.status_code == 400
    assert unsafe.get_json() == {
        "code": "invalid_term",
        "error": "术语请求无效，请检查字段、长度和 CSV 内容",
    }
    assert "secret-evidence" not in unsafe.get_data(as_text=True)

    state = test_client.application.config["app_state"]
    snapshot = state.translation_snapshot()
    coordinator = test_client.application.config["translation_coordinator"]
    job = coordinator.start(snapshot.document_id, [0], pdf_hash=snapshot.pdf_hash)
    busy = test_client.post(
        "/api/glossary/terms",
        json={
            "document_id": document_id,
            "revision": listing["revision"],
            "source": "AD",
            "target": "特应性皮炎",
        },
    )
    assert busy.status_code == 409
    assert busy.get_json()["code"] == "translation_busy"
    coordinator.finish(job.job_id)
