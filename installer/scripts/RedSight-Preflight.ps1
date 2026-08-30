<#
    RedSight-Preflight.ps1

    The RedSight dependency engine. Every external dependency RedSight needs is
    described here as a detect / provision / verify triple:

        Python 3.12      bundled official CPython, or a suitable one on PATH
        pip              seeded from the runtime's own ensurepip (offline)
        PyTorch          the CUDA build whose kernels match the installed GPUs
        virtualenvs      .venv-ui and .venv-actions, dependencies installed
        WSL2             Windows features enabled, kernel updated
        Docker Desktop   downloaded and installed silently, engine started
        Docker images    built via docker compose
        Node.js          LTS MSI, only for the optional WhatsApp bridge
        LM Studio        local server located, started and its model recorded
        .env             created from .env.example
        install paths    author-machine absolute paths rewritten

    Dot-source this file to use the functions, or run it directly with -Report
    to get a read-only dependency report (nothing is installed or changed).

    Every provision function is idempotent and safe to re-run.
#>

[CmdletBinding()]
param(
    [string]$ProjectRoot,
    [switch]$Report
)

Set-StrictMode -Version Latest

# Dot-source the shared helpers from the same directory.
$script:RsScriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
. (Join-Path $script:RsScriptDir 'RedSight-Common.ps1')
. (Join-Path $script:RsScriptDir 'RedSight-LmStudio.ps1')
. (Join-Path $script:RsScriptDir 'RedSight-Provision.ps1')

# --------------------------------------------------------------------------
# Pinned dependency versions and sources
# --------------------------------------------------------------------------

$script:RsPython = @{
    # Bundled runtime: the official Python Software Foundation CPython build for
    # Windows x64, redistributed as a NuGet package (nuget.org/packages/python).
    Version      = '3.12.10'
    BundleName   = 'python-3.12.10-win-x64.nupkg'
    BundleSha256 = ''   # filled in by Fetch-Bundles.ps1 into bundle-manifest.json
    # Fallback if the bundle is missing: the python.org web installer.
    WebUri       = 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe'
    MinVersion   = [version]'3.12.0'
    MaxExclusive = [version]'3.14.0'
}

$script:RsDocker = @{
    InstallerUri  = 'https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe'
    InstallerName = 'DockerDesktopInstaller.exe'
    # Docker Desktop takes a long time to come up on first launch.
    EngineWaitSeconds = 300
}

$script:RsNode = @{
    IndexUri       = 'https://nodejs.org/dist/index.json'
    FallbackUri    = 'https://nodejs.org/dist/v22.14.0/node-v22.14.0-x64.msi'
    FallbackVersion = '22.14.0'
    MinVersion     = [version]'18.0.0'
}

function Get-RsBundleRoot {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$ProjectRoot)
    return (Join-Path $ProjectRoot 'runtime\bundle')
}

function Get-RsRuntimePythonDir {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$ProjectRoot)
    return (Join-Path $ProjectRoot 'runtime\python')
}

function Get-RsWheelhouse {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$ProjectRoot)
    $wh = Join-Path (Get-RsBundleRoot -ProjectRoot $ProjectRoot) 'wheelhouse'
    if (Test-Path -LiteralPath $wh) { return $wh }
    return $null
}

function Get-RsDownloadCache {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$ProjectRoot)
    # Downloads live outside the app dir so an uninstall/reinstall can reuse
    # them and so a read-only Program Files install still works. Test the
    # variable before joining: Join-Path throws on a null Path.
    $dir = if ($env:ProgramData) { Join-Path $env:ProgramData 'RedSight\downloads' }
           else { Join-Path $ProjectRoot 'runtime\downloads' }
    New-Item -ItemType Directory -Path $dir -Force -ErrorAction SilentlyContinue | Out-Null
    return $dir
}

# ==========================================================================
# Hardware profile
# ==========================================================================

$script:RsHardwareProfile = $null

function Get-RsHardwareProfile {
    <#
        Returns the machine capability profile produced by RedSight-Hardware.ps1.

        The installer wizard already runs that scan before installing, so it can
        hand the result over with -ProfilePath rather than paying for a second
        scan; otherwise it is run here. Cached for the life of the process.
    #>
    [CmdletBinding()]
    param(
        [string]$ProfilePath,
        [switch]$Refresh
    )

    if ($script:RsHardwareProfile -and -not $Refresh) { return $script:RsHardwareProfile }

    if ($ProfilePath -and (Test-Path -LiteralPath $ProfilePath)) {
        try {
            $script:RsHardwareProfile = Get-Content -LiteralPath $ProfilePath -Raw | ConvertFrom-Json
            Write-RsLog "loaded the hardware profile from $ProfilePath" -Level DEBUG
            return $script:RsHardwareProfile
        } catch {
            Write-RsLog "could not read the hardware profile at $ProfilePath : $($_.Exception.Message)" -Level WARN
        }
    }

    $scanner = Join-Path $script:RsScriptDir 'RedSight-Hardware.ps1'
    if (-not (Test-Path -LiteralPath $scanner)) {
        Write-RsLog "hardware scanner not found at $scanner" -Level WARN
        return $null
    }

    Write-RsLog 'scanning hardware capabilities' -Level STEP
    $r = Invoke-RsProcess -FilePath (Get-RsPowerShellExe) `
                          -Arguments @('-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                                       '-File', $scanner, '-Json', '-Quiet') `
                          -TimeoutSeconds 300 -Quiet
    if ($r.ExitCode -ne 0 -or -not $r.StdOut.Trim()) {
        Write-RsLog "hardware scan produced no output (exit $($r.ExitCode))" -Level WARN
        return $null
    }
    try {
        $script:RsHardwareProfile = $r.StdOut | ConvertFrom-Json
    } catch {
        Write-RsLog "could not parse the hardware scan output: $($_.Exception.Message)" -Level WARN
        return $null
    }
    return $script:RsHardwareProfile
}

function Test-RsVirtualizationAvailable {
    <#
        True when this machine can actually run WSL2 / Docker Desktop.

        Earlier builds skipped this and enabled the WSL2 Windows features on
        machines whose firmware has virtualization switched off, which left a
        half-configured system: the features were on, Docker was installed, and
        the engine could never start. Setup now refuses to begin that work and
        falls back to native mode instead.
    #>
    [CmdletBinding()]
    param([string]$ProfilePath)

    $hw = Get-RsHardwareProfile -ProfilePath $ProfilePath
    if (-not $hw) {
        # No profile: fall back to a direct check rather than guessing.
        try {
            $cs = Get-CimInstance -ClassName Win32_ComputerSystem -ErrorAction Stop
            if ($cs.HypervisorPresent) { return $true }
            $cpu = Get-CimInstance -ClassName Win32_Processor -ErrorAction Stop | Select-Object -First 1
            return [bool]$cpu.VirtualizationFirmwareEnabled
        } catch {
            return $false
        }
    }
    return [bool]$hw.virtualization.wsl2Capable
}

# ==========================================================================
# Python
# ==========================================================================

function Get-RsPythonVersion {
    <# Runs an interpreter and returns its [version], or $null if unusable. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$PythonExe)

    if (-not (Test-Path -LiteralPath $PythonExe)) { return $null }
    $r = Invoke-RsProcess -FilePath $PythonExe -Arguments @('-c', 'import sys; print("%d.%d.%d" % sys.version_info[:3])') `
                          -TimeoutSeconds 60 -Quiet
    if ($r.ExitCode -ne 0) { return $null }
    return (ConvertTo-RsVersion -Text $r.StdOut)
}

function Test-RsPythonUsable {
    <#
        A usable interpreter is in the supported version range AND can create
        virtual environments (the Microsoft Store shim, for example, reports a
        fine version but cannot).
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$PythonExe)

    $v = Get-RsPythonVersion -PythonExe $PythonExe
    if (-not (Test-RsVersionInRange -Version $v -Minimum $script:RsPython.MinVersion -ExclusiveMaximum $script:RsPython.MaxExclusive)) {
        return $false
    }
    $r = Invoke-RsProcess -FilePath $PythonExe -Arguments @('-c', 'import venv, ensurepip, ssl, sqlite3, ctypes') `
                          -TimeoutSeconds 60 -Quiet
    return ($r.ExitCode -eq 0)
}

