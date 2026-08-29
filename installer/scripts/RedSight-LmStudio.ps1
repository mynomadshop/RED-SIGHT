<#
    RedSight-LmStudio.ps1

    Makes the local LM Studio server reachable by every RedSight process.

    Why this file exists
    --------------------
    RedSight's backend reads its LM Studio endpoint through
    app/config/settings.py, whose Settings class uses env_prefix "RED_SIGHT_".
    Nothing in the application calls load_dotenv, so a plain
    LM_STUDIO_BASE_URL line in .env never reaches the backend: only
    LmStudioConfig's own model validator reads it, and it reads it from the
    real process environment. With no value there the field keeps its shipped
    default, http://host.docker.internal:1234/v1, which resolves only inside a
    container - so a native install silently talks to a host that does not
    exist while the Settings dialog's own connection test, which probes the
    endpoint directly, still reports success.

    The fix is a single machine-local file that both sides agree on:

        %LOCALAPPDATA%\RedSight\settings\lmstudio.json

    Setup writes it, the launcher exports it into the environment of the
    backend, the gateway and the UI, and the Stage 11.5 UI overlay reads and
    rewrites it from the Settings dialog.

    Every function is idempotent and safe to re-run.
#>

Set-StrictMode -Version Latest

# The endpoints worth probing when no working one is known yet. LM Studio's
# default is 1234; 1235 is what it moves to when 1234 is taken.
$script:RsLmDefaultUrls = @(
    'http://127.0.0.1:1234/v1',
    'http://localhost:1234/v1',
    'http://127.0.0.1:1235/v1'
)

# Every key the configuration file holds. Read and write both walk this list so
# a new setting cannot be persisted by one side and dropped by the other.
$script:RsLmConfigKeys = @('base_url', 'model', 'timeout_seconds', 'auto_start',
                           'data_root', 'runtime_mode', 'ui_effects')

# Model ids matching these are embedding/reranking models, not chat models.
$script:RsLmNonChatMarkers = @('embed', 'bge-', 'gte-', 'e5-', 'minilm', 'nomic-embed', 'rerank', 'clip')

function Get-RsLmStudioConfigPath {
    <# The file both the launcher and the UI read the LM Studio endpoint from. #>
    [CmdletBinding()] param()
    return (Join-Path (Get-RsLocalAppData) 'RedSight\settings\lmstudio.json')
}

function ConvertTo-RsLmBaseUrl {
    <#
        Normalises whatever the user typed into an OpenAI-compatible base URL.

        Accepts "127.0.0.1:1234", "http://host:1234", ".../v1",
        ".../v1/models" and ".../v1/chat/completions".
    #>
    [CmdletBinding()]
    param([string]$Value)

    $text = ("$Value").Trim()
    if (-not $text) { return '' }
    if ($text -notmatch '^[a-zA-Z][a-zA-Z0-9+.-]*://') { $text = "http://$text" }

    $text = $text.TrimEnd('/')
    $text = $text -replace '/chat/completions$', ''
    $text = $text -replace '/models$', ''
    $text = $text.TrimEnd('/')
    if ($text -notmatch '/v\d+$') { $text = "$text/v1" }
    return $text
}

function Get-RsLmStudioRootUrl {
    <# The server root (no /v1), which is what LM_STUDIO_URL wants. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$BaseUrl)
    return (($BaseUrl -replace '/v\d+$', '').TrimEnd('/'))
}

