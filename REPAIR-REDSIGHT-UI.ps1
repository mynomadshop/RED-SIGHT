$ErrorActionPreference = "Stop"

$Root       = "C:\Users\walim\RedSight"
$Venv       = Join-Path $Root ".venv"
$Python     = Join-Path $Venv "Scripts\python.exe"
$PythonW    = Join-Path $Venv "Scripts\pythonw.exe"

$LauncherPS = Join-Path $Root "START-REDSIGHT-UI.ps1"
$LauncherBAT = Join-Path $Root "START-REDSIGHT.bat"
$Shortcut   = "C:\Users\walim\Desktop\RedSight.lnk"

$StdoutLog  = Join-Path $Root "redsight-ui.stdout.log"
$StderrLog  = Join-Path $Root "redsight-ui.stderr.log"
$DetectLog  = Join-Path $Root "redsight-ui-detection.txt"

Write-Host ""
Write-Host "============================================================"
Write-Host " REDSIGHT UI ENTRY-POINT REPAIR"
Write-Host "============================================================"
Write-Host ""

Set-Location $Root


# ============================================================
# 1. VERIFY WINDOWS VENV
# ============================================================

Write-Host "[1/10] Checking isolated RedSight environment..."

if (!(Test-Path $Python)) {
    throw "RedSight venv Python missing: $Python"
}

Write-Host "Python:"
Write-Host "  $Python"

& $Python -I -c "import sys; print(sys.executable); print(sys.version)"

if ($LASTEXITCODE -ne 0) {
    throw "RedSight Python environment cannot start."
}

Write-Host ""


# ============================================================
# 2. REMOVE HERMES / GLOBAL PYTHON CONTAMINATION
# ============================================================

Write-Host "[2/10] Clearing external Python environment contamination..."

$env:PYTHONPATH = $null
$env:PYTHONHOME = $null
$env:PYTHONNOUSERSITE = "1"

Write-Host "PYTHONPATH     = CLEARED"
Write-Host "PYTHONHOME     = CLEARED"
Write-Host "PYTHONNOUSERSITE = 1"
Write-Host ""


# ============================================================
# 3. VERIFY PYSIDE6 + QASYNC ON WINDOWS
# ============================================================

Write-Host "[3/10] Testing PySide6 desktop dependencies..."

& $Python -I -c @"
import sys
print("Python:", sys.executable)

import PySide6
print("PySide6:", PySide6.__version__)

from PySide6.QtWidgets import QApplication, QMainWindow
print("QtWidgets: OK")

import qasync
print("qasync: OK")
"@

if ($LASTEXITCODE -ne 0) {

    Write-Host ""
    Write-Host "Repairing Windows UI dependencies..."

    & $Python -m pip install --upgrade PySide6 qasync

    if ($LASTEXITCODE -ne 0) {
        throw "Could not repair PySide6/qasync."
    }

    & $Python -I -c "import PySide6, qasync; from PySide6.QtWidgets import QApplication; print('UI dependencies repaired')"

    if ($LASTEXITCODE -ne 0) {
        throw "UI dependencies still cannot import."
    }
}

Write-Host ""
Write-Host "PySide6 desktop runtime: OK"
Write-Host ""


# ============================================================
# 4. SHOW REDSIGHT EXECUTABLES
# ============================================================

Write-Host "[4/10] Inspecting installed RedSight executables..."

