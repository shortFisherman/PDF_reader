"""P0-02 候选术语存储：观察合并、状态保护、revision 与原子持久化。"""

import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pdf_reader import candidate_store
from pdf_reader.candidate_store import CANDIDATE_FILENAME, CandidateObservation, CandidateStore
from pdf_reader.term_model import (
    CANDIDATE_SCHEMA_VERSION,
    GlossaryRevisionConflictError,
    TermStoreError,
    rank_target_suggestions,
)
from pdf_reader.user_glossary import USER_GLOSSARY_FILENAME, UserGlossaryStore


def doc_dir(tmp_path: Path) -> Path:
    directory = tmp_path / ("b" * 64)
    directory.mkdir()
    return directory


def test_load_missing_file_returns_empty(tmp_path):
    store = CandidateStore(doc_dir(tmp_path))
    entries, revision, metadata = store.load()
    assert entries == []
    assert revision == 0
    assert metadata == {}


def test_document_dir_must_be_64_hex_hash(tmp_path):
    with pytest.raises(TermStoreError, match="64-char hex hash"):
        CandidateStore(tmp_path)


def test_record_observation_creates_candidate_with_normalized_key(tmp_path):
    store = CandidateStore(doc_dir(tmp_path))
    revision = store.record_observation(
        " Atopic Dermatitis  Practice Parameter ",
        "特应性皮炎实践指南",
        pages=[1, 3, 3],
        evidence=["Atopic Dermatitis Practice Parameter", "guideline page"],
        strategy_version="extractor/1.0",
    )
    assert revision == 1
    entries, loaded_revision, _ = store.load()
    assert loaded_revision == 1
    assert len(entries) == 1
    entry = entries[0]
    assert entry.source_key == "atopic dermatitis practice parameter"
    assert entry.source == "Atopic Dermatitis  Practice Parameter"
    assert entry.status == "candidate"
    assert entry.strategy_version == "extractor/1.0"
    assert len(entry.targets) == 1
    assert entry.targets[0].target == "特应性皮炎实践指南"
    assert entry.targets[0].observations == 1
    assert entry.targets[0].pages == (1, 3)
    assert entry.targets[0].evidence == ("Atopic Dermatitis Practice Parameter", "guideline page")
    assert entry.first_seen_at <= entry.last_seen_at


def test_record_observation_merges_counts_pages_and_bounds_evidence(tmp_path):
    store = CandidateStore(doc_dir(tmp_path))
    store.record_observation("AD", "特应性皮炎", pages=[2], evidence=["page two"])
    store.record_observation("ad", "特应性皮炎", pages=[2, 5], evidence=["page five"] * 8)
    entries, revision, _ = store.load()
    assert revision == 2
    assert len(entries) == 1
    suggestion = entries[0].targets[0]
    assert suggestion.observations == 2
    assert suggestion.pages == (2, 5)
    assert len(suggestion.evidence) == 2
    assert all(len(snippet) <= candidate_store.MAX_EVIDENCE_LENGTH for snippet in suggestion.evidence)


def test_record_observation_keeps_multiple_target_suggestions(tmp_path):
    store = CandidateStore(doc_dir(tmp_path))
    store.record_observation("TCS", "外用糖皮质激素")
    store.record_observation("TCS", "外用皮质类固醇")
    entries, _, _ = store.load()
    targets = [s.target for s in entries[0].targets]
    assert targets == ["外用皮质类固醇", "外用糖皮质激素"]


def test_record_observations_batch_merges_atomically(tmp_path):
    store = CandidateStore(doc_dir(tmp_path))
    revision = store.record_observations(
        [
            CandidateObservation(source="AD", target="特应性皮炎", pages=(1, 2)),
            CandidateObservation(source="TCS", target="外用糖皮质激素", pages=(2,)),
            CandidateObservation(source="AD", target="特应性皮炎", pages=(3,)),
        ],
        strategy_version="term-extraction-client/1",
    )
    assert revision == 1
    entries, loaded_revision, _ = store.load()
    assert loaded_revision == 1
    assert len(entries) == 2
    ad = next(entry for entry in entries if entry.source_key == "ad")
    assert ad.targets[0].observations == 2
    assert ad.targets[0].pages == (1, 2, 3)
    assert ad.strategy_version == "term-extraction-client/1"


