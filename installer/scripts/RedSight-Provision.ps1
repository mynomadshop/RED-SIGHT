<#
    RedSight-Provision.ps1

    Everything that turns a generic RedSight install into one configured for
    THIS machine and THIS user:

      * setup profiles - "cuda" (NVIDIA local inference) vs "api" (laptop, cloud
        providers), which decide the Python wheels that get downloaded
      * the RedSight working directory, created and wired into .env
      * the AI provider and its API key, written where the Settings dialog reads
      * runtime mode - containers when the machine can run WSL2/Docker, native
        (embedded Qdrant, backend in-process) when it cannot
      * MCP server registration from a directory or config file

    Dot-sourced by RedSight-Preflight.ps1.
#>

Set-StrictMode -Version Latest

# --------------------------------------------------------------------------
# .env editing
# --------------------------------------------------------------------------

function Set-RsEnvValue {
    <#
        Sets KEY=VALUE in a dotenv file, replacing an existing assignment in
        place and appending otherwise. Comments, ordering and unrelated keys are
        preserved, so a user's edits survive a repair run.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Key,
        [Parameter(Mandatory)][AllowEmptyString()][string]$Value
    )

    $lines = @()
    if (Test-Path -LiteralPath $Path) {
        $lines = @(Get-Content -LiteralPath $Path -ErrorAction SilentlyContinue)
    } else {
        New-Item -ItemType Directory -Path (Split-Path -Parent $Path) -Force -ErrorAction SilentlyContinue | Out-Null
    }

    $pattern = '^\s*' + [regex]::Escape($Key) + '\s*='
    $replaced = $false
    $out = New-Object System.Collections.Generic.List[string]
    foreach ($line in $lines) {
        if (-not $replaced -and $line -match $pattern) {
            $out.Add("$Key=$Value")
            $replaced = $true
        } else {
            $out.Add($line)
        }
    }
    if (-not $replaced) { $out.Add("$Key=$Value") }

    # UTF-8 without a BOM: Windows PowerShell 5.1's -Encoding utf8 adds one, and a
    # BOM in front of the first key trips dotenv parsers and the Windows INI API.
    [System.IO.File]::WriteAllLines($Path, $out.ToArray(), (New-Object System.Text.UTF8Encoding($false)))
    return $replaced
}

function Get-RsEnvValue {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$Key)
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    foreach ($line in @(Get-Content -LiteralPath $Path -ErrorAction SilentlyContinue)) {
        if ($line -match ('^\s*' + [regex]::Escape($Key) + '\s*=\s*(.*)$')) {
            return $Matches[1].Trim()
        }
    }
    return $null
}

# --------------------------------------------------------------------------
# Working directory
# --------------------------------------------------------------------------

function Initialize-RsWorkspace {
    <#
        Creates the RedSight working directory and records it in .env.

        This is where the agent reads and writes by default, so it lives under
        the user's profile rather than inside Program Files: the application
        directory is not user-writable on a normal install.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$ProjectRoot,
        [string]$WorkspaceDir,
        [switch]$NativeMode
    )

    if (-not $WorkspaceDir) {
        $base = if ($env:USERPROFILE) { $env:USERPROFILE } else { [Environment]::GetFolderPath('UserProfile') }
        if (-not $base) { $base = $ProjectRoot }
        $WorkspaceDir = Join-Path $base 'RedSight'
    }

    $subdirs = @('workspace', 'projects', 'inbox', 'outputs', 'memory', 'logs', 'mcp', 'data')
    foreach ($sub in @('') + $subdirs) {
        $p = if ($sub) { Join-Path $WorkspaceDir $sub } else { $WorkspaceDir }
        if (-not (Test-Path -LiteralPath $p)) {
            New-Item -ItemType Directory -Path $p -Force -ErrorAction SilentlyContinue | Out-Null
        }
    }

    # Prove it is actually writable before advertising it to the app.
    $probe = Join-Path $WorkspaceDir '.redsight-write-test'
    try {
        Set-Content -LiteralPath $probe -Value 'ok' -Encoding ascii -ErrorAction Stop
        Remove-Item -LiteralPath $probe -Force -ErrorAction SilentlyContinue
    } catch {
        throw "the RedSight working directory is not writable: $WorkspaceDir ($($_.Exception.Message))"
    }

    $envFile = Join-Path $ProjectRoot '.env'
    Set-RsEnvValue -Path $envFile -Key 'REDSIGHT_WORKSPACE' -Value $WorkspaceDir | Out-Null
    Set-RsEnvValue -Path $envFile -Key 'REDSIGHT_WORKING_DIR' -Value (Join-Path $WorkspaceDir 'workspace') | Out-Null
    Set-RsEnvValue -Path $envFile -Key 'REDSIGHT_OUTPUT_DIR' -Value (Join-Path $WorkspaceDir 'outputs') | Out-Null
    Set-RsEnvValue -Path $envFile -Key 'REDSIGHT_MCP_DIR' -Value (Join-Path $WorkspaceDir 'mcp') | Out-Null

    # In native mode the backend runs on the host, so its data root must be a
    # real host path. In container mode the compose file supplies /data inside
    # the container and RED_SIGHT_DATA_ROOT is left alone.
    if ($NativeMode) {
        Set-RsEnvValue -Path $envFile -Key 'RED_SIGHT_DATA_ROOT' -Value (Join-Path $WorkspaceDir 'data') | Out-Null
    }

    # A short README so the folder is self-explanatory when a user finds it.
    $readme = Join-Path $WorkspaceDir 'README.txt'
    if (-not (Test-Path -LiteralPath $readme)) {
        @(
            'RedSight working directory',
            '==========================',
            '',
            'This folder is where RedSight reads and writes by default.',
            '',
            '  workspace\  the agent''s default working directory',
            '  projects\   your project folders',
            '  inbox\      drop files here to make them available to RedSight',
            '  outputs\    generated files, reports and exports',
            '  memory\     conversation memory and vector index data',
            '  mcp\        MCP server definitions (see Settings -> MCP Servers)',
            '  logs\       runtime logs',
            '',
            'You can move this folder: update REDSIGHT_WORKSPACE in the .env file',
            'inside the RedSight installation directory, then restart RedSight.'
        ) | Set-Content -LiteralPath $readme -Encoding utf8
    }

    Write-RsLog "working directory ready: $WorkspaceDir" -Level OK
    return $WorkspaceDir
}

