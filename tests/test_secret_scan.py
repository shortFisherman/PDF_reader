"""P3-07 密钥扫描契约：只扫 Git 跟踪内容、高可信规则、误报放行、绝不泄漏值。"""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCANNER = REPO_ROOT / "scripts" / "secret_scan.py"

SECRET = "sk-" + "A" * 40
PRIVATE_KEY_BLOCK = "-----BEGIN RSA " + "PRIVATE KEY-----\nMIIEowIBAAKCAQEA\n-----END RSA " + "PRIVATE KEY-----"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )


def _make_repo(tmp_path: Path, files: dict[str, str | bytes]) -> Path:
    repo = tmp_path / "scan-repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test")
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
        _git(repo, "add", "--", name)
    _git(repo, "commit", "-q", "-m", "fixture")
    return repo


def _run_scanner(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCANNER), "--repo-root", str(repo)],
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_tracked_api_key_found_and_value_never_printed(tmp_path):
    repo = _make_repo(tmp_path, {"config.example.toml": f'api_key = "{SECRET}"\n'})
    result = _run_scanner(repo)

    assert result.returncode == 1
    assert "config.example.toml:1" in result.stderr
    assert "value redacted" in result.stderr
    assert SECRET not in result.stdout + result.stderr


def test_tracked_private_key_block_found(tmp_path):
    repo = _make_repo(tmp_path, {"keys/id_rsa": PRIVATE_KEY_BLOCK + "\n"})
    result = _run_scanner(repo)

    assert result.returncode == 1
    assert "PRIVATE_KEY_BLOCK" in result.stderr


def test_generic_api_key_assignment_found(tmp_path):
    key_name = "API" + "_KEY"
    value = "0123456789abcdef0123456789abcdef"
    repo = _make_repo(tmp_path, {"app.conf": f'{key_name}="{value}"\n'})
    result = _run_scanner(repo)

    assert result.returncode == 1
    assert "API_KEY_ASSIGNMENT" in result.stderr


def test_documented_placeholders_allowed(tmp_path):
    content = (
        'api_key = "sk-your-api-key-here"\n'
        '# api_key = "sk-..."\n'
        '# api_key = "AIza..."\n'
        '# PowerShell: $env:MODEL_API_KEY = "sk-你的密钥"\n'
        "token = Bearer <redacted>\n"
    )
    repo = _make_repo(tmp_path, {"config.example.toml": content})
    result = _run_scanner(repo)

    assert result.returncode == 0, result.stderr
    assert "no high-confidence secrets found" in result.stdout


def test_untracked_config_toml_with_secret_is_not_scanned(tmp_path):
    repo = _make_repo(tmp_path, {"README.md": "tracked content\n"})
    (repo / "config.toml").write_text(f'api_key = "{SECRET}"\n', encoding="utf-8")

    result = _run_scanner(repo)

    assert result.returncode == 0, result.stderr
    assert SECRET not in result.stdout + result.stderr
    assert "config.toml" not in result.stdout + result.stderr


def test_binary_tracked_file_skipped(tmp_path):
    blob = b"\x00\x01\x02" + SECRET.encode("ascii")
    repo = _make_repo(tmp_path, {"docs/sample.pdf": blob})
    result = _run_scanner(repo)

    assert result.returncode == 0, result.stderr


def test_repo_root_missing_git_fails_cleanly(tmp_path):
    bare = tmp_path / "not-a-repo"
    bare.mkdir()
    result = subprocess.run(
        [sys.executable, str(SCANNER), "--repo-root", str(bare)],
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 2
    assert "SECRET_SCAN:" in result.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="verify.ps1 is Windows/PowerShell-only")
def test_secret_scan_is_part_of_verify_and_ci():
    # 密钥扫描步骤由公共编排 scripts/verify.py 承担；verify.ps1 委托 verify.py。
    verify_py = (REPO_ROOT / "scripts" / "verify.py").read_text(encoding="utf-8")
    verify_ps1 = (REPO_ROOT / "scripts" / "verify.ps1").read_text(encoding="utf-8")
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "secret_scan.py" in verify_py
    assert "scripts/verify.py" in verify_ps1
    assert "scripts/verify.ps1" in ci
