<#
    Uninstall-RedSightDocker.ps1

    Removes the RedSight containers and images during uninstall, and asks
    separately about the data volumes.

    Run by the installer's [UninstallRun] step. Everything here is best-effort:
    an uninstall must never fail because Docker is not running, and it must
    never delete a user's vector index or chat memory without being asked.

        powershell -ExecutionPolicy Bypass -File Uninstall-RedSightDocker.ps1
                   [-ProjectRoot <path>] [-RemoveVolumes] [-NonInteractive]
#>

[CmdletBinding()]
param(
    [string]$ProjectRoot,
    [switch]$RemoveVolumes,
    [switch]$NonInteractive
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Continue'

$scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not $ProjectRoot) {
    $ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $scriptDir '..\..'))
}

$logDir = Join-Path $env:LOCALAPPDATA 'RedSight\logs'
New-Item -ItemType Directory -Path $logDir -Force -ErrorAction SilentlyContinue | Out-Null
$log = Join-Path $logDir ("uninstall-docker-{0}.log" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))

function Write-Line {
    param([string]$Message)
    $line = "$(Get-Date -Format s)  $Message"
    Add-Content -LiteralPath $log -Value $line -Encoding UTF8
    Write-Host $line
}

Write-Line "removing RedSight Docker resources for $ProjectRoot"

$docker = Get-Command 'docker' -CommandType Application -ErrorAction SilentlyContinue |
          Select-Object -First 1
if (-not $docker) {
    Write-Line 'Docker is not installed - nothing to remove'
    exit 0
}

& $docker.Source info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Line 'the Docker engine is not running - leaving containers and images in place'
    exit 0
}

# compose down removes the containers and the network but keeps named volumes,
# which is what preserves the Qdrant index and the chat memory.
$compose = Join-Path $ProjectRoot 'docker-compose.yml'
if (Test-Path -LiteralPath $compose) {
    Write-Line 'docker compose down'
    & $docker.Source 'compose' 'down' '--remove-orphans' *>> $log
} else {
    foreach ($name in @('redsight', 'redsight-qdrant')) {
        Write-Line "docker rm -f $name"
        & $docker.Source 'rm' '-f' $name *>> $log
    }
}

foreach ($image in @(
    'redsight-qdrant:v1.19.1',
    'redsight-qdrant:v1.19.0',
    'redsight:latest',
    'red-sight-redsight:latest'
)) {
    & $docker.Source 'image' 'inspect' $image *> $null
    if ($LASTEXITCODE -eq 0) {
        Write-Line "docker image rm $image"
        & $docker.Source 'image' 'rm' '-f' $image *>> $log
    }
}

if (-not $RemoveVolumes -and -not $NonInteractive) {
    Add-Type -AssemblyName PresentationFramework
    $answer = [System.Windows.MessageBox]::Show(
        "Also delete RedSight's stored data?" + [Environment]::NewLine + [Environment]::NewLine +
        "This removes the Qdrant vector index and the chat memory volumes. " +
        "Choose No to keep them for a future reinstall.",
        'RedSight uninstall',
        [System.Windows.MessageBoxButton]::YesNo,
        [System.Windows.MessageBoxImage]::Warning)
    $RemoveVolumes = ($answer -eq [System.Windows.MessageBoxResult]::Yes)
}

if ($RemoveVolumes) {
    foreach ($volume in @('redsight-data', 'qdrant-data', 'red-sight_redsight-data', 'red-sight_qdrant-data')) {
        & $docker.Source 'volume' 'inspect' $volume *> $null
        if ($LASTEXITCODE -eq 0) {
            Write-Line "docker volume rm $volume"
            & $docker.Source 'volume' 'rm' '-f' $volume *>> $log
        }
    }
} else {
    Write-Line 'data volumes kept'
}

Write-Line 'done'
exit 0
