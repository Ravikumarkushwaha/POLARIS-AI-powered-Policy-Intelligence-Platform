$ErrorActionPreference = "Stop"

$ProjectRoot = $PSScriptRoot
$RuntimeDir = Join-Path $ProjectRoot ".runtime"
$BackendDir = Join-Path $ProjectRoot "backend"
New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null

function Test-LocalPort([int]$Port) {
    return $null -ne (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

if (-not (Test-LocalPort 8001)) {
    # Prefer the same `python` command used for installation and tests. The
    # Windows `py` shim can exist even when its configured Python is missing.
    $Python = Get-Command python -ErrorAction Stop
    $PythonExecutable = $Python.Source
    # -B keeps disposable __pycache__ files out of the project on restarts.
    $PythonArguments = @("-B", "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8001")

    Start-Process -FilePath $PythonExecutable `
        -ArgumentList $PythonArguments `
        -WorkingDirectory $BackendDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $RuntimeDir "backend.stdout.log") `
        -RedirectStandardError (Join-Path $RuntimeDir "backend.stderr.log")
}

if (-not (Test-LocalPort 8080)) {
    $Npm = Get-Command npm.cmd -ErrorAction Stop
    Start-Process -FilePath $Npm.Source `
        -ArgumentList @("run", "dev", "--", "--host", "127.0.0.1", "--port", "8080", "--strictPort") `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $RuntimeDir "frontend.stdout.log") `
        -RedirectStandardError (Join-Path $RuntimeDir "frontend.stderr.log")
}

$BackendReady = $false
for ($Attempt = 0; $Attempt -lt 30; $Attempt++) {
    try {
        $Health = Invoke-RestMethod -Uri "http://127.0.0.1:8001/api/health" -TimeoutSec 2
        if ($Health.status -eq "ok") {
            $BackendReady = $true
            break
        }
    } catch {
        Start-Sleep -Milliseconds 500
    }
}

if (-not $BackendReady) {
    throw "Backend did not become healthy. See .runtime/backend.stderr.log"
}

Write-Host "POLARIS is running: http://127.0.0.1:8080"
Write-Host "Backend health: http://127.0.0.1:8001/api/health"
Write-Host "Interrupted analyses are resumed automatically after a restart."
