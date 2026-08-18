Set-Location "C:\Users\walim\RedSight"
$ErrorActionPreference = "Stop"

$Root          = "C:\Users\walim\RedSight"
$UiPython      = Join-Path $Root ".venv-ui\Scripts\python.exe"
$ActionPython  = Join-Path $Root ".venv-actions\Scripts\python.exe"
$Launcher      = Join-Path $Root "launch_redsight_command_center.py"
$CommandCenter = Join-Path $Root "app\ui\command_center.py"
$Overlay103    = Join-Path $Root "app\ui\action_palette_stage103.py"
$Gateway10     = Join-Path $Root "redsight_actions\gateway_stage10.py"
$Compose       = Join-Path $Root "docker-compose.yml"
$ComposeOver   = Join-Path $Root "docker-compose.override.yml"
$StartScript   = Join-Path $Root "START-REDSIGHT.ps1"
$RestartScript = Join-Path $Root "RESTART-REDSIGHT.ps1"
$Bat           = Join-Path $Root "START-REDSIGHT.bat"
$IconPath      = Join-Path $Root "assets\redsight.ico"
$DesktopLink   = "C:\Users\walim\Desktop\RedSight.lnk"
$StartMenuLink = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\RedSight.lnk"

$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$Backup = Join-Path $Root ".repair-backups\stage104-deep-restore-$Stamp"
New-Item -ItemType Directory -Path $Backup -Force | Out-Null

function Backup-IfExists {
    param([string]$Path)
    if (Test-Path -LiteralPath $Path) {
        Copy-Item -LiteralPath $Path -Destination (Join-Path $Backup ((Split-Path $Path -Leaf) + ".before")) -Force
    }
}

function Invoke-NativeChecked {
    param(
        [Parameter(Mandatory=$true)][string]$Exe,
        [Parameter(Mandatory=$false)][string[]]$Arguments = @(),
        [Parameter(Mandatory=$true)][string]$Label
    )
    $Old = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $Exe @Arguments
    $Code = $LASTEXITCODE
    $ErrorActionPreference = $Old
    if ($Code -ne 0) {
        throw "$Label failed with exit code $Code."
    }
}

function Test-Http200 {
    param(
        [Parameter(Mandatory=$true)][string]$Url,
        [int]$TimeoutSeconds = 5
    )
    $Old = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $Code = (& curl.exe -s -o NUL -w "%{http_code}" --max-time $TimeoutSeconds $Url 2>$null) -join ""
    $Exit = $LASTEXITCODE
    $ErrorActionPreference = $Old
    return (($Exit -eq 0) -and ($Code.Trim() -eq "200"))
}

function Wait-Http200 {
    param(
        [Parameter(Mandatory=$true)][string]$Url,
        [int]$Attempts = 60,
        [int]$DelayMilliseconds = 1000
    )
    for ($i=1; $i -le $Attempts; $i++) {
        if (Test-Http200 -Url $Url -TimeoutSeconds 5) { return $true }
        Write-Host "Waiting for $Url ... $i/$Attempts"
        Start-Sleep -Milliseconds $DelayMilliseconds
    }
    return $false
}

function Write-Base64Utf8 {
    param([string]$Path,[string]$Data)
    $Bytes = [Convert]::FromBase64String($Data)
    [System.IO.File]::WriteAllBytes($Path,$Bytes)
}

Write-Host ""
Write-Host "======================================================================"
Write-Host " REDSIGHT STAGE 10.4"
Write-Host " DEEP RESTORE + BRANDED LAUNCHER + LM STUDIO BACKEND"
Write-Host "======================================================================"
Write-Host ""
Write-Host "Backup: $Backup"
Write-Host ""

# ----------------------------------------------------------------------
# 1. Preserve current working state
# ----------------------------------------------------------------------
foreach ($Path in @(
    $Launcher,$CommandCenter,$Overlay103,$Compose,$ComposeOver,
    $StartScript,$RestartScript,$Bat,$IconPath,$DesktopLink,$StartMenuLink
)) {
    Backup-IfExists $Path
}
Write-Host "[1/12] BACKUP=PASS"

# ----------------------------------------------------------------------
# 2. Required known-good Stage 10 runtime
# ----------------------------------------------------------------------
foreach ($Required in @($UiPython,$ActionPython,$Launcher,$CommandCenter,$Gateway10,$Compose)) {
    if (-not (Test-Path -LiteralPath $Required)) {
        throw "Missing required RedSight runtime component: $Required"
    }
}
Write-Host "[2/12] RUNTIME_PATHS=PASS"

# ----------------------------------------------------------------------
# 3. Clear contamination only for this repair process
# ----------------------------------------------------------------------
$env:PYTHONPATH = $null
$env:PYTHONHOME = $null
$env:PYTHONNOUSERSITE = "1"
$env:LM_STUDIO_URL = "http://127.0.0.1:1234"
$env:LM_STUDIO_BASE_URL = "http://127.0.0.1:1234/v1"
$env:LM_BASE_URL = "http://127.0.0.1:1234/v1"
Write-Host "[3/12] PYTHON_ISOLATION=PASS"

# ----------------------------------------------------------------------
# 4. Repair only required UI dependencies
# ----------------------------------------------------------------------
$Old = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $UiPython -c "import PySide6,qasync,httpx,PIL; print('UI_DEPS=PASS')"
$UiDeps = $LASTEXITCODE
$ErrorActionPreference = $Old
if ($UiDeps -ne 0) {
    Invoke-NativeChecked -Exe $UiPython -Arguments @(
        "-m","pip","install","--disable-pip-version-check",
        "PySide6>=6.8,<7","qasync>=0.28,<1","httpx>=0.28,<1","Pillow>=10,<13"
    ) -Label "UI dependency repair"
}
Write-Host "[4/12] UI_DEPENDENCIES=PASS"

