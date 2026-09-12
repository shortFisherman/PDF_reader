# Release layer manifests

Versioned inputs that both PyInstaller specs reference by name:

| 文件 | 作用 | 如何更新 |
|---|---|---|
| `pdf_reader.ico` | 两个 EXE 的图标（16/32/48/64/128/256，PNG 帧 ICO 容器） | `python -m buildtool icon --write`（在 `packaging/windows` 内运行）；构建时 `build.ps1` 会调用 `icon --check` 验证提交的图标与生成器一致 |
| `version-info-launcher.txt` | 顶层 `PDF Reader.exe` 的 Windows 版本资源（`VSVersionInfo`） | 由 `buildtool generate` 按 `pyproject.toml` 的版本渲染到 `build/release-windows/generated/`；本文件是发行层默认值，用于在没有构建环境时仍能执行 spec 契约测试 |
| `version-info-service.txt` | `app/PDF Reader Service.exe` 的版本资源 | 同上 |

图标刻意以可重建的形式保存：它由 `buildtool.wheels` 从代码确定性地渲染，不需要外部设计
文件，也不会出现无法追溯来源的二进制。两个版本资源文件里的版本号与当前
`pyproject.toml` 一致；正式构建总是用构建期渲染的副本覆盖它们，因此发行物中的版本永远
来自 `pyproject.toml`。
