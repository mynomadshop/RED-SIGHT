<#
    Bootstrap-RedSight.ps1

    RedSight first-run setup. Run by the installer as Administrator, and safe to
    re-run at any time to repair a broken environment.

    Unlike the previous bootstrap, this one never tells the user to go and
    install something by hand: every dependency is detected and, if missing,
    downloaded, installed and configured. See RedSight-Preflight.ps1 for the
    per-dependency logic.

    Exit codes
        0   everything required and requested succeeded
        1   a required dependency could not be provisioned (RedSight will not run)
        2   required parts succeeded, optional parts did not (RedSight will run,
            but something like Docker image building needs attention)
        3   a restart is required before setup can finish; setup will resume
            automatically at the next logon
#>

[CmdletBinding()]
param(
    # Either the scripts\windows directory (as the installer passes) or the
    # project root; both are accepted so old invocations keep working.
    [string]$Root,
    [string]$ProjectRoot,

    # Python
    [switch]$PreferSystemPython,
    [switch]$IncludeMainVenv,
    [switch]$RecreateVenvs,

    # Docker / WSL2
    [switch]$SkipDocker,
    [switch]$InstallDocker,
    [switch]$EnableWsl,
    [switch]$BuildImages,

    # Optional extras
    [switch]$InstallNode,

    # Behaviour
    [switch]$OfflineOnly,
    [switch]$SkipShortcut,
    [switch]$SkipPathRewrite,
    [switch]$Launch,
    [switch]$Resume,
    [switch]$NonInteractive
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# --------------------------------------------------------------------------
# Locate ourselves and the project
# --------------------------------------------------------------------------

$scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
. (Join-Path $scriptDir 'RedSight-Preflight.ps1')

if (-not $ProjectRoot) {
    # $Root is historically scripts\windows; the project root is two levels up.
    $base = if ($Root) { $Root } else { $scriptDir }
    $ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $base '..\..'))
}
if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot 'docker-compose.yml'))) {
    # Fall back to treating the given path as the project root itself.
    $alt = if ($Root) { [System.IO.Path]::GetFullPath($Root) } else { $ProjectRoot }
    if (Test-Path -LiteralPath (Join-Path $alt 'docker-compose.yml')) { $ProjectRoot = $alt }
}

$logPath = Initialize-RsLog -Name 'bootstrap'

$failures = New-Object System.Collections.Generic.List[string]
$warnings = New-Object System.Collections.Generic.List[string]
$rebootRequired = $false

function Invoke-RsStep {
    <#
        Runs one setup step. A Required step that throws aborts the summary as a
        failure; an optional step that throws is recorded as a warning and setup
        continues, because a missing Docker must not stop the desktop UI from
        being installed.
    #>
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][scriptblock]$Action,
        [switch]$Required
    )

    Write-RsLog "==> $Name" -Level STEP
    try {
        $result = & $Action
        Write-RsLog "    done: $Name" -Level OK
        return $result
    } catch {
        $msg = "$Name :: $($_.Exception.Message)"
        if ($Required) {
            Write-RsLog "    FAILED (required): $msg" -Level FAIL
            $failures.Add($msg)
        } else {
            Write-RsLog "    FAILED (optional): $msg" -Level WARN
            $warnings.Add($msg)
        }
        return $null
    }
}

# --------------------------------------------------------------------------
# Banner
# --------------------------------------------------------------------------

Write-RsLog ('=' * 70)
Write-RsLog 'REDSIGHT SETUP'
Write-RsLog ('=' * 70)
Write-RsLog "ProjectRoot   : $ProjectRoot"
Write-RsLog "Log           : $logPath"
Write-RsLog "Elevated      : $(Test-RsAdmin)"
Write-RsLog "PowerShell    : $($PSVersionTable.PSVersion)"
Write-RsLog "Resume        : $Resume"
Write-RsLog "OfflineOnly   : $OfflineOnly"
Write-RsLog ('=' * 70)

if ($Resume) {
    # The RunOnce entry has already fired; clear it so we do not loop.
    Unregister-RsResumeAfterReboot
}

Set-RsSummary -Key 'projectRoot' -Value $ProjectRoot
Set-RsSummary -Key 'startedAt' -Value (Get-Date -Format 'o')
Set-RsSummary -Key 'elevated' -Value (Test-RsAdmin)
Set-RsSummary -Key 'log' -Value $logPath