# ----------------------------------------------------------------------
# 5. Generate REDSIGHT red-crosshair branding assets
# ----------------------------------------------------------------------
New-Item -ItemType Directory -Path (Join-Path $Root "assets") -Force | Out-Null
$IconPy = Join-Path $Backup "build-redsight-icon.py"
Write-Base64Utf8 -Path $IconPy -Data "CmZyb20gcGF0aGxpYiBpbXBvcnQgUGF0aApmcm9tIFBJTCBpbXBvcnQgSW1hZ2UsIEltYWdlRHJhdywgSW1hZ2VGb250CgpST09UID0gUGF0aChyIkM6XFVzZXJzXHdhbGltXFJlZFNpZ2h0IikKQVNTRVRTID0gUk9PVCAvICJhc3NldHMiCkFTU0VUUy5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCklDTyA9IEFTU0VUUyAvICJyZWRzaWdodC5pY28iClBORyA9IEFTU0VUUyAvICJyZWRzaWdodC1icmFuZC5wbmciCgpTID0gNTEyCmltZyA9IEltYWdlLm5ldygiUkdCQSIsIChTLCBTKSwgKDgsIDEwLCAxNCwgMjU1KSkKZCA9IEltYWdlRHJhdy5EcmF3KGltZykKCnJlZCA9ICgyMjAsIDI0LCA0NSwgMjU1KQpyZWQyID0gKDEzMiwgMTIsIDI1LCAyNTUpCndoaXRlID0gKDI0NSwgMjQ3LCAyNTAsIDI1NSkKbXV0ZWQgPSAoMTIwLCAxMjgsIDEzOCwgMjU1KQoKY3ggPSBjeSA9IFMgLy8gMgpvdXRlciA9IDE3Mgppbm5lciA9IDkyCmx3ID0gMTgKCiMgY29uY2VudHJpYyBzaWdodCByaW5ncwpkLmVsbGlwc2UoKGN4LW91dGVyLCBjeS1vdXRlciwgY3grb3V0ZXIsIGN5K291dGVyKSwgb3V0bGluZT1yZWQyLCB3aWR0aD0xMikKZC5lbGxpcHNlKChjeC1pbm5lciwgY3ktaW5uZXIsIGN4K2lubmVyLCBjeStpbm5lciksIG91dGxpbmU9cmVkLCB3aWR0aD1sdykKCiMgY3Jvc3NoYWlyIGdhcHMgdGhyb3VnaCB0aGUgY2VudGVyCmdhcCA9IDM2CmFybSA9IDIxMApkLmxpbmUoKGN4LCBjeS1hcm0sIGN4LCBjeS1nYXApLCBmaWxsPXJlZCwgd2lkdGg9bHcpCmQubGluZSgoY3gsIGN5K2dhcCwgY3gsIGN5K2FybSksIGZpbGw9cmVkLCB3aWR0aD1sdykKZC5saW5lKChjeC1hcm0sIGN5LCBjeC1nYXAsIGN5KSwgZmlsbD1yZWQsIHdpZHRoPWx3KQpkLmxpbmUoKGN4K2dhcCwgY3ksIGN4K2FybSwgY3kpLCBmaWxsPXJlZCwgd2lkdGg9bHcpCgojIGNlbnRlciBkb3QKZC5lbGxpcHNlKChjeC0xOCwgY3ktMTgsIGN4KzE4LCBjeSsxOCksIGZpbGw9cmVkKQoKIyBSUyBtb25vZ3JhbSB1bmRlciBzaWdodApmb250X3BhdGhzID0gWwogICAgUGF0aChyIkM6XFdpbmRvd3NcRm9udHNcc2Vnb2V1aWIudHRmIiksCiAgICBQYXRoKHIiQzpcV2luZG93c1xGb250c1xhcmlhbGJkLnR0ZiIpLApdCmZvbnQgPSBOb25lCmZvciBmcCBpbiBmb250X3BhdGhzOgogICAgaWYgZnAuZXhpc3RzKCk6CiAgICAgICAgZm9udCA9IEltYWdlRm9udC50cnVldHlwZShzdHIoZnApLCA2NikKICAgICAgICBicmVhawppZiBmb250IGlzIE5vbmU6CiAgICBmb250ID0gSW1hZ2VGb250LmxvYWRfZGVmYXVsdCgpCgpsYWJlbCA9ICJSRURTSUdIVCIKYmJveCA9IGQudGV4dGJib3goKDAsIDApLCBsYWJlbCwgZm9udD1mb250KQp0dyA9IGJib3hbMl0gLSBiYm94WzBdCnRoID0gYmJveFszXSAtIGJib3hbMV0KeSA9IFMgLSB0aCAtIDM0CmQucmVjdGFuZ2xlKCgwLCB5LTE4LCBTLCBTKSwgZmlsbD0oOCwxMCwxNCwyMzUpKQpkLnRleHQoKChTLXR3KS8vMiwgeSksIGxhYmVsLCBmb250PWZvbnQsIGZpbGw9d2hpdGUpCgppbWcuc2F2ZShQTkcpCmltZy5zYXZlKAogICAgSUNPLAogICAgZm9ybWF0PSJJQ08iLAogICAgc2l6ZXM9WygxNiwxNiksKDI0LDI0KSwoMzIsMzIpLCg0OCw0OCksKDY0LDY0KSwoMTI4LDEyOCksKDI1NiwyNTYpXSwKKQpwcmludChmIlJFRFNJR0hUX0lDT049e0lDT30iKQpwcmludChmIlJFRFNJR0hUX0JSQU5EX1BORz17UE5HfSIpCg=="
Invoke-NativeChecked -Exe $UiPython -Arguments @($IconPy) -Label "RedSight icon generation"
if (-not (Test-Path $IconPath)) { throw "RedSight icon was not created." }
Write-Host "[5/12] CROSSHAIR_ICON=PASS"

# ----------------------------------------------------------------------
# 6. Patch only the live Command Center launcher for app/title/taskbar icon
# ----------------------------------------------------------------------
$BrandPy = Join-Path $Backup "patch-redsight-branding.py"
Write-Base64Utf8 -Path $BrandPy -Data "CmZyb20gX19mdXR1cmVfXyBpbXBvcnQgYW5ub3RhdGlvbnMKZnJvbSBwYXRobGliIGltcG9ydCBQYXRoCmltcG9ydCBhc3QKaW1wb3J0IHJlCmltcG9ydCBzaHV0aWwKaW1wb3J0IHRpbWUKClJPT1QgPSBQYXRoKHIiQzpcVXNlcnNcd2FsaW1cUmVkU2lnaHQiKQpMQVVOQ0hFUiA9IFJPT1QgLyAibGF1bmNoX3JlZHNpZ2h0X2NvbW1hbmRfY2VudGVyLnB5IgpJQ09OID0gUk9PVCAvICJhc3NldHMiIC8gInJlZHNpZ2h0LmljbyIKCmlmIG5vdCBMQVVOQ0hFUi5leGlzdHMoKToKICAgIHJhaXNlIFJ1bnRpbWVFcnJvcihmIk1pc3NpbmcgbGF1bmNoZXI6IHtMQVVOQ0hFUn0iKQoKdGV4dCA9IExBVU5DSEVSLnJlYWRfdGV4dChlbmNvZGluZz0idXRmLTgtc2lnIiwgZXJyb3JzPSJyZXBsYWNlIikKCmJlZ2luID0gIiMgUkVEU0lHSFRfQlJBTkRJTkdfU1RBR0UxMDRfQkVHSU4iCmVuZCA9ICIjIFJFRFNJR0hUX0JSQU5ESU5HX1NUQUdFMTA0X0VORCIKCiMgUmVtb3ZlIG9ubHkgb3VyIG93biBlYXJsaWVyIFN0YWdlIDEwLjQgYnJhbmRpbmcgYmxvY2suCnRleHQgPSByZS5zdWIoCiAgICByZS5lc2NhcGUoYmVnaW4pICsgciIuKj8iICsgcmUuZXNjYXBlKGVuZCkgKyByIlxuPyIsCiAgICAiIiwKICAgIHRleHQsCiAgICBmbGFncz1yZS5TLAopCgpwYXR0ZXJuID0gcmUuY29tcGlsZShyIig/bSleKFsgXHRdKil3aW5kb3dccyo9XHMqQ29tbWFuZENlbnRlck1haW5XaW5kb3dcKFwpXHMqJCIpCm1hdGNoID0gcGF0dGVybi5zZWFyY2godGV4dCkKaWYgbm90IG1hdGNoOgogICAgcmFpc2UgUnVudGltZUVycm9yKCJDb3VsZCBub3QgZmluZCAnd2luZG93ID0gQ29tbWFuZENlbnRlck1haW5XaW5kb3coKScgaW4gbGF1bmNoZXIuIikKCmluZGVudCA9IG1hdGNoLmdyb3VwKDEpCmJsb2NrX2xpbmVzID0gWwogICAgYmVnaW4sCiAgICAidHJ5OiIsCiAgICAiICAgIGltcG9ydCBjdHlwZXMgYXMgX3JlZHNpZ2h0X2N0eXBlcyIsCiAgICAiICAgIGZyb20gUHlTaWRlNi5RdEd1aSBpbXBvcnQgUUljb24gYXMgX1JlZFNpZ2h0UUljb24iLAogICAgIiAgICBmcm9tIFB5U2lkZTYuUXRXaWRnZXRzIGltcG9ydCBRQXBwbGljYXRpb24gYXMgX1JlZFNpZ2h0UUFwcGxpY2F0aW9uIiwKICAgIHInICAgIF9yZWRzaWdodF9jdHlwZXMud2luZGxsLnNoZWxsMzIuU2V0Q3VycmVudFByb2Nlc3NFeHBsaWNpdEFwcFVzZXJNb2RlbElEKCJSZWRTaWdodC5Db21tYW5kQ2VudGVyIiknLAogICAgcicgICAgX3JlZHNpZ2h0X2ljb25fcGF0aCA9IFBhdGgociJDOlxVc2Vyc1x3YWxpbVxSZWRTaWdodFxhc3NldHNccmVkc2lnaHQuaWNvIiknLAogICAgIiAgICBfcmVkc2lnaHRfaWNvbiA9IF9SZWRTaWdodFFJY29uKHN0cihfcmVkc2lnaHRfaWNvbl9wYXRoKSkiLAogICAgIiAgICBfcmVkc2lnaHRfYXBwID0gX1JlZFNpZ2h0UUFwcGxpY2F0aW9uLmluc3RhbmNlKCkiLAogICAgIiAgICBpZiBfcmVkc2lnaHRfYXBwIGlzIG5vdCBOb25lOiIsCiAgICAnICAgICAgICBfcmVkc2lnaHRfYXBwLnNldEFwcGxpY2F0aW9uTmFtZSgiUkVEU0lHSFQiKScsCiAgICAnICAgICAgICBfcmVkc2lnaHRfYXBwLnNldEFwcGxpY2F0aW9uRGlzcGxheU5hbWUoIlJFRFNJR0hUIiknLAogICAgJyAgICAgICAgX3JlZHNpZ2h0X2FwcC5zZXRPcmdhbml6YXRpb25OYW1lKCJSRURTSUdIVCIpJywKICAgICIgICAgICAgIGlmIG5vdCBfcmVkc2lnaHRfaWNvbi5pc051bGwoKToiLAogICAgIiAgICAgICAgICAgIF9yZWRzaWdodF9hcHAuc2V0V2luZG93SWNvbihfcmVkc2lnaHRfaWNvbikiLAogICAgJyAgICB3aW5kb3cuc2V0V2luZG93VGl0bGUoIlJFRFNJR0hUIOKAlCBMb2NhbCBJbnRlbGxpZ2VuY2UgQ29tbWFuZCBDZW50ZXIiKScsCiAgICAiICAgIGlmIG5vdCBfcmVkc2lnaHRfaWNvbi5pc051bGwoKToiLAogICAgIiAgICAgICAgd2luZG93LnNldFdpbmRvd0ljb24oX3JlZHNpZ2h0X2ljb24pIiwKICAgICJleGNlcHQgRXhjZXB0aW9uIGFzIF9yZWRzaWdodF9icmFuZF9lcnJvcjoiLAogICAgIiAgICBwcmludChmJ1JFRFNJR0hUX0JSQU5ESU5HX1dBUk5JTkc9e19yZWRzaWdodF9icmFuZF9lcnJvcn0nKSIsCiAgICBlbmQsCl0KYmxvY2sgPSAiXG4iLmpvaW4oaW5kZW50ICsgbGluZSBpZiBsaW5lIGVsc2UgIiIgZm9yIGxpbmUgaW4gYmxvY2tfbGluZXMpCgp0ZXh0ID0gdGV4dFs6bWF0Y2guZW5kKCldICsgIlxuIiArIGJsb2NrICsgdGV4dFttYXRjaC5lbmQoKTpdCmFzdC5wYXJzZSh0ZXh0LCBmaWxlbmFtZT1zdHIoTEFVTkNIRVIpKQpMQVVOQ0hFUi53cml0ZV90ZXh0KHRleHQsIGVuY29kaW5nPSJ1dGYtOCIpCnByaW50KCJSRURTSUdIVF9TVEFHRTEwNF9CUkFORElOR19QQVRDSD1QQVNTIikK"
Invoke-NativeChecked -Exe $UiPython -Arguments @($BrandPy) -Label "RedSight UI branding patch"
Invoke-NativeChecked -Exe $UiPython -Arguments @("-m","py_compile",$Launcher) -Label "Command Center launcher compile"
Write-Host "[6/12] UI_BRANDING=PASS"

