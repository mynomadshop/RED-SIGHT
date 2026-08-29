#requires -version 5.1
<#!
.SYNOPSIS
  Resumable Windows bootstrapper for RedSight.

.DESCRIPTION
  Runs as the post-install state machine. WSL is a Windows capability and is
  therefore enabled on the host rather than pretending it is an application
  payload. If Windows requires a reboot, this script records state and creates
  a one-shot elevated scheduled task which resumes the same stage after logon.

  The script is deliberately idempotent: every stage verifies the desired
  state before making a change. It never installs a Linux distribution unless
  explicitly requested by the caller.
#>
[CmdletBinding()]
param(
  [string]$InstallRoot = $(Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
  [switch]$Resume,
  [switch]$SkipDocker
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$StateRoot = Join-Path $env:ProgramData 'RedSight\Setup'
$StateFile = Join-Path $StateRoot 'install-state.json'
$TaskName  = 'RedSight Setup Resume'
$LogFile   = Join-Path $StateRoot 'setup.log'
New-Item -ItemType Directory -Force -Path $StateRoot | Out-Null

function Write-Log([string]$Message) {
  $line = "$(Get-Date -Format o) $Message"
  Add-Content -LiteralPath $LogFile -Value $line -Encoding UTF8
  Write-Host $line
}

function Save-State([string]$Stage, [hashtable]$Extra = @{}) {
  $state = [ordered]@{ product='RedSight'; stage=$Stage; installRoot=$InstallRoot; updatedAt=(Get-Date).ToUniversalTime().ToString('o') }
  foreach ($k in $Extra.Keys) { $state[$k] = $Extra[$k] }
  $tmp = "$StateFile.tmp"
  $state | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $tmp -Encoding UTF8
  Move-Item -Force -LiteralPath $tmp -Destination $StateFile
}

function Get-State {
  if (Test-Path -LiteralPath $StateFile) {
    try { return (Get-Content -Raw -LiteralPath $StateFile | ConvertFrom-Json) } catch { }
  }
  return $null
}

function Register-ResumeTask {
  $ps = (Get-Command powershell.exe).Source
  $arg = '-NoProfile -ExecutionPolicy Bypass -File "{0}" -InstallRoot "{1}" -Resume' -f (Join-Path $InstallRoot 'scripts\windows\RedSight-Setup-Resume.ps1'), $InstallRoot
  $action = New-ScheduledTaskAction -Execute $ps -Argument $arg
  $trigger = New-ScheduledTaskTrigger -AtLogOn
  $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
  Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Force | Out-Null
}

function Remove-ResumeTask {
  try { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue } catch { }
}

function Needs-Reboot {
  $paths = @(
    'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending',
    'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired'
  )
  foreach ($p in $paths) { if (Test-Path $p) { return $true } }
  return $false
}

function Enable-WslFeatures {
  Write-Log 'Checking WSL2 Windows capabilities.'
  $wsl = Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux
  $vm  = Get-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform
  $changed = $false
  if ($wsl.State -ne 'Enabled') {
    Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux -All -NoRestart | Out-Null
    $changed = $true
  }
  if ($vm.State -ne 'Enabled') {
    Enable-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform -All -NoRestart | Out-Null
    $changed = $true
  }
  if ($changed -or -not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    if (Get-Command wsl.exe -ErrorAction SilentlyContinue) {
      try { & wsl.exe --update --web-download 2>&1 | ForEach-Object { Write-Log "WSL: $_" } } catch { Write-Log "WSL update deferred: $($_.Exception.Message)" }
    }
  }
  return ($changed -or (Needs-Reboot))
}

function Verify-Wsl {
  if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) { return $false }
  try {
    $v = & wsl.exe --version 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) { return $false }
    Write-Log ($v.Trim())
    & wsl.exe --set-default-version 2 2>&1 | ForEach-Object { Write-Log "WSL: $_" }
    return $true
  } catch { return $false }
}

function Test-Docker {
  $docker = Get-Command docker.exe -ErrorAction SilentlyContinue
  if (-not $docker) { return $false }
  try { & docker.exe version --format '{{.Server.Version}}' 2>$null | Out-Null; return ($LASTEXITCODE -eq 0) } catch { return $false }
}

function Start-Docker {
  $exeCandidates = @(
    (Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\Docker Desktop.exe')
  )
  $exe = $exeCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
  if (-not $exe) { return $false }
  Start-Process -FilePath $exe -ArgumentList '--accept-license' -ErrorAction SilentlyContinue
  for ($i=0; $i -lt 90; $i++) {
    if (Test-Docker) { return $true }
    Start-Sleep -Seconds 2
  }
  return $false
}

try {
  Write-Log "RedSight setup state machine starting. Root=$InstallRoot Resume=$Resume"
  if (-not (Test-Path (Join-Path $InstallRoot 'scripts'))) { throw "Invalid RedSight installation root: $InstallRoot" }

  Save-State 'wsl'
  if (Enable-WslFeatures) {
    Register-ResumeTask
    Save-State 'wsl-reboot-required'
    Write-Log 'WSL Windows capabilities require a reboot. Setup will resume automatically after logon.'
    shutdown.exe /r /t 60 /c 'RedSight needs to restart Windows to finish WSL2 setup. Setup will resume automatically.' /d p:4:1
    exit 3010
  }

  if (-not (Verify-Wsl)) {
    throw 'WSL2 is not operational after feature enablement. Check virtualization, Windows servicing level, and WSL logs.'
  }

  Save-State 'docker'
  if (-not $SkipDocker) {
    if (-not (Test-Docker)) {
      Write-Log 'Docker CLI/engine not ready. Docker Desktop must be installed by the installer bootstrapper.'
      # Do not fake success: the calling installer should install Docker Desktop
      # and invoke this state machine again after installation.
      Save-State 'docker-install-required'
      exit 20
    }
    if (-not (Start-Docker)) {
      throw 'Docker Desktop is installed but its engine did not become ready within the startup window.'
    }
  }

  Save-State 'application-health'
  $health = Join-Path $InstallRoot 'scripts\windows\RedSight-PostInstall-Health.ps1'
  if (Test-Path $health) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $health -InstallRoot $InstallRoot
    if ($LASTEXITCODE -ne 0) { throw "Post-install health check failed with exit code $LASTEXITCODE" }
  }

  Save-State 'complete'
  Remove-ResumeTask
  Write-Log 'RedSight setup completed successfully.'
  exit 0
}
catch {
  Save-State 'failed' @{ error=$_.Exception.Message }
  Write-Log "SETUP FAILED: $($_.Exception.Message)"
  exit 1
}