def test_record_observations_empty_is_noop(tmp_path):
    store = CandidateStore(doc_dir(tmp_path))
    assert store.record_observations([]) == 0
    assert not store.path.exists()


def test_record_observations_invalid_observation_writes_nothing(tmp_path):
    store = CandidateStore(doc_dir(tmp_path))
    store.record_observation("AD", "特应性皮炎")
    old_bytes = store.path.read_bytes()
    with pytest.raises(TermStoreError, match="invalid candidate observation"):
        store.record_observations(
            [
                CandidateObservation(source="TCS", target="外用糖皮质激素"),
                "not-an-observation",  # type: ignore[list-item]
            ]
        )
    with pytest.raises(TermStoreError, match="control characters"):
        store.record_observations(
            [
                CandidateObservation(source="TCS", target="外用糖皮质激素"),
                CandidateObservation(source="bad\nterm", target="译法"),
            ]
        )
    entries, revision, _ = store.load()
    assert revision == 1
    assert len(entries) == 1
    assert store.path.read_bytes() == old_bytes


def test_record_observations_never_changes_user_state(tmp_path):
    store = CandidateStore(doc_dir(tmp_path))
    store.record_observation("AD", "自动建议")
    store.accept("AD", target="用户确认")
    store.record_observation("TCS", "旧译法")
    store.reject("TCS", target="旧译法")

    store.record_observations(
        [
            CandidateObservation(source="AD", target="新建议"),
            CandidateObservation(source="TCS", target="新建议"),
        ]
    )
    entries, _, _ = store.load()
    by_source = {entry.source_key: entry for entry in entries}
    assert by_source["ad"].status == "accepted"
    assert by_source["ad"].accepted_target == "用户确认"
    assert by_source["tcs"].status == "rejected"
    assert by_source["tcs"].rejected_targets == ["旧译法"]


def test_accept_sets_status_and_keeps_it_under_auto_observations(tmp_path):
    store = CandidateStore(doc_dir(tmp_path))
    store.record_observation("AD", "特应性皮炎")
    entry, revision = store.accept("ad", target="特应性皮炎（AT）")
    assert entry.status == "accepted"
    assert entry.accepted_target == "特应性皮炎（AT）"
    assert revision == 2

    store.record_observation("AD", "别处建议")
    entries, _, _ = store.load()
    assert entries[0].status == "accepted"
    assert entries[0].accepted_target == "特应性皮炎（AT）"
    assert {s.target for s in entries[0].targets} == {"特应性皮炎（AT）", "特应性皮炎", "别处建议"}


def test_accept_without_target_uses_top_suggestion(tmp_path):
    store = CandidateStore(doc_dir(tmp_path))
    store.record_observation("TCS", "外用糖皮质激素")
    entry, _ = store.accept("TCS")
    assert entry.accepted_target == "外用糖皮质激素"


def test_accept_missing_entry_raises(tmp_path):
    store = CandidateStore(doc_dir(tmp_path))
    with pytest.raises(TermStoreError, match="not found"):
        store.accept("missing")


def test_reject_marks_status_and_rejected_targets(tmp_path):
    store = CandidateStore(doc_dir(tmp_path))
    store.record_observation("benefits", "获益")
    store.record_observation("benefits", "福利")
    entry, revision = store.reject("benefits", target="福利")
    assert entry.status == "rejected"
    assert entry.rejected_targets == ["福利"]
    assert revision == 3

    # 自动观察不得把已拒绝候选恢复为可提示状态，也不得改变拒绝记录。
    store.record_observation("benefits", "福利", pages=[9], evidence=["again"])
    entries, _, _ = store.load()
    assert entries[0].status == "rejected"
    assert entries[0].rejected_targets == ["福利"]
    suggestion = next(s for s in entries[0].targets if s.target == "福利")
    assert suggestion.observations == 2
    assert suggestion.pages == (9,)