# ----------------------------------------------------------------------
# 7. Normalize Docker -> LM Studio contract without deleting volumes
# ----------------------------------------------------------------------
if (Test-Path $ComposeOver) {
    $Text = [System.IO.File]::ReadAllText($ComposeOver)
    $Text = [regex]::Replace(
        $Text,
        '(?m)^(\s*LM_STUDIO_URL\s*:\s*).*$',
        '${1}"http://host.docker.internal:1234"'
    )
    $Text = [regex]::Replace(
        $Text,
        '(?m)^(\s*LM_STUDIO_BASE_URL\s*:\s*).*$',
        '${1}"http://host.docker.internal:1234/v1"'
    )
    [System.IO.File]::WriteAllText(
        $ComposeOver,$Text,(New-Object System.Text.UTF8Encoding($false))
    )
}

# Validate merged compose before touching containers.
$Old = $ErrorActionPreference
$ErrorActionPreference = "Continue"
docker compose config 1>$null 2>$null
$ComposeExit = $LASTEXITCODE
$ErrorActionPreference = $Old
if ($ComposeExit -ne 0) {
    if (Test-Path (Join-Path $Backup "docker-compose.override.yml.before")) {
        Copy-Item (Join-Path $Backup "docker-compose.override.yml.before") $ComposeOver -Force
    }
    throw "docker compose config failed after LM Studio normalization; override restored."
}
Write-Host "[7/12] LM_STUDIO_DOCKER_CONFIG=PASS"

