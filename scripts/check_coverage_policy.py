"""P2-03 coverage 策略检查：读取 coverage.json 并强制全局与关键模块阈值。

阈值来自实测 baseline 并保留维护余量；低于阈值时以非零退出，使统一验证入口失败。
"""

import json
import sys
from pathlib import Path

GLOBAL_LINE_FLOOR = 90.0
GLOBAL_BRANCH_FLOOR = 80.0

MODULE_FLOORS = {
    "state.py": (80.0, 75.0),
    "translation_coordinator.py": (95.0, 95.0),
    "translation_lifecycle.py": (95.0, 95.0),
    "sse_stream.py": (85.0, 75.0),
    "routes.py": (85.0, 70.0),
}


def _percent(covered: int, total: int) -> float:
    if total == 0:
        return 100.0
    return 100.0 * covered / total


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: check_coverage_policy.py <coverage.json>", file=sys.stderr)
        return 2
    data = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    totals = data["totals"]
    line_pct = _percent(totals["covered_lines"], totals["num_statements"])
    branch_pct = _percent(totals["covered_branches"], totals["num_branches"])

    failures: list[str] = []
    if line_pct < GLOBAL_LINE_FLOOR:
        failures.append(f"global line {line_pct:.1f}% < {GLOBAL_LINE_FLOOR:.1f}%")
    if branch_pct < GLOBAL_BRANCH_FLOOR:
        failures.append(f"global branch {branch_pct:.1f}% < {GLOBAL_BRANCH_FLOOR:.1f}%")

    for module, (line_floor, branch_floor) in MODULE_FLOORS.items():
        matches = [path for path in data["files"] if path.replace("\\", "/").endswith(f"/{module}")]
        if not matches:
            failures.append(f"{module}: not measured")
            continue
        summary = data["files"][matches[0]]["summary"]
        module_line = _percent(summary["covered_lines"], summary["num_statements"])
        module_branch = _percent(summary["covered_branches"], summary["num_branches"])
        if module_line < line_floor:
            failures.append(f"{module} line {module_line:.1f}% < {line_floor:.1f}%")
        if module_branch < branch_floor:
            failures.append(f"{module} branch {module_branch:.1f}% < {branch_floor:.1f}%")

    if failures:
        print("COVERAGE POLICY FAILED:", file=sys.stderr)
        for failure in failures:
            print(f" - {failure}", file=sys.stderr)
        return 1
    print(f"Coverage policy OK: global line={line_pct:.1f}% branch={branch_pct:.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
