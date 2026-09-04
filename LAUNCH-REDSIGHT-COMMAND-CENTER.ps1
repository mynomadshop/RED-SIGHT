$ErrorActionPreference = "Stop"

$Root = $PSScriptRoot
$Python = Join-Path $Root ".venv-ui\Scripts\python.exe"
$Launcher = Join-Path $Root "launch_redsight_command_center.py"

if (-not (Test-Path $Python)) {
    throw "RedSight UI Python environment not found: $Python"
}
if (-not (Test-Path $Launcher)) {
    throw "RedSight Command Center launcher not found: $Launcher"
}

Set-Location $Root
& $Python $Launcher
