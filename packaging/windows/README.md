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

## P1-03 portable data contract (source level)

**Release package.**  The artifact must ship no real `data/` content.  The P1-03
gate rejects any file under `data/` (config, models, document cache, logs, temp), any
leaked top-level development directory (an empty `data/` scaffold is allowed), a
user `config.toml`, a `portable-data.json` manifest, a launcher log or model weights
placed anywhere in the tree.  P2-01 runs the same policy against the assembled
onedir tree before packaging:

```powershell
python packaging/windows/data_policy.py --artifact "dist/release-windows/PDF Reader"
```

**In-place upgrade.**  Overwriting the same directory with a newer ZIP only replaces
`app/` and the launcher executable; `data/` is not part of any release package, so
configuration, models and document caches survive the upgrade.  The data format
version lives in `data/portable-data.json` (`schema_version`, `product`,
`app_version`, `created_at`, `updated_at`, `applied_migrations`) and is detected
before the service starts.

**Migration ordering, backup and rollback.**  `portable_launcher` calls
`portable_data.prepare_portable_data()` after it owns the single-instance lock and
before it spawns `app/PDF Reader Service.exe`; a second launch therefore only
activates the existing instance and never migrates concurrently.  A migration backs
up the old manifest bytes under `data/backups/<timestamp>/files/`, writes a sibling
`*.tmp` file and commits with an atomic replace (`DataMigrationTxn.commit`); a
failure keeps the old bytes and the failed temporary file is discarded, so the old
version still starts.  A failure *before* `commit()` must never leave new bytes
behind with no ledger: `replace_file()`/`commit()` restore every target this
transaction really replaced (old bytes written back, files created by this
transaction deleted) in reverse order, and the `with` statement covers unexpected
exceptions between the two steps, so an uncommitted migration rolls itself back.
If that automatic restore fails, the run stops with
`portable_data_recovery_failed`, naming the backup directory and the unrestored
targets for manual recovery, instead of reporting success.  Stable codes are
`portable_data_manifest_invalid`, `portable_data_schema_newer`,
`portable_data_write_failed` and `portable_data_recovery_failed`; a newer schema is
refused instead of downgraded.  `python scripts/portable_data.py rollback --yes`
(optionally `--backup DIR`) reverses the recorded file operations of the last
committed migration so the previous version can start again.

**New-directory install / import.**  Copying the old `data/` directory is a
documented, supported path; the controlled import copies only non-volatile data
(`documents/`, `models/`, `upstream-cache/`, `fonts/`, glossary) and never imports
`config/`, `logs/`, `temp/`, `runtime/`, the target manifest or migration backups,
so models do not have to be downloaded again:
`python scripts/portable_data.py import --from "D:\old\data" --yes`.  The source must
be a real directory outside the target data root and must not be a link.