# Report what we found before changing anything - this is in the log for support.
$before = Invoke-RsStep -Name 'Dependency scan' -Action {
    $r = Get-RsPreflightReport -ProjectRoot $ProjectRoot
    Write-RsLog "    python        : $(if ($r.PythonPath) { "$($r.PythonPath) ($($r.PythonVersion))" } else { 'NOT FOUND' })"
    Write-RsLog "    python bundle : $($r.PythonBundled)"
    Write-RsLog "    wheelhouse    : $(if ($r.Wheelhouse) { $r.Wheelhouse } else { 'none' })"
    Write-RsLog "    docker cli    : $(if ($r.DockerCli) { $r.DockerCli } else { 'NOT FOUND' })"
    Write-RsLog "    docker engine : $($r.DockerRunning)"
    Write-RsLog "    wsl subsystem : $($r.Wsl.SubsystemEnabled) / vmp: $($r.Wsl.VirtualMachinePlatform) / kernel: $($r.Wsl.KernelInstalled)"
    Write-RsLog "    node          : $(if ($r.NodePath) { $r.NodePath } else { 'NOT FOUND' })"
    Write-RsLog "    online        : $($r.Online)"
    return $r
}
if ($before) { Set-RsSummary -Key 'before' -Value $before }

# --------------------------------------------------------------------------
# 1. Install-path repair and .env
# --------------------------------------------------------------------------

if (-not $SkipPathRewrite) {
    Invoke-RsStep -Name 'Rewriting build-machine paths to the install directory' -Action {
        $r = Repair-RsHardcodedPaths -ProjectRoot $ProjectRoot
        Set-RsSummary -Key 'pathsRewritten' -Value $r.Rewritten
    } | Out-Null
}

Invoke-RsStep -Name 'Ensuring .env exists' -Action {
    New-RsEnvFile -ProjectRoot $ProjectRoot | Out-Null
} | Out-Null

# --------------------------------------------------------------------------
# 2. Python runtime  (REQUIRED)
# --------------------------------------------------------------------------

$python = Invoke-RsStep -Name 'Providing Python 3.12' -Required -Action {
    $p = Resolve-RsPython -ProjectRoot $ProjectRoot `
                          -PreferSystemPython:$PreferSystemPython `
                          -OfflineOnly:$OfflineOnly
    if (-not $p) { throw 'no usable Python 3.12 interpreter could be provisioned' }
    Set-RsSummary -Key 'python' -Value $p
    $pv = Get-RsPythonVersion -PythonExe $p
    Set-RsSummary -Key 'pythonVersion' -Value $(if ($pv) { $pv.ToString() } else { 'unknown' })
    return $p
}

if (-not $python) {
    Write-RsLog 'Python could not be provisioned; skipping every dependent step.' -Level FAIL
} else {
    $wheelhouse = Get-RsWheelhouse -ProjectRoot $ProjectRoot

    # ----------------------------------------------------------------------
    # 3. Desktop UI environment  (REQUIRED - this is what the shortcut runs)
    # ----------------------------------------------------------------------
    $uiPython = Invoke-RsStep -Name 'Setting up the desktop UI environment (.venv-ui)' -Required -Action {
        $venv = Join-Path $ProjectRoot '.venv-ui'
        $p = Initialize-RsVenv -PythonExe $python -VenvPath $venv -Description '.venv-ui' `
                               -EditableProjects @($ProjectRoot) `
                               -RequirementFiles @((Join-Path $ProjectRoot 'requirements-desktop-stage11.txt')) `
                               -Wheelhouse $wheelhouse -OfflineOnly:$OfflineOnly -Recreate:$RecreateVenvs
        Set-RsSummary -Key 'venvUi' -Value $p
        return $p
    }

    if ($uiPython) {
        Invoke-RsStep -Name 'Verifying the desktop UI environment' -Required -Action {
            # qasync was the module whose absence broke every 11.1 install.
            $modules = @('PySide6', 'qasync', 'httpx', 'pydantic')
            if (-not (Test-RsVenvImports -VenvPython $uiPython -Modules $modules)) {
                throw "the .venv-ui environment is missing required modules ($($modules -join ', '))"
            }
        } | Out-Null
    }

    # ----------------------------------------------------------------------
    # 4. Action/memory gateway environment
    # ----------------------------------------------------------------------
    Invoke-RsStep -Name 'Setting up the action gateway environment (.venv-actions)' -Action {
        $venv = Join-Path $ProjectRoot '.venv-actions'
        $p = Initialize-RsVenv -PythonExe $python -VenvPath $venv -Description '.venv-actions' `
                               -Packages @('fastapi', 'uvicorn[standard]', 'httpx', 'pydantic', 'apscheduler',
                                           'sqlalchemy', 'reportlab', 'tzlocal', 'playwright',
                                           'nvidia-ml-py>=13.580,<14') `
                               -RequirementFiles @((Join-Path $ProjectRoot 'requirements-stage111-actions.txt')) `
                               -Wheelhouse $wheelhouse -OfflineOnly:$OfflineOnly -Recreate:$RecreateVenvs
        Set-RsSummary -Key 'venvActions' -Value $p
    } | Out-Null

    # ----------------------------------------------------------------------
    # 5. Main application venv - opt-in only
    # ----------------------------------------------------------------------
    if ($IncludeMainVenv) {
        Invoke-RsStep -Name 'Setting up the main application environment (.venv)' -Action {
            Initialize-RsVenv -PythonExe $python -VenvPath (Join-Path $ProjectRoot '.venv') -Description '.venv' `
                              -EditableProjects @("$ProjectRoot[dev]") `
                              -Wheelhouse $wheelhouse -OfflineOnly:$OfflineOnly -Recreate:$RecreateVenvs | Out-Null
        } | Out-Null
    } else {
        Write-RsLog 'Skipping the main application venv (.venv) - the shortcut and Docker backend do not use it.' -Level INFO
    }
}

