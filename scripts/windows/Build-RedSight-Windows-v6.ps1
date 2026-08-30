<#
    Build-RedSight-Windows-v6.ps1

    Builds the RedSight Desktop for Windows v6 bundle: the setup .exe plus the
    release .zip that wraps it with its manifest, checksums and README.

        pwsh -NoLogo -NoProfile -File scripts\windows\Build-RedSight-Windows-v6.ps1

    This is a front end. The build itself is installer\build\Build-Installer.ps1,
    which is the pipeline the .iss, the setup scripts, the app overlay and the
    repair tooling are all written against.

    It used to be a second, self-contained pipeline that compiled its own .iss
    under a different AppId. Two AppIds meant Windows treated the two builds as
    unrelated products: both could be installed at once, into different
    directories, each with its own uninstall entry, and they then fought over
    ports 8000/8765 and over %LOCALAPPDATA%\RedSight. Its payload also shipped
    the launcher and health check of a retired install layout, which is what
    made a healthy install report files as missing. One pipeline, one AppId,
    one launcher.

    Everything the old pipeline did that the canonical one did not - bundling
    Playwright's Chromium - now happens during setup, on the target machine,
    where the browser is downloaded once for the account that will use it.
#>

[CmdletBinding()]
param(
    # The application tree to package. Defaults to this repository.
    [string]$AppSource,

    # Product version stamped into the installer, the zip name and the manifest.
    [Alias('AppVersion')]
    [string]$Version = '11.6.0',

    # Where the .exe and .zip land.
    [string]$OutputDir = 'dist',

    # Bundle every Python wheel so setup can run with no internet at all.
    # Adds roughly a gigabyte (PySide6, torch, onnxruntime).
    [Alias('BundleOfflineDependencies')]
    [switch]$IncludeAllWheels,

    # Staging tree. Override with a short path (-StagingDir C:\rs-stage) if
    # robocopy reports errors about very long destination paths.
    [string]$StagingDir,

    # Path to ISCC.exe. Found automatically when Inno Setup is installed.
    [string]$IsccPath,

    # Skip the CPython + wheelhouse download (a much faster build that produces
    # an installer which needs the network on the target machine).
    [switch]$SkipBundle
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $scriptDir '..\..'))
$builder = Join-Path $repoRoot 'installer\build\Build-Installer.ps1'

if (-not (Test-Path -LiteralPath $builder)) {
    throw "The installer build script is missing: $builder"
}

if (-not $AppSource) { $AppSource = $repoRoot }
$AppSource = (Resolve-Path -LiteralPath $AppSource).Path

Write-Host ''
Write-Host 'REDSIGHT DESKTOP FOR WINDOWS - v6 BUNDLE' -ForegroundColor Cyan
Write-Host ('-' * 55)
Write-Host "  source  : $AppSource"
Write-Host "  version : $Version"
Write-Host "  output  : $OutputDir"
Write-Host "  wheels  : $(if ($IncludeAllWheels) { 'all (fully offline installer)' } else { 'bootstrap only' })"
Write-Host ''

$buildArgs = @{
    AppSource = $AppSource
    Version   = $Version
    OutputDir = $OutputDir
}
if ($StagingDir) { $buildArgs['StagingDir'] = $StagingDir }
if ($IsccPath) { $buildArgs['IsccPath'] = $IsccPath }
if ($IncludeAllWheels) { $buildArgs['IncludeAllWheels'] = $true }
if ($SkipBundle) { $buildArgs['SkipBundle'] = $true }

# Reset first: a PowerShell script that returns without calling exit leaves
# $LASTEXITCODE at whatever the previous native command set, so testing it
# unreset can report a failure the build never had.
$global:LASTEXITCODE = 0
& $builder @buildArgs
if ($LASTEXITCODE -ne 0) { throw "the installer build failed with exit code $LASTEXITCODE" }
exit 0
