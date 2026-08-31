"""P0-03 确定性有效词表编译：优先级、冲突、排除、原子性、确定性与路径控制。"""

import csv
import hashlib
import json
import os
import threading
import time
from pathlib import Path

import pytest

from pdf_reader import glossary_compiler
from pdf_reader.candidate_store import CANDIDATE_FILENAME, CandidateStore
from pdf_reader.glossary_compiler import (
    EFFECTIVE_GLOSSARY_FILENAME,
    EFFECTIVE_GLOSSARY_META_FILENAME,
    GLOSSARY_COMPILER_VERSION,
    CompileResult,
    GlossaryCompileError,
    GlossaryStaleError,
    compile_effective_glossary,
    load_effective_glossary,
    verify_effective_glossary,
)
from pdf_reader.term_model import TermStoreError
from pdf_reader.user_glossary import USER_GLOSSARY_FILENAME, UserGlossaryStore


def doc_dir(tmp_path: Path) -> Path:
    directory = tmp_path / ("c" * 64)
    directory.mkdir()
    return directory


def _write_global(path: Path, rows: list[tuple[str, str]]) -> Path:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["source", "target"])
        writer.writerows(rows)
    return path


def _read_output_csv(path: Path) -> list[tuple[str, str]]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        assert next(reader) == ["source", "target"]
        return [(row[0], row[1]) for row in reader if row]


def test_document_dir_must_be_64_hex_hash(tmp_path):
    with pytest.raises(TermStoreError, match="64-char hex hash"):
        compile_effective_glossary(tmp_path, tmp_path / "global.csv")


def test_empty_inputs_produce_header_only_output(tmp_path):
    document_dir = doc_dir(tmp_path)
    global_path = tmp_path / "missing_global.csv"
    result = compile_effective_glossary(document_dir, global_path)
    assert result.rows == 0
    assert result.document_terms == 0
    assert result.accepted_candidates == 0
    assert result.global_terms == 0
    assert (document_dir / EFFECTIVE_GLOSSARY_FILENAME).read_bytes() == b"source,target\r\n"
    verify_effective_glossary(document_dir, global_path)

    again = compile_effective_glossary(document_dir, global_path)
    assert again.csv_path.read_bytes() == result.csv_path.read_bytes()
    assert again.csv_sha256 == result.csv_sha256
    assert again.meta_sha256 == result.meta_sha256


def test_priority_document_over_accepted_over_global(tmp_path):
    document_dir = doc_dir(tmp_path)
    global_path = _write_global(
        tmp_path / "global.csv",
        [("AD", "全局译法"), ("benefits", "全局获益"), ("global-only", "全局词条")],
    )
    user_store = UserGlossaryStore(document_dir)
    user_store.add("AD", "用户译法")

    candidate_store = CandidateStore(document_dir)
    candidate_store.record_observation("AD", "自动建议")
    candidate_store.accept("AD", target="自动建议")
    candidate_store.record_observation("TCS", "外用糖皮质激素")
    candidate_store.accept("TCS")
    candidate_store.record_observation("benefits", "自动获益", pages=[1])

    result = compile_effective_glossary(document_dir, global_path)
    rows = _read_output_csv(document_dir / EFFECTIVE_GLOSSARY_FILENAME)
    assert rows == [
        ("AD", "用户译法"),
        ("benefits", "全局获益"),
        ("global-only", "全局词条"),
        ("TCS", "外用糖皮质激素"),
    ]
    assert result.document_terms == 1
    assert result.accepted_candidates == 2
    assert result.global_terms == 3


def test_locked_document_term_is_included_and_wins(tmp_path):
    document_dir = doc_dir(tmp_path)
    global_path = _write_global(tmp_path / "global.csv", [("AD", "全局译法")])
    user_store = UserGlossaryStore(document_dir)
    user_store.add("AD", "锁定译法", locked=True)
    candidate_store = CandidateStore(document_dir)
    candidate_store.record_observation("AD", "自动建议")
    candidate_store.accept("AD")

    compile_effective_glossary(document_dir, global_path)
    assert _read_output_csv(document_dir / EFFECTIVE_GLOSSARY_FILENAME) == [("AD", "锁定译法")]


def test_candidate_and_rejected_never_enter_regardless_of_observations(tmp_path):
    document_dir = doc_dir(tmp_path)
    global_path = _write_global(tmp_path / "global.csv", [("fallback", "全局词条")])
    candidate_store = CandidateStore(document_dir)
    candidate_store.record_observation("candidate-only", "自动A", pages=[1, 2, 3])
    candidate_store.record_observation("candidate-only", "自动A", pages=[1, 2, 3])
    candidate_store.record_observation("rejected-only", "自动B", pages=[1])
    candidate_store.reject("rejected-only", target="自动B")

    compile_effective_glossary(document_dir, global_path)
    rows = _read_output_csv(document_dir / EFFECTIVE_GLOSSARY_FILENAME)
    assert rows == [("fallback", "全局词条")]


def test_higher_stat_auto_suggestion_cannot_override_accepted_target(tmp_path):
    document_dir = doc_dir(tmp_path)
    global_path = tmp_path / "missing_global.csv"
    candidate_store = CandidateStore(document_dir)
    candidate_store.record_observation("AD", "错误首译", pages=[1])
    candidate_store.accept("AD", target="用户确认译法")
    for page in range(2, 12):
        candidate_store.record_observation("AD", "高票自动建议", pages=[page])

    compile_effective_glossary(document_dir, global_path)
    assert _read_output_csv(document_dir / EFFECTIVE_GLOSSARY_FILENAME) == [("AD", "用户确认译法")]
    verify_effective_glossary(document_dir, global_path)


