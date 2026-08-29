#!/usr/bin/env python3
"""高可信密钥扫描器（gitleaks 的等价轻量实现，Windows/Python 可复现）。

只扫描 Git 跟踪内容（``git ls-files``），绝不读取或输出未跟踪的本地
``config.toml`` / ``.env`` / 用户 PDF，也绝不打印匹配到的 secret 值。
已知的占位示例值（``sk-your-api-key-here``、``AIza...`` 等）会被放行，
契约测试见 ``tests/test_secret_scan.py``。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

PLACEHOLDER_TOKENS = (
    "your",
    "example",
    "placeholder",
    "xxx",
    "demo",
    "dummy",
    "test",
    "redacted",
    "replace",
    "todo",
    "…",
    "<",
    ">",
    "此处",
    "密钥",
)


def _rule(name: str, pattern: str, flags: int = re.IGNORECASE) -> tuple[str, re.Pattern[str]]:
    return name, re.compile(pattern, flags)


RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    _rule("OPENAI_DEEPSEEK_API_KEY", r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    _rule("ANTHROPIC_API_KEY", r"\bsk-ant-[A-Za-z0-9_-]{20,}\b"),
    _rule("GOOGLE_API_KEY", r"\bAIza[0-9A-Za-z_-]{35}\b"),
    _rule("AWS_ACCESS_KEY_ID", r"\bAKIA[0-9A-Z]{16}\b"),
    _rule("GITHUB_TOKEN", r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    _rule("GITHUB_PAT", r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    _rule("SLACK_TOKEN", r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    _rule("STRIPE_SECRET_KEY", r"\b(?:sk|rk)_live_[0-9A-Za-z]{16,}\b"),
    _rule(
        "PRIVATE_KEY_BLOCK",
        r"-----BEGIN (?:RSA|DSA|EC|OPENSSH|PGP|ENCRYPTED) PRIVATE KEY-----",
        flags=0,
    ),
    _rule("BEARER_TOKEN", r"\bbearer\s+[A-Za-z0-9._~+/=-]{20,}"),
    _rule(
        "API_KEY_ASSIGNMENT",
        r"\b(?:api[_-]?key|apikey|secret|access[_-]?token)\b\s*[:=]\s*['\"]?[A-Za-z0-9_./+=-]{24,}",
    ),
)


def _is_placeholder(value: str) -> bool:
    lowered = value.lower()
    return any(token in lowered for token in PLACEHOLDER_TOKENS)


def _tracked_files(repo_root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=repo_root,
        capture_output=True,
        text=False,
        check=True,
    )
    names = result.stdout.split(b"\0")
    files: list[Path] = []
    for raw in names:
        if not raw:
            continue
        path = (repo_root / os_path_from_bytes(raw)).resolve()
        # 只处理实际存在的文件；符号链接/子模块条目保守跳过。
        if path.is_file() and repo_root.resolve() in path.parents:
            files.append(path)
    return files


def os_path_from_bytes(raw: bytes) -> str:
    # git ls-files -z 在 Windows 返回仓库相对路径（正斜杠），Path 可直接消费。
    return raw.decode("utf-8", errors="surrogateescape")


def _scan_file(path: Path, repo_root: Path) -> list[tuple[str, int, str]]:
    try:
        data = path.read_bytes()
    except OSError:
        return []
    if b"\x00" in data[:8192]:
        return []  # 二进制文件（含 PDF）不做文本密钥扫描
    text = data.decode("utf-8", errors="replace")
    findings: list[tuple[str, int, str]] = []
    for rule_name, pattern in RULES:
        for match in pattern.finditer(text):
            value = match.group(0).strip()
            if _is_placeholder(value):
                continue
            line = text.count("\n", 0, match.start()) + 1
            rel = path.relative_to(repo_root).as_posix()
            findings.append((rel, line, rule_name))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan Git-tracked content for high-confidence secrets.")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Git 仓库根目录（默认本脚本上级目录）。",
    )
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()

    try:
        files = _tracked_files(repo_root)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"SECRET_SCAN: 无法枚举 Git 跟踪文件（{exc}）；请确认在 Git 仓库内运行。", file=sys.stderr)
        return 2

    findings: list[tuple[str, int, str]] = []
    for path in files:
        findings.extend(_scan_file(path, repo_root))

    if not findings:
        print(f"Secret scan OK: scanned {len(files)} tracked files, no high-confidence secrets found.")
        return 0

    print("Secret scan FAILED: high-confidence secret-like content in tracked files:", file=sys.stderr)
    for rel, line, rule in sorted(findings):
        print(f"  {rel}:{line}: {rule} (value redacted)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
