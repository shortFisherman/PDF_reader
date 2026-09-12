"""Filesystem operations shared by guarded build and release-tree cleanup."""

from __future__ import annotations

import os
import shutil
import stat
from collections.abc import Callable
from pathlib import Path


def _retry_access_denied(function: Callable[[str], object], path: str, error: BaseException) -> None:
    """Make one denied rmtree entry writable, then retry its original operation."""

    if not isinstance(error, PermissionError) and getattr(error, "winerror", None) != 5:
        raise error

    status = os.lstat(path)
    if stat.S_ISLNK(status.st_mode):
        # Never chmod through a link: the retry must not mutate a target outside the
        # already validated release tree.
        raise error
    mode = status.st_mode | stat.S_IWUSR
    if stat.S_ISDIR(status.st_mode):
        mode |= stat.S_IXUSR
    os.chmod(path, mode)
    function(path)


def remove_tree(path: Path) -> None:
    """Remove a caller-validated tree, retrying read-only/access-denied entries."""

    shutil.rmtree(Path(path), onexc=_retry_access_denied)