def test_v1_candidate_file_compiles_with_compat_read(tmp_path):
    document_dir = doc_dir(tmp_path)
    global_path = tmp_path / "missing_global.csv"
    payload = {
        "schema_version": 1,
        "revision": 1,
        "updated_at": "2026-08-31T10:00:00+00:00",
        "candidates": {
            "ad": {
                "source": "AD",
                "normalized_source": "ad",
                "status": "accepted",
                "strategy_version": "auto/1",
                "first_seen_at": "2026-08-31T10:00:00+00:00",
                "last_seen_at": "2026-08-31T10:00:00+00:00",
                "targets": [
                    {
                        "target": "自动建议已接受",
                        "observations": 1,
                        "pages": [1],
                        "evidence": ["e"],
                    }
                ],
                "accepted_target": "自动建议已接受",
                "rejected_targets": [],
            }
        },
    }
    (document_dir / CANDIDATE_FILENAME).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    compile_effective_glossary(document_dir, global_path)
    assert _read_output_csv(document_dir / EFFECTIVE_GLOSSARY_FILENAME) == [("AD", "自动建议已接受")]
    verify_effective_glossary(document_dir, global_path)


def test_accepted_candidate_uses_edited_target_and_source_display(tmp_path):
    document_dir = doc_dir(tmp_path)
    global_path = _write_global(tmp_path / "global.csv", [("Atopic  Dermatitis", "全局译法")])
    candidate_store = CandidateStore(document_dir)
    candidate_store.record_observation("Atopic  Dermatitis", "自动建议")
    candidate_store.accept("Atopic  Dermatitis", target="用户编辑译法")

    compile_effective_glossary(document_dir, global_path)
    assert _read_output_csv(document_dir / EFFECTIVE_GLOSSARY_FILENAME) == [("Atopic  Dermatitis", "用户编辑译法")]


def test_same_level_global_conflict_fails_closed(tmp_path):
    document_dir = doc_dir(tmp_path)
    global_path = _write_global(tmp_path / "global.csv", [("AD", "译法A")])
    first = compile_effective_glossary(document_dir, global_path)
    old_csv = first.csv_path.read_bytes()
    old_meta = first.meta_path.read_bytes()

    _write_global(global_path, [("AD", "译法A"), ("ad", "译法B")])
    with pytest.raises(GlossaryCompileError, match="conflicting targets"):
        compile_effective_glossary(document_dir, global_path)
    assert first.csv_path.read_bytes() == old_csv
    assert first.meta_path.read_bytes() == old_meta
    assert not list(document_dir.glob("*.tmp"))
    assert not list(document_dir.glob("*.bak.tmp"))


def test_same_level_document_conflict_fails_closed(tmp_path):
    document_dir = doc_dir(tmp_path)
    global_path = tmp_path / "missing_global.csv"
    first = compile_effective_glossary(document_dir, global_path)
    old_csv = first.csv_path.read_bytes()
    old_meta = first.meta_path.read_bytes()

    user_path = document_dir / USER_GLOSSARY_FILENAME
    with open(user_path, "w", newline="", encoding="utf-8") as f:
        f.write("# schema_version=1; revision=2\n")
        writer = csv.writer(f)
        writer.writerow(["source", "target", "locked", "created_at", "updated_at", "note"])
        writer.writerow(["AD", "译法A", "false", "2026-08-31T10:00:00+00:00", "2026-08-31T10:00:00+00:00", ""])
        writer.writerow(["ad", "译法B", "false", "2026-08-31T10:00:00+00:00", "2026-08-31T10:00:00+00:00", ""])
    with pytest.raises(TermStoreError, match="duplicate"):
        compile_effective_glossary(document_dir, global_path)
    assert first.csv_path.read_bytes() == old_csv
    assert first.meta_path.read_bytes() == old_meta


def test_same_target_dedupes_deterministically(tmp_path):
    document_dir = doc_dir(tmp_path)
    global_path = _write_global(tmp_path / "global.csv", [(" AD ", "同一译法"), ("ad", "同一译法")])
    first = compile_effective_glossary(document_dir, global_path)
    rows = _read_output_csv(first.csv_path)
    assert rows == [("AD", "同一译法")]
    second = compile_effective_glossary(document_dir, global_path)
    assert first.csv_path.read_bytes() == second.csv_path.read_bytes()
    assert first.meta_path.read_bytes() == second.meta_path.read_bytes()


def test_case_and_whitespace_merge_but_display_text_preserved(tmp_path):
    document_dir = doc_dir(tmp_path)
    global_path = _write_global(tmp_path / "global.csv", [("ATOPIC DERMATITIS", "全局译法")])
    user_store = UserGlossaryStore(document_dir)
    user_store.add("Atopic   Dermatitis", "用户译法")
    candidate_store = CandidateStore(document_dir)
    candidate_store.record_observation("atopic dermatitis", "自动建议")
    candidate_store.accept("atopic dermatitis")

    compile_effective_glossary(document_dir, global_path)
    assert _read_output_csv(document_dir / EFFECTIVE_GLOSSARY_FILENAME) == [("Atopic   Dermatitis", "用户译法")]


def test_plural_hyphen_abbreviation_full_name_not_merged(tmp_path):
    document_dir = doc_dir(tmp_path)
    global_path = _write_global(
        tmp_path / "global.csv",
        [("ADs", "复数译法"), ("TC-S", "连字符译法"), ("atopic dermatitis", "全称译法")],
    )
    user_store = UserGlossaryStore(document_dir)
    user_store.add("AD", "缩写译法")

    compile_effective_glossary(document_dir, global_path)
    rows = _read_output_csv(document_dir / EFFECTIVE_GLOSSARY_FILENAME)
    assert [source for source, _ in rows] == ["AD", "ADs", "atopic dermatitis", "TC-S"]
    assert len(rows) == 4


