"""P2-01 Windows onedir build helpers (standard library only).

``packaging/windows/build.ps1`` is the only supported build entry point; it is a
thin PowerShell driver that delegates every non-trivial decision to this package so
the build contract stays testable without PowerShell or Windows:

* :mod:`buildtool.layout` -- path resolution plus the fail-closed deletion guard that
  confines ``--clean`` to ``build/release-windows`` and ``dist/release-windows``.
* :mod:`buildtool.lock` -- runtime lock parsing, build-venv verification and the
  wheel SHA-256 capture that feeds ``app/runtime-manifest.json``.
* :mod:`buildtool.wheels` -- image/png/ico generation for the release icons.
* :mod:`buildtool.snapshot` -- content and metadata snapshots of the developer
  ``venv/``, ``config.toml``, ``cache/`` and ``logs/`` trees before/after a build.
* :mod:`buildtool.winver` -- PyInstaller ``VSVersionInfo`` generation.
* :mod:`buildtool.modules` -- installed-distribution index used to prove which locked
  distributions really landed in ``app/_internal``.
* :mod:`buildtool.artifacts` -- artifact tree contract, file inventory and ZIP output.
* :mod:`buildtool.manifest` -- ``app/runtime-manifest.json`` (runtime policy schema 1).
* :mod:`buildtool.cli` -- the command surface consumed by ``build.ps1``/``build.sh``.

Everything here must import nothing outside the standard library: the helper runs in
the freshly created build virtual environment, before the runtime lock is installed.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "1.0.0"