$InstalledExecutables = @(
    Get-ChildItem "$Venv\Scripts" `
        -File `
        -Filter "redsight*.exe" `
        -ErrorAction SilentlyContinue
)

if ($InstalledExecutables.Count -gt 0) {

    $InstalledExecutables |
        Select-Object Name,FullName |
        Format-Table -AutoSize

}

Write-Host ""
Write-Host "IMPORTANT: benchmark executables will NOT be used."
Write-Host ""


# ============================================================
# 5. SEARCH SOURCE FOR ACTUAL QT APPLICATION
# ============================================================

Write-Host "[5/10] Searching source for actual QApplication entry point..."

$SearchRoots = @()

if (Test-Path "$Root\app") {
    $SearchRoots += "$Root\app"
}

if (Test-Path "$Root\redsight") {
    $SearchRoots += "$Root\redsight"
}

if ($SearchRoots.Count -eq 0) {
    throw "Could not find app\ or redsight\ source directories."
}

$Files = @(
    Get-ChildItem `
        -Path $SearchRoots `
        -Recurse `
        -File `
        -Filter "*.py" `
        -ErrorAction SilentlyContinue
)

$Candidates = @()

foreach ($File in $Files) {

    $Text = Get-Content $File.FullName -Raw -ErrorAction SilentlyContinue

    if ([string]::IsNullOrWhiteSpace($Text)) {
        continue
    }

    $HasQApplication = $Text -match "\bQApplication\b"
    $HasQMainWindow  = $Text -match "\bQMainWindow\b"
    $HasQAsync       = $Text -match "\bqasync\b"
    $HasMainGuard    = $Text -match "__name__\s*==\s*['""]__main__['""]"
    $HasMainFunction = $Text -match "(?m)^\s*(async\s+)?def\s+main\s*\("

    if (
        $HasQApplication -or
        ($HasQMainWindow -and $HasMainGuard) -or
        ($HasQAsync -and $HasMainGuard)
    ) {

        $Score = 0

        if ($HasQApplication) { $Score += 500 }
        if ($HasMainGuard)    { $Score += 250 }
        if ($HasMainFunction) { $Score += 150 }
        if ($HasQAsync)       { $Score += 100 }
        if ($HasQMainWindow)  { $Score += 50 }

        if ($File.FullName -match "\\ui\\") {
            $Score += 200
        }

        if ($File.Name -eq "main.py") {
            $Score += 150
        }

        if ($File.Name -match "desktop") {
            $Score += 125
        }

        if ($File.Name -match "launcher") {
            $Score += 100
        }

        if ($File.Name -eq "__main__.py") {
            $Score += 125
        }


        # Heavily reject non-UI code

        if ($File.FullName -match "\\tests?\\") {
            $Score -= 2000
        }

        if ($File.FullName -match "benchmark") {
            $Score -= 2000
        }

        if ($File.FullName -match "test_") {
            $Score -= 2000
        }

        if ($File.FullName -match "\\server\.py$") {
            $Score -= 1000
        }

        if ($File.FullName -match "\\api\\") {
            $Score -= 500
        }


        $Relative = $File.FullName.Substring($Root.Length + 1)

        $Module = $Relative `
            -replace "\.py$", "" `
            -replace "\\", "."


        $Candidates += [PSCustomObject]@{
            Score        = $Score
            Module       = $Module
            File         = $File.FullName
            QApplication = $HasQApplication
            MainGuard    = $HasMainGuard
            MainFunction = $HasMainFunction
            QAsync       = $HasQAsync
        }
    }
}


$Candidates = @(
    $Candidates |
        Where-Object { $_.Score -gt 0 } |
        Sort-Object Score -Descending
)


Write-Host ""