# --------------------------------------------------------------------------
# 6. Node.js and the WhatsApp bridge (optional feature)
# --------------------------------------------------------------------------

if ($InstallNode) {
    Invoke-RsStep -Name 'Providing Node.js (WhatsApp remote utility)' -Action {
        Install-RsNode -ProjectRoot $ProjectRoot -OfflineOnly:$OfflineOnly | Out-Null
    } | Out-Null
}

Invoke-RsStep -Name 'Installing WhatsApp bridge Node dependencies' -Action {
    $bridge = Join-Path $ProjectRoot 'redsight_remote\whatsapp_bridge'
    if (-not (Test-Path -LiteralPath (Join-Path $bridge 'package.json'))) {
        Write-RsLog '    bridge not present in this build - nothing to do' -Level INFO
        return
    }
    $npm = Get-RsCommand -Name 'npm'
    if (-not $npm) {
        Write-RsLog '    Node.js/npm not installed - the WhatsApp remote utility stays unavailable' -Level INFO
        return
    }
    $r = Invoke-RsProcess -FilePath $npm.Source `
                          -Arguments @('install', '--no-audit', '--no-fund', '--loglevel=error') `
                          -WorkingDirectory $bridge -TimeoutSeconds 1800
    if ($r.ExitCode -ne 0) { throw "npm install failed with exit code $($r.ExitCode)" }
} | Out-Null

# --------------------------------------------------------------------------
# 7. WSL2 + Docker
# --------------------------------------------------------------------------

if ($SkipDocker) {
    Write-RsLog 'Skipping all Docker setup (-SkipDocker).' -Level INFO
} else {
    $dockerPresent = [bool](Find-RsDockerDesktop)

    if ($EnableWsl -or ($InstallDocker -and -not $dockerPresent)) {
        Invoke-RsStep -Name 'Enabling the WSL2 platform (Docker backend)' -Action {
            $r = Enable-RsWsl2
            Set-RsSummary -Key 'wsl' -Value $r
            if ($r.RebootRequired) {
                $script:rebootRequired = $true
                Write-RsLog '    a restart is required before Docker can run' -Level WARN
            }
        } | Out-Null
    }

    if ($InstallDocker -and -not $dockerPresent) {
        Invoke-RsStep -Name 'Installing Docker Desktop' -Action {
            Install-RsDockerDesktop -ProjectRoot $ProjectRoot -OfflineOnly:$OfflineOnly | Out-Null
            Set-RsSummary -Key 'dockerInstalled' -Value $true
        } | Out-Null
    } elseif ($dockerPresent) {
        Write-RsLog 'Docker Desktop is already installed.' -Level OK
    } else {
        Write-RsLog 'Docker Desktop is not installed and automatic installation was not requested.' -Level WARN
        $warnings.Add('Docker Desktop is not installed; the RedSight backend containers cannot run until it is.')
    }

    if (-not $rebootRequired) {
        $engineUp = Invoke-RsStep -Name 'Starting the Docker engine' -Action {
            $ok = Start-RsDockerEngine
            Set-RsSummary -Key 'dockerRunning' -Value $ok
            if (-not $ok) { throw 'the Docker engine did not become available' }
            return $ok
        }

        if ($engineUp -and $BuildImages) {
            Invoke-RsStep -Name 'Building the RedSight Docker images' -Action {
                Build-RsDockerImages -ProjectRoot $ProjectRoot | Out-Null
                Set-RsSummary -Key 'dockerImagesBuilt' -Value $true
            } | Out-Null
        } elseif ($BuildImages) {
            Write-RsLog 'Skipping the image build because the Docker engine is unavailable; RedSight will build them on first launch.' -Level WARN
        }
    } else {
        Write-RsLog 'Deferring Docker startup and image build until after the restart.' -Level WARN
    }
}

