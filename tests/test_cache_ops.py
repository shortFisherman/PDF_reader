"""P3-05 缓存分类、统计与孤儿临时工作区清理契约。"""

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from pdf_reader import cache_ops

REPO_ROOT = Path(__file__).resolve().parents[1]
MANAGER = REPO_ROOT / "scripts" / "cache_manage.py"


def _make_cache(tmp_path: Path) -> Path:
    cache = tmp_path / "cache"
    cache.mkdir()
    doc_dir = cache / ("h" * 64)
    doc_dir.mkdir()
    (doc_dir / "right.pdf").write_bytes(b"pdf-data")
    (doc_dir / "cumulative_glossary.csv").write_text("source,target\n", encoding="utf-8")
    (doc_dir / "reading_progress.json").write_text('{"page": 3}', encoding="utf-8")

    marked = cache / (cache_ops.TEMP_WORKSPACE_PREFIX + "dead-job")
    marked.mkdir()
    cache_ops.write_temp_marker(marked, job_id="dead-job", pid=999_999_999)
    (marked / "out.pdf").write_bytes(b"x")

    unmarked = cache / (cache_ops.TEMP_WORKSPACE_PREFIX + "unmarked")
    unmarked.mkdir()
    (unmarked / "junk.bin").write_bytes(b"y")

    unknown = cache / "user-folder"
    unknown.mkdir()
    (unknown / "notes.txt").write_text("keep", encoding="utf-8")

    # 嵌套同名目录（位于文档缓存内）不是直接子项，绝不能被清理。
    nested = doc_dir / (cache_ops.TEMP_WORKSPACE_PREFIX + "nested")
    nested.mkdir()
    (nested / "keep.txt").write_text("keep", encoding="utf-8")
    return cache


def test_stats_classifies_documents_and_temp(tmp_path):
    cache = _make_cache(tmp_path)
    result = cache_ops.stats(cache)

    assert len(result.documents) == 1
    doc = result.documents[0]
    assert doc.right_pdf_bytes == 8
    assert doc.glossary_bytes > 0
    assert doc.reading_progress_present is True
    assert len(result.temp_workspaces) == 2
    assert result.temp_workspace_bytes >= 2


def test_stats_only_counts_document_dirs_with_right_pdf(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "user-folder").mkdir()
    (cache / "user-folder" / "notes.txt").write_text("keep", encoding="utf-8")
    doc = cache / ("a" * 64)
    doc.mkdir()
    (doc / "right.pdf").write_bytes(b"pdf")

    result = cache_ops.stats(cache)

    assert [item.hash_dir.name for item in result.documents] == ["a" * 64]


def test_cleanup_only_removes_marked_prefixed_direct_children(tmp_path):
    cache = _make_cache(tmp_path)
    report = cache_ops.cleanup_orphan_temp_workspaces(cache, dry_run=False)

    assert len(report.removed) == 1
    assert report.removed[0].name == cache_ops.TEMP_WORKSPACE_PREFIX + "dead-job"
    assert len(report.kept_unknown) == 1
    assert not (cache / (cache_ops.TEMP_WORKSPACE_PREFIX + "dead-job")).exists()
    assert (cache / (cache_ops.TEMP_WORKSPACE_PREFIX + "unmarked")).exists()
    assert (cache / "user-folder").exists()
    doc_dir = cache / ("h" * 64)
    assert (doc_dir / "right.pdf").exists()
    assert (doc_dir / "cumulative_glossary.csv").exists()
    assert (doc_dir / "reading_progress.json").exists()
    assert (doc_dir / (cache_ops.TEMP_WORKSPACE_PREFIX + "nested")).exists()


def test_dry_run_removes_nothing(tmp_path):
    cache = _make_cache(tmp_path)
    report = cache_ops.cleanup_orphan_temp_workspaces(cache, dry_run=True)

    assert report.dry_run is True
    assert len(report.removed) == 1
    assert (cache / (cache_ops.TEMP_WORKSPACE_PREFIX + "dead-job")).exists()


