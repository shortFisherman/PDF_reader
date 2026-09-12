#requires -Version 5.1
<#
.SYNOPSIS
    构建 Windows x64 便携发行物（PyInstaller onedir）。

.DESCRIPTION
    P2-01 的唯一正式本地构建入口。脚本只做四件事：解析基础解释器、创建专用构建环境、
    按固定顺序调用 packaging/windows/buildtool（标准库实现、可离线测试的构建逻辑）、
    并在构建前后比较开发态快照。所有路径、删除边界与产物契约都在 buildtool 内校验。

    发行边界（P2-01 验收项）：
      * 构建专用环境、PyInstaller workpath、缓存都在 build/release-windows/ 内；
      * 最终产物只在 dist/release-windows/ 内；
      * 仓库 venv/、config.toml、cache/、logs/ 只读，构建前后快照必须一致；
      * 发行依赖来自 packaging/windows/runtime-requirements.lock，构建工具来自
        packaging/windows/build-requirements.lock；
      * 失败与清理只作用于经解析验证的两个发行输出目录。

    路径真相来源：本脚本只写出仓库根、两个发行根与构建 venv 的字面量；其余每个构建/产物
    路径都来自 ``buildtool plan`` 写入的计划文件（Read-BuildPlan），并在使用前逐项校验：
    两个根必须精确相等，其余路径必须严格位于对应根内，且路径上不允许链接组件。因此
    PowerShell 不再自行推导关键输出路径。

.PARAMETER BasePython
    用于创建构建 venv 的 Python 3.12 解释器（默认 py -3.12，其次 PATH 上的 python）。

.PARAMETER Clean
    构建前删除 build/release-windows 与 dist/release-windows（只作用于这两个已验证目录）。

.PARAMETER SkipVenvInstall
    复用已存在的构建 venv，不重新安装锁定依赖（用于重复构建与离线复算）。

.PARAMETER KeepWork
    构建结束后保留 PyInstaller workpath，便于排查收集问题。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File packaging/windows/build.ps1
#>
[CmdletBinding()]
param(
    [string]$BasePython,
    [switch]$Clean,
    [switch]$SkipVenvInstall,
    [switch]$KeepWork
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$PackagingRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path

# 发行输出边界：下面三个变量是脚本内唯一的路径推导；其余路径全部来自构建计划。
$BuildRoot = Join-Path $RepoRoot 'build\release-windows'
$DistRoot = Join-Path $RepoRoot 'dist\release-windows'
$ReleaseRoots = @($BuildRoot, $DistRoot)
$VenvRoot = Join-Path $BuildRoot 'venv'
$VenvPython = Join-Path $VenvRoot 'Scripts\python.exe'
$PlanFile = Join-Path $BuildRoot 'build-plan.json'

function Write-Step {
    param([string]$Message)
    Write-Host "==> $Message"
}

function Invoke-Checked {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$Label
    )
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE"
    }
}

function Resolve-BasePython {
    param([string]$Requested)

    if ($Requested) {
        if (-not (Get-Command $Requested -ErrorAction SilentlyContinue)) {
            throw "base Python not found: $Requested"
        }
        return @{ File = $Requested; Prefix = @() }
    }
    if (Get-Command 'py' -ErrorAction SilentlyContinue) {
        return @{ File = 'py'; Prefix = @('-3.12') }
    }
    if (Get-Command 'python' -ErrorAction SilentlyContinue) {
        $version = & python -c "import sys; print('%d.%d' % sys.version_info[:2])"
        if ($version.Trim() -ne '3.12') {
            throw "base Python must be 3.12, found $($version.Trim()); pass -BasePython explicitly"
        }
        return @{ File = 'python'; Prefix = @() }
    }
    throw 'no Python 3.12 launcher found: install py -3.12 or pass -BasePython'
}

function Invoke-BuildTool {
    param(
        [string]$BuildPython,
        [string[]]$Arguments
    )
    $previousPath = $env:PYTHONPATH
    $env:PYTHONPATH = $PackagingRoot
    try {
        Invoke-Checked -FilePath $BuildPython -Arguments (@('-m', 'buildtool') + $Arguments) -Label "buildtool $($Arguments[0])"
    }
    finally {
        $env:PYTHONPATH = $previousPath
    }
}

function Invoke-PyInstaller {
    param(
        [string]$SpecFile,
        [string]$WorkPath
    )
    Invoke-Checked -FilePath $VenvPython -Arguments @(
        '-m', 'PyInstaller', '--noconfirm', '--clean',
        '--distpath', $Plan.staging_root,
        '--workpath', $WorkPath,
        '--log-level', 'WARN',
        $SpecFile
    ) -Label "PyInstaller $([IO.Path]::GetFileName($SpecFile))"
}

