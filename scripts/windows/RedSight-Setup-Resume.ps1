#requires -version 5.1
[CmdletBinding()]
param(
  [string]$InstallRoot = $(Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
  [switch]$Resume,
  [switch]$SkipDocker,
  [string]$DockerInstaller = ''
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

# --------------------------------------------------------------------------
# Retired pipeline guard
# --------------------------------------------------------------------------
# This resumable bootstrapper belongs to a Windows pipeline RedSight no longer
# ships. Setup is now installer\scripts\Bootstrap-RedSight.ps1, which the
# installer overlays onto scripts\windows and which handles the WSL2 feature
# enable, the reboot and Docker Desktop itself.
#
# Running this against a current install would register a logon scheduled task
# that re-runs the retired bootstrapper indefinitely, reinstalling Docker over
# an installation that already provisioned it. So: detect a current install,
# clean up any task an earlier run of this script left behind, and stop.
$currentSetup = Join-Path $InstallRoot 'scripts\windows\Bootstrap-RedSight.ps1'
if (Test-Path -LiteralPath $currentSetup) {
    $stale = Get-ScheduledTask -TaskName 'RedSight Setup Resume' -ErrorAction SilentlyContinue
    if ($stale) {
        Unregister-ScheduledTask -TaskName 'RedSight Setup Resume' -Confirm:$false -ErrorAction SilentlyContinue
        Write-Host 'Removed the leftover "RedSight Setup Resume" logon task from the retired pipeline.'
    }
    Write-Host ''
    Write-Host 'This script has been retired. RedSight setup is now:' -ForegroundColor Yellow
    Write-Host "  powershell -ExecutionPolicy Bypass -File `"$currentSetup`" -ProjectRoot `"$InstallRoot`""
    Write-Host ''
    Write-Host 'To diagnose or repair an existing installation:'
    Write-Host "  powershell -ExecutionPolicy Bypass -File `"$(Join-Path $InstallRoot 'scripts\windows\Repair-RedSight.ps1')`" -Fix"
    Write-Host ''
    exit 0
}

$StateRoot=Join-Path $env:ProgramData 'RedSight\Setup'
$StateFile=Join-Path $StateRoot 'install-state.json'
$TaskName='RedSight Setup Resume'
$LogFile=Join-Path $StateRoot 'setup.log'
New-Item -ItemType Directory -Force -Path $StateRoot|Out-Null
function Write-Log([string]$m){$l="$(Get-Date -Format o) $m";Add-Content -LiteralPath $LogFile -Value $l -Encoding UTF8;Write-Host $l}
function Save-State([string]$Stage,[hashtable]$Extra=@{}){$s=[ordered]@{product='RedSight';stage=$Stage;installRoot=$InstallRoot;updatedAt=(Get-Date).ToUniversalTime().ToString('o')};foreach($k in $Extra.Keys){$s[$k]=$Extra[$k]};$t="$StateFile.tmp";$s|ConvertTo-Json -Depth 8|Set-Content $t -Encoding UTF8;Move-Item -Force $t $StateFile}
function Register-ResumeTask{
  $ps=(Get-Command powershell.exe).Source
  $script=Join-Path $InstallRoot 'scripts\windows\RedSight-Setup-Resume.ps1'
  $arg='-NoProfile -ExecutionPolicy Bypass -File "{0}" -InstallRoot "{1}" -Resume' -f $script,$InstallRoot
  $a=New-ScheduledTaskAction -Execute $ps -Argument $arg
  $tr=New-ScheduledTaskTrigger -AtLogOn
  $user="$env:USERDOMAIN\$env:USERNAME"
  $pr=New-ScheduledTaskPrincipal -UserId $user -LogonType InteractiveToken -RunLevel Highest
  Register-ScheduledTask -TaskName $TaskName -Action $a -Trigger $tr -Principal $pr -Force|Out-Null
}
function Remove-ResumeTask{try{Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue}catch{}}
function Enable-WslFeatures{
  $changed=$false
  $wsl=Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux
  $vm=Get-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform
  if($wsl.State -ne 'Enabled'){
    $r=Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux -All -NoRestart
    $changed=$changed -or [bool]$r.RestartNeeded
  }
  if($vm.State -ne 'Enabled'){
    $r=Enable-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform -All -NoRestart
    $changed=$changed -or [bool]$r.RestartNeeded
  }
  return $changed
}
function Install-LatestWslMsi{
  if(-not(Get-Command wsl.exe -ErrorAction SilentlyContinue)){throw 'wsl.exe is unavailable after enabling the Windows feature.'}
  try{& wsl.exe --update --web-download 2>&1|ForEach-Object{Write-Log "WSL: $_"};if($LASTEXITCODE -eq 0){return}}catch{}
  Write-Log 'WSL self-update unavailable; using official Microsoft WSL MSI.'
  $offline=Join-Path $InstallRoot 'offline\wsl-latest-x64.msi'
  if(Test-Path -LiteralPath $offline){$msi=$offline}else{
    $rel=Invoke-RestMethod 'https://api.github.com/repos/microsoft/WSL/releases/latest' -Headers @{Accept='application/vnd.github+json';'User-Agent'='RedSight-Installer'}
    $asset=$rel.assets|Where-Object{$_.name -match '\.x64\.msi$'}|Select-Object -First 1
    if(-not$asset){throw 'Microsoft WSL x64 MSI was not found.'}
    $msi=Join-Path $env:TEMP $asset.name
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $msi -UseBasicParsing
  }
  $p=Start-Process msiexec.exe -ArgumentList @('/i',$msi,'/qn','/norestart') -Wait -PassThru
  if($p.ExitCode -notin 0,1641,3010){throw "WSL MSI failed with exit code $($p.ExitCode)."}
  if($msi -like "$env:TEMP\*"){Remove-Item $msi -Force -ErrorAction SilentlyContinue}
}
function Verify-Wsl{if(-not(Get-Command wsl.exe -ErrorAction SilentlyContinue)){return $false};try{& wsl.exe --status 2>&1|ForEach-Object{Write-Log "WSL: $_"};if($LASTEXITCODE -ne 0){return $false};& wsl.exe --set-default-version 2 2>&1|ForEach-Object{Write-Log "WSL: $_"};return $true}catch{return $false}}
function Test-Docker{if(-not(Get-Command docker.exe -ErrorAction SilentlyContinue)){return $false};try{& docker.exe version --format '{{.Server.Version}}' 2>$null|Out-Null;return($LASTEXITCODE -eq 0)}catch{return $false}}
function Install-Docker{
  if($DockerInstaller -and (Test-Path -LiteralPath $DockerInstaller)){$src=$DockerInstaller}
  else{$src=Join-Path $StateRoot 'Docker Desktop Installer.exe';if(-not(Test-Path -LiteralPath $src)){Invoke-WebRequest -Uri 'https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe' -OutFile $src -UseBasicParsing}}
  $p=Start-Process -FilePath $src -ArgumentList 'install','--quiet','--accept-license','--backend=wsl-2','--no-windows-containers' -Wait -PassThru
  if($p.ExitCode -notin 0,3010,1641){throw "Docker Desktop installer failed with exit code $($p.ExitCode)."}
}
function Start-Docker{
  if(Test-Docker){return $true}
  $c=@((Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'),(Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\Docker Desktop.exe'))
  $exe=$c|Where-Object{Test-Path -LiteralPath $_}|Select-Object -First 1
  if(-not$exe){return $false}
  Start-Process -FilePath $exe -ErrorAction SilentlyContinue
  for($i=0;$i-lt 120;$i++){if(Test-Docker){return $true};Start-Sleep 2}
  return $false
}
try{
  Write-Log "RedSight setup starting. Root=$InstallRoot Resume=$Resume"
  if(-not[Environment]::Is64BitOperatingSystem){throw 'RedSight requires 64-bit Windows.'}
  if(-not(Test-Path(Join-Path $InstallRoot 'scripts'))){throw "Invalid RedSight installation root: $InstallRoot"}
  Save-State 'wsl'
  if(Enable-WslFeatures){
    Register-ResumeTask
    Save-State 'wsl-reboot-required'
    Write-Log 'Windows needs a reboot to complete WSL2 enablement. Resuming automatically after logon.'
    shutdown.exe /r /t 60 /c 'RedSight needs to restart Windows to finish WSL2 setup. Setup will resume automatically after logon.' /d p:4:1
    exit 3010
  }
  if(-not(Verify-Wsl)){Install-LatestWslMsi;if(-not(Verify-Wsl)){throw 'WSL2 is not operational. Check BIOS/UEFI virtualization, Windows servicing, and WSL logs.'}}
  Save-State 'docker'
  if(-not$SkipDocker){if(-not(Test-Docker)){Install-Docker};if(-not(Start-Docker)){throw 'Docker Desktop is installed but its engine did not become ready within 4 minutes.'}}
  Save-State 'application-health'
  $health=Join-Path $InstallRoot 'scripts\windows\RedSight-PostInstall-Health.ps1'
  if(Test-Path -LiteralPath $health){& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $health -InstallRoot $InstallRoot;if($LASTEXITCODE-ne 0){throw "Post-install health check failed with exit code $LASTEXITCODE"}}
  Save-State 'complete';Remove-ResumeTask;Write-Log 'RedSight setup completed successfully.';exit 0
}catch{Save-State 'failed' @{error=$_.Exception.Message};Write-Log "SETUP FAILED: $($_.Exception.Message)";exit 1}