function Find-RsSystemPython {
    <#
        Looks for a supported Python already on the machine, in preference
        order. Returns the interpreter path or $null.
    #>
    [CmdletBinding()] param()

    $candidates = New-Object System.Collections.Generic.List[string]

    # The py launcher knows about every registered install.
    $py = Get-RsCommand -Name 'py'
    if ($py) {
        foreach ($tag in @('-3.12', '-3.13')) {
            $r = Invoke-RsProcess -FilePath $py.Source -Arguments @($tag, '-c', 'import sys; print(sys.executable)') `
                                  -TimeoutSeconds 60 -Quiet
            if ($r.ExitCode -eq 0) {
                $p = $r.StdOut.Trim()
                if ($p -and (Test-Path -LiteralPath $p)) { $candidates.Add($p) }
            }
        }
    }

    foreach ($name in @('python3.12', 'python3', 'python')) {
        $cmd = Get-RsCommand -Name $name
        if ($cmd) { $candidates.Add($cmd.Source) }
    }

    # Common per-machine / per-user install locations, in case PATH is not set.
    $userPrograms = if ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA 'Programs' } else { $null }
    foreach ($base in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $userPrograms)) {
        if (-not $base) { continue }
        foreach ($v in @('312', '313')) {
            $p = Join-Path $base "Python\Python$v\python.exe"
            if (Test-Path -LiteralPath $p) { $candidates.Add($p) }
        }
    }

    foreach ($c in $candidates) {
        # WindowsApps entries are Store shims that cannot create venvs.
        if ($c -like '*\WindowsApps\*') {
            Write-RsLog "ignoring Microsoft Store Python shim: $c" -Level DEBUG
            continue
        }
        if (Test-RsPythonUsable -PythonExe $c) {
            Write-RsLog "found usable system Python: $c" -Level OK
            return $c
        }
        Write-RsLog "unsuitable Python (wrong version or incomplete): $c" -Level DEBUG
    }
    return $null
}

function Install-RsBundledPython {
    <#
        Expands the bundled official CPython into {app}\runtime\python. This is
        a private, self-contained interpreter: it is never added to PATH and
        never registered, so it cannot conflict with any other Python on the
        machine (which is exactly the contamination the old bootstrap fought
        with sys.path stripping).
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$ProjectRoot, [switch]$Force)

    $target = Get-RsRuntimePythonDir -ProjectRoot $ProjectRoot
    $exe = Join-Path $target 'python.exe'

    if ((Test-Path -LiteralPath $exe) -and -not $Force) {
        if (Test-RsPythonUsable -PythonExe $exe) {
            Write-RsLog "bundled Python runtime already present: $exe" -Level OK
            return $exe
        }
        Write-RsLog 'bundled Python runtime present but unusable - re-expanding' -Level WARN
    }

    $bundleRoot = Get-RsBundleRoot -ProjectRoot $ProjectRoot
    $nupkg = Join-Path $bundleRoot $script:RsPython.BundleName
    if (-not (Test-Path -LiteralPath $nupkg)) {
        Write-RsLog "bundled Python package not found at $nupkg" -Level WARN
        return $null
    }

    # Verify against the manifest recorded at build time, when present.
    $manifest = Join-Path $bundleRoot 'bundle-manifest.json'
    if (Test-Path -LiteralPath $manifest) {
        try {
            $mf = Get-Content -LiteralPath $manifest -Raw | ConvertFrom-Json
            $expected = $mf.python.sha256
            if ($expected) {
                $actual = Get-RsFileHashSafe -Path $nupkg
                if ($actual -ne $expected.ToLowerInvariant()) {
                    throw "bundled Python package SHA256 mismatch: expected $expected, got $actual"
                }
                Write-RsLog "bundled Python package hash verified ($expected)" -Level OK
            }
        } catch {
            Write-RsLog "bundle manifest check failed: $($_.Exception.Message)" -Level FAIL
            throw
        }
    }

    Write-RsLog "expanding bundled CPython $($script:RsPython.Version) into $target" -Level STEP
    $staging = Join-Path (Get-RsDownloadCache -ProjectRoot $ProjectRoot) 'python-nupkg'
    Expand-RsArchive -Path $nupkg -Destination $staging -Force | Out-Null

    # The NuGet layout puts the whole distribution under tools\.
    $tools = Join-Path $staging 'tools'
    if (-not (Test-Path -LiteralPath (Join-Path $tools 'python.exe'))) {
        throw "unexpected bundle layout: $tools\python.exe not found"
    }

    if (Test-Path -LiteralPath $target) {
        Remove-Item -LiteralPath $target -Recurse -Force -ErrorAction SilentlyContinue
    }
    New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force -ErrorAction SilentlyContinue | Out-Null
    Move-Item -LiteralPath $tools -Destination $target -Force
    Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue

    if (-not (Test-Path -LiteralPath $exe)) { throw "bundled Python expansion failed: $exe missing" }

    # A private interpreter must not pick up a stray PYTHONPATH/PYTHONHOME.
    $v = Get-RsPythonVersion -PythonExe $exe
    Write-RsLog "bundled Python ready: $exe (version $v)" -Level OK
    return $exe
}

function Install-RsPythonFromWeb {
    <#
        Last-resort provisioning: download and silently run the official
        python.org installer, putting Python on PATH for all users.
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$ProjectRoot)

    if (-not (Test-RsAdmin)) {
        Write-RsLog 'not elevated - cannot install Python for all users' -Level WARN
    }

    $cache = Get-RsDownloadCache -ProjectRoot $ProjectRoot
    $installer = Join-Path $cache "python-$($script:RsPython.Version)-amd64.exe"
    Save-RsDownload -Uri $script:RsPython.WebUri -Destination $installer `
                    -Description "Python $($script:RsPython.Version) installer" | Out-Null

    Write-RsLog 'running the Python installer silently' -Level STEP
    $pyArgs = @('/quiet', 'InstallAllUsers=1', 'PrependPath=1', 'Include_test=0',
              'Include_launcher=1', 'AssociateFiles=0', 'Shortcuts=0', 'Include_doc=0')
    $r = Invoke-RsProcess -FilePath $installer -Arguments $pyArgs -TimeoutSeconds 1800

    # 3010 = success, reboot required.
    if ($r.ExitCode -notin @(0, 3010)) {
        throw "Python installer failed with exit code $($r.ExitCode)"
    }
    Update-RsProcessPath

    $found = Find-RsSystemPython
    if (-not $found) { throw 'Python was installed but no usable interpreter could be found afterwards' }
    Write-RsLog "Python installed from python.org: $found" -Level OK
    return $found
}

function Resolve-RsPython {
    <#
        Returns the interpreter RedSight should build its virtualenvs with,
        provisioning one if necessary.

        Order:
          1. the private bundled runtime (deterministic, already on disk)
          2. a suitable Python already on the machine
          3. expand the bundle
          4. download from python.org

        -PreferSystemPython swaps 1 and 2 for users who want their own install
        used.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$ProjectRoot,
        [switch]$PreferSystemPython,
        [switch]$OfflineOnly,
        [switch]$DetectOnly
    )

    $runtimeExe = Join-Path (Get-RsRuntimePythonDir -ProjectRoot $ProjectRoot) 'python.exe'

    if ($PreferSystemPython) {
        $probes = @({ Find-RsSystemPython }, { if (Test-Path -LiteralPath $runtimeExe) { $runtimeExe } else { $null } })
    } else {
        $probes = @({ if (Test-Path -LiteralPath $runtimeExe) { $runtimeExe } else { $null } })
    }

    foreach ($probe in $probes) {
        $candidate = & $probe
        if ($candidate -and (Test-RsPythonUsable -PythonExe $candidate)) {
            Write-RsLog "using Python: $candidate" -Level OK
            return $candidate
        }
    }

    if ($DetectOnly) { return (Find-RsSystemPython) }

    # Default order: expand the bundled runtime BEFORE falling back to whatever
    # Python happens to be installed. The bundle is the whole reason the install
    # is deterministic - a system interpreter may carry a stray PYTHONPATH or
    # site-packages that the app then inherits. Earlier builds probed the
    # expanded runtime directory first, found it absent (the bundle ships as a
    # .nupkg and is expanded here), and silently used the system Python instead,
    # so the bundle was effectively never used.
    if (-not $PreferSystemPython) {
        Write-RsLog 'providing the private bundled Python runtime' -Level STEP
        $bundled = Install-RsBundledPython -ProjectRoot $ProjectRoot
        if ($bundled -and (Test-RsPythonUsable -PythonExe $bundled)) {
            Write-RsLog "using Python: $bundled (private runtime)" -Level OK
            return $bundled
        }
        Write-RsLog 'the bundled runtime is unavailable; falling back to a system Python' -Level WARN
    }

    $system = Find-RsSystemPython
    if ($system) {
        Write-RsLog "using Python: $system (system install)" -Level OK
        return $system
    }

    Write-RsLog "no suitable Python $($script:RsPython.MinVersion) found - provisioning" -Level STEP
    $bundled = Install-RsBundledPython -ProjectRoot $ProjectRoot
    if ($bundled) { return $bundled }

    if ($OfflineOnly) {
        throw "No suitable Python and no bundled runtime available, and -OfflineOnly forbids downloading."
    }
    return (Install-RsPythonFromWeb -ProjectRoot $ProjectRoot)
}

# ==========================================================================
# Virtual environments
# ==========================================================================

function Initialize-RsVenv {
    <#
        Creates (or repairs) a virtualenv and installs the requested packages.
        Wheelhouse-first: when a bundled wheelhouse exists it is passed as
        --find-links so pip prefers local wheels, and with -OfflineOnly the
        package index is disabled entirely.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$PythonExe,
        [Parameter(Mandatory)][string]$VenvPath,
        [string]$Description = 'virtualenv',
        [string[]]$RequirementFiles = @(),
        [string[]]$Packages = @(),
        [string[]]$EditableProjects = @(),
        [object[]]$PreInstalls = @(),
        [string]$Wheelhouse,
        [switch]$OfflineOnly,
        [switch]$Recreate,
        [int]$TimeoutSeconds = 3600
    )

    $venvPython = Join-Path $VenvPath 'Scripts\python.exe'

    if ($Recreate -and (Test-Path -LiteralPath $VenvPath)) {
        Write-RsLog "removing existing $Description at $VenvPath" -Level STEP
        Remove-Item -LiteralPath $VenvPath -Recurse -Force -ErrorAction SilentlyContinue
    }

    if (-not (Test-Path -LiteralPath $venvPython)) {
        Write-RsLog "creating $Description at $VenvPath" -Level STEP
        $r = Invoke-RsProcess -FilePath $PythonExe -Arguments @('-m', 'venv', $VenvPath) -TimeoutSeconds 900
        if ($r.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $venvPython)) {
            # A partially created venv poisons every later attempt.
            Remove-Item -LiteralPath $VenvPath -Recurse -Force -ErrorAction SilentlyContinue
            throw "could not create $Description (exit $($r.ExitCode)): $($r.StdErr)"
        }
    } else {
        Write-RsLog "$Description already exists at $VenvPath" -Level OK
    }

    # Common pip arguments. --no-input keeps pip from ever blocking on a prompt.
    $common = @('--disable-pip-version-check', '--no-input')
    if ($Wheelhouse -and (Test-Path -LiteralPath $Wheelhouse)) {
        $common += @('--find-links', $Wheelhouse, '--prefer-binary')
        Write-RsLog "    using wheelhouse $Wheelhouse" -Level DEBUG
    }
    if ($OfflineOnly) {
        $common += '--no-index'
        Write-RsLog '    offline mode: package index disabled' -Level DEBUG
    }

    # Upgrade pip itself first; failure here is not fatal, the shipped pip works.
    $r = Invoke-RsProcess -FilePath $venvPython -Arguments (@('-m', 'pip', 'install', '--upgrade', 'pip', 'setuptools', 'wheel') + $common) `
                          -TimeoutSeconds 900
    if ($r.ExitCode -ne 0) {
        Write-RsLog "    pip self-upgrade failed (continuing with bundled pip): exit $($r.ExitCode)" -Level WARN
    }

    $installs = New-Object System.Collections.Generic.List[object]
    # PreInstalls run first on purpose: pinning torch to the CPU or CUDA wheel
    # index up front means the later resolution sees it already satisfied and
    # does not pull the multi-gigabyte default build over the top.
    foreach ($pre in $PreInstalls) { $installs.Add($pre) }
    foreach ($proj in $EditableProjects) { $installs.Add(@{ Label = "editable $proj"; Args = @('-e', $proj) }) }
    foreach ($file in $RequirementFiles) {
        if (Test-Path -LiteralPath $file) {
            $installs.Add(@{ Label = "requirements $(Split-Path -Leaf $file)"; Args = @('-r', $file) })
        } else {
            Write-RsLog "    requirements file not found, skipping: $file" -Level DEBUG
        }
    }
    if ($Packages.Count) { $installs.Add(@{ Label = 'explicit packages'; Args = $Packages }) }

    foreach ($install in $installs) {
        Write-RsLog "    installing $($install.Label) into $Description" -Level STEP
        $null = Invoke-RsRetry -Description "pip install $($install.Label)" -MaxAttempts 3 -Action {
            $res = Invoke-RsProcess -FilePath $venvPython `
                                    -Arguments (@('-m', 'pip', 'install') + $common + $install.Args) `
                                    -TimeoutSeconds $TimeoutSeconds
            if ($res.TimedOut) { throw "pip install timed out after ${TimeoutSeconds}s" }
            if ($res.ExitCode -ne 0) {
                $tail = ($res.StdOut + "`n" + $res.StdErr) -split "`r?`n" |
                        Where-Object { $_.Trim() } | Select-Object -Last 8
                throw "pip exit $($res.ExitCode): $($tail -join ' | ')"
            }
        }
        Write-RsLog "    installed $($install.Label)" -Level OK
    }

    return $venvPython
}

