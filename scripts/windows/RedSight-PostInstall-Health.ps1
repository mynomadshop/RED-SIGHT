<#
    RedSight-PostInstall-Health.ps1  (compatibility shim)

    The post-install health check is Verify-RedSightSetup.ps1. This file used to
    be a second, independent one written against a retired install layout - it
    looked for the interpreter at tools\python.exe and the gateway at
    redsight_actions\gateway.py. Neither path exists in a current install (the
    interpreter is runtime\python\python.exe plus the .venv-ui / .venv-actions
    environments, and the gateway is redsight_actions\gateway_stage10.py), so
    running it against a working RedSight reported missing files that are
    present under their real names. That is what made a healthy install look
    like it was pointing at an older one.

    Kept as a shim so existing shortcuts, notes and scheduled tasks that name
    this script keep working. It runs the real check.

    Exit codes are Verify-RedSightSetup.ps1's:
        0   every required check passed
        1   at least one required check failed
#>

[CmdletBinding()]
param(
    [string]$InstallRoot,
    [switch]$Json
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }

# Installed layout first (this file sits next to the real check), then the
# source checkout, where the maintained copy lives under installer\scripts.
$candidates = @(
    (Join-Path $scriptDir 'Verify-RedSightSetup.ps1'),
    (Join-Path ([System.IO.Path]::GetFullPath((Join-Path $scriptDir '..\..'))) 'installer\scripts\Verify-RedSightSetup.ps1')
)
$verify = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $verify) {
    throw ("Verify-RedSightSetup.ps1 was not found next to this script or under " +
           "installer\scripts. The installation is incomplete - run " +
           "scripts\windows\Repair-RedSight.ps1 -Fix.")
}

Write-Host "RedSight health check: $verify"

$forward = @{}
if ($InstallRoot) { $forward['ProjectRoot'] = $InstallRoot }
if ($Json) { $forward['Json'] = $true }

$global:LASTEXITCODE = 0
& $verify @forward
exit $LASTEXITCODE
