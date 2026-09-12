# P2-01 Windows 原生构建交接

状态：WSL 源码/契约工作已完成；P2-01 尚未完成，等待 Windows 本地 NTFS 原生构建与产物门禁。

## 为什么必须换到 Windows 本地目录

PyInstaller 不支持从 Linux 交叉生成 Windows 发行物，最终 `.exe`、`.pyd` 和 DLL 必须由 Windows Python 构建。与此同时，不应让 Windows Python 直接在 `\\wsl.localhost\...` 的 Linux 文件系统上工作：此前实测出现旧包元数据无法卸载以及 `-Clean` 删除 Windows EXE 时 `WinError 5`。源码仍可由 WSL 管理，但 PyInstaller 的 checkout、venv、中间目录和最终目录应全部位于 NTFS（例如 `C:\work\PDF_reader-p2-01`）。

## 已完成的 WSL 工作

- `48a528b`：加入 `packaging/windows/build.ps1`、双 onedir spec、buildtool、hooks、图标/版本/许可证 manifest、锁定构建工具依赖和发行契约测试。
- `e931f83`、`aa6b73d`：兼容 Windows PowerShell 5.1 的解析与 UTF-8 BOM。
- `c470ccf`：PowerShell 使用 provider path，避免把 provider-qualified UNC 路径传给 Git/Python。
- `c3d0905`：运行时锁和 PyInstaller 工具链统一使用 `packaging==26.3`。
- `5b5043f`：安全清理在只读/WinError 5 时只对失败项增加写权限后重试；链接和目录边界仍 fail closed。
- 主代理验证：P2-01 契约测试 32 passed；完整 `scripts/verify.py` 1892 passed、19 skipped，并通过覆盖率、Ruff、mypy、密钥扫描、npm audit、JS lint 和前端测试。

## Windows PowerShell 操作

以下命令必须在 **Windows PowerShell** 中运行，不要在 WSL shell 中运行 PowerShell，也不要把 `\\wsl.localhost\...` 作为当前 checkout。

如果提交尚未推送到远端，可从现有 WSL 仓库克隆到 NTFS；将发行版名称替换为本机 `wsl -l -q` 显示的名称：

```powershell
wsl -l -q
git clone "\\wsl.localhost\Ubuntu-26.04-Recovered\home\couper\projects\PDF_reader" C:\work\PDF_reader-p2-01
Set-Location C:\work\PDF_reader-p2-01
git status --short
git log -7 --oneline
```

`git status --short` 必须为空，日志中必须至少包含 `48a528b` 至 `5b5043f` 的 P2-01 提交。若代码已推送，也可从远端正常 clone/checkout，但必须确认取得相同或更新的提交。

安装可被 `py -3.12` 解析的 64 位 Python 3.12，然后运行：

```powershell
Set-Location C:\work\PDF_reader-p2-01
powershell -NoProfile -ExecutionPolicy Bypass -File packaging/windows/build.ps1 -Clean
```

不要手工把系统 Python、根 `venv`、开发 `config.toml`、`cache` 或 `logs` 复制进发行目录；不要在失败后放宽策略门。若构建失败，请保留完整终端输出以及 `build/release-windows/`，从稳定错误码定位后修复代码。

## P2-01 成功判定

构建命令必须退出 0，并且终端最后报告开发路径构建前后快照一致。随后在同一 Windows checkout 运行：

```powershell
$Artifact = "dist/release-windows/PDF Reader"
py -3.12 packaging/windows/runtime_policy.py --source-root . --artifact $Artifact
py -3.12 packaging/windows/data_policy.py --artifact $Artifact
Get-ChildItem dist/release-windows
Get-FileHash "dist/release-windows/PDF-Reader-1.0.0-windows-x64-portable.zip" -Algorithm SHA256
```

必须保存并回传以下证据：

1. 构建命令退出码和末段完整输出。
2. `dist/release-windows/PDF Reader/` 的目录清单；顶层只有一个用户入口 `PDF Reader.exe`，服务 EXE 位于 `app/`。
3. `app/runtime-manifest.json` 与 `app/release-manifest.json`。
4. `*.files.sha256`、ZIP 的 `*.sha256` 以及 `Get-FileHash` 输出；二者必须一致。
5. `runtime_policy.py` 和 `data_policy.py` 的成功输出。
6. 构建前后开发 `venv/`、`config.toml`、`cache/`、`logs/` 快照一致的输出。
7. 如果构建失败：稳定错误码、完整错误段和失败时的 Git commit；不要删除现场后只提供截图。

以上证据通过后，可把 P2-01 从“已改进”更新为“已完成”。无系统 Python/Node/Git 的双击启动、翻译、下载、升级、异常场景和 Process Monitor 写入审计属于 P2-02，不应混入 P2-01 的源码结论。