function Test-RsTorchCuda {
    <#
        Answers "can torch actually use this machine's GPUs?" - not "is a CUDA
        build installed", which is the question that has been passing while the
        answer to the real one was no.

        A PyTorch wheel carries compiled kernels for a fixed list of
        architectures. Running a cu124 build on an RTX 50-series card (sm_120)
        gets "no kernel image is available for execution on the device" on the
        first GPU operation, having reported a successful import and even
        torch.cuda.is_available() == True. The only honest check is to compare
        each device's capability against torch.cuda.get_arch_list() and then run
        a real operation on the device.

        Returns Ok / Detail / Devices / ArchList / Version. Never throws: on an
        API-profile machine there is nothing to check.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$VenvPython,
        [Parameter(Mandatory)][string]$ProjectRoot,
        [int]$TimeoutSeconds = 300
    )

    $result = [pscustomobject]@{
        Ok = $false; Detail = ''; Devices = ''; ArchList = ''; Version = ''; Usable = $false
    }
    if (-not (Test-Path -LiteralPath $VenvPython)) {
        $result.Detail = "interpreter not found: $VenvPython"
        return $result
    }

    $code = @'
import json, sys
report = {"imported": False}
try:
    import torch
except Exception as exc:
    report["error"] = f"{type(exc).__name__}: {exc}"
    print("TORCH_REPORT=" + json.dumps(report))
    sys.exit(0)

report["imported"] = True
report["version"] = torch.__version__
try:
    report["arch_list"] = list(torch.cuda.get_arch_list())
except Exception:
    report["arch_list"] = []
report["available"] = bool(torch.cuda.is_available())
report["device_count"] = torch.cuda.device_count() if report["available"] else 0

devices = []
for index in range(report["device_count"]):
    entry = {"index": index}
    try:
        entry["name"] = torch.cuda.get_device_name(index)
        major, minor = torch.cuda.get_device_capability(index)
        entry["capability"] = f"{major}.{minor}"
        entry["supported"] = f"sm_{major}{minor}" in report["arch_list"]
        # A real allocation and a real kernel: this is where a wheel without
        # kernels for the device finally admits it.
        torch.zeros(64, device=f"cuda:{index}").sum().item()
        entry["works"] = True
    except Exception as exc:
        entry["works"] = False
        entry["error"] = f"{type(exc).__name__}: {exc}"[:400]
    devices.append(entry)

