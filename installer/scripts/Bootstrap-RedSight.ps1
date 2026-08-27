<#
    Bootstrap-RedSight.ps1

    RedSight first-run setup. Run by the installer as Administrator, and safe to
    re-run at any time to repair a broken environment.

    Setup never tells the user to go and install something by hand, and never
    starts work the machine cannot finish: it scans the hardware first and
    adapts. A laptop with no NVIDIA driver gets CPU wheels instead of 2.5 GB of
    CUDA runtime; a machine whose firmware has virtualization switched off is
    never sent down the WSL2/Docker path at all, and runs RedSight natively with
    an embedded vector store instead.

    Exit codes
        0   everything required and requested succeeded
        1   a required dependency could not be provisioned (RedSight will not run)
        2   required parts succeeded, optional parts did not (RedSight will run,
            but something such as Docker image building needs attention)
        3   a restart is required before setup can finish; setup will resume
            automatically at the next logon
#>

[CmdletBinding()]
param(
    # Either the scripts\windows directory (as the installer passes) or the
    # project root; both are accepted so old invocations keep working.
    [string]$Root,
    [string]$ProjectRoot,

    # Machine profile produced by RedSight-Hardware.ps1. The installer wizard
    # scans before installing and passes the result here to avoid a second scan.
    [string]$HardwareProfile,

    # cuda  = NVIDIA local inference (CUDA wheels)
    # api   = laptop / cloud providers (CPU wheels, no CUDA payload)
    # auto  = decide from the hardware scan
    [ValidateSet('auto', 'cuda', 'api')][string]$SetupProfile = 'auto',

    # AI provider to preconfigure. The key is stored the same way the Settings
    # dialog stores it (Windows DPAPI, current user).
    [ValidateSet('', 'lmstudio', 'openai', 'gemini', 'xai', 'anthropic', 'custom')]
    [string]$ApiProvider = '',
    [string]$ApiKey = '',
    [string]$ApiModel = '',
    [string]$ApiBaseUrl = '',

    # Where RedSight reads and writes by default.
    [string]$WorkspaceDir,

    # container = Docker + WSL2 backend; native = in-process backend, no Docker.
    [ValidateSet('auto', 'container', 'native')][string]$RuntimeMode = 'auto',

    # Directory or file holding MCP server definitions to register.
    [string]$McpPath,

    # Local LM Studio server. Left empty, setup probes the usual local
    # endpoints and starts the server through the lms CLI if it finds one.
    [string]$LmStudioUrl = '',
    [string]$LmStudioModel = '',
    [switch]$NoLmStudioAutoStart,

    # full | reduced | off - how much animation the desktop UI runs. Reduced by
    # default: the shipped ambient layer repaints the whole window twenty times
    # a second through a translucent widget, which is felt as input lag on
    # integrated graphics.
    [ValidateSet('', 'full', 'reduced', 'off')][string]$UiEffects = '',

    # INI file carrying the installer wizard's answers. Used instead of passing
    # them as arguments so an API key never appears in a command line, the
    # process list, or the Inno Setup log.
    [string]$AnswerFile,

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

# Captured before dot-sourcing: RedSight-Preflight.ps1 declares its own
# [string]$ProjectRoot, and a dot-sourced param() block runs in this scope and
# would reset ours to ''. The installer passes -ProjectRoot "{app}".
$requestedRoot = if ($PSBoundParameters.ContainsKey('ProjectRoot')) { $ProjectRoot } else { '' }

. (Join-Path $scriptDir 'RedSight-Preflight.ps1')

$ProjectRoot = $requestedRoot
if (-not $ProjectRoot) {
    # $Root is historically scripts\windows; the project root is two levels up.
    $base = if ($Root) { $Root } else { $scriptDir }
    $ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $base '..\..'))
}
if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot 'docker-compose.yml'))) {
    $alt = if ($Root) { [System.IO.Path]::GetFullPath($Root) } else { $ProjectRoot }
    if (Test-Path -LiteralPath (Join-Path $alt 'docker-compose.yml')) { $ProjectRoot = $alt }
}