def test_output_order_is_deterministic_sorted(tmp_path):
    document_dir = doc_dir(tmp_path)
    global_path = tmp_path / "missing_global.csv"
    user_store = UserGlossaryStore(document_dir)
    for source, target in [("Zebra", "斑马"), ("banana", "香蕉"), ("Apple", "苹果")]:
        user_store.add(source, target)

    compile_effective_glossary(document_dir, global_path)
    assert _read_output_csv(document_dir / EFFECTIVE_GLOSSARY_FILENAME) == [
        ("Apple", "苹果"),
        ("banana", "香蕉"),
        ("Zebra", "斑马"),
    ]


def test_deterministic_bytes_after_recompile_and_delete_rebuild(tmp_path):
    document_dir = doc_dir(tmp_path)
    global_path = _write_global(tmp_path / "global.csv", [("AD", "全局译法"), ("TCS", "外用糖皮质激素")])
    user_store = UserGlossaryStore(document_dir)
    user_store.add("AD", "用户译法")
    candidate_store = CandidateStore(document_dir)
    candidate_store.record_observation("TCS", "外用糖皮质激素")
    candidate_store.accept("TCS")

    input_files = [
        document_dir / USER_GLOSSARY_FILENAME,
        document_dir / CANDIDATE_FILENAME,
        global_path,
    ]
    input_bytes = {path: path.read_bytes() for path in input_files}

    first = compile_effective_glossary(document_dir, global_path)
    first_csv = first.csv_path.read_bytes()
    first_meta = first.meta_path.read_bytes()

    again = compile_effective_glossary(document_dir, global_path)
    assert again.csv_path.read_bytes() == first_csv
    assert again.meta_path.read_bytes() == first_meta

    first.csv_path.unlink()
    first.meta_path.unlink()
    rebuilt = compile_effective_glossary(document_dir, global_path)
    assert rebuilt.csv_path.read_bytes() == first_csv
    assert rebuilt.meta_path.read_bytes() == first_meta
    assert all(path.read_bytes() == original for path, original in input_bytes.items())
    assert not list(document_dir.glob("*.tmp"))
    assert not list(document_dir.glob("*.bak.tmp"))


def test_corrupt_output_is_rebuilt_from_valid_inputs(tmp_path):
    document_dir = doc_dir(tmp_path)
    global_path = tmp_path / "missing_global.csv"
    user_store = UserGlossaryStore(document_dir)
    user_store.add("AD", "用户译法")
    first = compile_effective_glossary(document_dir, global_path)
    first.csv_path.write_bytes(b"garbage not csv")

    rebuilt = compile_effective_glossary(document_dir, global_path)
    assert _read_output_csv(rebuilt.csv_path) == [("AD", "用户译法")]
    verify_effective_glossary(document_dir, global_path)


def test_bad_user_glossary_preserves_old_outputs(tmp_path):
    document_dir = doc_dir(tmp_path)
    global_path = tmp_path / "missing_global.csv"
    user_store = UserGlossaryStore(document_dir)
    user_store.add("AD", "用户译法")
    first = compile_effective_glossary(document_dir, global_path)
    old_csv = first.csv_path.read_bytes()
    old_meta = first.meta_path.read_bytes()

    (document_dir / USER_GLOSSARY_FILENAME).write_bytes(b"\xff\xfe broken")
    with pytest.raises(GlossaryCompileError):
        compile_effective_glossary(document_dir, global_path)
    assert first.csv_path.read_bytes() == old_csv
    assert first.meta_path.read_bytes() == old_meta


def test_bad_candidate_store_preserves_old_outputs(tmp_path):
    document_dir = doc_dir(tmp_path)
    global_path = tmp_path / "missing_global.csv"
    candidate_store = CandidateStore(document_dir)
    candidate_store.record_observation("TCS", "外用糖皮质激素")
    candidate_store.accept("TCS")
    first = compile_effective_glossary(document_dir, global_path)
    old_csv = first.csv_path.read_bytes()
    old_meta = first.meta_path.read_bytes()

    (document_dir / CANDIDATE_FILENAME).write_text("{broken", encoding="utf-8")
    with pytest.raises(GlossaryCompileError):
        compile_effective_glossary(document_dir, global_path)
    assert first.csv_path.read_bytes() == old_csv
    assert first.meta_path.read_bytes() == old_meta


def test_bad_global_glossary_preserves_old_outputs(tmp_path):
    document_dir = doc_dir(tmp_path)
    global_path = _write_global(tmp_path / "global.csv", [("AD", "全局译法")])
    first = compile_effective_glossary(document_dir, global_path)
    old_csv = first.csv_path.read_bytes()
    old_meta = first.meta_path.read_bytes()

    global_path.write_text("foo,bar\nAD,全局译法\n", encoding="utf-8")
    with pytest.raises(GlossaryCompileError, match="header"):
        compile_effective_glossary(document_dir, global_path)
    assert first.csv_path.read_bytes() == old_csv
    assert first.meta_path.read_bytes() == old_meta