def test_rejected_source_target_reobservation_never_creates_duplicate(tmp_path):
    store = CandidateStore(doc_dir(tmp_path))
    store.record_observation("AD", "特应性皮炎")
    store.reject("AD", target="特应性皮炎")
    store.record_observation("AD", "特应性皮炎", pages=[1], evidence=["again"])
    entries, revision, _ = store.load()
    assert revision == 3
    assert len(entries) == 1
    assert entries[0].status == "rejected"
    assert entries[0].rejected_targets == ["特应性皮炎"]
    suggestion = entries[0].targets[0]
    assert suggestion.observations == 2
    assert suggestion.pages == (1,)


def test_revision_conflict_is_reported(tmp_path):
    store = CandidateStore(doc_dir(tmp_path))
    store.record_observation("AD", "特应性皮炎")
    with pytest.raises(GlossaryRevisionConflictError) as excinfo:
        store.record_observation("AD", "特应性皮炎", expected_revision=99)
    assert excinfo.value.expected == 99
    assert excinfo.value.actual == 1


def test_corrupt_json_is_refused_not_overwritten(tmp_path):
    store = CandidateStore(doc_dir(tmp_path))
    store.path.write_bytes(b"{broken")
    with pytest.raises(TermStoreError):
        store.record_observation("AD", "特应性皮炎")
    assert store.path.read_bytes() == b"{broken"


def test_unsupported_schema_version_is_refused(tmp_path):
    store = CandidateStore(doc_dir(tmp_path))
    store.path.write_text(json.dumps({"schema_version": 99, "revision": 1, "candidates": {}}), encoding="utf-8")
    with pytest.raises(TermStoreError, match="schema version"):
        store.load()


def test_write_failure_keeps_last_valid_store(tmp_path, monkeypatch):
    store = CandidateStore(doc_dir(tmp_path))
    store.record_observation("AD", "特应性皮炎")
    old_bytes = store.path.read_bytes()
    monkeypatch.setattr(
        candidate_store.os,
        "replace",
        lambda src, dst: (_ for _ in ()).throw(OSError("replace failed")),
    )
    with pytest.raises(OSError, match="replace failed"):
        store.record_observation("TCS", "外用糖皮质激素")
    assert store.path.read_bytes() == old_bytes
    assert not list(store.document_dir.glob("*.tmp"))


def test_fsync_failure_mid_write_keeps_last_valid_store(tmp_path, monkeypatch):
    store = CandidateStore(doc_dir(tmp_path))
    store.record_observation("AD", "特应性皮炎")
    old_bytes = store.path.read_bytes()
    replace_calls = []
    real_replace = os.replace
    monkeypatch.setattr(
        candidate_store.os,
        "replace",
        lambda src, dst: replace_calls.append((Path(src).name, Path(dst))) or real_replace(src, dst),
    )
    monkeypatch.setattr(candidate_store.os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("fsync failed")))
    with pytest.raises(OSError, match="fsync failed"):
        store.record_observation("TCS", "外用糖皮质激素")
    assert replace_calls == []
    assert store.path.read_bytes() == old_bytes
    assert not list(store.document_dir.glob("*.tmp"))


