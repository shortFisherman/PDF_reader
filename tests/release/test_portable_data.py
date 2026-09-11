"""P1-03 便携数据治理：schema 检测、备份式迁移、受控导入与分类清理。"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pdf_reader import paths, portable_data
from tests.release import portable_harness as h

FIXED_NOW = datetime(2026, 9, 11, 8, 0, 0, tzinfo=UTC)


def fixed_clock() -> datetime:
    return FIXED_NOW


def make_layout(tmp_path: Path) -> paths.RuntimeLayout:
    return h.make_portable_layout(tmp_path)


def manifest_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": portable_data.SCHEMA_VERSION,
        "product": portable_data.PRODUCT,
        "app_version": "1.0.0",
        "created_at": FIXED_NOW.isoformat(),
        "updated_at": FIXED_NOW.isoformat(),
        "applied_migrations": [portable_data.LEDGER_ADOPT],
    }
    payload.update(overrides)
    return payload


def write_raw_manifest(layout: paths.RuntimeLayout, text: str) -> Path:
    path = portable_data.manifest_path(layout)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def write_manifest(layout: paths.RuntimeLayout, **overrides: object) -> Path:
    return write_raw_manifest(layout, json.dumps(manifest_payload(**overrides), ensure_ascii=False))


def write_file(path: Path, payload: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def temp_leftovers(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.rglob("*") if path.name.endswith(portable_data.TEMP_SUFFIX))


def backup_directories(layout: paths.RuntimeLayout) -> list[Path]:
    root = portable_data.backup_root(layout)
    if not root.is_dir():
        return []
    return sorted(path for path in root.iterdir() if path.is_dir())


class TestSchemaDetection:
    def test_fresh_data_root_is_detected_as_absent(self, tmp_path):
        layout = make_layout(tmp_path)

        status = portable_data.detect_schema(layout)

        assert status.state == "absent"
        assert status.version is None
        assert status.manifest is None
        assert not portable_data.manifest_path(layout).exists()

    def test_detects_current_schema(self, tmp_path):
        layout = make_layout(tmp_path)
        write_manifest(layout)

        status = portable_data.detect_schema(layout)

        assert status.state == "current"
        assert status.version == portable_data.SCHEMA_VERSION
        assert status.manifest is not None
        assert status.manifest.applied_migrations == (portable_data.LEDGER_ADOPT,)

    def test_detects_outdated_schema(self, tmp_path):
        layout = make_layout(tmp_path)
        write_manifest(layout, schema_version=0, applied_migrations=[])

        status = portable_data.detect_schema(layout)

        assert status.state == "outdated"
        assert status.version == 0

    def test_detects_newer_schema_without_touching_it(self, tmp_path):
        layout = make_layout(tmp_path)
        path = write_manifest(layout, schema_version=portable_data.SCHEMA_VERSION + 1)
        original = path.read_bytes()

        status = portable_data.detect_schema(layout)

        assert status.state == "newer"
        assert path.read_bytes() == original

    @pytest.mark.parametrize(
        "text",
        ["{not-json", "[]", json.dumps({"schema_version": "one"})],
    )
    def test_invalid_manifest_is_reported_not_guessed(self, tmp_path, text):
        layout = make_layout(tmp_path)
        write_raw_manifest(layout, text)

        status = portable_data.detect_schema(layout)

        assert status.state == "invalid"
        assert status.version is None


class TestAdoptionMigration:
    def test_adopts_pre_versioned_data_and_records_the_schema(self, tmp_path):
        layout = make_layout(tmp_path)
        right_pdf = write_file(layout.data_root / "documents" / "abc" / "right.pdf", b"%PDF-1.4 translated")
        config = write_file(layout.data_root / "config" / "config.toml", b"[model]\nprovider = 'x'\n")

        report = portable_data.prepare_portable_data(layout, app_version="9.9.9", clock=fixed_clock)

        assert report.performed is True
        assert report.from_version == 0
        assert report.to_version == portable_data.SCHEMA_VERSION
        assert report.backup_dir is not None
        assert layout.require_data_path(report.backup_dir) == report.backup_dir
        manifest = json.loads(portable_data.manifest_path(layout).read_text(encoding="utf-8"))
        assert manifest["schema_version"] == portable_data.SCHEMA_VERSION
        assert manifest["product"] == portable_data.PRODUCT
        assert manifest["app_version"] == "9.9.9"
        assert manifest["applied_migrations"] == [portable_data.LEDGER_ADOPT]
        assert right_pdf.read_bytes() == b"%PDF-1.4 translated"
        assert config.read_bytes() == b"[model]\nprovider = 'x'\n"
        assert temp_leftovers(layout.data_root) == []
        assert "portable-data-adopted" in portable_data.migration_log_path(layout).read_text(encoding="utf-8")

    def test_second_prepare_is_a_noop_and_never_rewrites_bytes(self, tmp_path):
        layout = make_layout(tmp_path)
        first = portable_data.prepare_portable_data(layout, app_version="1.0.0", clock=fixed_clock)
        stored = portable_data.manifest_path(layout).read_bytes()

        second = portable_data.prepare_portable_data(layout, app_version="2.0.0", clock=fixed_clock)

        assert first.performed is True
        assert second.performed is False
        assert second.backup_dir is None
        assert portable_data.manifest_path(layout).read_bytes() == stored
        assert len(backup_directories(layout)) == 1

    def test_refuses_a_newer_schema_with_a_stable_code(self, tmp_path):
        layout = make_layout(tmp_path)
        path = write_manifest(layout, schema_version=portable_data.SCHEMA_VERSION + 1)
        original = path.read_bytes()

        with pytest.raises(portable_data.PortableDataError) as excinfo:
            portable_data.prepare_portable_data(layout, app_version="1.0.0", clock=fixed_clock)

        assert excinfo.value.code == "portable_data_schema_newer"
        assert path.read_bytes() == original
        assert backup_directories(layout) == []

    def test_corrupt_manifest_fails_closed_and_keeps_the_bytes(self, tmp_path):
        layout = make_layout(tmp_path)
        path = write_raw_manifest(layout, "{not-json")

        with pytest.raises(portable_data.PortableDataError) as excinfo:
            portable_data.prepare_portable_data(layout, app_version="1.0.0", clock=fixed_clock)

        assert excinfo.value.code == "portable_data_manifest_invalid"
        assert path.read_text(encoding="utf-8") == "{not-json"

    def test_unknown_manifest_field_fails_closed(self, tmp_path):
        layout = make_layout(tmp_path)
        payload = manifest_payload()
        payload["unexpected"] = 1
        write_raw_manifest(layout, json.dumps(payload))

        status = portable_data.detect_schema(layout)

        assert status.state == "invalid"

    def test_outdated_manifest_is_upgraded_with_a_backup_and_can_be_rolled_back(self, tmp_path):
        layout = make_layout(tmp_path)
        previous = write_raw_manifest(
            layout,
            json.dumps(manifest_payload(schema_version=0, applied_migrations=[])),
        )
        previous_bytes = previous.read_bytes()

        report = portable_data.prepare_portable_data(layout, app_version="1.0.0", clock=fixed_clock)

        assert report.performed is True
        assert report.from_version == 0
        assert report.backup_dir is not None
        backed_up = report.backup_dir / "files" / portable_data.MANIFEST_NAME
        assert backed_up.read_bytes() == previous_bytes
        assert json.loads(previous.read_text(encoding="utf-8"))["schema_version"] == portable_data.SCHEMA_VERSION

        rollback = portable_data.rollback_last_migration(layout)

        assert rollback.performed is True
        assert rollback.backup_dir == report.backup_dir
        assert previous.read_bytes() == previous_bytes
        assert portable_data.detect_schema(layout).state == "outdated"

    def test_rollback_of_a_fresh_adoption_restores_pre_versioned_state(self, tmp_path):
        layout = make_layout(tmp_path)
        portable_data.prepare_portable_data(layout, app_version="1.0.0", clock=fixed_clock)

        rollback = portable_data.rollback_last_migration(layout)

        assert rollback.performed is True
        assert rollback.removed_manifest is True
        assert not portable_data.manifest_path(layout).exists()
        assert portable_data.detect_schema(layout).state == "absent"

    def test_rollback_without_any_backup_is_a_stable_error(self, tmp_path):
        layout = make_layout(tmp_path)

        with pytest.raises(portable_data.PortableDataError) as excinfo:
            portable_data.rollback_last_migration(layout)

        assert excinfo.value.code == "portable_data_backup_missing"


class TestMigrationTransaction:
    def test_replace_file_backs_up_previous_bytes_and_commits_atomically(self, tmp_path):
        layout = make_layout(tmp_path)
        target = write_file(layout.data_root / "config" / "config.toml", b"previous")
        txn = portable_data.DataMigrationTxn(layout, from_version=0, to_version=1, app_version="1.0.0")

        txn.replace_file(target, b"replacement", label="测试文件")
        txn.commit()

        assert target.read_bytes() == b"replacement"
        assert (txn.backup_dir / "files" / "config" / "config.toml").read_bytes() == b"previous"
        state = json.loads((txn.backup_dir / "state.json").read_text(encoding="utf-8"))
        assert state["schema_version_to"] == 1
        assert state["entries"][0]["path"] == "config/config.toml"
        assert state["committed_at"]
        assert temp_leftovers(layout.data_root) == []

    def test_replaced_file_can_be_restored_from_the_backup(self, tmp_path):
        layout = make_layout(tmp_path)
        target = write_file(layout.data_root / "config" / "config.toml", b"previous")
        txn = portable_data.DataMigrationTxn(layout, from_version=0, to_version=1, app_version="1.0.0")
        txn.replace_file(target, b"replacement", label="测试文件")
        txn.commit()

        portable_data.restore_backup_directory(layout, txn.backup_dir)

        assert target.read_bytes() == b"previous"
        assert temp_leftovers(layout.data_root) == []

    def test_failed_atomic_replace_keeps_previous_bytes_and_no_temp_file(self, tmp_path, monkeypatch):
        layout = make_layout(tmp_path)
        target = write_file(layout.data_root / "config" / "config.toml", b"previous")
        txn = portable_data.DataMigrationTxn(layout, from_version=0, to_version=1, app_version="1.0.0")

        def fail_replace(src, dst) -> None:  # noqa: ANN001 - 模拟原子替换失败
            raise OSError("simulated replace failure")

        monkeypatch.setattr(portable_data.os, "replace", fail_replace)

        with pytest.raises(portable_data.PortableDataError) as excinfo:
            txn.replace_file(target, b"replacement", label="测试文件")

        assert excinfo.value.code == "portable_data_write_failed"
        assert target.read_bytes() == b"previous"
        assert temp_leftovers(layout.data_root) == []

    def test_backup_directories_are_unique_and_never_overwritten(self, tmp_path):
        layout = make_layout(tmp_path)
        first = portable_data.DataMigrationTxn(
            layout, from_version=0, to_version=1, app_version="1.0.0", clock=fixed_clock
        )
        first.replace_file(layout.data_root / "a.txt", b"a", label="a")
        first.commit()
        second = portable_data.DataMigrationTxn(
            layout, from_version=0, to_version=1, app_version="1.0.0", clock=fixed_clock
        )
        second.replace_file(layout.data_root / "b.txt", b"b", label="b")
        second.commit()

        assert first.backup_dir != second.backup_dir
        assert first.backup_dir.is_dir() and second.backup_dir.is_dir()
        assert (first.backup_dir / "state.json").is_file()

    def test_replace_file_refuses_targets_outside_the_data_root(self, tmp_path):
        layout = make_layout(tmp_path)
        external = tmp_path / "external.txt"
        txn = portable_data.DataMigrationTxn(layout, from_version=0, to_version=1, app_version="1.0.0")

        with pytest.raises(paths.PathStrategyError) as excinfo:
            txn.replace_file(external, b"nope", label="外部文件")

        assert excinfo.value.code == "path_outside_data_root"
        assert not external.exists()


class TestCleanupCategories:
    def _populate(self, layout: paths.RuntimeLayout) -> dict[str, Path]:
        return {
            "right_pdf": write_file(layout.data_root / "documents" / "hash1" / "right.pdf", b"x" * 100),
            "glossary": write_file(layout.data_root / "documents" / "hash1" / "user_glossary.csv", b"a,b\n"),
            "model": write_file(layout.data_root / "models" / "layout.onnx", b"m" * 50),
            "upstream": write_file(layout.data_root / "upstream-cache" / "babeldoc" / "font.ttf", b"u" * 10),
            "font": write_file(layout.data_root / "fonts" / "Noto.ttf", b"f" * 20),
            "log": write_file(layout.data_root / "logs" / "pdf_reader.log", b"l" * 5),
            "temp": write_file(layout.data_root / "temp" / "task.tmp", b"t" * 7),
        }

    def test_stats_report_size_and_consequences_per_category(self, tmp_path):
        layout = make_layout(tmp_path)
        files = self._populate(layout)

        stats = {item.key: item for item in portable_data.category_stats(layout)}

        assert [item.key for item in portable_data.category_stats(layout)] == [
            "documents",
            "models",
            "fonts",
            "logs",
            "temp",
        ]
        assert stats["documents"].bytes == 100 + len(b"a,b\n")
        assert stats["documents"].file_count == 2
        assert stats["documents"].consequence
        assert "重新翻译" in stats["documents"].consequence
        assert stats["models"].bytes == 50 + 10
        assert "重新下载" in stats["models"].consequence
        assert stats["fonts"].bytes == 20
        assert stats["logs"].bytes == 5
        assert stats["temp"].bytes == 7
        assert stats["documents"].regenerable is False
        assert stats["models"].regenerable is True
        assert files["right_pdf"].is_file()

    def test_dry_run_reports_without_deleting_anything(self, tmp_path):
        layout = make_layout(tmp_path)
        files = self._populate(layout)

        reports = portable_data.run_cleanup(layout, ["documents"], dry_run=True)

        assert len(reports) == 1
        assert reports[0].dry_run is True
        assert reports[0].removed == (files["right_pdf"].parent,)
        assert reports[0].bytes_reclaimed == 100 + len(b"a,b\n")
        assert files["right_pdf"].is_file()
        assert files["glossary"].is_file()

    def test_cleanup_deletes_only_the_selected_category(self, tmp_path):
        layout = make_layout(tmp_path)
        files = self._populate(layout)

        reports = portable_data.run_cleanup(layout, ["temp"], dry_run=False)

        assert reports[0].removed == (files["temp"],)
        assert not files["temp"].exists()
        assert files["right_pdf"].is_file()
        assert files["model"].is_file()
        assert files["font"].is_file()
        assert files["log"].is_file()

    def test_cleanup_never_deletes_user_pdfs_outside_the_data_root(self, tmp_path):
        layout = make_layout(tmp_path)
        files = self._populate(layout)
        external_pdf = write_file(tmp_path / "library" / "book.pdf", b"%PDF-1.4 original user document")

        portable_data.run_cleanup(layout, ["documents"], dry_run=False)

        assert not files["right_pdf"].exists()
        assert external_pdf.read_bytes() == b"%PDF-1.4 original user document"

    def test_cleanup_removes_a_symlinked_child_without_following_it(self, tmp_path):
        layout = make_layout(tmp_path)
        external_dir = tmp_path / "outside"
        important = write_file(external_dir / "important.pdf", b"keep me")
        link = layout.data_root / "documents" / "linked"
        link.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.symlink(external_dir, link)
        except (OSError, NotImplementedError):  # pragma: no cover - 平台不支持符号链接
            pytest.skip("平台不允许创建符号链接")

        reports = portable_data.run_cleanup(layout, ["documents"], dry_run=False)

        assert reports[0].removed == (link,)
        assert not link.exists()
        assert important.read_bytes() == b"keep me"
        assert external_dir.is_dir()

    def test_cleanup_refuses_a_linked_category_root(self, tmp_path):
        layout = make_layout(tmp_path)
        external_dir = tmp_path / "outside"
        important = write_file(external_dir / "important.pdf", b"keep me")
        documents = layout.data_root / "documents"
        if documents.exists():
            documents.rmdir()
        try:
            os.symlink(external_dir, documents)
        except (OSError, NotImplementedError):  # pragma: no cover - 平台不支持符号链接
            pytest.skip("平台不允许创建符号链接")

        with pytest.raises(portable_data.PortableDataError) as excinfo:
            portable_data.run_cleanup(layout, ["documents"], dry_run=False)

        assert excinfo.value.code == "portable_data_cleanup_root_is_link"
        assert important.read_bytes() == b"keep me"

    def test_cleanup_requires_an_explicit_category(self, tmp_path):
        layout = make_layout(tmp_path)
        self._populate(layout)

        with pytest.raises(portable_data.PortableDataError) as excinfo:
            portable_data.run_cleanup(layout, [], dry_run=False)

        assert excinfo.value.code == "portable_data_cleanup_category_required"

    def test_unknown_category_is_rejected(self, tmp_path):
        layout = make_layout(tmp_path)

        with pytest.raises(portable_data.PortableDataError) as excinfo:
            portable_data.run_cleanup(layout, ["everything"], dry_run=True)

        assert excinfo.value.code == "portable_data_cleanup_category_unknown"

    def test_cleanup_refuses_while_an_instance_record_exists(self, tmp_path):
        layout = make_layout(tmp_path)
        files = self._populate(layout)
        write_file(layout.runtime_dir / "instance.json", b"{}")

        with pytest.raises(portable_data.PortableDataError) as excinfo:
            portable_data.run_cleanup(layout, ["documents"], dry_run=False)

        assert excinfo.value.code == "portable_instance_running"
        assert files["right_pdf"].is_file()

    def test_cleanup_never_touches_config_glossary_runtime_or_manifest(self, tmp_path):
        layout = make_layout(tmp_path)
        self._populate(layout)
        config = write_file(layout.data_root / "config" / "config.toml", b"[model]\n")
        glossary = write_file(layout.data_root / "glossary" / "glossary.csv", b"a,b\n")
        instance = write_file(layout.data_root / "runtime" / "other.json", b"{}\n")
        portable_data.prepare_portable_data(layout, app_version="1.0.0", clock=fixed_clock)

        for key in ("documents", "models", "fonts", "logs", "temp"):
            portable_data.run_cleanup(layout, [key], dry_run=False)

        assert config.read_bytes() == b"[model]\n"
        assert glossary.read_bytes() == b"a,b\n"
        assert instance.read_bytes() == b"{}\n"
        assert portable_data.manifest_path(layout).is_file()
        assert portable_data.detect_schema(layout).state == "current"


class TestControlledImport:
    def _source_data(self, tmp_path: Path) -> paths.RuntimeLayout:
        source = h.make_portable_layout(tmp_path / "old", name="旧安装")
        write_file(source.data_root / "models" / "layout.onnx", b"model-bytes")
        write_file(source.data_root / "upstream-cache" / "babeldoc" / "cache.db", b"upstream")
        write_file(source.data_root / "documents" / "hash" / "right.pdf", b"%PDF-1.4 cached")
        write_file(source.data_root / "fonts" / "Noto.ttf", b"font")
        write_file(source.data_root / "glossary" / "glossary.csv", b"a,b\n")
        write_file(source.data_root / "config" / "config.toml", b"from-old-install")
        return source

    def test_dry_run_reports_the_import_without_touching_the_target(self, tmp_path):
        target = make_layout(tmp_path / "new")
        source = self._source_data(tmp_path)

        report = portable_data.import_portable_data(target, source.data_root, dry_run=True)

        assert report.dry_run is True
        assert "models/layout.onnx" in report.copied
        assert not (target.data_root / "models" / "layout.onnx").exists()
        # config 永不导入，因此不计入字节数，但必须出现在跳过原因里。
        assert report.bytes_copied == sum(
            len(payload) for payload in (b"model-bytes", b"upstream", b"%PDF-1.4 cached", b"font", b"a,b\n")
        )
        assert dict(report.skipped) == {"config/config.toml": "existing-config-preserved"}

    def test_import_copies_models_and_documents_but_never_overwrites_config(self, tmp_path):
        target = make_layout(tmp_path / "new")
        target_config = write_file(target.data_root / "config" / "config.toml", b"keep-me")
        source = self._source_data(tmp_path)

        report = portable_data.import_portable_data(target, source.data_root, dry_run=False)

        assert (target.data_root / "models" / "layout.onnx").read_bytes() == b"model-bytes"
        assert (target.data_root / "upstream-cache" / "babeldoc" / "cache.db").read_bytes() == b"upstream"
        assert (target.data_root / "documents" / "hash" / "right.pdf").read_bytes() == b"%PDF-1.4 cached"
        assert target_config.read_bytes() == b"keep-me"
        assert dict(report.skipped) == {"config/config.toml": "existing-config-preserved"}
        assert temp_leftovers(target.data_root) == []

    def test_import_skips_existing_files_unless_overwrite_is_requested(self, tmp_path):
        target = make_layout(tmp_path / "new")
        existing = write_file(target.data_root / "models" / "layout.onnx", b"already-here")
        source = self._source_data(tmp_path)

        report = portable_data.import_portable_data(target, source.data_root, dry_run=False)

        assert existing.read_bytes() == b"already-here"
        assert dict(report.skipped)["models/layout.onnx"] == "already-exists"

        replaced = portable_data.import_portable_data(target, source.data_root, dry_run=False, overwrite=True)

        assert existing.read_bytes() == b"model-bytes"
        assert "models/layout.onnx" in replaced.copied
        assert all(not path.name.endswith(portable_data.TEMP_SUFFIX) for path in target.data_root.rglob("*"))

    def test_import_rejects_a_source_inside_the_data_root_or_containing_it(self, tmp_path):
        target = make_layout(tmp_path / "new")

        with pytest.raises(portable_data.PortableDataError) as inside:
            portable_data.import_portable_data(target, target.data_root / "documents", dry_run=True)
        assert inside.value.code == "portable_data_import_source_unsafe"

        with pytest.raises(portable_data.PortableDataError) as containing:
            portable_data.import_portable_data(target, target.portable_root, dry_run=True)
        assert containing.value.code == "portable_data_import_source_unsafe"

    def test_import_refuses_a_missing_or_linked_source(self, tmp_path):
        target = make_layout(tmp_path / "new")

        with pytest.raises(portable_data.PortableDataError) as missing:
            portable_data.import_portable_data(target, tmp_path / "nope", dry_run=True)
        assert missing.value.code == "portable_data_import_source_missing"

        real = tmp_path / "real-data"
        real.mkdir()
        link = tmp_path / "linked-data"
        try:
            os.symlink(real, link)
        except (OSError, NotImplementedError):  # pragma: no cover - 平台不支持符号链接
            pytest.skip("平台不允许创建符号链接")
        with pytest.raises(portable_data.PortableDataError) as linked:
            portable_data.import_portable_data(target, link, dry_run=True)
        assert linked.value.code == "portable_data_import_source_unsafe"

    def test_import_skips_linked_entries_inside_the_source(self, tmp_path):
        target = make_layout(tmp_path / "new")
        source = self._source_data(tmp_path)
        external_file = write_file(tmp_path / "outside" / "secret.pdf", b"never copy")
        link = source.data_root / "documents" / "linked.pdf"
        try:
            os.symlink(external_file, link)
        except (OSError, NotImplementedError):  # pragma: no cover - 平台不支持符号链接
            pytest.skip("平台不允许创建符号链接")

        report = portable_data.import_portable_data(target, source.data_root, dry_run=False)

        assert "documents/linked.pdf" not in report.copied
        assert dict(report.skipped)["documents/linked.pdf"] == "source-entry-is-link"
        assert not (target.data_root / "documents" / "linked.pdf").exists()
        assert external_file.read_bytes() == b"never copy"
