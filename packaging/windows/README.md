# Windows portable release layer

This directory contains only release-specific policy and, starting with P2-01,
the PyInstaller build definition.  It must not contain a copy of application
source, frontend assets, templates, wheels, or user data.

## P0-04 private-runtime contract

`runtime-requirements.lock` is the Python 3.12 runtime-only dependency closure.
It is constrained by the repository-wide `requirements.lock`, so every version
must match while pytest, coverage, mypy, pip-tools, pip, setuptools, and wheel are
excluded.  `ruff` remains because the locked Gradio/Xsdata dependency graph
declares it as a runtime dependency; the artifact scanner may include it only for
that documented reason.

Regenerate the lock from the repository root with the exact command recorded in
its header:

```powershell
$env:CUSTOM_COMPILE_COMMAND = "python -m piptools compile --resolver=backtracking --strip-extras --constraint=requirements.lock --output-file=packaging/windows/runtime-requirements.lock pyproject.toml"
python -m piptools compile --resolver=backtracking --strip-extras --constraint requirements.lock --output-file packaging/windows/runtime-requirements.lock pyproject.toml
Remove-Item Env:CUSTOM_COMPILE_COMMAND
```

The source policy is part of the normal verification gate:

```powershell
python packaging/windows/runtime_policy.py --source-root .
```

P2-01 must run the artifact policy against the assembled `PDF Reader/` directory:

```powershell
python packaging/windows/runtime_policy.py --source-root . --artifact dist/release-windows/PDF Reader
```

The artifact must contain `app/runtime-manifest.json`.  Schema version 1 records
the full Git commit, Python 3.12 patch version, private service executable SHA-256,
the runtime-lock SHA-256, and exactly one name/version/wheel-SHA-256 entry for each
locked distribution.  This makes every bundled package traceable without keeping
pip or wheel files in the shipped application.
