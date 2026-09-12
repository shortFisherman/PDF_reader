"""P2-01 构建定义契约：onedir spec、单顶层入口、资源/动态导入收集与开发数据排除。

真实 Windows 构建不在本文件执行：spec 在桩 PyInstaller API 下运行（Linux 可运行），
断言锁定发行树结构、显式资源收集、动态导入声明与“绝不收集开发数据/绝对路径”的边界。
真实 onedir 目录、ZIP 运行与干净机验收属于 P2-01 构建执行与 P2-02/P3-01。
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.release import packaging_harness as pkg

REPO_ROOT = pkg.REPO_ROOT


def test_release_layer_owns_versioned_spec_and_build_script() -> None:
    specs = pkg.all_specs()
    script = pkg.resolve_build_script()

    assert specs, "P2-01 必须在 packaging/windows/ 内提供受版本控制的 PyInstaller spec"
    for path in [*specs, script]:
        assert path.is_file()
        assert path.resolve().is_relative_to(pkg.RELEASE_LAYER.resolve()), (
            f"发行构建定义必须位于 packaging/windows/ 内：{path}"
        )

    tracked = pkg.tracked_layer_paths()
    for path in [*specs, script]:
        relative = path.relative_to(REPO_ROOT).as_posix()
        assert relative in tracked, f"构建定义必须受版本控制：{relative}"


def test_release_layer_never_copies_business_sources_frontend_assets_or_user_data() -> None:
    forbidden_directories = {
        ".git",
        "__pycache__",
        "build",
        "cache",
        "dist",
        "logs",
        "node_modules",
        "src",
        "static",
        "templates",
        "tests",
        "venv",
        ".venv",
    }
    forbidden_names = {
        ".env",
        "app.js",
        "app.py",
        "config.toml",
        "index.html",
        "package.json",
        "paths.py",
        "routes.py",
        "start.bat",
        "state.py",
        "style.css",
    }
    for path in pkg.layer_files():
        relative = path.relative_to(pkg.RELEASE_LAYER)
        assert not (set(relative.parts) & forbidden_directories), (
            f"发行层只存放发行适配与构建基础设施，不得复制业务/开发内容：{relative.as_posix()}"
        )
        assert path.name.lower() not in forbidden_names, f"发行层不得包含开发文件：{relative.as_posix()}"
        assert path.suffix.lower() not in {".whl", ".egg", ".tar", ".gz", ".zip", ".7z"}, (
            f"发行层不得保存 wheel/压缩产物：{relative.as_posix()}"
        )


def test_build_definitions_have_no_developer_absolute_paths_or_key_material() -> None:
    absolute_path_patterns = (
        r"[A-Za-z]:\\",
        r"/home/[A-Za-z0-9_.-]+/",
        r"/Users/[A-Za-z0-9_.-]+/",
    )
    for path, text in pkg.script_documents():
        cleaned = pkg.strip_comments(text)
        for pattern in absolute_path_patterns:
            match = re.search(pattern, cleaned)
            assert match is None, f"{path.name} 含本机绝对路径：{match.group(0)!r}"
    for path, text in pkg.layer_documents():
        match = re.search(r"sk-[A-Za-z0-9]{16,}|Bearer\s+[A-Za-z0-9._-]{20,}", text)
        assert match is None, f"{path.name} 含疑似密钥材料：{match.group(0)!r}"


def test_spec_executes_under_stub_pyinstaller_as_onedir_collect(tmp_path: Path) -> None:
    recordings = pkg.collect_spec_recordings(tmp_path)

    for recording in recordings:
        assert recording.calls_named("COLLECT"), (
            f"{recording.path.name} 必须用 COLLECT 汇总目录式运行时（onedir），而不是把依赖内嵌进 EXE"
        )
        exes = recording.calls_named("EXE")
        assert exes, f"{recording.path.name} 必须定义 EXE 入口"
        for call in exes:
            assert pkg.exe_excludes_binaries(call), (
                f"{recording.path.name} 的 EXE 必须 exclude_binaries=True 并由 COLLECT 收集依赖"
            )
    for path, text in pkg.script_documents():
        assert "--onefile" not in text, f"{path.name} 不得改用 onefile 打包"


def test_build_layer_defines_one_top_level_launcher_and_app_private_service(tmp_path: Path) -> None:
    recordings = pkg.collect_spec_recordings(tmp_path)
    merged = pkg.merge_recordings(recordings)
    names = {pkg.executable_stem(call.kwargs.get("name")) for call in merged.calls_named("EXE")}

    assert pkg.LAUNCHER_STEM in names, f"缺少顶层启动入口 {pkg.LAUNCHER_EXE}；当前 EXE：{sorted(names)}"
    assert pkg.SERVICE_STEM in names, f"缺少 app 内私有服务 {pkg.SERVICE_EXE}；当前 EXE：{sorted(names)}"
    assert names == {pkg.LAUNCHER_STEM, pkg.SERVICE_STEM}, (
        f"顶层只能有一个面向用户的启动入口，当前 EXE：{sorted(names)}"
    )

    spec_places_service = [
        recording.path.name
        for recording in recordings
        if any(
            pkg.executable_stem(call.kwargs.get("name")) == pkg.SERVICE_STEM for call in recording.calls_named("EXE")
        )
        and pkg.mentions_app_directory(pkg.document(recording.path))
    ]
    script_places_service = [
        path.name
        for path, text in pkg.build_documents()
        if pkg.SERVICE_STEM in text and pkg.mentions_app_directory(text)
    ]
    assert spec_places_service or script_places_service, (
        f"{pkg.SERVICE_EXE} 必须由 spec 的收集结果或构建脚本落到 {pkg.APP_DIRECTORY}/ 私有运行时目录"
        "（与 paths.portable_from_executable 及 runtime_policy 的产物契约一致）"
    )


def test_build_layer_entry_scripts_reach_launcher_and_service_modules(tmp_path: Path) -> None:
    merged = pkg.merge_recordings(pkg.collect_spec_recordings(tmp_path))
    documents = pkg.layer_documents()

    for module_name in ("portable_launcher", "portable_service"):
        holders = [path.name for path, text in documents if module_name in text]
        assert holders, f"构建层必须接入 pdf_reader.{module_name} 入口（spec 或包装入口）"

    assert merged.calls_named("Analysis"), "spec 必须至少分析一次业务入口脚本"
    entry_scripts = [pkg.normalize_separators(name).lower() for name in pkg.analysis_scripts(merged)]
    assert any("launcher" in name for name in entry_scripts), f"缺少启动器入口脚本：{entry_scripts}"
    assert any("service" in name for name in entry_scripts), f"缺少服务入口脚本：{entry_scripts}"


def test_artifact_layout_matches_existing_runtime_and_data_policy_contracts() -> None:
    runtime_policy = pkg.load_release_module("runtime_policy.py", "windows_runtime_policy")
    data_policy = pkg.load_release_module("data_policy.py", "windows_data_policy")
    corpus = pkg.layer_corpus()
    normalized = pkg.normalize_separators(corpus)

    assert runtime_policy.RUNTIME_MANIFEST.as_posix() == pkg.RUNTIME_MANIFEST_RELATIVE_PATH
    assert data_policy.LAUNCHER_EXECUTABLE == pkg.LAUNCHER_EXE
    assert data_policy.APP_DIRECTORY == pkg.APP_DIRECTORY

    assert "runtime-manifest.json" in normalized, "构建必须产出 app/runtime-manifest.json"
    assert pkg.LAUNCHER_EXE in corpus, f"构建必须产出顶层 {pkg.LAUNCHER_EXE}"
    assert pkg.DIST_DIRECTORY in normalized, f"最终产物必须位于 {pkg.DIST_DIRECTORY}/"
    assert pkg.ARTIFACT_DIRNAME in corpus, f"产品目录名必须仍然是 {pkg.ARTIFACT_DIRNAME!r}"


def test_spec_collects_frontend_templates_config_example_and_license(tmp_path: Path) -> None:
    merged = pkg.merge_recordings(pkg.collect_spec_recordings(tmp_path))
    datas = pkg.analysis_datas(merged)
    collected = [source for source, _ in datas] + [destination for _, destination in datas]
    collected += sorted(pkg.tree_sources(merged))

    for directory in ("static", "templates"):
        assert any(pkg.has_path_component(value, directory) for value in collected), (
            f"必须显式收集 {directory}/（业务资源只有一份，禁止复制到 packaging）"
        )
    for filename in ("config.example.toml", "LICENSE"):
        assert any(Path(pkg.normalize_separators(value)).name == filename for value in collected), (
            f"必须显式收集 {filename}"
        )


def test_build_layer_declares_icon_and_version_metadata(tmp_path: Path) -> None:
    merged = pkg.merge_recordings(pkg.collect_spec_recordings(tmp_path))
    corpus = pkg.layer_corpus()

    layer_icons = [path for path in pkg.layer_files() if path.suffix.lower() == ".ico"]
    assert layer_icons, "发行层必须保存受版本控制的图标资源（.ico）"
    exe_icons = [call.kwargs.get("icon") for call in merged.calls_named("EXE") if call.kwargs.get("icon")]
    assert exe_icons, "每个发行 EXE 都必须显式绑定图标（spec 的 icon=）"
    for icon in exe_icons:
        assert _layer_asset_exists(str(icon)), f"EXE icon= 必须指向真实图标：{icon}"
    assert any(_layer_asset_exists(str(icon)) for icon in exe_icons)

    version_resources = [
        path
        for path in pkg.layer_files()
        if path.suffix.lower() in {".txt", ".rc"} and "VSVersionInfo" in pkg.document(path)
    ]
    exe_versions = [call.kwargs.get("version") for call in merged.calls_named("EXE") if call.kwargs.get("version")]
    for version in exe_versions:
        assert _layer_asset_exists(str(version)), f"EXE version= 必须指向受版本控制的版本资源：{version}"
    version_in_manifest = "source_commit" in corpus and "__version__" in corpus
    assert version_resources or exe_versions or version_in_manifest, (
        "必须显式提供版本信息：Windows 版本资源（VSVersionInfo/--version-file，由 spec 的 version= 引用）"
        "或把应用版本与源码提交写入 app/runtime-manifest.json"
    )


def _layer_asset_exists(reference: str) -> bool:
    """引用（相对路径/纯文件名）是否指向仓库内真实存在的发行资源。"""

    normalized = pkg.normalize_separators(reference)
    name = Path(normalized).name
    candidates = [pkg.RELEASE_LAYER / normalized, REPO_ROOT / normalized, REPO_ROOT / "static" / name]
    if any(candidate.is_file() for candidate in candidates):
        return True
    layer_matches = any(path.name == name for path in pkg.layer_files())
    static_matches = any(path.name == name for path in (REPO_ROOT / "static").rglob("*"))
    return layer_matches or static_matches


def test_spec_declares_upstream_dynamic_imports_and_package_data(tmp_path: Path) -> None:
    runtime_policy = pkg.load_release_module("runtime_policy.py", "windows_runtime_policy")
    lock = runtime_policy.parse_lock(REPO_ROOT / runtime_policy.RUNTIME_LOCK)
    corpus = pkg.layer_corpus()
    merged = pkg.merge_recordings(pkg.collect_spec_recordings(tmp_path))
    declared = pkg.analysis_hiddenimports(merged) | pkg.collected_package_names(merged)
    declared |= {source for source, _ in pkg.analysis_datas(merged)}
    declared |= {source for source, _ in pkg.analysis_binaries(merged)}
    declared |= pkg.tree_sources(merged)
    declared_text = "\n".join(declared)

    # 服务入口必须显式声明上游动态导入/包数据，不能依赖“装了什么就收什么”。
    spec_required = {
        "pdf2zh-next": ("pdf2zh_next",),
        "babeldoc": ("babeldoc",),
        "pymupdf": ("fitz", "pymupdf"),
    }
    missing = [
        f"{distribution} → {'/'.join(names)}"
        for distribution, names in spec_required.items()
        if distribution in lock and not any(name in declared_text for name in names)
    ]
    assert not missing, "spec 必须显式声明上游动态导入与包数据：" + "; ".join(missing)

    native_required = {
        "onnxruntime": ("onnxruntime",),
        "opencv-python": ("cv2",),
        "hyperscan": ("hyperscan",),
        "rtree": ("rtree",),
        "uharfbuzz": ("uharfbuzz",),
    }
    unknown = [
        f"{distribution} → {'/'.join(names)}"
        for distribution, names in native_required.items()
        if distribution in lock
        and not any(
            name in declared_text or re.search(rf"(?<![\w.]){re.escape(name)}(?![\w])", corpus) for name in names
        )
    ]
    assert not unknown, "构建层必须显式处理原生 DLL/动态导入：" + "; ".join(unknown)


def test_spec_analysis_never_collects_development_data_or_repository_state(tmp_path: Path) -> None:
    merged = pkg.merge_recordings(pkg.collect_spec_recordings(tmp_path))
    entries = [*pkg.analysis_datas(merged), *pkg.analysis_binaries(merged)]

    forbidden_components = {
        ".git",
        ".venv",
        "__pycache__",
        "cache",
        "fixtures",
        "history",
        "logs",
        "node_modules",
        "tests",
        "venv",
    }
    forbidden_names = {"config.toml", ".env", "instance.json", "launcher.log", "portable-data.json"}
    for source, destination in entries:
        assert not (set(pkg.path_parts(source)) & forbidden_components), f"不得收集开发数据：{source} → {destination}"
        assert Path(source).name.lower() not in forbidden_names, f"不得收集开发数据：{source}"
        assert "docs/reports" not in pkg.normalize_separators(source), f"不得收集开发报告：{source}"

    for script in pkg.analysis_scripts(merged):
        assert "tests" not in pkg.path_parts(script), f"入口脚本不得来自 tests/：{script}"