function Read-RsLmStudioConfig {
    <# The stored LM Studio settings, with defaults filled in. #>
    [CmdletBinding()]
    param([string]$Path)

    if (-not $Path) { $Path = Get-RsLmStudioConfigPath }
    $config = [ordered]@{
        version         = 1
        base_url        = $script:RsLmDefaultUrls[0]
        model           = ''
        timeout_seconds = 180
        auto_start      = $true
        data_root       = ''
        runtime_mode    = ''
        ui_effects      = 'reduced'
    }

    if (Test-Path -LiteralPath $Path) {
        try {
            # Get-Content -Raw strips a byte order mark, and ConvertFrom-Json
            # would choke on one, so a file written by an editor still reads.
            $raw = Get-Content -LiteralPath $Path -Raw -ErrorAction Stop
            $parsed = $raw | ConvertFrom-Json -ErrorAction Stop
            foreach ($key in @($script:RsLmConfigKeys)) {
                if ($parsed.PSObject.Properties.Name -contains $key -and $null -ne $parsed.$key) {
                    $config[$key] = $parsed.$key
                }
            }
        } catch {
            Write-RsLog "could not read $Path ($($_.Exception.Message)); using LM Studio defaults" -Level WARN
        }
    }

    $config['base_url'] = ConvertTo-RsLmBaseUrl -Value $config['base_url']
    if (-not $config['base_url']) { $config['base_url'] = $script:RsLmDefaultUrls[0] }
    if (@('full', 'reduced', 'off') -notcontains "$($config['ui_effects'])".ToLowerInvariant()) {
        $config['ui_effects'] = 'reduced'
    }
    return $config
}

function Save-RsLmStudioConfig {
    <#
        Writes the LM Studio settings without a byte order mark.

        ConvertTo-Json plus Set-Content -Encoding utf8 emits a BOM on PowerShell
        5.1, and Python's json.load rejects it - the same trap that made the
        11.3 hardware scan read as "nothing detected".
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][hashtable]$Config,
        [string]$Path
    )

    if (-not $Path) { $Path = Get-RsLmStudioConfigPath }
    New-Item -ItemType Directory -Path (Split-Path -Parent $Path) -Force -ErrorAction SilentlyContinue | Out-Null

    # Start from what is on disk and overlay the caller's keys, so a caller that
    # only knows about one setting cannot drop the others. Writing a whitelist
    # here is how the runtime mode and the effects budget got lost.
    $merged = Read-RsLmStudioConfig -Path $Path
    foreach ($key in @($script:RsLmConfigKeys)) {
        if ($Config.ContainsKey($key) -and $null -ne $Config[$key]) { $merged[$key] = $Config[$key] }
    }

    $ordered = [ordered]@{
        version         = 1
        base_url        = ConvertTo-RsLmBaseUrl -Value $merged['base_url']
        model           = "$($merged['model'])"
        timeout_seconds = if ($merged['timeout_seconds']) { [int]$merged['timeout_seconds'] } else { 180 }
        auto_start      = [bool]$merged['auto_start']
        data_root       = "$($merged['data_root'])"
        runtime_mode    = "$($merged['runtime_mode'])"
        ui_effects      = "$($merged['ui_effects'])"
    }
    if (-not $ordered['base_url']) { $ordered['base_url'] = $script:RsLmDefaultUrls[0] }

    $json = ([pscustomobject]$ordered) | ConvertTo-Json -Depth 4
    [System.IO.File]::WriteAllText($Path, $json, (New-Object System.Text.UTF8Encoding($false)))
    Write-RsLog "LM Studio endpoint recorded in $Path" -Level OK
    return $Path
}

function Test-RsLmStudioEndpoint {
    <#
        Asks an endpoint for its model list.

        Returns Ok / Models / Error. Never throws: an unreachable LM Studio is
        an ordinary outcome, not an installer failure.

        HttpWebRequest with the proxy switched off is used rather than
        Invoke-RestMethod because a machine with a system proxy configured
        would otherwise send a request for 127.0.0.1 to the proxy and fail. The
        application's own httpx calls pass trust_env=False for the same reason.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$BaseUrl,
        [int]$TimeoutSeconds = 5
    )

    $result = [ordered]@{ Ok = $false; Models = @(); Error = '' }
    $url = (ConvertTo-RsLmBaseUrl -Value $BaseUrl) + '/models'

    try {
        $req = [System.Net.HttpWebRequest]::Create($url)
        $req.Method = 'GET'
        $req.Timeout = $TimeoutSeconds * 1000
        $req.ReadWriteTimeout = $TimeoutSeconds * 1000
        $req.Proxy = $null
        $resp = $req.GetResponse()
        try {
            $reader = New-Object System.IO.StreamReader($resp.GetResponseStream())
            try { $body = $reader.ReadToEnd() } finally { $reader.Dispose() }
        } finally {
            $resp.Dispose()
        }

        $ids = @()
        $parsed = $body | ConvertFrom-Json -ErrorAction Stop
        if ($parsed -and $parsed.PSObject.Properties.Name -contains 'data') {
            foreach ($entry in @($parsed.data)) {
                if ($entry -and $entry.PSObject.Properties.Name -contains 'id' -and $entry.id) { $ids += "$($entry.id)" }
            }
        }
        $result['Ok'] = $true
        $result['Models'] = $ids
    } catch {
        $result['Error'] = $_.Exception.Message
    }

    return [pscustomobject]$result
}

