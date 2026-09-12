"""P2-01 构建隔离契约：专用环境、发行输出边界、门禁、输出物、开发路径快照与安全清理。

只做源码层验证（PowerShell 脚本静态契约 + 发行层模块契约）：真实 PyInstaller 构建、
dist/ZIP 运行、干净机与 Process Monitor 审计属于 P2-01 构建执行与 P2-02/P3-01，
本文件不把它们伪装成已执行。
"""

from __future__ import annotations

import re

import pytest

from tests.release import packaging_harness as pkg

REPO_ROOT = pkg.REPO_ROOT


def test_build_creates_only_a_dedicated_release_environment() -> None:
    creations = pkg.logical_lines_containing("-m venv")
    assert creations, "构建脚本必须自行创建发行构建专用环境（python -m venv）"
    for path, line in creations:
        assert pkg.window_scope_ok(path, line), f"venv 必须建在发行构建目录内：{line.strip()[:200]}"

    installs = [
        entry for token in ("pip install", "pip download", "pip wheel") for entry in pkg.logical_lines_containing(token)
    ]
    assert installs, "构建必须在专用环境内安装锁定依赖"
    for path, line in installs:
        assert pkg.window_scope_ok(path, line), (
            f"发行依赖安装只能作用于发行构建环境，不得污染根 venv/：{line.strip()[:200]}"
        )
    assert any("runtime-requirements.lock" in line for _, line in installs), (
        "发行依赖必须来自 packaging/windows/runtime-requirements.lock"
    )


def test_build_pins_runtime_lock_and_pyinstaller_version() -> None:
    corpus = pkg.normalize_separators(pkg.layer_corpus())

    assert pkg.RUNTIME_LOCK_RELATIVE_PATH in corpus or "runtime-requirements.lock" in corpus
    assert re.search(r"(?i)pyinstaller\s*==\s*[0-9]", corpus), (
        "PyInstaller 版本必须被锁定（构建工具锁或构建脚本内的精确 pin），不能使用浮动版本"
    )


def test_build_intermediates_outputs_and_cache_stay_inside_release_directories() -> None:
    corpus_scope = pkg.layer_scoped_variables()
    for token in ("--workpath", "--distpath"):
        arguments = pkg.argument_lines_containing(token)
        assert arguments, f"构建层必须显式指定 {token}（PyInstaller 中间产物/缓存不得落到默认用户目录）"
        for path, argument in arguments:
            assert pkg.window_scope_ok(path, argument, corpus_scope), (
                f"{token} 必须指向 {pkg.BUILD_DIRECTORY}/ 或 {pkg.DIST_DIRECTORY}/：{argument.strip()[:200]}"
            )

    assignments = [
        entry
        for entry in pkg.logical_lines_containing("PYINSTALLER_CONFIG_DIR")
        if re.search(r"(?<![<>=!])=(?!=)", entry[1])
    ]
    assert assignments, "构建层必须把 PyInstaller 缓存显式指向发行构建目录（PYINSTALLER_CONFIG_DIR）"
    offenders = [entry[1].strip()[:200] for entry in assignments if not pkg.window_scope_ok(*entry, corpus_scope)]
    assert not offenders, f"PYINSTALLER_CONFIG_DIR 必须指向 {pkg.BUILD_DIRECTORY}/：{offenders}"


def test_build_runs_runtime_and_data_policy_gates_against_the_assembled_artifact() -> None:
    build_text = "\n".join(text for _, text in pkg.build_documents())
    artifacts = pkg.logical_lines_containing("--artifact", build_only=True)
    assert artifacts, "策略门必须以 --artifact 指向组装后的发行目录"
    gate_files = {path for path, _ in artifacts}
    gate_text = "\n".join(pkg.document(path) for path in gate_files) + build_text
    for module in ("runtime_policy.py", "data_policy.py"):
        assert module in gate_text, f"构建必须运行 packaging/windows/{module}"

    for path, argument in pkg.argument_lines_containing("--artifact"):
        assert pkg.window_scope_ok(path, argument), f"--artifact 必须指向发行输出目录：{argument.strip()[:200]}"

    assert any(
        re.search(
            r"\$LASTEXITCODE|\bthrow\b|exit\s+1|-ErrorAction\s+Stop|check=True|subprocess\.run|_fail\(|run_checked",
            pkg.document(path),
        )
        for path in gate_files
    ), "策略门失败必须中止构建：必须检查退出码，而不是忽略结果继续打包"


