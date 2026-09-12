"""Command surface for the P2-01 build; ``build.ps1`` and ``build.sh`` call this.

Every command is idempotent, prints a single stable summary line, and exits non-zero
with an ``ERROR [<code>]:`` line on failure.  PowerShell therefore never has to
reimplement build logic -- it resolves the interpreter, then delegates.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from . import artifacts, deps, filesystem, layout, lock, manifest, modules, snapshot, wheels, winver
from . import assemble as assemble_module


def _ensure_utf8_streams() -> None:
    """Force UTF-8 output so Chinese paths/messages survive a cp936 Windows console."""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):  # pragma: no cover - non-reconfigurable stream
                continue


def _fail(code: str, message: str) -> int:
    print(f"ERROR [{code}]: {message}", file=sys.stderr)
    return 1


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _resolve_repo_root(args: argparse.Namespace) -> Path:
    if args.repo_root is not None:
        return Path(args.repo_root).resolve(strict=False)
    return layout.find_repo_root()


def _load_plan(args: argparse.Namespace) -> layout.BuildPlan:
    repo_root = _resolve_repo_root(args)
    if args.plan_file is not None:
        # 计划文件本身是构建产物：它必须留在仓库内，且不得谎报 repo_root，否则后续所有
        # 边界校验都会围绕一个伪造的根展开。
        plan_file = layout.require_inside(Path(args.plan_file), repo_root, label="build plan file")
        try:
            payload = json.loads(plan_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise layout.BuildLayoutError(f"cannot read the build plan: {exc}") from exc
        if not isinstance(payload, dict):
            raise layout.BuildLayoutError("build plan must be a JSON object")
        plan = layout.plan_from_payload(payload)
        if not layout.same_path(plan.repo_root, repo_root):
            raise layout.BuildLayoutError(f"build plan belongs to another repository: {plan.repo_root} != {repo_root}")
        return plan
    return layout.build_plan(repo_root, version=args.version)


def _build_output(plan: layout.BuildPlan, value: str, *, label: str) -> Path:
    """Resolve a build-scoped output path and prove it stays inside build/release-windows.

    The build helper is the only writer that can name its own output files, so this is the
    single choke point that keeps a mistyped ``--output`` from touching the developer
    ``config.toml``/``cache``/``logs`` or the repository root.
    """

    build_root = layout.ensure_release_root(plan.repo_root, plan.build_root)
    return layout.require_inside(Path(value), build_root, label=label)


def _dist_output(plan: layout.BuildPlan, value: str, *, label: str) -> Path:
    """Resolve a release-tree path and prove it stays inside dist/release-windows."""

    dist_root = layout.ensure_release_root(plan.repo_root, plan.dist_root)
    return layout.require_inside(Path(value), dist_root, label=label)


def _release_tree(plan: layout.BuildPlan, value: str | None, *, label: str = "release tree") -> Path:
    """Resolve the assembled release tree; writes into it stay inside the dist root."""

    if value is None:
        return _dist_output(plan, str(plan.artifact_root), label=label)
    return _dist_output(plan, value, label=label)


def _staging_root(plan: layout.BuildPlan, value: str | None) -> Path:
    """Resolve the PyInstaller staging root; it lives inside the build root."""

    if value is None:
        return _build_output(plan, str(plan.staging_root), label="staging root")
    return _build_output(plan, value, label="staging root")


def _audit_target(plan: layout.BuildPlan, value: str, root_kind: str, *, label: str) -> Path:
    """Validate a read-only audit target.

    Audits never write, but they still must not be pointed at an unrelated in-repository
    tree: either the target lives in the owning release root, or it is an explicit external
    tree (an unpacked ZIP or a CI workspace) that resolves outside the repository.
    """

    target = Path(value)
    root = layout.ensure_release_root(
        plan.repo_root,
        plan.build_root if root_kind == "build" else plan.dist_root,
    )
    if layout.is_within(target, root):
        return layout.require_inside(target, root, label=label)
    return layout.require_external_audit(target, plan.repo_root, label=label)


def command_plan(args: argparse.Namespace) -> int:
    plan = layout.build_plan(_resolve_repo_root(args), version=args.version)
    payload = plan.as_payload()
    if args.output:
        destination = _build_output(plan, args.output, label="build plan output")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"plan: ok version={plan.version} artifact={plan.artifact_name} zip={plan.zip_path.name}")
    return 0


def command_layout_check(args: argparse.Namespace) -> int:
    plan = _load_plan(args)
    layout.validate_repo_layout(plan.repo_root)
    if plan.version != layout.read_project_version(plan.repo_root):
        return _fail("layout_version_mismatch", f"plan version {plan.version} differs from pyproject.toml")
    for target in (plan.build_root, plan.dist_root):
        if target.exists() and layout.ensure_release_root(plan.repo_root, target) != target.resolve(strict=False):
            return _fail("layout_target_unresolved", f"build output target did not resolve to itself: {target}")
    # 计划是全部构建路径的唯一事实来源；调用方（build.ps1）传入它自己的两个根，由这里证明
    # 计划与之一致，而不是让 PowerShell 另行拼装输出路径。
    expected_build = Path(args.expect_build_root) if args.expect_build_root else None
    expected_dist = Path(args.expect_dist_root) if args.expect_dist_root else None
    violations = layout.verify_plan(
        plan,
        expected_build_root=expected_build,
        expected_dist_root=expected_dist,
    )
    if violations:
        return _fail("build_plan_invalid", "; ".join(violations))
    print(
        "layout: ok "
        f"build={plan.build_root.relative_to(plan.repo_root).as_posix()} "
        f"dist={plan.dist_root.relative_to(plan.repo_root).as_posix()}"
    )
    return 0


def command_generate(args: argparse.Namespace) -> int:
    plan = _load_plan(args)
    generated = plan.generated_root
    generated.mkdir(parents=True, exist_ok=True)
    icon = wheels.write_icon(generated / "pdf_reader.ico")
    launcher_version = winver.write_version_info(
        generated / "launcher-version.txt",
        version=plan.version,
        executable_name=layout.LAUNCHER_EXECUTABLE,
    )
    service_version = winver.write_version_info(
        generated / "service-version.txt",
        version=plan.version,
        executable_name=layout.SERVICE_EXECUTABLE,
    )
    print(
        "generate: ok "
        f"icon={icon.relative_to(plan.repo_root).as_posix()} "
        f"launcher_version={launcher_version.relative_to(plan.repo_root).as_posix()} "
        f"service_version={service_version.relative_to(plan.repo_root).as_posix()}"
    )
    return 0


def command_icon(args: argparse.Namespace) -> int:
    """Verify (or rewrite) the versioned release icon in ``packaging/windows/manifests``."""

    plan = _load_plan(args)
    tracked = plan.hooks_root.parent / "manifests" / "pdf_reader.ico"
    rendered = wheels.build_ico()
    if args.write:
        tracked.parent.mkdir(parents=True, exist_ok=True)
        tracked.write_bytes(rendered)
        print(f"icon: ok written={tracked.as_posix()} bytes={len(rendered)}")
        return 0
    if not tracked.is_file():
        return _fail("icon_missing", f"release icon is missing: {tracked}; run 'buildtool icon --write'")
    committed = tracked.read_bytes()
    if committed != rendered:
        return _fail(
            "icon_stale",
            "release icon does not match the generator output; run 'buildtool icon --write' "
            "and commit packaging/windows/manifests/pdf_reader.ico",
        )
    print(f"icon: ok bytes={len(committed)} tracked={tracked.as_posix()}")
    return 0


def command_scaffold(args: argparse.Namespace) -> int:
    plan = _load_plan(args)
    build_root = layout.ensure_release_root(plan.repo_root, plan.build_root)
    dist_root = layout.ensure_release_root(plan.repo_root, plan.dist_root)
    for directory in (
        plan.staging_root,
        plan.wheel_root,
        plan.generated_root,
        plan.spec_scratch,
        plan.build_root / layout.WORK_DIRECTORY_NAME,
    ):
        layout.require_inside(directory, build_root, label="build directory")
        directory.mkdir(parents=True, exist_ok=True)
    dist_root.mkdir(parents=True, exist_ok=True)
    print(f"scaffold: ok build={build_root.relative_to(plan.repo_root).as_posix()}")
    return 0


def _pip(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, "-m", "pip", *arguments]
    return subprocess.run(command, capture_output=True, text=True, check=False)


def command_env_check(args: argparse.Namespace) -> int:
    plan = _load_plan(args)
    expected = lock.parse_runtime_lock(plan.runtime_lock)
    result = _pip(["list", "--format=json", "--disable-pip-version-check", "--no-color"])
    if result.returncode != 0:
        return _fail("pip_list_failed", result.stderr.strip() or "pip list failed")
    try:
        payload = json.loads(result.stdout)
    except ValueError as exc:
        return _fail("pip_list_invalid", f"cannot parse pip list output: {exc}")
    installed = {
        lock.normalize_distribution(item["name"]): str(item["version"])
        for item in payload
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    violations = lock.audit_installed_environment(expected, installed)
    if violations:
        return _fail("build_environment_mismatch", "; ".join(violations))
    if not sys.version.startswith(f"{manifest.PYTHON_MINOR}."):
        return _fail("build_python_unsupported", f"build interpreter must be Python {manifest.PYTHON_MINOR}.x")
    print(f"env-check: ok distributions={len(expected)} python={sys.version.split()[0]}")
    return 0


def command_dist_records(args: argparse.Namespace) -> int:
    plan = _load_plan(args)
    index = modules.collect_installed_distributions()
    payload = {
        "schema": modules.INDEX_SCHEMA,
        "python": sys.version.split()[0],
        "implementation": sys.implementation.name,
        "distributions": [index[name].as_payload() for name in sorted(index)],
    }
    destination = _build_output(plan, args.output, label="distribution index output")
    artifacts.write_json(destination, payload)
    print(f"dist-records: ok distributions={len(index)} output={destination.as_posix()}")
    return 0


def command_wheel_hashes(args: argparse.Namespace) -> int:
    plan = _load_plan(args)
    expected = lock.parse_runtime_lock(plan.runtime_lock)
    # 这里既写入下载的 wheel，也写入 pip 报告，因此按写入语义严格限制在 build 根内。
    wheel_root = (
        _build_output(plan, args.wheel_root, label="wheel root")
        if args.wheel_root
        else _build_output(plan, str(plan.wheel_root), label="wheel root")
    )
    report_path = wheel_root / "pip-report.json"
    if wheel_root.exists() and args.refresh:
        filesystem.remove_tree(wheel_root)
    wheel_root.mkdir(parents=True, exist_ok=True)
    if args.refresh or not list(wheel_root.glob("*.whl")):
        result = _pip(
            [
                "download",
                "--only-binary=:all:",
                "--no-deps",
                "--report",
                str(report_path),
                "--dest",
                str(wheel_root),
                "-r",
                str(plan.runtime_lock),
                "--disable-pip-version-check",
                "--no-color",
            ]
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            return _fail("wheel_download_failed", f"pip could not fetch the locked wheels: {detail}")
    from_directory = lock.records_from_wheel_directory(wheel_root)
    from_report = lock.records_from_pip_report(report_path) if report_path.is_file() else None
    violations = lock.reconcile_wheel_records(expected, from_directory, from_report)
    if violations:
        return _fail("wheel_hash_mismatch", "; ".join(violations))
    destination = (
        _build_output(plan, args.output, label="wheel hash output")
        if args.output
        else _build_output(plan, str(plan.wheel_hashes_path), label="wheel hash output")
    )
    artifacts.write_json(
        destination,
        {
            "schema": 1,
            "runtime_lock": plan.runtime_lock.relative_to(plan.repo_root).as_posix(),
            "runtime_lock_sha256": lock.sha256_file(plan.runtime_lock),
            "packages": [from_directory[name].as_payload() for name in sorted(from_directory)],
        },
    )
    print(f"wheel-hashes: ok packages={len(from_directory)} output={destination.as_posix()}")
    return 0


def command_manifest(args: argparse.Namespace) -> int:
    plan = _load_plan(args)
    # manifest 写入 app/runtime-manifest.json，因此发行树按写入语义限制在 dist 根内。
    artifact = _release_tree(plan, args.release_tree, label="release tree")
    expected = lock.parse_runtime_lock(plan.runtime_lock)
    wheel_records = manifest.load_wheel_records(Path(args.wheel_hashes))
    installed = manifest.load_distribution_index(Path(args.distribution_index))
    payload, violations = manifest.build_manifest(
        artifact_root=artifact,
        version=plan.version,
        source_commit=args.commit,
        python_version=args.python_version or sys.version.split()[0],
        python_implementation=args.python_implementation or sys.implementation.name,
        expected_lock=expected,
        wheels=wheel_records,
        installed=installed,
        lock_sha256=lock.sha256_file(plan.runtime_lock),
    )
    if args.violations_output:
        body = "\n".join(violations) + ("\n" if violations else "")
        _build_output(plan, args.violations_output, label="manifest violation report").write_text(
            body, encoding="utf-8"
        )
    if violations:
        return _fail("runtime_manifest_invalid", "; ".join(violations))
    destination = artifact / layout.APP_DIRECTORY / manifest.RUNTIME_MANIFEST_NAME
    manifest.write_runtime_manifest(destination, payload)
    coverage = payload["coverage"]
    collected = sum(1 for item in coverage if item["status"] == "collected")
    excluded = sum(1 for item in coverage if item["status"] == "excluded")
    print(
        "manifest: ok "
        f"packages={len(payload['packages'])} collected={collected} excluded={excluded} "
        f"output={destination.as_posix()}"
    )
    return 0


def command_verify_tree(args: argparse.Namespace) -> int:
    plan = _load_plan(args)
    # 只读审计：目标可以位于 dist 根内，也可以是完全在仓库之外的外部树（解包 ZIP、CI
    # 工作区）；仓库内其它路径一律拒绝，避免把开发目录当成发行物审计。
    artifact = _audit_target(plan, args.release_tree or str(plan.artifact_root), "dist", label="release tree")
    violations = artifacts.verify_tree(artifact)
    if violations:
        return _fail("artifact_tree_invalid", "; ".join(violations))
    entries, total = artifacts.inventory(artifact)
    print(f"verify-tree: ok files={len(entries)} bytes={total}")
    return 0


def command_verify_bundles(args: argparse.Namespace) -> int:
    plan = _load_plan(args)
    staging = _audit_target(plan, args.staging_root or str(plan.staging_root), "build", label="staging root")
    violations = assemble_module.verify_bundles(staging)
    if violations:
        return _fail("pyinstaller_bundle_invalid", "; ".join(violations))
    print(f"verify-bundles: ok staging={staging.as_posix()}")
    return 0


def command_assemble(args: argparse.Namespace) -> int:
    plan = _load_plan(args)
    # 读取 staging、写入发行树：读按 build 根、写按 dist 根分别校验。
    staging = _staging_root(plan, args.staging_root)
    artifact = _release_tree(plan, args.release_tree, label="release tree")
    violations = assemble_module.verify_bundles(staging)
    if violations:
        return _fail("pyinstaller_bundle_invalid", "; ".join(violations))
    notes = assemble_module.assemble(staging, artifact, plan.repo_root)
    for note in notes:
        print(f"assemble: {note}")
    print(f"assemble: ok artifact={artifact.as_posix()}")
    return 0


def command_dependencies(args: argparse.Namespace) -> int:
    plan = _load_plan(args)
    artifact = _release_tree(plan, args.release_tree, label="release tree")
    wheels = manifest.load_wheel_records(Path(args.wheel_hashes))
    rows, problems = deps.collect_dependency_rows(wheels)
    exclusions = dict(manifest.DEFAULT_EXCLUSIONS)
    body = deps.render_dependencies(
        rows,
        version=plan.version,
        source_commit=args.commit,
        python_version=args.python_version or sys.version.split()[0],
        lock_relative_path=plan.runtime_lock.relative_to(plan.repo_root).as_posix(),
        lock_sha256=lock.sha256_file(plan.runtime_lock),
        exclusions=exclusions,
        generated_at=args.generated_at or _utc_now(),
    )
    destination = deps.write_dependencies(artifact / layout.APP_DIRECTORY / "licenses" / deps.DEPENDENCIES_NAME, body)
    if problems:
        return _fail("dependency_manifest_invalid", "; ".join(problems))
    print(f"dependencies: ok distributions={len(rows)} output={destination.as_posix()}")
    return 0


def command_finalize(args: argparse.Namespace) -> int:
    plan = _load_plan(args)
    # finalize 写入 release-manifest.json 与 dist 根内的文件清单，两处都按写入语义校验。
    artifact = _release_tree(plan, args.release_tree, label="release tree")
    violations = artifacts.verify_tree(artifact)
    if violations:
        return _fail("artifact_tree_invalid", "; ".join(violations))
    # 清单本身也是产物，无法包含自己的摘要；把它记为有意排除项，而不是让清单静默地少
    # 一个文件。
    self_manifest = f"{layout.APP_DIRECTORY}/{manifest.BUILD_MANIFEST_NAME}"
    all_entries, total = artifacts.inventory(artifact)
    entries = [entry for entry in all_entries if entry.path != self_manifest]
    inventory_path = _dist_output(plan, str(plan.filelist_path), label="release file list")
    artifacts.write_inventory(inventory_path, entries)
    summary = {
        "schema_version": manifest.SCHEMA_VERSION,
        "product": layout.PRODUCT_NAME,
        "app_version": plan.version,
        "artifact_name": plan.artifact_name,
        "source_commit": args.commit,
        "source_lock": manifest.SOURCE_LOCK,
        "source_lock_sha256": lock.sha256_file(plan.runtime_lock),
        "python_version": args.python_version or sys.version.split()[0],
        "python_implementation": args.python_implementation or sys.implementation.name,
        "file_count": len(entries),
        "total_bytes": total,
        "excluded_from_inventory": {self_manifest: "self-reference: the inventory cannot contain its own file digest"},
        "files": [{"path": entry.path, "size": entry.size, "sha256": entry.sha256} for entry in entries],
    }
    artifacts.write_json(artifact / layout.APP_DIRECTORY / manifest.BUILD_MANIFEST_NAME, summary)
    print(f"finalize: ok files={len(entries)} bytes={total} inventory={inventory_path.name}")
    return 0


def command_package(args: argparse.Namespace) -> int:
    plan = _load_plan(args)
    artifact = _release_tree(plan, args.release_tree, label="release tree")
    zip_path = _dist_output(plan, str(plan.zip_path), label="release ZIP")
    artifacts.write_zip(artifact, zip_path, plan.artifact_name)
    checksum_target = _dist_output(plan, str(plan.checksum_path), label="release checksum")
    digest, checksum_path = artifacts.write_zip_checksum(zip_path, checksum_target)
    print(f"package: ok zip={zip_path.name} sha256={digest} checksum={checksum_path.name}")
    return 0


def command_snapshot(args: argparse.Namespace) -> int:
    plan = _load_plan(args)
    targets = tuple(args.targets) if args.targets else snapshot.DEFAULT_TARGETS
    payload = snapshot.build_snapshot(plan.repo_root, targets)
    destination = snapshot.write_snapshot(_build_output(plan, args.output, label="snapshot output"), payload)
    entries = sum(len(target["entries"]) for target in payload["targets"])
    print(f"snapshot: ok targets={len(payload['targets'])} entries={entries} output={destination.as_posix()}")
    return 0


def command_snapshot_diff(args: argparse.Namespace) -> int:
    plan = _load_plan(args)
    # 快照是构建期开发态证据，读写都只允许发生在 build 根内。
    before = snapshot.read_snapshot(_build_output(plan, args.before, label="before snapshot"))
    after = snapshot.read_snapshot(_build_output(plan, args.after, label="after snapshot"))
    differences = snapshot.diff_snapshots(before, after)
    if differences:
        for line in differences[:50]:
            print(line, file=sys.stderr)
        return _fail("developer_state_changed", f"{len(differences)} difference(s) after the build")
    print(f"snapshot-diff: ok targets={len(before.get('targets', []))} differences=0")
    return 0


def command_clean(args: argparse.Namespace) -> int:
    plan = _load_plan(args)
    targets = [layout.ensure_release_root(plan.repo_root, plan.build_root)]
    if args.include_dist:
        targets.append(layout.ensure_release_root(plan.repo_root, plan.dist_root))
    removed: list[str] = []
    for target in targets:
        if not target.exists():
            continue
        if args.dry_run:
            removed.append(f"{target.as_posix()}(dry-run)")
            continue
        filesystem.remove_tree(target)
        removed.append(target.as_posix())
    print(f"clean: ok removed={','.join(removed) if removed else 'nothing-to-remove'}")
    return 0


def command_check_wheels(args: argparse.Namespace) -> int:
    plan = _load_plan(args)
    # 只读校验：building 目录内的 wheel 集合，或仓库外的显式 wheel 目录。
    provided = _audit_target(plan, args.wheel, "build", label="wheel")
    directory = provided if provided.is_dir() else provided.parent
    records = lock.records_from_wheel_directory(directory)
    expected = lock.parse_runtime_lock(plan.runtime_lock)
    violations = lock.reconcile_wheel_records(expected, records)
    if violations:
        return _fail("wheel_hash_mismatch", "; ".join(violations))
    print(f"check-wheels: ok packages={len(records)}")
    return 0


def _write_stub(path: Path, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"PDF Reader build self-check placeholder\n")
    if executable and os.name != "nt":
        path.chmod(0o755)


def _synthetic_wheel_records(expected: dict[str, str]) -> dict[str, lock.WheelRecord]:
    records: dict[str, lock.WheelRecord] = {}
    for name in sorted(expected):
        digest = lock.sha256_text(f"self-check:{name}:{expected[name]}")
        records[name] = lock.WheelRecord(
            name=name,
            version=expected[name],
            wheel_sha256=digest,
            wheel_file=f"{name.replace('-', '_')}-{expected[name]}-py3-none-any.whl",
        )
    return records


def command_self_check(args: argparse.Namespace) -> int:
    """Prove the artifact contract using the local environment, without PyInstaller.

    A real onedir build only exists on Windows, but the manifest schema, the policy
    cross-check and the packaging pipeline do not need Windows to be verified: this
    command builds a synthetic staging tree in a throw-away directory outside the
    repository and then runs the same commands the real build runs (bundle verification,
    assembly, dependency inventory, runtime manifest, both policies, tree verification
    and packaging).
    """

    plan = _load_plan(args)
    repo_root = plan.repo_root
    sys.path.insert(0, str(repo_root / "packaging" / "windows"))
    import importlib

    runtime_policy = importlib.import_module("runtime_policy")
    data_policy = importlib.import_module("data_policy")

    expected = lock.parse_runtime_lock(plan.runtime_lock)
    exclusions = dict(manifest.DEFAULT_EXCLUSIONS)
    installed = modules.collect_installed_distributions()
    missing = sorted(set(expected) - set(installed))
    if missing:
        return _fail("self_check_environment_incomplete", f"local environment misses: {', '.join(missing)}")
    unlocked = sorted(set(installed) - set(expected))

    workspace = (
        Path(args.workspace)
        if args.workspace
        else Path(
            os.environ.get(
                "PDF_READER_SELF_CHECK_DIR",
                str(Path(os.environ.get("TMPDIR", Path(os.environ.get("TEMP", "/tmp")))) / "pdf-reader-self-check"),
            )
        )
    )
    if workspace.exists():
        shutil.rmtree(workspace)
    staging = workspace / "staging"
    artifact = workspace / "dist" / layout.PRODUCT_NAME
    _write_stub(staging / "launcher" / layout.LAUNCHER_EXECUTABLE, executable=True)
    _write_stub(staging / "launcher" / layout.INTERNAL_DIRECTORY / "python312.dll")
    service_bundle = staging / "service"
    _write_stub(service_bundle / layout.SERVICE_EXECUTABLE, executable=True)
    _write_stub(service_bundle / layout.INTERNAL_DIRECTORY / "python312.dll")
    for upstream in ("pdf2zh_next", "babeldoc", "pymupdf", "onnxruntime", "cv2", "tiktoken_ext"):
        (service_bundle / layout.INTERNAL_DIRECTORY / upstream).mkdir(parents=True, exist_ok=True)
        _write_stub(service_bundle / layout.INTERNAL_DIRECTORY / upstream / "__init__.py")

    problems: list[str] = list(assemble_module.verify_bundles(staging))
    if problems:
        for problem in problems:
            print(f"self-check problem: {problem}", file=sys.stderr)
        return _fail("self_check_failed", f"{len(problems)} problem(s) reported")
    assemble_module.assemble(staging, artifact, repo_root)

    # ``_internal`` 里逐条放入被收集发行版的顶层模块与元数据目录占位，用于验证覆盖检查。
    internal = artifact / layout.APP_DIRECTORY / layout.INTERNAL_DIRECTORY
    for name in sorted(set(expected) - set(exclusions)):
        info = installed[name]
        for module in info.top_level or ():
            target = internal / module
            if not target.exists():
                target.mkdir(parents=True, exist_ok=True)
                (target / "__init__.py").write_text("", encoding="utf-8")
        metadata = internal / f"{name}-{info.version}.dist-info"
        metadata.mkdir(parents=True, exist_ok=True)
        (metadata / "METADATA").write_text(f"Name: {name}\nVersion: {info.version}\n", encoding="utf-8")

    wheels = _synthetic_wheel_records(expected)
    rows, dependency_problems = deps.collect_dependency_rows(wheels)
    problems.extend(dependency_problems)
    deps.write_dependencies(
        artifact / layout.APP_DIRECTORY / "licenses" / deps.DEPENDENCIES_NAME,
        deps.render_dependencies(
            rows,
            version=plan.version,
            source_commit=args.commit or "0" * 40,
            python_version=args.python_version or sys.version.split()[0],
            lock_relative_path=plan.runtime_lock.relative_to(repo_root).as_posix(),
            lock_sha256=lock.sha256_file(plan.runtime_lock),
            exclusions=exclusions,
            generated_at="self-check",
        ),
    )
    payload, violations = manifest.build_manifest(
        artifact_root=artifact,
        version=plan.version,
        source_commit=args.commit or "0" * 40,
        python_version=args.python_version or sys.version.split()[0],
        python_implementation=args.python_implementation or sys.implementation.name,
        expected_lock=expected,
        wheels=wheels,
        installed=installed,
        lock_sha256=lock.sha256_file(plan.runtime_lock),
        created_at="self-check",
        exclusions=exclusions,
    )
    problems.extend(violations)
    manifest_path = artifact / layout.APP_DIRECTORY / manifest.RUNTIME_MANIFEST_NAME
    manifest.write_runtime_manifest(manifest_path, payload)
    entries, total = artifacts.inventory(artifact)
    summary = {
        "schema_version": manifest.SCHEMA_VERSION,
        "product": layout.PRODUCT_NAME,
        "app_version": plan.version,
        "artifact_name": plan.artifact_name,
        "source_commit": args.commit or "0" * 40,
        "source_lock": manifest.SOURCE_LOCK,
        "source_lock_sha256": lock.sha256_file(plan.runtime_lock),
        "python_version": args.python_version or sys.version.split()[0],
        "python_implementation": args.python_implementation or sys.implementation.name,
        "file_count": len(entries),
        "total_bytes": total,
        "files": [{"path": entry.path, "size": entry.size, "sha256": entry.sha256} for entry in entries],
    }
    artifacts.write_json(artifact / layout.APP_DIRECTORY / manifest.BUILD_MANIFEST_NAME, summary)
    problems.extend(runtime_policy.audit_runtime_manifest(repo_root, artifact))
    problems.extend(runtime_policy.audit_artifact_tree(repo_root, artifact))
    problems.extend(data_policy.audit_artifact_tree(artifact))

    # 自检不绑定真实提交：全零 commit 只用于验证 schema 形状，因此过滤对应的单条违规；
    # 真实构建必须在 build.ps1 里传入 HEAD，缺提交会在 manifest 阶段直接失败。
    if not args.commit:
        problems = [problem for problem in problems if "source_commit" not in problem]
    tree_violations = artifacts.verify_tree(artifact)
    problems.extend(tree_violations)
    # 自检的工作区在仓库之外，因此清单/ZIP/校验和都写在临时工作区里（名称沿用计划里的
    # 规范产物名），绝不落到真实仓库的 dist/release-windows。
    self_dist = workspace / "dist"
    artifacts.write_inventory(self_dist / f"{plan.artifact_name}{artifacts.FILELIST_SUFFIX}", entries)
    zip_path = artifacts.write_zip(artifact, self_dist / plan.zip_path.name, plan.artifact_name)
    digest, _ = artifacts.write_zip_checksum(zip_path, self_dist / plan.checksum_path.name)

    if problems:
        for problem in problems[:40]:
            print(f"self-check problem: {problem}", file=sys.stderr)
        return _fail("self_check_failed", f"{len(problems)} problem(s) reported")
    print(
        "self-check: ok "
        f"files={len(entries)} bytes={total} zip_sha256={digest[:16]} "
        f"packages={len(payload['packages'])} unlocked_in_env={len(unlocked)} workspace={workspace.as_posix()}"
    )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="buildtool", description="P2-01 Windows release build helper")
    parser.add_argument("--repo-root", default=None, help="repository root (defaults to autodetect)")
    parser.add_argument("--plan-file", default=None, help="JSON build plan written by the plan command")
    parser.add_argument("--version", default=None, help="override the project version (defaults to pyproject.toml)")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan", help="resolve and print the build plan")
    plan_parser.add_argument("--output", default=None)
    plan_parser.set_defaults(handler=command_plan)

    layout_parser = subparsers.add_parser("layout-check", help="validate repo and build boundaries")
    layout_parser.add_argument("--expect-build-root", default=None, help="the caller's canonical build/release-windows")
    layout_parser.add_argument("--expect-dist-root", default=None, help="the caller's canonical dist/release-windows")
    layout_parser.set_defaults(handler=command_layout_check)

    generate_parser = subparsers.add_parser("generate", help="render icons and version resources")
    generate_parser.set_defaults(handler=command_generate)

    icon_parser = subparsers.add_parser("icon", help="verify or rewrite the versioned release icon")
    icon_parser.add_argument("--write", action="store_true")
    icon_parser.set_defaults(handler=command_icon)

    scaffold_parser = subparsers.add_parser("scaffold", help="create staging tree and build directories")
    scaffold_parser.set_defaults(handler=command_scaffold)

    env_parser = subparsers.add_parser("env-check", help="verify the build venv against the runtime lock")
    env_parser.set_defaults(handler=command_env_check)

    dist_parser = subparsers.add_parser("dist-records", help="write the installed-distribution index")
    dist_parser.add_argument("--output", required=True)
    dist_parser.set_defaults(handler=command_dist_records)

    wheel_parser = subparsers.add_parser("wheel-hashes", help="capture wheel SHA-256 for the runtime lock")
    wheel_parser.add_argument("--output", default=None)
    wheel_parser.add_argument("--wheel-root", default=None)
    wheel_parser.add_argument("--refresh", action="store_true")
    wheel_parser.set_defaults(handler=command_wheel_hashes)

    manifest_parser = subparsers.add_parser("manifest", help="write app/runtime-manifest.json")
    # 组装好的发行目录默认取构建计划里的 dist/release-windows/PDF Reader；显式覆盖时
    # 仍会被解析并验证必须位于该 dist 根内。
    manifest_parser.add_argument("--release-tree", default=None)
    manifest_parser.add_argument("--wheel-hashes", required=True)
    manifest_parser.add_argument("--distribution-index", required=True)
    manifest_parser.add_argument("--commit", required=True)
    manifest_parser.add_argument("--python-version", default=None)
    manifest_parser.add_argument("--python-implementation", default=None)
    manifest_parser.add_argument("--violations-output", default=None)
    manifest_parser.set_defaults(handler=command_manifest)

    verify_parser = subparsers.add_parser("verify-tree", help="verify the assembled artifact tree")
    verify_parser.add_argument("--release-tree", default=None)
    verify_parser.set_defaults(handler=command_verify_tree)

    bundles_parser = subparsers.add_parser("verify-bundles", help="verify the two PyInstaller bundles")
    bundles_parser.add_argument("--staging-root", default=None)
    bundles_parser.set_defaults(handler=command_verify_bundles)

    assemble_parser = subparsers.add_parser("assemble", help="assemble dist/release-windows/PDF Reader")
    assemble_parser.add_argument("--staging-root", default=None)
    assemble_parser.add_argument("--release-tree", default=None)
    assemble_parser.set_defaults(handler=command_assemble)

    dependencies_parser = subparsers.add_parser("dependencies", help="write app/licenses/DEPENDENCIES.txt")
    dependencies_parser.add_argument("--release-tree", default=None)
    dependencies_parser.add_argument("--wheel-hashes", required=True)
    dependencies_parser.add_argument("--commit", required=True)
    dependencies_parser.add_argument("--python-version", default=None)
    dependencies_parser.add_argument("--generated-at", default=None)
    dependencies_parser.set_defaults(handler=command_dependencies)

    finalize_parser = subparsers.add_parser("finalize", help="write build manifest and file inventory")
    finalize_parser.add_argument("--release-tree", default=None)
    finalize_parser.add_argument("--commit", required=True)
    finalize_parser.add_argument("--python-version", default=None)
    finalize_parser.add_argument("--python-implementation", default=None)
    finalize_parser.set_defaults(handler=command_finalize)

    package_parser = subparsers.add_parser("package", help="write the release ZIP and SHA-256")
    package_parser.add_argument("--release-tree", default=None)
    package_parser.set_defaults(handler=command_package)

    snapshot_parser = subparsers.add_parser("snapshot", help="snapshot developer state")
    snapshot_parser.add_argument("--output", required=True)
    snapshot_parser.add_argument("--targets", nargs="*", default=None)
    snapshot_parser.set_defaults(handler=command_snapshot)

    diff_parser = subparsers.add_parser("snapshot-diff", help="compare two developer-state snapshots")
    diff_parser.add_argument("--before", required=True)
    diff_parser.add_argument("--after", required=True)
    diff_parser.set_defaults(handler=command_snapshot_diff)

    clean_parser = subparsers.add_parser("clean", help="remove release build output (guarded)")
    clean_parser.add_argument("--include-dist", action="store_true")
    clean_parser.add_argument("--dry-run", action="store_true")
    clean_parser.set_defaults(handler=command_clean)

    check_parser = subparsers.add_parser("check-wheels", help="re-verify captured wheel hashes")
    check_parser.add_argument("--wheel", required=True, help="wheel file or directory")
    check_parser.set_defaults(handler=command_check_wheels)

    self_parser = subparsers.add_parser("self-check", help="verify the artifact contract without PyInstaller")
    self_parser.add_argument("--workspace", default=None)
    self_parser.add_argument("--commit", default=None)
    self_parser.add_argument("--python-version", default=None)
    self_parser.add_argument("--python-implementation", default=None)
    self_parser.set_defaults(handler=command_self_check)

    return parser


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_streams()
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except layout.BuildLayoutError as exc:
        return _fail("build_layout_invalid", str(exc))
    except (lock.LockError, manifest.ManifestError, artifacts.ArtifactError, snapshot.SnapshotError) as exc:
        return _fail("build_contract_invalid", str(exc))
    except OSError as exc:
        return _fail("build_io_failed", str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