function Select-RsLmStudioChatModel {
    <#
        Picks the model a chat request should name.

        LM Studio rejects a request for a model it has not got, and RedSight's
        UI sends no model at all - the provider falls back to the literal id
        "default", which no install has. Naming a real loaded model is what
        turns a 404 into an answer. Embedding and reranking models are skipped:
        they cannot answer a chat.
    #>
    [CmdletBinding()]
    param(
        [string[]]$Models = @(),
        [string]$Preferred = ''
    )

    $list = @($Models | Where-Object { $_ })
    if ($Preferred -and ($list -contains $Preferred)) { return $Preferred }

    foreach ($model in $list) {
        $lower = $model.ToLowerInvariant()
        $isNonChat = $false
        foreach ($marker in $script:RsLmNonChatMarkers) {
            if ($lower -like "*$marker*") { $isNonChat = $true; break }
        }
        if (-not $isNonChat) { return $model }
    }

    if ($list.Count -gt 0) { return $list[0] }
    return ''
}

function Get-RsLmStudioProgram {
    <#
        Locates LM Studio: the lms CLI first, because it can start the server
        headlessly, then the desktop app.
    #>
    [CmdletBinding()] param()

    $found = [ordered]@{ Cli = ''; App = '' }

    # Get-RsCommand hands back a CommandInfo, so the executable path is .Source.
    $cli = Get-RsCommand -Name 'lms'
    if ($cli) { $found['Cli'] = "$($cli.Source)" }
    if (-not $found['Cli']) {
        $userProfile = [Environment]::GetFolderPath('UserProfile')
        foreach ($rel in @('.lmstudio\bin\lms.exe', '.cache\lm-studio\bin\lms.exe')) {
            if (-not $userProfile) { break }
            $candidate = Join-Path $userProfile $rel
            if (Test-Path -LiteralPath $candidate) { $found['Cli'] = $candidate; break }
        }
    }

    $localAppData = Get-RsLocalAppData
    $programFiles = ${env:ProgramFiles}
    $appCandidates = @()
    if ($localAppData) { $appCandidates += (Join-Path $localAppData 'Programs\LM Studio\LM Studio.exe') }
    if ($programFiles) { $appCandidates += (Join-Path $programFiles 'LM Studio\LM Studio.exe') }
    foreach ($candidate in $appCandidates) {
        if (Test-Path -LiteralPath $candidate) { $found['App'] = $candidate; break }
    }

    return [pscustomobject]$found
}

function Start-RsLmStudioServer {
    <#
        Brings the LM Studio local server up through the lms CLI.

        Only the CLI is used here: launching the desktop app from an elevated
        installer would put a GUI in the wrong session, and its server still
        has to be switched on by hand afterwards.
    #>
    [CmdletBinding()]
    param(
        [int]$Port = 1234,
        [int]$WaitSeconds = 45
    )

    $program = Get-RsLmStudioProgram
    if (-not $program.Cli) {
        Write-RsLog 'the LM Studio CLI (lms) is not installed, so the local server cannot be started automatically' -Level INFO
        return $false
    }

    Write-RsLog "starting the LM Studio local server on port $Port" -Level STEP
    Invoke-RsProcess -FilePath $program.Cli -Arguments @('server', 'start', '--port', "$Port") -TimeoutSeconds 120 -Quiet | Out-Null

    $deadline = (Get-Date).AddSeconds($WaitSeconds)
    while ((Get-Date) -lt $deadline) {
        $probe = Test-RsLmStudioEndpoint -BaseUrl "http://127.0.0.1:$Port/v1" -TimeoutSeconds 3
        if ($probe.Ok) {
            Write-RsLog "the LM Studio local server is answering on port $Port" -Level OK
            return $true
        }
        Start-Sleep -Seconds 2
    }

    Write-RsLog "the LM Studio local server did not answer on port $Port within $WaitSeconds seconds" -Level WARN
    return $false
}

