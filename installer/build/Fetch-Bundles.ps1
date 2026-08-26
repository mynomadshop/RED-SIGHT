<#
    Fetch-Bundles.ps1

    Downloads everything that ships inside the installer as an offline bundle:

      * the official Python Software Foundation CPython 3.12 build for Windows
        x64, taken from nuget.org/packages/python (a complete, relocatable
        distribution including ensurepip, venv, ssl and sqlite3)
      * a wheelhouse with the packaging tools needed to bootstrap a virtualenv
        without network access

    With -IncludeAllWheels it additionally downloads every wheel named by the
    application's requirements, producing a bundle that can install with no
    internet at all. That adds roughly a gigabyte (PySide6, torch, onnxruntime),
    which is why it is opt-in.

    Writes bundle-manifest.json next to the artifacts so the installer can
    verify each file's SHA256 before using it.

        pwsh -File installer/build/Fetch-Bundles.ps1 -Destination out/bundle
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Destination,
    [string]$PythonVersion = '3.12.10',
    [string]$ProjectRoot,
    [switch]$IncludeAllWheels,
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
. (Join-Path (Join-Path (Split-Path -Parent $scriptDir) 'scripts') 'RedSight-Common.ps1')

Initialize-RsLog -Name 'fetch-bundles' -LogDir (Join-Path $Destination '_logs') | Out-Null

New-Item -ItemType Directory -Path $Destination -Force | Out-Null
$wheelhouse = Join-Path $Destination 'wheelhouse'
New-Item -ItemType Directory -Path $wheelhouse -Force | Out-Null

$manifest = [ordered]@{
    generatedAt = (Get-Date -Format 'o')
    python      = [ordered]@{}
    wheelhouse  = [ordered]@{}
}

# --------------------------------------------------------------------------
# 1. CPython runtime
# --------------------------------------------------------------------------

$nupkgName = "python-$PythonVersion-win-x64.nupkg"
$nupkgPath = Join-Path $Destination $nupkgName
$nupkgUri = "https://api.nuget.org/v3-flatcontainer/python/$PythonVersion/python.$PythonVersion.nupkg"

if ($Force -and (Test-Path -LiteralPath $nupkgPath)) {
    Remove-Item -LiteralPath $nupkgPath -Force
}

Write-RsLog "fetching CPython $PythonVersion for Windows x64" -Level STEP
Save-RsDownload -Uri $nupkgUri -Destination $nupkgPath -Description "CPython $PythonVersion (nuget)" | Out-Null

# Sanity-check the package really is a Windows CPython distribution before we
# ship it: a silently-redirected download would otherwise fail at install time.
Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction SilentlyContinue
$zip = [System.IO.Compression.ZipFile]::OpenRead((Resolve-Path -LiteralPath $nupkgPath).Path)
try {
    $names = @($zip.Entries | ForEach-Object { $_.FullName })
} finally {
    $zip.Dispose()
}
foreach ($required in @('tools/python.exe', 'tools/Lib/venv/__init__.py', 'tools/Lib/ensurepip/__init__.py')) {
    if ($names -notcontains $required) {
        throw "the downloaded CPython package is missing $required - refusing to ship it"
    }
}
$pipWheel = @($names | Where-Object { $_ -like 'tools/Lib/ensurepip/_bundled/pip-*.whl' }) | Select-Object -First 1
Write-RsLog "    verified: python.exe, venv, ensurepip ($(Split-Path -Leaf $pipWheel))" -Level OK

$manifest.python.version = $PythonVersion
$manifest.python.file = $nupkgName
$manifest.python.sha256 = Get-RsFileHashSafe -Path $nupkgPath
$manifest.python.size = (Get-Item -LiteralPath $nupkgPath).Length
$manifest.python.source = $nupkgUri
$manifest.python.entries = $names.Count

# --------------------------------------------------------------------------
# 2. Wheelhouse
# --------------------------------------------------------------------------