$logPath = Initialize-RsLog -Name 'bootstrap'

# --------------------------------------------------------------------------
# Wizard answers
# --------------------------------------------------------------------------

if ($AnswerFile) {
    if (Test-Path -LiteralPath $AnswerFile) {
        Write-RsLog "reading wizard answers from $AnswerFile" -Level STEP
        $answers = @{}
        foreach ($line in @(Get-Content -LiteralPath $AnswerFile -ErrorAction SilentlyContinue)) {
            $t = $line.Trim()
            if (-not $t -or $t.StartsWith('[') -or $t.StartsWith(';') -or $t.StartsWith('#')) { continue }
            $eq = $t.IndexOf('=')
            if ($eq -lt 1) { continue }
            $answers[$t.Substring(0, $eq).Trim()] = $t.Substring($eq + 1).Trim()
        }

        # Explicit parameters win over the answer file, so a repair run can
        # override anything the wizard recorded.
        if (-not $PSBoundParameters.ContainsKey('SetupProfile') -and $answers['profile']) { $SetupProfile = $answers['profile'] }
        if (-not $PSBoundParameters.ContainsKey('RuntimeMode') -and $answers['runtimeMode']) { $RuntimeMode = $answers['runtimeMode'] }
        if (-not $WorkspaceDir -and $answers['workspace']) { $WorkspaceDir = $answers['workspace'] }
        if (-not $ApiProvider -and $answers['provider']) { $ApiProvider = $answers['provider'] }
        if (-not $ApiKey -and $answers['apiKey']) { $ApiKey = $answers['apiKey'] }
        if (-not $ApiModel -and $answers['model']) { $ApiModel = $answers['model'] }
        if (-not $ApiBaseUrl -and $answers['baseUrl']) { $ApiBaseUrl = $answers['baseUrl'] }
        if (-not $McpPath -and $answers['mcpPath']) { $McpPath = $answers['mcpPath'] }
        if (-not $HardwareProfile -and $answers['hardwareProfile']) { $HardwareProfile = $answers['hardwareProfile'] }
        if (-not $LmStudioUrl -and $answers['lmStudioUrl']) { $LmStudioUrl = $answers['lmStudioUrl'] }
        if (-not $LmStudioModel -and $answers['lmStudioModel']) { $LmStudioModel = $answers['lmStudioModel'] }
        if (-not $UiEffects -and $answers['uiEffects']) { $UiEffects = $answers['uiEffects'] }

        $keyNote = if ($ApiKey) { 'yes' } else { 'no' }
        Write-RsLog "    profile=$SetupProfile runtime=$RuntimeMode provider=$ApiProvider apiKey=$keyNote" -Level DEBUG

        # The answers may contain a secret; do not leave it lying in %TEMP%.
        try {
            $len = (Get-Item -LiteralPath $AnswerFile).Length
            # Overwrite before deleting so the bytes are not simply unlinked.
            [System.IO.File]::WriteAllBytes($AnswerFile, (New-Object byte[] $len))
            Remove-Item -LiteralPath $AnswerFile -Force -ErrorAction SilentlyContinue
            Write-RsLog '    answer file consumed and erased' -Level DEBUG
        } catch {
            Write-RsLog "    could not erase the answer file: $($_.Exception.Message)" -Level WARN
        }
    } else {
        Write-RsLog "answer file not found: $AnswerFile" -Level WARN
    }
}

$failures = New-Object System.Collections.Generic.List[string]
$warnings = New-Object System.Collections.Generic.List[string]
$rebootRequired = $false

