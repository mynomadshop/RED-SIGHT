<#
    Build-Installer.ps1

    Builds the RedSight Windows installer and the release .zip.

    Steps
      1. stage the application payload (from a source tree, or by extracting a
         previously shipped setup exe)
      2. strip virtualenvs, caches, backups and private data from the staging tree
      3. overlay the updated setup scripts into scripts\windows
      4. fetch the offline bundle (CPython 3.12 + wheelhouse) into runtime\bundle
      5. compile installer\RedSight.iss with ISCC
      6. package setup.exe + README + SHA256SUMS + manifest into the release zip

    Examples
      # from an application source tree
      pwsh -File installer/build/Build-Installer.ps1 -AppSource C:\src\RedSight -Version 11.3.0

      # reusing the payload of the previously shipped installer (Windows only)
      pwsh -File installer/build/Build-Installer.ps1 `
           -LegacyInstaller installer/legacy/RedSight-Setup-11.2.0.exe -Version 11.3.0
#>

[CmdletBinding()]
param(
    [string]$AppSource,
    [string]$LegacyInstaller,
    [string]$Version = '11.3.0',
    [string]$OutputDir = 'dist',
    [string]$StagingDir,
    [string]$IsccPath,
    [switch]$IncludeAllWheels,
    [switch]$SkipBundle,
    [switch]$StageOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$installerRoot = Split-Path -Parent $scriptDir
$repoRoot = Split-Path -Parent $installerRoot
. (Join-Path (Join-Path $installerRoot 'scripts') 'RedSight-Common.ps1')

if (-not $StagingDir) { $StagingDir = Join-Path $repoRoot 'build\staging' }
if (-not [System.IO.Path]::IsPathRooted($OutputDir)) { $OutputDir = Join-Path $repoRoot $OutputDir }

New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
Initialize-RsLog -Name 'build-installer' -LogDir (Join-Path $OutputDir '_logs') | Out-Null

Write-RsLog ('=' * 70)
Write-RsLog "REDSIGHT INSTALLER BUILD  version $Version"
Write-RsLog ('=' * 70)
Write-RsLog "repo      : $repoRoot"
Write-RsLog "staging   : $StagingDir"
Write-RsLog "output    : $OutputDir"

# ==========================================================================
# 1. Stage the application payload
# ==========================================================================

if (-not $AppSource -and -not $LegacyInstaller) {
    throw 'supply either -AppSource <dir> or -LegacyInstaller <setup.exe>'
}

if (Test-Path -LiteralPath $StagingDir) {
    Write-RsLog 'clearing the previous staging tree' -Level STEP
    Remove-Item -LiteralPath $StagingDir -Recurse -Force
}
New-Item -ItemType Directory -Path $StagingDir -Force | Out-Null

if ($AppSource) {
    $src = (Resolve-Path -LiteralPath $AppSource).Path
    Write-RsLog "copying the application tree from $src" -Level STEP
    # robocopy is dramatically faster than Copy-Item for tens of thousands of
    # files, and /XD prunes the heavy directories before they are ever copied.
    $robocopy = Get-RsSystem32 'robocopy.exe'
    if ([System.IO.File]::Exists($robocopy)) {
        $excludeDirs = @('.git', '.github', '.venv', '.venv-ui', '.venv-actions', '.venv-release-test',
                         'node_modules', '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache',
                         'backups', 'release', 'dist', 'build')
        $copyArgs = @($src, $StagingDir, '/E', '/NFL', '/NDL', '/NJH', '/NJS', '/NP', '/R:1', '/W:1', '/XD') + $excludeDirs
        $r = Invoke-RsProcess -FilePath $robocopy -Arguments $copyArgs -TimeoutSeconds 3600
        # robocopy uses a bit field: < 8 means success (files copied / extra files).
        if ($r.ExitCode -ge 8) { throw "robocopy failed with exit code $($r.ExitCode)" }
    } else {
        # Copy the contents, not the directory itself: Copy-Item of a folder
        # into an existing folder would nest it one level deeper.
        Copy-Item -Path (Join-Path $src '*') -Destination $StagingDir -Recurse -Force
    }
} else {
    $legacy = (Resolve-Path -LiteralPath $LegacyInstaller).Path
    Write-RsLog "extracting the application payload from $legacy" -Level STEP
    Write-RsLog '    (running the shipped installer silently with Python hidden from PATH,' -Level DEBUG
    Write-RsLog '     so its own first-run bootstrap exits immediately after the files land)' -Level DEBUG

    $savedPath = $env:PATH
    # A deliberately minimal PATH: no Python, Node or Docker for the old
    # bootstrap to find, so it fails fast instead of building venvs.
    $env:PATH = 'C:\Windows\system32;C:\Windows;C:\Windows\System32\Wbem;C:\Windows\System32\WindowsPowerShell\v1.0'
    try {
        $r = Invoke-RsProcess -FilePath $legacy `
                              -Arguments @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/NOCANCEL',
                                           "/DIR=$StagingDir", '/NOICONS', '/TASKS=',
                                           "/LOG=$(Join-Path $OutputDir 'legacy-extract.log')") `
                              -TimeoutSeconds 1800
        Write-RsLog "    legacy installer exit code: $($r.ExitCode)" -Level DEBUG
    } finally {
        $env:PATH = $savedPath
    }

    $count = @(Get-ChildItem -LiteralPath $StagingDir -Recurse -File -ErrorAction SilentlyContinue).Count
    if ($count -lt 100) {
        throw "payload extraction produced only $count files - the legacy installer did not unpack correctly"
    }
    Write-RsLog "    extracted $count files" -Level OK

    # The old installer registers itself in Add/Remove Programs; drop the
    # uninstaller it left behind so it cannot shadow the new one.
    foreach ($leftover in @('unins000.exe', 'unins000.dat', 'unins000.msg')) {
        $p = Join-Path $StagingDir $leftover
        if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue }
    }
}

# ==========================================================================
# 2. Clean the staging tree
# ==========================================================================

Write-RsLog 'pruning virtualenvs, caches, backups and private data' -Level STEP

$pruneDirs = @(
    '.git', '.github', '.venv', '.venv-ui', '.venv-actions', '.venv-release-test',
    '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache',
    'backups', 'release', 'dist', 'build', 'qdrant_storage', 'storage',
    'outputs',                          # local filesystem scan results
    'data\runtime',                     # runtime state
    'data\memory_exports',              # exported chat sessions
    'data\skills',                      # downloaded third-party skill sources
    'redsight_remote\state',            # private WhatsApp session auth
    'node_modules', '.repair-backups'
)
$prunedDirs = 0
foreach ($rel in $pruneDirs) {
    $p = Join-Path $StagingDir $rel
    if (Test-Path -LiteralPath $p) {
        Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction SilentlyContinue
        $prunedDirs++
    }
}
# Nested copies (any __pycache__ / node_modules deeper in the tree).
Get-ChildItem -LiteralPath $StagingDir -Recurse -Directory -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -in @('__pycache__', 'node_modules', '.pytest_cache', '.mypy_cache', '.ruff_cache') } |
    Sort-Object { $_.FullName.Length } -Descending |
    ForEach-Object {
        Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
        $prunedDirs++
    }

$pruneFilePatterns = @('*.bak', '*.backup-*', 'Dockerfile.backup-*', '*.pyc', '*.pyo',
                       'get-pip.py', '*.log', 'provider-secrets.json', 'secrets.json',
                       '*.sqlite', '*.sqlite3', '*.db', '*.lnk', '.env')
$prunedFiles = 0
foreach ($pattern in $pruneFilePatterns) {
    Get-ChildItem -LiteralPath $StagingDir -Recurse -File -Force -Filter $pattern -ErrorAction SilentlyContinue |
        ForEach-Object {
            Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue
            $prunedFiles++
        }
}
Write-RsLog "    pruned $prunedDirs director(ies) and $prunedFiles file(s)" -Level OK

# A .env in the payload would overwrite nothing (setup only creates it when
# absent) but it could leak the build machine's settings, so it is removed above
# and .env.example is required instead.
if (-not (Test-Path -LiteralPath (Join-Path $StagingDir '.env.example'))) {
    Write-RsLog '    .env.example is missing from the payload; setup will not be able to seed .env' -Level WARN
}

# ==========================================================================
# 3. Overlay the updated setup scripts
# ==========================================================================

Write-RsLog 'installing the updated setup scripts into scripts\windows' -Level STEP
$targetScripts = Join-Path $StagingDir 'scripts\windows'
New-Item -ItemType Directory -Path $targetScripts -Force | Out-Null

$overlay = @('RedSight-Common.ps1', 'RedSight-Preflight.ps1', 'Bootstrap-RedSight.ps1', 'Verify-RedSightSetup.ps1')
foreach ($name in $overlay) {
    $src = Join-Path (Join-Path $installerRoot 'scripts') $name
    if (-not (Test-Path -LiteralPath $src)) { throw "setup script missing from the repository: $src" }
    Copy-Item -LiteralPath $src -Destination (Join-Path $targetScripts $name) -Force
    Write-RsLog "    + scripts\windows\$name" -Level DEBUG
}

# The payload's own shortcut and Docker-cleanup helpers are kept as shipped;
# warn if the uninstall helper the .iss references is absent.
foreach ($expected in @('Install-RedSightDesktopShortcut.ps1', 'Uninstall-RedSightDocker.ps1')) {
    if (-not (Test-Path -LiteralPath (Join-Path $targetScripts $expected))) {
        Write-RsLog "    payload does not contain scripts\windows\$expected" -Level WARN
    }
}

Set-Content -LiteralPath (Join-Path $StagingDir 'VERSION') -Value $Version -Encoding utf8 -NoNewline

# ==========================================================================
# 4. Offline bundle
# ==========================================================================

if ($SkipBundle) {
    Write-RsLog 'skipping the offline bundle (-SkipBundle): setup will download Python if needed' -Level WARN
} else {
    $bundleDir = Join-Path $StagingDir 'runtime\bundle'
    $fetch = Join-Path $scriptDir 'Fetch-Bundles.ps1'
    Write-RsLog 'fetching the offline bundle (CPython 3.12 + wheelhouse)' -Level STEP
    $fetchArgs = @('-NoLogo', '-NoProfile', '-File', $fetch, '-Destination', $bundleDir, '-ProjectRoot', $StagingDir)
    if ($IncludeAllWheels) { $fetchArgs += '-IncludeAllWheels' }

    # Prefer pwsh when present; fall back to Windows PowerShell.
    $shell = (Get-RsCommand -Name 'pwsh')
    $shellPath = if ($shell) { $shell.Source } else { Get-RsPowerShellExe }
    $r = Invoke-RsProcess -FilePath $shellPath -Arguments $fetchArgs -TimeoutSeconds 5400
    if ($r.ExitCode -ne 0) { throw "Fetch-Bundles.ps1 failed with exit code $($r.ExitCode)" }
    Remove-Item -LiteralPath (Join-Path $bundleDir '_logs') -Recurse -Force -ErrorAction SilentlyContinue
}

$payloadFiles = @(Get-ChildItem -LiteralPath $StagingDir -Recurse -File -Force -ErrorAction SilentlyContinue)
$payloadBytes = ($payloadFiles | Measure-Object Length -Sum).Sum
Write-RsLog "staged payload: $($payloadFiles.Count) files, $([math]::Round($payloadBytes / 1MB, 1)) MB" -Level OK

if ($StageOnly) {
    Write-RsLog 'stopping after staging (-StageOnly)' -Level OK
    exit 0
}

# ==========================================================================
# 5. Compile
# ==========================================================================

function Find-Iscc {
    param([string]$Explicit)
    if ($Explicit) {
        if (Test-Path -LiteralPath $Explicit) { return (Resolve-Path -LiteralPath $Explicit).Path }
        throw "ISCC not found at the supplied path: $Explicit"
    }
    $cmd = Get-RsCommand -Name 'ISCC'
    if ($cmd) { return $cmd.Source }
    foreach ($base in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
        if (-not $base) { continue }
        foreach ($v in @('6', '5')) {
            $p = Join-Path $base "Inno Setup $v\ISCC.exe"
            if (Test-Path -LiteralPath $p) { return $p }
        }
    }
    throw 'ISCC.exe (the Inno Setup compiler) was not found. Install Inno Setup 6 or pass -IsccPath.'
}

$iscc = Find-Iscc -Explicit $IsccPath
Write-RsLog "compiling with $iscc" -Level STEP

$iss = Join-Path $installerRoot 'RedSight.iss'
$outputBase = "RedSight-Setup-$Version"
$icon = Join-Path $StagingDir 'assets\redsight.ico'

$isccArgs = @(
    $iss,
    "/DAppVersion=$Version",
    "/DPayloadDir=$StagingDir",
    "/DOutputDir=$OutputDir",
    "/DOutputBase=$outputBase"
)
if (Test-Path -LiteralPath $icon) { $isccArgs += "/DIconFile=$icon" }

$r = Invoke-RsProcess -FilePath $iscc -Arguments $isccArgs -TimeoutSeconds 5400
if ($r.ExitCode -ne 0) {
    Write-RsLog 'ISCC output:' -Level FAIL
    foreach ($l in (($r.StdOut + "`n" + $r.StdErr) -split "`r?`n")) {
        if ($l.Trim()) { Write-RsLog "  $l" -Level FAIL }
    }
    throw "ISCC failed with exit code $($r.ExitCode)"
}

