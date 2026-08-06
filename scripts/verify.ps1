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

$python = Join-Path $PSScriptRoot '..\venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    $python = 'python'
}

Invoke-Checked 'Ruff lint' { & $python -m ruff check . }
Invoke-Checked 'Ruff format check' { & $python -m ruff format --check . }
Invoke-Checked 'Python tests' { & $python -m pytest -q }
Invoke-Checked 'Frontend tests' { npm test }

Write-Host 'All verification checks passed.'
