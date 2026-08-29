param(
    [string]$PythonExecutable
)

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

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Label,
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command
    )

    Write-Host "==> $Label"
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE"
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    $pythonCommand = Resolve-VerifyPython -PythonExecutable $PythonExecutable
    $pythonInfo = & $pythonCommand -c "import sys; print(sys.executable); print(sys.version.split()[0])"
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to query Python interpreter: $pythonCommand"
    }
    Write-Host "Resolved Python: $($pythonInfo[0])"
    Write-Host "Python version: $($pythonInfo[1])"

    Invoke-Checked 'Ruff lint' { & $pythonCommand -m ruff check . }
    Invoke-Checked 'Ruff format check' { & $pythonCommand -m ruff format --check . }
    Invoke-Checked 'Python tests' { & $pythonCommand -m pytest -q }
    Invoke-Checked 'Frontend tests' { npm test }

    Write-Host 'All verification checks passed.'
}
