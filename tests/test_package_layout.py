"""P2-01 结构性回归：所有生产模块来自 src/pdf_reader，无 shim/路径 hack。"""

import importlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pymupdf

from pdf_reader.app import create_app

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PACKAGE = REPO_ROOT / "src" / "pdf_reader"

PRODUCTION_MODULES = [
    "app",
    "config",
    "debug_trace",
    "engine_resolver",
    "file_hash",
    "glossary_merger",
    "glossary_service",
    "logging_config",
    "paths",
    "pdf_extraction",
    "pdf_renderer",
    "routes",
    "sse_stream",
    "state",
    "task_logging",
    "translation_coordinator",
    "translation_lifecycle",
    "translation_orchestrator",
    "translation_settings",
]


def test_all_production_modules_live_under_src():
    expected_dir = SRC_PACKAGE.resolve()
    for name in PRODUCTION_MODULES:
        module = importlib.import_module(f"pdf_reader.{name}")
        assert module.__file__ is not None, name
        assert Path(module.__file__).resolve().parent == expected_dir, (
            f"pdf_reader.{name} resolved to {module.__file__}"
        )


def test_no_root_shim_modules():
    for name in PRODUCTION_MODULES:
        assert not (REPO_ROOT / f"{name}.py").exists(), f"root shim must not exist: {name}.py"


def test_no_sys_path_or_pythonpath_hacks():
    conftest = (REPO_ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert "sys.path" not in conftest
    assert "PYTHONPATH" not in conftest
    for py in SRC_PACKAGE.glob("*.py"):
        text = py.read_text(encoding="utf-8")
        assert "sys.path" not in text, f"{py.name} must not mutate sys.path"
        assert "sitecustomize" not in text, f"{py.name} must not rely on sitecustomize"


def test_no_bare_production_imports_in_package():
    names = "|".join(PRODUCTION_MODULES)
    pattern = re.compile(rf"^\s*(?:import|from)\s+({names})\b", re.MULTILINE)
    for py in SRC_PACKAGE.glob("*.py"):
        text = py.read_text(encoding="utf-8")
        match = pattern.search(text)
        assert match is None, f"{py.name}: bare import {match.group(0)!r}"


def test_no_old_patch_strings_in_tests():
    names = "|".join(PRODUCTION_MODULES)
    pattern = re.compile(rf'patch\("({names})\.')
    for py in (REPO_ROOT / "tests").glob("test_*.py"):
        text = py.read_text(encoding="utf-8")
        match = pattern.search(text)
        assert match is None, f"{py.name}: old patch string {match.group(0)!r}"


def test_installed_package_import_from_outside_repo(tmp_path):
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, "-c", "import pdf_reader; print(pdf_reader.__file__)"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    resolved = Path(result.stdout.strip()).resolve()
    assert resolved == (SRC_PACKAGE / "__init__.py").resolve()


def test_python_m_help_from_outside_repo(tmp_path):
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, "-m", "pdf_reader", "--help"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "usage: python -m pdf_reader" in result.stdout
    assert "--debug" in result.stdout
    assert "--no-debug" in result.stdout


def test_create_app_from_outside_repo_finds_root_resources(tmp_path):
    probe = r"""
import json
from pdf_reader import config, paths
from pdf_reader.app import create_app

app = create_app()
print(json.dumps({
    "project_root": str(paths.get_project_root()),
    "config_path": str(config.CONFIG_PATH),
    "glossary_path": str(config.GLOSSARY_PATH),
    "log_dir": str(paths.get_log_dir()),
    "cache_dir": str(config.CACHE_DIR),
    "templates": str(app.template_folder),
    "static": str(app.static_folder),
}))
"""
    data_root = tmp_path / "data"
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["PDF_READER_DATA_ROOT"] = str(data_root)
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout.strip().splitlines()[-1])
    root = REPO_ROOT.resolve()
    assert data["project_root"] == str(root)
    assert data["config_path"] == str(root / "config.toml")
    assert data["glossary_path"] == str(root / "docs" / "glossary.csv")
    assert data["log_dir"] == str((data_root / "logs").resolve())
    assert data["cache_dir"] == str((data_root / "cache").resolve())
    assert data["templates"] == str(root / "templates")
    assert data["static"] == str(root / "static")


def test_minimal_open_pdf_smoke_via_flask_client(tmp_path):
    """无 GUI 替代冒烟：真实 Flask test client + 真实 AppState 打开最小 PDF 并渲染。"""
    pdf_path = tmp_path / "sample.pdf"
    doc = pymupdf.open()
    doc.new_page(width=612, height=792)
    doc.save(str(pdf_path))
    doc.close()

    app = create_app()
    app.config["TESTING"] = True
    try:
        with app.test_client() as client:
            opened = client.post("/api/open", json={"path": str(pdf_path)})
            assert opened.status_code == 200
            data = opened.get_json()
            assert data["page_count"] == 1
            assert data["document_id"]
            rendered = client.get("/api/page/left/0")
            assert rendered.status_code == 200
            assert rendered.data[:8] == b"\x89PNG\r\n\x1a\n"
    finally:
        # Windows：先关闭 AppState 持有的左右文档句柄，再删除自建 PDF；
        # 若仍泄漏句柄，unlink 会抛 PermissionError/WinError，测试失败即锁定回归。
        app.config["app_state"]._close_docs()
        pdf_path.unlink()
    assert not pdf_path.exists()