function Resolve-RsLmStudio {
    <#
        Settles the LM Studio endpoint and model for this machine and records
        them where every RedSight process can find them.

        Probes the configured endpoint first, then the usual local ones, and
        starts the server through the lms CLI if nothing answers. Writes the
        result whether or not LM Studio was reachable: a stored endpoint is
        what makes the first launch after LM Studio is switched on work
        without re-running setup.

        Returns Ok / BaseUrl / Model / Models / Detail.
    #>
    [CmdletBinding()]
    param(
        [string]$BaseUrl = '',
        [string]$Model = '',
        [switch]$NoAutoStart,
        [string]$ConfigPath
    )

    $stored = Read-RsLmStudioConfig -Path $ConfigPath
    $requested = if ($BaseUrl) { ConvertTo-RsLmBaseUrl -Value $BaseUrl } else { '' }
    $preferredModel = if ($Model) { "$Model" } else { "$($stored['model'])" }

    $candidates = New-Object System.Collections.Generic.List[string]
    foreach ($candidate in @($requested, $stored['base_url']) + $script:RsLmDefaultUrls) {
        if ($candidate -and -not $candidates.Contains($candidate)) { $candidates.Add($candidate) }
    }

    $state = [ordered]@{ Ok = $false; BaseUrl = $candidates[0]; Model = $preferredModel; Models = @(); Detail = '' }

    foreach ($candidate in $candidates) {
        $probe = Test-RsLmStudioEndpoint -BaseUrl $candidate
        if ($probe.Ok) {
            $state['Ok'] = $true
            $state['BaseUrl'] = $candidate
            $state['Models'] = @($probe.Models)
            break
        }
    }

    if (-not $state['Ok'] -and -not $NoAutoStart) {
        if (Start-RsLmStudioServer) {
            $probe = Test-RsLmStudioEndpoint -BaseUrl $script:RsLmDefaultUrls[0]
            if ($probe.Ok) {
                $state['Ok'] = $true
                $state['BaseUrl'] = $script:RsLmDefaultUrls[0]
                $state['Models'] = @($probe.Models)
            }
        }
    }

    if ($state['Ok']) {
        $chosen = Select-RsLmStudioChatModel -Models $state['Models'] -Preferred $preferredModel
        $state['Model'] = $chosen
        if ($chosen) {
            $state['Detail'] = "LM Studio is answering at $($state['BaseUrl']) with model '$chosen'"
        } else {
            $state['Detail'] = "LM Studio is answering at $($state['BaseUrl']) but has no model loaded - load one in LM Studio"
        }
        Write-RsLog $state['Detail'] -Level OK
    } else {
        # Keeping the requested endpoint rather than a probe order artefact is
        # what lets the user point RedSight at a LAN machine before starting it.
        if ($requested) { $state['BaseUrl'] = $requested } else { $state['BaseUrl'] = $stored['base_url'] }
        $state['Model'] = $preferredModel
        $state['Detail'] = "LM Studio did not answer at $($state['BaseUrl']). Start LM Studio, switch on its local server, then use Settings -> LM Studio in RedSight."
        Write-RsLog $state['Detail'] -Level WARN
    }

    $stored['base_url'] = $state['BaseUrl']
    $stored['model'] = $state['Model']
    Save-RsLmStudioConfig -Config $stored -Path $ConfigPath | Out-Null

    return [pscustomobject]$state
}

