"""P1-03 便携数据治理 CLI（scripts/portable_data.py）的端到端契约测试。

CLI 是清理与导入的公开命令面：默认只读/预览，任何删除或复制都必须显式确认，
分类统计必须显示大小与删除后果。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from pdf_reader import portable_data
from tests.release import portable_harness as h

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "portable_data.py"


def _run(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--portable-root", str(root), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        cwd=str(REPO_ROOT),
        check=False,
    )


def test_status_reports_schema_and_every_category_with_consequences(tmp_path: Path) -> None:
    layout = h.make_portable_layout(tmp_path)
    assert layout.portable_root is not None

    result = _run(layout.portable_root, "status")

    assert result.returncode == 0, result.stderr
    assert "数据格式版本" in result.stdout
    assert str(layout.data_root) in result.stdout
    for spec in portable_data.CATEGORY_SPECS:
        assert spec.label in result.stdout
        assert spec.consequence in result.stdout
    assert "绝不递归删除 data 之外的用户 PDF" in result.stdout


def test_clean_previews_by_default_and_deletes_only_the_confirmed_category(tmp_path: Path) -> None:
    layout = h.make_portable_layout(tmp_path)
    assert layout.portable_root is not None
    temp_file = layout.data_root / "temp" / "work.bin"
    temp_file.parent.mkdir(parents=True, exist_ok=True)
    temp_file.write_bytes(b"t" * 16)
    document = layout.data_root / "documents" / "abc" / "right.pdf"
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_bytes(b"p" * 8)

    preview = _run(layout.portable_root, "clean", "--category", "temp")
    assert preview.returncode == 0, preview.stderr
    assert "预览" in preview.stdout
    assert "16 B" in preview.stdout
    assert temp_file.exists()

    confirmed = _run(layout.portable_root, "clean", "--category", "temp", "--yes")
    assert confirmed.returncode == 0, confirmed.stderr
    assert "已删除" in confirmed.stdout
    assert not temp_file.exists()
    assert document.read_bytes() == b"p" * 8


def test_clean_requires_an_explicit_category_or_all_flag(tmp_path: Path) -> None:
    layout = h.make_portable_layout(tmp_path)
    assert layout.portable_root is not None

    result = _run(layout.portable_root, "clean", "--yes")

    assert result.returncode == 1
    assert portable_data.CODE_CLEANUP_CATEGORY_REQUIRED in result.stderr
    for spec in portable_data.CATEGORY_SPECS:
        assert spec.key in result.stderr


def test_clean_all_after_confirmation_removes_documents_and_temp(tmp_path: Path) -> None:
    layout = h.make_portable_layout(tmp_path)
    assert layout.portable_root is not None
    document = layout.data_root / "documents" / "abc" / "right.pdf"
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_bytes(b"p" * 8)
    temp_file = layout.data_root / "temp" / "work.bin"
    temp_file.parent.mkdir(parents=True, exist_ok=True)
    temp_file.write_bytes(b"t" * 4)

    result = _run(layout.portable_root, "clean", "--all", "--yes")

    assert result.returncode == 0, result.stderr
    assert not document.exists()
    assert not temp_file.exists()


def test_import_previews_by_default_and_copies_models_without_config(tmp_path: Path) -> None:
    layout = h.make_portable_layout(tmp_path / "new")
    legacy = h.make_portable_layout(tmp_path / "legacy", name="旧 便携")
    assert layout.portable_root is not None
    (legacy.data_root / "config").mkdir(exist_ok=True)
    (legacy.data_root / "config" / "config.toml").write_text("[api]\n", encoding="utf-8")
    model = legacy.data_root / "models" / "doclayout.pt"
    model.parent.mkdir(exist_ok=True)
    model.write_bytes(b"m" * 32)
    document = legacy.data_root / "documents" / "abc" / "right.pdf"
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_bytes(b"p" * 12)

    preview = _run(layout.portable_root, "import", "--from", str(legacy.data_root))
    assert preview.returncode == 0, preview.stderr
    assert "预览" in preview.stdout
    assert not (layout.data_root / "models" / "doclayout.pt").exists()

    confirmed = _run(layout.portable_root, "import", "--from", str(legacy.data_root), "--yes")
    assert confirmed.returncode == 0, confirmed.stderr
    assert (layout.data_root / "models" / "doclayout.pt").read_bytes() == b"m" * 32
    assert (layout.data_root / "documents" / "abc" / "right.pdf").read_bytes() == b"p" * 12
    assert not (layout.data_root / "config" / "config.toml").exists()
    assert portable_data.REASON_CONFIG_PRESERVED in confirmed.stdout


def test_rollback_requires_explicit_confirmation_and_reports_missing_backup(tmp_path: Path) -> None:
    layout = h.make_portable_layout(tmp_path)
    assert layout.portable_root is not None

    refused = _run(layout.portable_root, "rollback")
    assert refused.returncode == 2
    assert "--yes" in refused.stderr

    confirmed = _run(layout.portable_root, "rollback", "--yes")
    assert confirmed.returncode == 1
    assert portable_data.CODE_BACKUP_MISSING in confirmed.stderr