def test_build_outputs_version_commit_manifest_file_list_zip_and_sha256() -> None:
    build_documents = pkg.build_documents()
    normalized = pkg.normalize_separators("\n".join(text for _, text in build_documents))

    assert re.search(r"rev-parse[^\n]*HEAD", normalized) or "source_commit" in normalized, (
        "构建必须记录源码提交（git rev-parse HEAD）"
    )
    assert "__version__" in normalized or "pyproject.toml" in normalized, "构建必须记录应用版本"

    manifest_writers = [
        path.name
        for path, text in build_documents
        if "runtime-manifest" in pkg.normalize_separators(text)
        and re.search(r"ConvertTo-Json|Set-Content|Out-File|json\.dump|WriteAllText|write_text|write_json", text)
    ]
    assert manifest_writers, "构建必须实际写出依赖 manifest：app/runtime-manifest.json"

    assert re.search(
        r"(?i)file[-_]?list|files\.txt|files\.sha256|filelist|SHA256SUMS|checksums|inventory", normalized
    ), "构建必须产出文件清单"
    assert re.search(r"\.sha256\b", normalized), "构建必须产出 .sha256 校验和文件"
    assert re.search(r"(?i)sha256", normalized) and (
        "Get-FileHash" in normalized or "sha256sum" in normalized or "hashlib" in normalized
    ), "SHA-256 必须由确定的哈希实现计算"
    assert "PDF-Reader" in normalized and "windows-x64-portable" in normalized, "构建产物名必须包含产品与渠道"
    assert re.search(r"\.zip\b", normalized), "构建必须产出便携 ZIP"
    assert re.search(r"(?i)Compress-Archive|zipfile|write_zip|MakeArchive|7z\b", normalized), "构建必须真正打包 ZIP"


def test_development_paths_are_snapshotted_before_build_and_verified_after_build() -> None:
    """构建前后各取一次开发路径快照，且比较失败必须中止构建。

    行为细节（覆盖哪四个开发路径、差异如何报告）由 CLI 契约测试验证；这里只锁定
    build.ps1 的调用序列与失败传播结构。
    """

    orchestration = {path for path, _ in pkg.orchestration_documents()}
    captures = [
        (path, line)
        for path, line in pkg.logical_lines_containing("snapshot")
        if path in orchestration and re.search(r"--output", line)
    ]
    assert len(captures) >= 2, (
        "构建必须在开始前与结束后各取一次开发路径快照（venv/config.toml/cache/logs）；"
        f"当前捕获点：{[line.strip()[:120] for _, line in captures]}"
    )

    comparison = [entry for entry in pkg.logical_line_contexts("snapshot-diff") if entry[0] in orchestration]
    assert comparison, "构建必须比较构建前后的开发路径快照"
    invokers = pkg.checked_invokers()
    assert invokers, "构建必须提供失败即中止的调用入口（检查 $LASTEXITCODE 并抛错）"
    for path, line, context in comparison:
        assert any(re.search(rf"(?i)(?<![\w-]){re.escape(name)}\b", context) for name in invokers), (
            f"快照差异必须经会中止构建的调用入口，而不是只打印结果：{line.strip()[:160]}"
        )
    comparison_files = {path for path, _, _ in comparison}
    assert any(re.search(r"\bfinally\b|\btrap\b", pkg.document(path)) for path in comparison_files), (
        "构建失败路径也必须完成快照校验（try/finally 或 trap）"
    )