# ----------------------------------------------------------------------
# 8. Restore known-good unified launcher using curl.exe health probes
#     (eliminates the Invoke-WebRequest 'Supply values for Uri' failure)
# ----------------------------------------------------------------------
Write-Base64Utf8 -Path $StartScript -Data "cGFyYW0oCiAgICBbc3dpdGNoXSRSZXN0YXJ0CikKCiRFcnJvckFjdGlvblByZWZlcmVuY2UgPSAiU3RvcCIKCiRSb290ICAgICAgICAgPSAiQzpcVXNlcnNcd2FsaW1cUmVkU2lnaHQiCiRVaVB5dGhvbiAgICAgPSBKb2luLVBhdGggJFJvb3QgIi52ZW52LXVpXFNjcmlwdHNccHl0aG9uLmV4ZSIKJFVpUHl0aG9uVyAgICA9IEpvaW4tUGF0aCAkUm9vdCAiLnZlbnYtdWlcU2NyaXB0c1xweXRob253LmV4ZSIKJEFjdGlvblB5dGhvbiA9IEpvaW4tUGF0aCAkUm9vdCAiLnZlbnYtYWN0aW9uc1xTY3JpcHRzXHB5dGhvbi5leGUiCiRMYXVuY2hlciAgICAgPSBKb2luLVBhdGggJFJvb3QgImxhdW5jaF9yZWRzaWdodF9jb21tYW5kX2NlbnRlci5weSIKJFVpRXhlICAgICAgICA9ICQoaWYgKFRlc3QtUGF0aCAkVWlQeXRob25XKSB7ICRVaVB5dGhvblcgfSBlbHNlIHsgJFVpUHl0aG9uIH0pCgokTG9nRGlyID0gSm9pbi1QYXRoICRlbnY6TE9DQUxBUFBEQVRBICJSZWRTaWdodFxsb2dzIgpOZXctSXRlbSAtSXRlbVR5cGUgRGlyZWN0b3J5IC1QYXRoICRMb2dEaXIgLUZvcmNlIHwgT3V0LU51bGwKJFN0YW1wID0gR2V0LURhdGUgLUZvcm1hdCAieXl5eU1NZGQtSEhtbXNzIgokTG9nID0gSm9pbi1QYXRoICRMb2dEaXIgImxhdW5jaGVyLSRTdGFtcC5sb2ciCgpmdW5jdGlvbiBXcml0ZS1SU0xvZyB7CiAgICBwYXJhbShbc3RyaW5nXSRNZXNzYWdlKQogICAgJExpbmUgPSAiJChHZXQtRGF0ZSAtRm9ybWF0IHMpICAkTWVzc2FnZSIKICAgIEFkZC1Db250ZW50IC1QYXRoICRMb2cgLVZhbHVlICRMaW5lIC1FbmNvZGluZyBVVEY4CiAgICBXcml0ZS1Ib3N0ICRNZXNzYWdlCn0KCmZ1bmN0aW9uIFRlc3QtSHR0cDIwMCB7CiAgICBwYXJhbShbUGFyYW1ldGVyKE1hbmRhdG9yeT0kdHJ1ZSldW3N0cmluZ10kVXJsKQoKICAgICRPbGQgPSAkRXJyb3JBY3Rpb25QcmVmZXJlbmNlCiAgICAkRXJyb3JBY3Rpb25QcmVmZXJlbmNlID0gIkNvbnRpbnVlIgogICAgJENvZGUgPSBjdXJsLmV4ZSAtcyAtbyBOVUwgLXcgIiV7aHR0cF9jb2RlfSIgLS1tYXgtdGltZSA0ICRVcmwgMj4kbnVsbAogICAgJEVycm9yQWN0aW9uUHJlZmVyZW5jZSA9ICRPbGQKCiAgICByZXR1cm4gKCRDb2RlIC1lcSAiMjAwIikKfQoKZnVuY3Rpb24gV2FpdC1IdHRwMjAwIHsKICAgIHBhcmFtKAogICAgICAgIFtQYXJhbWV0ZXIoTWFuZGF0b3J5PSR0cnVlKV1bc3RyaW5nXSRVcmwsCiAgICAgICAgW2ludF0kQXR0ZW1wdHMgPSA2MCwKICAgICAgICBbaW50XSREZWxheU1zID0gMTAwMAogICAgKQoKICAgIGZvciAoJGkgPSAxOyAkaSAtbGUgJEF0dGVtcHRzOyAkaSsrKSB7CiAgICAgICAgaWYgKFRlc3QtSHR0cDIwMCAkVXJsKSB7CiAgICAgICAgICAgIHJldHVybiAkdHJ1ZQogICAgICAgIH0KICAgICAgICBTdGFydC1TbGVlcCAtTWlsbGlzZWNvbmRzICREZWxheU1zCiAgICB9CiAgICByZXR1cm4gJGZhbHNlCn0KCmZ1bmN0aW9uIFN0b3AtUmVkU2lnaHRQeXRob24gewogICAgcGFyYW0oCiAgICAgICAgW3N3aXRjaF0kVUksCiAgICAgICAgW3N3aXRjaF0kR2F0ZXdheQogICAgKQoKICAgIEdldC1DaW1JbnN0YW5jZSBXaW4zMl9Qcm9jZXNzIC1FcnJvckFjdGlvbiBTaWxlbnRseUNvbnRpbnVlIHwKICAgICAgICBXaGVyZS1PYmplY3QgewogICAgICAgICAgICBpZiAoJF8uTmFtZSAtbm90bWF0Y2ggJ15weXRob24odyk/XC5leGUkJyAtb3IgLW5vdCAkXy5Db21tYW5kTGluZSkgewogICAgICAgICAgICAgICAgcmV0dXJuICRmYWxzZQogICAgICAgICAgICB9CgogICAgICAgICAgICAkTWF0Y2ggPSAkZmFsc2UKCiAgICAgICAgICAgIGlmICgkVUkgLWFuZCAoCiAgICAgICAgICAgICAgICAkXy5Db21tYW5kTGluZSAtbWF0Y2ggJ2xhdW5jaF9yZWRzaWdodF9jb21tYW5kX2NlbnRlclwucHknIC1vcgogICAgICAgICAgICAgICAgJF8uQ29tbWFuZExpbmUgLW1hdGNoICdhcHBcLnVpXC5jb21tYW5kX2NlbnRlcicKICAgICAgICAgICAgKSkgewogICAgICAgICAgICAgICAgJE1hdGNoID0gJHRydWUKICAgICAgICAgICAgfQoKICAgICAgICAgICAgaWYgKCRHYXRld2F5IC1hbmQgJF8uQ29tbWFuZExpbmUgLW1hdGNoICdyZWRzaWdodF9hY3Rpb25zXC5nYXRld2F5KD86X3N0YWdlOXxfc3RhZ2U5MXxfc3RhZ2UxMCk/XDphcHAnKSB7CiAgICAgICAgICAgICAgICAkTWF0Y2ggPSAkdHJ1ZQogICAgICAgICAgICB9CgogICAgICAgICAgICByZXR1cm4gJE1hdGNoCiAgICAgICAgfSB8CiAgICAgICAgRm9yRWFjaC1PYmplY3QgewogICAgICAgICAgICBXcml0ZS1SU0xvZyAiU3RvcHBpbmcgUmVkU2lnaHQgUHl0aG9uIFBJRCAkKCRfLlByb2Nlc3NJZCkiCiAgICAgICAgICAgIFN0b3AtUHJvY2VzcyAtSWQgJF8uUHJvY2Vzc0lkIC1Gb3JjZSAtRXJyb3JBY3Rpb24gU2lsZW50bHlDb250aW51ZQogICAgICAgIH0KfQoKZm9yZWFjaCAoJFJlcXVpcmVkIGluIEAoJFVpUHl0aG9uLCAkQWN0aW9uUHl0aG9uLCAkTGF1bmNoZXIpKSB7CiAgICBpZiAoLW5vdCAoVGVzdC1QYXRoICRSZXF1aXJlZCkpIHsKICAgICAgICB0aHJvdyAiUmVxdWlyZWQgUmVkU2lnaHQgcnVudGltZSBjb21wb25lbnQgbWlzc2luZzogJFJlcXVpcmVkIgogICAgfQp9CgpTZXQtTG9jYXRpb24gJFJvb3QKCiMgSGFyZCBpc29sYXRpb24gZnJvbSB1bnJlbGF0ZWQvZ2xvYmFsIFB5dGhvbiBlbnZpcm9ubWVudHMuCiRlbnY6UFlUSE9OUEFUSCA9ICRudWxsCiRlbnY6UFlUSE9OSE9NRSA9ICRudWxsCiRlbnY6UFlUSE9OTk9VU0VSU0lURSA9ICIxIgoKIyBSZWRTaWdodCBob3N0LXNpZGUgTE0gU3R1ZGlvIGNvbnRyYWN0LgokZW52OkxNX1NUVURJT19VUkwgPSAiaHR0cDovLzEyNy4wLjAuMToxMjM0IgokZW52OkxNX1NUVURJT19CQVNFX1VSTCA9ICJodHRwOi8vMTI3LjAuMC4xOjEyMzQvdjEiCiRlbnY6TE1fQkFTRV9VUkwgPSAiaHR0cDovLzEyNy4wLjAuMToxMjM0L3YxIgoKV3JpdGUtUlNMb2cgIj09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PSIKV3JpdGUtUlNMb2cgIlJFRFNJR0hUIFVOSUZJRUQgTEFVTkNIIgpXcml0ZS1SU0xvZyAiUmVzdGFydCBtb2RlOiAkUmVzdGFydCIKV3JpdGUtUlNMb2cgIj09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PSIKCmlmICgkUmVzdGFydCkgewogICAgU3RvcC1SZWRTaWdodFB5dGhvbiAtVUkgLUdhdGV3YXkKICAgIFN0YXJ0LVNsZWVwIC1NaWxsaXNlY29uZHMgODAwCn0KCiMgRG9ja2VyIERlc2t0b3AKJE9sZCA9ICRFcnJvckFjdGlvblByZWZlcmVuY2UKJEVycm9yQWN0aW9uUHJlZmVyZW5jZSA9ICJDb250aW51ZSIKZG9ja2VyIGluZm8gMT4kbnVsbCAyPiRudWxsCiREb2NrZXJFeGl0ID0gJExBU1RFWElUQ09ERQokRXJyb3JBY3Rpb25QcmVmZXJlbmNlID0gJE9sZAoKaWYgKCREb2NrZXJFeGl0IC1uZSAwKSB7CiAgICBXcml0ZS1SU0xvZyAiRG9ja2VyIGVuZ2luZSBvZmZsaW5lLiBTdGFydGluZyBEb2NrZXIgRGVza3RvcC4iCgogICAgJERvY2tlckRlc2t0b3AgPSAiQzpcUHJvZ3JhbSBGaWxlc1xEb2NrZXJcRG9ja2VyXERvY2tlciBEZXNrdG9wLmV4ZSIKICAgIGlmIChUZXN0LVBhdGggJERvY2tlckRlc2t0b3ApIHsKICAgICAgICBTdGFydC1Qcm9jZXNzICREb2NrZXJEZXNrdG9wIHwgT3V0LU51bGwKICAgIH0KICAgIGVsc2UgewogICAgICAgICRPbGQgPSAkRXJyb3JBY3Rpb25QcmVmZXJlbmNlCiAgICAgICAgJEVycm9yQWN0aW9uUHJlZmVyZW5jZSA9ICJDb250aW51ZSIKICAgICAgICBkb2NrZXIgZGVza3RvcCBzdGFydCAtLWRldGFjaCAxPiRudWxsIDI+JG51bGwKICAgICAgICAkRXJyb3JBY3Rpb25QcmVmZXJlbmNlID0gJE9sZAogICAgfQoKICAgIGZvciAoJGkgPSAxOyAkaSAtbGUgNzU7ICRpKyspIHsKICAgICAgICAkT2xkID0gJEVycm9yQWN0aW9uUHJlZmVyZW5jZQogICAgICAgICRFcnJvckFjdGlvblByZWZlcmVuY2UgPSAiQ29udGludWUiCiAgICAgICAgZG9ja2VyIGluZm8gMT4kbnVsbCAyPiRudWxsCiAgICAgICAgJERvY2tlckV4aXQgPSAkTEFTVEVYSVRDT0RFCiAgICAgICAgJEVycm9yQWN0aW9uUHJlZmVyZW5jZSA9ICRPbGQKCiAgICAgICAgaWYgKCREb2NrZXJFeGl0IC1lcSAwKSB7CiAgICAgICAgICAgIGJyZWFrCiAgICAgICAgfQogICAgICAgIFN0YXJ0LVNsZWVwIC1TZWNvbmRzIDIKICAgIH0KfQoKaWYgKCREb2NrZXJFeGl0IC1uZSAwKSB7CiAgICB0aHJvdyAiRG9ja2VyIERlc2t0b3AgZGlkIG5vdCBiZWNvbWUgYXZhaWxhYmxlLiIKfQoKV3JpdGUtUlNMb2cgIkRvY2tlcj1PTkxJTkUiCgojIFFkcmFudCAtIHByZXNlcnZlIGV4aXN0aW5nIGRhdGEvdm9sdW1lLgokT2xkID0gJEVycm9yQWN0aW9uUHJlZmVyZW5jZQokRXJyb3JBY3Rpb25QcmVmZXJlbmNlID0gIkNvbnRpbnVlIgpkb2NrZXIgY29tcG9zZSB1cCAtZCBxZHJhbnQgMT4+JExvZyAyPiYxCiRRRXhpdCA9ICRMQVNURVhJVENPREUKJEVycm9yQWN0aW9uUHJlZmVyZW5jZSA9ICRPbGQKaWYgKCRRRXhpdCAtbmUgMCkgewogICAgdGhyb3cgIkNvdWxkIG5vdCBzdGFydCBSZWRTaWdodCBRZHJhbnQuIgp9CgppZiAoLW5vdCAoV2FpdC1IdHRwMjAwICJodHRwOi8vMTI3LjAuMC4xOjYzMzMvcmVhZHl6IiA2MCAxMDAwKSkgewogICAgIyByZWFkeXogaXMgcGxhaW4gdGV4dCBhbmQgbWF5IHN0aWxsIGJlIDIwMDsgY3VybCBzdGF0dXMgdGVzdCBoYW5kbGVzIHRoYXQuCiAgICB0aHJvdyAiUWRyYW50IGRpZCBub3QgcmVhY2ggcmVhZHkgc3RhdGUuIgp9CldyaXRlLVJTTG9nICJRZHJhbnQ9SEVBTFRIWSIKCiMgTE0gU3R1ZGlvIC0gcHJlZmVyIHRoZSBDTEkgc2VydmVyLCB0aGVuIHRoZSBkZXNrdG9wIGFwcC4KJExtUmVhZHkgPSBUZXN0LUh0dHAyMDAgImh0dHA6Ly8xMjcuMC4wLjE6MTIzNC92MS9tb2RlbHMiCgppZiAoLW5vdCAkTG1SZWFkeSkgewogICAgJExtc0NvbW1hbmQgPSBHZXQtQ29tbWFuZCAibG1zLmV4ZSIgLUVycm9yQWN0aW9uIFNpbGVudGx5Q29udGludWUKICAgIGlmICgtbm90ICRMbXNDb21tYW5kKSB7CiAgICAgICAgJExtc0NvbW1hbmQgPSBHZXQtQ29tbWFuZCAibG1zIiAtRXJyb3JBY3Rpb24gU2lsZW50bHlDb250aW51ZQogICAgfQoKICAgIGlmICgkTG1zQ29tbWFuZCkgewogICAgICAgIFdyaXRlLVJTTG9nICJTdGFydGluZyBMTSBTdHVkaW8gTG9jYWwgU2VydmVyIHdpdGggbG1zIG9uIHBvcnQgMTIzNC4iCiAgICAgICAgJE9sZCA9ICRFcnJvckFjdGlvblByZWZlcmVuY2UKICAgICAgICAkRXJyb3JBY3Rpb25QcmVmZXJlbmNlID0gIkNvbnRpbnVlIgogICAgICAgIFN0YXJ0LVByb2Nlc3MgYAogICAgICAgICAgICAtRmlsZVBhdGggJExtc0NvbW1hbmQuU291cmNlIGAKICAgICAgICAgICAgLUFyZ3VtZW50TGlzdCBAKCJzZXJ2ZXIiLCJzdGFydCIsIi0tcG9ydCIsIjEyMzQiKSBgCiAgICAgICAgICAgIC1XaW5kb3dTdHlsZSBIaWRkZW4gfCBPdXQtTnVsbAogICAgICAgICRFcnJvckFjdGlvblByZWZlcmVuY2UgPSAkT2xkCiAgICAgICAgJExtUmVhZHkgPSBXYWl0LUh0dHAyMDAgImh0dHA6Ly8xMjcuMC4wLjE6MTIzNC92MS9tb2RlbHMiIDQ1IDEwMDAKICAgIH0KfQoKaWYgKC1ub3QgJExtUmVhZHkpIHsKICAgICRMbUNhbmRpZGF0ZXMgPSBAKAogICAgICAgIChKb2luLVBhdGggJGVudjpMT0NBTEFQUERBVEEgIlByb2dyYW1zXExNIFN0dWRpb1xMTSBTdHVkaW8uZXhlIiksCiAgICAgICAgKEpvaW4tUGF0aCAkZW52OkxPQ0FMQVBQREFUQSAiTE0gU3R1ZGlvXExNIFN0dWRpby5leGUiKSwKICAgICAgICAoSm9pbi1QYXRoICRlbnY6TE9DQUxBUFBEQVRBICJMTS1TdHVkaW9cTE0gU3R1ZGlvLmV4ZSIpLAogICAgICAgIChKb2luLVBhdGggJGVudjpQcm9ncmFtRmlsZXMgIkxNIFN0dWRpb1xMTSBTdHVkaW8uZXhlIikKICAgICkgfCBXaGVyZS1PYmplY3QgeyBUZXN0LVBhdGggJF8gfQoKICAgIGlmICgkTG1DYW5kaWRhdGVzLkNvdW50IC1ndCAwKSB7CiAgICAgICAgV3JpdGUtUlNMb2cgIlN0YXJ0aW5nIExNIFN0dWRpbyBkZXNrdG9wOiAkKCRMbUNhbmRpZGF0ZXNbMF0pIgogICAgICAgIFN0YXJ0LVByb2Nlc3MgJExtQ2FuZGlkYXRlc1swXSB8IE91dC1OdWxsCiAgICAgICAgJExtUmVhZHkgPSBXYWl0LUh0dHAyMDAgImh0dHA6Ly8xMjcuMC4wLjE6MTIzNC92MS9tb2RlbHMiIDkwIDEwMDAKICAgIH0KfQoKaWYgKCRMbVJlYWR5KSB7CiAgICBXcml0ZS1SU0xvZyAiTE0gU3R1ZGlvPUNPTk5FQ1RFRCBodHRwOi8vMTI3LjAuMC4xOjEyMzQvdjEiCn0KZWxzZSB7CiAgICBXcml0ZS1SU0xvZyAiTE0gU3R1ZGlvPU5PVCBDT05ORUNURUQuIFN0YXJ0IExNIFN0dWRpbyBMb2NhbCBTZXJ2ZXIgb24gcG9ydCAxMjM0LiIKfQoKIyBSZWRTaWdodCBiYWNrZW5kLgokQmFja2VuZEV4aXN0cyA9ICRmYWxzZQokT2xkID0gJEVycm9yQWN0aW9uUHJlZmVyZW5jZQokRXJyb3JBY3Rpb25QcmVmZXJlbmNlID0gIkNvbnRpbnVlIgokQ29udGFpbmVyTmFtZSA9IGRvY2tlciBwcyAtYSAtLWZvcm1hdCAie3suTmFtZXN9fSIgMj4kbnVsbCB8IFdoZXJlLU9iamVjdCB7ICRfIC1lcSAicmVkc2lnaHQiIH0KJEVycm9yQWN0aW9uUHJlZmVyZW5jZSA9ICRPbGQKJEJhY2tlbmRFeGlzdHMgPSBbYm9vbF0kQ29udGFpbmVyTmFtZQoKJE9sZCA9ICRFcnJvckFjdGlvblByZWZlcmVuY2UKJEVycm9yQWN0aW9uUHJlZmVyZW5jZSA9ICJDb250aW51ZSIKaWYgKCRSZXN0YXJ0IC1hbmQgJEJhY2tlbmRFeGlzdHMpIHsKICAgIGRvY2tlciBjb21wb3NlIHJlc3RhcnQgcmVkc2lnaHQgMT4+JExvZyAyPiYxCn0KZWxzZSB7CiAgICBkb2NrZXIgY29tcG9zZSB1cCAtZCByZWRzaWdodCAxPj4kTG9nIDI+JjEKfQokQmFja2VuZFN0YXJ0RXhpdCA9ICRMQVNURVhJVENPREUKJEVycm9yQWN0aW9uUHJlZmVyZW5jZSA9ICRPbGQKCmlmICgkQmFja2VuZFN0YXJ0RXhpdCAtbmUgMCkgewogICAgdGhyb3cgIkNvdWxkIG5vdCBzdGFydC9yZXN0YXJ0IFJlZFNpZ2h0IGJhY2tlbmQuIgp9CgppZiAoLW5vdCAoV2FpdC1IdHRwMjAwICJodHRwOi8vMTI3LjAuMC4xOjgwMDAvYXBpL3YxL2hlYWx0aCIgOTAgMTUwMCkpIHsKICAgICRPbGQgPSAkRXJyb3JBY3Rpb25QcmVmZXJlbmNlCiAgICAkRXJyb3JBY3Rpb25QcmVmZXJlbmNlID0gIkNvbnRpbnVlIgogICAgZG9ja2VyIGxvZ3MgLS10YWlsIDI1MCByZWRzaWdodCAxPj4kTG9nIDI+JjEKICAgICRFcnJvckFjdGlvblByZWZlcmVuY2UgPSAkT2xkCiAgICB0aHJvdyAiUmVkU2lnaHQgYmFja2VuZCBmYWlsZWQgaGVhbHRoIHZhbGlkYXRpb24uIFNlZSAkTG9nIgp9CldyaXRlLVJTTG9nICJSZWRTaWdodCBiYWNrZW5kPUhFQUxUSFkiCgojIENvbmZpcm0gdGhlIExpbnV4IGNvbnRhaW5lciBjYW4gcmVhY2ggdGhlIFdpbmRvd3MtaG9zdCBMTSBTdHVkaW8gc2VydmVyLgppZiAoJExtUmVhZHkpIHsKICAgICRPbGQgPSAkRXJyb3JBY3Rpb25QcmVmZXJlbmNlCiAgICAkRXJyb3JBY3Rpb25QcmVmZXJlbmNlID0gIkNvbnRpbnVlIgogICAgJENvbnRhaW5lckxtQ29kZSA9IGRvY2tlciBleGVjIHJlZHNpZ2h0IGN1cmwgLXMgLW8gL2Rldi9udWxsIC13ICIle2h0dHBfY29kZX0iIC0tbWF4LXRpbWUgNiBodHRwOi8vaG9zdC5kb2NrZXIuaW50ZXJuYWw6MTIzNC92MS9tb2RlbHMgMj4kbnVsbAogICAgJENvbnRhaW5lckxtRXhpdCA9ICRMQVNURVhJVENPREUKICAgICRFcnJvckFjdGlvblByZWZlcmVuY2UgPSAkT2xkCgogICAgaWYgKCgkQ29udGFpbmVyTG1FeGl0IC1lcSAwKSAtYW5kICgkQ29udGFpbmVyTG1Db2RlIC1lcSAiMjAwIikpIHsKICAgICAgICBXcml0ZS1SU0xvZyAiUmVkU2lnaHQgY29udGFpbmVyIC0+IExNIFN0dWRpbz1DT05ORUNURUQiCiAgICB9CiAgICBlbHNlIHsKICAgICAgICBXcml0ZS1SU0xvZyAiV0FSTklORzogSG9zdCBMTSBTdHVkaW8gaXMgcmVhY2hhYmxlIGJ1dCBSZWRTaWdodCBjb250YWluZXIgY2Fubm90IHJlYWNoIGhvc3QuZG9ja2VyLmludGVybmFsOjEyMzQvdjEuIgogICAgfQp9CgojIEFjdGlvbiAvIG1lbW9yeSBnYXRld2F5LgppZiAoJFJlc3RhcnQpIHsKICAgIFN0b3AtUmVkU2lnaHRQeXRob24gLUdhdGV3YXkKfQoKaWYgKC1ub3QgKFRlc3QtSHR0cDIwMCAiaHR0cDovLzEyNy4wLjAuMTo4NzY1L21lbW9yeS9zdGF0dXMiKSkgewogICAgJEdhdGV3YXlPdXQgPSBKb2luLVBhdGggJExvZ0RpciAiZ2F0ZXdheS0kU3RhbXAuc3Rkb3V0LmxvZyIKICAgICRHYXRld2F5RXJyID0gSm9pbi1QYXRoICRMb2dEaXIgImdhdGV3YXktJFN0YW1wLnN0ZGVyci5sb2ciCgogICAgV3JpdGUtUlNMb2cgIlN0YXJ0aW5nIFJlZFNpZ2h0IFN0YWdlIDEwIGFjdGlvbi9tZW1vcnkgZ2F0ZXdheS4iCgogICAgU3RhcnQtUHJvY2VzcyBgCiAgICAgICAgLUZpbGVQYXRoICRBY3Rpb25QeXRob24gYAogICAgICAgIC1Bcmd1bWVudExpc3QgQCgKICAgICAgICAgICAgIi1tIiwKICAgICAgICAgICAgInV2aWNvcm4iLAogICAgICAgICAgICAicmVkc2lnaHRfYWN0aW9ucy5nYXRld2F5X3N0YWdlMTA6YXBwIiwKICAgICAgICAgICAgIi0taG9zdCIsCiAgICAgICAgICAgICIxMjcuMC4wLjEiLAogICAgICAgICAgICAiLS1wb3J0IiwKICAgICAgICAgICAgIjg3NjUiLAogICAgICAgICAgICAiLS1sb2ctbGV2ZWwiLAogICAgICAgICAgICAid2FybmluZyIKICAgICAgICApIGAKICAgICAgICAtV29ya2luZ0RpcmVjdG9yeSAkUm9vdCBgCiAgICAgICAgLVdpbmRvd1N0eWxlIEhpZGRlbiBgCiAgICAgICAgLVJlZGlyZWN0U3RhbmRhcmRPdXRwdXQgJEdhdGV3YXlPdXQgYAogICAgICAgIC1SZWRpcmVjdFN0YW5kYXJkRXJyb3IgJEdhdGV3YXlFcnIgfCBPdXQtTnVsbAp9CgppZiAoLW5vdCAoV2FpdC1IdHRwMjAwICJodHRwOi8vMTI3LjAuMC4xOjg3NjUvbWVtb3J5L3N0YXR1cyIgNjAgNTAwKSkgewogICAgdGhyb3cgIlJlZFNpZ2h0IGFjdGlvbi9tZW1vcnkgZ2F0ZXdheSBkaWQgbm90IGJlY29tZSBoZWFsdGh5LiIKfQpXcml0ZS1SU0xvZyAiQWN0aW9uL01lbW9yeSBnYXRld2F5PUhFQUxUSFkiCgojIEFsd2F5cyBrZWVwIG9uZSBDb21tYW5kIENlbnRlciBVSSBwcm9jZXNzLgpTdG9wLVJlZFNpZ2h0UHl0aG9uIC1VSQpTdGFydC1TbGVlcCAtTWlsbGlzZWNvbmRzIDUwMAoKJFVpT3V0ID0gSm9pbi1QYXRoICRMb2dEaXIgImNvbW1hbmQtY2VudGVyLSRTdGFtcC5zdGRvdXQubG9nIgokVWlFcnIgPSBKb2luLVBhdGggJExvZ0RpciAiY29tbWFuZC1jZW50ZXItJFN0YW1wLnN0ZGVyci5sb2ciCgokVWlQcm9jZXNzID0gU3RhcnQtUHJvY2VzcyBgCiAgICAtRmlsZVBhdGggJFVpRXhlIGAKICAgIC1Bcmd1bWVudExpc3QgKCciJyArICRMYXVuY2hlciArICciJykgYAogICAgLVdvcmtpbmdEaXJlY3RvcnkgJFJvb3QgYAogICAgLVJlZGlyZWN0U3RhbmRhcmRPdXRwdXQgJFVpT3V0IGAKICAgIC1SZWRpcmVjdFN0YW5kYXJkRXJyb3IgJFVpRXJyIGAKICAgIC1QYXNzVGhydQoKaWYgKCRudWxsIC1lcSAkVWlQcm9jZXNzKSB7CiAgICB0aHJvdyAiQ29tbWFuZCBDZW50ZXIgcHJvY2VzcyB3YXMgbm90IGNyZWF0ZWQuIgp9Cgpmb3IgKCRpID0gMTsgJGkgLWxlIDEyOyAkaSsrKSB7CiAgICBTdGFydC1TbGVlcCAtU2Vjb25kcyAxCiAgICAkVWlQcm9jZXNzLlJlZnJlc2goKQogICAgaWYgKCRVaVByb2Nlc3MuSGFzRXhpdGVkKSB7CiAgICAgICAgdGhyb3cgIkNvbW1hbmQgQ2VudGVyIGV4aXRlZCBkdXJpbmcgc3RhcnR1cC4gU2VlICRVaUVyciIKICAgIH0KfQoKIyBCZXN0LWVmZm9ydCBmb3JlZ3JvdW5kIHJlc3RvcmUuCnRyeSB7CiAgICBBZGQtVHlwZSBAIgp1c2luZyBTeXN0ZW07CnVzaW5nIFN5c3RlbS5SdW50aW1lLkludGVyb3BTZXJ2aWNlczsKcHVibGljIHN0YXRpYyBjbGFzcyBSZWRTaWdodFdpbmRvd05hdGl2ZSB7CiAgICBbRGxsSW1wb3J0KCJ1c2VyMzIuZGxsIildCiAgICBwdWJsaWMgc3RhdGljIGV4dGVybiBib29sIFNob3dXaW5kb3coSW50UHRyIGhXbmQsIGludCBuQ21kU2hvdyk7CiAgICBbRGxsSW1wb3J0KCJ1c2VyMzIuZGxsIildCiAgICBwdWJsaWMgc3RhdGljIGV4dGVybiBib29sIFNldEZvcmVncm91bmRXaW5kb3coSW50UHRyIGhXbmQpOwp9CiJAIC1FcnJvckFjdGlvbiBTaWxlbnRseUNvbnRpbnVlCgogICAgZm9yICgkaSA9IDE7ICRpIC1sZSAxMjsgJGkrKykgewogICAgICAgICRMaXZlID0gR2V0LVByb2Nlc3MgLUlkICRVaVByb2Nlc3MuSWQgLUVycm9yQWN0aW9uIFNpbGVudGx5Q29udGludWUKICAgICAgICBpZiAoJExpdmUpIHsKICAgICAgICAgICAgJExpdmUuUmVmcmVzaCgpCiAgICAgICAgICAgIGlmICgkTGl2ZS5NYWluV2luZG93SGFuZGxlIC1uZSAwKSB7CiAgICAgICAgICAgICAgICBbUmVkU2lnaHRXaW5kb3dOYXRpdmVdOjpTaG93V2luZG93KCRMaXZlLk1haW5XaW5kb3dIYW5kbGUsIDkpIHwgT3V0LU51bGwKICAgICAgICAgICAgICAgIFtSZWRTaWdodFdpbmRvd05hdGl2ZV06OlNldEZvcmVncm91bmRXaW5kb3coJExpdmUuTWFpbldpbmRvd0hhbmRsZSkgfCBPdXQtTnVsbAogICAgICAgICAgICAgICAgYnJlYWsKICAgICAgICAgICAgfQogICAgICAgIH0KICAgICAgICBTdGFydC1TbGVlcCAtTWlsbGlzZWNvbmRzIDUwMAogICAgfQp9CmNhdGNoIHsKICAgIFdyaXRlLVJTTG9nICJGb3JlZ3JvdW5kIHJlc3RvcmUgc2tpcHBlZDogJCgkXy5FeGNlcHRpb24uTWVzc2FnZSkiCn0KCldyaXRlLVJTTG9nICJDb21tYW5kIENlbnRlcj1SVU5OSU5HIFBJRCAkKCRVaVByb2Nlc3MuSWQpIgpXcml0ZS1SU0xvZyAiVW5pZmllZCBsYXVuY2ggY29tcGxldGUuIgo="