report["devices"] = devices
report["usable"] = bool(devices) and all(d.get("works") for d in devices)
print("TORCH_REPORT=" + json.dumps(report))
'@

    $r = Invoke-RsProcess -FilePath $VenvPython -Arguments @('-c', $code) `
                          -WorkingDirectory $ProjectRoot -TimeoutSeconds $TimeoutSeconds -Quiet
    if ($r.TimedOut) {
        $result.Detail = "the torch CUDA check timed out after ${TimeoutSeconds}s"
        return $result
    }

    $match = [regex]::Match(($r.StdOut + "`n" + $r.StdErr), 'TORCH_REPORT=(\{.*\})')
    if (-not $match.Success) {
        $result.Detail = 'the torch CUDA check produced no report'
        return $result
    }

    try {
        $report = $match.Groups[1].Value | ConvertFrom-Json
    } catch {
        $result.Detail = "could not read the torch report: $($_.Exception.Message)"
        return $result
    }

    if (-not $report.imported) {
        $result.Detail = "torch could not be imported: $($report.error)"
        return $result
    }

    $result.Ok = $true
    $result.Version = "$($report.version)"
    $result.ArchList = (@($report.arch_list) -join ' ')
    $result.Usable = [bool]$report.usable

    if (-not $report.available) {
        $result.Detail = "torch $($report.version) is installed but reports no CUDA device"
        return $result
    }

    $lines = New-Object System.Collections.Generic.List[string]
    foreach ($d in @($report.devices)) {
        $verdict = if ($d.works) { 'works' } else { "FAILS - $($d.error)" }
        $lines.Add("GPU $($d.index) $($d.name) sm_$(("$($d.capability)" -replace '\.', '')) $verdict")
    }
    $result.Devices = ($lines.ToArray() -join ' | ')

    if ($result.Usable) {
        $result.Detail = "torch $($report.version) runs on $($report.device_count) GPU(s)"
    } else {
        $result.Detail = ("torch $($report.version) cannot run this machine's GPU(s). " +
                         "Its wheel carries kernels for: $($result.ArchList)")
    }
    return $result
}

function Test-RsUiLaunch {
    <#
        Answers "will the Command Center actually start?" by importing the exact
        chain launch_redsight_command_center.py imports, in the real environment,
        with Qt on its offscreen platform so no display is needed.

        A plain module-presence check is not enough here: the UI has repeatedly
        failed at startup on a fully installed environment (the missing qasync in
        11.1, a Qt bootstrap raising at import time), and only a real import
        reproduces that. Returns the traceback so the failure is actionable
        instead of "the UI did not launch".
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$VenvPython,
        [Parameter(Mandatory)][string]$ProjectRoot,
        [int]$TimeoutSeconds = 300
    )

    $result = [pscustomobject]@{ Ok = $false; Detail = ''; Traceback = ''; Fixes = '' }
    if (-not (Test-Path -LiteralPath $VenvPython)) {
        $result.Detail = "interpreter not found: $VenvPython"
        return $result
    }

    $code = @'
import os, sys, traceback
root = sys.argv[1]
if root not in sys.path:
    sys.path.insert(0, root)
# Import Qt headlessly: this must not require a desktop session.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
stage = "start"
try:
    stage = "PySide6.QtWidgets"
    import PySide6.QtWidgets  # noqa: F401
    stage = "qasync"
    import qasync  # noqa: F401
    stage = "app.ui.qt_bootstrap"
    import app.ui.qt_bootstrap as qb
    stage = "configure_qt_pre_application"
    if hasattr(qb, "configure_qt_pre_application"):
        qb.configure_qt_pre_application()
    stage = "QApplication"
    app = PySide6.QtWidgets.QApplication.instance() or PySide6.QtWidgets.QApplication([])
    stage = "app.ui.command_center"
    import app.ui.command_center  # noqa: F401
    print("UI_LAUNCH_OK")
except Exception:
    print("UI_LAUNCH_FAILED_AT=" + stage)
    traceback.print_exc()
    sys.exit(1)

# The Stage 11.5 fixes - the LM Studio endpoint, the redirected status probes,
# nvidia-smi off the GUI thread and the calmed animation - are installed by an
# overlay module. It is wired into the launcher inside a try/except so the UI
# always starts, which also means a failure there would be invisible. Report it.
try:
    import json
    from app.ui import action_palette_stage115_lmstudio as rs115
    print("UI_FIXES=" + json.dumps(rs115.install(), default=str))
except Exception as exc:
    print("UI_FIXES_FAILED=" + type(exc).__name__ + ": " + str(exc))
'@

    # QT_QPA_PLATFORM is also set on the child so Qt cannot try to open a window.
    $saved = $env:QT_QPA_PLATFORM
    $env:QT_QPA_PLATFORM = 'offscreen'
    try {
        $r = Invoke-RsProcess -FilePath $VenvPython -Arguments @('-c', $code, $ProjectRoot) `
                              -WorkingDirectory $ProjectRoot -TimeoutSeconds $TimeoutSeconds -Quiet
    } finally {
        if ($null -ne $saved) { $env:QT_QPA_PLATFORM = $saved } else { Remove-Item Env:\QT_QPA_PLATFORM -ErrorAction SilentlyContinue }
    }

    $out = ($r.StdOut + "`n" + $r.StdErr)
    if ($r.TimedOut) {
        $result.Detail = "the UI import test timed out after ${TimeoutSeconds}s"
        return $result
    }
    if ($r.ExitCode -eq 0 -and $out -match 'UI_LAUNCH_OK') {
        $result.Ok = $true
        $result.Detail = 'the Command Center import chain loads cleanly'
        $fixes = [regex]::Match($out, 'UI_FIXES=(.+)')
        if ($fixes.Success) {
            $result.Fixes = $fixes.Groups[1].Value.Trim()
        } else {
            $failed = [regex]::Match($out, 'UI_FIXES_FAILED=(.+)')
            if ($failed.Success) { $result.Fixes = 'FAILED: ' + $failed.Groups[1].Value.Trim() }
        }
        return $result
    }

    $stageMatch = [regex]::Match($out, 'UI_LAUNCH_FAILED_AT=(\S+)')
    $failedAt = if ($stageMatch.Success) { $stageMatch.Groups[1].Value } else { 'unknown' }
    # The last few traceback lines carry the actual exception.
    $tail = @($out -split "`r?`n" | Where-Object { $_.Trim() } | Select-Object -Last 12)
    $result.Detail = "the Command Center could not load (failed at: $failedAt)"
    $result.Traceback = ($tail -join [Environment]::NewLine)
    return $result
}

function Test-RsVenvImports {
    <# Verifies a venv can import the modules the app actually needs. #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$VenvPython,
        [Parameter(Mandatory)][string[]]$Modules
    )
    if (-not (Test-Path -LiteralPath $VenvPython)) { return $false }
    # Import for real rather than probing with importlib.util.find_spec: a
    # present-but-broken package (missing native DLLs, half-installed wheel)
    # must count as missing. Note that "import importlib" alone does not expose
    # importlib.util, which made an earlier find_spec version always fail.
    $code = 'import sys
missing = []
for name in sys.argv[1:]:
    try:
        __import__(name)
    except Exception as exc:
        missing.append("%s(%s)" % (name, type(exc).__name__))
print("MISSING=" + ",".join(missing))
sys.exit(1 if missing else 0)'
    $r = Invoke-RsProcess -FilePath $VenvPython -Arguments (@('-c', $code) + $Modules) -TimeoutSeconds 180 -Quiet
    if ($r.ExitCode -ne 0) {
        Write-RsLog "    venv import check failed: $($r.StdOut.Trim())" -Level WARN
        return $false
    }
    return $true
}

# ==========================================================================
# WSL2
# ==========================================================================