**Cleanup.**  `python scripts/portable_data.py status` (also reachable through the
launcher's hidden data commands) reports one row per category with size, file count
and consequence: 文档缓存 (not regenerable), 模型与上游缓存, 字体, 日志, 临时文件.
`clean` requires explicit categories (`--category ...` or `--all`) and only deletes
with `--yes`; preview is the default.  Cleanup refuses to run while
`data/runtime/instance.json` exists, resolves every target inside the normalized
data root, rejects a category root that is a symlink or junction, deletes a linked
child as a link only, and therefore never recursively deletes user PDFs stored
outside `data/`.

Source-level coverage: `tests/release/test_portable_data.py` (schema detection,
atomic migration/rollback, category statistics, boundary-safe cleanup, controlled
import), `tests/release/test_portable_data_cli.py` (status/clean/import/rollback
commands), `tests/release/test_portable_launcher.py` (preparation happens after the
lock and before the service spawn) and `tests/release/test_data_policy.py`
(artifact and release-notes gate).  A real Windows ZIP, a real clean-machine upgrade
and the final artifact audit still belong to P2-01/P2-02.

## P2-01 onedir build

`build.ps1` is the only supported local build entry point.  It resolves a Python 3.12
launcher, creates `build/release-windows/venv`, installs the locked dependencies, drives
PyInstaller, and delegates every non-trivial decision to `buildtool` (standard-library
only, see `buildtool/__init__.py`).  PowerShell never reimplements build logic, so the
same decisions are unit-testable without Windows.

```powershell
# 完整构建（首次需要网络下载锁定依赖）
powershell -ExecutionPolicy Bypass -File packaging/windows/build.ps1
# 从零重建（只删除两个已验证的发行输出目录）
powershell -ExecutionPolicy Bypass -File packaging/windows/build.ps1 -Clean
# 复用已有构建环境重新打包
powershell -ExecutionPolicy Bypass -File packaging/windows/build.ps1 -SkipVenvInstall
```

**Inputs.** `pyproject.toml` (version), `requirements.lock`,
`runtime-requirements.lock` (runtime closure), `build-requirements.lock` (PyInstaller and
its Windows dependencies, installed with `--require-hashes`), `src/pdf_reader/`,
`static/`, `templates/`, `config.example.toml`, `LICENSE`, both `*.spec` files,
`hooks/` and `manifests/`.

**Outputs.** Everything lands under `dist/release-windows/`:

```text
PDF Reader/                         # 解压后的便携目录（ZIP 内的唯一根目录）
├─ PDF Reader.exe                   # 唯一面向用户的入口（含私有 _internal/）
├─ app/                             # 私有服务与只读资源（便携模式下的 RESOURCE_ROOT）
│  ├─ PDF Reader Service.exe        # 承载 PyMuPDF/pdf2zh-next/BabelDOC/ONNX Runtime
│  ├─ _internal/                    # 服务自己的私有运行时
│  ├─ static/  templates/  config.example.toml
│  ├─ licenses/{LICENSE,DEPENDENCIES.txt}
│  ├─ runtime-manifest.json         # runtime_policy schema 1（含每个 wheel 的 SHA-256）
│  └─ release-manifest.json         # 版本、commit、依赖锁哈希与逐文件清单
├─ data/                            # 空目录：所有可变数据在首次启动时创建
└─ PDF-Reader-<version>-windows-x64-portable.zip
```

`dist/release-windows/` also receives `<artifact>.files.sha256` (the release filelist in
`sha256sum` format) and `<zip>.sha256` (the ZIP checksum).

**Plan as the path source of truth.**  `build.ps1` writes only three literals of its own --
the repository root, `build/release-windows`, `dist/release-windows` -- plus the build venv
and plan-file names inside them; every other build and artifact path comes from the JSON
that `buildtool plan` emits, and `Read-BuildPlan` verifies each one before use.  `plan`
writes absolute paths, `layout-check --expect-build-root/--expect-dist-root` proves the
plan's two roots are exactly the caller's canonical roots, and a plan that claims another
repository, widens a root, or points an artifact at the build root is rejected.

**Boundaries.** The build only writes `build/release-windows/` and
`dist/release-windows/`.  Every externally supplied path is validated by its read/write
semantics: `--output` for plans, snapshots, snapshots-diff inputs, wheel caches and
reports must resolve inside the build root, while the release tree (`manifest`,
`verify-tree`, `assemble`, `dependencies`, `finalize`, `package`) and the staging bundles
must resolve inside the dist/build root respectively.  Containment is compared
component-wise, so a sibling such as `release-windows-typo` is never mistaken for the
root, and any symbolic link or junction on the path is rejected.

Read-only audits are the one deliberate exception: `verify-tree`, `verify-bundles` and
`check-wheels` accept a target that resolves outside the repository (an unpacked ZIP or a
CI workspace), but reject any path that resolves back into the checkout, so a
mis-specified audit can never silently inspect a development tree.

`clean` resolves its two targets and proves each one equals `build/release-windows` or
`dist/release-windows` exactly -- a name prefix, the repository root or a link target is
refused.  `build.ps1 -Clean` reuses that same check: it prefers the build venv, falls back
to a base Python 3.12 (so cleaning works before any venv exists), and only if no
interpreter is available does it fall back to an equivalent PowerShell check.  Developer
state (`venv/`, `config.toml`, `cache/`, `logs/`) is snapshotted with content hashes before
the build and compared afterwards; any difference fails the build.

**Release gates.** After assembly the build runs `runtime_policy.py --artifact` and
`data_policy.py --artifact`, so a manifest that drifts from the lock, a bundled installer
or development distribution, real `data/` content, model weights or a leaked user
`config.toml` stops the build before the ZIP exists.

**Verification without Windows.** `python -m buildtool self-check` (from
`packaging/windows`, with `PYTHONPATH` pointing at it) assembles a synthetic release tree
in a temporary directory outside the repository and exercises the same code paths:
bundle verification, assembly, dependency inventory, runtime manifest, both policy gates,
tree verification and ZIP writing.  The PowerShell contract itself is covered by
`tests/release/test_packaging_isolation_contract.py` and the spec/artifact contract by
`tests/release/test_packaging_build_contract.py`.

**PyInstaller specifics.** The service spec declares the upstream dynamic imports
(`pdf2zh-next` translation backends through `importlib`, tiktoken's `tiktoken_ext` plugin
namespace), the native runtime (`onnxruntime`, `cv2`, `hyperscan`, `rtree`, `uharfbuzz`),
and the package data that `import` scanning cannot see (BabelDOC CMap/`DocumentIL` files,
PyMuPDF's MuPDF library).  `gradio`, `onnx` and `ruff` are excluded: the GUI stack is
unused by the service and the `onnx` wheel ships the `.onnx` model files that the data
policy forbids shipping.  Both bundles are onedir (`exclude_binaries=True` plus
`COLLECT`), so the shipped runtime is a private interpreter directory, never a system
Python.

**Known gaps for P2-01.** `runtime-requirements.lock` pins exact versions but carries no
wheel hashes yet, so the runtime install trusts PyPI to serve the pinned version; the
recorded wheel SHA-256 in `app/runtime-manifest.json` is what makes the shipped bytes
auditable afterwards (hash-carrying runtime pins belong to the P2-03 CI pipeline).  The
`build-requirements.lock` (PyInstaller toolchain) already installs with
`--require-hashes`.  The Windows executable build itself must run on Windows: PyInstaller
cannot cross-compile, so this repository's Linux/WSL side covers the contract, the policy
gates and the packaging path (through `self-check`) but never produces the real EXE.

**Troubleshooting.**

- `icon_stale`: run `python -m buildtool icon --write` inside `packaging/windows` and
  commit `manifests/pdf_reader.ico`.
- `pyinstaller_bundle_invalid`: read the reported missing runtime/module; a missing
  upstream package usually means the build venv was installed from a different lock than
  `runtime-requirements.lock`.
- `runtime_manifest_invalid` / `artifact_tree_invalid`: the message names the offending
  file or distribution; fix the collection instead of relaxing the policy gates.
- A build that must be re-run from scratch: `build.ps1 -Clean` (never delete
  `build`/`dist` by hand while a build is running).

All mutable state stays inside the extracted directory, and the extracted directory
is the unit of uninstall: **deleting the whole portable directory deletes
configuration and caches**.  `README.md` states this for users, and the P1-03 build
gate fails the build if that statement (or the documented copy/import path for an
old `data/`) disappears from the release notes.
