"""Repository, build and release-output path resolution for the P2-01 build.

Two rules drive this module:

1. Build-scoped state (the dedicated venv, PyInstaller work path, caches) lives
   under ``build/release-windows`` and final artifacts under
   ``dist/release-windows``; the repository ``venv/`` is never a build target.
2. Anything destructive (``clean``) resolves its target first and then verifies the
   resolved physical path *is exactly* one of the two release output directories,
   so a symlink, junction, ``..`` segment, environment override or workspace root can
   never widen the deletion scope.
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

BUILD_DIRECTORY = Path("build/release-windows")
DIST_DIRECTORY = Path("dist/release-windows")

VENV_DIRECTORY_NAME = "venv"
WORK_DIRECTORY_NAME = "pyinstaller"
STAGING_DIRECTORY_NAME = "staging"
WHEEL_DIRECTORY_NAME = "wheels"
SPEC_DIRECTORY_NAME = "spec"
GENERATED_DIRECTORY_NAME = "generated"
PLAN_FILE_NAME = "build-plan.json"
SNAPSHOT_BEFORE_NAME = "snapshot-before.json"
SNAPSHOT_AFTER_NAME = "snapshot-after.json"
SERVICE_WORK_DIRECTORY_NAME = "service"
LAUNCHER_WORK_DIRECTORY_NAME = "launcher"
PYINSTALLER_CACHE_DIRECTORY_NAME = "pyinstaller-cache"
ICON_FILE_NAME = "pdf_reader.ico"
LAUNCHER_VERSION_FILE_NAME = "version-info-launcher.txt"
SERVICE_VERSION_FILE_NAME = "version-info-service.txt"
WHEEL_HASHES_FILE_NAME = "wheel-hashes.json"
DISTRIBUTION_INDEX_FILE_NAME = "distribution-index.json"

LAUNCHER_EXECUTABLE = "PDF Reader.exe"
SERVICE_EXECUTABLE = "PDF Reader Service.exe"
APP_DIRECTORY = "app"
INTERNAL_DIRECTORY = "_internal"

PROJECT_NAME = "PDF-Reader"
PRODUCT_NAME = "PDF Reader"
RELEASE_CHANNEL = "windows-x64-portable"

_VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[.-][0-9A-Za-z.]+)?$")


class BuildLayoutError(RuntimeError):
    """A build-scoped path failed validation; callers must abort, never guess."""


@dataclass(frozen=True, slots=True)
class BuildPlan:
    """One build's resolved inputs and outputs (no side effects).

    This is the single source of truth for build paths: ``build.ps1`` reads the JSON
    written by ``plan`` and uses these values verbatim, so PowerShell never composes an
    output path on its own.
    """

    repo_root: Path
    version: str
    build_root: Path
    dist_root: Path
    plan_path: Path
    snapshot_before: Path
    snapshot_after: Path
    venv_root: Path
    work_root: Path
    service_work_root: Path
    launcher_work_root: Path
    pyinstaller_cache_root: Path
    staging_root: Path
    wheel_root: Path
    wheel_hashes_path: Path
    spec_scratch: Path
    generated_root: Path
    generated_icon: Path
    launcher_version_file: Path
    service_version_file: Path
    distribution_index_path: Path
    artifact_root: Path
    filelist_path: Path
    zip_path: Path
    checksum_path: Path
    artifact_name: str
    # ZIP 名只以计划里的绝对路径（zip_path）形式存在：计划中不允许出现两个都叫 “*.zip” 的
    # 取值，否则调用方无法判断哪个才是真正的产物名。
    runtime_lock: Path
    launcher_spec: Path
    service_spec: Path
    hooks_root: Path

    def as_payload(self) -> dict[str, str]:
        return {name: str(getattr(self, name)) for name in BUILD_PLAN_FIELDS}

    def field(self, name: str) -> Path:
        value = getattr(self, name)
        if not isinstance(value, Path):
            raise BuildLayoutError(f"build plan field {name} is not a path")
        return value


def read_project_version(repo_root: Path) -> str:
    """Read the single product version from ``pyproject.toml`` (no second source)."""

    try:
        with (repo_root / "pyproject.toml").open("rb") as handle:
            payload = tomllib.load(handle)
        version = payload["project"]["version"]
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError) as exc:
        raise BuildLayoutError(f"cannot read the project version from pyproject.toml: {exc}") from exc
    if not isinstance(version, str) or not _VERSION_PATTERN.fullmatch(version):
        raise BuildLayoutError(f"pyproject.toml project.version is not a release version: {version!r}")
    return version


def find_repo_root(start: Path | None = None) -> Path:
    """Locate the repository root by its build markers, never by the current directory."""

    candidates = []
    if start is not None:
        candidates.append(Path(start))
    candidates.extend(Path(__file__).resolve().parents)
    for candidate in candidates:
        resolved = candidate.resolve(strict=False)
        if (resolved / "pyproject.toml").is_file() and (resolved / "packaging/windows/runtime_policy.py").is_file():
            return resolved
    raise BuildLayoutError("cannot locate the repository root from the build helper location")


def validate_repo_layout(repo_root: Path) -> None:
    """Fail before any build step when an input or a build boundary is missing."""

    required = (
        "pyproject.toml",
        "requirements.lock",
        "src/pdf_reader/portable_launcher.py",
        "src/pdf_reader/portable_service.py",
        "static/app.js",
        "static/style.css",
        "templates/index.html",
        "config.example.toml",
        "packaging/windows/runtime-requirements.lock",
        "packaging/windows/runtime_policy.py",
        "packaging/windows/data_policy.py",
    )
    missing = [name for name in required if not (repo_root / name).exists()]
    if missing:
        raise BuildLayoutError(f"repository is missing build inputs: {', '.join(missing)}")

    for ignored in (BUILD_DIRECTORY, DIST_DIRECTORY):
        path = repo_root / ignored
        if path.is_symlink():
            raise BuildLayoutError(f"build output path must not be a link: {ignored.as_posix()}")

    gitignore = repo_root / ".gitignore"
    try:
        lines = {line.strip() for line in gitignore.read_text(encoding="utf-8").splitlines()}
    except OSError as exc:  # pragma: no cover - only reachable on a damaged checkout
        raise BuildLayoutError(f"cannot read .gitignore: {exc}") from exc
    if not {"build/", "dist/"} <= lines:
        raise BuildLayoutError("build/ and dist/ must both stay git-ignored for release output")


def build_plan(repo_root: Path, *, version: str | None = None) -> BuildPlan:
    """Resolve every build path from the repository root; creates nothing."""

    root = Path(repo_root).resolve(strict=False)
    validate_repo_layout(root)
    resolved_version = read_project_version(root) if version is None else version
    build_root = root / BUILD_DIRECTORY
    dist_root = root / DIST_DIRECTORY
    venv_root = build_root / VENV_DIRECTORY_NAME
    work_root = build_root / WORK_DIRECTORY_NAME
    staging_root = build_root / STAGING_DIRECTORY_NAME
    wheel_root = build_root / WHEEL_DIRECTORY_NAME
    spec_scratch = build_root / SPEC_DIRECTORY_NAME
    generated_root = build_root / GENERATED_DIRECTORY_NAME
    artifact_name = f"{PROJECT_NAME}-{resolved_version}-{RELEASE_CHANNEL}"
    zip_name = f"{artifact_name}.zip"
    return BuildPlan(
        repo_root=root,
        version=resolved_version,
        build_root=build_root,
        dist_root=dist_root,
        plan_path=build_root / PLAN_FILE_NAME,
        snapshot_before=build_root / SNAPSHOT_BEFORE_NAME,
        snapshot_after=build_root / SNAPSHOT_AFTER_NAME,
        venv_root=venv_root,
        work_root=work_root,
        service_work_root=work_root / SERVICE_WORK_DIRECTORY_NAME,
        launcher_work_root=work_root / LAUNCHER_WORK_DIRECTORY_NAME,
        pyinstaller_cache_root=build_root / PYINSTALLER_CACHE_DIRECTORY_NAME,
        staging_root=staging_root,
        wheel_root=wheel_root,
        wheel_hashes_path=generated_root / WHEEL_HASHES_FILE_NAME,
        spec_scratch=spec_scratch,
        generated_root=generated_root,
        generated_icon=generated_root / ICON_FILE_NAME,
        launcher_version_file=generated_root / LAUNCHER_VERSION_FILE_NAME,
        service_version_file=generated_root / SERVICE_VERSION_FILE_NAME,
        distribution_index_path=generated_root / DISTRIBUTION_INDEX_FILE_NAME,
        artifact_root=dist_root / PRODUCT_NAME,
        filelist_path=dist_root / f"{artifact_name}.files.sha256",
        zip_path=dist_root / zip_name,
        checksum_path=dist_root / f"{zip_name}.sha256",
        artifact_name=artifact_name,
        runtime_lock=root / "packaging/windows/runtime-requirements.lock",
        launcher_spec=root / "packaging/windows/pdf_reader.spec",
        service_spec=root / "packaging/windows/pdf_reader_service.spec",
        hooks_root=root / "packaging/windows/hooks",
    )


def plan_from_payload(payload: dict[str, str]) -> BuildPlan:
    """Rebuild a plan from the JSON written by ``plan`` so PowerShell never guesses paths."""

    required = tuple(BuildPlan.__dataclass_fields__)  # type: ignore[attr-defined]
    missing = [name for name in required if name not in payload]
    if missing:
        raise BuildLayoutError(f"build plan is incomplete: {', '.join(missing)}")
    values: dict[str, object] = {}
    for name in required:
        raw = payload[name]
        if not isinstance(raw, str):
            raise BuildLayoutError(f"build plan field {name} must be a string")
        values[name] = raw if name in {"version", "artifact_name"} else Path(raw)
    return BuildPlan(**values)  # type: ignore[arg-type]


# 计划字段分组决定每个路径的读写边界：构建目录内的中间产物只能写入 build 根，发行物只能
# 写入 dist 根，输入只能从仓库内读取。分组是唯一事实来源，PowerShell 与 CLI 都按它校验。
BUILD_ROOT_FIELDS: tuple[str, ...] = (
    "venv_root",
    "work_root",
    "staging_root",
    "wheel_root",
    "spec_scratch",
    "generated_root",
)
BUILD_TREE_FIELDS: tuple[str, ...] = (
    "plan_path",
    "snapshot_before",
    "snapshot_after",
    "service_work_root",
    "launcher_work_root",
    "pyinstaller_cache_root",
    "wheel_hashes_path",
    "generated_icon",
    "launcher_version_file",
    "service_version_file",
    "distribution_index_path",
)
DIST_TREE_FIELDS: tuple[str, ...] = ("artifact_root", "filelist_path", "zip_path", "checksum_path")
REPOSITORY_INPUT_FIELDS: tuple[str, ...] = ("runtime_lock", "launcher_spec", "service_spec", "hooks_root")
BUILD_PLAN_FIELDS: tuple[str, ...] = (
    "repo_root",
    "version",
    "build_root",
    "dist_root",
    *BUILD_ROOT_FIELDS,
    *BUILD_TREE_FIELDS,
    *DIST_TREE_FIELDS,
    "artifact_name",
    *REPOSITORY_INPUT_FIELDS,
)


def _is_linkish(path: Path) -> bool:
    """True for a symbolic link, a Windows junction, or any other reparse point."""

    if path.is_symlink():
        return True
    if os.name == "nt":
        try:
            return path.is_junction()
        except (AttributeError, OSError):
            return False
    return False


def ensure_no_links(path: Path, root: Path, *, label: str) -> Path:
    """Reject ``path`` when any component between ``root`` and it is a link.

    A link inside a release root could redirect a write outside it (or make a read audit
    inspect a different tree than the caller named), so the whole chain is checked, not
    only the leaf.
    """

    resolved_root = Path(root).resolve(strict=False)
    candidate = Path(os.path.abspath(path))
    chain: list[Path] = []
    for ancestor in [candidate, *candidate.parents]:
        chain.append(ancestor)
        if _same_path(ancestor, resolved_root):
            break
    else:
        raise BuildLayoutError(f"{label} is not inside {resolved_root}: {candidate}")
    for component in reversed(chain):
        if not (component.exists() or component.is_symlink()):
            continue
        if _is_linkish(component):
            raise BuildLayoutError(f"{label} passes through a link: {component}")
    return candidate


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))


def same_path(left: Path, right: Path) -> bool:
    """Public form of the normalized comparison used by every boundary check."""

    return _same_path(left, right)


def ensure_release_root(repo_root: Path, candidate: Path) -> Path:
    """Resolve a deletion target and prove it is exactly one release output root.

    The candidate must be this build's own ``build/release-windows`` or
    ``dist/release-windows``.  Anything else -- the repository root, ``venv/``, a
    symlink or junction pointing elsewhere, a parent directory, or a path that merely
    shares a name prefix -- is rejected so ``clean`` can never widen its scope.
    """

    root = Path(repo_root).resolve(strict=False)
    allowed = [root / BUILD_DIRECTORY, root / DIST_DIRECTORY]
    provided = Path(candidate)
    if not provided.is_absolute():
        provided = root / provided
    resolved = provided.resolve(strict=False)
    for target in allowed:
        if _same_path(resolved, target):
            if not root.is_dir():
                raise BuildLayoutError(f"repository root is not a directory: {root}")
            return resolved
    raise BuildLayoutError(
        f"refusing to operate on {resolved}: only build/release-windows and dist/release-windows are removable"
    )


def require_inside(path: Path, root: Path, *, label: str) -> Path:
    """Resolve ``path`` and require it to stay strictly inside a validated root.

    The comparison is component-wise (a separator must follow the root), so a sibling
    that merely shares a name prefix -- ``release-windows-typo`` next to
    ``release-windows`` -- is rejected rather than mistaken for the root.  Link and
    junction components between the root and the target are rejected too.
    """

    resolved_root = Path(root).resolve(strict=False)
    resolved = Path(path).resolve(strict=False)
    if not _is_strictly_inside(resolved, resolved_root):
        raise BuildLayoutError(f"{label} escapes {resolved_root}: {resolved}")
    if _same_path(resolved, resolved_root):
        raise BuildLayoutError(f"{label} must be inside {resolved_root}, not the root itself")
    ensure_no_links(resolved, resolved_root, label=label)
    return resolved


def _is_strictly_inside(candidate: Path, root: Path) -> bool:
    """Component-wise containment test that cannot be fooled by name prefixes."""

    root_text = os.path.normcase(os.path.abspath(root)).rstrip("\\/")
    candidate_text = os.path.normcase(os.path.abspath(candidate)).rstrip("\\/")
    if candidate_text == root_text:
        return True
    return candidate_text.startswith(root_text + os.sep)


def is_within(candidate: Path, root: Path) -> bool:
    """True when ``candidate`` resolves to ``root`` or a path below it."""

    return _is_strictly_inside(Path(candidate).resolve(strict=False), Path(root).resolve(strict=False))


def require_external_audit(path: Path, repo_root: Path, *, label: str) -> Path:
    """Validate a read-only audit target that is allowed to live outside the repository.

    Unpacked ZIP audits and CI workspaces legitimately point at trees outside the
    checkout.  What must never happen is a path that resolves back into the repository
    (through a link or ``..``) and gets audited while the caller believes it named an
    external tree, so resolution is checked against the repository root.
    """

    root = Path(repo_root).resolve(strict=False)
    resolved = Path(path).resolve(strict=False)
    if _is_strictly_inside(resolved, root):
        raise BuildLayoutError(
            f"{label} resolves inside the repository ({resolved}); "
            "audit repository trees through build/release-windows or dist/release-windows"
        )
    return resolved


def verify_plan(
    plan: BuildPlan,
    *,
    expected_build_root: Path | None = None,
    expected_dist_root: Path | None = None,
) -> list[str]:
    """Check that a plan's paths are consistent with the release boundaries.

    Called by ``layout-check`` (and by ``build.ps1`` through it) so the plan -- not an
    ad-hoc PowerShell join -- is the single source of truth for every build path.
    """

    violations: list[str] = []
    if expected_build_root is not None and not _same_path(plan.build_root, Path(expected_build_root)):
        violations.append(f"plan build_root must be exactly {Path(expected_build_root)}: {plan.build_root}")
    if expected_dist_root is not None and not _same_path(plan.dist_root, Path(expected_dist_root)):
        violations.append(f"plan dist_root must be exactly {Path(expected_dist_root)}: {plan.dist_root}")
    for name in BUILD_ROOT_FIELDS:
        target = plan.field(name)
        if _same_path(target, plan.build_root):
            violations.append(f"plan {name} must not be the build root itself: {target}")
            continue
        violations.extend(_plan_violations(name, target, plan.build_root, plan.repo_root, root_label="build root"))
    for name in (*BUILD_TREE_FIELDS, *DIST_TREE_FIELDS):
        target = plan.field(name)
        in_build_root = name in BUILD_TREE_FIELDS
        scope = plan.build_root if in_build_root else plan.dist_root
        violations.extend(
            _plan_violations(
                name,
                target,
                scope,
                plan.repo_root,
                root_label="build root" if in_build_root else "dist root",
            )
        )
    for name in REPOSITORY_INPUT_FIELDS:
        target = plan.field(name)
        if not _is_strictly_inside(target, plan.repo_root):
            violations.append(f"plan {name} must stay inside the repository: {target}")
    return violations


def _plan_violations(name: str, target: Path, scope: Path, repo_root: Path, *, root_label: str) -> list[str]:
    violations: list[str] = []
    if not target.is_absolute():
        violations.append(f"plan {name} must be an absolute path: {target}")
        return violations
    if not _is_strictly_inside(target, scope):
        violations.append(f"plan {name} must stay inside the {root_label} {scope}: {target}")
        return violations
    try:
        ensure_no_links(target, scope, label=f"plan {name}")
    except BuildLayoutError as exc:
        violations.append(str(exc))
    if not _is_strictly_inside(target, repo_root):
        violations.append(f"plan {name} must stay inside the repository: {target}")
    return violations


def venv_python(venv_root: Path) -> Path:
    """Return the interpreter path inside a build venv for the running platform."""

    if os.name == "nt":
        return Path(venv_root) / "Scripts" / "python.exe"
    return Path(venv_root) / "bin" / "python"