def test_fsync_failure_keeps_last_valid_pair(tmp_path, monkeypatch):
    document_dir = doc_dir(tmp_path)
    global_path = tmp_path / "missing_global.csv"
    user_store = UserGlossaryStore(document_dir)
    user_store.add("AD", "用户译法")
    first = compile_effective_glossary(document_dir, global_path)
    old_csv = first.csv_path.read_bytes()
    old_meta = first.meta_path.read_bytes()

    monkeypatch.setattr(
        glossary_compiler.os,
        "fsync",
        lambda fd: (_ for _ in ()).throw(OSError("fsync failed")),
    )
    with pytest.raises(GlossaryCompileError, match="fsync failed"):
        compile_effective_glossary(document_dir, global_path)
    assert first.csv_path.read_bytes() == old_csv
    assert first.meta_path.read_bytes() == old_meta
    assert not list(document_dir.glob("*.tmp"))
    assert not list(document_dir.glob("*.bak.tmp"))


def test_replace_failure_keeps_last_valid_pair(tmp_path, monkeypatch):
    document_dir = doc_dir(tmp_path)
    global_path = tmp_path / "missing_global.csv"
    user_store = UserGlossaryStore(document_dir)
    user_store.add("AD", "用户译法")
    first = compile_effective_glossary(document_dir, global_path)
    old_csv = first.csv_path.read_bytes()
    old_meta = first.meta_path.read_bytes()
    real_replace = os.replace

    def fake_replace(src, dst) -> None:
        if Path(dst) == first.csv_path:
            raise OSError("replace failed")
        return real_replace(src, dst)

    monkeypatch.setattr(glossary_compiler.os, "replace", fake_replace)
    with pytest.raises(GlossaryCompileError, match="replace failed"):
        compile_effective_glossary(document_dir, global_path)
    assert first.csv_path.read_bytes() == old_csv
    assert first.meta_path.read_bytes() == old_meta
    assert not list(document_dir.glob("*.tmp"))
    assert not list(document_dir.glob("*.bak.tmp"))


def test_sidecar_replace_failure_rolls_back_csv(tmp_path, monkeypatch):
    document_dir = doc_dir(tmp_path)
    global_path = tmp_path / "missing_global.csv"
    user_store = UserGlossaryStore(document_dir)
    user_store.add("AD", "用户译法")
    first = compile_effective_glossary(document_dir, global_path)
    old_csv = first.csv_path.read_bytes()
    old_meta = first.meta_path.read_bytes()
    real_replace = os.replace

    def fake_replace(src, dst) -> None:
        if Path(dst) == first.meta_path:
            raise OSError("meta replace failed")
        return real_replace(src, dst)

    monkeypatch.setattr(glossary_compiler.os, "replace", fake_replace)
    with pytest.raises(GlossaryCompileError) as excinfo:
        compile_effective_glossary(document_dir, global_path)
    assert excinfo.value.inconsistent is False
    assert first.csv_path.read_bytes() == old_csv
    assert first.meta_path.read_bytes() == old_meta
    assert not list(document_dir.glob("*.tmp"))
    assert not list(document_dir.glob("*.bak.tmp"))


def test_rollback_failure_marks_inconsistent(tmp_path, monkeypatch):
    document_dir = doc_dir(tmp_path)
    global_path = tmp_path / "missing_global.csv"
    user_store = UserGlossaryStore(document_dir)
    user_store.add("AD", "用户译法")
    compile_effective_glossary(document_dir, global_path)
    csv_path = document_dir / EFFECTIVE_GLOSSARY_FILENAME
    meta_path = document_dir / EFFECTIVE_GLOSSARY_META_FILENAME
    real_replace = os.replace
    csv_replace_count = {"count": 0}

    def fake_replace(src, dst) -> None:
        dst_path = Path(dst)
        if dst_path == meta_path:
            raise OSError("meta replace failed")
        if dst_path == csv_path:
            csv_replace_count["count"] += 1
            if csv_replace_count["count"] > 1:
                raise OSError("rollback replace failed")
        return real_replace(src, dst)

    monkeypatch.setattr(glossary_compiler.os, "replace", fake_replace)
    with pytest.raises(GlossaryCompileError) as excinfo:
        compile_effective_glossary(document_dir, global_path)
    assert excinfo.value.inconsistent is True
    assert not list(document_dir.glob("*.tmp"))
    assert not list(document_dir.glob("*.bak.tmp"))