# --------------------------------------------------------------------------
# Setup profiles and dependency selection
# --------------------------------------------------------------------------

function Get-RsDependencyPlan {
    <#
        Chooses the Python packages to install for this machine.

        The point is to never download CUDA builds for a computer that cannot
        use them. The CUDA build of torch alone is roughly 2.5 GB of GPU runtime
        libraries; the CPU build is about 200 MB. On a laptop with no NVIDIA
        driver the CUDA build is not merely wasted, it fails to load.

        Returns PreInstalls (installed first, so later resolution sees the
        chosen torch already satisfied) plus the profile decision and why.
    #>
    [CmdletBinding()]
    param(
        [ValidateSet('auto', 'cuda', 'api')][string]$SetupProfile = 'auto',
        $Hardware
    )

    $reason = ''
    $effective = $SetupProfile

    $cudaCapable = $false
    $vram = 0.0
    if ($Hardware) {
        $cudaCapable = [bool]$Hardware.gpu.cudaCapable
        $vram = [double]$Hardware.gpu.maxVramGB
    }

    if ($SetupProfile -eq 'auto') {
        if ($cudaCapable -and $vram -ge 4) {
            $effective = 'cuda'
            $reason = "an NVIDIA GPU with $vram GB of VRAM and a working driver was detected"
        } else {
            $effective = 'api'
            $reason = if ($Hardware -and $Hardware.gpu.hasNvidiaHardware) {
                'an NVIDIA GPU is present but its driver did not respond, so CUDA packages would not load'
            } else {
                'no CUDA-capable GPU was detected'
            }
        }
    } elseif ($SetupProfile -eq 'cuda' -and -not $cudaCapable) {
        # Honour the explicit request but say plainly that it will not accelerate.
        $reason = 'CUDA was selected explicitly, but no working NVIDIA driver was detected on this machine'
    } else {
        $reason = "the $SetupProfile profile was selected explicitly"
    }

    $preInstalls = New-Object System.Collections.Generic.List[object]
    if ($effective -eq 'cuda') {
        # The documented PyTorch install form: its wheel index also carries the
        # transitive dependencies, so --index-url alone is correct here.
        $preInstalls.Add(@{
            Label = 'PyTorch (CUDA 12.4 build)'
            Args  = @('torch', '--index-url', 'https://download.pytorch.org/whl/cu124')
        })
        $preInstalls.Add(@{ Label = 'onnxruntime-gpu'; Args = @('onnxruntime-gpu') })
    } else {
        $preInstalls.Add(@{
            Label = 'PyTorch (CPU build)'
            Args  = @('torch', '--index-url', 'https://download.pytorch.org/whl/cpu')
        })
        $preInstalls.Add(@{ Label = 'onnxruntime (CPU)'; Args = @('onnxruntime') })
    }

    return [pscustomobject]@{
        Profile     = $effective
        Requested   = $SetupProfile
        Reason      = $reason
        PreInstalls = $preInstalls.ToArray()
        CudaCapable = $cudaCapable
        VramGB      = $vram
    }
}

