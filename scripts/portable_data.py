#!/usr/bin/env python3
"""便携数据治理 CLI（P1-03）：状态/统计、分类清理、受控导入与迁移回滚。

用法：
    python scripts/portable_data.py status [--portable-root PATH]
    python scripts/portable_data.py clean --category temp [--category logs] [--yes]
    python scripts/portable_data.py clean --all [--yes]
    python scripts/portable_data.py import --from OLD_DATA_DIR [--yes] [--overwrite]
    python scripts/portable_data.py rollback [--backup DIR] --yes

安全语义：
- ``status`` 只读；``clean`` 与 ``import`` 默认 dry-run，只有显式 ``--yes`` 才写入或删除。
- 清理必须显式给出 ``--category`` 或 ``--all``；删除范围严格限制在规范化 data root 的直接
  子项，分类根是链接时整体拒绝，子项是链接时只删除链接本身，绝不递归删除 data 之外的
  用户 PDF。
- ``import`` 只复制非易变数据，``config/``、``logs/``、``temp/``、``runtime/`` 与迁移备份
  永不导入；需要沿用旧配置时手动复制 ``config/config.toml``。
- ``rollback`` 必须显式 ``--yes``，回滚最近一次已提交迁移（或 ``--backup`` 指定的备份）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pdf_reader import paths, portable_data

PRODUCT_LAUNCHER = "PDF Reader.exe"


def _layout_from_args(args: argparse.Namespace) -> paths.RuntimeLayout:
    if args.portable_root is not None:
        root = Path(args.portable_root).expanduser()
        return paths.RuntimeLayout.portable_from_executable(root / PRODUCT_LAUNCHER)
    if getattr(sys, "frozen", False):
        return paths.RuntimeLayout.portable_from_executable(sys.executable)
    return paths.RuntimeLayout.development()


def _command_status(layout: paths.RuntimeLayout) -> int:
    print(portable_data.render_data_report(layout))
    return 0


def _command_clean(layout: paths.RuntimeLayout, args: argparse.Namespace) -> int:
    if args.all_categories:
        categories = [spec.key for spec in portable_data.CATEGORY_SPECS]
    else:
        categories = list(args.category or ())
    reports = portable_data.run_cleanup(layout, categories, dry_run=not args.yes)
    print(portable_data.render_cleanup_report(reports))
    return 0


def _command_import(layout: paths.RuntimeLayout, args: argparse.Namespace) -> int:
    report = portable_data.import_portable_data(
        layout,
        args.source,
        dry_run=not args.yes,
        overwrite=args.overwrite,
    )
    print(portable_data.render_import_report(report))
    return 0


def _command_rollback(layout: paths.RuntimeLayout, args: argparse.Namespace) -> int:
    if not args.yes:
        print(
            "ERROR [portable_data_rollback_requires_confirmation]: 回滚会覆盖当前 data 文件，必须显式加 --yes",
            file=sys.stderr,
        )
        return 2
    if args.backup is None:
        report = portable_data.rollback_last_migration(layout)
    else:
        backup_dir = Path(args.backup).expanduser()
        removed_manifest = portable_data.restore_backup_directory(layout, backup_dir)
        report = portable_data.RollbackReport(performed=True, backup_dir=backup_dir, removed_manifest=removed_manifest)
    if report.performed:
        print(f"已回滚：{report.backup_dir}（恢复旧数据文件，移除清单={report.removed_manifest}）")
    else:
        print(f"无需回滚：{report.backup_dir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PDF Reader 便携数据治理（状态、清理、导入、回滚）")
    parser.add_argument(
        "--portable-root",
        type=Path,
        help="便携根目录（含 PDF Reader.exe）；默认按冻结态或开发态解析",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="显示数据格式版本与各分类大小/删除后果（只读）")

    clean = sub.add_parser("clean", help="分类清理 data 内的文档缓存/模型/字体/日志/临时文件")
    clean.add_argument(
        "--category",
        action="append",
        choices=[spec.key for spec in portable_data.CATEGORY_SPECS],
        help="可重复；省略时必须加 --all",
    )
    clean.add_argument("--all", dest="all_categories", action="store_true", help="选择全部五个分类")
    clean.add_argument("--yes", action="store_true", help="真正删除；不加则只预览")

    importer = sub.add_parser("import", help="从旧安装的 data 受控导入数据（默认预览）")
    importer.add_argument("--from", dest="source", required=True, type=Path, help="旧安装的 data 目录")
    importer.add_argument("--yes", action="store_true", help="真正复制；不加则只预览")
    importer.add_argument("--overwrite", action="store_true", help="覆盖目标已有的同名数据文件")

    rollback = sub.add_parser("rollback", help="回滚最近一次已提交的数据迁移")
    rollback.add_argument("--backup", type=Path, help="回滚指定备份目录而不是最近一次")
    rollback.add_argument("--yes", action="store_true", help="确认回滚（必需）")

    args = parser.parse_args(argv)
    try:
        layout = _layout_from_args(args)
        if args.command == "status":
            return _command_status(layout)
        if args.command == "clean":
            return _command_clean(layout, args)
        if args.command == "import":
            return _command_import(layout, args)
        return _command_rollback(layout, args)
    except portable_data.PortableDataError as exc:
        print(f"ERROR [{exc.code}]: {exc}", file=sys.stderr)
        return 1
    except paths.PathStrategyError as exc:
        print(f"ERROR [{exc.code}]: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