def test_concurrent_compiles_are_safe_and_identical(tmp_path):
    document_dir = doc_dir(tmp_path)
    global_path = _write_global(tmp_path / "global.csv", [("benefits", "全局获益")])
    user_store = UserGlossaryStore(document_dir)
    user_store.add("AD", "用户译法")
    candidate_store = CandidateStore(document_dir)
    candidate_store.record_observation("TCS", "外用糖皮质激素")
    candidate_store.accept("TCS")

    reference = compile_effective_glossary(document_dir, global_path)
    reference_csv = reference.csv_path.read_bytes()
    reference_meta = reference.meta_path.read_bytes()

    thread_count = 8
    barrier = threading.Barrier(thread_count)
    errors = []
    results: list[CompileResult] = []
    results_lock = threading.Lock()

    def worker() -> None:
        try:
            barrier.wait(timeout=5)
            result = compile_effective_glossary(document_dir, global_path)
            with results_lock:
                results.append(result)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(thread_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert errors == []
    assert len(results) == thread_count
    assert all(result.csv_sha256 == reference.csv_sha256 for result in results)
    assert reference.csv_path.read_bytes() == reference_csv
    assert reference.meta_path.read_bytes() == reference_meta
    assert not list(document_dir.glob("*.tmp"))
    assert not list(document_dir.glob("*.bak.tmp"))


def test_path_control_writes_only_fixed_files(tmp_path):
    document_dir = doc_dir(tmp_path)
    global_path = _write_global(tmp_path / "global.csv", [("benefits", "全局获益")])
    user_store = UserGlossaryStore(document_dir)
    user_store.add("AD", "用户译法")
    candidate_store = CandidateStore(document_dir)
    candidate_store.record_observation("TCS", "外用糖皮质激素")
    candidate_store.accept("TCS")
    global_bytes = global_path.read_bytes()

    compile_effective_glossary(document_dir, global_path)
    assert sorted(p.name for p in document_dir.iterdir()) == [
        EFFECTIVE_GLOSSARY_FILENAME,
        EFFECTIVE_GLOSSARY_META_FILENAME,
        CANDIDATE_FILENAME,
        USER_GLOSSARY_FILENAME,
    ]
    assert global_path.read_bytes() == global_bytes


def test_verify_detects_tampered_csv(tmp_path):
    document_dir = doc_dir(tmp_path)
    global_path = tmp_path / "missing_global.csv"
    user_store = UserGlossaryStore(document_dir)
    user_store.add("AD", "用户译法")
    first = compile_effective_glossary(document_dir, global_path)
    first.csv_path.write_bytes(first.csv_path.read_bytes() + "X,坏译法\r\n".encode())
    with pytest.raises(GlossaryCompileError, match="mismatch"):
        verify_effective_glossary(document_dir)


def _compile_baseline(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    document_dir = doc_dir(tmp_path)
    global_path = tmp_path / "missing_global.csv"
    user_store = UserGlossaryStore(document_dir)
    user_store.add("AD", "用户译法")
    compile_effective_glossary(document_dir, global_path)
    return (
        document_dir,
        global_path,
        document_dir / EFFECTIVE_GLOSSARY_FILENAME,
        document_dir / EFFECTIVE_GLOSSARY_META_FILENAME,
    )


def test_verify_rejects_missing_sidecar_or_csv(tmp_path):
    document_dir, global_path, csv_path, meta_path = _compile_baseline(tmp_path)
    meta_path.unlink()
    with pytest.raises(GlossaryCompileError, match="sidecar missing"):
        verify_effective_glossary(document_dir, global_path)
    compile_effective_glossary(document_dir, global_path)
    csv_path.unlink()
    with pytest.raises(GlossaryCompileError, match="CSV missing"):
        verify_effective_glossary(document_dir, global_path)


def test_verify_rejects_invalid_json_payload(tmp_path):
    document_dir, global_path, _, meta_path = _compile_baseline(tmp_path)
    meta_path.write_text("{bad", encoding="utf-8")
    with pytest.raises(GlossaryCompileError, match="failed to read"):
        verify_effective_glossary(document_dir, global_path)


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda p: p.pop("inputs"), "sidecar keys"),
        (lambda p: p.update({"extra": 1}), "sidecar keys"),
        (lambda p: p.update({"schema_version": 99}), "schema version"),
        (lambda p: p.update({"compiler_version": "wrong/1"}), "compiler version"),
        (lambda p: p.update({"output": "bad"}), "sidecar output"),
        (lambda p: p["output"].pop("rows"), "output keys"),
        (lambda p: p["output"].update({"extra": 1}), "output keys"),
        (lambda p: p["output"].update({"filename": "wrong.csv"}), "filename"),
        (lambda p: p["output"].update({"sha256": "z" * 64}), "sha256"),
        (lambda p: p["output"].update({"sha256": 123}), "sha256"),
        (lambda p: p["output"].update({"rows": -1}), "row count"),
        (lambda p: p["output"].update({"rows": True}), "row count"),
        (lambda p: p.update({"inputs": "bad"}), "sidecar inputs"),
        (lambda p: p["inputs"].pop("user_glossary.csv"), "input entries"),
        (lambda p: p["inputs"].update({"extra.csv": {"present": False}}), "input entries"),
        (lambda p: p["inputs"].update({"glossary.csv": {"present": False, "rows": 0}}), "invalid fields"),
        (lambda p: p["inputs"]["user_glossary.csv"].pop("sha256"), "invalid fields"),
        (lambda p: p["inputs"]["user_glossary.csv"].update({"sha256": "short"}), "invalid sha256"),
        (lambda p: p["inputs"]["user_glossary.csv"].update({"sha256": "g" * 64}), "invalid sha256"),
        (lambda p: p["inputs"]["user_glossary.csv"].update({"rows": "1"}), "invalid rows"),
        (lambda p: p["inputs"]["user_glossary.csv"].update({"rows": True}), "invalid rows"),
        (lambda p: p["inputs"]["user_glossary.csv"].update({"revision": -1}), "invalid revision"),
        (lambda p: p["inputs"]["user_glossary.csv"].update({"revision": "1"}), "invalid revision"),
        (lambda p: p["inputs"]["glossary.csv"].update({"revision": 1}), "invalid fields"),
        (
            lambda p: p["inputs"]["user_glossary.csv"].update({"accepted_projection": {"rows": 0, "sha256": "0" * 64}}),
            "invalid fields",
        ),
        (
            lambda p: p["inputs"]["term_candidates.json"].update(
                {"present": False, "accepted_projection": {"rows": 0, "sha256": "0" * 64}}
            ),
            "invalid fields",
        ),
        (lambda p: p["inputs"].update({"user_glossary.csv": {"present": None}}), "present"),
        (lambda p: p["inputs"].update({"user_glossary.csv": "bad"}), "input entry"),
        (lambda p: p.update({"inputs": {}}), "input entries"),
    ],
)
def test_verify_strict_sidecar_validation(tmp_path, mutate, match):
    document_dir, global_path, _, meta_path = _compile_baseline(tmp_path)
    payload = json.loads(meta_path.read_text(encoding="utf-8"))
    mutate(payload)
    meta_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with pytest.raises(GlossaryCompileError, match=match):
        verify_effective_glossary(document_dir, global_path)


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda p: p["inputs"]["term_candidates.json"].pop("accepted_projection"), "invalid fields"),
        (lambda p: p["inputs"]["term_candidates.json"].update({"accepted_projection": "bad"}), "accepted_projection"),
        (
            lambda p: p["inputs"]["term_candidates.json"].update({"accepted_projection": {"rows": 1}}),
            "accepted_projection",
        ),
        (
            lambda p: p["inputs"]["term_candidates.json"].update(
                {"accepted_projection": {"rows": 1, "sha256": "x" * 64}}
            ),
            "accepted_projection",
        ),
        (
            lambda p: p["inputs"]["term_candidates.json"].update(
                {"accepted_projection": {"rows": -1, "sha256": "0" * 64}}
            ),
            "accepted_projection",
        ),
        (
            lambda p: p["inputs"]["term_candidates.json"].update(
                {"accepted_projection": {"rows": True, "sha256": "0" * 64}}
            ),
            "accepted_projection",
        ),
        (
            lambda p: p["inputs"]["term_candidates.json"].update(
                {"accepted_projection": {"rows": "1", "sha256": "0" * 64}}
            ),
            "accepted_projection",
        ),
        (
            lambda p: p["inputs"]["term_candidates.json"].update(
                {"accepted_projection": {"rows": 1, "sha256": "g" * 64}}
            ),
            "accepted_projection",
        ),
        (
            lambda p: p["inputs"]["term_candidates.json"].update({"accepted_projection": {"rows": 1, "sha256": 123}}),
            "accepted_projection",
        ),
    ],
)
def test_verify_strict_candidate_projection_validation(tmp_path, mutate, match):
    document_dir = doc_dir(tmp_path)
    global_path = tmp_path / "missing_global.csv"
    candidate_store = CandidateStore(document_dir)
    candidate_store.record_observation("TCS", "外用糖皮质激素")
    candidate_store.accept("TCS")
    compile_effective_glossary(document_dir, global_path)
    meta_path = document_dir / EFFECTIVE_GLOSSARY_META_FILENAME
    payload = json.loads(meta_path.read_text(encoding="utf-8"))
    mutate(payload)
    meta_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with pytest.raises(GlossaryCompileError, match=match):
        verify_effective_glossary(document_dir, global_path)


