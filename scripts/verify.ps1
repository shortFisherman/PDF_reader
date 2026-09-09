param(
    [string]$PythonExecutable
)

# P2-04 跨平台公共验证入口的 Windows 启动器。
#
# 完整验证编排（步骤顺序、版本门槛、coverage 产物与失败即停）只存在于
# scripts/verify.py；本脚本只做三件事：解析 Python 解释器、校验基本可用性，
# 然后以“python scripts/verify.py”委托公共验证并传播退出码。
# 这样 Windows（PowerShell）与 WSL（venv/bin/python scripts/verify.py）
# 执行的是同一份逻辑，不会漂移。
#
# coverage 产物目录通过环境变量 PDF_READER_COVERAGE_ARTIFACT_DIR 传给
# scripts/verify.py（与旧版 verify.ps1 的外部调用方式兼容）。

$ErrorActionPreference = 'Stop'

function Resolve-VerifyPython {
    param(
        [string]$PythonExecutable,
        [string]$RepoRoot = (Join-Path $PSScriptRoot '..')
    )

    if ($PythonExecutable) {
        if (-not (Get-Command $PythonExecutable -ErrorAction SilentlyContinue)) {
            throw "Python executable not found: $PythonExecutable"
        }
        return $PythonExecutable
    }

    $venvPython = Join-Path $RepoRoot 'venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $venvPython) {
        return $venvPython
    }

    if (-not (Get-Command 'python' -ErrorAction SilentlyContinue)) {
        throw "Python executable not found: no repository venv and no python on PATH"
    }

    Write-Warning "No repository venv found at $venvPython; falling back to python on PATH. Pass -PythonExecutable explicitly for reproducible verification."
    return 'python'
}

if ($MyInvocation.InvocationName -ne '.') {
    $pythonCommand = Resolve-VerifyPython -PythonExecutable $PythonExecutable

    Write-Host "==> Common verification (scripts/verify.py)"
    & $pythonCommand scripts/verify.py
    if ($LASTEXITCODE -ne 0) {
        throw "Verification failed with exit code $LASTEXITCODE"
    }

    Write-Host 'All verification checks passed.'
}