if ($Candidates.Count -gt 0) {

    Write-Host "Potential GUI entry points:"
    Write-Host ""

    $Candidates |
        Select-Object -First 15 `
            Score,Module,QApplication,MainGuard,MainFunction,QAsync |
        Format-Table -AutoSize

    $Candidates |
        Format-List * |
        Out-File $DetectLog -Encoding utf8
}


# ============================================================
# 6. SELECT REAL GUI ENTRY POINT
# ============================================================

Write-Host ""
Write-Host "[6/10] Selecting RedSight desktop UI..."

$LaunchKind = $null
$LaunchTarget = $null


# First: explicit GUI executables ONLY.
# Do NOT accept redsight-benchmark.exe or arbitrary redsight*.exe.

$ExplicitGuiExeNames = @(
    "redsight-ui.exe",
    "redsight-gui.exe",
    "redsight-desktop.exe"
)

foreach ($Name in $ExplicitGuiExeNames) {

    $CandidateExe = Join-Path "$Venv\Scripts" $Name

    if (Test-Path $CandidateExe) {

        $LaunchKind = "exe"
        $LaunchTarget = $CandidateExe
        break
    }
}


# If no explicit GUI executable, use detected QApplication module.

if (-not $LaunchTarget) {

    if ($Candidates.Count -gt 0) {

        $LaunchKind = "module"
        $LaunchTarget = $Candidates[0].Module

    }
}


if (-not $LaunchTarget) {

    Write-Host ""
    Write-Host "No automatic QApplication entry point was found."
    Write-Host ""
    Write-Host "Searching for Qt-related source:"
    Write-Host ""

    Get-ChildItem $SearchRoots -Recurse -File -Filter "*.py" |
        Select-String `
            -Pattern "QApplication|QMainWindow|qasync" |
        Select-Object Path,LineNumber,Line |
        Format-Table -AutoSize

    throw "Could not identify the actual RedSight desktop UI entry point."
}


Write-Host ""
Write-Host "SELECTED GUI:"
Write-Host ""
Write-Host "  Type   : $LaunchKind"
Write-Host "  Target : $LaunchTarget"
Write-Host ""

if ($LaunchTarget -match "benchmark") {
    throw "Safety check rejected benchmark executable."
}


# ============================================================
# 7. CREATE PERMANENT WINDOWS UI LAUNCHER
# ============================================================

Write-Host "[7/10] Creating permanent RedSight UI launcher..."


$PermanentLauncher = @"
`$ErrorActionPreference = "Continue"

`$Root      = "C:\Users\walim\RedSight"
`$Python    = "C:\Users\walim\RedSight\.venv\Scripts\python.exe"
`$Target    = "$LaunchTarget"
`$Kind      = "$LaunchKind"

`$StdoutLog = "C:\Users\walim\RedSight\redsight-ui.stdout.log"
`$StderrLog = "C:\Users\walim\RedSight\redsight-ui.stderr.log"

Set-Location `$Root

# Isolate from Hermes/global Python variables
`$env:PYTHONPATH = `$null
`$env:PYTHONHOME = `$null
`$env:PYTHONNOUSERSITE = "1"

Clear-Content `$StdoutLog -ErrorAction SilentlyContinue
Clear-Content `$StderrLog -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "============================================================"
Write-Host " REDSIGHT DESKTOP"
Write-Host "============================================================"
Write-Host ""
Write-Host "Starting Docker backend..."

docker compose up -d

Write-Host ""
Write-Host "Waiting for API..."

`$ApiReady = `$false

for (`$i = 1; `$i -le 30; `$i++) {

    try {

        `$Response = Invoke-WebRequest `
            -Uri "http://127.0.0.1:8000/api/v1/health" `
            -UseBasicParsing `
            -TimeoutSec 2 `
            -ErrorAction Stop

        if (`$Response.StatusCode -ge 200 -and `$Response.StatusCode -lt 500) {
            `$ApiReady = `$true
            break
        }

    }
    catch {}

    Start-Sleep -Seconds 1
}

Write-Host ""

if (`$ApiReady) {
    Write-Host "RedSight backend: READY"
}

if (-not `$ApiReady) {
    Write-Warning "Backend health endpoint did not answer yet."
}

Write-Host ""
Write-Host "Launching desktop UI..."
Write-Host "Target: `$Target"
Write-Host ""


if (`$Kind -eq "module") {

    `$Process = Start-Process `
        -FilePath `$Python `
        -ArgumentList @("-m", `$Target) `
        -WorkingDirectory `$Root `
        -RedirectStandardOutput `$StdoutLog `
        -RedirectStandardError `$StderrLog `
        -PassThru

}


if (`$Kind -eq "exe") {

    `$Process = Start-Process `
        -FilePath `$Target `
        -WorkingDirectory `$Root `
        -RedirectStandardOutput `$StdoutLog `
        -RedirectStandardError `$StderrLog `
        -PassThru

}


Start-Sleep -Seconds 5

`$Process.Refresh()


if (`$Process.HasExited) {

    Write-Host ""
    Write-Host "============================================================"
    Write-Host " REDSIGHT UI CRASHED DURING STARTUP"
    Write-Host "============================================================"
    Write-Host ""

    Write-Host "Exit code:"
    Write-Host "  `$(`$Process.ExitCode)"
    Write-Host ""

    Write-Host "---------------- STDERR ----------------"
    Write-Host ""

    if (Test-Path `$StderrLog) {
        Get-Content `$StderrLog -Tail 250
    }

    Write-Host ""
    Write-Host "---------------- STDOUT ----------------"
    Write-Host ""

    if (Test-Path `$StdoutLog) {
        Get-Content `$StdoutLog -Tail 250
    }

    Write-Host ""
    Write-Host "Logs:"
    Write-Host "  `$StderrLog"
    Write-Host "  `$StdoutLog"
    Write-Host ""

    Read-Host "Press ENTER to close"

}


