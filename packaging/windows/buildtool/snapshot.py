"""Before/after snapshots of the developer state a release build must not touch.

The build contract forbids the packager from modifying the repository ``venv/``,
``config.toml``, ``cache/`` or ``logs/``.  A snapshot records path, size, mtime,
mode and a content digest for every entry, so ``snapshot-diff`` can prove equality
instead of asserting it.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

SNAPSHOT_SCHEMA = 1
DEFAULT_TARGETS: tuple[str, ...] = ("venv", "config.toml", "cache", "logs")


class SnapshotError(RuntimeError):
    """A snapshot could not be written or compared."""


def _digest(path: Path) -> tuple[str, int]:
    digest = hashlib.new("sha256")
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _describe(root: Path, relative: Path, path: Path) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "path": relative.as_posix(),
        "type": "link" if path.is_symlink() else ("dir" if path.is_dir() else "file"),
    }
    try:
        info = path.lstat()
    except OSError:
        return entry
    entry["mtime_ns"] = info.st_mtime_ns
    entry["mode"] = info.st_mode & 0o7777
    if entry["type"] == "link":
        try:
            entry["target"] = os.readlink(path)
        except OSError:
            entry["target"] = ""
        return entry
    if entry["type"] == "file":
        try:
            digest, size = _digest(path)
        except OSError as exc:
            entry["error"] = str(exc)
            return entry
        entry["sha256"] = digest
        entry["size"] = size
    return entry


def snapshot_target(root: Path, target: str) -> dict[str, Any]:
    """Describe one target path (a directory tree or a single file)."""

    base = Path(root).resolve(strict=False)
    path = base / target
    if not path.exists() and not path.is_symlink():
        return {"target": target, "present": False, "entries": []}
    if path.is_file() or path.is_symlink():
        return {"target": target, "present": True, "entries": [_describe(base, Path(target), path)]}
    entries: list[dict[str, Any]] = []
    for current in sorted(path.rglob("*")):
        relative = current.relative_to(base)
        if current.is_symlink() and current.is_dir():
            entries.append(_describe(base, relative, current))
            continue
        entries.append(_describe(base, relative, current))
    return {"target": target, "present": True, "entries": entries}


def build_snapshot(root: Path, targets: tuple[str, ...] = DEFAULT_TARGETS) -> dict[str, Any]:
    return {
        "schema": SNAPSHOT_SCHEMA,
        "root": str(Path(root).resolve(strict=False)),
        "targets": [snapshot_target(root, target) for target in targets],
    }


def write_snapshot(path: Path, payload: dict[str, Any]) -> Path:
    """Write the snapshot atomically; a partial file must never masquerade as one."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f"{destination.name}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:  # pragma: no cover - only reachable on a broken filesystem
            raise SnapshotError(f"cannot remove the temporary snapshot {temporary}: {exc}") from exc
    return destination


def read_snapshot(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SnapshotError(f"cannot read snapshot {path}: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("targets"), list):
        raise SnapshotError(f"snapshot {path} is not a snapshot document")
    return payload


def _index(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for target in payload["targets"]:
        if not isinstance(target, dict):
            continue
        name = str(target.get("target"))
        if not target.get("present"):
            index[name] = {"present": False, "entries": {}}
            continue
        entries: dict[str, dict[str, Any]] = {}
        for raw in target.get("entries", []):
            if isinstance(raw, dict) and isinstance(raw.get("path"), str):
                entries[raw["path"]] = raw
        index[name] = {"present": True, "entries": entries}
    return index


def diff_snapshots(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    """Return human-readable differences; an empty list means byte-identical state."""

    left = _index(before)
    right = _index(after)
    differences: list[str] = []
    for target in sorted(set(left) | set(right)):
        old = left.get(target, {"present": False, "entries": {}})
        new = right.get(target, {"present": False, "entries": {}})
        if old["present"] != new["present"]:
            differences.append(f"{target}: presence changed (before={old['present']}, after={new['present']})")
            continue
        for name in sorted(set(old["entries"]) | set(new["entries"])):
            old_entry = old["entries"].get(name)
            new_entry = new["entries"].get(name)
            if old_entry is None:
                differences.append(f"{name}: added")
                continue
            if new_entry is None:
                differences.append(f"{name}: removed")
                continue
            for field in ("type", "size", "sha256", "mtime_ns", "mode", "target"):
                if old_entry.get(field) != new_entry.get(field):
                    differences.append(
                        f"{name}: {field} changed ({old_entry.get(field)!r} -> {new_entry.get(field)!r})"
                    )
    return differences