$setupExe = Join-Path $OutputDir "$outputBase.exe"
if (-not (Test-Path -LiteralPath $setupExe)) { throw "ISCC reported success but $setupExe does not exist" }
$setupInfo = Get-Item -LiteralPath $setupExe
$setupHash = (Get-FileHash -LiteralPath $setupExe -Algorithm SHA256).Hash.ToLowerInvariant()
Write-RsLog "built $($setupInfo.Name) ($([math]::Round($setupInfo.Length / 1MB, 1)) MB)" -Level OK
Write-RsLog "  sha256 $setupHash" -Level OK

# ==========================================================================
# 6. Package the release zip
# ==========================================================================

Write-RsLog 'packaging the release zip' -Level STEP

$stage = Join-Path $OutputDir "_zip-$Version"
if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
New-Item -ItemType Directory -Path $stage -Force | Out-Null
Copy-Item -LiteralPath $setupExe -Destination $stage -Force

# SHA256SUMS
$sumsName = "SHA256SUMS-v$Version.txt"
"$setupHash  $($setupInfo.Name)" | Set-Content -LiteralPath (Join-Path $stage $sumsName) -Encoding ascii

# README
$readmeTemplate = Join-Path (Join-Path $installerRoot 'docs') 'README.template.txt'
$readmeOut = Join-Path $stage 'README.txt'
if (Test-Path -LiteralPath $readmeTemplate) {
    $text = Get-Content -LiteralPath $readmeTemplate -Raw
    $text = $text.Replace('{{VERSION}}', $Version).
                  Replace('{{SETUP_EXE}}', $setupInfo.Name).
                  Replace('{{SHA256}}', $setupHash).
                  Replace('{{SIZE_MB}}', [string][math]::Round($setupInfo.Length / 1MB, 1)).
                  Replace('{{SUMS_FILE}}', $sumsName).
                  Replace('{{BUILD_DATE}}', (Get-Date -Format 'yyyy-MM-dd'))
    Set-Content -LiteralPath $readmeOut -Value $text -Encoding utf8
} else {
    Write-RsLog "    README template not found at $readmeTemplate" -Level WARN
}

