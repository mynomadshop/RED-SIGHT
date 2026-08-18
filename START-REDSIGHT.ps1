param(
    [switch]$Restart
)

$ErrorActionPreference = "Stop"

$Root         = "C:\Users\walim\RedSight"
$UiPython     = Join-Path $Root ".venv-ui\Scripts\python.exe"
$UiPythonW    = Join-Path $Root ".venv-ui\Scripts\pythonw.exe"
$ActionPython = Join-Path $Root ".venv-actions\Scripts\python.exe"
$Launcher     = Join-Path $Root "launch_redsight_command_center.py"
$UiExe        = $(if (Test-Path $UiPythonW) { $UiPythonW } else { $UiPython })

$LogDir = Join-Path $env:LOCALAPPDATA "RedSight\logs"
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$Log = Join-Path $LogDir "launcher-$Stamp.log"

function Write-RSLog {
    param([string]$Message)
    $Line = "$(Get-Date -Format s)  $Message"
    Add-Content -Path $Log -Value $Line -Encoding UTF8
    Write-Host $Message
}

function Test-Http200 {
    param([Parameter(Mandatory=$true)][string]$Url)

    $Old = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $Code = curl.exe -s -o NUL -w "%{http_code}" --max-time 4 $Url 2>$null
    $ErrorActionPreference = $Old

    return ($Code -eq "200")
}

function Wait-Http200 {
    param(
        [Parameter(Mandatory=$true)][string]$Url,
        [int]$Attempts = 60,
        [int]$DelayMs = 1000
    )

    for ($i = 1; $i -le $Attempts; $i++) {
        if (Test-Http200 $Url) {
            return $true
        }
        Start-Sleep -Milliseconds $DelayMs
    }
    return $false
}

function Stop-RedSightPython {
    param(
        [switch]$UI,
        [switch]$Gateway
    )

    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            if ($_.Name -notmatch '^python(w)?\.exe$' -or -not $_.CommandLine) {
                return $false
            }

            $Match = $false

            if ($UI -and (
                $_.CommandLine -match 'launch_redsight_command_center\.py' -or
                $_.CommandLine -match 'app\.ui\.command_center'
            )) {
                $Match = $true
            }

            if ($Gateway -and $_.CommandLine -match 'redsight_actions\.gateway(?:_stage9|_stage91|_stage10)?\:app') {
                $Match = $true
            }

            return $Match
        } |
        ForEach-Object {
            Write-RSLog "Stopping RedSight Python PID $($_.ProcessId)"
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
}

foreach ($Required in @($UiPython, $ActionPython, $Launcher)) {
    if (-not (Test-Path $Required)) {
        throw "Required RedSight runtime component missing: $Required"
    }
}

Set-Location $Root

# Hard isolation from unrelated/global Python environments.
$env:PYTHONPATH = $null
$env:PYTHONHOME = $null
$env:PYTHONNOUSERSITE = "1"

# RedSight host-side LM Studio contract.
$env:LM_STUDIO_URL = "http://127.0.0.1:1234"
$env:LM_STUDIO_BASE_URL = "http://127.0.0.1:1234/v1"
$env:LM_BASE_URL = "http://127.0.0.1:1234/v1"

Write-RSLog "============================================================"
Write-RSLog "REDSIGHT UNIFIED LAUNCH"
Write-RSLog "Restart mode: $Restart"
Write-RSLog "============================================================"

if ($Restart) {
    Stop-RedSightPython -UI -Gateway
    Start-Sleep -Milliseconds 800
}

# Docker Desktop
$Old = $ErrorActionPreference
$ErrorActionPreference = "Continue"
docker info 1>$null 2>$null
$DockerExit = $LASTEXITCODE
$ErrorActionPreference = $Old