function Get-RsWslState {
    <#
        Reports whether the two Windows features Docker's WSL2 backend needs are
        enabled, and whether the WSL kernel is installed.
    #>
    [CmdletBinding()] param()

    $state = [ordered]@{
        SubsystemEnabled       = $false
        VirtualMachinePlatform = $false
        KernelInstalled        = $false
        DefaultVersion         = $null
    }

    foreach ($feature in @('Microsoft-Windows-Subsystem-Linux', 'VirtualMachinePlatform')) {
        $enabled = $false
        try {
            # Needs elevation. Setup is elevated, so this is the normal path.
            $f = Get-WindowsOptionalFeature -Online -FeatureName $feature -ErrorAction Stop
            $enabled = ($f.State -eq 'Enabled')
        } catch {
            # The health check is run from the Start Menu, unelevated. dism is
            # not a fallback there - /online /get-featureinfo returns error 740
            # (elevated permissions required) and its output contains no
            # "State : Enabled", so parsing it reports every feature as disabled
            # on a machine where both are on.
            #
            # Win32_OptionalFeature answers the same question over WMI and does
            # not require elevation. InstallState 1 = enabled.
            try {
                $q = "Name='$feature'"
                $wmi = Get-CimInstance -ClassName Win32_OptionalFeature -Filter $q -ErrorAction Stop |
                       Select-Object -First 1
                if ($wmi) { $enabled = ($wmi.InstallState -eq 1) }
            } catch {
                $r = Invoke-RsProcess -FilePath (Get-RsSystem32 'dism.exe') `
                                      -Arguments @('/online', '/get-featureinfo', "/featurename:$feature") `
                                      -TimeoutSeconds 180 -Quiet
                $enabled = ($r.StdOut -match 'State\s*:\s*Enabled')
            }
        }
        if ($feature -eq 'Microsoft-Windows-Subsystem-Linux') { $state.SubsystemEnabled = $enabled }
        else { $state.VirtualMachinePlatform = $enabled }
    }

    $wsl = Get-RsCommand -Name 'wsl'
    if ($wsl) {
        $r = Invoke-RsProcess -FilePath $wsl.Source -Arguments @('--status') -TimeoutSeconds 120 -Quiet
        # wsl.exe emits UTF-16; the text may contain NULs when captured.
        $text = ($r.StdOut + $r.StdErr) -replace "`0", ''
        if ($r.ExitCode -eq 0) {
            $state.KernelInstalled = $true
            $m = [regex]::Match($text, 'Default Version:\s*(\d)')
            if ($m.Success) { $state.DefaultVersion = [int]$m.Groups[1].Value }
            # wsl --status cannot succeed with the subsystem feature off, so
            # this settles it even if every feature probe above was blocked.
            $state.SubsystemEnabled = $true
            if ($state.DefaultVersion -eq 2) { $state.VirtualMachinePlatform = $true }
        }
    }
    return [pscustomobject]$state
}

function Enable-RsWsl2 {
    <#
        Enables the WSL2 prerequisites. Returns an object whose RebootRequired
        flag tells the caller whether Docker can be expected to start now or
        only after a restart.
    #>
    [CmdletBinding()]
    param([string]$HardwareProfilePath)

    $result = [pscustomobject]@{
        Changed = $false; RebootRequired = $false; Ok = $false
        Blocked = $false; Reason = ''
    }

    # Hardware gate first. Turning on the WSL2 features when the firmware has
    # virtualization disabled produces a machine that reboots, still cannot
    # start Docker, and has no way to say why - the exact failure reported
    # against earlier builds.
    $hw = Get-RsHardwareProfile -ProfilePath $HardwareProfilePath
    if ($hw -and -not $hw.virtualization.wsl2Capable) {
        $result.Blocked = $true
        $result.Reason = [string]$hw.virtualization.wsl2Blocker
        Write-RsLog 'WSL2 is not available on this machine, so it will not be enabled:' -Level WARN
        Write-RsLog "    $($result.Reason)" -Level WARN
        if (-not $hw.virtualization.available) {
            Write-RsLog '    To enable it: restart, open the firmware setup screen (usually F2, F10, Del' -Level INFO
            Write-RsLog '    or Esc during boot), turn on Intel VT-x / AMD-V (often listed as' -Level INFO
            Write-RsLog '    "Virtualization Technology", "SVM Mode" or "Intel VMX"), save and reboot,' -Level INFO
            Write-RsLog '    then re-run "Repair RedSight setup" from the Start Menu.' -Level INFO
        }
        Write-RsLog '    RedSight will run in native mode instead - no containers required.' -Level INFO
        return $result
    }

    if (-not (Test-RsAdmin)) {
        Write-RsLog 'enabling WSL2 requires elevation - skipping' -Level WARN
        return $result
    }

    $state = Get-RsWslState
    if ($state.SubsystemEnabled -and $state.VirtualMachinePlatform -and $state.KernelInstalled) {
        Write-RsLog 'WSL2 already enabled and kernel present' -Level OK
        $result.Ok = $true
        return $result
    }

    $dism = Get-RsSystem32 'dism.exe'
    foreach ($feature in @('Microsoft-Windows-Subsystem-Linux', 'VirtualMachinePlatform')) {
        $already = if ($feature -eq 'Microsoft-Windows-Subsystem-Linux') { $state.SubsystemEnabled } else { $state.VirtualMachinePlatform }
        if ($already) {
            Write-RsLog "Windows feature already enabled: $feature" -Level OK
            continue
        }
        Write-RsLog "enabling Windows feature: $feature" -Level STEP
        $r = Invoke-RsProcess -FilePath $dism `
                              -Arguments @('/online', '/enable-feature', "/featurename:$feature", '/all', '/norestart') `
                              -TimeoutSeconds 1200
        $result.Changed = $true
        # 3010 / 1641 both mean "done, restart needed".
        if ($r.ExitCode -in @(3010, 1641)) {
            Write-RsLog "    $feature enabled; a restart is required" -Level WARN
            $result.RebootRequired = $true
        } elseif ($r.ExitCode -ne 0) {
            Write-RsLog "    could not enable $feature (dism exit $($r.ExitCode))" -Level FAIL
            return $result
        }
    }

    # Install/refresh the WSL2 kernel and make v2 the default.
    $wsl = Get-RsCommand -Name 'wsl'
    if ($wsl -and -not $result.RebootRequired) {
        Write-RsLog 'updating the WSL kernel' -Level STEP
        # --no-distribution keeps this from installing Ubuntu; RedSight only
        # needs the WSL2 platform for Docker's backend.
        $r = Invoke-RsProcess -FilePath $wsl.Source -Arguments @('--install', '--no-distribution') -TimeoutSeconds 1800
        if ($r.ExitCode -ne 0) {
            $r2 = Invoke-RsProcess -FilePath $wsl.Source -Arguments @('--update') -TimeoutSeconds 1800
            if ($r2.ExitCode -ne 0) {
                Write-RsLog "    wsl --update returned $($r2.ExitCode) (continuing; Docker Desktop can install the kernel itself)" -Level WARN
            }
        }
        Invoke-RsProcess -FilePath $wsl.Source -Arguments @('--set-default-version', '2') -TimeoutSeconds 180 | Out-Null
    }

    $after = Get-RsWslState
    $result.Ok = ($after.SubsystemEnabled -and $after.VirtualMachinePlatform)
    return $result
}

# ==========================================================================
# Docker
# ==========================================================================

function Find-RsDockerCli {
    <# Resolves docker.exe from PATH or the standard Docker Desktop location. #>
    [CmdletBinding()] param()
    $cmd = Get-RsCommand -Name 'docker'
    if ($cmd) { return $cmd.Source }
    if ($env:ProgramFiles) {
        foreach ($rel in @('Docker\Docker\resources\bin\docker.exe', 'Docker\Docker\resources\docker.exe')) {
            $p = Join-Path $env:ProgramFiles $rel
            if (Test-Path -LiteralPath $p) { return $p }
        }
    }
    return $null
}

function Find-RsDockerDesktop {
    [CmdletBinding()] param()
    foreach ($base in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
        if (-not $base) { continue }
        $p = Join-Path $base 'Docker\Docker\Docker Desktop.exe'
        if (Test-Path -LiteralPath $p) { return $p }
    }
    return $null
}

