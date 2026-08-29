#requires -version 5.1
[CmdletBinding()]
param([switch]$NoUI)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$Root=Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Python=Join-Path $Root 'tools\python.exe'
if(-not(Test-Path$Python)){$Python=(Get-Command python.exe -ErrorAction SilentlyContinue).Source}
if(-not$Python){throw 'RedSight private Python runtime is missing.'}
$LogRoot=Join-Path $env:LOCALAPPDATA 'RedSight\logs';New-Item -ItemType Directory -Force -Path $LogRoot|Out-Null
function Start-RedSightProcess([string]$Name,[string[]]$Args){$log=Join-Path $LogRoot "$Name.log";$p=Start-Process -FilePath $Python -ArgumentList $Args -WorkingDirectory $Root -RedirectStandardOutput $log -RedirectStandardError "$log.err" -PassThru;return $p}
# Avoid duplicate instances for the same installation. The health/diagnostics tools can identify other installs.
$api=Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if(-not$api){Start-RedSightProcess 'api' @('-m','uvicorn','app.server:app','--host','127.0.0.1','--port','8000')|Out-Null}
$gateway=Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
if(-not$gateway){Start-RedSightProcess 'actions' @('-m','uvicorn','redsight_actions.gateway:app','--host','127.0.0.1','--port','8765')|Out-Null}
for($i=0;$i-lt 45;$i++){try{$r=Invoke-WebRequest 'http://127.0.0.1:8000/api/v1/health' -UseBasicParsing -TimeoutSec 2;if($r.StatusCode-eq200){break}}catch{};Start-Sleep 1}
if($NoUI){exit 0}
& $Python '-c' 'from redsight.ui import main; main()'