# Release manifest
$bundleManifestPath = Join-Path $StagingDir 'runtime\bundle\bundle-manifest.json'
$bundleManifest = $null
if (Test-Path -LiteralPath $bundleManifestPath) {
    $bundleManifest = Get-Content -LiteralPath $bundleManifestPath -Raw | ConvertFrom-Json
}

# Read the bundle facts out explicitly: on a PSCustomObject a property called
# 'count' can be shadowed by the intrinsic Count member, so go through PSObject.
function Get-JsonProp {
    param($Object, [string]$Name, $Default = $null)
    if (-not $Object) { return $Default }
    $prop = $Object.PSObject.Properties[$Name]
    if (-not $prop) { return $Default }
    return $prop.Value
}

$bundlePython = Get-JsonProp -Object $bundleManifest -Name 'python'
$bundleWheels = Get-JsonProp -Object $bundleManifest -Name 'wheelhouse'
$bundledInfo = [ordered]@{
    python              = Get-JsonProp -Object $bundlePython -Name 'version'
    python_source       = Get-JsonProp -Object $bundlePython -Name 'source'
    wheelhouse_count    = Get-JsonProp -Object $bundleWheels -Name 'count' -Default 0
    wheelhouse_complete = Get-JsonProp -Object $bundleWheels -Name 'complete' -Default $false
}

