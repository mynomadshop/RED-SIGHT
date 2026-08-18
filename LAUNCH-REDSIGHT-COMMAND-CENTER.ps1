$ErrorActionPreference = "Stop"

$Root = "C:\Users\walim\RedSight"
$Python = Join-Path $Root ".venv-ui\Scripts\python.exe"
$Launcher = Join-Path $Root "launch_redsight_command_center.py"

Set-Location $Root

& $Python $Launcher
