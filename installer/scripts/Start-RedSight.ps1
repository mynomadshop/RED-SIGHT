<#
    Start-RedSight.ps1

    The one entry point every RedSight shortcut points at.

    RedSight ships more than one launcher and they are not equivalent:

        START-REDSIGHT.ps1           Docker, the action/memory gateway on
                                     127.0.0.1:8765, then the Command Center
        LAUNCH-REDSIGHT-DESKTOP.ps1  Docker and the Command Center only
        START-REDSIGHT-NATIVE.ps1    written by setup for machines that cannot
                                     run WSL2: backend, gateway and UI, no
                                     containers

    The desktop UI sends every chat through the gateway - /memory/build before
    the model call and /memory/commit after it - and reads its memory indicator
    from /memory/status there. A shortcut to the launcher that does not start
    the gateway therefore produces a UI that reports memory as missing and
    answers nothing, which is why the choice is made here from the recorded
    runtime mode rather than from whichever file happens to exist.
#>

[CmdletBinding()]
param(
    [string]$ProjectRoot,
    [switch]$NoUi
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not $ProjectRoot) {
    # This script lives in <root>\scripts\windows.
    $ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $scriptDir '..\..'))
}

function Get-RuntimeMode {
    param([Parameter(Mandatory)][string]$Root)
    $envFile = Join-Path $Root '.env'
    if (Test-Path -LiteralPath $envFile) {
        foreach ($line in @(Get-Content -LiteralPath $envFile -ErrorAction SilentlyContinue)) {
            if ($line -match '^\s*REDSIGHT_RUNTIME_MODE\s*=\s*(.+?)\s*$') {
                return $Matches[1].Trim('"').Trim("'").ToLowerInvariant()
            }
        }
    }
    # No recorded mode: native is the safe assumption, because the native
    # launcher exists only when setup chose that mode.
    if (Test-Path -LiteralPath (Join-Path $Root 'START-REDSIGHT-NATIVE.ps1')) { return 'native' }
    return 'container'
}

$mode = Get-RuntimeMode -Root $ProjectRoot

if ($mode -eq 'native') {
    $order = @('START-REDSIGHT-NATIVE.ps1', 'START-REDSIGHT.ps1', 'LAUNCH-REDSIGHT-DESKTOP.ps1')
} else {
    # START-REDSIGHT.ps1 first: it is the only shipped launcher that starts the
    # action/memory gateway.
    $order = @('START-REDSIGHT.ps1', 'LAUNCH-REDSIGHT-DESKTOP.ps1', 'START-REDSIGHT-NATIVE.ps1')
}

$target = $null
foreach ($candidate in $order) {
    $path = Join-Path $ProjectRoot $candidate
    if (Test-Path -LiteralPath $path) { $target = $path; break }
}

if (-not $target) {
    $message = "RedSight is not fully installed: no launcher was found in $ProjectRoot.`n`n" +
               "Run 'Repair RedSight setup' from the Start Menu."
    try {
        Add-Type -AssemblyName PresentationFramework
        [System.Windows.MessageBox]::Show($message, 'RedSight') | Out-Null
    } catch {
        Write-Host $message
    }
    exit 1
}

$logDir = Join-Path $env:LOCALAPPDATA 'RedSight\logs'
New-Item -ItemType Directory -Path $logDir -Force -ErrorAction SilentlyContinue | Out-Null
"$(Get-Date -Format s)  runtime mode $mode -> $(Split-Path -Leaf $target)" |
    Add-Content -LiteralPath (Join-Path $logDir 'start.log') -Encoding UTF8

$arguments = @('-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $target)
if ($NoUi -and (Split-Path -Leaf $target) -eq 'START-REDSIGHT-NATIVE.ps1') { $arguments += '-NoUi' }

& (Join-Path $PSHOME 'powershell.exe') @arguments
exit $LASTEXITCODE