$manifest = [ordered]@{
    product = 'RedSight'
    version = $Version
    tag     = "v$Version"
    builtAt = (Get-Date -Format 'o')
    download = [ordered]@{
        file           = $setupInfo.Name
        size_bytes     = $setupInfo.Length
        sha256         = $setupHash
        installer_type = 'Inno Setup 6'
        code_signed    = $false
        silent_install_args = '/VERYSILENT /SUPPRESSMSGBOXES'
        requires       = @(
            'Windows 10 version 2004 (build 19041) or later, 64-bit',
            'Administrator privileges (setup installs Docker Desktop and enables WSL2)',
            'Internet access, unless installing from a full offline bundle'
        )
    }
    bundled = $bundledInfo
    auto_provisioned = @(
        'Python 3.12 private runtime (bundled; falls back to python.org)',
        'pip / setuptools / wheel (offline from the bundled wheelhouse)',
        '.venv-ui and .venv-actions virtual environments and their dependencies',
        'WSL2 platform (Microsoft-Windows-Subsystem-Linux + VirtualMachinePlatform)',
        'Docker Desktop (downloaded from docker.com and installed silently)',
        'Docker images for the redsight and qdrant services',
        'Node.js LTS (optional, WhatsApp remote utility only)',
        '.env seeded from .env.example',
        'build-machine install paths rewritten to the real install directory',
        'Desktop and Start Menu shortcuts'
    )
    payload = [ordered]@{
        files = $payloadFiles.Count
        bytes = $payloadBytes
    }
}
($manifest | ConvertTo-Json -Depth 8) |
    Set-Content -LiteralPath (Join-Path $stage "manifest-v$Version.json") -Encoding utf8

$zipPath = Join-Path $OutputDir "RedSightDesktopWindows$Version.zip"
if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction SilentlyContinue
[System.IO.Compression.ZipFile]::CreateFromDirectory((Resolve-Path -LiteralPath $stage).Path, $zipPath,
    [System.IO.Compression.CompressionLevel]::Optimal, $false)
Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue

$zipInfo = Get-Item -LiteralPath $zipPath
Write-RsLog ('=' * 70)
Write-RsLog 'BUILD COMPLETE' -Level OK
Write-RsLog "  installer : $setupExe"
Write-RsLog "  sha256    : $setupHash"
Write-RsLog "  release   : $zipPath ($([math]::Round($zipInfo.Length / 1MB, 1)) MB)"
Write-RsLog ('=' * 70)
