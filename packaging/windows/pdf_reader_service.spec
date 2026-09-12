# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir definition for the private ``app/PDF Reader Service.exe``.

This executable owns the private Python runtime: PyMuPDF, pdf2zh-next, BabelDOC, ONNX
Runtime, OpenCV, tiktoken and their native libraries are collected here, inside ``app/``.
``portable_launcher`` and ``validate_private_frozen_runtime`` both require the service to
live at ``app/PDF Reader Service.exe`` with every module search path inside ``app/``, so
the onedir output must not be flattened elsewhere.

Two decisions are deliberate, and both are verified again after the build:

* Dynamic imports are declared instead of guessed.  pdf2zh-next resolves translation
  backends through ``importlib.import_module`` and tiktoken discovers its plugins by
  scanning the ``tiktoken_ext`` namespace, so both need explicit collection.  Declaring
  them means the analysis warnings stay informative: the authoritative evidence that a
  locked distribution really shipped comes from the artifact coverage check, and any
  warn file PyInstaller writes stays inside the work path (never in the artifact).
* ``gradio``/``onnx``/``ruff`` are excluded: the upstream GUI stack is unused by the
  service, and the ``onnx`` wheel ships ``.onnx`` model files that the release data
  policy forbids shipping.
"""

import os
import pathlib

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

SPEC_DIRECTORY = pathlib.Path(SPECPATH)  # noqa: F821 - injected by PyInstaller
REPO_ROOT = pathlib.Path(os.environ.get("PDF_READER_BUILD_REPO_ROOT") or SPEC_DIRECTORY.resolve().parents[1])
GENERATED_DIRECTORY = pathlib.Path(
    os.environ.get("PDF_READER_BUILD_GENERATED_DIR") or REPO_ROOT / "build" / "release-windows" / "generated"
)


def _resource(environment_name, generated_name, tracked_name):
    """Prefer the build-rendered resource, then the versioned one shipped in the layer."""

    override = os.environ.get(environment_name)
    if override:
        return pathlib.Path(override)
    generated = GENERATED_DIRECTORY / generated_name
    if generated.is_file():
        return generated
    return SPEC_DIRECTORY / "manifests" / tracked_name


ICON = _resource("PDF_READER_BUILD_ICON", "pdf_reader.ico", "pdf_reader.ico")
VERSION_FILE = _resource("PDF_READER_BUILD_SERVICE_VERSION", "version-info-service.txt", "version-info-service.txt")

# 前端资源、配置示例与许可证在这里显式声明为收集输入（业务资源只有一份，禁止复制到
# packaging 层）。PyInstaller 先把它们放进 ``_internal``，``buildtool assemble`` 再把它们
# 移动到便携服务真正解析的 ``app/static``、``app/templates``、``app/config.example.toml``
# 与 ``app/licenses/LICENSE``，因此发行树里不会出现第二份副本。
datas = [
    (str(REPO_ROOT / "static"), "static"),
    (str(REPO_ROOT / "templates"), "templates"),
    (str(REPO_ROOT / "config.example.toml"), "."),
    (str(REPO_ROOT / "LICENSE"), "."),
]

# PyMuPDF 把 MuPDF 原生库放在包内（Windows 为 mupdf.dll），Python 侧依赖扫描不会把它
# 当成扩展模块；wheel 自带的 C 头文件属于开发材料，不进入发行物。
datas += collect_data_files(
    "pymupdf",
    excludes=["mupdf-devel/**", "**/*.h", "**/*.hpp", "**/*.a", "**/*.lib"],
)
# BabelDOC 的 CMap 表（pdfminer 兼容层）、DocumentIL 结构校验文件与 docvision 资源。
datas += collect_data_files(
    "babeldoc",
    includes=[
        "pdfminer/cmap/**",
        "pdfminer/*.txt",
        "pdfminer/LICENSE",
        "pdfminer/py.typed",
        "format/pdf/document_il/*.xsd",
        "format/pdf/document_il/*.rng",
        "format/pdf/document_il/*.rnc",
        "docvision/**",
    ],
)
# pdf2zh-next 的词表与品牌资源；其余源码由导入分析覆盖。
datas += collect_data_files("pdf2zh_next", includes=["gui_translation.yaml", "assets/**"])
datas += collect_data_files("tiktoken", includes=["py.typed"])

# 上游包在运行期动态解析的模块：静态导入扫描看不到它们，缺失只会在干净机上表现为翻译
# 阶段崩溃，因此这里显式声明；原生扩展模块（onnxruntime、cv2、hyperscan、rtree、
# uharfbuzz）也必须显式收集，否则只会在首次翻译时以 ImportError 暴露。
hiddenimports = []
hiddenimports += collect_submodules("tiktoken_ext")
hiddenimports += collect_submodules("pdf2zh_next.translator.translator_impl")
hiddenimports += collect_submodules("pdf2zh_next.config")
hiddenimports += collect_submodules("babeldoc.docvision")
hiddenimports += collect_submodules("babeldoc.format.pdf")
hiddenimports += [
    "pdf_reader",
    "pdf_reader.app",
    "pdf_reader.portable_service",
    "pdf_reader.portable_runtime",
    "pdf_reader.portable_data",
    "pdf_reader.paths",
    "babeldoc",
    "babeldoc.main",
    "babeldoc.glossary",
    "babeldoc.assets.assets",
    "babeldoc.pdfminer",
    "onnxruntime",
    "cv2",
    "sklearn.cluster",
    "tiktoken",
    "hyperscan",
    "rtree",
    "rtree.index",
    "uharfbuzz",
    "pymupdf",
    "fitz",
]

excludes = [
    # gradio 只在 pdf2zh_next.gui 中使用；本发行物使用自有前端，服务端不导入 GUI。
    "gradio",
    "gradio_client",
    "gradio_i18n",
    "gradio_pdf",
    # onnx 仅提供模型转换/校验工具，其 wheel 携带的数据策略禁止的 .onnx 测试模型。
    "onnx",
    # 构建工具与开发依赖绝不进入发行物。
    "ruff",
    "pytest",
    "coverage",
    "mypy",
    "pip",
    "setuptools",
    "wheel",
]

analysis = Analysis(
    [str(REPO_ROOT / "src" / "pdf_reader" / "portable_service.py")],
    pathex=[str(REPO_ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(SPEC_DIRECTORY / "hooks")],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    name="PDF Reader Service",
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
    name="service",
)