function Test-RsDockerEngine {
    <# True when the daemon answers - the only reliable "Docker works" test. #>
    [CmdletBinding()] param([string]$DockerCli)
    if (-not $DockerCli) { $DockerCli = Find-RsDockerCli }
    if (-not $DockerCli) { return $false }
    $r = Invoke-RsProcess -FilePath $DockerCli -Arguments @('info', '--format', '{{.ServerVersion}}') -TimeoutSeconds 120 -Quiet
    return [bool]($r.ExitCode -eq 0 -and $r.StdOut.Trim())
}

function Install-RsDockerDesktop {
    <#
        Downloads and silently installs Docker Desktop.

        Docker Desktop is not redistributable, so it is fetched from Docker's
        official URL at setup time rather than bundled into the installer. An
        administrator can pre-seed the download cache (or drop the installer
        next to setup.exe as DockerDesktopInstaller.exe) for offline installs.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$ProjectRoot,
        [string]$HardwareProfilePath,
        [switch]$OfflineOnly
    )

    if (-not (Test-RsAdmin)) {
        throw 'installing Docker Desktop requires administrator privileges'
    }

    # Docker Desktop's only supported backend here is WSL2. Installing it on a
    # machine that cannot run WSL2 downloads 1.6 GB to produce an engine that
    # will never start, so refuse with a reason the user can act on.
    $hw = Get-RsHardwareProfile -ProfilePath $HardwareProfilePath
    if ($hw -and -not $hw.virtualization.wsl2Capable) {
        throw ("Docker Desktop needs WSL2, which this machine cannot run. " +
               [string]$hw.virtualization.wsl2Blocker +
               " RedSight will run in native mode instead.")
    }

    $cache = Get-RsDownloadCache -ProjectRoot $ProjectRoot
    $installer = Join-Path $cache $script:RsDocker.InstallerName

    # Accept an operator-supplied copy from the bundle directory first.
    $preseeded = Join-Path (Get-RsBundleRoot -ProjectRoot $ProjectRoot) $script:RsDocker.InstallerName
    if ((Test-Path -LiteralPath $preseeded) -and -not (Test-Path -LiteralPath $installer)) {
        Write-RsLog "using pre-seeded Docker Desktop installer from $preseeded" -Level OK
        Copy-Item -LiteralPath $preseeded -Destination $installer -Force
    }

    if (-not (Test-Path -LiteralPath $installer)) {
        if ($OfflineOnly) {
            throw 'Docker Desktop is missing and -OfflineOnly forbids downloading it.'
        }
        Save-RsDownload -Uri $script:RsDocker.InstallerUri -Destination $installer `
                        -Description 'Docker Desktop installer (~1.6 GB)' -TimeoutSeconds 5400 | Out-Null
    }

    Write-RsLog 'installing Docker Desktop silently (this takes several minutes)' -Level STEP
    # "install" subcommand + --quiet is Docker's documented unattended mode.
    $dockerArgs = @('install', '--quiet', '--accept-license', '--backend=wsl-2')
    $r = Invoke-RsProcess -FilePath $installer -Arguments $dockerArgs -TimeoutSeconds 5400

    if ($r.ExitCode -notin @(0, 3010)) {
        throw "Docker Desktop installer failed with exit code $($r.ExitCode)"
    }
    Write-RsLog 'Docker Desktop installed' -Level OK
    Update-RsProcessPath

    # Membership in docker-users is what lets a non-admin user run docker.
    try {
        $user = "$env:USERDOMAIN\$env:USERNAME"
        $r2 = Invoke-RsProcess -FilePath (Get-RsSystem32 'net.exe') `
                               -Arguments @('localgroup', 'docker-users', $user, '/add') -TimeoutSeconds 120 -Quiet
        if ($r2.ExitCode -eq 0) { Write-RsLog "added $user to the docker-users group" -Level OK }
    } catch { }

    return $true
}

function Start-RsDockerEngine {
    <#
        Starts Docker Desktop if needed and waits for the daemon to answer.
        Returns $true only when `docker info` succeeds.
    #>
    [CmdletBinding()]
    param([int]$TimeoutSeconds = 0)

    if ($TimeoutSeconds -le 0) { $TimeoutSeconds = $script:RsDocker.EngineWaitSeconds }

    $cli = Find-RsDockerCli
    if (-not $cli) {
        Write-RsLog 'docker CLI not found - cannot start the engine' -Level WARN
        return $false
    }
    if (Test-RsDockerEngine -DockerCli $cli) {
        Write-RsLog 'Docker engine is already running' -Level OK
        return $true
    }

    $desktop = Find-RsDockerDesktop
    if ($desktop) {
        Write-RsLog 'starting Docker Desktop' -Level STEP
        try { Start-Process -FilePath $desktop -ArgumentList '-Autostart' -ErrorAction Stop | Out-Null }
        catch { try { Start-Process -FilePath $desktop | Out-Null } catch { } }
    } else {
        Write-RsLog 'Docker Desktop executable not found' -Level WARN
    }

    Write-RsLog "waiting up to ${TimeoutSeconds}s for the Docker engine" -Level STEP
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-RsDockerEngine -DockerCli $cli) {
            Write-RsLog 'Docker engine is up' -Level OK
            return $true
        }
        Start-Sleep -Seconds 5
    }
    Write-RsLog 'Docker engine did not come up in time' -Level WARN
    return $false
}

function Build-RsDockerImages {
    <# Builds the redsight + qdrant images with docker compose. #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$ProjectRoot,
        [int]$TimeoutSeconds = 5400
    )

    $cli = Find-RsDockerCli
    if (-not $cli) { throw 'docker CLI not available' }
    if (-not (Test-RsDockerEngine -DockerCli $cli)) { throw 'Docker engine is not running' }

    $compose = Join-Path $ProjectRoot 'docker-compose.yml'
    if (-not (Test-Path -LiteralPath $compose)) { throw "docker-compose.yml not found in $ProjectRoot" }

    Write-RsLog 'building Docker images (docker compose build)' -Level STEP
    Write-RsLog '    this is the long step - a first build downloads base images and installs' -Level INFO
    Write-RsLog '    the Python stack inside the container, which can take 15-30 minutes' -Level INFO
    # --progress plain keeps the captured output readable instead of a stream of
    # terminal control sequences.
    $r = Invoke-RsProcess -FilePath $cli -Arguments @('compose', 'build', '--progress', 'plain') `
                          -WorkingDirectory $ProjectRoot -TimeoutSeconds $TimeoutSeconds `
                          -HeartbeatSeconds 60
    if ($r.TimedOut) { throw "docker compose build timed out after ${TimeoutSeconds}s" }
    if ($r.ExitCode -ne 0) { throw "docker compose build failed with exit code $($r.ExitCode)" }
    Write-RsLog 'Docker images built' -Level OK
    return $true
}

# ==========================================================================
# Node.js (optional - WhatsApp remote bridge only)
# ==========================================================================