function Assert-NoLinkComponents {
    # 拒绝目标路径上位于 Stop 之下（不含 Stop 自身）的任何链接/重解析点组件：
    # 链接可能把读取或删除重定向到发行目录之外。
    param(
        [string]$Target,
        [string]$Stop,
        [string]$Label
    )
    $stopFull = [IO.Path]::GetFullPath($Stop).TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
    $current = [IO.Path]::GetFullPath($Target)
    while ($true) {
        $trimmed = $current.TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
        if ([string]::Equals($trimmed, $stopFull, [StringComparison]::OrdinalIgnoreCase)) { break }
        $item = Get-Item -LiteralPath $current -Force -ErrorAction SilentlyContinue
        if ($null -ne $item -and ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw "refusing to use a linked path ($Label): $current"
        }
        $parent = [IO.Path]::GetDirectoryName($current)
        if (-not $parent -or $parent -eq $current) { break }
        $current = $parent
    }
}

function Resolve-ExactReleaseRoot {
    # 把候选路径解析为绝对路径，并要求它精确等于 build/release-windows 或
    # dist/release-windows：前缀相同的兄弟目录、仓库根与链接目标都被拒绝。
    param(
        [string]$Candidate,
        [string]$Label
    )
    if (-not $Candidate) { throw "$Label was not provided" }
    if (-not [IO.Path]::IsPathRooted($Candidate)) { throw "$Label must be an absolute path: $Candidate" }
    $full = [IO.Path]::GetFullPath($Candidate)
    if (-not ($full.StartsWith($BuildRoot) -or $full.StartsWith($DistRoot))) {
        throw "refusing to operate outside the release output directories ($Label): $full"
    }
    $normalized = $full.TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
    $matched = @($ReleaseRoots | Where-Object {
            $allowed = $_.TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
            [string]::Equals($allowed, $normalized, [StringComparison]::OrdinalIgnoreCase)
        })
    if ($matched.Count -ne 1) {
        throw "refusing to operate on ${full}: $Label must be exactly build\release-windows or dist\release-windows of this repository"
    }
    Assert-NoLinkComponents -Target $full -Stop $RepoRoot -Label $Label
    return $matched[0]
}

function Assert-PlanPath {
    # 证明计划字段落在它应有的根内（严格包含，不接受同名前缀），并拒绝链接组件。
    param(
        [string]$Value,
        [string]$Root,
        [string]$Label
    )
    if (-not $Value) { throw "build plan is missing the $Label path" }
    if (-not [IO.Path]::IsPathRooted($Value)) { throw "build plan $Label must be an absolute path: $Value" }
    $rootFull = [IO.Path]::GetFullPath($Root).TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
    $full = [IO.Path]::GetFullPath($Value)
    $normalized = $full.TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
    $inside = [string]::Equals($normalized, $rootFull, [StringComparison]::OrdinalIgnoreCase) -or
        $normalized.StartsWith($rootFull + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)
    if (-not $inside) {
        throw "build plan $Label must stay inside $rootFull; got $full"
    }
    Assert-NoLinkComponents -Target $full -Stop $rootFull -Label $Label
    return $full
}

function Assert-PlanRoot {
    # 证明计划的根字段精确等于调用方自己的规范化根，而不是同名前缀或其它目录。
    param(
        [string]$Value,
        [string]$Expected,
        [string]$Label
    )
    if (-not $Value) { throw "build plan is missing the $Label path" }
    $full = [IO.Path]::GetFullPath($Value)
    $expectedFull = [IO.Path]::GetFullPath($Expected)
    $matches = [string]::Equals(
        $full.TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar),
        $expectedFull.TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar),
        [StringComparison]::OrdinalIgnoreCase)
    if (-not $matches) {
        throw "build plan $Label must be exactly $expectedFull; got $full"
    }
    Assert-NoLinkComponents -Target $full -Stop $RepoRoot -Label $Label
    return $full
}