function Get-RsLmStudioEnvironment {
    <#
        The environment variables the RedSight processes need for LM Studio.

        LM_STUDIO_BASE_URL is the one the backend's settings validator reads;
        LM_STUDIO_URL and LM_BASE_URL are the historical names the desktop
        launchers and the actions gateway use. All three are set, as the
        application's own launcher did.
    #>
    [CmdletBinding()]
    param([string]$ConfigPath)

    $config = Read-RsLmStudioConfig -Path $ConfigPath
    $base = ConvertTo-RsLmBaseUrl -Value $config['base_url']
    $root = Get-RsLmStudioRootUrl -BaseUrl $base

    $vars = [ordered]@{
        LM_STUDIO_BASE_URL                   = $base
        LM_BASE_URL                          = $base
        LM_STUDIO_URL                        = $root
        LM_STUDIO_TIMEOUT                    = "$($config['timeout_seconds'])"
        LM_STUDIO_MODELS_URL                 = "$base/models"
        RED_SIGHT_LMSTUDIO__BASE_URL         = $base
        RED_SIGHT_LMSTUDIO__TIMEOUT_SECONDS  = "$($config['timeout_seconds'])"
        REDSIGHT_UI_EFFECTS                  = "$($config['ui_effects'])"
    }
    if ($config['model']) {
        $vars['LM_STUDIO_MODEL'] = "$($config['model'])"
        $vars['RED_SIGHT_LMSTUDIO__MODEL_ID'] = "$($config['model'])"
    }
    if ($config['data_root']) { $vars['RED_SIGHT_PLATFORM__DATA_ROOT'] = "$($config['data_root'])" }
    if ($config['runtime_mode'] -eq 'native') {
        # No Qdrant server runs natively; saying so skips a lookup for the
        # container hostname "qdrant" and the connection attempt after it.
        $vars['VECTOR_BACKEND_EMBEDDED'] = 'true'
        $vars['VECTOR_BACKEND_HOST'] = '127.0.0.1'
    }
    return $vars
}

function Get-RsLmStudioContainerUrl {
    <#
        The endpoint a container should use to reach the same LM Studio.

        A loopback address means the server is on this machine, which a
        container cannot reach under that name - host.docker.internal is the
        name Docker Desktop publishes for the host. Any other host is reachable
        from the container as it stands.
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$BaseUrl)

    $base = ConvertTo-RsLmBaseUrl -Value $BaseUrl
    try {
        $uri = [System.Uri]$base
    } catch {
        return 'http://host.docker.internal:1234/v1'
    }

    if ($uri.Host -in @('127.0.0.1', 'localhost', '::1', '0.0.0.0')) {
        $port = if ($uri.IsDefaultPort) { 1234 } else { $uri.Port }
        return "http://host.docker.internal:$port$($uri.AbsolutePath.TrimEnd('/'))"
    }
    return $base
}

