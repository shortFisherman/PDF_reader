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

## P1-02 launcher contract (source level)

The top-level `PDF Reader.exe` is the only entry point users double-click.  It
keeps the real user environment (proxy, certificates, `HOME`/`USERPROFILE`) and
drives exactly one `app/PDF Reader Service.exe` over loopback:

- **Single instance.**  A kernel-owned lock is the only ownership authority: a
  named Windows mutex, which the kernel releases when the owning process dies, so
  a crash or a forced kill can never leave a stale lock.  `data/runtime/instance.json`
  only carries the loopback endpoints and the current launch's tokens, and a
  second launch trusts it only after an authenticated `GET /api/health` probe and
  an authenticated `POST /api/control` (`open_reader`) that the running launcher
  answers by opening the reader in the real user environment.  No process is ever
  terminated to make room for a second instance.
- **Readiness.**  The launcher never guesses with a fixed sleep: it waits for the
  atomic readiness descriptor under `data/temp/` and confirms it with a
  token-authenticated health probe (`X-PDF-Reader-Health-Token`), bounded by the
  startup timeout.  Failures carry stable codes and are logged to
  `data/logs/launcher.log`.
- **Control window.**  One fixed launcher window with exactly three actions:
  打开阅读器 (open reader), 打开日志 (open logs), 退出程序 (quit).  Closing the
  browser tab is not a shutdown; the service keeps running.  Closing the window is
  the quit action, identical to 退出程序.  The default launch must create this
  window before opening the browser.  Missing Tk/Tcl, no desktop session, or a
  window initialization/runtime failure is the stable `launcher_ui_unavailable`
  error: the launcher requests cooperative service shutdown and exits with code 7
  instead of leaving a hidden service.  Only the explicit `--no-ui` diagnostic/test
  mode may wait without a window.
- **Exit.**  Quit asks the service to stop cooperatively through the
  token-protected `POST /api/shutdown`: the service stops accepting new work,
  cancels/waits for the active translation, closes `AppState`, and only then
  returns from `app.main`.  The launcher force-stops only the child process it
  started, and only after the shutdown timeout; the service requests the same
  cooperative exit when it notices the launcher has died.  Liveness is not inferred
  from a PID: each Windows launch owns a fresh random named mutex, and the service
  waits for that exact mutex to become abandoned.  PID reuse therefore cannot make
  an orphan service mistake an unrelated process for its launcher.  POSIX tests use
  the equivalent per-launch random `flock` identity.
- **Port conflict.**  If another program owns the port, the launcher reports the
  stable, recoverable `service_port_in_use` message and exits without touching the
  other process and without switching ports automatically.
- **Exit codes.**  0 clean exit, 2 launcher/state error, 3 service failed to
  start, 4 port in use, 5 existing instance could not be activated, 6 service
  exited unexpectedly/abnormally, 7 required control window unavailable,
  130 interrupted.
- **State location.**  All file-backed coordination state (the POSIX lock file,
  instance record, readiness descriptors, and tokens) stays under `data/`; the
  Windows lock is a kernel object whose non-secret name is derived from the
  portable root.  Tokens never appear in URLs, logs, or user-visible messages.

Cleanup ordering is fixed: stop the launcher control server, finish cooperative
service shutdown (or bounded fallback), close the per-launch liveness owner,
remove the instance/readiness/temp state, and release the global instance lock
last.  A successor cannot acquire ownership while the old service or advisory
record is still active.

The source-level state machine is covered by `tests/release/`
(`test_portable_instance.py`, `test_portable_launcher.py`,
`test_portable_control_window.py`, `test_portable_service_lifecycle.py`) with
`python -m pytest tests/release -q`.  Real Windows double-click behaviour on a
clean machine and the final ZIP still belong to P2-01/P2-02.