def test_verify_rejects_csv_hash_mismatch_with_valid_sidecar(tmp_path):
    document_dir, global_path, _, meta_path = _compile_baseline(tmp_path)
    payload = json.loads(meta_path.read_text(encoding="utf-8"))
    payload["output"]["sha256"] = "0" * 64
    meta_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with pytest.raises(GlossaryCompileError, match="mismatch"):
        verify_effective_glossary(document_dir, global_path)


def test_verify_rejects_row_count_mismatch_with_matching_hash(tmp_path):
    document_dir, global_path, csv_path, meta_path = _compile_baseline(tmp_path)
    csv_path.write_bytes(csv_path.read_bytes() + "X,坏译法\r\n".encode())
    payload = json.loads(meta_path.read_text(encoding="utf-8"))
    payload["output"]["sha256"] = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    meta_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with pytest.raises(GlossaryCompileError, match="row count"):
        verify_effective_glossary(document_dir, global_path)


def test_verify_rejects_non_canonical_csv_row(tmp_path):
    document_dir, global_path, csv_path, _ = _compile_baseline(tmp_path)
    csv_path.write_text("source,target\n AD ,译法\r\n", encoding="utf-8")
    with pytest.raises(GlossaryCompileError, match="non-canonical"):
        verify_effective_glossary(document_dir, global_path)


def test_verify_reports_stale_after_user_glossary_change(tmp_path):
    document_dir, global_path, _, _ = _compile_baseline(tmp_path)
    user_store = UserGlossaryStore(document_dir)
    user_store.add("TCS", "外用糖皮质激素")
    with pytest.raises(GlossaryStaleError) as excinfo:
        verify_effective_glossary(document_dir, global_path)
    assert USER_GLOSSARY_FILENAME in excinfo.value.changed_inputs
    with pytest.raises(GlossaryStaleError):
        load_effective_glossary(document_dir, global_path)
    compile_effective_glossary(document_dir, global_path)
    verify_effective_glossary(document_dir, global_path)


def test_candidate_observation_changes_keep_fresh(tmp_path):
    document_dir = doc_dir(tmp_path)
    global_path = tmp_path / "missing_global.csv"
    candidate_store = CandidateStore(document_dir)
    candidate_store.record_observation("TCS", "外用糖皮质激素")
    candidate_store.accept("TCS")
    compile_effective_glossary(document_dir, global_path)

    # 已 accepted 条目被自动观察（新增 target 建议，accepted_target 不变）。
    candidate_store.record_observation(
        "TCS",
        "自动新建议",
        pages=[2],
        evidence=["page two"],
        strategy_version="auto/2",
    )
    # 纯 candidate 新增与观察变化。
    candidate_store.record_observation("benefits", "获益", pages=[1])
    candidate_store.record_observation("benefits", "福利", pages=[3], evidence=["again"])
    # rejected 观察变化。
    candidate_store.record_observation("jargon", "行话")
    candidate_store.reject("jargon")
    candidate_store.record_observation("jargon", "行话", pages=[9])
    verify_effective_glossary(document_dir, global_path)