function Invoke-RsStep {
    <#
        Runs one setup step. A Required step that throws is a failure; an
        optional step that throws is a warning and setup continues, because a
        missing Docker must not stop the desktop UI from being installed.
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
Write-RsLog "Setup profile : $SetupProfile"
Write-RsLog "Runtime mode  : $RuntimeMode"
Write-RsLog "Resume        : $Resume"
Write-RsLog "OfflineOnly   : $OfflineOnly"
Write-RsLog ('=' * 70)

if ($Resume) {
    Unregister-RsResumeAfterReboot
}

Set-RsSummary -Key 'projectRoot' -Value $ProjectRoot
Set-RsSummary -Key 'startedAt' -Value (Get-Date -Format 'o')
Set-RsSummary -Key 'elevated' -Value (Test-RsAdmin)
Set-RsSummary -Key 'log' -Value $logPath

# --------------------------------------------------------------------------
# 1. Hardware scan - everything below adapts to what this finds
# --------------------------------------------------------------------------

$hw = Invoke-RsStep -Name 'Scanning this machine' -Action {
    $h = Get-RsHardwareProfile -ProfilePath $HardwareProfile
    if (-not $h) {
        Write-RsLog '    hardware scan unavailable; assuming a conservative profile' -Level WARN
        return $null
    }
    Write-RsLog "    cpu            : $($h.cpu.name) ($($h.cpu.cores) cores)"
    Write-RsLog "    memory         : $($h.memoryGB) GB"
    Write-RsLog "    form factor    : $(if ($h.chassis.isLaptop) { 'laptop / portable' } else { 'desktop' })"
    $gpuCount = if ($h.gpu.PSObject.Properties['nvidiaGpuCount']) { $h.gpu.nvidiaGpuCount } else { 0 }
    Write-RsLog "    cuda capable   : $($h.gpu.cudaCapable) - $gpuCount NVIDIA GPU(s), max VRAM $($h.gpu.maxVramGB) GB"
    foreach ($g in @($h.gpu.nvidia)) {
        if ($g) { Write-RsLog "      GPU          : $($g.Name) ($($g.VramGB) GB, driver $($g.Driver))" }
    }
    Write-RsLog "    virtualization : $($h.virtualization.available) / wsl2 capable: $($h.virtualization.wsl2Capable)"
    foreach ($w in @($h.warnings)) { Write-RsLog "    ! $w" -Level WARN }
    return $h
}
Set-RsSummary -Key 'hardware' -Value $hw

# --------------------------------------------------------------------------
# 2. Decide the setup profile and the runtime mode
# --------------------------------------------------------------------------

$plan = Get-RsDependencyPlan -SetupProfile $SetupProfile -Hardware $hw
Write-RsLog "dependency profile: $($plan.Profile) - $($plan.Reason)" -Level OK
foreach ($pre in $plan.PreInstalls) { Write-RsLog "    will install: $($pre.Label)" -Level INFO }
Set-RsSummary -Key 'setupProfile' -Value $plan.Profile
Set-RsSummary -Key 'setupProfileReason' -Value $plan.Reason

# Container mode needs WSL2. Anything that rules WSL2 out forces native mode -
# this is what stops setup from installing Docker on a machine whose firmware
# has virtualization disabled and then failing to start the engine.
$wsl2Capable = $true
$nativeReason = ''
if ($hw) {
    $wsl2Capable = [bool]$hw.virtualization.wsl2Capable
    if (-not $wsl2Capable) { $nativeReason = [string]$hw.virtualization.wsl2Blocker }
}

$effectiveRuntime = $RuntimeMode
if ($RuntimeMode -eq 'auto') {
    if ($SkipDocker) {
        $effectiveRuntime = 'native'
        $nativeReason = 'Docker setup was skipped'
    } elseif (-not $wsl2Capable) {
        $effectiveRuntime = 'native'
    } else {
        $effectiveRuntime = 'container'
    }
} elseif ($RuntimeMode -eq 'container' -and -not $wsl2Capable) {
    Write-RsLog 'container mode was requested but this machine cannot run WSL2; falling back to native mode' -Level WARN
    $warnings.Add("Containerized backend was requested but is not possible: $nativeReason")
    $effectiveRuntime = 'native'
}

if ($effectiveRuntime -eq 'native') {
    Write-RsLog "runtime mode: NATIVE$(if ($nativeReason) { " ($nativeReason)" })" -Level WARN
    # Nothing Docker-related may run in native mode.
    $SkipDocker = $true
    $InstallDocker = $false
    $EnableWsl = $false
    $BuildImages = $false
}
Set-RsSummary -Key 'runtimeMode' -Value $effectiveRuntime
Set-RsSummary -Key 'runtimeModeReason' -Value $nativeReason

# The local model server is what a "lmstudio" provider actually talks to. Its
# endpoint has to be recorded whether or not it answers now: the launcher reads
# the recorded value on every start, so switching LM Studio on later is enough.
if (-not $ApiProvider -or $ApiProvider -eq 'lmstudio') {
    Invoke-RsStep -Name 'Locating the LM Studio local server' -Action {
        $lm = Resolve-RsLmStudio -BaseUrl $LmStudioUrl -Model $LmStudioModel `
                                 -NoAutoStart:$NoLmStudioAutoStart
        Set-RsSummary -Key 'lmStudioReachable' -Value $lm.Ok
        Set-RsSummary -Key 'lmStudioUrl' -Value $lm.BaseUrl
        Set-RsSummary -Key 'lmStudioModel' -Value $lm.Model
        if (-not $lm.Ok) {
            Write-RsLog '    RedSight will use this endpoint as soon as LM Studio is running' -Level INFO
        }
    } | Out-Null
}

Invoke-RsStep -Name 'Recording the desktop visual-effects budget' -Action {
    $effects = $UiEffects
    if (-not $effects) {
        # Reduced regardless of the GPU. The ambient layer's cost is not the
        # GPU's fill rate: it is a translucent, antialiased repaint of the whole
        # window driven from the Qt GUI thread, so it competes with input
        # handling on any machine. The lag that prompted this was reported on a
        # dual RTX 5090 desktop. Full remains available in the wizard and in
        # Settings for anyone who wants the shipped look back.
        $effects = 'reduced'
    }
    $config = Read-RsLmStudioConfig
    $config['ui_effects'] = $effects
    Save-RsLmStudioConfig -Config $config | Out-Null
    Set-RsSummary -Key 'uiEffects' -Value $effects
    Write-RsLog "    visual effects: $effects" -Level OK
} | Out-Null

# --------------------------------------------------------------------------
# 3. Install-path repair, .env and the working directory
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

$workspace = Invoke-RsStep -Name 'Creating the RedSight working directory' -Required -Action {
    $ws = Initialize-RsWorkspace -ProjectRoot $ProjectRoot -WorkspaceDir $WorkspaceDir `
                                 -NativeMode:($effectiveRuntime -eq 'native')
    Set-RsSummary -Key 'workspace' -Value $ws
    return $ws
}

if ($workspace) {
    Invoke-RsStep -Name 'Recording the runtime mode' -Action {
        Set-RsRuntimeMode -ProjectRoot $ProjectRoot -Mode $effectiveRuntime `
                          -WorkspaceDir $workspace -Reason $nativeReason | Out-Null
    } | Out-Null
}

# --------------------------------------------------------------------------
# 4. Python runtime  (REQUIRED)
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
    # 5. Desktop UI environment  (REQUIRED - this is what the shortcut runs)
    # ----------------------------------------------------------------------
    $uiPython = Invoke-RsStep -Name "Setting up the desktop UI environment (.venv-ui, $($plan.Profile) profile)" -Required -Action {
        $venv = Join-Path $ProjectRoot '.venv-ui'
        $p = Initialize-RsVenv -PythonExe $python -VenvPath $venv -Description '.venv-ui' `
                               -PreInstalls $plan.PreInstalls `
                               -EditableProjects @($ProjectRoot) `
                               -RequirementFiles @((Join-Path $ProjectRoot 'requirements-desktop-stage11.txt')) `
                               -Wheelhouse $wheelhouse -OfflineOnly:$OfflineOnly -Recreate:$RecreateVenvs
        Set-RsSummary -Key 'venvUi' -Value $p
        # Puts the recorded LM Studio endpoint into the environment of every
        # process this interpreter starts, before any application code runs.
        Install-RsRuntimeBootstrap -VenvPython $p -ProjectRoot $ProjectRoot | Out-Null
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

        # The real question is whether the Command Center starts, not whether a
        # module list resolves. This imports the actual launcher chain headlessly.
        Invoke-RsStep -Name 'Testing that the Command Center can start' -Required -Action {
            $ui = Test-RsUiLaunch -VenvPython $uiPython -ProjectRoot $ProjectRoot
            Set-RsSummary -Key 'uiLaunchOk' -Value $ui.Ok
            Set-RsSummary -Key 'uiLaunchDetail' -Value $ui.Detail
            if (-not $ui.Ok) {
                if ($ui.Traceback) {
                    Write-RsLog '    ---- Command Center import failure ----' -Level FAIL
                    foreach ($l in ($ui.Traceback -split "`r?`n")) { Write-RsLog "    $l" -Level FAIL }
                    Write-RsLog '    ---------------------------------------' -Level FAIL
                    Set-RsSummary -Key 'uiLaunchTraceback' -Value $ui.Traceback
                }
                throw $ui.Detail
            }
            Write-RsLog "    $($ui.Detail)" -Level OK
            if ($ui.Fixes) {
                Set-RsSummary -Key 'uiFixes' -Value $ui.Fixes
                if ($ui.Fixes -like 'FAILED:*') {
                    Write-RsLog "    the desktop responsiveness and LM Studio fixes did not install: $($ui.Fixes)" -Level WARN
                } else {
                    Write-RsLog "    desktop fixes: $($ui.Fixes)" -Level OK
                }
            }
        } | Out-Null

        if ($plan.Profile -eq 'cuda') {
            # "A CUDA build is installed" is not the same claim as "the GPUs
            # work": a wheel without kernels for the installed architecture
            # imports fine, reports torch.cuda.is_available() == True, and then
            # fails on the first operation. Ask the real question.
            Invoke-RsStep -Name 'Verifying that PyTorch can use this GPU' -Action {
                $t = Test-RsTorchCuda -VenvPython $uiPython -ProjectRoot $ProjectRoot
                Set-RsSummary -Key 'torchVersion' -Value $t.Version
                Set-RsSummary -Key 'torchCudaUsable' -Value $t.Usable
                Set-RsSummary -Key 'torchDetail' -Value $t.Detail
                Set-RsSummary -Key 'torchDevices' -Value $t.Devices
                if ($t.Devices) { Write-RsLog "    $($t.Devices)" -Level INFO }
                if ($t.Usable) {
                    Write-RsLog "    $($t.Detail)" -Level OK
                    return
                }
                # Not fatal: RedSight runs on CPU, only slower. But it must be
                # said plainly rather than left to surface as a runtime error.
                Write-RsLog "    $($t.Detail)" -Level WARN
                if ($plan.ComputeCap) {
                    Write-RsLog "    this machine reports compute capability $($plan.ComputeCap)" -Level WARN
                }
                Write-RsLog '    re-run setup with -RecreateVenvs to install the matching build' -Level WARN
                throw $t.Detail
            } | Out-Null
        }

        if ($effectiveRuntime -eq 'native') {
            Invoke-RsStep -Name 'Verifying the native backend environment' -Action {
                # Native mode runs the FastAPI app and the embedded vector store
                # in this same environment, so both must import.
                $modules = @('fastapi', 'uvicorn', 'qdrant_client')
                if (-not (Test-RsVenvImports -VenvPython $uiPython -Modules $modules)) {
                    throw "native mode needs $($modules -join ', ') in .venv-ui"
                }
            } | Out-Null
        }
    }

    # ----------------------------------------------------------------------
    # 6. Action/memory gateway environment
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
        Install-RsRuntimeBootstrap -VenvPython $p -ProjectRoot $ProjectRoot | Out-Null
    } | Out-Null

    # ----------------------------------------------------------------------
    # 7. Main application venv - opt-in only
    # ----------------------------------------------------------------------
    if ($IncludeMainVenv) {
        Invoke-RsStep -Name 'Setting up the main application environment (.venv)' -Action {
            Initialize-RsVenv -PythonExe $python -VenvPath (Join-Path $ProjectRoot '.venv') -Description '.venv' `
                              -PreInstalls $plan.PreInstalls `
                              -EditableProjects @("$ProjectRoot[dev]") `
                              -Wheelhouse $wheelhouse -OfflineOnly:$OfflineOnly -Recreate:$RecreateVenvs | Out-Null
        } | Out-Null
    } else {
        Write-RsLog 'Skipping the main application venv (.venv) - the shortcut and backend do not use it.' -Level INFO
    }
}

# --------------------------------------------------------------------------
# 8. AI provider and MCP servers
# --------------------------------------------------------------------------

if ($ApiProvider) {
    Invoke-RsStep -Name "Configuring the AI provider ($ApiProvider)" -Action {
        $stored = Set-RsProviderConfig -Provider $ApiProvider -ApiKey $ApiKey `
                                       -Model $ApiModel -BaseUrl $ApiBaseUrl
        Set-RsSummary -Key 'apiProvider' -Value $ApiProvider
        Set-RsSummary -Key 'apiKeyStored' -Value $stored
        if ($ApiProvider -ne 'lmstudio' -and -not $ApiKey) {
            Write-RsLog '    no API key supplied; add one in Settings -> AI Provider' -Level WARN
        }
    } | Out-Null
}

if ($McpPath -and $workspace) {
    Invoke-RsStep -Name 'Registering MCP servers' -Action {
        $n = Install-RsMcpConfig -SourcePath $McpPath -WorkspaceDir $workspace
        Set-RsSummary -Key 'mcpFiles' -Value $n
    } | Out-Null
}

# --------------------------------------------------------------------------
# 9. Node.js and the WhatsApp bridge (optional feature)
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
# 10. WSL2 + Docker (container mode only)
# --------------------------------------------------------------------------

if ($effectiveRuntime -eq 'native') {
    Write-RsLog 'Native runtime mode: WSL2 and Docker are not needed and will not be touched.' -Level INFO
    if ($nativeReason) {
        $warnings.Add("Running natively rather than in containers: $nativeReason")
    }
} elseif ($SkipDocker) {
    Write-RsLog 'Skipping all Docker setup (-SkipDocker).' -Level INFO
} else {
    $dockerPresent = [bool](Find-RsDockerDesktop)

    if ($EnableWsl -or ($InstallDocker -and -not $dockerPresent)) {
        Invoke-RsStep -Name 'Enabling the WSL2 platform (Docker backend)' -Action {
            $r = Enable-RsWsl2 -HardwareProfilePath $HardwareProfile
            Set-RsSummary -Key 'wsl' -Value $r
            if ($r.Blocked) {
                throw "WSL2 cannot be enabled on this machine: $($r.Reason)"
            }
            if ($r.RebootRequired) {
                $script:rebootRequired = $true
                Write-RsLog '    a restart is required before Docker can run' -Level WARN
            }
        } | Out-Null
    }

    if ($InstallDocker -and -not $dockerPresent) {
        Invoke-RsStep -Name 'Installing Docker Desktop' -Action {
            Install-RsDockerDesktop -ProjectRoot $ProjectRoot -HardwareProfilePath $HardwareProfile `
                                    -OfflineOnly:$OfflineOnly | Out-Null
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
# 11. Shortcut
# --------------------------------------------------------------------------

if (-not $SkipShortcut) {
    Invoke-RsStep -Name 'Creating the Desktop shortcut' -Action {
        Install-RsShortcuts -ProjectRoot $ProjectRoot -RuntimeMode $effectiveRuntime | Out-Null
    } | Out-Null
}

# --------------------------------------------------------------------------
# 12. Reboot handling
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
# 13. Final report
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
Write-RsLog "Setup profile   : $($plan.Profile) ($($plan.Reason))"
Write-RsLog "Runtime mode    : $effectiveRuntime$(if ($nativeReason) { " - $nativeReason" })"
Write-RsLog "Working folder  : $(if ($workspace) { $workspace } else { 'NOT CREATED' })"
Write-RsLog "Python          : $(if ($after.PythonPath) { "$($after.PythonPath) ($($after.PythonVersion))" } else { 'MISSING' })"
Write-RsLog "Desktop UI env  : $(if ($after.Venvs.'.venv-ui') { 'ready' } else { 'MISSING' })"
$uiVerdict = (Get-RsSummary)['uiLaunchOk']
Write-RsLog "Command Center  : $(if ($uiVerdict) { 'starts cleanly' } else { 'DID NOT START - see the traceback above' })"
Write-RsLog "Gateway env     : $(if ($after.Venvs.'.venv-actions') { 'ready' } else { 'missing' })"
if ($effectiveRuntime -eq 'container') {
    Write-RsLog "Docker Desktop  : $(if ($after.DockerInstalled) { 'installed' } else { 'not installed' })"
    Write-RsLog "Docker engine   : $(if ($after.DockerRunning) { 'running' } else { 'not running' })"
} else {
    Write-RsLog 'Backend         : native (embedded vector store, no Docker required)'
}
Write-RsLog "Node.js         : $(if ($after.NodePath) { $after.NodePath } else { 'not installed (optional)' })"

$sum = Get-RsSummary
$lmUrl = if ($sum['lmStudioUrl']) { $sum['lmStudioUrl'] } else { '(not configured)' }
Write-RsLog "LM Studio       : $lmUrl$(if ($sum['lmStudioReachable']) { ' - reachable' } else { ' - not answering yet' })"
if ($sum['lmStudioModel']) {
    Write-RsLog "LM Studio model : $($sum['lmStudioModel'])"
} elseif ($sum['lmStudioReachable']) {
    Write-RsLog 'LM Studio model : none loaded - load one in LM Studio' -Level WARN
}
Write-RsLog "Visual effects  : $(if ($sum['uiEffects']) { $sum['uiEffects'] } else { 'reduced' })"
if ($plan.Profile -eq 'cuda') {
    if ($sum['torchCudaUsable']) {
        Write-RsLog "GPU acceleration: $($sum['torchDetail'])"
    } else {
        Write-RsLog "GPU acceleration: NOT WORKING - $(if ($sum['torchDetail']) { $sum['torchDetail'] } else { 'not verified' })" -Level WARN
    }
}
if (-not $sum['lmStudioReachable']) {
    Write-RsLog '  Start LM Studio, switch on its local server (Developer tab), then use' -Level INFO
    Write-RsLog '  Settings -> LM Studio in RedSight to test and pick a model.' -Level INFO
}

if ($warnings.Count) {
    Write-RsLog ''
    Write-RsLog "$($warnings.Count) item(s) need attention:" -Level WARN
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
    $start = Get-RsLauncherPath -ProjectRoot $ProjectRoot -Mode $effectiveRuntime
    if ($start) {
        Write-RsLog "launching RedSight ($start)" -Level STEP
        Start-Process -FilePath (Get-RsPowerShellExe) `
                      -ArgumentList @('-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $start) | Out-Null
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