if ($DockerExit -ne 0) {
    Write-RSLog "Docker engine offline. Starting Docker Desktop."

    $DockerDesktop = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    if (Test-Path $DockerDesktop) {
        Start-Process $DockerDesktop | Out-Null
    }
    else {
        $Old = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        docker desktop start --detach 1>$null 2>$null
        $ErrorActionPreference = $Old
    }

    for ($i = 1; $i -le 75; $i++) {
        $Old = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        docker info 1>$null 2>$null
        $DockerExit = $LASTEXITCODE
        $ErrorActionPreference = $Old

        if ($DockerExit -eq 0) {
            break
        }
        Start-Sleep -Seconds 2
    }
}

if ($DockerExit -ne 0) {
    throw "Docker Desktop did not become available."
}

Write-RSLog "Docker=ONLINE"

# Qdrant - preserve existing data/volume.
$Old = $ErrorActionPreference
$ErrorActionPreference = "Continue"
docker compose up -d qdrant 1>>$Log 2>&1
$QExit = $LASTEXITCODE
$ErrorActionPreference = $Old
if ($QExit -ne 0) {
    throw "Could not start RedSight Qdrant."
}

if (-not (Wait-Http200 "http://127.0.0.1:6333/readyz" 60 1000)) {
    # readyz is plain text and may still be 200; curl status test handles that.
    throw "Qdrant did not reach ready state."
}
Write-RSLog "Qdrant=HEALTHY"

# LM Studio - prefer the CLI server, then the desktop app.
$LmReady = Test-Http200 "http://127.0.0.1:1234/v1/models"

