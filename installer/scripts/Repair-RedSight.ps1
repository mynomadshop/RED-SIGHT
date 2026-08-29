<#
    Repair-RedSight.ps1

    Diagnoses and repairs a RedSight installation that will not launch.

    Reports first, changes nothing, and prints exactly what it would do:

        powershell -ExecutionPolicy Bypass -File Repair-RedSight.ps1

    Then applies the repairs it found:

        powershell -ExecutionPolicy Bypass -File Repair-RedSight.ps1 -Fix

    What it looks at, in the order that matters when the UI will not start:

      1. every RedSight installation on this device, and which one the
         shortcuts actually point at - two installs on one machine is the
         usual cause of "it worked, then it did not"
      2. files inside this installation that reference a different root
      3. the real Command Center traceback, captured by running it headlessly
         rather than reporting that it "failed to launch"
      4. the environment the UI and the backend will actually see - the LM
         Studio endpoint above all, which is read from the process
         environment and not from .env
      5. the services the UI needs - the backend on 8000 and the action/memory
         gateway on 8765 - including which installation the process holding
         each port was started from, because a leftover backend from an older
         tree makes this one exit with [Errno 10048] while the UI happily talks
         to the old one

    Every repair is idempotent. Nothing is deleted without -Fix, and the
    working directory's contents are never touched.
#>

[CmdletBinding()]
param(
    [string]$ProjectRoot,
    [switch]$Fix,
    # Recreate .venv-ui from scratch. Slow (it reinstalls every wheel) and only
    # needed when the environment itself is broken rather than misconfigured.
    [switch]$RecreateVenv,
    # Stop a RedSight process from another installation that is holding one of
    # the ports this installation needs. Separate from -Fix because it ends a
    # running program.
    [switch]$StopOtherInstances,
    [switch]$Json
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }

# Capture what the caller asked for BEFORE dot-sourcing anything. A dot-sourced
# script's param() block runs in this scope, so RedSight-Preflight.ps1's own
# [string]$ProjectRoot resets ours to '' - and the tool then silently inspects
# the wrong directory.
$requestedRoot = if ($PSBoundParameters.ContainsKey('ProjectRoot')) { $ProjectRoot } else { '' }

. (Join-Path $scriptDir 'RedSight-Preflight.ps1')

$ProjectRoot = $requestedRoot
if (-not $ProjectRoot) {
    $ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $scriptDir '..\..'))
}
function Write-Refusal {
    <# A readable message, not a PowerShell error dump. #>
    # Not Mandatory: a mandatory array parameter rejects the blank lines that
    # make the message readable.
    param([string[]]$Lines = @())
    Write-Host ''
    foreach ($line in $Lines) { Write-Host $line -ForegroundColor Yellow }
    Write-Host ''
}

