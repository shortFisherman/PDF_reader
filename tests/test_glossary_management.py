import csv
import io
from pathlib import Path
from typing import Never

import pytest

from pdf_reader.candidate_store import CandidateStore
from pdf_reader.glossary_compiler import load_effective_glossary
from pdf_reader.glossary_management import (
    GlossaryEffectiveUpdateError,
    GlossaryManagementRevisionConflict,
    GlossaryManagementService,
    GlossaryRequestError,
    RevisionToken,
)
from pdf_reader.term_model import GlossaryLockedError
from pdf_reader.user_glossary import UserGlossaryStore


def _service(tmp_path: Path) -> GlossaryManagementService:
    document_dir = tmp_path / ("a" * 64)
    document_dir.mkdir()
    global_glossary = tmp_path / "glossary.csv"
    global_glossary.write_text("source,target\nGlobal,全局\n", encoding="utf-8")
    return GlossaryManagementService(document_dir, global_glossary)


def test_authoritative_crud_lock_and_effective_compile(tmp_path):
    service = _service(tmp_path)
    initial = service.revisions()

    term, revisions, compiled = service.add_term(
        "TCS",
        "外用糖皮质激素",
        note="用户决定",
        expected=initial,
    )
    assert term.source == "TCS"
    assert revisions == RevisionToken(user=1, candidates=0)
    assert compiled.rows == 2
    assert load_effective_glossary(service.document_dir, service.global_glossary) == [
        ("Global", "全局"),
        ("TCS", "外用糖皮质激素"),
    ]

    edited, revisions, _ = service.edit_term(
        "TCS",
        "topical corticosteroids",
        "局部糖皮质激素",
        note="修订",
        expected=revisions,
    )
    assert edited.source == "topical corticosteroids"
    assert edited.target == "局部糖皮质激素"

    locked, revisions, _ = service.set_term_locked(edited.source, True, expected=revisions)
    assert locked.locked is True
    with pytest.raises(GlossaryLockedError):
        service.delete_term(edited.source, expected=revisions)

    _, revisions, _ = service.set_term_locked(edited.source, False, expected=revisions)
    removed, revisions, _ = service.delete_term(edited.source, expected=revisions)
    assert removed.source == edited.source
    assert revisions.user == 5
    assert load_effective_glossary(service.document_dir, service.global_glossary) == [("Global", "全局")]


def test_candidate_state_evidence_and_revision_conflict(tmp_path):
    service = _service(tmp_path)
    candidate_store = CandidateStore(service.document_dir)
    candidate_store.record_observation(
        "AD",
        "特应性皮炎",
        pages=[0, 2],
        evidence=["AD appears here"],
    )
    revision = service.revisions()

    listing = service.list_view(view="candidates")
    item = listing["items"][0]
    assert item["affects_translation"] is False
    assert item["targets"][0]["pages"] == [1, 3]
    assert item["targets"][0]["evidence"] == ["AD appears here"]
    assert "不会影响正文" in listing["candidate_notice"]

    accepted, current, _ = service.accept_candidate("AD", "用户译法", expected=revision)
    assert accepted.status == "accepted"
    assert load_effective_glossary(service.document_dir, service.global_glossary)[0] == ("AD", "用户译法")

    with pytest.raises(GlossaryManagementRevisionConflict) as excinfo:
        service.reject_candidate("AD", expected=revision)
    assert excinfo.value.actual_token == current

    authority = service.list_view(view="authoritative")
    accepted_item = next(item for item in authority["items"] if item["origin"] == "accepted_candidate")
    assert accepted_item["effective"] is True
    assert accepted_item["target"] == "用户译法"
    assert accepted_item["lockable"] is True

    locked, current, _ = service.set_term_locked(
        "AD",
        True,
        origin="accepted_candidate",
        expected=current,
    )
    assert locked.locked is True
    candidate_store.record_observation("AD", "更高频自动译法", pages=[4])
    current = service.revisions()
    with pytest.raises(GlossaryLockedError):
        service.reject_candidate("AD", expected=current)
    _, current, _ = service.set_term_locked(
        "AD",
        False,
        origin="accepted_candidate",
        expected=current,
    )
    rejected, _, _ = service.reject_candidate("AD", expected=current)
    assert rejected.status == "rejected"
    assert load_effective_glossary(service.document_dir, service.global_glossary) == [("Global", "全局")]


@pytest.mark.parametrize("value", ["=CMD()", "+SUM(1,1)", "-1+2", "@evil", "bad\x07text"])
def test_user_input_rejects_csv_injection_and_control_characters(tmp_path, value):
    service = _service(tmp_path)
    with pytest.raises(GlossaryRequestError):
        service.add_term(value, "安全译法", expected=service.revisions())
    assert service.revisions() == RevisionToken(0, 0)


def test_csv_import_is_atomic_exportable_and_revision_checked(tmp_path):
    service = _service(tmp_path)
    imported, revisions, compiled = service.import_csv(
        "source,target,locked,note\nAD,特应性皮炎,true,用户导入\nTCS,外用糖皮质激素,false,\n",
        expected=service.revisions(),
    )
    assert len(imported) == 2
    assert revisions.user == 1
    assert compiled.rows == 3

    exported = service.export_csv()
    rows = list(csv.DictReader(io.StringIO(exported.lstrip("\ufeff"))))
    assert rows == [
        {"source": "AD", "target": "特应性皮炎", "locked": "true", "note": "用户导入"},
        {"source": "TCS", "target": "外用糖皮质激素", "locked": "false", "note": ""},
    ]

    with pytest.raises(GlossaryRequestError):
        service.import_csv("source,target\nSafe,安全\nUnsafe,=CMD()\n", expected=revisions)
    terms, after_revision = UserGlossaryStore(service.document_dir).load()
    assert after_revision == revisions.user
    assert [term.source for term in terms] == ["AD", "TCS"]


def test_compile_failure_reports_saved_decision_without_leaking_input(tmp_path, monkeypatch):
    service = _service(tmp_path)

    def fail_compile(*_args: object, **_kwargs: object) -> Never:
        from pdf_reader.glossary_compiler import GlossaryCompileError

        raise GlossaryCompileError("secret evidence and prompt")

    monkeypatch.setattr("pdf_reader.glossary_management.compile_effective_glossary", fail_compile)
    with pytest.raises(GlossaryEffectiveUpdateError) as excinfo:
        service.add_term("AD", "特应性皮炎", expected=service.revisions())
    assert excinfo.value.revisions.user == 1
    assert "secret" not in str(excinfo.value)
    terms, revision = UserGlossaryStore(service.document_dir).load()
    assert revision == 1
    assert terms[0].target == "特应性皮炎"
