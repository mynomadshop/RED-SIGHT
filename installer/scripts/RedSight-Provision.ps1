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
      * the runtime configuration module, copied into each virtualenv so every
        RedSight process reads the same LM Studio endpoint

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
    <#
        Reads one key out of a .env file the way python-dotenv does.

        The raw right-hand side is not the value: `MODE=native  # set by setup`
        would otherwise yield "native  # set by setup", and a quoted path would
        keep its quotes. Callers compare these against literals ('native',
        'container') and join them into paths, so both would silently fail.

        Commented-out and `export `-prefixed lines are handled the same way
        python-dotenv handles them: skipped, and stripped, respectively.
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$Key)
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    foreach ($line in @(Get-Content -LiteralPath $Path -ErrorAction SilentlyContinue)) {
        if ($line -notmatch ('^\s*(?:export\s+)?' + [regex]::Escape($Key) + '\s*=\s*(.*)$')) { continue }
        $value = $Matches[1].Trim()

        if ($value -match '^"([^"]*)"') { return $Matches[1] }      # "quoted value"  # comment
        if ($value -match "^'([^']*)'") { return $Matches[1] }      # 'quoted value'  # comment

        # Unquoted: a # ends the value only when whitespace precedes it, so a
        # value that is itself a fragment or colour (#free-form) survives.
        if ($value -match '^(.*?)\s+#') { $value = $Matches[1] }
        return $value.Trim()
    }
    return $null
}

# --------------------------------------------------------------------------
# Working directory
# --------------------------------------------------------------------------

function Test-RsIsAppTree {
    <#
        Does this directory hold a RedSight installation?

        Used to keep the working directory out of one. The launcher is the
        distinguishing file: a workspace never contains it, and every install
        does.
    #>
    [CmdletBinding()]
    param([string]$Path)

    if (-not $Path -or -not (Test-Path -LiteralPath $Path)) { return $false }
    foreach ($marker in @('launch_redsight_command_center.py', 'docker-compose.yml', 'pyproject.toml')) {
        if (Test-Path -LiteralPath (Join-Path $Path $marker)) { return $true }
    }
    return $false
}

