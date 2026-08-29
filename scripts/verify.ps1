param(
    [string]$PythonExecutable
)

$ErrorActionPreference = 'Stop'

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

$pythonCommand = $PythonExecutable
if (-not $pythonCommand) {
    $pythonCommand = Join-Path $PSScriptRoot '..\venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $pythonCommand)) {
        $pythonCommand = 'python'
    }
}
if (-not (Get-Command $pythonCommand -ErrorAction SilentlyContinue)) {
    throw "Python executable not found: $pythonCommand"
}

Invoke-Checked 'Ruff lint' { & $pythonCommand -m ruff check . }
Invoke-Checked 'Ruff format check' { & $pythonCommand -m ruff format --check . }
Invoke-Checked 'Python tests' { & $pythonCommand -m pytest -q }
Invoke-Checked 'Frontend tests' { npm test }

Write-Host 'All verification checks passed.'
