"""P2-01 发行构建助手 CLI 的行为契约（Linux 可运行，不执行真实 Windows 构建）。

``build.ps1`` 只解析基础解释器，随后把全部构建逻辑交给 ``packaging/windows`` 内的助手包
（``python -m <helper> <command>``）；因此 CLI 子命令、退出码、发行目录边界与产物文件就是
发行层的稳定外部契约。本文件只通过该 CLI 驱动行为验证：

* 构建计划与清理边界只落在 ``build/release-windows`` 与 ``dist/release-windows``；
* 开发 venv/``config.toml``/``cache``/``logs`` 在构建与清理后保持不变；
* 快照命令覆盖四个开发路径，输出不得逃出发行构建目录；
* 两个 PyInstaller 包的边界（启动器不带翻译运行时、服务不带被排除的 GUI 栈）；
* 组装出单顶层入口、``data/`` 空骨架的 onedir 树，发行树拒绝开发泄漏；
* ``self-check`` 用桩运行时跑完整管线：manifest、两个策略门、文件清单、ZIP 与 SHA-256。

真实 PyInstaller onedir、ZIP 在干净 Windows 上运行与 Process Monitor 审计属于构建执行与
P2-02/P3-01；本文件不把它们伪装成已执行。助手缺失或改名时测试直接失败（而不是整体跳过）。
"""

from __future__ import annotations

import hashlib
import importlib
import json
import re
import shutil
import stat
import zipfile
from pathlib import Path

import pytest

from tests.release import packaging_harness as pkg

REPO_ROOT = pkg.REPO_ROOT
ARTIFACT_NAME_PATTERN = re.compile(r"^PDF-Reader-\d+\.\d+\.\d+-windows-x64-portable$")
SHA256_LINE = re.compile(r"^(?P<digest>[0-9a-f]{64})  (?P<path>.+)$")


# --------------------------------------------------------------------------- 夹具