function Read-BuildPlan {
    # 读取计划文件，把每个字段按读写边界校验后返回；除 $PlanFile 自身（也与计划精确比对）
    # 之外，本脚本不再自行拼装构建或产物路径。$PlanFile 与 $VenvRoot 只允许来自
    # build/release-windows 下，且必须在计划里得到相同取值。
    param([string]$PlanPath)
    $payload = Get-Content -Raw -LiteralPath $PlanPath | ConvertFrom-Json
    $plan = @{
        build_root              = Assert-PlanRoot -Value $payload.build_root -Expected $BuildRoot -Label 'build_root'
        dist_root               = Assert-PlanRoot -Value $payload.dist_root -Expected $DistRoot -Label 'dist_root'
        plan_path               = Assert-PlanPath -Value $payload.plan_path -Root $BuildRoot -Label 'plan_path'
        venv_root               = Assert-PlanPath -Value $payload.venv_root -Root $BuildRoot -Label 'venv_root'
        staging_root            = Assert-PlanPath -Value $payload.staging_root -Root $BuildRoot -Label 'staging_root'
        generated_root          = Assert-PlanPath -Value $payload.generated_root -Root $BuildRoot -Label 'generated_root'
        service_work_root       = Assert-PlanPath -Value $payload.service_work_root -Root $BuildRoot -Label 'service_work_root'
        launcher_work_root      = Assert-PlanPath -Value $payload.launcher_work_root -Root $BuildRoot -Label 'launcher_work_root'
        pyinstaller_cache_root  = Assert-PlanPath -Value $payload.pyinstaller_cache_root -Root $BuildRoot -Label 'pyinstaller_cache_root'
        work_root               = Assert-PlanPath -Value $payload.work_root -Root $BuildRoot -Label 'work_root'
        wheel_hashes_path       = Assert-PlanPath -Value $payload.wheel_hashes_path -Root $BuildRoot -Label 'wheel_hashes_path'
        distribution_index_path = Assert-PlanPath -Value $payload.distribution_index_path -Root $BuildRoot -Label 'distribution_index_path'
        generated_icon          = Assert-PlanPath -Value $payload.generated_icon -Root $BuildRoot -Label 'generated_icon'
        launcher_version_file   = Assert-PlanPath -Value $payload.launcher_version_file -Root $BuildRoot -Label 'launcher_version_file'
        service_version_file    = Assert-PlanPath -Value $payload.service_version_file -Root $BuildRoot -Label 'service_version_file'
        snapshot_before         = Assert-PlanPath -Value $payload.snapshot_before -Root $BuildRoot -Label 'snapshot_before'
        snapshot_after          = Assert-PlanPath -Value $payload.snapshot_after -Root $BuildRoot -Label 'snapshot_after'
        artifact_root           = Assert-PlanPath -Value $payload.artifact_root -Root $DistRoot -Label 'artifact_root'
    }
    $null = Assert-PlanRoot -Value $plan.plan_path -Expected $PlanFile -Label 'plan_path'
    $null = Assert-PlanRoot -Value $plan.venv_root -Expected $VenvRoot -Label 'venv_root'
    return $plan
}

function Invoke-ReleaseClean {
    # 清理两个发行输出目录。优先复用 buildtool 的严格解析：有构建 venv 时直接用 venv
    # 解释器，没有 venv 时改用基础 Python 3.12（两者都不需要先建环境）；完全没有可用
    # 解释器时退回到等价的 PowerShell 精确校验，绝不用前缀匹配判定删除范围。
    $cleanPython = $null
    $cleanArguments = @()
    if (Test-Path -LiteralPath $VenvPython) {
        $cleanPython = $VenvPython
    }
    else {
        try {
            $base = Resolve-BasePython -Requested $BasePython
            $cleanPython = $base.File
            if ($base.Prefix) { $cleanArguments += $base.Prefix }
        }
        catch {
            $cleanPython = $null
        }
    }
    if ($cleanPython) {
        $cleanArguments += @('-m', 'buildtool', '--repo-root', $RepoRoot, 'clean', '--include-dist')
        $previousPath = $env:PYTHONPATH
        $env:PYTHONPATH = $PackagingRoot
        try {
            Invoke-Checked -FilePath $cleanPython -Arguments $cleanArguments -Label 'buildtool clean'
        }
        finally {
            $env:PYTHONPATH = $previousPath
        }
        return
    }
    foreach ($Candidate in $ReleaseRoots) {
        $Verified = Resolve-ExactReleaseRoot -Candidate $Candidate -Label 'release output root'
        if (Test-Path -LiteralPath $Verified) {
            Remove-Item -LiteralPath $Verified -Recurse -Force
        }
    }
}

function Get-GitField {
    param([string[]]$Arguments, [string]$Fallback)
    try {
        $value = & git -C $RepoRoot @Arguments 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $value) {
            return $Fallback
        }
        return $value.Trim()
    }
    catch {
        return $Fallback
    }
}

