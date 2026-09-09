"""P3-05 缓存分类、统计与孤儿临时工作区清理契约。"""

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
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


# --- P3-05 acceptance: per-task workspace ownership and crash recovery ---


def test_create_temp_workspace_structure_and_marker(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    workspace = cache_ops.create_temp_workspace(cache, job_id="job-1")
    try:
        assert workspace.parent == cache
        assert workspace.name.startswith(cache_ops.TEMP_WORKSPACE_PREFIX)
        assert (workspace / "input").is_dir()
        assert (workspace / "output").is_dir()
        marker = json.loads((workspace / cache_ops.TEMP_MARKER_NAME).read_text(encoding="utf-8"))
        assert marker["kind"] == "pdf-reader-translation-temp"
        assert marker["job_id"] == "job-1"
        assert marker["pid"] == os.getpid()
        assert "created_at" in marker
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def test_create_temp_workspace_cleans_up_when_marker_write_fails(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    cache.mkdir()

    def fail_marker(*args: object, **kwargs: object) -> None:
        raise OSError("marker write failed")

    monkeypatch.setattr(cache_ops, "write_temp_marker", fail_marker)
    before = set(cache.iterdir())

    with pytest.raises(OSError, match="marker write failed"):
        cache_ops.create_temp_workspace(cache, job_id="job-2")

    assert set(cache.iterdir()) == before


def test_create_temp_workspace_cleans_up_when_subdir_creation_fails(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    cache.mkdir()
    real_mkdir = cache_ops.Path.mkdir
    counter = {"n": 0}

    def flaky_mkdir(self: Path, *args: object, **kwargs: object) -> None:
        counter["n"] += 1
        if counter["n"] == 1:
            raise OSError("disk full")
        real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(cache_ops.Path, "mkdir", flaky_mkdir)
    before = set(cache.iterdir())

    with pytest.raises(OSError, match="disk full"):
        cache_ops.create_temp_workspace(cache, job_id="job-3")

    assert set(cache.iterdir()) == before


def test_create_temp_workspace_cleanup_failure_keeps_only_new_dir(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    cache.mkdir()
    doc = cache / ("a" * 64)
    doc.mkdir()
    (doc / "right.pdf").write_bytes(b"keep")

    def fail_marker(*args: object, **kwargs: object) -> None:
        raise OSError("marker write failed")

    def fail_rmtree(path: Path, ignore_errors: bool = False) -> None:
        raise OSError("cannot remove")

    monkeypatch.setattr(cache_ops, "write_temp_marker", fail_marker)
    monkeypatch.setattr(cache_ops.shutil, "rmtree", fail_rmtree)

    with pytest.raises(OSError, match="marker write failed"):
        cache_ops.create_temp_workspace(cache, job_id="job-4")

    leftovers = [p for p in cache.iterdir() if p.name.startswith(cache_ops.TEMP_WORKSPACE_PREFIX)]
    assert len(leftovers) == 1
    assert not (leftovers[0] / cache_ops.TEMP_MARKER_NAME).exists()
    assert (doc / "right.pdf").read_bytes() == b"keep"


def test_recovery_removes_crashed_workspace_with_input_and_output(tmp_path):
    """崩溃模拟：抽取与输出都在已标记根工作区内，启动恢复只删除该工作区；
    right.pdf/术语/进度/未知目录与嵌套前缀目录不受影响。"""
    cache = _make_cache(tmp_path)
    crashed = cache_ops.create_temp_workspace(cache, job_id="crashed")
    (crashed / "input" / "page.pdf").write_bytes(b"extracted")
    (crashed / "output" / "out.pdf").write_bytes(b"output")
    cache_ops.write_temp_marker(crashed, job_id="crashed", pid=999_999_999)

    report = cache_ops.recover_orphan_temp_workspaces(cache)

    assert crashed.name in [p.name for p in report.removed]
    assert not crashed.exists()
    doc_dir = cache / ("h" * 64)
    assert (doc_dir / "right.pdf").exists()
    assert (doc_dir / "cumulative_glossary.csv").exists()
    assert (doc_dir / "reading_progress.json").exists()
    assert (cache / "user-folder").exists()
    assert (cache / (cache_ops.TEMP_WORKSPACE_PREFIX + "unmarked")).exists()
    assert (doc_dir / (cache_ops.TEMP_WORKSPACE_PREFIX + "nested")).exists()


# --- P3-05 acceptance: conservative Windows PID probe ------------------


def _fake_windows_api(
    *,
    open_result: int = 0,
    last_error: int = 0,
    get_exit_ok: bool = True,
    exit_code: int = 259,
    close_calls: list[int] | None = None,
) -> tuple[
    Callable[[int, bool, int], tuple[int, int]],
    Callable[[int], tuple[bool, int]],
    Callable[[int], None],
]:
    def open_process(access: int, inherit: bool, pid: int) -> tuple[int, int]:
        return open_result, last_error

    def get_exit_code(handle: int) -> tuple[bool, int]:
        return get_exit_ok, exit_code

    def close_handle(handle: int) -> None:
        if close_calls is not None:
            close_calls.append(handle)

    return open_process, get_exit_code, close_handle


@pytest.mark.skipif(os.name != "nt", reason="Windows-only real API probe")
def test_windows_pid_alive_current_process_on_windows():
    assert cache_ops._windows_pid_alive(os.getpid()) is True


@pytest.mark.skipif(os.name != "nt", reason="Windows-only real API probe")
def test_windows_pid_alive_nonexistent_pid_on_windows():
    assert cache_ops._windows_pid_alive(999_999_999) is False


def test_windows_pid_alive_invalid_parameter_is_dead(monkeypatch):
    monkeypatch.setattr(
        cache_ops,
        "_load_windows_api",
        lambda: _fake_windows_api(open_result=0, last_error=cache_ops.ERROR_INVALID_PARAMETER),
    )
    assert cache_ops._windows_pid_alive(12345) is False


def test_windows_pid_alive_access_denied_is_unknown(monkeypatch):
    monkeypatch.setattr(cache_ops, "_load_windows_api", lambda: _fake_windows_api(open_result=0, last_error=5))
    assert cache_ops._windows_pid_alive(12345) is True


def test_windows_pid_alive_unknown_error_is_unknown(monkeypatch):
    monkeypatch.setattr(cache_ops, "_load_windows_api", lambda: _fake_windows_api(open_result=0, last_error=6))
    assert cache_ops._windows_pid_alive(12345) is True


def test_windows_pid_alive_get_exit_code_failure_is_unknown(monkeypatch):
    monkeypatch.setattr(
        cache_ops,
        "_load_windows_api",
        lambda: _fake_windows_api(open_result=1, get_exit_ok=False),
    )
    assert cache_ops._windows_pid_alive(12345) is True


def test_windows_pid_alive_closes_handle(monkeypatch):
    closed = []
    api = _fake_windows_api(open_result=7, exit_code=259, close_calls=closed)
    monkeypatch.setattr(cache_ops, "_load_windows_api", lambda: api)

    assert cache_ops._windows_pid_alive(12345) is True
    assert closed == [7]


# --- P3-05 acceptance: POSIX 平台边界（Windows ctypes 永不加载） ----------
# Windows 行为契约由上面的 fake-API 测试固定；以下测试在非 Windows 宿主验证
# ``sys.platform != "win32"`` 边界：ctypes/WinDLL 加载体不执行、存活探测走
# os.kill(pid, 0)。这些测试也约束 Linux 上 mypy 平台检查的对应代码段。


@pytest.mark.skipif(os.name == "nt", reason="POSIX-only real boundary probe")
def test_load_windows_api_returns_none_on_posix():
    assert sys.platform != "win32"
    assert cache_ops._load_windows_api() is None


@pytest.mark.skipif(os.name == "nt", reason="POSIX-only real boundary probe")
def test_posix_liveness_uses_kill_probe(monkeypatch):
    probed: list[int] = []

    def fake_kill(pid: int, sig: int) -> None:
        probed.append(pid)
        raise ProcessLookupError()

    monkeypatch.setattr(cache_ops.os, "kill", fake_kill)
    assert cache_ops.is_process_alive(4242) is False
    assert probed == [4242]


@pytest.mark.skipif(os.name == "nt", reason="POSIX-only real boundary probe")
def test_posix_live_pid_uses_kill_without_windows_api(monkeypatch):
    probed: list[int] = []
    monkeypatch.setattr(cache_ops.os, "kill", lambda pid, sig: probed.append(pid))

    assert cache_ops.is_process_alive(os.getpid()) is True
    assert probed == [os.getpid()]


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
