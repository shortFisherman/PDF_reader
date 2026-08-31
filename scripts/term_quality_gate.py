"""P2-01 离线术语质量门（稳定独立命令）。

用法：
    python scripts/term_quality_gate.py [--fixture PATH] [--baseline PATH]
        [--update-baseline] [--json] [--no-baseline] [--tolerance FLOAT]

- 评测完全离线：不联网、不需要 API Key、不写真实 cache/docs 用户数据；
- 报告是确定性 JSON；阈值或基线漂移失败时以非零退出；
- ``--update-baseline`` 只在当前报告通过硬阈值时原子写入版本化基线。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pdf_reader.term_quality import (
    DRIFT_TOLERANCE,
    TermQualityError,
    compare_baseline,
    evaluate_quality,
    load_baseline,
    write_baseline,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "term_quality" / "fixture.json"
DEFAULT_BASELINE = REPO_ROOT / "docs" / "reports" / "term-quality-baseline.json"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="离线术语黄金样本质量门")
    parser.add_argument(
        "--fixture",
        type=str,
        default=str(DEFAULT_FIXTURE),
        help="黄金样本 fixture JSON 路径",
    )
    parser.add_argument(
        "--baseline",
        type=str,
        default=None,
        help="版本化基线 JSON 路径（默认 docs/reports/term-quality-baseline.json）",
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="当前报告通过硬阈值后原子更新基线",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="输出机器可读 JSON",
    )
    parser.add_argument(
        "--no-baseline",
        action="store_true",
        help="跳过基线漂移对比",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=DRIFT_TOLERANCE,
        help="基线漂移容忍度（默认 0.05）",
    )
    return parser


def _print_human(
    report: Any,
    deltas: dict[str, float | bool],
    failures: Sequence[str],
) -> None:
    print("== Term quality report ==")
    print(f"fixture: {report.fixture}")
    for key in sorted(report.metrics):
        value = report.metrics[key]
        threshold = report.thresholds[key]
        delta = deltas.get(key)
        delta_text = ""
        if isinstance(delta, (int, float)) and not isinstance(delta, bool):
            delta_text = f" (delta {delta:+.6f})"
        print(f"  {key}: {value!r} (threshold {threshold!r}){delta_text}")
    if failures:
        print("Term quality gate FAILED:")
        for failure in failures:
            print(f"  - {failure}")
    else:
        print("Term quality gate PASSED")


def _print_json(
    report: Any,
    baseline_path: Path | None,
    deltas: dict[str, float | bool],
    failures: Sequence[str],
    passed: bool,
) -> None:
    payload = {
        "tool": "term-quality-gate",
        "report": json.loads(report.to_json()),
        "baseline": {
            "path": str(baseline_path) if baseline_path is not None else None,
            "deltas": deltas,
        },
        "passed": passed,
        "failures": list(failures),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if isinstance(args.tolerance, bool) or not math.isfinite(args.tolerance) or args.tolerance < 0:
        print(
            "term quality error: --tolerance must be a finite number >= 0",
            file=sys.stderr,
        )
        return 2
    fixture_path = Path(args.fixture)
    if not fixture_path.is_file():
        print(f"term quality error: fixture not found: {fixture_path}", file=sys.stderr)
        return 2
    try:
        with tempfile.TemporaryDirectory(prefix="pdf-reader-term-quality-") as tmp:
            report = evaluate_quality(fixture_path, work_dir=Path(tmp))
    except TermQualityError as exc:
        print(f"term quality error: {exc}", file=sys.stderr)
        return 2

    threshold_failures = list(report.failures)
    baseline_path: Path | None = None
    deltas: dict[str, float | bool] = {}
    drift_failures: list[str] = []
    try:
        if args.update_baseline:
            if threshold_failures:
                print(
                    "term quality error: refusing to update baseline while thresholds fail",
                    file=sys.stderr,
                )
                return 1
            target = Path(args.baseline) if args.baseline else DEFAULT_BASELINE
            write_baseline(report, target)
            baseline_path = target
            baseline = load_baseline(target)
            deltas, drift_failures = compare_baseline(
                report.metrics,
                baseline["metrics"],
                tolerance=args.tolerance,
            )
            if baseline["fixture_sha256"] != report.fixture_sha256:
                drift_failures.append("fixture_sha256 mismatch with baseline")
        elif not args.no_baseline:
            candidate = (
                Path(args.baseline) if args.baseline else (DEFAULT_BASELINE if DEFAULT_BASELINE.is_file() else None)
            )
            if candidate is None:
                raise TermQualityError("baseline not found; use --update-baseline first")
            baseline_path = candidate
            baseline = load_baseline(candidate)
            deltas, drift_failures = compare_baseline(
                report.metrics,
                baseline["metrics"],
                tolerance=args.tolerance,
            )
            if baseline["fixture_sha256"] != report.fixture_sha256:
                drift_failures.append("fixture_sha256 mismatch with baseline")
    except TermQualityError as exc:
        print(f"term quality error: {exc}", file=sys.stderr)
        return 2

    failures = [*threshold_failures, *drift_failures]
    passed = not failures
    if args.json_output:
        _print_json(report, baseline_path, deltas, failures, passed)
    else:
        _print_human(report, deltas, failures)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