def test_clean_target_validates_release_targets_before_deleting() -> None:
    removals = [
        (path, command, line, context)
        for path, text in pkg.script_documents()
        for command, line, context in pkg.removal_command_windows(text)
    ]
    assert removals, "必须提供显式清理入口（清理 build/dist 发行产物）"

    corpus = pkg.layer_corpus()
    assert re.search(r"(?i)\[switch\]\s*\$\w*clean\w*", corpus), (
        "清理必须是显式开关（例如 param([switch]$Clean)），而不是构建的隐式副作用"
    )

    scope = pkg.layer_scoped_variables()
    for path, command, line, context in removals:
        if re.search(r"TEMP|GetTempPath", line, re.IGNORECASE):
            continue  # 系统 Temp 不属于开发路径，允许显式使用
        assert pkg.guarded_command_ok(path, line, context, scope), (
            f"{command} 只允许作用于 {pkg.BUILD_DIRECTORY}/ 与 {pkg.DIST_DIRECTORY}/，"
            f"不得扩大到仓库根或用户数据：{context.strip()[:200]}"
        )

    validating = [
        path.name
        for path, text in pkg.script_documents()
        if re.search(r"Resolve-Path|GetFullPath|\[IO\.Path\]|realpath|\bresolve\(", text)
        and re.search(r"StartsWith|IsPathRooted|-notlike\b|relative_to|is_relative_to", text)
    ]
    assert validating, (
        "clean 必须先解析绝对目标并验证其严格位于两个发行输出目录内"
        "（Resolve-Path/GetFullPath + StartsWith/IsPathRooted/relative_to）"
    )


def test_write_operations_never_touch_development_entrypoints() -> None:
    scope = pkg.layer_scoped_variables()
    offenders: list[str] = []
    for path, text in pkg.script_documents():
        for command, line, context in pkg.write_command_windows(text):
            if pkg.guarded_command_ok(path, line, context, scope):
                continue
            if re.search(r"TEMP|GetTempPath", line, re.IGNORECASE):
                continue
            offenders.append(f"{path.relative_to(REPO_ROOT).as_posix()}: {command} … {context.strip()[:160]}")
    assert not offenders, "构建只允许写发行构建目录；开发 venv/、config.toml、cache/、logs/ 不得被修改：\n" + "\n".join(
        offenders
    )


def test_release_output_directories_are_git_ignored_and_untracked() -> None:
    for relative in (f"{pkg.BUILD_DIRECTORY}/probe.txt", f"{pkg.DIST_DIRECTORY}/probe.txt"):
        ignored = pkg.git_ignored(relative)
        if ignored is None:
            pytest.skip("需要可用的 git 工作区")
        assert ignored, f"{relative} 必须被 .gitignore 忽略"

    tracked = pkg.tracked_repository_paths()
    offenders = [name for name in tracked if name.startswith(("build/", "dist/"))]
    assert not offenders, f"发行构建产物不得进入 Git 跟踪：{offenders}"


def test_build_layer_scans_assembled_artifact_for_secrets_and_developer_paths() -> None:
    documents = pkg.layer_documents()

    assert documents, "发行层必须有可审计的构建输入"
    scanners = [
        path
        for path, text in pkg.script_documents()
        if re.search(r"(?i)Select-String|re\.(?:search|findall|compile)|fnmatch|--scan\b", text)
        and re.search(r"(?i)artifact|PDF Reader|release-windows", pkg.normalize_separators(text))
    ]
    assert scanners, "必须提供对组装后发行目录的密钥/开发者路径扫描步骤"

    corpus = pkg.layer_corpus()
    both_forms = corpus + "\n" + pkg.normalize_separators(corpus)
    assert re.search(r"(?i)sk-|api[_-]?key|Bearer|secret_scan|密钥|私钥", both_forms), (
        "产物扫描必须覆盖密钥材料模式（例如 sk-、api_key、Bearer、secret_scan）"
    )
    assert re.search(r"(?i)C:/Users|\\\\Users\\\\|\$env:USERNAME|USERPROFILE|/home/|/Users/", both_forms), (
        "产物扫描必须覆盖开发者用户名/家目录模式（例如 C:/Users、$env:USERNAME、USERPROFILE、/home/）"
    )