if (-not `$Process.HasExited) {

    Write-Host "RedSight UI process is running."
    Write-Host ""
    Write-Host "PID:"
    Write-Host "  `$(`$Process.Id)"
    Write-Host ""
}

"@


[System.IO.File]::WriteAllText(
    $LauncherPS,
    $PermanentLauncher,
    (New-Object System.Text.UTF8Encoding($false))
)


# ============================================================
# 8. CREATE SIMPLE BAT
# ============================================================

Write-Host "[8/10] Rebuilding START-REDSIGHT.bat..."

$Batch = @"
@echo off
title RedSight
cd /d "C:\Users\walim\RedSight"

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "C:\Users\walim\RedSight\START-REDSIGHT-UI.ps1"
"@

[System.IO.File]::WriteAllText(
    $LauncherBAT,
    $Batch,
    [System.Text.Encoding]::ASCII
)


# ============================================================
# 9. RECREATE DESKTOP SHORTCUT
# ============================================================

Write-Host "[9/10] Recreating Desktop shortcut..."

if (Test-Path $Shortcut) {
    Remove-Item $Shortcut -Force
}

$WShell = New-Object -ComObject WScript.Shell
$Link = $WShell.CreateShortcut($Shortcut)

$Link.TargetPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"

$Link.Arguments = '-NoLogo -NoProfile -ExecutionPolicy Bypass -File "C:\Users\walim\RedSight\START-REDSIGHT-UI.ps1"'

$Link.WorkingDirectory = $Root
$Link.Description = "RedSight Desktop"
$Link.WindowStyle = 1

$Link.Save()


Write-Host ""
Write-Host "Shortcut recreated:"
Write-Host "  $Shortcut"
Write-Host ""


# ============================================================
# 10. LAUNCH
# ============================================================

Write-Host "[10/10] Launching repaired RedSight UI..."
Write-Host ""

Start-Process `
    -FilePath "powershell.exe" `
    -ArgumentList @(
        "-NoLogo",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        "`"$LauncherPS`""
    ) `
    -WorkingDirectory $Root


Write-Host ""
Write-Host "============================================================"
Write-Host " REPAIR COMPLETE"
Write-Host "============================================================"
Write-Host ""
Write-Host "Selected UI:"
Write-Host "  $LaunchTarget"
Write-Host ""
Write-Host "Desktop shortcut:"
Write-Host "  $Shortcut"
Write-Host ""
Write-Host "Permanent launcher:"
Write-Host "  $LauncherPS"
Write-Host ""