# --------------------------------------------------------------------------
# AI provider configuration
# --------------------------------------------------------------------------

# Must match app/ui/action_palette_stage105.py.
$script:RsProviders = @('lmstudio', 'openai', 'gemini', 'xai', 'anthropic', 'custom')
$script:RsProviderDefaultModels = @{
    lmstudio  = ''
    openai    = 'gpt-5.6-terra'
    gemini    = 'gemini-3.7-flash'
    xai       = 'grok-4.6'
    anthropic = 'claude-sonnet-5'
    custom    = ''
}

function Get-RsSettingsDir {
    [CmdletBinding()] param()
    $base = Get-RsLocalAppData
    return (Join-Path $base 'RedSight\settings')
}

function Protect-RsSecret {
    <#
        Encrypts a secret exactly the way the RedSight Settings dialog does:
        Windows DPAPI in CurrentUser scope, base64-encoded. That way a key set
        during installation is readable by the app and can be changed later in
        Settings without a format mismatch.
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Value)

    Add-Type -AssemblyName System.Security -ErrorAction SilentlyContinue
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($Value)
    $protected = [System.Security.Cryptography.ProtectedData]::Protect(
        $bytes, $null, [System.Security.Cryptography.DataProtectionScope]::CurrentUser)
    return [Convert]::ToBase64String($protected)
}

function Set-RsProviderConfig {
    <#
        Writes the chosen AI provider, model and API key into the same files the
        Settings dialog uses:

            %LOCALAPPDATA%\RedSight\settings\provider.json          (plain)
            %LOCALAPPDATA%\RedSight\settings\provider-secrets.json  (DPAPI)

        Returns $true when the key was stored encrypted.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][ValidateSet('lmstudio', 'openai', 'gemini', 'xai', 'anthropic', 'custom')]
        [string]$Provider,
        [string]$ApiKey,
        [string]$Model,
        [string]$BaseUrl
    )

    $dir = Get-RsSettingsDir
    New-Item -ItemType Directory -Path $dir -Force -ErrorAction SilentlyContinue | Out-Null
    $configFile = Join-Path $dir 'provider.json'
    $secretFile = Join-Path $dir 'provider-secrets.json'

    # Preserve any models the user already configured for other providers.
    $models = @{}
    foreach ($slug in $script:RsProviders) { $models[$slug] = [string]$script:RsProviderDefaultModels[$slug] }
    $customBase = ''
    if (Test-Path -LiteralPath $configFile) {
        try {
            $existing = Get-Content -LiteralPath $configFile -Raw | ConvertFrom-Json
            foreach ($slug in $script:RsProviders) {
                $p = $existing.models.PSObject.Properties[$slug]
                if ($p -and $p.Value) { $models[$slug] = [string]$p.Value }
            }
            $cb = $existing.PSObject.Properties['custom_base_url']
            if ($cb -and $cb.Value) { $customBase = [string]$cb.Value }
        } catch {
            Write-RsLog 'existing provider.json was unreadable and will be rewritten' -Level WARN
        }
    }

    if ($Model) { $models[$Provider] = $Model }
    if ($BaseUrl) { $customBase = $BaseUrl }

    $config = [ordered]@{
        version         = 1
        active_provider = $Provider
        models          = $models
        custom_base_url = $customBase
    }
    ($config | ConvertTo-Json -Depth 5) | Set-Content -LiteralPath $configFile -Encoding utf8
    Write-RsLog "provider set to $Provider (config: $configFile)" -Level OK

    if (-not $ApiKey -or $Provider -eq 'lmstudio') { return $false }

    try {
        $store = @{}
        if (Test-Path -LiteralPath $secretFile) {
            try {
                $raw = Get-Content -LiteralPath $secretFile -Raw | ConvertFrom-Json
                foreach ($prop in $raw.PSObject.Properties) { $store[$prop.Name] = [string]$prop.Value }
            } catch { }
        }
        $store[$Provider] = Protect-RsSecret -Value $ApiKey
        ($store | ConvertTo-Json -Depth 3) | Set-Content -LiteralPath $secretFile -Encoding utf8
        Write-RsLog "API key for $Provider stored encrypted (DPAPI, current user)" -Level OK
        return $true
    } catch {
        Write-RsLog "could not store the API key: $($_.Exception.Message)" -Level WARN
        Write-RsLog '    add it in RedSight Settings -> AI Provider after setup finishes' -Level INFO
        return $false
    }
}