Push-Location $RepoRoot
try {
    Write-Step "PDF Reader Windows 便携构建：$RepoRoot"

    $commit = Get-GitField -Arguments @('rev-parse', 'HEAD') -Fallback ''
    if ($commit -notmatch '^[0-9a-f]{40}$') {
        throw 'cannot resolve HEAD; refusing to build an untraceable release'
    }
    if (Get-GitField -Arguments @('status', '--porcelain') -Fallback '') {
        Write-Warning '工作区包含未提交改动；发行物记录的是 HEAD，manifest 与工作区不一致。'
    }

    if ($Clean) {
        Write-Step '清理已验证的发行输出目录'
        Invoke-ReleaseClean
    }

    New-Item -ItemType Directory -Path $BuildRoot -Force | Out-Null
    if (-not (Test-Path -LiteralPath $VenvPython)) {
        $base = Resolve-BasePython -Requested $BasePython
        $baseArguments = @()
        if ($base.Prefix) { $baseArguments += $base.Prefix }
        Write-Step "创建发行构建专用环境（$VenvRoot）"
        & $base.File @baseArguments -m venv $VenvRoot
        if ($LASTEXITCODE -ne 0) {
            throw "creating the dedicated release build venv failed with exit code $LASTEXITCODE"
        }
    }

    Invoke-BuildTool -BuildPython $VenvPython -Arguments @('--repo-root', $RepoRoot, 'plan', '--output', $PlanFile)
    Invoke-BuildTool -BuildPython $VenvPython -Arguments @(
        '--plan-file', $PlanFile, 'layout-check',
        '--expect-build-root', $BuildRoot,
        '--expect-dist-root', $DistRoot
    )
    $Plan = Read-BuildPlan -PlanPath $PlanFile

    Invoke-BuildTool -BuildPython $VenvPython -Arguments @('--plan-file', $PlanFile, 'icon')
    Invoke-BuildTool -BuildPython $VenvPython -Arguments @('--plan-file', $PlanFile, 'snapshot', '--output', $Plan.snapshot_before)

    if (-not $SkipVenvInstall) {
        Write-Step '在专用构建环境中安装锁定运行时依赖与构建工具'
        & $VenvPython -m pip install --disable-pip-version-check --no-color --upgrade pip
        if ($LASTEXITCODE -ne 0) { throw "upgrading pip in the release build venv failed ($LASTEXITCODE)" }
        & $VenvPython -m pip install --disable-pip-version-check --no-color -r (Join-Path $PackagingRoot 'runtime-requirements.lock')
        if ($LASTEXITCODE -ne 0) { throw "installing the runtime lock failed ($LASTEXITCODE)" }
        # 构建工具锁带 SHA-256，安装时强制校验：pip 会拒绝任何摘要不匹配的下载。
        & $VenvPython -m pip install --disable-pip-version-check --no-color --require-hashes -r (Join-Path $PackagingRoot 'build-requirements.lock')
        if ($LASTEXITCODE -ne 0) { throw "installing the build tools failed ($LASTEXITCODE)" }
    }

    Invoke-BuildTool -BuildPython $VenvPython -Arguments @('--plan-file', $PlanFile, 'env-check')
    Invoke-BuildTool -BuildPython $VenvPython -Arguments @('--plan-file', $PlanFile, 'wheel-hashes')
    Invoke-BuildTool -BuildPython $VenvPython -Arguments @('--plan-file', $PlanFile, 'generate')
    Invoke-BuildTool -BuildPython $VenvPython -Arguments @(
        '--plan-file', $PlanFile, 'dist-records', '--output', $Plan.distribution_index_path
    )
    Invoke-BuildTool -BuildPython $VenvPython -Arguments @('--plan-file', $PlanFile, 'scaffold')

    Write-Step 'PyInstaller：私有服务（app/PDF Reader Service.exe）'
    # 构建期间临时设置的进程环境变量都在这里登记；构建结束后按原值恢复。PyInstaller 缓存
    # 目录同样登记在案，目的只有一个：让本次构建的全部临时状态都留在 $Plan 指定的构建根内。
    $buildEnvironmentSnapshot = @{ Boundary = $BuildRoot; Names = @('PDF_READER_BUILD_REPO_ROOT', 'PDF_READER_BUILD_ICON', 'PDF_READER_BUILD_GENERATED_DIR', 'PDF_READER_BUILD_LAUNCHER_VERSION', 'PDF_READER_BUILD_SERVICE_VERSION', 'PYINSTALLER_CONFIG_DIR') }
    $buildEnvironmentValues = @{}
    foreach ($name in $buildEnvironmentSnapshot.Names) {
        $buildEnvironmentValues[$name] = [Environment]::GetEnvironmentVariable($name)
    }
    $env:PDF_READER_BUILD_REPO_ROOT = $RepoRoot
    # spec 的资源解析顺序：先构建期渲染产物，再退化到受版本控制的 manifests/ 资源。
    $env:PDF_READER_BUILD_GENERATED_DIR = $Plan.generated_root
    $env:PDF_READER_BUILD_ICON = $Plan.generated_icon
    $env:PDF_READER_BUILD_LAUNCHER_VERSION = $Plan.launcher_version_file
    $env:PDF_READER_BUILD_SERVICE_VERSION = $Plan.service_version_file
    # PyInstaller 默认把缓存写到用户目录；发行构建不允许在便携目录之外留下构建痕迹。
    $env:PYINSTALLER_CONFIG_DIR = $Plan.pyinstaller_cache_root
    try {
        Invoke-PyInstaller -SpecFile (Join-Path $PackagingRoot 'pdf_reader_service.spec') -WorkPath $Plan.service_work_root
        Invoke-PyInstaller -SpecFile (Join-Path $PackagingRoot 'pdf_reader.spec') -WorkPath $Plan.launcher_work_root
    }
    finally {
        foreach ($name in $buildEnvironmentSnapshot.Names) {
            [Environment]::SetEnvironmentVariable($name, $buildEnvironmentValues[$name])
        }
    }

    Write-Step '组装 dist/release-windows 产物树'
    Invoke-BuildTool -BuildPython $VenvPython -Arguments @('--plan-file', $PlanFile, 'verify-bundles')
    Invoke-BuildTool -BuildPython $VenvPython -Arguments @('--plan-file', $PlanFile, 'assemble')
    Invoke-BuildTool -BuildPython $VenvPython -Arguments @(
        '--plan-file', $PlanFile, 'dependencies',
        '--wheel-hashes', $Plan.wheel_hashes_path,
        '--commit', $commit
    )
    Invoke-BuildTool -BuildPython $VenvPython -Arguments @(
        '--plan-file', $PlanFile, 'manifest',
        '--wheel-hashes', $Plan.wheel_hashes_path,
        '--distribution-index', $Plan.distribution_index_path,
        '--commit', $commit
    )
    Invoke-BuildTool -BuildPython $VenvPython -Arguments @('--plan-file', $PlanFile, 'verify-tree')

    Write-Step '运行 P0-04 / P1-03 发行策略门'
    & $VenvPython (Join-Path $PackagingRoot 'runtime_policy.py') --source-root $RepoRoot --artifact $Plan.artifact_root
    if ($LASTEXITCODE -ne 0) { throw "runtime policy gate failed with exit code $LASTEXITCODE" }
    & $VenvPython (Join-Path $PackagingRoot 'data_policy.py') --artifact $Plan.artifact_root
    if ($LASTEXITCODE -ne 0) { throw "data policy gate failed with exit code $LASTEXITCODE" }

    Invoke-BuildTool -BuildPython $VenvPython -Arguments @('--plan-file', $PlanFile, 'finalize', '--commit', $commit)
    Invoke-BuildTool -BuildPython $VenvPython -Arguments @('--plan-file', $PlanFile, 'package')
    Invoke-BuildTool -BuildPython $VenvPython -Arguments @('--plan-file', $PlanFile, 'snapshot', '--output', $Plan.snapshot_after)
    Invoke-BuildTool -BuildPython $VenvPython -Arguments @(
        '--plan-file', $PlanFile, 'snapshot-diff', '--before', $Plan.snapshot_before, '--after', $Plan.snapshot_after
    )

    if (-not $KeepWork) {
        $WorkRoot = Assert-PlanPath -Value $Plan.work_root -Root $BuildRoot -Label 'work_root'
        if (Test-Path -LiteralPath $WorkRoot) {
            Remove-Item -LiteralPath $WorkRoot -Recurse -Force
        }
    }

    Write-Host ''
    Write-Host '构建完成。'
    Get-ChildItem -LiteralPath $DistRoot | Select-Object Name, Length | Format-Table
}
catch {
    Write-Host ''
    Write-Host "构建失败：$($_.Exception.Message)" -ForegroundColor Red
    Write-Host '按 P2-01 契约，失败只影响 build/release-windows 与 dist/release-windows；开发 venv、config.toml、cache、logs 未被修改。'
    Write-Host '如需重置构建状态：powershell -File packaging/windows/build.ps1 -Clean'
    exit 1
}
finally {
    Pop-Location
}