# Any Python can drive `pip download` for a different target platform, so this
# works on the Linux CI leg as well as on Windows.
$pip = $null
foreach ($candidate in @('python3', 'python', 'py')) {
    $cmd = Get-RsCommand -Name $candidate
    if ($cmd) {
        $r = Invoke-RsProcess -FilePath $cmd.Source -Arguments @('-m', 'pip', '--version') -TimeoutSeconds 120 -Quiet
        if ($r.ExitCode -eq 0) { $pip = $cmd.Source; break }
    }
}
if (-not $pip) {
    Write-RsLog 'no local Python with pip found - skipping the wheelhouse (the installer will fall back to PyPI)' -Level WARN
} else {
    Write-RsLog "building the wheelhouse with $pip" -Level STEP

    # Cross-platform download: always target CPython 3.12 on Windows x64,
    # binary-only, so the wheels are usable by the bundled runtime.
    $targetArgs = @(
        '--only-binary=:all:',
        '--platform', 'win_amd64',
        '--python-version', '312',
        '--implementation', 'cp',
        '--dest', $wheelhouse
    )

    # Always bundled: the packaging tools a fresh venv needs before it can
    # reach the network at all.
    $bootstrapPkgs = @('pip', 'setuptools', 'wheel')

    $groups = @(@{ Label = 'bootstrap packaging tools'; Packages = $bootstrapPkgs; Files = @() })

    if ($IncludeAllWheels) {
        if (-not $ProjectRoot) { throw '-IncludeAllWheels requires -ProjectRoot so the requirements files can be found' }
        $reqFiles = @()
        foreach ($name in @('requirements-desktop-stage11.txt', 'requirements-stage111-actions.txt')) {
            $p = Join-Path $ProjectRoot $name
            if (Test-Path -LiteralPath $p) { $reqFiles += $p }
        }
        if ($reqFiles.Count) {
            $groups += @{ Label = 'application requirements'; Packages = @(); Files = $reqFiles }
        }
        # The heavy desktop stack comes from pyproject rather than a requirements file.
        $groups += @{ Label = 'desktop runtime stack'
                      Packages = @('PySide6', 'qasync', 'httpx', 'pydantic', 'pydantic-settings',
                                   'fastapi', 'uvicorn[standard]', 'qdrant-client', 'structlog', 'rich')
                      Files = @() }
    }

    foreach ($group in $groups) {
        $pipArgs = @('-m', 'pip', 'download') + $targetArgs
        foreach ($f in $group.Files) { $pipArgs += @('-r', $f) }
        $pipArgs += $group.Packages

        Write-RsLog "    downloading $($group.Label)" -Level STEP
        $r = Invoke-RsProcess -FilePath $pip -Arguments $pipArgs -TimeoutSeconds 3600
        if ($r.ExitCode -ne 0) {
            if ($group.Label -eq 'bootstrap packaging tools') {
                throw "could not download the bootstrap packaging tools (pip exit $($r.ExitCode))"
            }
            # Optional groups: a single unresolvable wheel must not fail the build.
            Write-RsLog "    $($group.Label) could not be fully downloaded (pip exit $($r.ExitCode)); the installer will fetch the rest from PyPI" -Level WARN
        }
    }

    $wheels = @(Get-ChildItem -LiteralPath $wheelhouse -Filter '*.whl' -File -ErrorAction SilentlyContinue)
    $bytes = ($wheels | Measure-Object Length -Sum).Sum
    if (-not $bytes) { $bytes = 0 }
    Write-RsLog "wheelhouse: $($wheels.Count) wheel(s), $([math]::Round($bytes / 1MB, 1)) MB" -Level OK

    $manifest.wheelhouse.count = $wheels.Count
    $manifest.wheelhouse.bytes = $bytes
    $manifest.wheelhouse.complete = [bool]$IncludeAllWheels
    $manifest.wheelhouse.files = @($wheels | ForEach-Object {
        [ordered]@{ name = $_.Name; sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() }
    })
}

# --------------------------------------------------------------------------
# 3. Manifest
# --------------------------------------------------------------------------

$manifestPath = Join-Path $Destination 'bundle-manifest.json'
($manifest | ConvertTo-Json -Depth 8) | Set-Content -LiteralPath $manifestPath -Encoding utf8
Write-RsLog "wrote $manifestPath" -Level OK

Write-RsLog ('=' * 60)
Write-RsLog "bundle ready in $Destination"
Write-RsLog "  python : $nupkgName ($([math]::Round($manifest.python.size / 1MB, 1)) MB)"
if ($manifest.wheelhouse.Contains('count')) {
    Write-RsLog "  wheels : $($manifest.wheelhouse['count'])"
}
Write-RsLog ('=' * 60)
