#requires -version 5.1
[CmdletBinding()]
param([switch]$NoUI)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$Root=Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Python=Join-Path $Root 'tools\python.exe'
if(-not(Test-Path -LiteralPath $Python)){$cmd=Get-Command python.exe -ErrorAction SilentlyContinue;if($cmd){$Python=$cmd.Source}}
if(-not(Test-Path -LiteralPath $Python)){throw 'RedSight private Python runtime is missing.'}
$LogRoot=Join-Path $env:LOCALAPPDATA 'RedSight\logs'
New-Item -ItemType Directory -Force -Path $LogRoot|Out-Null
function Start-RedSightProcess([string]$Name,[string[]]$Args){
  $log=Join-Path $LogRoot "$Name.log"
  $err=Join-Path $LogRoot "$Name.err.log"
  return Start-Process -FilePath $Python -ArgumentList $Args -WorkingDirectory $Root -RedirectStandardOutput $log -RedirectStandardError $err -PassThru
}
$api=Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if(-not$api){Start-RedSightProcess 'api' @('-m','uvicorn','app.server:app','--host','127.0.0.1','--port','8000')|Out-Null}
$gateway=Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
if(-not$gateway){Start-RedSightProcess 'actions' @('-m','uvicorn','redsight_actions.gateway:app','--host','127.0.0.1','--port','8765')|Out-Null}
$healthy=$false
for($i=0;$i-lt 60;$i++){
  try{$r=Invoke-WebRequest 'http://127.0.0.1:8000/api/v1/health' -UseBasicParsing -TimeoutSec 2;if($r.StatusCode-eq200){$healthy=$true;break}}catch{}
  Start-Sleep 1
}
if(-not$healthy){throw "RedSight backend did not become healthy within 60 seconds. Check $LogRoot\api.err.log"}
if($NoUI){exit 0}
& $Python '-c' 'from ui.command_center import main; main()'
exit $LASTEXITCODE