def test_concurrent_observations_do_not_lose_updates(tmp_path):
    store = CandidateStore(doc_dir(tmp_path))
    thread_count = 8
    barrier = threading.Barrier(thread_count)
    errors = []

    def worker(index: int) -> None:
        try:
            barrier.wait(timeout=5)
            store.record_observation("AD", "特应性皮炎", pages=[index], strategy_version=f"thread/{index}")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(thread_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert errors == []
    entries, _, _ = store.load()
    assert entries[0].targets[0].observations == thread_count
    assert entries[0].targets[0].pages == tuple(range(thread_count))
    assert not list(store.document_dir.glob("*.tmp"))


def test_candidate_store_never_touches_user_glossary(tmp_path):
    document_dir = doc_dir(tmp_path)
    user_store = UserGlossaryStore(document_dir)
    user_store.add("AD", "特应性皮炎", locked=True)
    user_bytes = user_store.path.read_bytes()

    candidate_store_ = CandidateStore(document_dir)
    candidate_store_.record_observation("AD", "自动建议")
    candidate_store_.accept("AD", target="自动建议")
    candidate_store_.record_observation("TCS", "外用糖皮质激素")
    candidate_store_.reject("TCS", target="其他")

    assert user_store.path.read_bytes() == user_bytes
    files = sorted(p.name for p in document_dir.iterdir())
    assert files == [CANDIDATE_FILENAME, USER_GLOSSARY_FILENAME]


def test_persisted_payload_has_schema_version_and_revision(tmp_path):
    store = CandidateStore(doc_dir(tmp_path))
    store.record_observation("AD", "特应性皮炎")
    payload = json.loads(store.path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == CANDIDATE_SCHEMA_VERSION
    assert payload["revision"] == 1
    assert payload["candidates"]["ad"]["normalized_source"] == "ad"
    assert payload["candidates"]["ad"]["status"] == "candidate"
    assert payload["candidates"]["ad"]["accepted_target"] is None
    assert payload["candidates"]["ad"]["rejected_targets"] == []
    assert payload["candidates"]["ad"]["targets"][0]["last_observed_at"]


def test_wrong_first_translation_does_not_win_after_correct_observations(tmp_path):
    store = CandidateStore(doc_dir(tmp_path))
    store.record_observation("TCS", "错误首译", pages=[1], evidence=["page one"])
    for page in range(2, 12):
        store.record_observation("TCS", "正确译法", pages=[page], evidence=[f"page {page}"])
    entries, _, _ = store.load()
    entry = entries[0]
    ranked = rank_target_suggestions(entry)
    assert ranked[0].target == "正确译法"
    assert ranked[0].observations == 10
    assert ranked[0].distinct_page_count == 10
    accepted, _ = store.accept("TCS")
    assert accepted.accepted_target == "正确译法"


def test_batch_permutation_yields_identical_stats_and_persistence(tmp_path, monkeypatch):
    class _FixedDatetime:
        fixed = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)

        @classmethod
        def now(cls, tz=UTC) -> datetime:
            return cls.fixed

    monkeypatch.setattr(candidate_store, "datetime", _FixedDatetime)
    batch = [
        CandidateObservation(source="AD", target="译法甲", pages=(1,), evidence=("e1",)),
        CandidateObservation(source="AD", target="译法甲", pages=(2,), evidence=("e2",)),
        CandidateObservation(source="AD", target="译法甲", pages=(2,), evidence=("e2",)),
        CandidateObservation(source="AD", target="译法乙", pages=(1, 2), evidence=("e3", "e4")),
        CandidateObservation(source="TCS", target="外用糖皮质激素", pages=(3,), evidence=("e5",)),
    ]
    permutations = [
        batch,
        list(reversed(batch)),
        [batch[3], batch[1], batch[4], batch[0], batch[2]],
    ]
    stores = []
    for index in range(len(permutations)):
        directory = tmp_path / f"{index:064x}"
        directory.mkdir()
        stores.append(CandidateStore(directory))
    for store, observations in zip(stores, permutations):
        store.record_observations(observations, strategy_version="extractor/1")
    payloads = [store.path.read_bytes() for store in stores]
    assert payloads[0] == payloads[1] == payloads[2]

    loaded = [store.load()[0] for store in stores]
    for entries in loaded:
        ad = next(entry for entry in entries if entry.source_key == "ad")
        targets = {suggestion.target: suggestion for suggestion in ad.targets}
        assert targets["译法甲"].observations == 3
        assert targets["译法甲"].pages == (1, 2)
        assert targets["译法乙"].observations == 1
        assert targets["译法乙"].pages == (1, 2)
    assert [s.target for s in rank_target_suggestions(loaded[0][0])] == [
        s.target for s in rank_target_suggestions(loaded[1][0])
    ]
    assert [s.target for s in rank_target_suggestions(loaded[0][0])] == [
        s.target for s in rank_target_suggestions(loaded[2][0])
    ]


def test_v1_payload_reads_and_upgrades_on_next_write(tmp_path):
    store = CandidateStore(doc_dir(tmp_path))
    payload = _valid_candidate_payload()
    store.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    entries, revision, _ = store.load()
    assert revision == 1
    assert len(entries) == 1
    suggestion = entries[0].targets[0]
    assert suggestion.observations == 1
    assert suggestion.last_observed_at == entries[0].last_seen_at

    store.record_observation("TCS", "外用糖皮质激素")
    stored = json.loads(store.path.read_text(encoding="utf-8"))
    assert stored["schema_version"] == CANDIDATE_SCHEMA_VERSION
    assert stored["revision"] == 2
    assert stored["candidates"]["ad"]["targets"][0]["last_observed_at"]
    assert stored["candidates"]["tcs"]["targets"][0]["last_observed_at"]


def _valid_candidate_payload_v2() -> dict:
    payload = _valid_candidate_payload()
    payload["schema_version"] = CANDIDATE_SCHEMA_VERSION
    payload["candidates"]["ad"]["targets"][0]["last_observed_at"] = "2026-08-31T10:00:00+00:00"
    return payload


def test_v2_payload_with_target_time_loads(tmp_path):
    store = CandidateStore(doc_dir(tmp_path))
    payload = _valid_candidate_payload_v2()
    store.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    entries, revision, _ = store.load()
    assert revision == 1
    assert entries[0].targets[0].last_observed_at == datetime(2026, 8, 31, 10, 0, 0, tzinfo=UTC)


def test_v2_requires_target_last_observed_at(tmp_path):
    store = CandidateStore(doc_dir(tmp_path))
    payload = _valid_candidate_payload_v2()
    del payload["candidates"]["ad"]["targets"][0]["last_observed_at"]
    _assert_fail_closed(store, payload, "last_observed_at")


def test_v2_rejects_invalid_target_last_observed_at(tmp_path):
    store = CandidateStore(doc_dir(tmp_path))
    payload = _valid_candidate_payload_v2()
    payload["candidates"]["ad"]["targets"][0]["last_observed_at"] = "not-a-date"
    _assert_fail_closed(store, payload, "last_observed_at")


def test_accept_without_target_uses_deterministic_ranked_first(tmp_path):
    store = CandidateStore(doc_dir(tmp_path))
    store.record_observation("TCS", "乙译法", pages=[1])
    store.record_observation("TCS", "甲译法", pages=[1, 2, 3])
    store.record_observation("TCS", "甲译法", pages=[4])
    store.record_observation("TCS", "甲译法", pages=[5])
    store.record_observation("TCS", "甲译法", pages=[6])
    entry, _ = store.accept("TCS")
    assert entry.accepted_target == "甲译法"
    assert entry.targets[0].target == "乙译法"


def test_accept_explicit_target_clears_its_own_rejection(tmp_path):
    store = CandidateStore(doc_dir(tmp_path))
    store.record_observation("AD", "译法")
    store.reject("AD", target="译法")
    entry, _ = store.accept("AD", target="译法")
    assert entry.status == "accepted"
    assert entry.accepted_target == "译法"
    assert entry.rejected_targets == []
    entries, _, _ = store.load()
    assert entries[0].rejected_targets == []
    summary = store.target_summaries("AD")[0]
    assert summary.accepted is True
    assert summary.rejected is False
    assert summary.suppressed is False

    # 自动观察不得把已接受的 target 重新标记为拒绝或改变状态。
    store.record_observation("AD", "译法", pages=[2])
    entries, _, _ = store.load()
    assert entries[0].status == "accepted"
    assert entries[0].accepted_target == "译法"
    assert entries[0].rejected_targets == []


def test_accept_without_target_clears_ranked_first_rejection(tmp_path):
    store = CandidateStore(doc_dir(tmp_path))
    store.record_observation("AD", "译法")
    store.reject("AD", target="译法")
    entry, _ = store.accept("AD")
    assert entry.status == "accepted"
    assert entry.accepted_target == "译法"
    assert entry.rejected_targets == []
    summary = store.target_summaries("AD")[0]
    assert summary.accepted is True
    assert summary.rejected is False
    assert summary.suppressed is False


def test_accept_keeps_other_rejected_targets(tmp_path):
    store = CandidateStore(doc_dir(tmp_path))
    store.record_observation("AD", "译法A")
    store.record_observation("AD", "译法B")
    store.reject("AD", target="译法A")
    store.reject("AD", target="译法B")
    entry, _ = store.accept("AD", target="译法A")
    assert entry.status == "accepted"
    assert entry.accepted_target == "译法A"
    assert entry.rejected_targets == ["译法B"]
    summaries = store.target_summaries("AD")
    by_target = {item.target: item for item in summaries}
    assert by_target["译法A"].accepted is True
    assert by_target["译法A"].rejected is False
    assert by_target["译法A"].suppressed is False
    assert by_target["译法B"].rejected is True
    assert by_target["译法B"].suppressed is True


def test_accepted_target_survives_higher_stat_auto_observations(tmp_path):
    document_dir = doc_dir(tmp_path)
    store = CandidateStore(document_dir)
    store.record_observation("AD", "自动建议")
    store.accept("AD", target="用户确认")
    for page in range(1, 21):
        store.record_observation("AD", "高票自动建议", pages=[page])
    entries, _, _ = store.load()
    entry = entries[0]
    assert entry.status == "accepted"
    assert entry.accepted_target == "用户确认"
    assert rank_target_suggestions(entry)[0].target == "用户确认"
    again, _ = store.accept("AD")
    assert again.accepted_target == "用户确认"

    summaries = store.target_summaries("AD")
    assert [item.target for item in summaries] == ["用户确认", "高票自动建议", "自动建议"]
    assert summaries[0].accepted is True
    assert summaries[0].rejected is False
    assert summaries[0].suppressed is False
    assert summaries[0].rank == 1
    assert summaries[1].target == "高票自动建议"
    assert summaries[1].observations == 20
    assert summaries[1].distinct_page_count == 20


def test_rejected_target_stats_grow_but_stay_suppressed(tmp_path):
    store = CandidateStore(doc_dir(tmp_path))
    store.record_observation("benefits", "福利", pages=[1])
    store.reject("benefits", target="福利")
    store.record_observation("benefits", "福利", pages=[2, 3], evidence=["again"])
    store.record_observation("benefits", "新建议", pages=[4])
    entries, revision, _ = store.load()
    assert revision == 4
    entry = entries[0]
    assert entry.status == "rejected"
    assert entry.rejected_targets == ["福利"]
    by_target = {suggestion.target: suggestion for suggestion in entry.targets}
    assert by_target["福利"].observations == 2
    assert by_target["福利"].pages == (1, 2, 3)

    summaries = store.target_summaries("benefits")
    assert [item.target for item in summaries] == ["新建议", "福利"]
    assert all(item.suppressed for item in summaries)
    assert summaries[1].rejected is True
    assert summaries[1].observations == 2
    assert summaries[1].distinct_page_count == 3


def test_candidate_summaries_expose_deterministic_service_boundary(tmp_path):
    store = CandidateStore(doc_dir(tmp_path))
    store.record_observation("TCS", "外用糖皮质激素", pages=[1])
    store.record_observation("AD", "自动建议", pages=[1, 2])
    summaries = store.candidate_summaries()
    assert [summary.source_key for summary in summaries] == ["ad", "tcs"]
    ad = summaries[0]
    assert ad.status == "candidate"
    assert ad.accepted_target is None
    target = ad.targets[0]
    assert target.target == "自动建议"
    assert target.observations == 1
    assert target.distinct_page_count == 2
    assert target.pages == (1, 2)
    assert target.rank == 1
    assert isinstance(target.last_observed_at, datetime)
    assert target.accepted is False
    assert target.rejected is False
    assert target.suppressed is False


def test_two_store_instances_concurrent_writes_do_not_lose_observations(tmp_path):
    document_dir = doc_dir(tmp_path)
    store_a = CandidateStore(document_dir)
    store_b = CandidateStore(document_dir)
    thread_count = 8
    barrier = threading.Barrier(thread_count)
    errors = []

    def worker(index: int) -> None:
        store = store_a if index % 2 == 0 else store_b
        try:
            barrier.wait(timeout=5)
            store.record_observation("AD", "特应性皮炎", pages=[index])
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(thread_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert errors == []
    entries, revision, _ = store_a.load()
    assert revision == thread_count
    assert entries[0].targets[0].observations == thread_count
    assert entries[0].targets[0].pages == tuple(range(thread_count))
    assert not list(document_dir.glob("*.tmp"))


@pytest.mark.parametrize("bad", ["", "   ", "auto\n1", "auto\r1", "auto\x001"])
def test_record_observation_rejects_invalid_strategy_version(tmp_path, bad):
    store = CandidateStore(doc_dir(tmp_path))
    with pytest.raises(TermStoreError, match="strategy_version"):
        store.record_observation("AD", "特应性皮炎", strategy_version=bad)
    assert not store.path.exists()


def _valid_candidate_payload() -> dict:
    return {
        "schema_version": 1,
        "revision": 1,
        "updated_at": "2026-08-31T10:00:00+00:00",
        "candidates": {
            "ad": {
                "source": "AD",
                "normalized_source": "ad",
                "status": "candidate",
                "strategy_version": "auto/1",
                "first_seen_at": "2026-08-31T10:00:00+00:00",
                "last_seen_at": "2026-08-31T10:00:00+00:00",
                "targets": [
                    {
                        "target": "特应性皮炎",
                        "observations": 1,
                        "pages": [1],
                        "evidence": ["page one"],
                    }
                ],
                "accepted_target": None,
                "rejected_targets": [],
            }
        },
    }


def _replace_entry_key_with_case_variant(payload: dict) -> None:
    """把入口 key 改成与规范化 source 不一致的大小写变体。"""
    entry = payload["candidates"].pop("ad")
    payload["candidates"]["AD"] = entry


def _assert_fail_closed(store: CandidateStore, payload: dict, match: str) -> None:
    store.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    original = store.path.read_bytes()
    with pytest.raises(TermStoreError, match=match):
        store.load()
    with pytest.raises(TermStoreError, match=match):
        store.record_observation("TCS", "外用糖皮质激素")
    assert store.path.read_bytes() == original


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda p: p["candidates"]["ad"].update({"normalized_source": "atopic"}), "normalized_source"),
        (_replace_entry_key_with_case_variant, "normalized_source"),
        (lambda p: p["candidates"]["ad"].pop("source"), "missing source"),
        (lambda p: p["candidates"]["ad"].update({"status": "pending"}), "status"),
        (lambda p: p["candidates"]["ad"].update({"status": "accepted", "accepted_target": None}), "accepted_target"),
        (lambda p: p["candidates"]["ad"].update({"accepted_target": "特应性皮炎"}), "accepted_target"),
        (
            lambda p: p["candidates"]["ad"].update({"status": "accepted", "accepted_target": "别的译法"}),
            "accepted_target",
        ),
        (lambda p: p["candidates"]["ad"]["targets"][0].update({"pages": ["1"]}), "page"),
        (lambda p: p["candidates"]["ad"]["targets"][0].update({"pages": [-1]}), "page"),
        (lambda p: p["candidates"]["ad"]["targets"][0].update({"pages": [True]}), "page"),
        (lambda p: p["candidates"]["ad"]["targets"][0].update({"pages": [1, 1]}), "duplicate page"),
        (lambda p: p["candidates"]["ad"]["targets"][0].update({"evidence": ["ok", 5]}), "evidence"),
        (lambda p: p["candidates"]["ad"]["targets"][0].update({"evidence": [""]}), "evidence"),
        (lambda p: p["candidates"]["ad"]["targets"][0].update({"evidence": ["x" * 201]}), "evidence"),
        (lambda p: p["candidates"]["ad"]["targets"][0].update({"evidence": [f"e{i}" for i in range(6)]}), "evidence"),
        (lambda p: p["candidates"]["ad"].update({"rejected_targets": ["ok", 5]}), "rejected"),
        (lambda p: p["candidates"]["ad"].update({"rejected_targets": [""]}), "rejected"),
        (lambda p: p["candidates"]["ad"].update({"rejected_targets": ["x", "x"]}), "duplicate rejected"),
        (lambda p: p.update({"revision": 0}), "revision"),
        (lambda p: p.update({"revision": True}), "revision"),
        (lambda p: p.pop("updated_at"), "updated_at"),
        (lambda p: p.update({"updated_at": "not-a-date"}), "updated_at"),
        (lambda p: p.update({"legacy_migration": "marker"}), "legacy_migration"),
        (lambda p: p.update({"legacy_migration": {"from": "cumulative_glossary.csv"}}), "legacy_migration"),
        (
            lambda p: p.update(
                {
                    "legacy_migration": {
                        "from": "cumulative_glossary.csv",
                        "rows": "2",
                        "completed_at": "2026-08-31T10:00:00+00:00",
                    }
                }
            ),
            "legacy_migration",
        ),
        (lambda p: p["candidates"]["ad"].update({"targets": []}), "targets"),
        (lambda p: p["candidates"]["ad"]["targets"][0].update({"observations": 0}), "observations"),
        (lambda p: p["candidates"]["ad"].pop("first_seen_at"), "first_seen_at"),
        (lambda p: p["candidates"]["ad"].pop("strategy_version"), "strategy_version"),
        (lambda p: p["candidates"]["ad"].update({"strategy_version": "  "}), "strategy_version"),
        (lambda p: p["candidates"]["ad"].update({"strategy_version": "auto\n1"}), "strategy_version"),
        (lambda p: p["candidates"]["ad"].update({"source": " AD "}), "source"),
        (lambda p: p["candidates"]["ad"]["targets"][0].update({"target": " 特应性皮炎 "}), "target"),
        (lambda p: p["candidates"]["ad"].update({"accepted_target": " 特应性皮炎 "}), "accepted_target"),
        (lambda p: p["candidates"]["ad"].update({"rejected_targets": [" 福利 "]}), "rejected"),
        (
            lambda p: (
                p["candidates"].update(
                    {
                        "ad": {
                            "source": "AD",
                            "normalized_source": "ad",
                            "status": "candidate",
                            "strategy_version": "auto/1",
                            "first_seen_at": "2026-08-31T10:00:00+00:00",
                            "last_seen_at": "2026-08-31T10:00:00+00:00",
                            "targets": [{"target": "特应性皮炎", "observations": 1, "pages": [], "evidence": []}],
                            "accepted_target": None,
                            "rejected_targets": [],
                        }
                    }
                )
                or p["candidates"].update(
                    {
                        "AD": {
                            "source": "AD",
                            "normalized_source": "ad",
                            "status": "candidate",
                            "strategy_version": "auto/1",
                            "first_seen_at": "2026-08-31T10:00:00+00:00",
                            "last_seen_at": "2026-08-31T10:00:00+00:00",
                            "targets": [{"target": "特应性皮炎", "observations": 1, "pages": [], "evidence": []}],
                            "accepted_target": None,
                            "rejected_targets": [],
                        }
                    }
                )
            ),
            "normalized_source",
        ),
    ],
)
def test_fail_closed_rejects_invalid_persisted_payload(tmp_path, mutate, match):
    store = CandidateStore(doc_dir(tmp_path))
    payload = _valid_candidate_payload()
    mutate(payload)
    _assert_fail_closed(store, payload, match)