@pytest.fixture
def release_repo(tmp_path: Path) -> Path:
    """合成仓库骨架：只包含构建预检要求的输入与忽略规则，不碰真实工作区。"""

    repo = tmp_path / "repo"
    policy_layer = repo / "packaging" / "windows"
    policy_layer.mkdir(parents=True)
    for name in ("runtime_policy.py", "data_policy.py", "runtime-requirements.lock"):
        shutil.copy2(pkg.RELEASE_LAYER / name, policy_layer / name)
    inputs = (
        "requirements.lock",
        "src/pdf_reader/portable_launcher.py",
        "src/pdf_reader/portable_service.py",
        "static/app.js",
        "static/style.css",
        "static/modules/scroll-sync.js",
        "templates/index.html",
        "config.example.toml",
    )
    for relative in inputs:
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"placeholder for {relative}\n", encoding="utf-8")
    (repo / "LICENSE").write_text("AGPL-3.0-only placeholder\n", encoding="utf-8")
    (repo / "README.md").write_text("placeholder release notes\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text('[project]\nname = "pdf_reader"\nversion = "9.9.9"\n', encoding="utf-8")
    (repo / ".gitignore").write_text("build/\ndist/\n", encoding="utf-8")
    return repo


@pytest.fixture(scope="module")
def selfcheck_workspace(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """跑一次 ``self-check``：用桩运行时执行完整打包管线，产物留在临时目录。"""

    workspace = tmp_path_factory.mktemp("p2-01-self-check")
    result = pkg.run_build_helper("self-check", "--workspace", str(workspace), repo_root=REPO_ROOT, timeout=900)
    assert result.returncode == 0, f"self-check 失败：\n{result.stdout}\n{result.stderr}"
    assert "self-check: ok" in result.stdout, result.stdout
    return workspace


def _staging_bundles(repo: Path) -> Path:
    """在合成仓库的构建目录里伪造两个 PyInstaller onedir 包。"""

    staging = repo / pkg.BUILD_DIRECTORY / "staging"
    for bundle, executable in (
        ("launcher", pkg.LAUNCHER_EXE),
        ("service", pkg.SERVICE_EXE),
    ):
        internal = staging / bundle / "_internal"
        internal.mkdir(parents=True)
        (staging / bundle / executable).write_bytes(b"portable executable placeholder\n")
        (internal / "python312.dll").write_bytes(b"private runtime placeholder\n")
    service_internal = staging / "service" / "_internal"
    for upstream in ("pdf2zh_next", "babeldoc", "pymupdf", "onnxruntime", "cv2", "tiktoken_ext"):
        (service_internal / upstream).mkdir()
        (service_internal / upstream / "__init__.py").write_text("", encoding="utf-8")
    return staging


def _artifact_of(workspace: Path) -> Path:
    dist = workspace / "dist"
    artifact = pkg.ARTIFACT_DIRNAME
    assert (dist / artifact).is_dir(), f"self-check 必须产出发行目录：{dist / artifact}"
    return dist / artifact


def _release_files(root: Path) -> set[str]:
    return {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}


def _run(argv: list[str], *, repo_root: Path, cwd: Path | None = None) -> object:
    return pkg.run_build_helper(*argv, repo_root=repo_root, cwd=cwd)


# --------------------------------------------------------------------------- 计划与边界


def test_build_plan_keeps_every_path_inside_the_two_release_directories(release_repo: Path) -> None:
    result = _run(["--json", "plan"], repo_root=release_repo)

    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    values = [value for value in plan.values() if isinstance(value, str)]
    paths = [Path(value) for value in values if "/" in value or "\\" in value]
    assert paths, f"构建计划必须解析出绝对路径：{values}"
    outputs_root = release_repo / pkg.BUILD_DIRECTORY
    dist_root = release_repo / pkg.DIST_DIRECTORY
    inputs_root = release_repo / "packaging" / "windows"
    for path in paths:
        assert path.is_absolute(), f"构建计划不接受相对路径：{path}"
        assert path == release_repo or release_repo in path.parents, f"构建路径逃出仓库：{path}"
        allowed = (release_repo, outputs_root, dist_root, inputs_root)
        assert any(path == root or root in path.parents for root in allowed), (
            f"构建路径只能来自仓库根、两个发行输出目录或 packaging/windows：{path}"
        )

    assert any(outputs_root in path.parents for path in paths), f"缺少 {pkg.BUILD_DIRECTORY}/ 内的构建路径：{paths}"
    assert any(dist_root in path.parents for path in paths), f"缺少 {pkg.DIST_DIRECTORY}/ 内的产物路径：{paths}"
    assert "9.9.9" in values, f"构建版本必须来自 pyproject.toml：{values}"
    assert [value for value in values if ARTIFACT_NAME_PATTERN.fullmatch(value)], (
        f"计划必须给出规范产物名（产品-版本-渠道）：{values}"
    )
    zip_names = [Path(value).name for value in values if value.endswith(".zip")]
    assert len(zip_names) == 1, f"计划必须给出唯一 ZIP 名：{zip_names}"
    assert ARTIFACT_NAME_PATTERN.fullmatch(zip_names[0][:-4]), f"ZIP 名必须带版本与渠道：{zip_names[0]}"


def test_layout_check_passes_here_and_rejects_missing_inputs_or_linked_output_dirs(release_repo: Path) -> None:
    healthy = _run(["layout-check"], repo_root=REPO_ROOT)
    assert healthy.returncode == 0, f"当前仓库必须通过构建预检：{healthy.stderr}"

    assert _run(["layout-check"], repo_root=release_repo).returncode == 0
    (release_repo / "templates" / "index.html").unlink()
    missing = _run(["layout-check"], repo_root=release_repo)
    assert missing.returncode != 0, "缺少构建输入时必须在构建前失败"
    assert "index.html" in missing.stderr, missing.stderr

    (release_repo / "templates" / "index.html").write_text("restored\n", encoding="utf-8")
    linked = release_repo / pkg.DIST_DIRECTORY
    linked.parent.mkdir(parents=True, exist_ok=True)
    linked.symlink_to(release_repo / "static", target_is_directory=True)
    assert _run(["layout-check"], repo_root=release_repo).returncode != 0, "发行输出目录不得是链接"


# --------------------------------------------------------------------------- 清理边界


def test_clean_removes_only_the_two_release_directories(release_repo: Path) -> None:
    developer_paths = ("venv", "cache", "logs")
    for name in developer_paths:
        (release_repo / name).mkdir()
        (release_repo / name / "keep.txt").write_text(name, encoding="utf-8")
    (release_repo / "config.toml").write_text("[api]\nkey = 'dev'\n", encoding="utf-8")
    build_root = release_repo / pkg.BUILD_DIRECTORY
    dist_root = release_repo / pkg.DIST_DIRECTORY
    (build_root / "venv").mkdir(parents=True)
    build_marker = build_root / "venv" / "marker.txt"
    build_marker.write_text("build", encoding="utf-8")
    build_marker.chmod(stat.S_IREAD)
    dist_root.mkdir(parents=True)
    dist_marker = dist_root / "marker.txt"
    dist_marker.write_text("dist", encoding="utf-8")
    dist_marker.chmod(stat.S_IREAD)

    dry_run = _run(["clean", "--include-dist", "--dry-run"], repo_root=release_repo)
    assert dry_run.returncode == 0, dry_run.stderr
    assert (build_root / "venv" / "marker.txt").is_file(), "dry-run 不得删除任何内容"
    assert (dist_root / "marker.txt").is_file(), "dry-run 不得删除任何内容"

    cleaned = _run(["clean", "--include-dist"], repo_root=release_repo)

    assert cleaned.returncode == 0, cleaned.stderr
    assert not build_root.exists() and not dist_root.exists()
    assert release_repo.is_dir(), "清理不得删除仓库根"
    for name in developer_paths:
        assert (release_repo / name / "keep.txt").is_file(), f"清理不得触碰开发路径 {name}/"
    assert (release_repo / "config.toml").is_file(), "清理不得触碰开发配置"


def test_remove_tree_retries_access_denied_after_making_entry_writable(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.syspath_prepend(str(pkg.RELEASE_LAYER))
    filesystem = importlib.import_module(f"{pkg.build_helper_module_name()}.filesystem")
    tree = tmp_path / "release-tree"
    tree.mkdir()
    protected = tree / "python.exe"
    protected.write_bytes(b"stub")
    retried: list[Path] = []
    chmod_modes: list[int] = []
    real_chmod = filesystem.os.chmod

    def retry_unlink(path: str) -> None:
        retried.append(Path(path))
        Path(path).unlink()

    def fake_chmod(path: str, mode: int) -> None:
        chmod_modes.append(mode)
        real_chmod(path, mode)

    def fake_rmtree(path: Path, *, onexc) -> None:
        denied = PermissionError(13, "access denied", str(protected))
        onexc(retry_unlink, str(protected), denied)
        Path(path).rmdir()

    monkeypatch.setattr(filesystem.os, "chmod", fake_chmod)
    monkeypatch.setattr(filesystem.shutil, "rmtree", fake_rmtree)

    filesystem.remove_tree(tree)

    assert retried == [protected]
    assert chmod_modes and chmod_modes[0] & stat.S_IWUSR
    assert not tree.exists()


def test_remove_tree_does_not_retry_unrelated_io_errors(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.syspath_prepend(str(pkg.RELEASE_LAYER))
    filesystem = importlib.import_module(f"{pkg.build_helper_module_name()}.filesystem")
    tree = tmp_path / "release-tree"
    tree.mkdir()
    protected = tree / "python.exe"
    protected.write_bytes(b"stub")

    def fake_rmtree(_path: Path, *, onexc) -> None:
        onexc(lambda _entry: None, str(protected), OSError(22, "unrelated failure"))

    monkeypatch.setattr(filesystem.shutil, "rmtree", fake_rmtree)

    with pytest.raises(OSError, match="unrelated failure"):
        filesystem.remove_tree(tree)
    assert protected.is_file()


def test_clean_rejects_linked_release_root_without_touching_its_target(release_repo: Path) -> None:
    outside = release_repo.parent / "outside-clean-target"
    outside.mkdir()
    sentinel = outside / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    build_root = release_repo / pkg.BUILD_DIRECTORY
    build_root.parent.mkdir(parents=True)
    build_root.symlink_to(outside, target_is_directory=True)

    cleaned = _run(["clean"], repo_root=release_repo)

    assert cleaned.returncode != 0, "链接形式的 build/release-windows 必须在删除前被拒绝"
    assert sentinel.read_text(encoding="utf-8") == "keep"


# --------------------------------------------------------------------------- 开发路径快照


def test_snapshot_commands_cover_developer_state_and_stay_inside_the_build_directory(release_repo: Path) -> None:
    snapshots = release_repo / pkg.BUILD_DIRECTORY
    for name in ("venv", "cache", "logs"):
        (release_repo / name).mkdir(parents=True)
        (release_repo / name / "state.txt").write_text(name, encoding="utf-8")
    (release_repo / "config.toml").write_text("[api]\nkey = 'dev'\n", encoding="utf-8")
    before = snapshots / "before.json"
    after = snapshots / "after.json"

    first = _run(["snapshot", "--output", str(before)], repo_root=release_repo)
    assert first.returncode == 0, first.stderr
    assert before.is_file(), "快照必须写到发行构建目录"
    assert _run(["snapshot", "--output", str(after)], repo_root=release_repo).returncode == 0
    identical = _run(["snapshot-diff", "--before", str(before), "--after", str(after)], repo_root=release_repo)
    assert identical.returncode == 0, f"未改动的开发路径必须判定为一致：{identical.stderr}"

    outside = release_repo.parent / "escape.json"
    escaped = _run(["snapshot", "--output", str(outside)], repo_root=release_repo)
    assert escaped.returncode != 0, "快照输出不得逃出 build/release-windows/"
    assert not outside.exists(), "被拒绝的快照输出不得落盘"

    for name in ("venv", "cache", "logs"):
        target = release_repo / name / "state.txt"
        target.write_text("changed", encoding="utf-8")
        assert _run(["snapshot", "--output", str(after)], repo_root=release_repo).returncode == 0
        changed = _run(["snapshot-diff", "--before", str(before), "--after", str(after)], repo_root=release_repo)
        assert changed.returncode != 0, f"{name}/ 的改动必须被判定为开发路径变化"
        assert f"{name}/state.txt" in changed.stderr, changed.stderr
        target.write_text(name, encoding="utf-8")

    (release_repo / "config.toml").write_text("[api]\nkey = 'other'\n", encoding="utf-8")
    assert _run(["snapshot", "--output", str(after)], repo_root=release_repo).returncode == 0
    changed = _run(["snapshot-diff", "--before", str(before), "--after", str(after)], repo_root=release_repo)
    assert changed.returncode != 0, "config.toml 的改动必须被判定为开发路径变化"
    assert "config.toml" in changed.stderr, changed.stderr


# --------------------------------------------------------------------------- 包与组装


def test_verify_bundles_separates_launcher_from_translation_runtime(release_repo: Path) -> None:
    staging = _staging_bundles(release_repo)

    healthy = _run(["verify-bundles", "--staging-root", str(staging)], repo_root=release_repo)
    assert healthy.returncode == 0, healthy.stderr

    (staging / "launcher" / "_internal" / "babeldoc").mkdir()
    (staging / "service" / "_internal" / "gradio").mkdir()
    rejected = _run(["verify-bundles", "--staging-root", str(staging)], repo_root=release_repo)

    assert rejected.returncode != 0, "启动器携带翻译运行时/服务携带 GUI 栈必须被拒绝"
    assert "babeldoc" in rejected.stderr and "launcher" in rejected.stderr, rejected.stderr
    assert "gradio" in rejected.stderr, rejected.stderr


def test_assemble_builds_a_single_entry_onedir_tree_with_empty_data_scaffold(release_repo: Path) -> None:
    staging = _staging_bundles(release_repo)
    dist_root = release_repo / pkg.DIST_DIRECTORY
    artifact = dist_root / pkg.ARTIFACT_DIRNAME

    assembled = _run(
        ["assemble", "--staging-root", str(staging), "--release-tree", str(artifact)], repo_root=release_repo
    )

    assert assembled.returncode == 0, assembled.stderr
    assert assembled.stdout.count("assemble:") >= 2, assembled.stdout
    assert (artifact / pkg.LAUNCHER_EXE).is_file()
    assert sorted(path.name for path in artifact.glob("*.exe")) == [pkg.LAUNCHER_EXE], (
        "顶层只能有唯一面向用户的启动入口"
    )
    assert (artifact / "_internal").is_dir(), "启动器私有运行时必须与 EXE 同级"
    assert (artifact / pkg.APP_DIRECTORY / pkg.SERVICE_EXE).is_file(), "私有服务必须位于 app/"
    assert (artifact / pkg.APP_DIRECTORY / "_internal").is_dir()
    for relative in (
        "app/static/app.js",
        "app/static/style.css",
        "app/templates/index.html",
        "app/config.example.toml",
        "app/licenses/LICENSE",
    ):
        assert (artifact / relative).is_file(), f"业务资源必须显式收集：{relative}"
    assert (artifact / "data").is_dir() and not list((artifact / "data").iterdir()), (
        "data/ 只允许空骨架，真实数据由首次启动创建"
    )

    stale = artifact / "readonly-stale.txt"
    stale.write_text("stale", encoding="utf-8")
    stale.chmod(stat.S_IREAD)
    rebuilt = _run(
        ["assemble", "--staging-root", str(staging), "--release-tree", str(artifact)], repo_root=release_repo
    )
    assert rebuilt.returncode == 0, rebuilt.stderr
    assert not stale.exists(), "重复组装必须能清理只读的旧发行文件"

    escaped = _run(
        ["assemble", "--staging-root", str(staging), "--release-tree", str(release_repo)], repo_root=release_repo
    )
    assert escaped.returncode != 0, "产物目录不得落在 dist/release-windows/ 之外"


# --------------------------------------------------------------------------- 产物与自检


def test_self_check_artifact_tree_rejects_development_leaks(selfcheck_workspace: Path, tmp_path: Path) -> None:
    artifact = _artifact_of(selfcheck_workspace)
    leaked = tmp_path / pkg.ARTIFACT_DIRNAME
    shutil.copytree(artifact, leaked)
    (leaked / "config.toml").write_text("[api]\n", encoding="utf-8")
    (leaked / pkg.APP_DIRECTORY / "stale.pyc").write_bytes(b"pyc")
    (leaked / "venv").mkdir()
    (leaked / "helper.exe").write_bytes(b"exe")
    (leaked / pkg.APP_DIRECTORY / "notes.txt").write_text(
        "built from C:\\Users\\developer\\PDF_reader\\venv\\Scripts\\python.exe\n", encoding="utf-8"
    )

    result = _run(["verify-tree", "--release-tree", str(leaked)], repo_root=REPO_ROOT)

    assert result.returncode != 0, "发行树审计必须拒绝开发泄漏"
    for marker in ("config.toml", ".pyc", "venv", "additional top-level executables", "developer path"):
        assert marker in result.stderr, f"缺少对 {marker!r} 的报告：{result.stderr}"


def test_self_check_packages_versioned_manifest_inventory_zip_and_checksum(selfcheck_workspace: Path) -> None:
    workspace = selfcheck_workspace
    dist = workspace / "dist"
    artifact = _artifact_of(workspace)
    zips = [path for path in dist.iterdir() if path.suffix == ".zip"]
    assert len(zips) == 1, f"dist/ 必须有唯一便携 ZIP：{sorted(p.name for p in dist.iterdir())}"
    zip_path = zips[0]
    artifact_name = zip_path.name[: -len(".zip")]
    assert ARTIFACT_NAME_PATTERN.fullmatch(artifact_name), f"ZIP 名必须带规范版本：{zip_path.name}"

    clean = _run(["verify-tree", "--release-tree", str(artifact)], repo_root=REPO_ROOT)
    assert clean.returncode == 0, f"自检产物必须通过发行树审计：{clean.stderr}"

    for relative in (
        "app/runtime-manifest.json",
        "app/release-manifest.json",
        "app/licenses/DEPENDENCIES.txt",
        "app/licenses/LICENSE",
    ):
        assert (artifact / relative).is_file(), f"产物缺少必需文件：{relative}"
    runtime_manifest = json.loads((artifact / "app" / "runtime-manifest.json").read_text(encoding="utf-8"))
    assert runtime_manifest["schema_version"] == 1
    assert re.fullmatch(r"[0-9a-f]{40}", runtime_manifest["source_commit"]), runtime_manifest["source_commit"]
    assert runtime_manifest["packages"], "运行时 manifest 必须列出锁定依赖"

    files = _release_files(artifact)
    inventory = dist / f"{artifact_name}.files.sha256"
    assert inventory.is_file(), f"dist/ 必须给出逐文件清单：{inventory.name}"
    listed: dict[str, str] = {}
    for line in inventory.read_text(encoding="utf-8").splitlines():
        match = SHA256_LINE.match(line)
        assert match is not None, f"清单行必须是 sha256sum 格式：{line!r}"
        listed[match.group("path")] = match.group("digest")
    assert listed, "文件清单不得为空"
    assert set(listed) <= files, f"清单列出了不存在的文件：{sorted(set(listed) - files)}"
    for relative, digest in listed.items():
        actual = hashlib.sha256((artifact / relative).read_bytes()).hexdigest()
        assert actual == digest, f"清单摘要不匹配：{relative}"
    assert len(files) - len(listed) <= 1, f"清单必须覆盖除自身摘要清单外的全部文件：{sorted(files - set(listed))}"

    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
    assert names and all(name.startswith(f"{artifact_name}/") for name in names), (
        "ZIP 必须只有一个版本化根目录，且不包含本机路径"
    )
    assert {name[len(artifact_name) + 1 :] for name in names} == files, "ZIP 必须包含完整发行树"

    checksum = dist / f"{zip_path.name}.sha256"
    assert checksum.is_file(), f"dist/ 必须给出 ZIP 校验和：{checksum.name}"
    body = checksum.read_text(encoding="utf-8").strip()
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    assert digest in body and zip_path.name in body, f"校验和文件必须对应 ZIP：{body!r}"

    second = pkg.run_build_helper(
        "self-check", "--workspace", str(workspace.parent / "second-run"), repo_root=REPO_ROOT, timeout=900
    )
    assert second.returncode == 0, second.stderr
    other = next((workspace.parent / "second-run" / "dist").glob("*.zip"))
    assert other.read_bytes() == zip_path.read_bytes(), "同一输入的便携 ZIP 必须逐字节可复现"