# --------------------------------------------------------------------------
# MCP servers
# --------------------------------------------------------------------------

function Install-RsMcpConfig {
    <#
        Registers MCP servers from a path the user supplies. Accepts either a
        directory (every *.json / *.yaml / *.yml inside it is taken as a server
        definition set) or a single config file, and merges them into the
        workspace MCP directory that the app reads.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$SourcePath,
        [Parameter(Mandatory)][string]$WorkspaceDir
    )

    if (-not (Test-Path -LiteralPath $SourcePath)) {
        throw "MCP source path not found: $SourcePath"
    }

    $mcpDir = Join-Path $WorkspaceDir 'mcp'
    New-Item -ItemType Directory -Path $mcpDir -Force -ErrorAction SilentlyContinue | Out-Null

    $files = @()
    if ((Get-Item -LiteralPath $SourcePath).PSIsContainer) {
        $files = @(Get-ChildItem -LiteralPath $SourcePath -File -ErrorAction SilentlyContinue |
                   Where-Object { $_.Extension -in @('.json', '.yaml', '.yml') })
    } else {
        $files = @(Get-Item -LiteralPath $SourcePath)
    }

    if (-not $files.Count) {
        throw "no MCP definition files (*.json, *.yaml, *.yml) were found at $SourcePath"
    }

    $copied = 0
    foreach ($f in $files) {
        Copy-Item -LiteralPath $f.FullName -Destination (Join-Path $mcpDir $f.Name) -Force
        $copied++
        Write-RsLog "    registered MCP definitions from $($f.Name)" -Level DEBUG
    }
    Write-RsLog "registered $copied MCP definition file(s) in $mcpDir" -Level OK
    return $copied
}

# --------------------------------------------------------------------------
# Runtime mode
# --------------------------------------------------------------------------

function New-RsNativeLauncher {
    <#
        Writes START-REDSIGHT-NATIVE.ps1: a launcher that runs RedSight without
        Docker at all.

        RedSight's vector store already supports an embedded, in-process mode
        (QdrantClient(path=...)) and falls back to it when no server answers, and
        the FastAPI backend can be run directly by scripts/start.py. Together
        that means a machine which cannot run WSL2 - because virtualization is
        switched off in its firmware - can still run the whole product.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$ProjectRoot,
        [Parameter(Mandatory)][string]$WorkspaceDir
    )

    $launcher = Join-Path $ProjectRoot 'START-REDSIGHT-NATIVE.ps1'
    $content = @'
<#
    START-REDSIGHT-NATIVE.ps1

    Runs RedSight without Docker: the FastAPI backend runs directly in the
    RedSight Python environment and the vector store runs embedded, in-process.

    Generated by RedSight setup because this machine cannot run WSL2/Docker
    (hardware virtualization is unavailable). Re-run setup after enabling
    virtualization in the firmware to switch to the containerized backend.
#>

[CmdletBinding()]
param([switch]$NoUi, [int]$Port = 8000)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
Set-Location $Root

$LogDir = Join-Path $env:LOCALAPPDATA 'RedSight\logs'
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
$Log = Join-Path $LogDir ("native-{0}.log" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))

function Write-Line { param([string]$m) ; "$(Get-Date -Format s)  $m" | Tee-Object -FilePath $Log -Append }

$Python = Join-Path $Root '.venv-ui\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) {
    throw "RedSight Python environment not found at $Python. Run 'Repair RedSight setup' from the Start Menu."
}

# No Qdrant server runs in native mode: the store fails fast against the closed
# port and falls back to its embedded, in-process mode.
$env:REDSIGHT_API_URL = "http://127.0.0.1:$Port"
$env:REDSIGHT_API_BASE_URL = $env:REDSIGHT_API_URL
$env:API_BASE_URL = $env:REDSIGHT_API_URL
$env:REDSIGHT_RUNTIME_MODE = 'native'