if (-not (Test-Path -LiteralPath $ProjectRoot)) {
    Write-Refusal @(
        "That directory does not exist: $ProjectRoot",
        '',
        'Pass the installed copy with -ProjectRoot, for example:',
        '    -ProjectRoot "D:\RedSight"'
    )
    exit 2
}
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path.TrimEnd('\')

# A source checkout is not an installation. Rewriting install paths inside one
# edits tracked files and points shortcuts at a tree that was never installed.
# A .git directory settles it; an installer/ tree with no payload manifest is a
# checkout of an older layout. An installed payload carries the manifest and
# never carries .git, which the build prunes.
$checkoutMarker = ''
if (Test-Path -LiteralPath (Join-Path $ProjectRoot '.git')) {
    $checkoutMarker = '.git'
} elseif ((Test-Path -LiteralPath (Join-Path $ProjectRoot 'installer\build\Build-Installer.ps1')) -and
          -not (Test-Path -LiteralPath (Join-Path $ProjectRoot 'redsight-payload.json'))) {
    $checkoutMarker = 'installer\build\Build-Installer.ps1 and no payload manifest'
}

if ($checkoutMarker) {
    $recorded = ''
    $key = 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{B6C1E9C2-6E2E-4C7B-9B2C-REDSIGHT01}_is1'
    foreach ($hive in @('HKLM:\', 'HKCU:\')) {
        try {
            if (Test-Path -LiteralPath ($hive + $key)) {
                $value = (Get-ItemProperty -LiteralPath ($hive + $key) -ErrorAction Stop).InstallLocation
                if ($value) { $recorded = $value.TrimEnd('\'); break }
            }
        } catch { }
    }

    $lines = @(
        "$ProjectRoot is a RedSight source checkout, not an installation.",
        "  (it contains $checkoutMarker)",
        '',
        'Nothing was changed. Rewriting install paths in a checkout would edit',
        'its tracked files and point your shortcuts at a tree that was never',
        'installed.'
    )
    if ($recorded) {
        $lines += @('', 'Windows records your installation here. Run:', '',
                    "    powershell -ExecutionPolicy Bypass -File `"$PSCommandPath`" -ProjectRoot `"$recorded`"")
    } else {
        $lines += @('', 'Pass the installed copy with -ProjectRoot, for example:',
                    '    -ProjectRoot "D:\RedSight"')
    }
    Write-Refusal $lines
    exit 2
}

Initialize-RsLog -Name 'repair' | Out-Null

$findings = New-Object System.Collections.Generic.List[object]
$actions = New-Object System.Collections.Generic.List[string]

function Add-Finding {
    param(
        [Parameter(Mandatory)][string]$Area,
        [Parameter(Mandatory)][ValidateSet('ok', 'problem', 'info', 'fixed')][string]$Status,
        [Parameter(Mandatory)][string]$Detail,
        [string]$Fix = ''
    )
    $findings.Add([pscustomobject]@{ Area = $Area; Status = $Status; Detail = $Detail; Fix = $Fix })
    $level = switch ($Status) { 'ok' { 'OK' } 'problem' { 'FAIL' } 'fixed' { 'OK' } default { 'INFO' } }
    Write-RsLog ("[{0}] {1}" -f $Area, $Detail) -Level $level
    if ($Fix) { Write-RsLog ("        fix: {0}" -f $Fix) -Level INFO }
}

Write-RsLog ('=' * 72)
Write-RsLog "REDSIGHT REPAIR / DIAGNOSTICS"
Write-RsLog "Installation : $ProjectRoot"
Write-RsLog "Mode         : $(if ($Fix) { 'REPAIR (changes will be made)' } else { 'DIAGNOSE ONLY (nothing will change)' })"
Write-RsLog ('=' * 72)

# ==========================================================================
# 1. Every RedSight installation on this device
# ==========================================================================

Write-RsLog ''
Write-RsLog '--- installations ---' -Level STEP

$installs = New-Object System.Collections.Generic.List[string]

function Add-Install {
    param([string]$Path)
    if (-not $Path) { return }
    $trimmed = $Path.TrimEnd('\')
    if (-not (Test-RsIsAppTree -Path $trimmed)) { return }
    foreach ($existing in $installs) {
        if ($existing.ToLowerInvariant() -eq $trimmed.ToLowerInvariant()) { return }
    }
    $installs.Add($trimmed)
}

Add-Install -Path $ProjectRoot

# What Windows records for the installer's own product code.
$uninstallKey = 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{B6C1E9C2-6E2E-4C7B-9B2C-REDSIGHT01}_is1'
$recordedInstall = ''
foreach ($hive in @('HKLM:\', 'HKCU:\')) {
    $key = $hive + $uninstallKey
    try {
        if (Test-Path -LiteralPath $key) {
            $recorded = (Get-ItemProperty -LiteralPath $key -ErrorAction Stop).InstallLocation
            if ($recorded) {
                $recorded = $recorded.TrimEnd('\')
                if (-not $recordedInstall) { $recordedInstall = $recorded }
                Add-Finding -Area 'registry' -Status 'info' -Detail "Windows records the installation at $recorded"
                Add-Install -Path $recorded
            }
        }
    } catch { }
}

# The most consequential thing this tool can get wrong is repairing the wrong
# tree, so say plainly when the directory being examined is not the one Windows
# recorded. Nothing below is trustworthy if this is unintentional.
if ($recordedInstall -and ($recordedInstall.ToLowerInvariant() -ne $ProjectRoot.ToLowerInvariant())) {
    Add-Finding -Area 'target' -Status 'problem' `
        -Detail ("this run is examining $ProjectRoot, but Windows records the installation at " +
                 "$recordedInstall - they are different directories") `
        -Fix ("If you meant the installed copy, stop and re-run with:`n" +
              "          -ProjectRoot `"$recordedInstall`"")
    Write-RsLog ''
    Write-RsLog ('!' * 72) -Level FAIL
    Write-RsLog "  Examining : $ProjectRoot" -Level FAIL
    Write-RsLog "  Installed : $recordedInstall" -Level FAIL
    Write-RsLog '  These differ. Repairs would be applied to the first one.' -Level FAIL
    Write-RsLog ('!' * 72) -Level FAIL
    Write-RsLog ''
}

# The usual places, plus wherever the user profile keeps one.
$profileDir = if ($env:USERPROFILE) { $env:USERPROFILE } else { [Environment]::GetFolderPath('UserProfile') }
$candidates = @()
foreach ($base in @(${env:ProgramFiles}, ${env:ProgramFiles(x86)}, ${env:LOCALAPPDATA}, $profileDir)) {
    if ($base) { $candidates += (Join-Path $base 'RedSight') }
}
foreach ($drive in (Get-PSDrive -PSProvider FileSystem -ErrorAction SilentlyContinue)) {
    foreach ($name in @('RedSight', 'RSFinalCheck')) {
        $candidates += (Join-Path "$($drive.Name):\" $name)
    }
}
foreach ($candidate in $candidates) { Add-Install -Path $candidate }

if ($installs.Count -le 1) {
    Add-Finding -Area 'installations' -Status 'ok' -Detail "one RedSight installation: $ProjectRoot"
} else {
    # Recommend keeping the installation Windows recorded, not whichever
    # directory this run was pointed at - that advice once told the user to keep
    # a git clone and retire their real install.
    $keep = if ($recordedInstall) { $recordedInstall } else { $ProjectRoot }
    $others = @($installs | Where-Object { $_.ToLowerInvariant() -ne $keep.ToLowerInvariant() })
    $why = if ($recordedInstall) { ' (the one Windows recorded, and the one the Start Menu targets)' } else { '' }
    Add-Finding -Area 'installations' -Status 'problem' `
        -Detail ("$($installs.Count) RedSight trees exist on this device: " + ($installs -join ' | ')) `
        -Fix ("Keep $keep$why and remove or rename the others: " + ($others -join ', ') +
              '. More than one tree is the usual reason a shortcut launches the wrong one, ' +
              'and their leftover backends hold the ports this one needs.')
}

# ==========================================================================
# 2. Where the shortcuts point
# ==========================================================================

Write-RsLog ''
Write-RsLog '--- shortcuts ---' -Level STEP

$shortcutPaths = @()
$desktop = [Environment]::GetFolderPath('Desktop')
if ($desktop) { $shortcutPaths += (Join-Path $desktop 'RedSight.lnk') }
foreach ($menu in @([Environment]::GetFolderPath('CommonPrograms'), [Environment]::GetFolderPath('Programs'))) {
    if ($menu) { $shortcutPaths += (Join-Path $menu 'RedSight\RedSight.lnk') }
}

$shell = $null
try { $shell = New-Object -ComObject WScript.Shell } catch { }

$badShortcuts = New-Object System.Collections.Generic.List[string]
foreach ($lnk in $shortcutPaths) {
    if (-not (Test-Path -LiteralPath $lnk)) { continue }
    if (-not $shell) {
        Add-Finding -Area 'shortcuts' -Status 'info' -Detail "found $lnk (cannot read its target on this system)"
        continue
    }
    try {
        $sc = $shell.CreateShortcut($lnk)
        $args = "$($sc.Arguments)"
        $work = "$($sc.WorkingDirectory)".TrimEnd('\')
        $pointsHere = ($args -like "*$ProjectRoot*") -or ($work.ToLowerInvariant() -eq $ProjectRoot.ToLowerInvariant())
        $pointsAtRecorded = $recordedInstall -and (($args -like "*$recordedInstall*") -or
                                                  ($work.ToLowerInvariant() -eq $recordedInstall.ToLowerInvariant()))
        if ($pointsHere) {
            Add-Finding -Area 'shortcuts' -Status 'ok' -Detail "$(Split-Path -Leaf $lnk) -> $args"
        } elseif ($pointsAtRecorded) {
            # Correct on its own terms: it targets the installation Windows
            # recorded. Repointing it at this run's directory would break it.
            Add-Finding -Area 'shortcuts' -Status 'info' `
                -Detail "$(Split-Path -Leaf $lnk) targets the recorded installation $recordedInstall, not $ProjectRoot"
        } else {
            $badShortcuts.Add($lnk)
            Add-Finding -Area 'shortcuts' -Status 'problem' `
                -Detail "$lnk points somewhere else: $args (working directory $work)" `
                -Fix 'Re-create it against this installation.'
        }
    } catch {
        Add-Finding -Area 'shortcuts' -Status 'info' -Detail "could not read $lnk : $($_.Exception.Message)"
    }
}
if ($shortcutPaths.Count -gt 0 -and -not (@($shortcutPaths | Where-Object { Test-Path -LiteralPath $_ }).Count)) {
    Add-Finding -Area 'shortcuts' -Status 'problem' -Detail 'no RedSight shortcut exists' `
        -Fix 'Create the Desktop shortcut for this installation.'
}

# ==========================================================================
# 3. Files referencing another root
# ==========================================================================

Write-RsLog ''
Write-RsLog '--- install-path references ---' -Level STEP

$sourceRoot = Get-RsPayloadSourceRoot -ProjectRoot $ProjectRoot
if ($sourceRoot) {
    Add-Finding -Area 'paths' -Status 'info' -Detail "this payload was built from $sourceRoot"
} else {
    Add-Finding -Area 'paths' -Status 'info' `
        -Detail 'this payload records no build root, so path matching falls back to any path ending in \RedSight'
}

$stale = Repair-RsHardcodedPaths -ProjectRoot $ProjectRoot -WhatIf
if ($stale.Rewritten -eq 0) {
    Add-Finding -Area 'paths' -Status 'ok' -Detail 'no file references another installation'
} else {
    foreach ($file in @($stale.Files)) {
        $rel = $file.Substring($ProjectRoot.Length).TrimStart('\')
        # Show the offending lines: "a file points elsewhere" is not actionable
        # on its own.
        $shown = 0
        try {
            $lineNumber = 0
            foreach ($line in @(Get-Content -LiteralPath $file -ErrorAction Stop)) {
                $lineNumber++
                # (?<![A-Za-z]) so a URI scheme such as https:// is not read as
                # a drive letter.
                if ($line -match '(?<![A-Za-z])[A-Za-z]:[\\/]' -and $line -notmatch [regex]::Escape($ProjectRoot)) {
                    if ($shown -lt 3) {
                        Write-RsLog ("        {0}:{1}: {2}" -f $rel, $lineNumber, $line.Trim()) -Level WARN
                        $shown++
                    }
                }
            }
        } catch { }
    }
    Add-Finding -Area 'paths' -Status 'problem' `
        -Detail "$($stale.Rewritten) file(s) reference another installation root" `
        -Fix 'Rewrite them to this installation directory.'
}

# ==========================================================================
# 4. The working directory
# ==========================================================================

Write-RsLog ''
Write-RsLog '--- working directory ---' -Level STEP

$envFile = Join-Path $ProjectRoot '.env'
$workspace = Get-RsEnvValue -Path $envFile -Key 'REDSIGHT_WORKSPACE'

if (-not $workspace) {
    Add-Finding -Area 'workspace' -Status 'problem' -Detail 'REDSIGHT_WORKSPACE is not set in .env' `
        -Fix 'Create the working directory and record it.'
} elseif ($workspace.TrimEnd('\').ToLowerInvariant() -eq $ProjectRoot.ToLowerInvariant()) {
    Add-Finding -Area 'workspace' -Status 'problem' `
        -Detail "the working directory is the installation directory itself ($workspace)" `
        -Fix 'Move it to a separate folder so the two trees stop mixing.'
} elseif (Test-RsIsAppTree -Path $workspace) {
    Add-Finding -Area 'workspace' -Status 'problem' `
        -Detail "the working directory is itself a RedSight installation ($workspace)" `
        -Fix 'Move it to a separate folder. Nothing already in that folder is touched.'
} elseif (-not (Test-Path -LiteralPath $workspace)) {
    Add-Finding -Area 'workspace' -Status 'problem' -Detail "the working directory is missing: $workspace" `
        -Fix 'Re-create it.'
} else {
    Add-Finding -Area 'workspace' -Status 'ok' -Detail $workspace
}

# ==========================================================================
# 5. The environment the app will actually see
# ==========================================================================

Write-RsLog ''
Write-RsLog '--- LM Studio and the runtime environment ---' -Level STEP

$uiPython = Join-Path $ProjectRoot '.venv-ui\Scripts\python.exe'
$lmConfig = Read-RsLmStudioConfig
Add-Finding -Area 'lmstudio' -Status 'info' -Detail "recorded endpoint: $($lmConfig['base_url']) model: $(if ($lmConfig['model']) { $lmConfig['model'] } else { '(auto)' })"

$probe = Test-RsLmStudioEndpoint -BaseUrl $lmConfig['base_url']
if ($probe.Ok) {
    Add-Finding -Area 'lmstudio' -Status 'ok' -Detail "answering, $(@($probe.Models).Count) model(s) loaded"
} else {
    Add-Finding -Area 'lmstudio' -Status 'info' `
        -Detail "not answering at $($lmConfig['base_url']) - start it, or change it in Settings -> LM Studio"
}

if (Test-Path -LiteralPath $uiPython) {
    $r = Invoke-RsProcess -FilePath $uiPython -TimeoutSeconds 90 -Quiet `
        -Arguments @('-c', 'import os,json;print(json.dumps({k:os.environ.get(k,"") for k in ("LM_STUDIO_BASE_URL","LM_STUDIO_MODEL","REDSIGHT_UI_EFFECTS","RED_SIGHT_PLATFORM__DATA_ROOT")}))')
    if ($r.ExitCode -eq 0 -and $r.StdOut.Trim()) {
        Add-Finding -Area 'runtime-config' -Status 'ok' -Detail "the backend will read $($r.StdOut.Trim())"
    } else {
        Add-Finding -Area 'runtime-config' -Status 'problem' `
            -Detail 'redsight_bootstrap is not installed in .venv-ui, so the endpoint will not reach the backend' `
            -Fix 'Re-install the runtime configuration into both virtualenvs.'
    }
} else {
    Add-Finding -Area 'runtime-config' -Status 'problem' -Detail "missing: $uiPython" `
        -Fix 'Re-run dependency setup to create the environment.'
}

# ==========================================================================
# 6. Why the UI will not start
# ==========================================================================

Write-RsLog ''
Write-RsLog '--- Command Center launch ---' -Level STEP

if (Test-Path -LiteralPath $uiPython) {
    $ui = Test-RsUiLaunch -VenvPython $uiPython -ProjectRoot $ProjectRoot
    if ($ui.Ok) {
        Add-Finding -Area 'ui' -Status 'ok' -Detail $ui.Detail
        if ($ui.Fixes) { Add-Finding -Area 'ui' -Status 'info' -Detail "desktop fixes: $($ui.Fixes)" }
    } else {
        Add-Finding -Area 'ui' -Status 'problem' -Detail $ui.Detail `
            -Fix 'The traceback below names the failing import; that is the thing to fix.'
        if ($ui.Traceback) {
            Write-RsLog '        ---- Command Center traceback ----' -Level FAIL
            foreach ($line in ($ui.Traceback -split "`r?`n")) {
                if ($line.Trim()) { Write-RsLog "        $line" -Level FAIL }
            }
            Write-RsLog '        ---------------------------------' -Level FAIL
        }
    }
}

# The launcher's own logs from the last real attempt, which carry failures the
# headless import cannot reproduce (a missing display, a crashed backend).
$logDir = Join-Path (Get-RsLocalAppData) 'RedSight\logs'
if (Test-Path -LiteralPath $logDir) {
    $recent = @(Get-ChildItem -LiteralPath $logDir -File -ErrorAction SilentlyContinue |
                Where-Object { $_.Name -match 'stderr|ui-error|native-backend\.err|native-gateway\.err' } |
                Sort-Object LastWriteTime -Descending | Select-Object -First 3)
    foreach ($file in $recent) {
        $tail = @(Get-Content -LiteralPath $file.FullName -Tail 25 -ErrorAction SilentlyContinue |
                  Where-Object { $_.Trim() })
        if ($tail.Count -eq 0) { continue }
        Write-RsLog "        ---- $($file.Name) (last $($tail.Count) lines) ----" -Level WARN
        foreach ($line in $tail) { Write-RsLog "        $line" -Level WARN }
    }
}

# ==========================================================================
# 6b. GPU acceleration
# ==========================================================================

if (Test-Path -LiteralPath $uiPython) {
    Write-RsLog ''
    Write-RsLog '--- GPU acceleration ---' -Level STEP
    $torch = Test-RsTorchCuda -VenvPython $uiPython -ProjectRoot $ProjectRoot
    if (-not $torch.Ok) {
        Add-Finding -Area 'gpu' -Status 'info' -Detail $torch.Detail
    } elseif ($torch.Usable) {
        Add-Finding -Area 'gpu' -Status 'ok' -Detail $torch.Detail
    } elseif ($torch.Devices) {
        # A wheel with no kernels for the installed architecture imports fine and
        # reports CUDA as available; only a real allocation exposes it.
        Add-Finding -Area 'gpu' -Status 'problem' -Detail $torch.Detail `
            -Fix ('Re-run the installer from 11.5.1 or later, which picks the wheel from ' +
                  'the GPU architecture. This cannot be repaired from here: it needs the ' +
                  'matching PyTorch build downloaded.')
        Write-RsLog "        $($torch.Devices)" -Level FAIL
    } else {
        Add-Finding -Area 'gpu' -Status 'info' -Detail $torch.Detail
    }
}

# ==========================================================================
# 7. Services
# ==========================================================================

Write-RsLog ''
Write-RsLog '--- services ---' -Level STEP

function Test-LocalEndpoint {
    param([Parameter(Mandatory)][string]$Url)
    try {
        $req = [System.Net.HttpWebRequest]::Create($Url)
        $req.Timeout = 4000
        $req.Proxy = $null
        $resp = $req.GetResponse()
        $resp.Dispose()
        return $true
    } catch {
        return $false
    }
}

function Get-PortHolder {
    <#
        Which process is listening on a port, and where it was started from.

        This is the check that explains "the backend will not start" when the
        backend is in fact already running - from a different RedSight tree.
        uvicorn reports [Errno 10048] and exits; the UI then talks to whatever
        else owns the port.
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][int]$Port)

    $result = [pscustomobject]@{ Pid = 0; Name = ''; Path = ''; CommandLine = '' }
    try {
        $conn = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop |
                  Select-Object -First 1)
        if ($conn.Count -eq 0) { return $null }
        $result.Pid = [int]$conn[0].OwningProcess
    } catch {
        return $null
    }

    try {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $($result.Pid)" -ErrorAction Stop
        if ($proc) {
            $result.Name = "$($proc.Name)"
            $result.Path = "$($proc.ExecutablePath)"
            $result.CommandLine = "$($proc.CommandLine)"
        }
    } catch { }
    return $result
}

$services = [ordered]@{
    'backend (8000)'               = @{ Url = 'http://127.0.0.1:8000/api/v1/health'; Port = 8000 }
    'action/memory gateway (8765)' = @{ Url = 'http://127.0.0.1:8765/memory/status'; Port = 8765 }
}

$foreignHolders = New-Object System.Collections.Generic.List[object]

foreach ($name in $services.Keys) {
    $spec = $services[$name]
    $answering = Test-LocalEndpoint -Url $spec.Url
    $holder = Get-PortHolder -Port $spec.Port

    if (-not $answering -and -not $holder) {
        Add-Finding -Area 'services' -Status 'info' `
            -Detail "$name is not answering (it is started by the RedSight launcher)"
        continue
    }

    # Whose process is it? A path under this installation is what we want.
    $from = if ($holder) { $holder.Path } else { '' }
    $line = if ($holder) { $holder.CommandLine } else { '' }
    $belongsHere = $false
    foreach ($text in @($from, $line)) {
        if ($text -and $text.ToLowerInvariant().Contains($ProjectRoot.ToLowerInvariant())) {
            $belongsHere = $true
        }
    }

    # In container mode the backend runs inside the container and Docker
    # publishes the port on the host through its own proxy, so the listener is
    # never a RedSight process and never has this installation's path. Calling
    # that a foreign holder is wrong: it is exactly how a containerized install
    # is supposed to look.
    if (-not $belongsHere -and $holder) {
        $proxyNames = @('wslrelay.exe', 'com.docker.backend.exe', 'vpnkit.exe',
                        'com.docker.proxy.exe', 'docker.exe', 'dockerd.exe', 'svchost.exe')
        if ($proxyNames -contains $holder.Name.ToLowerInvariant()) {
            Add-Finding -Area 'services' -Status 'ok' `
                -Detail ("$name is answering, published by $($holder.Name) - the container " +
                         'port proxy, which is how container mode looks')
            continue
        }
    }

    if ($belongsHere) {
        Add-Finding -Area 'services' -Status 'ok' -Detail "$name is answering, from this installation (pid $($holder.Pid))"
    } elseif ($holder) {
        $foreignHolders.Add([pscustomobject]@{ Name = $name; Port = $spec.Port; Holder = $holder })
        Add-Finding -Area 'services' -Status 'problem' `
            -Detail ("port $($spec.Port) is held by pid $($holder.Pid) ($($holder.Name)) started from " +
                     "$(if ($from) { $from } else { '(unknown path)' }), which is NOT this installation") `
            -Fix ("This installation's own service cannot bind the port and exits with " +
                  "[Errno 10048], so the UI talks to the other one - which resolves file " +
                  "actions and exports against its own directory, not this one. Stop it " +
                  "with 'Stop-Process -Id $($holder.Pid)' and relaunch RedSight, or re-run " +
                  'with -StopOtherInstances.')
        if ($line) { Write-RsLog "        command line: $line" -Level WARN }
    } else {
        Add-Finding -Area 'services' -Status 'ok' -Detail "$name is answering"
    }
}

# ==========================================================================
# 8. Repairs
# ==========================================================================

$problems = @($findings | Where-Object { $_.Status -eq 'problem' })

Write-RsLog ''
Write-RsLog ('=' * 72)
if ($problems.Count -eq 0) {
    Write-RsLog 'No problems found.' -Level OK
} else {
    Write-RsLog "$($problems.Count) problem(s) found:" -Level FAIL
    foreach ($p in $problems) { Write-RsLog "  - [$($p.Area)] $($p.Detail)" -Level FAIL }
}
Write-RsLog ('=' * 72)

if (-not $Fix) {
    if ($problems.Count -gt 0) {
        Write-RsLog ''
        Write-RsLog 'Re-run with -Fix to apply the repairs above:' -Level INFO
        Write-RsLog "  powershell -ExecutionPolicy Bypass -File `"$scriptDir\Repair-RedSight.ps1`" -Fix" -Level INFO
    }
} elseif ($problems.Count -gt 0) {
    Write-RsLog ''
    Write-RsLog '--- applying repairs ---' -Level STEP

    if (@($problems | Where-Object { $_.Area -eq 'paths' }).Count) {
        $result = Repair-RsHardcodedPaths -ProjectRoot $ProjectRoot
        $actions.Add("rewrote install paths in $($result.Rewritten) file(s)")
    }

    if (@($problems | Where-Object { $_.Area -eq 'workspace' }).Count) {
        # A colliding or missing workspace: Initialize-RsWorkspace picks a safe
        # directory itself and records it. Existing contents are never touched.
        $mode = Get-RsEnvValue -Path $envFile -Key 'REDSIGHT_RUNTIME_MODE'
        $ws = Initialize-RsWorkspace -ProjectRoot $ProjectRoot -NativeMode:($mode -eq 'native')
        $actions.Add("working directory set to $ws")
    }

    if (@($problems | Where-Object { $_.Area -eq 'runtime-config' }).Count) {
        foreach ($venv in @('.venv-ui', '.venv-actions')) {
            $py = Join-Path $ProjectRoot "$venv\Scripts\python.exe"
            if (Test-Path -LiteralPath $py) {
                if (Install-RsRuntimeBootstrap -VenvPython $py -ProjectRoot $ProjectRoot) {
                    $actions.Add("runtime configuration installed into $venv")
                }
            }
        }
    }

    if (@($problems | Where-Object { $_.Area -eq 'shortcuts' }).Count -or $badShortcuts.Count) {
        $mode = Get-RsEnvValue -Path $envFile -Key 'REDSIGHT_RUNTIME_MODE'
        if (-not $mode) { $mode = 'container' }
        if (Install-RsShortcuts -ProjectRoot $ProjectRoot -RuntimeMode $mode) {
            $actions.Add('desktop shortcut re-created against this installation')
        }
    }

    if ($StopOtherInstances -and $foreignHolders.Count) {
        foreach ($entry in $foreignHolders) {
            try {
                Stop-Process -Id $entry.Holder.Pid -Force -ErrorAction Stop
                $actions.Add("stopped pid $($entry.Holder.Pid) which held port $($entry.Port)")
            } catch {
                Write-RsLog "could not stop pid $($entry.Holder.Pid): $($_.Exception.Message)" -Level WARN
            }
        }
    } elseif ($foreignHolders.Count) {
        Write-RsLog 'a port is held by another installation; re-run with -StopOtherInstances to free it' -Level WARN
    }

    if ($RecreateVenv) {
        $python = Resolve-RsPython -ProjectRoot $ProjectRoot
        if ($python) {
            $plan = Get-RsDependencyPlan -SetupProfile 'auto' -Hardware (Get-RsHardwareProfile)
            Initialize-RsVenv -PythonExe $python -VenvPath (Join-Path $ProjectRoot '.venv-ui') `
                              -Description '.venv-ui' -PreInstalls $plan.PreInstalls `
                              -EditableProjects @($ProjectRoot) `
                              -RequirementFiles @((Join-Path $ProjectRoot 'requirements-desktop-stage11.txt')) `
                              -Wheelhouse (Get-RsWheelhouse -ProjectRoot $ProjectRoot) -Recreate | Out-Null
            $actions.Add('.venv-ui recreated')
        } else {
            Write-RsLog 'no usable Python 3.12 found; cannot recreate the environment' -Level FAIL
        }
    }

    Write-RsLog ''
    Write-RsLog ('=' * 72)
    if ($actions.Count) {
        Write-RsLog 'Repairs applied:' -Level OK
        foreach ($a in $actions) { Write-RsLog "  - $a" -Level OK }
        Write-RsLog ''
        Write-RsLog 'Re-run this script without -Fix to confirm, then launch RedSight.' -Level INFO
    } else {
        Write-RsLog 'Nothing could be repaired automatically. The findings above name what to do.' -Level WARN
    }
    Write-RsLog ('=' * 72)
}

Write-RsLog ''
Write-RsLog "Full log: $(Get-RsLogPath)"

if ($Json) { $findings | ConvertTo-Json -Depth 4 }

exit $(if (@($findings | Where-Object { $_.Status -eq 'problem' }).Count) { 1 } else { 0 })
