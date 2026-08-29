#requires -version 5.1
[CmdletBinding()]
param([Parameter(Mandatory)][string]$InstallRoot)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$fail=@()
function Check([string]$Name,[scriptblock]$Test) { try { & $Test; Write-Host "[PASS] $Name" } catch { $fail += "$Name: $($_.Exception.Message)"; Write-Host "[FAIL] $Name :: $($_.Exception.Message)" } }

Check '64-bit Windows' { if (-not [Environment]::Is64BitOperatingSystem) { throw '32-bit Windows is unsupported.' } }
Check 'Windows build suitable for WSL2' { $b=[Environment]::OSVersion.Version.Build; if($b -lt 19041){throw "Windows build $b is below 19041."} }
Check 'WSL command' { if(-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)){throw 'wsl.exe not found.'}; & wsl.exe --status 2>&1 | Out-Null; if($LASTEXITCODE -ne 0){throw 'wsl --status failed.'} }
Check 'WSL2 feature' { $f=Get-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform; if($f.State -ne 'Enabled'){throw "VirtualMachinePlatform is $($f.State)."} }
Check 'RedSight files' { foreach($p in @('pyproject.toml','app\server.py','ui\command_center.py','redsight_actions\gateway.py')){if(-not(Test-Path(Join-Path $InstallRoot $p))){throw "Missing $p"}} }
Check 'Python runtime' { $p=Join-Path $InstallRoot 'tools\python.exe'; if(-not(Test-Path $p)){ $p=(Get-Command python.exe -ErrorAction SilentlyContinue).Source }; if(-not $p){throw 'Python 3.12 runtime not found.'}; $v=& $p --version 2>&1 | Out-String; if($v -notmatch 'Python 3\.12'){throw "Unexpected Python version: $v"} }
Check 'Port 8000 available or owned by RedSight' { $c=Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue; if($c){$proc=Get-CimInstance Win32_Process -Filter "ProcessId=$($c.OwningProcess)"; if(-not $proc.CommandLine -match [regex]::Escape($InstallRoot)){throw "Port 8000 is occupied by PID $($c.OwningProcess)."}} }
Check 'Port 8765 available or owned by RedSight' { $c=Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue; if($c){$proc=Get-CimInstance Win32_Process -Filter "ProcessId=$($c.OwningProcess)"; if(-not $proc.CommandLine -match [regex]::Escape($InstallRoot)){throw "Port 8765 is occupied by PID $($c.OwningProcess)."}} }

if($fail.Count){ Write-Host "`nRedSight health check failed:" -ForegroundColor Red; $fail | ForEach-Object {Write-Host " - $_"}; exit 1 }
Write-Host "`nRedSight post-install health check passed." -ForegroundColor Green
exit 0