Write-Line "starting the RedSight backend natively on port $Port"
$backend = Start-Process -FilePath $Python -PassThru -WindowStyle Hidden `
    -ArgumentList @('scripts\start.py', '--host', '127.0.0.1', '--port', "$Port") `
    -RedirectStandardOutput (Join-Path $LogDir 'native-backend.out.log') `
    -RedirectStandardError  (Join-Path $LogDir 'native-backend.err.log')
Write-Line "backend pid $($backend.Id)"

# Wait for the health endpoint rather than sleeping a fixed amount.
$ready = $false
$deadline = (Get-Date).AddSeconds(180)
while ((Get-Date) -lt $deadline) {
    if ($backend.HasExited) {
        Write-Line "backend exited early with code $($backend.ExitCode); see native-backend.err.log"
        break
    }
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/v1/health" -TimeoutSec 3 -UseBasicParsing
        if ($resp.StatusCode -eq 200) { $ready = $true; break }
    } catch { }
    Start-Sleep -Seconds 2
}
Write-Line ("backend ready: {0}" -f $ready)

# The action/memory gateway is optional; start it when its environment exists.
$GatewayPython = Join-Path $Root '.venv-actions\Scripts\python.exe'
$Gateway = Join-Path $Root 'redsight_actions\gateway_stage10.py'
if ((Test-Path -LiteralPath $GatewayPython) -and (Test-Path -LiteralPath $Gateway)) {
    Write-Line 'starting the action/memory gateway'
    Start-Process -FilePath $GatewayPython -ArgumentList @($Gateway) -WindowStyle Hidden | Out-Null
}

if (-not $NoUi) {
    $Launcher = Join-Path $Root 'launch_redsight_command_center.py'
    if (Test-Path -LiteralPath $Launcher) {
        Write-Line 'opening the Command Center'
        $Pythonw = Join-Path $Root '.venv-ui\Scripts\pythonw.exe'
        if (-not (Test-Path -LiteralPath $Pythonw)) { $Pythonw = $Python }
        # Run through python.exe, not pythonw.exe, when it fails: pythonw
        # discards the traceback and the shortcut appears to do nothing.
        & $Pythonw $Launcher
        if ($LASTEXITCODE -ne 0) {
            Write-Line "Command Center exited with code $LASTEXITCODE - re-running with output captured"
            $err = Join-Path $LogDir 'ui-error.log'
            & $Python $Launcher *>> $err
            Add-Type -AssemblyName PresentationFramework
            [System.Windows.MessageBox]::Show(
                "RedSight could not open the Command Center.`n`nDetails:`n$err`n`nRun 'RedSight health check' from the Start Menu for a diagnosis.",
                'RedSight') | Out-Null
        }
    } else {
        Write-Line "Command Center launcher not found at $Launcher"
        Add-Type -AssemblyName PresentationFramework
        [System.Windows.MessageBox]::Show(
            "RedSight is not fully installed: $Launcher is missing.`n`nRun 'Repair RedSight setup' from the Start Menu.",
            'RedSight') | Out-Null
    }
}
'@
    Set-Content -LiteralPath $launcher -Value $content -Encoding utf8
    Write-RsLog "native launcher written to $launcher" -Level OK
    return $launcher
}

function Set-RsRuntimeMode {
    <#
        Records whether RedSight runs its backend in containers or natively, and
        makes sure the matching launcher exists.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$ProjectRoot,
        [Parameter(Mandatory)][ValidateSet('container', 'native')][string]$Mode,
        [Parameter(Mandatory)][string]$WorkspaceDir,
        [string]$Reason = ''
    )

    $envFile = Join-Path $ProjectRoot '.env'
    Set-RsEnvValue -Path $envFile -Key 'REDSIGHT_RUNTIME_MODE' -Value $Mode | Out-Null

    if ($Mode -eq 'native') {
        New-RsNativeLauncher -ProjectRoot $ProjectRoot -WorkspaceDir $WorkspaceDir | Out-Null
        # QDRANT_URL is deliberately left as shipped. The store tries the server,
        # fails fast against a closed port and falls back to its embedded mode,
        # which is the application's own designed behaviour; feeding an empty URL
        # into its connection code is a change of contract for no benefit.
        Write-RsLog "runtime mode: native (no Docker required)$(if ($Reason) { " - $Reason" })" -Level OK
    } else {
        Write-RsLog 'runtime mode: containerized backend (Docker + WSL2)' -Level OK
    }
    return $Mode
}

function Get-RsLauncherPath {
    <# The script the shortcuts should point at for the current runtime mode. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$ProjectRoot, [Parameter(Mandatory)][string]$Mode)

    if ($Mode -eq 'native') {
        $native = Join-Path $ProjectRoot 'START-REDSIGHT-NATIVE.ps1'
        if (Test-Path -LiteralPath $native) { return $native }
    }
    foreach ($candidate in @('LAUNCH-REDSIGHT-DESKTOP.ps1', 'START-REDSIGHT.ps1')) {
        $p = Join-Path $ProjectRoot $candidate
        if (Test-Path -LiteralPath $p) { return $p }
    }
    return $null
}