def test_verify_reports_stale_after_candidate_accepted_change(tmp_path):
    document_dir = doc_dir(tmp_path)
    global_path = tmp_path / "missing_global.csv"
    candidate_store = CandidateStore(document_dir)
    candidate_store.record_observation("TCS", "外用糖皮质激素")
    candidate_store.accept("TCS")
    compile_effective_glossary(document_dir, global_path)
    candidate_store.record_observation("benefits", "获益")
    verify_effective_glossary(document_dir, global_path)
    candidate_store.accept("benefits")
    with pytest.raises(GlossaryStaleError) as excinfo:
        verify_effective_glossary(document_dir, global_path)
    assert CANDIDATE_FILENAME in excinfo.value.changed_inputs


def test_verify_reports_stale_after_candidate_accepted_target_edit(tmp_path):
    document_dir = doc_dir(tmp_path)
    global_path = tmp_path / "missing_global.csv"
    candidate_store = CandidateStore(document_dir)
    candidate_store.record_observation("TCS", "外用糖皮质激素")
    candidate_store.accept("TCS")
    compile_effective_glossary(document_dir, global_path)
    candidate_store.accept("TCS", target="用户改定的新译法")
    with pytest.raises(GlossaryStaleError, match="term_candidates"):
        verify_effective_glossary(document_dir, global_path)


def test_verify_reports_stale_after_candidate_accepted_to_rejected(tmp_path):
    document_dir = doc_dir(tmp_path)
    global_path = tmp_path / "missing_global.csv"
    candidate_store = CandidateStore(document_dir)
    candidate_store.record_observation("TCS", "外用糖皮质激素")
    candidate_store.accept("TCS")
    compile_effective_glossary(document_dir, global_path)
    candidate_store.reject("TCS")
    with pytest.raises(GlossaryStaleError, match="term_candidates"):
        verify_effective_glossary(document_dir, global_path)


def test_candidate_file_created_without_accepted_stays_fresh(tmp_path):
    document_dir = doc_dir(tmp_path)
    global_path = tmp_path / "missing_global.csv"
    compile_effective_glossary(document_dir, global_path)
    candidate_store = CandidateStore(document_dir)
    candidate_store.record_observation("benefits", "获益")
    verify_effective_glossary(document_dir, global_path)
    candidate_store.record_observation("jargon", "行话")
    verify_effective_glossary(document_dir, global_path)
    candidate_store.accept("benefits")
    with pytest.raises(GlossaryStaleError, match="term_candidates"):
        verify_effective_glossary(document_dir, global_path)


def test_candidate_file_deleted_makes_stale(tmp_path):
    document_dir = doc_dir(tmp_path)
    global_path = tmp_path / "missing_global.csv"
    candidate_store = CandidateStore(document_dir)
    candidate_store.record_observation("TCS", "外用糖皮质激素")
    candidate_store.accept("TCS")
    compile_effective_glossary(document_dir, global_path)
    (document_dir / CANDIDATE_FILENAME).unlink()
    with pytest.raises(GlossaryStaleError, match="term_candidates"):
        verify_effective_glossary(document_dir, global_path)


def test_candidate_file_corrupt_fails_verify(tmp_path):
    document_dir = doc_dir(tmp_path)
    global_path = tmp_path / "missing_global.csv"
    candidate_store = CandidateStore(document_dir)
    candidate_store.record_observation("TCS", "外用糖皮质激素")
    candidate_store.accept("TCS")
    compile_effective_glossary(document_dir, global_path)
    (document_dir / CANDIDATE_FILENAME).write_text("{broken", encoding="utf-8")
    with pytest.raises(GlossaryCompileError, match="candidate snapshot"):
        verify_effective_glossary(document_dir, global_path)


def test_verify_reports_stale_after_global_change(tmp_path):
    document_dir = doc_dir(tmp_path)
    global_path = _write_global(tmp_path / "global.csv", [("benefits", "全局获益")])
    compile_effective_glossary(document_dir, global_path)
    _write_global(global_path, [("benefits", "全局获益"), ("extra", "新词条")])
    with pytest.raises(GlossaryStaleError) as excinfo:
        verify_effective_glossary(document_dir, global_path)
    assert "glossary.csv" in excinfo.value.changed_inputs
    compile_effective_glossary(document_dir, global_path)
    verify_effective_glossary(document_dir, global_path)