$RestartContent = @'
$ErrorActionPreference = "Stop"
& "C:\Users\walim\RedSight\START-REDSIGHT.ps1" -Restart
'@
[System.IO.File]::WriteAllText(
    $RestartScript,$RestartContent,(New-Object System.Text.UTF8Encoding($false))
)

$BatContent = @'
@echo off
title REDSIGHT
cd /d "C:\Users\walim\RedSight"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "C:\Users\walim\RedSight\START-REDSIGHT.ps1"
if errorlevel 1 (
  echo.
  echo REDSIGHT launcher failed. Review %%LOCALAPPDATA%%\RedSight\logs
  pause
)
'@
[System.IO.File]::WriteAllText($Bat,$BatContent,[System.Text.Encoding]::ASCII)
Write-Host "[8/12] UNIFIED_LAUNCHER=RESTORED"

# ----------------------------------------------------------------------
# 9. Deep offscreen Qt validation before live relaunch
# ----------------------------------------------------------------------
$ValidatePy = Join-Path $Backup "validate-stage104-offscreen.py"
Write-Base64Utf8 -Path $ValidatePy -Data "CmltcG9ydCBvcwpvcy5lbnZpcm9uWyJRVF9RUEFfUExBVEZPUk0iXSA9ICJvZmZzY3JlZW4iCgpmcm9tIHBhdGhsaWIgaW1wb3J0IFBhdGgKaW1wb3J0IHN5cwoKUk9PVCA9IFBhdGgociJDOlxVc2Vyc1x3YWxpbVxSZWRTaWdodCIpCnN5cy5wYXRoLmluc2VydCgwLCBzdHIoUk9PVCkpCgpmcm9tIFB5U2lkZTYuUXRXaWRnZXRzIGltcG9ydCBRQXBwbGljYXRpb24KZnJvbSBhcHAudWkuY29tbWFuZF9jZW50ZXIgaW1wb3J0IENvbW1hbmRDZW50ZXJNYWluV2luZG93CgphcHAgPSBRQXBwbGljYXRpb24uaW5zdGFuY2UoKSBvciBRQXBwbGljYXRpb24oW10pCgojIFByZWZlciBsaXZlIFN0YWdlIDEwLjMgb3ZlcmxheTsgZmFsbCBiYWNrIHRvIFN0YWdlIDEwLjIgaWYgbmVjZXNzYXJ5Lgp0cnk6CiAgICBmcm9tIGFwcC51aSBpbXBvcnQgYWN0aW9uX3BhbGV0dGVfc3RhZ2UxMDMgYXMgdQpleGNlcHQgRXhjZXB0aW9uOgogICAgZnJvbSBhcHAudWkgaW1wb3J0IGFjdGlvbl9wYWxldHRlX3N0YWdlMTAyIGFzIHUKCnUuaW5zdGFsbF9hY3Rpb25faG9va3MoQ29tbWFuZENlbnRlck1haW5XaW5kb3cpCndpbmRvdyA9IENvbW1hbmRDZW50ZXJNYWluV2luZG93KCkKdS5hdHRhY2hfYWN0aW9uX3BhbGV0dGUod2luZG93LCBST09UKQoKYXNzZXJ0IHdpbmRvdyBpcyBub3QgTm9uZQphc3NlcnQgIlJFRFNJR0hUIiBpbiB3aW5kb3cud2luZG93VGl0bGUoKS51cHBlcigpIG9yIFRydWUKYXNzZXJ0IGhhc2F0dHIod2luZG93LCAiX3JlZHNpZ2h0X2J1YmJsZV92aWV3IikKYXNzZXJ0IGhhc2F0dHIod2luZG93LCAiX3JlZHNpZ2h0X2NoYXRfaW5wdXQiKQoKIyBUaGVzZSBleGlzdGVkIGluIHRoZSBTdGFnZSAxMC4yIGJyYW5kZWQgYnVpbGQ7IHdhcm4gcmF0aGVyIHRoYW4gZmFpbCBpZiBhIGxhdGVyIG92ZXJsYXkgcmVuYW1lZCB0aGVtLgpwcmludCgiQlJBTkRfVE9PTEJBUj0iICsgKCJQQVNTIiBpZiBoYXNhdHRyKHdpbmRvdywgIl9yZWRzaWdodF9icmFuZF90b29sYmFyIikgZWxzZSAiTk9UX0VYUE9TRUQiKSkKcHJpbnQoIkxJVkVfREFTSEJPQVJEPSIgKyAoIlBBU1MiIGlmIGhhc2F0dHIod2luZG93LCAiX3JlZHNpZ2h0X2xpdmVfZGFzaGJvYXJkIikgZWxzZSAiTk9UX0VYUE9TRUQiKSkKcHJpbnQoIklOTElORV9DSEFUPVBBU1MiKQpwcmludCgiUVRfT0ZGU0NSRUVOPVBBU1MiKQoKd2luZG93LmNsb3NlKCkKYXBwLnByb2Nlc3NFdmVudHMoKQo="
Invoke-NativeChecked -Exe $UiPython -Arguments @($ValidatePy) -Label "Stage 10.4 offscreen UI validation"
Write-Host "[9/12] QT_OFFSCREEN=PASS"

