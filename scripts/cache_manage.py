#!/usr/bin/env python3
"""缓存只读统计与孤儿翻译临时工作区清理 CLI（P3-05）。

用法：
    python scripts/cache_manage.py stats [--cache-dir PATH] [--json]
    python scripts/cache_manage.py orphans [--cache-dir PATH]
    python scripts/cache_manage.py clean [--cache-dir PATH] [--yes]

安全语义：
- 只读统计永不删除任何内容；``clean`` 默认 dry-run，只有显式 ``--yes`` 才删除。
- 删除范围严格限制为 cache_dir 直接子目录中带固定前缀且含有效标记的翻译临时
  工作区；``right.pdf``、术语表、阅读进度与未知/无标记目录一律保留。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pdf_reader import cache_ops, config


def _cache_dir_from_args(args: argparse.Namespace) -> Path:
    if args.cache_dir:
        return Path(args.cache_dir).expanduser().resolve()
    return config.CACHE_DIR.resolve()


def _print_stats(cache_dir: Path, as_json: bool) -> int:
    result = cache_ops.stats(cache_dir)
    docs = [
        {
            "hash": item.hash_dir.name,
            "right_pdf_bytes": item.right_pdf_bytes,
            "cumulative_glossary_bytes": item.glossary_bytes,
            "reading_progress_present": item.reading_progress_present,
            "debug_trace_bytes": item.debug_trace_bytes,
        }
        for item in result.documents
    ]
    payload = {
        "cache_dir": str(cache_dir),
        "document_count": len(result.documents),
        "documents": docs,
        "temp_workspaces": [str(p) for p in result.temp_workspaces],
        "temp_workspace_count": len(result.temp_workspaces),
        "temp_workspace_bytes": result.temp_workspace_bytes,
    }
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print(f"cache_dir: {cache_dir}")
    print(f"documents: {len(result.documents)}")
    for item in result.documents:
        print(
            f"  {item.hash_dir.name}: right.pdf={item.right_pdf_bytes}B "
            f"glossary={item.glossary_bytes}B progress={item.reading_progress_present} "
            f"debug_trace={item.debug_trace_bytes}B"
        )
    print(f"temp workspaces: {len(result.temp_workspaces)} ({result.temp_workspace_bytes}B)")
    for path in result.temp_workspaces:
        print(f"  {path}")
    return 0


def _print_orphans(cache_dir: Path) -> int:
    workspaces = cache_ops.list_temp_workspaces(cache_dir)
    if not workspaces:
        print(f"no translation temp workspaces under {cache_dir}")
        return 0
    for item in workspaces:
        status = "marked" if item.marked else "unknown/unmarked"
        age = f"{item.marker_age_seconds:.0f}s" if item.marker_age_seconds is not None else "unknown-age"
        pid = item.marker_pid if item.marker_pid is not None else "no-pid"
        print(f"{item.path} [{status} pid={pid} age={age}]")
    return 0


def _clean(cache_dir: Path, yes: bool) -> int:
    report = cache_ops.cleanup_orphan_temp_workspaces(cache_dir, dry_run=not yes)
    mode = "dry-run" if report.dry_run else "removed"
    print(
        f"cleanup {mode}: scanned={report.scanned} removed={len(report.removed)} "
        f"kept_unknown={len(report.kept_unknown)} kept_live_pid={len(report.kept_live_pid)} "
        f"kept_recent={len(report.kept_recent)} errors={len(report.errors)}"
    )
    for path in report.removed:
        print(f"  {path}")
    for path in report.kept_unknown:
        print(f"  kept (unknown/unmarked): {path}")
    for path in report.kept_live_pid:
        print(f"  kept (live pid): {path}")
    for path in report.kept_recent:
        print(f"  kept (too recent): {path}")
    for error in report.errors:
        print(f"  ERROR: {error}", file=sys.stderr)
    if report.errors:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PDF Reader 缓存统计与孤儿临时工作区清理")
    sub = parser.add_subparsers(dest="command", required=True)

    stats_parser = sub.add_parser("stats", help="只读缓存统计")
    stats_parser.add_argument("--cache-dir", type=str, default=None, help="缓存根目录（默认 DATA_ROOT/cache）")
    stats_parser.add_argument("--json", action="store_true", help="输出 JSON")

    orphans_parser = sub.add_parser("orphans", help="列出可识别的翻译临时工作区")
    orphans_parser.add_argument("--cache-dir", type=str, default=None)

    clean_parser = sub.add_parser("clean", help="清理孤儿翻译临时工作区（默认 dry-run）")
    clean_parser.add_argument("--cache-dir", type=str, default=None)
    clean_parser.add_argument("--yes", action="store_true", help="真正删除（默认只预览）")

    args = parser.parse_args(argv)
    cache_dir = _cache_dir_from_args(args)
    if args.command == "stats":
        return _print_stats(cache_dir, args.json)
    if args.command == "orphans":
        return _print_orphans(cache_dir)
    if args.command == "clean":
        return _clean(cache_dir, args.yes)
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
