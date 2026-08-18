$ErrorActionPreference = "Continue"

$Root      = "C:\Users\walim\RedSight"
$Python    = "C:\Users\walim\RedSight\.venv\Scripts\python.exe"
$Target    = "C:\Users\walim\RedSight\.venv\Scripts\redsight-ui.exe"
$Kind      = "exe"

$StdoutLog = "C:\Users\walim\RedSight\redsight-ui.stdout.log"
$StderrLog = "C:\Users\walim\RedSight\redsight-ui.stderr.log"

Set-Location $Root

# Isolate from Hermes/global Python variables
$env:PYTHONPATH = $null
$env:PYTHONHOME = $null
$env:PYTHONNOUSERSITE = "1"

Clear-Content $StdoutLog -ErrorAction SilentlyContinue
Clear-Content $StderrLog -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "============================================================"
Write-Host " REDSIGHT DESKTOP"
Write-Host "============================================================"
Write-Host ""
Write-Host "Starting Docker backend..."

docker compose up -d

Write-Host ""
Write-Host "Waiting for API..."

$ApiReady = $false

for ($i = 1; $i -le 30; $i++) {

    try {

        $Response = Invoke-WebRequest 
            -Uri "http://127.0.0.1:8000/api/v1/health" 
            -UseBasicParsing 
            -TimeoutSec 2 
            -ErrorAction Stop

        if ($Response.StatusCode -ge 200 -and $Response.StatusCode -lt 500) {
            $ApiReady = $true
            break
        }

    }
    catch {}

    Start-Sleep -Seconds 1
}

Write-Host ""

if ($ApiReady) {
    Write-Host "RedSight backend: READY"
}

if (-not $ApiReady) {
    Write-Warning "Backend health endpoint did not answer yet."
}

Write-Host ""
Write-Host "Launching desktop UI..."
Write-Host "Target: $Target"
Write-Host ""


if ($Kind -eq "module") {

    $Process = Start-Process 
        -FilePath $Python 
        -ArgumentList @("-m", $Target) 
        -WorkingDirectory $Root 
        -RedirectStandardOutput $StdoutLog 
        -RedirectStandardError $StderrLog 
        -PassThru

}


if ($Kind -eq "exe") {

    $Process = Start-Process 
        -FilePath $Target 
        -WorkingDirectory $Root 
        -RedirectStandardOutput $StdoutLog 
        -RedirectStandardError $StderrLog 
        -PassThru

}


Start-Sleep -Seconds 5

$Process.Refresh()


if ($Process.HasExited) {

    Write-Host ""
    Write-Host "============================================================"
    Write-Host " REDSIGHT UI CRASHED DURING STARTUP"
    Write-Host "============================================================"
    Write-Host ""

    Write-Host "Exit code:"
    Write-Host "  $($Process.ExitCode)"
    Write-Host ""

    Write-Host "---------------- STDERR ----------------"
    Write-Host ""

    if (Test-Path $StderrLog) {
        Get-Content $StderrLog -Tail 250
    }

    Write-Host ""
    Write-Host "---------------- STDOUT ----------------"
    Write-Host ""

    if (Test-Path $StdoutLog) {
        Get-Content $StdoutLog -Tail 250
    }

    Write-Host ""
    Write-Host "Logs:"
    Write-Host "  $StderrLog"
    Write-Host "  $StdoutLog"
    Write-Host ""

    Read-Host "Press ENTER to close"

}


if (-not $Process.HasExited) {

    Write-Host "RedSight UI process is running."
    Write-Host ""
    Write-Host "PID:"
    Write-Host "  $($Process.Id)"
    Write-Host ""
}