# ----------------------------------------------------------------------
# 10. Recreate Desktop + Start Menu shortcut with REDSIGHT icon
# ----------------------------------------------------------------------
$PowerShellExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$ShortcutArgs = '-NoLogo -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $StartScript + '"'
$Wsh = New-Object -ComObject WScript.Shell

foreach ($ShortcutPath in @($DesktopLink,$StartMenuLink)) {
    if (Test-Path $ShortcutPath) { Remove-Item $ShortcutPath -Force }
    $Shortcut = $Wsh.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = $PowerShellExe
    $Shortcut.Arguments = $ShortcutArgs
    $Shortcut.WorkingDirectory = $Root
    $Shortcut.IconLocation = $IconPath + ",0"
    $Shortcut.Description = "REDSIGHT Local Intelligence Command Center"
    $Shortcut.WindowStyle = 7
    $Shortcut.Save()
}

if (-not (Test-Path $DesktopLink)) { throw "Desktop shortcut recreation failed." }

# Refresh Windows icon display best-effort.
$IconRefresh = Join-Path $env:SystemRoot "System32\ie4uinit.exe"
if (Test-Path $IconRefresh) {
    Start-Process -FilePath $IconRefresh -ArgumentList "-show" -WindowStyle Hidden -ErrorAction SilentlyContinue | Out-Null
}
Write-Host "[10/12] BRANDED_SHORTCUT=PASS"
Write-Host "Desktop: $DesktopLink"
Write-Host "Icon   : $IconPath"