def test_snapshot_input_lock_blocks_update_and_hash_matches_compiled_version(tmp_path, monkeypatch):
    document_dir = doc_dir(tmp_path)
    global_path = tmp_path / "missing_global.csv"
    user_path = document_dir / USER_GLOSSARY_FILENAME
    user_store = UserGlossaryStore(document_dir)
    user_store.add("AD", "用户译法")
    pre_update_bytes = user_path.read_bytes()

    entered = threading.Event()
    release = threading.Event()
    real_input_meta = glossary_compiler._input_meta

    def blocking_input_meta(path: Path, *, revision: int | None = None, rows: int = 0) -> dict[str, object]:
        if Path(path) == user_path:
            entered.set()
            assert release.wait(timeout=10)
        return real_input_meta(path, revision=revision, rows=rows)

    monkeypatch.setattr(glossary_compiler, "_input_meta", blocking_input_meta)
    compile_errors: list[BaseException] = []

    def compile_worker() -> None:
        try:
            compile_effective_glossary(document_dir, global_path)
        except Exception as exc:  # noqa: BLE001
            compile_errors.append(exc)

    compile_thread = threading.Thread(target=compile_worker)
    compile_thread.start()
    assert entered.wait(timeout=10)

    writer_errors: list[BaseException] = []

    def writer_worker() -> None:
        try:
            user_store.add("TCS", "外用糖皮质激素")
        except Exception as exc:  # noqa: BLE001
            writer_errors.append(exc)

    writer_thread = threading.Thread(target=writer_worker)
    writer_thread.start()
    time.sleep(0.2)
    assert writer_thread.is_alive()
    release.set()
    compile_thread.join(timeout=20)
    writer_thread.join(timeout=20)
    assert compile_errors == []
    assert writer_errors == []
    assert not writer_thread.is_alive()

    csv_path = document_dir / EFFECTIVE_GLOSSARY_FILENAME
    meta_path = document_dir / EFFECTIVE_GLOSSARY_META_FILENAME
    assert _read_output_csv(csv_path) == [("AD", "用户译法")]
    payload = json.loads(meta_path.read_text(encoding="utf-8"))
    recorded = payload["inputs"][USER_GLOSSARY_FILENAME]
    assert recorded["present"] is True
    assert recorded["rows"] == 1
    assert recorded["sha256"] == hashlib.sha256(pre_update_bytes).hexdigest()

    with pytest.raises(GlossaryStaleError, match="user_glossary"):
        verify_effective_glossary(document_dir, global_path)
    rebuilt = compile_effective_glossary(document_dir, global_path)
    assert _read_output_csv(rebuilt.csv_path) == [("AD", "用户译法"), ("TCS", "外用糖皮质激素")]
    verify_effective_glossary(document_dir, global_path)


def test_load_requires_pair_when_either_output_exists(tmp_path):
    document_dir = doc_dir(tmp_path)
    global_path = tmp_path / "missing_global.csv"
    user_store = UserGlossaryStore(document_dir)
    user_store.add("AD", "用户译法")
    compile_effective_glossary(document_dir, global_path)
    csv_path = document_dir / EFFECTIVE_GLOSSARY_FILENAME
    meta_path = document_dir / EFFECTIVE_GLOSSARY_META_FILENAME
    csv_path.unlink()
    with pytest.raises(GlossaryCompileError, match="CSV missing"):
        load_effective_glossary(document_dir, global_path)
    compile_effective_glossary(document_dir, global_path)
    meta_path.unlink()
    with pytest.raises(GlossaryCompileError, match="sidecar missing"):
        load_effective_glossary(document_dir, global_path)
    compile_effective_glossary(document_dir, global_path)
    csv_path.unlink()
    meta_path.unlink()
    assert load_effective_glossary(document_dir, global_path) == []


def test_sidecar_has_only_deterministic_summaries_no_timestamps_or_body(tmp_path):
    document_dir = doc_dir(tmp_path)
    global_path = _write_global(tmp_path / "global.csv", [("benefits", "全局获益")])
    user_store = UserGlossaryStore(document_dir)
    user_store.add("AD", "特应性皮炎")
    candidate_store = CandidateStore(document_dir)
    candidate_store.record_observation("TCS", "外用糖皮质激素")
    candidate_store.accept("TCS")
    compile_effective_glossary(document_dir, global_path)

    meta_path = document_dir / EFFECTIVE_GLOSSARY_META_FILENAME
    payload = json.loads(meta_path.read_text(encoding="utf-8"))
    assert set(payload) == {"schema_version", "compiler_version", "inputs", "output"}
    assert payload["compiler_version"] == GLOSSARY_COMPILER_VERSION
    meta_text = meta_path.read_text(encoding="utf-8").lower()
    for forbidden in ("特应性皮炎", "外用糖皮质激素", "全局获益", "prompt", "api_key", "created_at", "updated_at"):
        assert forbidden not in meta_text
    user_input = payload["inputs"][USER_GLOSSARY_FILENAME]
    assert user_input["present"] is True
    assert user_input["revision"] == 1
    assert user_input["rows"] == 1
    assert len(user_input["sha256"]) == 64
    assert "accepted_projection" not in user_input
    candidate_input = payload["inputs"][CANDIDATE_FILENAME]
    assert candidate_input["present"] is True
    assert candidate_input["revision"] == 2
    projection = candidate_input["accepted_projection"]
    assert projection["rows"] == 1
    assert len(projection["sha256"]) == 64
    assert payload["inputs"]["glossary.csv"]["rows"] == 1
    assert "accepted_projection" not in payload["inputs"]["glossary.csv"]
    assert payload["output"]["filename"] == EFFECTIVE_GLOSSARY_FILENAME
    assert payload["output"]["rows"] == 3
    assert len(payload["output"]["sha256"]) == 64


def test_load_effective_glossary_returns_sorted_rows_and_rejects_bad_files(tmp_path):
    document_dir = doc_dir(tmp_path)
    global_path = tmp_path / "missing_global.csv"
    user_store = UserGlossaryStore(document_dir)
    for source, target in [("Zebra", "斑马"), ("Apple", "苹果")]:
        user_store.add(source, target)
    compile_effective_glossary(document_dir, global_path)
    assert load_effective_glossary(document_dir, global_path) == [("Apple", "苹果"), ("Zebra", "斑马")]

    csv_path = document_dir / EFFECTIVE_GLOSSARY_FILENAME
    csv_path.write_text("foo,bar\nAD,译法\n", encoding="utf-8")
    with pytest.raises(GlossaryCompileError, match="header"):
        load_effective_glossary(document_dir, global_path)
    csv_path.write_text("source,target\nAD\n", encoding="utf-8")
    with pytest.raises(GlossaryCompileError, match="row"):
        load_effective_glossary(document_dir, global_path)
    empty_dir = tmp_path / ("d" * 64)
    empty_dir.mkdir()
    assert load_effective_glossary(empty_dir) == []
