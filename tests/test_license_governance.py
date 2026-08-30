"""P3-04 许可证与包元数据契约的离线回归测试。"""

import hashlib
import importlib.metadata as md
import json
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

SPDX = "AGPL-3.0-only"
UPSTREAM_SPDX = "AGPL-3.0"
VERIFY_DATE = "2026-08-30"
GNU_AGPLV3_SHA256 = "0d96a4ff68ad6d4b6f1f30f713b18d5184912ba8dd389f86aa7710db079abcb0"
UPSTREAM_VERSIONS = {"pdf2zh-next": "2.9.0", "babeldoc": "0.6.2"}


def _pyproject() -> dict:
    with open(REPO_ROOT / "pyproject.toml", "rb") as f:
        return tomllib.load(f)


def _package_json() -> dict:
    return json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))


def _package_lock() -> dict:
    return json.loads((REPO_ROOT / "package-lock.json").read_text(encoding="utf-8"))


def test_root_license_is_full_official_gnu_agplv3_text():
    license_file = REPO_ROOT / "LICENSE"
    license_text = license_file.read_text(encoding="utf-8")
    assert len(license_text) > 30000
    assert "GNU AFFERO GENERAL PUBLIC LICENSE" in license_text
    assert "Version 3, 19 November 2007" in license_text
    assert "Everyone is permitted to copy and distribute verbatim copies" in license_text
    assert "The GNU Affero General Public License is a free, copyleft license" in license_text
    assert "Remote Network Interaction" in license_text
    assert "How to Apply These Terms to Your New Programs" in license_text
    assert "Copyright (C) 2007 Free Software Foundation, Inc." in license_text
    assert license_text.rstrip().endswith("<https://www.gnu.org/licenses/>.")
    assert hashlib.sha256(license_file.read_bytes()).hexdigest() == GNU_AGPLV3_SHA256


def test_spdx_metadata_consistent_across_pyproject_package_and_lock():
    project = _pyproject()["project"]
    assert project["license"] == SPDX
    assert project["license-files"] == ["LICENSE"]
    assert _package_json()["license"] == SPDX
    assert _package_lock()["packages"][""]["license"] == SPDX
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert SPDX in readme


def test_readme_links_license_and_governance_doc():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "](LICENSE)" in readme
    assert "docs/governance/license.md" in readme
    assert (REPO_ROOT / "docs" / "governance" / "license.md").is_file()


def test_license_governance_doc_records_version_date_sources_and_scope():
    doc = (REPO_ROOT / "docs" / "governance" / "license.md").read_text(encoding="utf-8")
    assert VERIFY_DATE in doc
    for name, version in UPSTREAM_VERSIONS.items():
        assert f"{name}=={version}" in doc
    for fragment in (
        "https://www.gnu.org/licenses/agpl-3.0.txt",
        "https://pypi.org/pypi/pdf2zh-next/2.9.0/json",
        "https://pypi.org/pypi/babeldoc/0.6.2/json",
        "https://raw.githubusercontent.com/PDFMathTranslate-next/PDFMathTranslate-next/v2.9.0/LICENSE",
        "https://raw.githubusercontent.com/funstory-ai/BabelDOC/v0.6.2/LICENSE",
    ):
        assert fragment in doc, fragment
    assert "不是法律意见" in doc or "不构成法律意见" in doc
    assert "单独核验" in doc
    assert "源码提供义务" in doc


def test_license_doc_distinguishes_usage_scenarios_and_avoids_derivative_claim():
    doc = (REPO_ROOT / "docs" / "governance" / "license.md").read_text(encoding="utf-8")
    for keyword in ("本地内部使用", "源代码再分发", "组合再分发或网络部署", "上游/依赖许可证"):
        assert keyword in doc, keyword
    assert "不声称" in doc and "只要 Python 依赖" in doc and "衍生作品" in doc
    assert "重新许可" in doc


def test_upstream_pins_locked_in_requirements():
    text = (REPO_ROOT / "requirements.lock").read_text(encoding="utf-8")
    for name, version in UPSTREAM_VERSIONS.items():
        assert f"{name}=={version}" in text


def test_installed_upstream_metadata_license_expression():
    for name, version in UPSTREAM_VERSIONS.items():
        try:
            dist = md.distribution(name)
        except md.PackageNotFoundError:
            pytest.skip(f"{name} 未安装；CI 在 pip install -r requirements.lock 后执行本测试")
        assert dist.version == version
        assert dist.metadata.get("License-Expression") == UPSTREAM_SPDX


def test_package_json_has_no_main_and_keeps_esm_type():
    package = _package_json()
    assert "main" not in package
    assert package["type"] == "module"
    mjs_runners = list((REPO_ROOT / "tests").glob("run-*.mjs"))
    assert mjs_runners
    for script in package["scripts"].values():
        if "node " in script:
            assert ".mjs" in script