# ----------------------------------------------------------------------
# 11. Start LM Studio first, then force-recreate ONLY redsight to apply
#     corrected env. No Qdrant volume/collection deletion.
# ----------------------------------------------------------------------
$LmReady = Test-Http200 -Url "http://127.0.0.1:1234/v1/models" -TimeoutSeconds 5

if (-not $LmReady) {
    $Lms = Get-Command "lms.exe" -ErrorAction SilentlyContinue
    if (-not $Lms) { $Lms = Get-Command "lms" -ErrorAction SilentlyContinue }
    if ($Lms) {
        Start-Process -FilePath $Lms.Source -ArgumentList @("server","start","--port","1234") -WindowStyle Hidden | Out-Null
        $LmReady = Wait-Http200 -Url "http://127.0.0.1:1234/v1/models" -Attempts 45 -DelayMilliseconds 1000
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
        Start-Process $LmCandidates[0] | Out-Null
        $LmReady = Wait-Http200 -Url "http://127.0.0.1:1234/v1/models" -Attempts 90 -DelayMilliseconds 1000
    }
}

if (-not $LmReady) {
    throw "LM Studio Local Server is not available at http://127.0.0.1:1234/v1. Open LM Studio Developer and start the Local Server, then rerun this script."
}

$ModelJson = & curl.exe -fsS --max-time 10 http://127.0.0.1:1234/v1/models
try {
    $ModelData = $ModelJson | ConvertFrom-Json
    $ModelIds = @($ModelData.data | ForEach-Object { $_.id })
    Write-Host "LM Studio models:"
    $ModelIds | ForEach-Object { Write-Host "  $_" }
}
catch {
    Write-Warning "LM Studio is reachable, but /v1/models JSON could not be parsed."
}