def test_live_pid_workspace_kept(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    live = cache / (cache_ops.TEMP_WORKSPACE_PREFIX + "live")
    live.mkdir()
    cache_ops.write_temp_marker(live, job_id="live", pid=os.getpid())

    report = cache_ops.cleanup_orphan_temp_workspaces(cache, dry_run=False)

    assert report.removed == ()
    assert len(report.kept_live_pid) == 1
    assert live.exists()


def test_recover_orphan_keeps_live_pid_workspace(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    live = cache / (cache_ops.TEMP_WORKSPACE_PREFIX + "live")
    live.mkdir()
    cache_ops.write_temp_marker(live, job_id="live", pid=os.getpid())

    report = cache_ops.recover_orphan_temp_workspaces(cache)

    assert report.removed == ()
    assert len(report.kept_live_pid) == 1
    assert live.exists()


def test_malformed_or_wrong_markers_are_kept(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    cases = {
        "missing-pid": {"kind": "pdf-reader-translation-temp"},
        "string-pid": {"kind": "pdf-reader-translation-temp", "pid": "123"},
        "negative-pid": {"kind": "pdf-reader-translation-temp", "pid": -1},
        "bool-pid": {"kind": "pdf-reader-translation-temp", "pid": True},
        "wrong-kind": {"kind": "something-else", "pid": 999_999_999},
    }
    for name, marker in cases.items():
        workspace = cache / (cache_ops.TEMP_WORKSPACE_PREFIX + name)
        workspace.mkdir()
        (workspace / cache_ops.TEMP_MARKER_NAME).write_text(json.dumps(marker), encoding="utf-8")

    report = cache_ops.cleanup_orphan_temp_workspaces(cache, dry_run=False)

    assert report.removed == ()
    assert len(report.kept_unknown) == len(cases)
    for name in cases:
        assert (cache / (cache_ops.TEMP_WORKSPACE_PREFIX + name)).exists()


def test_invalid_marker_json_is_kept(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    workspace = cache / (cache_ops.TEMP_WORKSPACE_PREFIX + "corrupt")
    workspace.mkdir()
    (workspace / cache_ops.TEMP_MARKER_NAME).write_text("{not json", encoding="utf-8")

    report = cache_ops.cleanup_orphan_temp_workspaces(cache, dry_run=False)

    assert report.removed == ()
    assert len(report.kept_unknown) == 1
    assert workspace.exists()


def test_prefixed_file_and_symlink_are_never_cleaned(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    prefixed_file = cache / (cache_ops.TEMP_WORKSPACE_PREFIX + "file.txt")
    prefixed_file.write_text("x", encoding="utf-8")
    target = cache / ("h" * 64)
    target.mkdir()
    right_pdf = target / "right.pdf"
    right_pdf.write_bytes(b"keep")
    # 恶意场景：链接目标内部也放一个“有效标记”，若把链接当普通目录清理会误删文档缓存。
    cache_ops.write_temp_marker(target, job_id="evil", pid=999_999_999)
    link = cache / (cache_ops.TEMP_WORKSPACE_PREFIX + "link")
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        try:
            import _winapi

            _winapi.CreateJunction(str(target), str(link))
        except Exception:
            pytest.skip("directory symlinks/junctions are not available in this environment")

    report = cache_ops.cleanup_orphan_temp_workspaces(cache, dry_run=False)

    assert report.removed == ()
    assert link in report.kept_unknown
    assert prefixed_file.exists()
    assert link.exists()
    assert right_pdf.read_bytes() == b"keep"


def test_cleanup_rmtree_failure_reports_error_and_keeps(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    cache.mkdir()
    workspace = cache / (cache_ops.TEMP_WORKSPACE_PREFIX + "stuck")
    workspace.mkdir()
    cache_ops.write_temp_marker(workspace, job_id="stuck", pid=999_999_999)

    def fail_rmtree(path) -> None:
        raise OSError("denied")

    monkeypatch.setattr(cache_ops.shutil, "rmtree", fail_rmtree)
    report = cache_ops.cleanup_orphan_temp_workspaces(cache, dry_run=False)

    assert report.removed == ()
    assert len(report.errors) == 1
    assert workspace.exists()


def test_min_age_keeps_recent_and_removes_old(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    recent = cache / (cache_ops.TEMP_WORKSPACE_PREFIX + "recent")
    recent.mkdir()
    cache_ops.write_temp_marker(recent, job_id="recent", pid=999_999_999)
    old = cache / (cache_ops.TEMP_WORKSPACE_PREFIX + "old")
    old.mkdir()
    marker = {
        "kind": "pdf-reader-translation-temp",
        "job_id": "old",
        "pid": 999_999_999,
        "created_at": (datetime.now(UTC) - timedelta(days=2)).isoformat(),
    }
    (old / cache_ops.TEMP_MARKER_NAME).write_text(json.dumps(marker), encoding="utf-8")

    report = cache_ops.cleanup_orphan_temp_workspaces(cache, dry_run=False, min_age_seconds=3600)

    assert [p.name for p in report.removed] == [cache_ops.TEMP_WORKSPACE_PREFIX + "old"]
    assert len(report.kept_recent) == 1
    assert recent.exists()
    assert not old.exists()


def test_recover_orphan_uses_conservative_defaults(tmp_path):
    cache = _make_cache(tmp_path)
    report = cache_ops.recover_orphan_temp_workspaces(cache)

    assert len(report.removed) == 1
    assert len(report.kept_unknown) == 1


def _run_manager(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MANAGER), *args],
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_cli_stats_json(tmp_path):
    cache = _make_cache(tmp_path)
    result = _run_manager("stats", "--cache-dir", str(cache), "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["document_count"] == 1
    assert payload["documents"][0]["right_pdf_bytes"] == 8
    assert payload["temp_workspace_count"] == 2


def test_cli_orphans_lists_statuses(tmp_path):
    cache = _make_cache(tmp_path)
    result = _run_manager("orphans", "--cache-dir", str(cache))

    assert result.returncode == 0, result.stderr
    assert "marked" in result.stdout
    assert "unknown/unmarked" in result.stdout


def test_cli_clean_dry_run_then_yes(tmp_path):
    cache = _make_cache(tmp_path)
    dry = _run_manager("clean", "--cache-dir", str(cache))
    assert dry.returncode == 0, dry.stderr
    assert "dry-run" in dry.stdout
    assert (cache / (cache_ops.TEMP_WORKSPACE_PREFIX + "dead-job")).exists()

    real = _run_manager("clean", "--cache-dir", str(cache), "--yes")
    assert real.returncode == 0, real.stderr
    assert "removed" in real.stdout
    assert not (cache / (cache_ops.TEMP_WORKSPACE_PREFIX + "dead-job")).exists()
    assert (cache / "user-folder").exists()
    assert (cache / ("h" * 64) / "right.pdf").exists()