function Install-RsNode {
    <# Installs the current Node.js LTS from nodejs.org via msiexec. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$ProjectRoot, [switch]$OfflineOnly)

    $node = Get-RsCommand -Name 'node'
    if ($node) {
        $r = Invoke-RsProcess -FilePath $node.Source -Arguments @('--version') -TimeoutSeconds 60 -Quiet
        $v = ConvertTo-RsVersion -Text $r.StdOut
        if (Test-RsVersionInRange -Version $v -Minimum $script:RsNode.MinVersion -ExclusiveMaximum $null) {
            Write-RsLog "Node.js $v already present" -Level OK
            return $node.Source
        }
        Write-RsLog "Node.js $v is older than $($script:RsNode.MinVersion) - upgrading" -Level WARN
    }

    if (-not (Test-RsAdmin)) { throw 'installing Node.js requires administrator privileges' }
    if ($OfflineOnly) { throw 'Node.js is missing and -OfflineOnly forbids downloading it.' }

    # Resolve the newest LTS from the official dist index, with a pinned fallback.
    $uri = $script:RsNode.FallbackUri
    $version = $script:RsNode.FallbackVersion
    try {
        $ProgressPreference = 'SilentlyContinue'
        $index = Invoke-RestMethod -Uri $script:RsNode.IndexUri -TimeoutSec 60 -UseBasicParsing
        $lts = $index | Where-Object { $_.lts } | Select-Object -First 1
        if ($lts) {
            $version = $lts.version.TrimStart('v')
            $uri = "https://nodejs.org/dist/v$version/node-v$version-x64.msi"
            Write-RsLog "latest Node.js LTS is $version" -Level DEBUG
        }
    } catch {
        Write-RsLog "could not read the Node.js dist index ($($_.Exception.Message)); using pinned $version" -Level WARN
    }

    $cache = Get-RsDownloadCache -ProjectRoot $ProjectRoot
    $msi = Join-Path $cache "node-v$version-x64.msi"
    Save-RsDownload -Uri $uri -Destination $msi -Description "Node.js $version MSI" | Out-Null

    Write-RsLog "installing Node.js $version" -Level STEP
    $r = Invoke-RsProcess -FilePath (Get-RsSystem32 'msiexec.exe') `
                          -Arguments @('/i', $msi, '/qn', '/norestart', 'ADDLOCAL=ALL') -TimeoutSeconds 1800
    if ($r.ExitCode -notin @(0, 3010)) { throw "Node.js MSI failed with exit code $($r.ExitCode)" }

    Update-RsProcessPath
    $node = Get-RsCommand -Name 'node'
    if (-not $node) { throw 'Node.js was installed but node.exe is not on PATH' }
    Write-RsLog "Node.js installed: $($node.Source)" -Level OK
    return $node.Source
}

# ==========================================================================
# Application wiring
# ==========================================================================

function New-RsEnvFile {
    <# Creates .env from .env.example when absent. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$ProjectRoot)

    $envFile = Join-Path $ProjectRoot '.env'
    $example = Join-Path $ProjectRoot '.env.example'
    if (Test-Path -LiteralPath $envFile) {
        Write-RsLog '.env already exists - leaving it untouched' -Level OK
        return $false
    }
    if (-not (Test-Path -LiteralPath $example)) {
        Write-RsLog '.env.example not found - skipping .env creation' -Level WARN
        return $false
    }
    Copy-Item -LiteralPath $example -Destination $envFile -Force
    Write-RsLog 'created .env from .env.example' -Level OK
    return $true
}

# .env keys whose values are directories the user chose, not build-machine
# leftovers. The workspace default is <UserProfile>\RedSight, so a pattern that
# rewrites "any drive path ending in RedSight" rewrites the user's own working
# directory to the install root - which is how an install ends up pointing half
# at one tree and half at another.
$script:RsUserPathKeys = @(
    'REDSIGHT_WORKSPACE', 'REDSIGHT_WORKING_DIR', 'REDSIGHT_OUTPUT_DIR',
    'REDSIGHT_MCP_DIR', 'RED_SIGHT_DATA_ROOT'
)

function Get-RsPayloadSourceRoot {
    <#
        The directory this payload was built from, as recorded at build time.

        Knowing it turns the path rewrite from a guess into an exact
        substitution. Returns an empty string for a payload built before the
        manifest existed.
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$ProjectRoot)

    $manifest = Join-Path $ProjectRoot 'redsight-payload.json'
    if (-not (Test-Path -LiteralPath $manifest)) { return '' }
    try {
        $parsed = Get-Content -LiteralPath $manifest -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
        if ($parsed.PSObject.Properties['sourceRoot']) { return "$($parsed.sourceRoot)".TrimEnd('\') }
    } catch {
        Write-RsLog "could not read $manifest ($($_.Exception.Message))" -Level WARN
    }
    return ''
}

function Repair-RsHardcodedPaths {
    <#
        RedSight ships source files containing the build machine's absolute
        install path. Every such reference has to become the real install
        directory or the app launches against a non-existent tree.

        Handles three encodings of the same path - for a build root of
        <drive>:\<dir>\RedSight:
          plain         one backslash between segments
          JSON/escaped  two backslashes, as written inside a JSON string
          forward slash slashes instead, as written in a URI or a POSIX path

        No example is spelled out here on purpose: a literal build path in this
        file would itself be matched and rewritten, and the health check would
        then report a stale reference on every fresh install.

        The root that gets rewritten comes from redsight-payload.json, written
        at build time. When that is missing - a payload from an older build -
        the previous heuristic applies: any drive path ending in \RedSight. That
        heuristic is why this function needs the protections below, because the
        user's own working directory defaults to <UserProfile>\RedSight and
        matches it.

        Never rewritten:
          * the target path itself
          * the values of the .env keys naming user-chosen directories
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$ProjectRoot,
        [string[]]$Extensions = @('*.py', '*.ps1', '*.psm1', '*.json', '*.cmd', '*.bat', '*.txt', '*.yml', '*.yaml', '*.env', '*.ini', '*.cfg'),
        [string]$SourceRoot,
        [switch]$WhatIf
    )

    $target = (Resolve-Path -LiteralPath $ProjectRoot).Path.TrimEnd('\')
    $targetEscaped = $target -replace '\\', '\\'
    $targetForward = $target -replace '\\', '/'

    if (-not $PSBoundParameters.ContainsKey('SourceRoot')) {
        $SourceRoot = Get-RsPayloadSourceRoot -ProjectRoot $target
    }
    $SourceRoot = "$SourceRoot".TrimEnd('\')

    # Directories that must never be rewritten: virtualenvs and package caches
    # contain thousands of files and their own absolute paths.
    $excluded = @('.venv', '.venv-ui', '.venv-actions', '.venv-release-test', 'runtime',
                  'node_modules', '__pycache__', '.git', '.pytest_cache', '.mypy_cache',
                  '.ruff_cache', 'backups', 'release')

    # The manifest records the build root; rewriting it would erase the only
    # thing that makes this an exact substitution rather than a guess. The setup
    # scripts are overlaid fresh at build time and hold no install paths - only
    # the code that computes them, and prose about them.
    $excludedFiles = @('redsight-payload.json', 'RedSight-Common.ps1', 'RedSight-Hardware.ps1',
                       'RedSight-LmStudio.ps1', 'RedSight-Provision.ps1', 'RedSight-Preflight.ps1',
                       'Bootstrap-RedSight.ps1', 'Verify-RedSightSetup.ps1', 'Start-RedSight.ps1',
                       'Uninstall-RedSightDocker.ps1', 'Repair-RedSight.ps1')

    if ($SourceRoot -and ($SourceRoot -ne $target)) {
        # The exact recorded root, in each encoding. Nothing else is touched.
        $literal = [regex]::Escape($SourceRoot)
        $patterns = @(
            @{ Regex = [regex]::Escape(($SourceRoot -replace '\\', '\\')); Replacement = $targetEscaped; Label = 'escaped' }
            @{ Regex = $literal;                                          Replacement = $target;        Label = 'plain' }
            @{ Regex = [regex]::Escape(($SourceRoot -replace '\\', '/')); Replacement = $targetForward; Label = 'forward' }
        )
        Write-RsLog "rewriting the recorded build root $SourceRoot -> $target" -Level DEBUG
    } elseif ($SourceRoot -eq $target) {
        Write-RsLog 'the payload was built from this directory; no path rewrite is needed' -Level OK
        return [pscustomobject]@{ Rewritten = 0; Failed = 0; Files = @(); SourceRoot = $SourceRoot }
    } else {
        # A drive-letter path ending in \RedSight, in each of the three encodings.
        $patterns = @(
            @{ Regex = '[A-Za-z]:\\\\(?:[^\\/:*?"<>|\r\n]+\\\\)*?RedSight'; Replacement = $targetEscaped; Label = 'escaped' }
            @{ Regex = '[A-Za-z]:\\(?:[^\\/:*?"<>|\r\n]+\\)*?RedSight';     Replacement = $target;        Label = 'plain' }
            @{ Regex = '[A-Za-z]:/(?:[^\\/:*?"<>|\r\n]+/)*?RedSight';       Replacement = $targetForward; Label = 'forward' }
        )
        Write-RsLog 'no build root recorded in this payload; matching any path ending in \RedSight' -Level DEBUG
    }

    # Lines assigning a user-chosen directory keep their value verbatim.
    $protectedLine = '^\s*(' + (($script:RsUserPathKeys | ForEach-Object { [regex]::Escape($_) }) -join '|') + ')\s*='

    $rewritten = 0
    $failed = 0
    $filesTouched = New-Object System.Collections.Generic.List[string]

    # -Force so dotfiles are included: .env is the one file where a wrong
    # rewrite does the most damage, and it is hidden on some systems.
    Get-ChildItem -LiteralPath $target -Recurse -Include $Extensions -File -Force -ErrorAction SilentlyContinue |
        Where-Object {
            $rel = $_.FullName.Substring($target.Length).TrimStart('\', '/')
            $first = ($rel -split '[\\/]')[0]
            (-not ($excluded -contains $first)) -and (-not ($excludedFiles -contains $_.Name))
        } |
        ForEach-Object {
            $file = $_.FullName
            try { $content = Get-Content -LiteralPath $file -Raw -ErrorAction Stop } catch { return }
            if ($null -eq $content -or $content.Length -eq 0) { return }

            # Rewrite line by line so a protected assignment can be skipped
            # without giving up the rest of the file.
            $newline = if ($content -match "`r`n") { "`r`n" } else { "`n" }
            $lines = $content -split "`r?`n"
            $changed = $false
            for ($i = 0; $i -lt $lines.Count; $i++) {
                $line = $lines[$i]
                if ($line -match $protectedLine) { continue }
                $updatedLine = $line
                foreach ($p in $patterns) {
                    if ($updatedLine -notmatch $p.Regex) { continue }
                    # A literal replacement: the target path may contain $ or \
                    # which would otherwise be read as regex substitutions.
                    $updatedLine = [regex]::Replace($updatedLine, $p.Regex, { param($m) $p.Replacement })
                }
                if ($updatedLine -ne $line) { $lines[$i] = $updatedLine; $changed = $true }
            }

            if (-not $changed) { return }

            if ($WhatIf) {
                $filesTouched.Add($file)
                $rewritten++
                return
            }
            try {
                $updated = ($lines -join $newline)
                # BOM-free, and written whole rather than through Set-Content.
                # Windows PowerShell 5.1's -Encoding UTF8 means UTF-8 WITH a byte
                # order mark, and $Extensions includes *.bat and *.cmd: cmd.exe
                # reads the BOM as part of the first command and the launcher
                # dies with an unrecognised-command error.
                [System.IO.File]::WriteAllText($file, $updated,
                    (New-Object System.Text.UTF8Encoding($false)))
                $filesTouched.Add($file)
                $rewritten++
            } catch {
                $failed++
                Write-RsLog "    could not rewrite $file : $($_.Exception.Message)" -Level WARN
            }
        }

    Write-RsLog "rewrote install-path references in $rewritten file(s), $failed failure(s)" -Level $(if ($failed) { 'WARN' } else { 'OK' })
    return [pscustomobject]@{ Rewritten = $rewritten; Failed = $failed; Files = $filesTouched; SourceRoot = $SourceRoot }
}

