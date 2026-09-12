"""Runtime-lock handling: build-venv auditing and wheel SHA-256 capture.

The release must be traceable to ``packaging/windows/runtime-requirements.lock``:
the build venv may contain nothing outside that closure, and every bundled
distribution needs the SHA-256 of the exact wheel it came from.  Wheel hashes are
captured by asking pip for a download report, so the script never has to guess a
PyPI URL or trust a filename.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

_PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s\\;]+)")
_NAME_NORMALIZER = re.compile(r"[-_.]+")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")


class LockError(RuntimeError):
    """The runtime lock, the wheel report or the build venv violates the contract."""


def normalize_distribution(name: str) -> str:
    return _NAME_NORMALIZER.sub("-", name).lower()


def parse_runtime_lock(path: Path) -> dict[str, str]:
    """Parse exact ``name==version`` pins, rejecting duplicates and empty locks."""

    packages: dict[str, str] = {}
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise LockError(f"cannot read the runtime lock {path}: {exc}") from exc
    for line in text.splitlines():
        match = _PIN.match(line)
        if not match:
            continue
        name = normalize_distribution(match.group(1))
        if name in packages:
            raise LockError(f"duplicate distribution in {path}: {name}")
        packages[name] = match.group(2)
    if not packages:
        raise LockError(f"no exact package pins in {path}")
    return packages


def sha256_file(path: Path) -> str:
    digest = hashlib.new("sha256")
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.new("sha256", value.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class WheelRecord:
    """One locked distribution and the SHA-256 of the wheel it was built from."""

    name: str
    version: str
    wheel_sha256: str
    wheel_file: str

    def as_payload(self) -> dict[str, str]:
        return {
            "name": self.name,
            "version": self.version,
            "wheel_sha256": self.wheel_sha256,
            "wheel_file": self.wheel_file,
        }


def records_from_wheel_directory(wheel_root: Path) -> dict[str, WheelRecord]:
    """Hash every downloaded wheel and map it onto its normalized distribution name."""

    root = Path(wheel_root)
    if not root.is_dir():
        raise LockError(f"wheel directory does not exist: {root}")
    records: dict[str, WheelRecord] = {}
    for candidate in sorted(root.glob("*.whl")):
        parts = candidate.name.split("-")
        if len(parts) < 3:
            raise LockError(f"unexpected wheel filename: {candidate.name}")
        name = normalize_distribution(parts[0])
        version = parts[1]
        digest = sha256_file(candidate)
        if not _HEX_64.fullmatch(digest):
            raise LockError(f"wheel hash is not a SHA-256 digest: {candidate.name}")
        existing = records.get(name)
        if existing is not None and existing.wheel_sha256 != digest:
            raise LockError(f"two different wheels match distribution {name}")
        records[name] = WheelRecord(name=name, version=version, wheel_sha256=digest, wheel_file=candidate.name)
    if not records:
        raise LockError(f"no wheels found in {root}")
    return records


def records_from_pip_report(report_path: Path) -> dict[str, WheelRecord]:
    """Derive wheel SHA-256 values from the JSON report pip writes for a download run.

    Used as a cross-check against the on-disk wheels: both sources must agree, or the
    build stops rather than publishing a manifest with a hash nobody can reproduce.
    """

    try:
        payload = json.loads(Path(report_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LockError(f"cannot read the wheel download report {report_path}: {exc}") from exc
    install = payload.get("install") if isinstance(payload, dict) else None
    if not isinstance(install, list):
        raise LockError(f"wheel download report has no install list: {report_path}")
    records: dict[str, WheelRecord] = {}
    for item in install:
        if not isinstance(item, dict):
            raise LockError("wheel download report install entry is not an object")
        metadata = item.get("metadata")
        archive = item.get("archive_info")
        if not isinstance(metadata, dict) or not isinstance(archive, dict):
            raise LockError("wheel download report entry is missing metadata")
        raw_name = metadata.get("name")
        version = metadata.get("version")
        hashes = archive.get("hashes")
        if not isinstance(raw_name, str) or not isinstance(version, str) or not isinstance(hashes, dict):
            raise LockError("wheel download report entry is missing name")
        digest = hashes.get("sha256")
        if not isinstance(digest, str) or not _HEX_64.fullmatch(digest.lower()):
            raise LockError(f"wheel download report entry has no digest: {raw_name}")
        name = normalize_distribution(raw_name)
        url = item.get("download_info", {})
        wheel_file = ""
        if isinstance(url, dict) and isinstance(url.get("url"), str):
            wheel_file = url["url"].rsplit("/", 1)[-1]
        records[name] = WheelRecord(
            name=name,
            version=version,
            wheel_sha256=digest.lower(),
            wheel_file=wheel_file,
        )
    if not records:
        raise LockError(f"wheel download report contains no distributions: {report_path}")
    return records


def reconcile_wheel_records(
    expected: dict[str, str],
    from_directory: dict[str, WheelRecord],
    from_report: dict[str, WheelRecord] | None = None,
) -> list[str]:
    """Return the list of lock/report/wheel disagreements, including version drift."""

    violations: list[str] = []
    missing = sorted(set(expected) - set(from_directory))
    if missing:
        violations.append(f"no wheel captured for locked distributions: {', '.join(missing)}")
    extra = sorted(set(from_directory) - set(expected))
    if extra:
        violations.append(f"wheel captured for unlocked distributions: {', '.join(extra)}")
    for name in sorted(set(expected) & set(from_directory)):
        record = from_directory[name]
        if record.version != expected[name]:
            violations.append(
                f"wheel version differs from the runtime lock: {name} lock={expected[name]} wheel={record.version}"
            )
        if not _HEX_64.fullmatch(record.wheel_sha256):
            violations.append(f"wheel hash is not a SHA-256 digest: {name}")
    if from_report is not None:
        for name, record in sorted(from_directory.items()):
            reported = from_report.get(name)
            if reported is None:
                violations.append(f"pip report is missing distribution: {name}")
                continue
            if reported.wheel_sha256 != record.wheel_sha256:
                violations.append(f"wheel hash disagrees with the pip report: {name}")
    return violations


def audit_installed_environment(expected: dict[str, str], installed: dict[str, str]) -> list[str]:
    """Compare the build venv's installed distributions with the runtime lock."""

    violations: list[str] = []
    missing = sorted(set(expected) - set(installed))
    if missing:
        violations.append(f"build venv is missing locked distributions: {', '.join(missing)}")
    changed = sorted(
        f"{name} lock={expected[name]} installed={installed[name]}"
        for name in set(expected) & set(installed)
        if expected[name] != installed[name]
    )
    if changed:
        violations.append(f"build venv versions differ from the runtime lock: {'; '.join(changed)}")
    return violations