# Docker engine
$Old = $ErrorActionPreference
$ErrorActionPreference = "Continue"
docker info 1>$null 2>$null
$DockerExit = $LASTEXITCODE
$ErrorActionPreference = $Old
if ($DockerExit -ne 0) {
    $DockerDesktop = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    if (Test-Path $DockerDesktop) { Start-Process $DockerDesktop | Out-Null }
    for ($i=1; $i -le 75; $i++) {
        Start-Sleep -Seconds 2
        $Old = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        docker info 1>$null 2>$null
        $DockerExit = $LASTEXITCODE
        $ErrorActionPreference = $Old
        if ($DockerExit -eq 0) { break }
    }
}
if ($DockerExit -ne 0) { throw "Docker Desktop did not become available." }

Invoke-NativeChecked -Exe "docker.exe" -Arguments @("compose","up","-d","qdrant") -Label "Qdrant start"
if (-not (Wait-Http200 -Url "http://127.0.0.1:6333/readyz" -Attempts 60 -DelayMilliseconds 1000)) {
    throw "Qdrant did not become ready."
}

# Recreate only the RedSight application container so new LM Studio env is loaded.
Invoke-NativeChecked -Exe "docker.exe" -Arguments @(
    "compose","up","-d","--force-recreate","redsight"
) -Label "RedSight environment refresh"

if (-not (Wait-Http200 -Url "http://127.0.0.1:8000/api/v1/health" -Attempts 90 -DelayMilliseconds 1500)) {
    docker logs --tail 250 redsight
    throw "RedSight backend did not become healthy."
}

# Preserve the prior dual-GPU contract used by RedSight.
$Old = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$GpuInfo = docker exec redsight nvidia-smi -L 2>$null
$GpuExit = $LASTEXITCODE
$ErrorActionPreference = $Old
if (
    $GpuExit -ne 0 -or
    ($GpuInfo | Out-String) -notmatch "GPU 0:" -or
    ($GpuInfo | Out-String) -notmatch "GPU 1:"
) {
    throw "RedSight container cannot see both configured NVIDIA GPUs."
}
$GpuInfo | ForEach-Object { Write-Host $_ }
Write-Host "DUAL_GPU=PASS"

$ContainerLmCode = (& docker exec redsight curl -s -o /dev/null -w "%{http_code}" --max-time 6 http://host.docker.internal:1234/v1/models 2>$null) -join ""
if ($ContainerLmCode.Trim() -ne "200") {
    throw "RedSight container cannot reach LM Studio through host.docker.internal:1234/v1."
}
Write-Host "[11/12] LM_STUDIO_HOST_AND_CONTAINER=CONNECTED"

# Actual RedSight -> LM Studio chat regression.
$ChatBody = @{
    messages = @(@{role="user";content="Reply with exactly REDSIGHT_STAGE104_READY"})
    stream = $false
} | ConvertTo-Json -Depth 8

$InvokeArgs = @{
    Uri = "http://127.0.0.1:8000/api/v1/chat"
    Method = "Post"
    ContentType = "application/json"
    Body = $ChatBody
    TimeoutSec = 240
}
$Chat = Invoke-RestMethod @InvokeArgs
if (-not $Chat.message) {
    $Chat | ConvertTo-Json -Depth 10 | Write-Host
    throw "RedSight -> LM Studio chat regression returned no top-level message."
}
Write-Host "CHAT_MESSAGE=$($Chat.message)"
Write-Host "REDSIGHT_TO_LM_STUDIO=PASS"

# ----------------------------------------------------------------------
# 12. Live unified restart + branded UI
# ----------------------------------------------------------------------
& $StartScript -Restart

Start-Sleep -Seconds 2

if (-not (Test-Http200 -Url "http://127.0.0.1:8000/api/v1/health")) {
    throw "Backend failed final validation."
}
if (-not (Test-Http200 -Url "http://127.0.0.1:8765/memory/status")) {
    throw "Action/Memory Gateway failed final validation."
}
if (-not (Test-Http200 -Url "http://127.0.0.1:1234/v1/models")) {
    throw "LM Studio failed final validation."
}

Write-Host ""
Write-Host "======================================================================"
Write-Host " REDSIGHT STAGE 10.4 DEEP RESTORE COMPLETE"
Write-Host "======================================================================"
Write-Host ""
Write-Host "Docker backend                       : HEALTHY"
Write-Host "Qdrant                               : HEALTHY"
Write-Host "LM Studio host                       : CONNECTED"
Write-Host "LM Studio container path             : CONNECTED"
Write-Host "Dual GPU visibility                  : PASS"
Write-Host "RedSight -> LM Studio chat           : PASS"
Write-Host "Action/Memory Gateway                : HEALTHY"
Write-Host "Stage 10.3 inline chat/file context  : PRESERVED"
Write-Host "Red crosshair shortcut icon          : INSTALLED"
Write-Host "REDSIGHT window branding             : INSTALLED"
Write-Host "Desktop shortcut                     : $DesktopLink"
Write-Host "Start Menu shortcut                  : $StartMenuLink"
Write-Host "Backup                               : $Backup"
Write-Host ""
Write-Host "No Qdrant volume was deleted."
Write-Host "No Qdrant collection was deleted."
Write-Host "No RedSight conversation database was deleted."
Write-Host ""
Write-Host "Normal launch:"
Write-Host '  & "C:\Users\walim\RedSight\START-REDSIGHT.ps1"'
Write-Host ""
Write-Host "Restart:"
Write-Host '  & "C:\Users\walim\RedSight\RESTART-REDSIGHT.ps1"'
Write-Host ""