function Initialize-RsWorkspace {
    <#
        Creates the RedSight working directory and records it in .env.

        This is where the agent reads and writes by default, so it lives under
        the user's profile rather than inside Program Files: the application
        directory is not user-writable on a normal install.

        The default is <UserProfile>\RedSight, which is also exactly where a
        hand-installed RedSight usually lives. Putting a workspace inside an
        application tree mixes the two - workspace subdirectories land among the
        source, and a later path rewrite has two roots to confuse - so a
        directory that looks like an install is declined in favour of
        <UserProfile>\RedSight-Data.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$ProjectRoot,
        [string]$WorkspaceDir,
        [switch]$NativeMode
    )

    $installRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path.TrimEnd('\')
    $base = if ($env:USERPROFILE) { $env:USERPROFILE } else { [Environment]::GetFolderPath('UserProfile') }
    if (-not $base) { $base = $installRoot }

    if (-not $WorkspaceDir) { $WorkspaceDir = Join-Path $base 'RedSight' }

    $resolved = $WorkspaceDir
    try { if (Test-Path -LiteralPath $WorkspaceDir) { $resolved = (Resolve-Path -LiteralPath $WorkspaceDir).Path } } catch { }
    $resolved = "$resolved".TrimEnd('\')

    $rejection = ''
    if ($resolved -eq $installRoot) {
        $rejection = 'it is the RedSight installation directory itself'
    } elseif ($resolved.ToLowerInvariant().StartsWith(($installRoot + [System.IO.Path]::DirectorySeparatorChar).ToLowerInvariant()) -or
              $resolved.ToLowerInvariant().StartsWith(($installRoot + '\').ToLowerInvariant())) {
        $rejection = 'it is inside the RedSight installation directory'
    } elseif (Test-RsIsAppTree -Path $resolved) {
        $rejection = 'it already holds a RedSight installation'
    }

    if ($rejection) {
        $fallback = Join-Path $base 'RedSight-Data'
        if ((Test-RsIsAppTree -Path $fallback) -or ($fallback.TrimEnd('\') -eq $installRoot)) {
            $fallback = Join-Path $base 'RedSight-Workspace'
        }
        Write-RsLog "the requested working directory cannot be used - $rejection : $WorkspaceDir" -Level WARN
        Write-RsLog "using $fallback instead" -Level WARN
        $WorkspaceDir = $fallback
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

# PyTorch wheel indexes, by the GPU architecture they carry kernels for.
#
# This mapping is the difference between "CUDA is installed" and "CUDA works".
# A wheel contains compiled kernels for a fixed set of architectures; asking a
# cu124 build to run on sm_120 - any RTX 50-series card - gets the driver's
# "no kernel image is available for execution on the device", not a fallback.
# Blackwell support arrived in PyTorch 2.7 on the CUDA 12.8 index.
$script:RsTorchIndexes = @(
    @{ MinCap = 12.0; Index = 'https://download.pytorch.org/whl/cu128'; Spec = 'torch>=2.7'
       Label = 'PyTorch (CUDA 12.8 build, Blackwell/sm_120 kernels)' }
    @{ MinCap = 0.0;  Index = 'https://download.pytorch.org/whl/cu124'; Spec = 'torch'
       Label = 'PyTorch (CUDA 12.4 build)' }
)

function Get-RsTorchPlan {
    <#
        The PyTorch wheel index for a GPU compute capability.

        An unknown capability keeps the long-standing cu124 default: it covers
        every NVIDIA generation from Maxwell to Hopper, and guessing the newer
        index for a card that does not need it would download a larger payload
        for no gain.
    #>
    [CmdletBinding()]
    param([string]$ComputeCapability = '')

    # The single-argument TryParse overload parses in the current culture. On a
    # machine set to a comma-decimal locale (de-DE, fr-FR, pt-BR) the dot is a
    # thousands separator, so nvidia-smi's "8.9" parses as 89 - successfully,
    # and silently. Every GPU then clears the highest MinCap and is handed the
    # newest CUDA wheel, which for an Ada or Ampere card is the wrong build.
    # nvidia-smi always reports a dot, so parse invariantly.
    $cap = 0.0
    [void][double]::TryParse("$ComputeCapability",
                             [System.Globalization.NumberStyles]::Float,
                             [System.Globalization.CultureInfo]::InvariantCulture,
                             [ref]$cap)

    foreach ($entry in $script:RsTorchIndexes) {
        if ($cap -ge [double]$entry.MinCap) { return [pscustomobject]$entry }
    }
    return [pscustomobject]$script:RsTorchIndexes[-1]
}

function Get-RsDependencyPlan {
    <#
        Chooses the Python packages to install for this machine.

        The point is to never download CUDA builds for a computer that cannot
        use them. The CUDA build of torch alone is roughly 2.5 GB of GPU runtime
        libraries; the CPU build is about 200 MB. On a laptop with no NVIDIA
        driver the CUDA build is not merely wasted, it fails to load.

        Which CUDA build matters as much as whether: see $script:RsTorchIndexes.

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
    $computeCap = ''
    if ($Hardware) {
        $cudaCapable = [bool]$Hardware.gpu.cudaCapable
        $vram = [double]$Hardware.gpu.maxVramGB
        if ($Hardware.gpu.PSObject.Properties['maxComputeCap']) {
            $computeCap = "$($Hardware.gpu.maxComputeCap)"
        }
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
    $torch = $null
    if ($effective -eq 'cuda') {
        $torch = Get-RsTorchPlan -ComputeCapability $computeCap
        # The documented PyTorch install form: its wheel index also carries the
        # transitive dependencies, so --index-url alone is correct here. The
        # version floor matters: pip reports an already-installed torch as
        # satisfied, so without it a machine carrying the wrong CUDA build keeps
        # it forever.
        $preInstalls.Add(@{
            Label = $torch.Label
            Args  = @($torch.Spec, '--index-url', $torch.Index)
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
        Profile      = $effective
        Requested    = $SetupProfile
        Reason       = $reason
        PreInstalls  = $preInstalls.ToArray()
        CudaCapable  = $cudaCapable
        VramGB       = $vram
        ComputeCap   = $computeCap
        TorchIndex   = if ($torch) { $torch.Index } else { '' }
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
    # Written without a BOM: the application reads these with Python's json,
    # and json.loads chokes on a leading U+FEFF. Windows PowerShell 5.1's
    # -Encoding utf8 always emits one.
    Write-RsUtf8File -Path $configFile -Content ($config | ConvertTo-Json -Depth 5)
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
        Write-RsUtf8File -Path $secretFile -Content ($store | ConvertTo-Json -Depth 3)
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

function Install-RsRuntimeBootstrap {
    <#
        Puts redsight_bootstrap.py on the import path of a virtualenv, and adds
        a .pth file that imports it at interpreter startup.

        This is what makes the LM Studio endpoint reach the backend. The
        application reads its endpoint through app/config/settings.py, whose
        Settings class uses env_prefix RED_SIGHT_, and nothing in the codebase
        calls load_dotenv - so a plain LM_STUDIO_BASE_URL line in .env is never
        seen. Only LmStudioConfig's own validator reads that name, and it reads
        it from the real process environment. Importing the module through a
        .pth puts it there before any application code runs, whichever way the
        process was started.

        A .pth is used rather than sitecustomize.py so nothing another package
        installed gets overwritten.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$VenvPython,
        [Parameter(Mandatory)][string]$ProjectRoot
    )

    $source = Join-Path $ProjectRoot 'redsight_bootstrap.py'
    if (-not (Test-Path -LiteralPath $source)) {
        Write-RsLog "redsight_bootstrap.py is not in the payload - the LM Studio endpoint will not reach the backend automatically" -Level WARN
        return $false
    }
    if (-not (Test-Path -LiteralPath $VenvPython)) { return $false }

    $sitePackages = Join-Path (Split-Path -Parent (Split-Path -Parent $VenvPython)) 'Lib\site-packages'
    if (-not (Test-Path -LiteralPath $sitePackages)) {
        # Ask the interpreter rather than guessing at a non-standard layout.
        $r = Invoke-RsProcess -FilePath $VenvPython -TimeoutSeconds 60 -Quiet `
                              -Arguments @('-c', 'import sysconfig;print(sysconfig.get_paths()["purelib"])')
        if ($r.ExitCode -eq 0) { $sitePackages = $r.StdOut.Trim() }
    }
    if (-not $sitePackages -or -not (Test-Path -LiteralPath $sitePackages)) {
        Write-RsLog "could not locate site-packages for $VenvPython" -Level WARN
        return $false
    }

    Copy-Item -LiteralPath $source -Destination (Join-Path $sitePackages 'redsight_bootstrap.py') -Force

    # A .pth line beginning with "import" is executed by site.py at startup.
    $pth = Join-Path $sitePackages 'redsight_bootstrap.pth'
    [System.IO.File]::WriteAllText($pth, "import redsight_bootstrap$([Environment]::NewLine)",
                                   (New-Object System.Text.UTF8Encoding($false)))

    Write-RsLog "runtime configuration installed into $sitePackages" -Level OK
    return $true
}

function New-RsNativeLauncher {
    <#
        Writes START-REDSIGHT-NATIVE.ps1: a launcher that runs RedSight without
        Docker at all.

        RedSight's vector store already supports an embedded, in-process mode
        (QdrantClient(path=...)) and falls back to it when no server answers, and
        the FastAPI backend can be run directly by scripts/start.py. Together
        that means a machine which cannot run WSL2 - because virtualization is
        switched off in its firmware - can still run the whole product.

        Three services have to be up, not one. The desktop UI sends every chat
        through the action/memory gateway on 127.0.0.1:8765 (/memory/build, then
        /memory/commit) and reads its memory indicator from
        /memory/status there, so with the gateway down the UI reports memory as
        missing and no query ever reaches a model. The gateway is an ASGI app:
        running gateway_stage10.py as a script starts nothing.
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
param([switch]$NoUi, [int]$Port = 8000, [int]$GatewayPort = 8765)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
Set-Location $Root

$LogDir = Join-Path $env:LOCALAPPDATA 'RedSight\logs'
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
$Log = Join-Path $LogDir ("native-{0}.log" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))

function Write-Line { param([string]$m) ; "$(Get-Date -Format s)  $m" | Tee-Object -FilePath $Log -Append }

function Test-Endpoint {
    param([Parameter(Mandatory)][string]$Url, [int]$TimeoutSeconds = 3)
    try {
        # No proxy: a configured system proxy must not intercept a loopback call.
        $req = [System.Net.HttpWebRequest]::Create($Url)
        $req.Method = 'GET'
        $req.Timeout = $TimeoutSeconds * 1000
        $req.Proxy = $null
        $resp = $req.GetResponse()
        $code = [int]$resp.StatusCode
        $resp.Dispose()
        return ($code -ge 200 -and $code -lt 500)
    } catch {
        return $false
    }
}

function Wait-Endpoint {
    param(
        [Parameter(Mandatory)][string]$Url,
        [Parameter(Mandatory)][string]$Name,
        [int]$Seconds = 180,
        $Process
    )
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        if ($Process -and $Process.HasExited) {
            Write-Line "$Name exited early with code $($Process.ExitCode)"
            return $false
        }
        if (Test-Endpoint -Url $Url) { return $true }
        Start-Sleep -Seconds 2
    }
    return $false
}

$Python = Join-Path $Root '.venv-ui\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) {
    throw "RedSight Python environment not found at $Python. Run 'Repair RedSight setup' from the Start Menu."
}

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
# The LM Studio endpoint has to be in the real process environment: the backend
# reads it through a validator on os.environ, and nothing in the application
# loads .env. redsight_bootstrap holds the value setup recorded.

$env:PYTHONPATH = $null
$env:PYTHONHOME = $null
$env:PYTHONNOUSERSITE = '1'
$env:REDSIGHT_API_URL = "http://127.0.0.1:$Port"
$env:REDSIGHT_API_BASE_URL = $env:REDSIGHT_API_URL
$env:API_BASE_URL = $env:REDSIGHT_API_URL
$env:REDSIGHT_RUNTIME_MODE = 'native'

# Qt: PassThrough rounding keeps text crisp on fractional scaling instead of
# rounding the whole UI up to the next integer factor.
if (-not $env:QT_SCALE_FACTOR_ROUNDING_POLICY) { $env:QT_SCALE_FACTOR_ROUNDING_POLICY = 'PassThrough' }

$Applied = & $Python -c "import json,redsight_bootstrap as r;print(json.dumps(r.environment()))" 2>$null
if ($LASTEXITCODE -eq 0 -and $Applied) {
    try {
        $Parsed = $Applied | ConvertFrom-Json
        foreach ($entry in $Parsed.PSObject.Properties) {
            Set-Item -Path ("Env:" + $entry.Name) -Value ([string]$entry.Value)
        }
        Write-Line "LM Studio endpoint: $($env:LM_STUDIO_BASE_URL) model: $(if ($env:LM_STUDIO_MODEL) { $env:LM_STUDIO_MODEL } else { '(auto-detected at first request)' })"
    } catch {
        Write-Line "could not apply the recorded runtime configuration: $($_.Exception.Message)"
    }
} else {
    Write-Line 'the runtime configuration module is not installed; falling back to the local LM Studio default'
    if (-not $env:LM_STUDIO_BASE_URL) { $env:LM_STUDIO_BASE_URL = 'http://127.0.0.1:1234/v1' }
    if (-not $env:LM_BASE_URL) { $env:LM_BASE_URL = $env:LM_STUDIO_BASE_URL }
    if (-not $env:LM_STUDIO_URL) { $env:LM_STUDIO_URL = 'http://127.0.0.1:1234' }
}

# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------

if (Test-Endpoint -Url "http://127.0.0.1:$Port/api/v1/health") {
    Write-Line "the backend is already running on port $Port"
} else {
    Write-Line "starting the RedSight backend natively on port $Port"
    $StartScript = Join-Path $Root 'scripts\start.py'
    if (Test-Path -LiteralPath $StartScript) {
        $BackendArgs = @($StartScript, '--host', '127.0.0.1', '--port', "$Port")
    } else {
        # Same entry point the container image uses.
        $BackendArgs = @('-m', 'uvicorn', 'app.server:app', '--host', '127.0.0.1', '--port', "$Port")
    }
    $backend = Start-Process -FilePath $Python -PassThru -WindowStyle Hidden `
        -ArgumentList $BackendArgs -WorkingDirectory $Root `
        -RedirectStandardOutput (Join-Path $LogDir 'native-backend.out.log') `
        -RedirectStandardError  (Join-Path $LogDir 'native-backend.err.log')
    Write-Line "backend pid $($backend.Id)"
    $ready = Wait-Endpoint -Url "http://127.0.0.1:$Port/api/v1/health" -Name 'backend' -Seconds 180 -Process $backend
    Write-Line ("backend ready: {0}" -f $ready)
    if (-not $ready) { Write-Line 'see native-backend.err.log' }
}

# ---------------------------------------------------------------------------
# Action/memory gateway
# ---------------------------------------------------------------------------
# The UI's chat path is /memory/build here, then the backend, then
# /memory/commit here. Without this service there is no memory and no answer.

$GatewayPython = Join-Path $Root '.venv-actions\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $GatewayPython)) { $GatewayPython = $Python }
$GatewayModule = Join-Path $Root 'redsight_actions\gateway_stage10.py'
$GatewayHealth = "http://127.0.0.1:$GatewayPort/memory/status"

if (Test-Endpoint -Url $GatewayHealth) {
    Write-Line "the action/memory gateway is already running on port $GatewayPort"
} elseif (Test-Path -LiteralPath $GatewayModule) {
    Write-Line "starting the action/memory gateway on port $GatewayPort"
    # gateway_stage10 exposes an ASGI app, so it has to be served by uvicorn;
    # running the file as a script defines the app and exits.
    $gateway = Start-Process -FilePath $GatewayPython -PassThru -WindowStyle Hidden `
        -ArgumentList @('-m', 'uvicorn', 'redsight_actions.gateway_stage10:app',
                        '--host', '127.0.0.1', '--port', "$GatewayPort", '--log-level', 'warning') `
        -WorkingDirectory $Root `
        -RedirectStandardOutput (Join-Path $LogDir 'native-gateway.out.log') `
        -RedirectStandardError  (Join-Path $LogDir 'native-gateway.err.log')
    Write-Line "gateway pid $($gateway.Id)"
    $gatewayReady = Wait-Endpoint -Url $GatewayHealth -Name 'gateway' -Seconds 90 -Process $gateway
    Write-Line ("gateway ready: {0}" -f $gatewayReady)
    if (-not $gatewayReady) {
        Write-Line 'memory will show as missing in the UI; see native-gateway.err.log'
    }
} else {
    Write-Line "the action/memory gateway is not in this install ($GatewayModule)"
}

# ---------------------------------------------------------------------------
# Command Center
# ---------------------------------------------------------------------------

if (-not $NoUi) {
    $Launcher = Join-Path $Root 'launch_redsight_command_center.py'
    if (Test-Path -LiteralPath $Launcher) {
        Write-Line 'opening the Command Center'
        $Pythonw = Join-Path $Root '.venv-ui\Scripts\pythonw.exe'
        if (-not (Test-Path -LiteralPath $Pythonw)) { $Pythonw = $Python }
        # Start-Process -Wait, not the call operator: pythonw.exe is a GUI
        # subsystem binary, and PowerShell does not wait for those. `& $Pythonw`
        # returns the moment the process is created, leaving $LASTEXITCODE at 0
        # however the UI ends - so the diagnostic re-run below would never fire
        # and a UI that dies on an import error would just silently not appear.
        $ui = Start-Process -FilePath $Pythonw -ArgumentList @($Launcher) `
                            -WorkingDirectory $Root -Wait -PassThru
        $UiExit = $ui.ExitCode
        if ($UiExit -ne 0) {
            Write-Line "Command Center exited with code $UiExit - re-running with output captured"
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

        The mode is also written into the runtime configuration file, because it
        decides two things every RedSight process needs to agree on: whether the
        vector store runs embedded, and which LM Studio endpoint a container
        should use.
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

    # Recorded where the backend, the gateway and the UI all read it.
    $config = Read-RsLmStudioConfig
    $config['runtime_mode'] = $Mode
    $config['data_root'] = (Join-Path $ProjectRoot 'data')
    Save-RsLmStudioConfig -Config $config | Out-Null

    # The shipped launchers hard-assign the LM Studio variables, which would
    # override the recorded endpoint; both modes use one of them.
    Repair-RsAppLauncher -ProjectRoot $ProjectRoot `
                         -BaseUrl $config['base_url'] -Model $config['model'] | Out-Null

    if ($Mode -eq 'native') {
        New-RsNativeLauncher -ProjectRoot $ProjectRoot -WorkspaceDir $WorkspaceDir | Out-Null
        # QDRANT_URL is deliberately left as shipped. The store tries the server,
        # fails fast against a closed port and falls back to its embedded mode,
        # which is the application's own designed behaviour; feeding an empty URL
        # into its connection code is a change of contract for no benefit. What
        # the runtime configuration does add is VECTOR_BACKEND_EMBEDDED, so the
        # wasted lookup for the container hostname is skipped.
        Write-RsLog "runtime mode: native (no Docker required)$(if ($Reason) { " - $Reason" })" -Level OK
    } else {
        # The shipped compose files carry the author's own LAN address for LM
        # Studio, so a containerized backend would talk to someone else's
        # machine.
        Repair-RsComposeLmStudio -ProjectRoot $ProjectRoot `
                                 -BaseUrl $config['base_url'] -Model $config['model'] | Out-Null
        Write-RsLog 'runtime mode: containerized backend (Docker + WSL2)' -Level OK
    }
    return $Mode
}

function Get-RsLauncherPath {
    <#
        The script the shortcuts should point at for the current runtime mode.

        START-REDSIGHT.ps1 comes before LAUNCH-REDSIGHT-DESKTOP.ps1 because it
        is the one that starts the action/memory gateway on 127.0.0.1:8765.
        The desktop UI sends every chat through that gateway and reads its
        memory indicator from it, so a shortcut to the launcher that only starts
        Docker and the UI produces exactly the reported symptom: memory missing
        and no answer to a query.
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$ProjectRoot, [Parameter(Mandatory)][string]$Mode)

    # The dispatcher decides from the recorded runtime mode at launch time, so
    # a shortcut created before setup finished still points somewhere correct.
    $dispatcher = Join-Path $ProjectRoot 'scripts\windows\Start-RedSight.ps1'
    if (Test-Path -LiteralPath $dispatcher) { return $dispatcher }

    if ($Mode -eq 'native') {
        $native = Join-Path $ProjectRoot 'START-REDSIGHT-NATIVE.ps1'
        if (Test-Path -LiteralPath $native) { return $native }
    }
    foreach ($candidate in @('START-REDSIGHT.ps1', 'LAUNCH-REDSIGHT-DESKTOP.ps1')) {
        $p = Join-Path $ProjectRoot $candidate
        if (Test-Path -LiteralPath $p) { return $p }
    }
    return $null
}