if (-not $LmReady) {
    $LmsCommand = Get-Command "lms.exe" -ErrorAction SilentlyContinue
    if (-not $LmsCommand) {
        $LmsCommand = Get-Command "lms" -ErrorAction SilentlyContinue
    }

    if ($LmsCommand) {
        Write-RSLog "Starting LM Studio Local Server with lms on port 1234."
        $Old = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        Start-Process `
            -FilePath $LmsCommand.Source `
            -ArgumentList @("server","start","--port","1234") `
            -WindowStyle Hidden | Out-Null
        $ErrorActionPreference = $Old
        $LmReady = Wait-Http200 "http://127.0.0.1:1234/v1/models" 45 1000
    }
}

if (-not $LmReady) {
    $LmCandidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\LM Studio\LM Studio.exe"),
        (Join-Path $env:LOCALAPPDATA "LM Studio\LM Studio.exe"),
        (Join-Path $env:LOCALAPPDATA "LM-Studio\LM Studio.exe"),
        (Join-Path $env:ProgramFiles "LM Studio\LM Studio.exe")
    ) | Where-Object { Test-Path $_ }

    if ($LmCandidates.Count -gt 0) {
        Write-RSLog "Starting LM Studio desktop: $($LmCandidates[0])"
        Start-Process $LmCandidates[0] | Out-Null
        $LmReady = Wait-Http200 "http://127.0.0.1:1234/v1/models" 90 1000
    }
}

if ($LmReady) {
    Write-RSLog "LM Studio=CONNECTED http://127.0.0.1:1234/v1"
}
else {
    Write-RSLog "LM Studio=NOT CONNECTED. Start LM Studio Local Server on port 1234."
}

# RedSight backend.
$BackendExists = $false
$Old = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$ContainerName = docker ps -a --format "{{.Names}}" 2>$null | Where-Object { $_ -eq "redsight" }
$ErrorActionPreference = $Old
$BackendExists = [bool]$ContainerName

$Old = $ErrorActionPreference
$ErrorActionPreference = "Continue"
if ($Restart -and $BackendExists) {
    docker compose restart redsight 1>>$Log 2>&1
}
else {
    docker compose up -d redsight 1>>$Log 2>&1
}
$BackendStartExit = $LASTEXITCODE
$ErrorActionPreference = $Old

if ($BackendStartExit -ne 0) {
    throw "Could not start/restart RedSight backend."
}

if (-not (Wait-Http200 "http://127.0.0.1:8000/api/v1/health" 90 1500)) {
    $Old = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    docker logs --tail 250 redsight 1>>$Log 2>&1
    $ErrorActionPreference = $Old
    throw "RedSight backend failed health validation. See $Log"
}
Write-RSLog "RedSight backend=HEALTHY"

# Confirm the Linux container can reach the Windows-host LM Studio server.
if ($LmReady) {
    $Old = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $ContainerLmCode = docker exec redsight curl -s -o /dev/null -w "%{http_code}" --max-time 6 http://host.docker.internal:1234/v1/models 2>$null
    $ContainerLmExit = $LASTEXITCODE
    $ErrorActionPreference = $Old

    if (($ContainerLmExit -eq 0) -and ($ContainerLmCode -eq "200")) {
        Write-RSLog "RedSight container -> LM Studio=CONNECTED"
    }
    else {
        Write-RSLog "WARNING: Host LM Studio is reachable but RedSight container cannot reach host.docker.internal:1234/v1."
    }
}

# Action / memory gateway.
if ($Restart) {
    Stop-RedSightPython -Gateway
}

if (-not (Test-Http200 "http://127.0.0.1:8765/memory/status")) {
    $GatewayOut = Join-Path $LogDir "gateway-$Stamp.stdout.log"
    $GatewayErr = Join-Path $LogDir "gateway-$Stamp.stderr.log"

    Write-RSLog "Starting RedSight Stage 10 action/memory gateway."

    Start-Process `
        -FilePath $ActionPython `
        -ArgumentList @(
            "-m",
            "uvicorn",
            "redsight_actions.gateway_stage10:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8765",
            "--log-level",
            "warning"
        ) `
        -WorkingDirectory $Root `
        -WindowStyle Hidden `
        -RedirectStandardOutput $GatewayOut `
        -RedirectStandardError $GatewayErr | Out-Null
}

if (-not (Wait-Http200 "http://127.0.0.1:8765/memory/status" 60 500)) {
    throw "RedSight action/memory gateway did not become healthy."
}
Write-RSLog "Action/Memory gateway=HEALTHY"

# Always keep one Command Center UI process.
Stop-RedSightPython -UI
Start-Sleep -Milliseconds 500

$UiOut = Join-Path $LogDir "command-center-$Stamp.stdout.log"
$UiErr = Join-Path $LogDir "command-center-$Stamp.stderr.log"

$UiProcess = Start-Process `
    -FilePath $UiExe `
    -ArgumentList ('"' + $Launcher + '"') `
    -WorkingDirectory $Root `
    -RedirectStandardOutput $UiOut `
    -RedirectStandardError $UiErr `
    -PassThru

if ($null -eq $UiProcess) {
    throw "Command Center process was not created."
}

for ($i = 1; $i -le 12; $i++) {
    Start-Sleep -Seconds 1
    $UiProcess.Refresh()
    if ($UiProcess.HasExited) {
        throw "Command Center exited during startup. See $UiErr"
    }
}

# Best-effort foreground restore.
try {
    Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class RedSightWindowNative {
    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);
}
"@ -ErrorAction SilentlyContinue

    for ($i = 1; $i -le 12; $i++) {
        $Live = Get-Process -Id $UiProcess.Id -ErrorAction SilentlyContinue
        if ($Live) {
            $Live.Refresh()
            if ($Live.MainWindowHandle -ne 0) {
                [RedSightWindowNative]::ShowWindow($Live.MainWindowHandle, 9) | Out-Null
                [RedSightWindowNative]::SetForegroundWindow($Live.MainWindowHandle) | Out-Null
                break
            }
        }
        Start-Sleep -Milliseconds 500
    }
}
catch {
    Write-RSLog "Foreground restore skipped: $($_.Exception.Message)"
}

Write-RSLog "Command Center=RUNNING PID $($UiProcess.Id)"
Write-RSLog "Unified launch complete."
