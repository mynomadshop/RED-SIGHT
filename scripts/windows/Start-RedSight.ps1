<#
    Start-RedSight.ps1  (source-tree forwarder)

    The real launcher is installer\scripts\Start-RedSight.ps1. The installer
    overlays it onto scripts\windows\Start-RedSight.ps1 in the payload, so in an
    installed RedSight this file *is* that launcher and this forwarder is never
    present.

    In a source checkout the two paths both exist, and a second, independently
    maintained launcher here is how RedSight ended up with shortcuts that start
    redsight_actions.gateway - which serves no /memory routes - instead of
    gateway_stage10. The UI then reports memory as missing and its chat answers
    nothing. Forwarding rather than duplicating makes that divergence
    impossible.
#>

[CmdletBinding()]
param(
    [string]$ProjectRoot,
    [switch]$NoUi
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $scriptDir '..\..'))
$launcher = Join-Path $repoRoot 'installer\scripts\Start-RedSight.ps1'

if (-not (Test-Path -LiteralPath $launcher)) {
    throw ("The RedSight launcher is missing: $launcher`n" +
           'This file only forwards to it. In an installed RedSight the ' +
           'installer replaces this file with the launcher itself, so seeing ' +
           'this error means the installation is incomplete - run ' +
           'scripts\windows\Repair-RedSight.ps1 -Fix.')
}

$forward = @{}
if ($PSBoundParameters.ContainsKey('ProjectRoot')) { $forward['ProjectRoot'] = $ProjectRoot }
else { $forward['ProjectRoot'] = $repoRoot }
if ($NoUi) { $forward['NoUi'] = $true }

$global:LASTEXITCODE = 0
& $launcher @forward
exit $LASTEXITCODE