function Repair-RsComposeLmStudio {
    <#
        Rewrites the LM Studio endpoint baked into the compose files.

        The shipped docker-compose.yml carries the author's own LAN address
        (LM_STUDIO_BASE_URL=http://192.168.50.139:1234/v1), so a containerized
        install talks to a machine that is not the user's. Both the list form
        (- KEY=value) and the mapping form (KEY: "value") are handled, and only
        the LM Studio keys are touched.

        Returns the number of files changed.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$ProjectRoot,
        [string]$BaseUrl,
        [string]$Model
    )

    if (-not $BaseUrl) { $BaseUrl = (Read-RsLmStudioConfig)['base_url'] }
    $containerBase = Get-RsLmStudioContainerUrl -BaseUrl $BaseUrl
    $containerRoot = Get-RsLmStudioRootUrl -BaseUrl $containerBase

    $values = [ordered]@{
        LM_STUDIO_BASE_URL = $containerBase
        LM_BASE_URL        = $containerBase
        LM_STUDIO_URL      = $containerRoot
    }
    if ($Model) { $values['LM_STUDIO_MODEL'] = $Model }

    $changed = 0
    foreach ($name in @('docker-compose.yml', 'docker-compose.override.yml', 'docker-compose.yaml')) {
        $path = Join-Path $ProjectRoot $name
        if (-not (Test-Path -LiteralPath $path)) { continue }

        $text = [System.IO.File]::ReadAllText($path)
        $original = $text
        foreach ($key in $values.Keys) {
            $value = $values[$key]
            # list form:    - LM_STUDIO_BASE_URL=http://...
            $text = [regex]::Replace($text, "(?m)^(\s*-\s*$key\s*=\s*).*$", "`${1}$value")
            # mapping form: LM_STUDIO_BASE_URL: "http://..."
            $text = [regex]::Replace($text, "(?m)^(\s*$key\s*:\s*).*$", "`${1}`"$value`"")
        }

        if ($text -ne $original) {
            [System.IO.File]::WriteAllText($path, $text, (New-Object System.Text.UTF8Encoding($false)))
            Write-RsLog "rewrote the LM Studio endpoint in $name to $containerBase" -Level OK
            $changed++
        }
    }

    if ($changed -eq 0) { Write-RsLog 'no compose file needed its LM Studio endpoint rewritten' -Level INFO }
    return $changed
}

function Repair-RsAppLauncher {
    <#
        Points the application's own shipped launchers at the recorded LM Studio
        endpoint.

        START-REDSIGHT.ps1 and its siblings hard-assign the three historical
        variables:

            $env:LM_STUDIO_URL      = "http://127.0.0.1:1234"
            $env:LM_STUDIO_BASE_URL = "http://127.0.0.1:1234/v1"
            $env:LM_BASE_URL        = "http://127.0.0.1:1234/v1"

        An explicit assignment wins over the recorded configuration, which is
        correct behaviour - but it means a server on another port or another
        machine is never reached from those launchers. Rewriting the assignments
        keeps the launchers authoritative and correct at the same time.

        Returns the number of files changed.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$ProjectRoot,
        [string]$BaseUrl,
        [string]$Model
    )

    $config = Read-RsLmStudioConfig
    if (-not $BaseUrl) { $BaseUrl = $config['base_url'] }
    if (-not $Model) { $Model = $config['model'] }
    $base = ConvertTo-RsLmBaseUrl -Value $BaseUrl
    $root = Get-RsLmStudioRootUrl -BaseUrl $base

    $values = [ordered]@{
        LM_STUDIO_BASE_URL = $base
        LM_BASE_URL        = $base
        LM_STUDIO_URL      = $root
    }
    if ($Model) { $values['LM_STUDIO_MODEL'] = $Model }

    $changed = 0
    $targets = @('START-REDSIGHT.ps1', 'RESTART-REDSIGHT.ps1', 'LAUNCH-REDSIGHT-DESKTOP.ps1',
                 'START-REDSIGHT.bat', 'LAUNCH-REDSIGHT.bat')

    foreach ($name in $targets) {
        $path = Join-Path $ProjectRoot $name
        if (-not (Test-Path -LiteralPath $path)) { continue }

        $text = [System.IO.File]::ReadAllText($path)
        $original = $text
        foreach ($key in $values.Keys) {
            $value = $values[$key]
            # PowerShell:  $env:KEY = "..."
            # The backtick keeps the dollar out of PowerShell's expansion so the
            # regex sees a literal \$env: prefix.
            $text = [regex]::Replace($text, "(?m)^(\s*\`$env:$key\s*=\s*).*$", "`${1}`"$value`"")
            # Batch:       set KEY=...
            $text = [regex]::Replace($text, "(?im)^(\s*set\s+$key\s*=\s*).*$", "`${1}$value")
        }

        if ($text -ne $original) {
            [System.IO.File]::WriteAllText($path, $text, (New-Object System.Text.UTF8Encoding($false)))
            Write-RsLog "pointed $name at $base" -Level OK
            $changed++
        }
    }

    if ($changed -eq 0) { Write-RsLog 'no shipped launcher needed its LM Studio endpoint rewritten' -Level INFO }
    return $changed
}
