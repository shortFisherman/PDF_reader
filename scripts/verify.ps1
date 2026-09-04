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

    $pythonVersion = [string]$pythonInfo[1]
    $pythonParts = $pythonVersion.Split('.')
    $pythonMajorMinor = if ($pythonParts.Length -ge 2) {
        [int]$pythonParts[0] * 100 + [int]$pythonParts[1]
    } else {
        0
    }
    if ($pythonMajorMinor -lt 312) {
        throw "Unsupported Python version $pythonVersion (>= 3.12 required). Fix the interpreter or pass -PythonExecutable."
    }

    $nodeVersionRaw = & node --version 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $nodeVersionRaw) {
        throw "Node.js not found or failed to report its version; Node.js >= 22 is required for frontend tests."
    }
    Write-Host "Node version: $nodeVersionRaw"
    $nodeMajorText = ([string]$nodeVersionRaw).TrimStart('v')
    $nodeMajor = 0
    if ($nodeMajorText -match '^\d+') {
        $nodeMajor = [int]($nodeMajorText -split '\.')[0]
    }
    if ($nodeMajor -lt 22) {
        throw "Unsupported Node.js version $nodeVersionRaw (>= 22 required)."
    }

    $coverageArtifactDir = $env:PDF_READER_COVERAGE_ARTIFACT_DIR
    $coverageDir = $coverageArtifactDir
    $tempCoverageDir = $null
    if (-not $coverageDir) {
        $tempCoverageDir = Join-Path $env:TEMP ('pdf-reader-coverage-' + [guid]::NewGuid().ToString('N'))
        $coverageDir = $tempCoverageDir
    }
    New-Item -ItemType Directory -Path $coverageDir -Force | Out-Null
    $env:COVERAGE_FILE = Join-Path $coverageDir '.coverage'
    $coverageJson = Join-Path $coverageDir 'coverage.json'
    try {
        Invoke-Checked 'Secret scan' { & $pythonCommand scripts/secret_scan.py }
        Invoke-Checked 'Upgrade governance gate (static)' { & $pythonCommand scripts/upgrade_governance_gate.py --static-only }
        Invoke-Checked 'Portable runtime policy' { & $pythonCommand packaging/windows/runtime_policy.py --source-root . }
        Invoke-Checked 'Ruff lint' { & $pythonCommand -m ruff check . }
        Invoke-Checked 'Ruff format check' { & $pythonCommand -m ruff format --check . }
        Invoke-Checked 'Coverage + Python tests' { & $pythonCommand -m coverage run --branch -m pytest -q }
        Invoke-Checked 'Coverage report' { & $pythonCommand -m coverage report }
        Invoke-Checked 'Coverage JSON' { & $pythonCommand -m coverage json -o $coverageJson }
        Invoke-Checked 'Coverage policy' { & $pythonCommand scripts/check_coverage_policy.py $coverageJson }
        Invoke-Checked 'Term quality gate' { & $pythonCommand scripts/term_quality_gate.py }
        Invoke-Checked 'Mypy' { & $pythonCommand -m mypy }
        Invoke-Checked 'JS lint' { npm run lint:js }
        Invoke-Checked 'Frontend tests' { npm test }
        if ($coverageArtifactDir) {
            Invoke-Checked 'Coverage XML artifact' { & $pythonCommand -m coverage xml -o (Join-Path $coverageDir 'coverage.xml') }
        }
        Write-Host 'All verification checks passed.'
    } finally {
        Remove-Item Env:COVERAGE_FILE -ErrorAction SilentlyContinue
        if ($tempCoverageDir -and (Test-Path -LiteralPath $tempCoverageDir)) {
            Remove-Item -LiteralPath $tempCoverageDir -Recurse -Force
        }
    }
}