# --------------------------------------------------------------------------
# 8. Shortcut
# --------------------------------------------------------------------------

if (-not $SkipShortcut) {
    Invoke-RsStep -Name 'Creating the Desktop shortcut' -Action {
        Install-RsShortcuts -ProjectRoot $ProjectRoot | Out-Null
    } | Out-Null
}

# --------------------------------------------------------------------------
# 9. Reboot handling
# --------------------------------------------------------------------------

if ($rebootRequired) {
    $resumeArgs = @()
    if ($InstallDocker)       { $resumeArgs += '-InstallDocker' }
    if ($BuildImages)         { $resumeArgs += '-BuildImages' }
    if ($InstallNode)         { $resumeArgs += '-InstallNode' }
    if ($PreferSystemPython)  { $resumeArgs += '-PreferSystemPython' }
    if ($OfflineOnly)         { $resumeArgs += '-OfflineOnly' }
    # The heavy Python work is already done; skip it on resume.
    $resumeArgs += '-SkipPathRewrite'
    Register-RsResumeAfterReboot -ProjectRoot $ProjectRoot -ExtraArguments ($resumeArgs -join ' ') | Out-Null
}

# --------------------------------------------------------------------------
# 10. Final report
# --------------------------------------------------------------------------

$after = Get-RsPreflightReport -ProjectRoot $ProjectRoot
Set-RsSummary -Key 'after' -Value $after
Set-RsSummary -Key 'failures' -Value $failures
Set-RsSummary -Key 'warnings' -Value $warnings
Set-RsSummary -Key 'rebootRequired' -Value $rebootRequired
Set-RsSummary -Key 'finishedAt' -Value (Get-Date -Format 'o')

$summaryPath = Join-Path (Get-RsLocalAppData) 'RedSight\setup-summary.json'
Save-RsSummary -Path $summaryPath

Write-RsLog ('=' * 70)
Write-RsLog 'REDSIGHT SETUP SUMMARY'
Write-RsLog ('=' * 70)
Write-RsLog "Python          : $(if ($after.PythonPath) { "$($after.PythonPath) ($($after.PythonVersion))" } else { 'MISSING' })"
Write-RsLog "Desktop UI env  : $(if ($after.Venvs.'.venv-ui') { 'ready' } else { 'MISSING' })"
Write-RsLog "Gateway env     : $(if ($after.Venvs.'.venv-actions') { 'ready' } else { 'missing' })"
Write-RsLog "Docker Desktop  : $(if ($after.DockerInstalled) { 'installed' } else { 'not installed' })"
Write-RsLog "Docker engine   : $(if ($after.DockerRunning) { 'running' } else { 'not running' })"
Write-RsLog "Node.js         : $(if ($after.NodePath) { $after.NodePath } else { 'not installed (optional)' })"

if ($warnings.Count) {
    Write-RsLog ''
    Write-RsLog "$($warnings.Count) optional step(s) need attention:" -Level WARN
    foreach ($w in $warnings) { Write-RsLog "  - $w" -Level WARN }
}
if ($failures.Count) {
    Write-RsLog ''
    Write-RsLog "$($failures.Count) required step(s) failed:" -Level FAIL
    foreach ($f in $failures) { Write-RsLog "  - $f" -Level FAIL }
}

Write-RsLog ''
Write-RsLog "Log     : $logPath"
Write-RsLog "Summary : $summaryPath"
Write-RsLog ('=' * 70)

if ($Launch -and -not $failures.Count -and -not $rebootRequired) {
    $start = Join-Path $ProjectRoot 'START-REDSIGHT.ps1'
    if (Test-Path -LiteralPath $start) {
        Write-RsLog 'launching RedSight' -Level STEP
        $ps = Get-RsPowerShellExe
        Start-Process -FilePath $ps -ArgumentList @('-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $start) | Out-Null
    }
}

if ($rebootRequired) {
    Write-RsLog 'RESTART REQUIRED - setup will resume automatically after you sign in again.' -Level WARN
    exit 3
}
if ($failures.Count) { exit 1 }
if ($warnings.Count) { exit 2 }
Write-RsLog 'RedSight setup completed successfully.' -Level OK
exit 0