function Install-RsShortcuts {
    <#
        Creates the Desktop shortcut, pointing at the launcher that matches the
        runtime mode: the native launcher when RedSight runs without Docker, the
        app's own desktop launcher otherwise.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$ProjectRoot,
        [ValidateSet('container', 'native')][string]$RuntimeMode = 'container',
        [string]$ShortcutPath
    )

    $launcher = Get-RsLauncherPath -ProjectRoot $ProjectRoot -Mode $RuntimeMode
    if (-not $launcher) {
        # Fall back to the payload's own installer, which has its own chain of
        # candidate launchers.
        $script = Join-Path $ProjectRoot 'scripts\windows\Install-RedSightDesktopShortcut.ps1'
        if (-not (Test-Path -LiteralPath $script)) {
            Write-RsLog 'no launcher and no shortcut installer found - skipping' -Level WARN
            return $false
        }
        $r = Invoke-RsProcess -FilePath (Get-RsPowerShellExe) `
                              -Arguments @('-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $script) `
                              -TimeoutSeconds 300
        if ($r.ExitCode -ne 0) {
            Write-RsLog "shortcut creation returned $($r.ExitCode)" -Level WARN
            return $false
        }
        Write-RsLog 'desktop shortcut created by the application installer' -Level OK
        return $true
    }

    if (-not $ShortcutPath) {
        $desktop = [Environment]::GetFolderPath('Desktop')
        if (-not $desktop) { $desktop = $ProjectRoot }
        $ShortcutPath = Join-Path $desktop 'RedSight.lnk'
    }

    try {
        $shell = New-Object -ComObject WScript.Shell
        $sc = $shell.CreateShortcut($ShortcutPath)
        $sc.TargetPath = Get-RsPowerShellExe
        # -WindowStyle Hidden keeps a console window from flashing up on launch.
        $sc.Arguments = '-NoLogo -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $launcher + '"'
        $sc.WorkingDirectory = $ProjectRoot
        $sc.Description = "RedSight Local Intelligence Command Center ($RuntimeMode mode)"
        $icon = Join-Path $ProjectRoot 'assets\redsight.ico'
        if (Test-Path -LiteralPath $icon) { $sc.IconLocation = $icon }
        $sc.Save()
        Write-RsLog "desktop shortcut created: $ShortcutPath -> $(Split-Path -Leaf $launcher)" -Level OK
        return $true
    } catch {
        Write-RsLog "could not create the desktop shortcut: $($_.Exception.Message)" -Level WARN
        return $false
    }
}

# ==========================================================================
# Read-only dependency report
# ==========================================================================

function Get-RsPreflightReport {
    <#
        Detects everything without changing anything. This is what the installer
        wizard shows and what -Report prints, so the user can see exactly what
        will be downloaded before agreeing to it.
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$ProjectRoot)

    $runtimeExe = Join-Path (Get-RsRuntimePythonDir -ProjectRoot $ProjectRoot) 'python.exe'
    $bundledPkg = Join-Path (Get-RsBundleRoot -ProjectRoot $ProjectRoot) $script:RsPython.BundleName

    $pythonPath = $null
    if (Test-Path -LiteralPath $runtimeExe) {
        if (Test-RsPythonUsable -PythonExe $runtimeExe) { $pythonPath = $runtimeExe }
    }
    if (-not $pythonPath) { $pythonPath = Find-RsSystemPython }

    $dockerCli = Find-RsDockerCli
    $wsl = Get-RsWslState
    $node = Get-RsCommand -Name 'node'

    $venvs = [ordered]@{}
    foreach ($name in @('.venv-ui', '.venv-actions')) {
        $p = Join-Path $ProjectRoot "$name\Scripts\python.exe"
        $venvs[$name] = (Test-Path -LiteralPath $p)
    }

    return [pscustomobject]@{
        ProjectRoot        = $ProjectRoot
        Elevated           = Test-RsAdmin
        Online             = Test-RsOnline
        PythonPath         = $pythonPath
        PythonVersion      = if ($pythonPath) { $pv = Get-RsPythonVersion -PythonExe $pythonPath; if ($pv) { $pv.ToString() } else { $null } } else { $null }
        PythonBundled      = (Test-Path -LiteralPath $bundledPkg)
        PythonNeedsInstall = (-not $pythonPath)
        Wheelhouse         = (Get-RsWheelhouse -ProjectRoot $ProjectRoot)
        Venvs              = $venvs
        DockerCli          = $dockerCli
        DockerInstalled    = [bool](Find-RsDockerDesktop)
        DockerRunning      = if ($dockerCli) { Test-RsDockerEngine -DockerCli $dockerCli } else { $false }
        Wsl                = $wsl
        NodePath           = if ($node) { $node.Source } else { $null }
        EnvFile            = (Test-Path -LiteralPath (Join-Path $ProjectRoot '.env'))
    }
}

# --------------------------------------------------------------------------
# Direct invocation: print the report
# --------------------------------------------------------------------------

if ($MyInvocation.InvocationName -ne '.' -and $Report) {
    if (-not $ProjectRoot) {
        $ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $script:RsScriptDir '..\..'))
    }
    Initialize-RsLog -Name 'preflight' | Out-Null
    $r = Get-RsPreflightReport -ProjectRoot $ProjectRoot
    $r | Format-List
    $r | ConvertTo-Json -Depth 6
}
