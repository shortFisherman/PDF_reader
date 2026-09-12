# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir definition for the user-facing ``PDF Reader.exe``.

This is the only entry point a user double-clicks.  It keeps the real user environment
and drives exactly one private ``app/PDF Reader Service.exe`` over loopback, so the
translation runtime (PyMuPDF, pdf2zh-next, BabelDOC, ONNX Runtime, ...) belongs to
``pdf_reader_service.spec`` and must not appear here.

Paths are derived from ``SPECPATH`` (this directory) or from the ``PDF_READER_BUILD_*``
variables that ``build.ps1`` exports; the file never hard-codes a build machine path.
``packaging/windows`` only carries release adaptation, so nothing from ``src/``,
``static/`` or ``templates/`` is copied here -- the build reads the single sources from
the repository root at build time.
"""

import os
import pathlib

from PyInstaller.utils.hooks import collect_submodules

SPEC_DIRECTORY = pathlib.Path(SPECPATH)  # noqa: F821 - injected by PyInstaller
REPO_ROOT = pathlib.Path(os.environ.get("PDF_READER_BUILD_REPO_ROOT") or SPEC_DIRECTORY.resolve().parents[1])
GENERATED_DIRECTORY = pathlib.Path(
    os.environ.get("PDF_READER_BUILD_GENERATED_DIR") or REPO_ROOT / "build" / "release-windows" / "generated"
)


def _resource(environment_name, generated_name, tracked_name):
    """Prefer the build-rendered resource, then the versioned one shipped in the layer.

    The checked-in copy under ``manifests/`` is the release-layer default (it keeps the
    spec executable in contract tests and documents the shipped metadata); ``build.ps1``
    exports the rendered files so the bundled version always matches ``pyproject.toml``.
    """

    override = os.environ.get(environment_name)
    if override:
        return pathlib.Path(override)
    generated = GENERATED_DIRECTORY / generated_name
    if generated.is_file():
        return generated
    return SPEC_DIRECTORY / "manifests" / tracked_name


ICON = _resource("PDF_READER_BUILD_ICON", "pdf_reader.ico", "pdf_reader.ico")
VERSION_FILE = _resource("PDF_READER_BUILD_LAUNCHER_VERSION", "version-info-launcher.txt", "version-info-launcher.txt")

# 顶层启动器不提供 web 资源（前端由私有服务提供），因此这里不收集 static/templates。
datas = []

# tiktoken discovers its encoding plugins by iterating the ``tiktoken_ext`` namespace at
# runtime, so a static import scan cannot see them.
hiddenimports = collect_submodules("tiktoken_ext") + [
    "tkinter",
    "tkinter.filedialog",
    "tkinter.messagebox",
    "tkinter.scrolledtext",
    "tkinter.ttk",
    "pdf_reader",
    "pdf_reader.portable_launcher",
    "pdf_reader.portable_runtime",
    "pdf_reader.portable_errors",
    "pdf_reader.portable_instance",
    "pdf_reader.portable_data",
    "pdf_reader.paths",
]

excludes = [
    # 上游 GUI/工具发行版不属于启动器面；数据策略也会拒绝 ``onnx`` 附带的 .onnx 测试模型。
    "gradio",
    "gradio_client",
    "gradio_i18n",
    "gradio_pdf",
    "onnx",
    "ruff",
    "pytest",
    "coverage",
    "mypy",
    "pip",
    "setuptools",
    "wheel",
]

analysis = Analysis(
    [str(REPO_ROOT / "src" / "pdf_reader" / "portable_launcher.py")],
    pathex=[str(REPO_ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(SPEC_DIRECTORY / "hooks")],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    # 分析器的缺失导入告警只是提示，且其 warn 文件写在 PyInstaller workpath 内（不会进
    # 发行物）；是否真的缺包由 buildtool 的发行物覆盖检查给出可发布证据。
)
pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    name="PDF Reader",
    icon=str(ICON),
    version=str(VERSION_FILE),
    console=False,
    disable_windowed_traceback=False,
    upx=False,
    exclude_binaries=True,
    debug=False,
    strip=False,
)

collection = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="launcher",
)
