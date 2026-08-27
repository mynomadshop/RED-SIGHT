<#
    Verify-RedSightSetup.ps1

    Health check for an installed RedSight. Answers one question: can RedSight
    actually launch and work right now, and if not, what exactly is missing?

    Run it any time:
        powershell -ExecutionPolicy Bypass -File scripts\windows\Verify-RedSightSetup.ps1

    Exit codes
        0   every required check passed
        1   at least one required check failed
#>

[CmdletBinding()]
param(
    [string]$ProjectRoot,
    [switch]$Json
)

Set-StrictMode -Version Latest

$scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
. (Join-Path $scriptDir 'RedSight-Preflight.ps1')

if (-not $ProjectRoot) {
    $ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $scriptDir '..\..'))
}

Initialize-RsLog -Name 'verify' | Out-Null

$checks = New-Object System.Collections.Generic.List[object]

function Add-RsCheck {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][ValidateSet('pass', 'fail', 'warn', 'skip')][string]$Status,
        [string]$Detail = '',
        [switch]$Required
    )
    $checks.Add([pscustomobject]@{
        Name     = $Name
        Status   = $Status
        Detail   = $Detail
        Required = [bool]$Required
    })
    $level = switch ($Status) { 'pass' { 'OK' } 'fail' { 'FAIL' } 'warn' { 'WARN' } default { 'INFO' } }
    Write-RsLog ("{0,-34} {1,-5} {2}" -f $Name, $Status.ToUpperInvariant(), $Detail) -Level $level
}

Write-RsLog ('=' * 70)
Write-RsLog "REDSIGHT HEALTH CHECK  ($ProjectRoot)"
Write-RsLog ('=' * 70)

# --- Application tree -----------------------------------------------------

foreach ($rel in @('docker-compose.yml', 'launch_redsight_command_center.py', 'app', 'redsight_actions')) {
    $p = Join-Path $ProjectRoot $rel
    Add-RsCheck -Name "app file: $rel" -Required `
                -Status $(if (Test-Path -LiteralPath $p) { 'pass' } else { 'fail' }) `
                -Detail $(if (Test-Path -LiteralPath $p) { '' } else { "missing: $p" })
}

# --- Leftover build-machine paths -----------------------------------------

# A single surviving author-machine path breaks the launcher at runtime, so this
# is a required check rather than a cosmetic one.
$leaked = Repair-RsHardcodedPaths -ProjectRoot $ProjectRoot -WhatIf
Add-RsCheck -Name 'install paths rewritten' -Required `
            -Status $(if ($leaked.Rewritten -eq 0) { 'pass' } else { 'fail' }) `
            -Detail $(if ($leaked.Rewritten -eq 0) { 'no build-machine paths remain' }
                      else { "$($leaked.Rewritten) file(s) still reference another install path" })

# --- Python ---------------------------------------------------------------

$python = $null
$runtimeExe = Join-Path (Get-RsRuntimePythonDir -ProjectRoot $ProjectRoot) 'python.exe'
if ((Test-Path -LiteralPath $runtimeExe) -and (Test-RsPythonUsable -PythonExe $runtimeExe)) {
    $python = $runtimeExe
} else {
    $python = Find-RsSystemPython
}
if ($python) {
    $v = Get-RsPythonVersion -PythonExe $python
    Add-RsCheck -Name 'python 3.12 runtime' -Status 'pass' -Required -Detail "$python ($v)"
} else {
    Add-RsCheck -Name 'python 3.12 runtime' -Status 'fail' -Required -Detail 'no usable Python 3.12 found'
}

# --- Virtual environments -------------------------------------------------

$uiPython = Join-Path $ProjectRoot '.venv-ui\Scripts\python.exe'
if (Test-Path -LiteralPath $uiPython) {
    # These four are exactly what the Command Center imports at startup.
    $modules = @('PySide6', 'qasync', 'httpx', 'pydantic')
    $ok = Test-RsVenvImports -VenvPython $uiPython -Modules $modules
    Add-RsCheck -Name 'desktop UI env (.venv-ui)' -Required `
                -Status $(if ($ok) { 'pass' } else { 'fail' }) `
                -Detail $(if ($ok) { "imports $($modules -join ', ')" } else { 'required modules missing' })
} else {
    Add-RsCheck -Name 'desktop UI env (.venv-ui)' -Status 'fail' -Required -Detail "missing: $uiPython"
}

$actionsPython = Join-Path $ProjectRoot '.venv-actions\Scripts\python.exe'
if (Test-Path -LiteralPath $actionsPython) {
    $ok = Test-RsVenvImports -VenvPython $actionsPython -Modules @('fastapi', 'uvicorn', 'httpx')
    Add-RsCheck -Name 'gateway env (.venv-actions)' `
                -Status $(if ($ok) { 'pass' } else { 'warn' }) `
                -Detail $(if ($ok) { 'imports fastapi, uvicorn, httpx' } else { 'some modules missing' })
} else {
    Add-RsCheck -Name 'gateway env (.venv-actions)' -Status 'warn' -Detail 'not created'
}

# --- Configuration --------------------------------------------------------

Add-RsCheck -Name '.env present' `
            -Status $(if (Test-Path -LiteralPath (Join-Path $ProjectRoot '.env')) { 'pass' } else { 'warn' }) `
            -Detail 'LM Studio / Qdrant settings'

# --- Docker ---------------------------------------------------------------

# In native mode Docker is genuinely not needed, so its absence is informational
# rather than a failure - the whole point of that mode.
$nativeMode = (Get-RsEnvValue -Path (Join-Path $ProjectRoot '.env') -Key 'REDSIGHT_RUNTIME_MODE') -eq 'native'
$dockerRequired = -not $nativeMode

$dockerCli = Find-RsDockerCli
if (-not $dockerCli) {
    Add-RsCheck -Name 'docker CLI' -Required:$dockerRequired `
                -Status $(if ($dockerRequired) { 'fail' } else { 'skip' }) `
                -Detail $(if ($dockerRequired) { 'Docker Desktop is not installed' }
                          else { 'not needed in native mode' })
} else {
    Add-RsCheck -Name 'docker CLI' -Status 'pass' -Required:$dockerRequired -Detail $dockerCli

    if (Test-RsDockerEngine -DockerCli $dockerCli) {
        Add-RsCheck -Name 'docker engine' -Status 'pass' -Required:$dockerRequired -Detail 'daemon is responding'

        # Does the compose file parse against this engine?
        $r = Invoke-RsProcess -FilePath $dockerCli -Arguments @('compose', 'config', '--quiet') `
                              -WorkingDirectory $ProjectRoot -TimeoutSeconds 180 -Quiet
        Add-RsCheck -Name 'docker compose config' `
                    -Status $(if ($r.ExitCode -eq 0) { 'pass' } else { 'warn' }) `
                    -Detail $(if ($r.ExitCode -eq 0) { 'docker-compose.yml is valid' } else { "exit $($r.ExitCode)" })

        # Are the images already built? Not required - first launch builds them.
        $r = Invoke-RsProcess -FilePath $dockerCli -Arguments @('images', '--format', '{{.Repository}}') `
                              -TimeoutSeconds 120 -Quiet
        $hasQdrant = $r.StdOut -match 'qdrant'
        Add-RsCheck -Name 'docker images built' `
                    -Status $(if ($hasQdrant) { 'pass' } else { 'warn' }) `
                    -Detail $(if ($hasQdrant) { 'qdrant image present' } else { 'will be built on first launch' })
    } else {
        Add-RsCheck -Name 'docker engine' -Required:$dockerRequired `
                    -Status $(if ($dockerRequired) { 'fail' } else { 'skip' }) `
                    -Detail 'Docker Desktop is installed but not running'
    }
}

# --- WSL2 -----------------------------------------------------------------

$wsl = Get-RsWslState
$wslOk = $wsl.SubsystemEnabled -and $wsl.VirtualMachinePlatform
Add-RsCheck -Name 'WSL2 platform' `
            -Status $(if ($wslOk) { 'pass' } elseif ($nativeMode) { 'skip' } else { 'warn' }) `
            -Detail $(if ($wslOk) { "subsystem=$($wsl.SubsystemEnabled) vmp=$($wsl.VirtualMachinePlatform) kernel=$($wsl.KernelInstalled)" }
                      elseif ($nativeMode) { 'not needed in native mode' }
                      else { "subsystem=$($wsl.SubsystemEnabled) vmp=$($wsl.VirtualMachinePlatform) kernel=$($wsl.KernelInstalled)" })

# --- Optional integrations -----------------------------------------------

$node = Get-RsCommand -Name 'node'
Add-RsCheck -Name 'Node.js (WhatsApp bridge)' `
            -Status $(if ($node) { 'pass' } else { 'skip' }) `
            -Detail $(if ($node) { $node.Source } else { 'optional feature not installed' })

# LM Studio is started by the user, so its absence is only informational.
$lmUp = $false
try {
    $req = [System.Net.HttpWebRequest]::Create('http://127.0.0.1:1234/v1/models')
    $req.Timeout = 3000
    $resp = $req.GetResponse()
    $resp.Dispose()
    $lmUp = $true
} catch { }
Add-RsCheck -Name 'LM Studio local server' `
            -Status $(if ($lmUp) { 'pass' } else { 'skip' }) `
            -Detail $(if ($lmUp) { 'responding on 127.0.0.1:1234' } else { 'not running (start it for local inference)' })

# --- Agent capabilities ---------------------------------------------------

# Multi-step planning, multiple tool calls per task and skill-driven workflows
# are what make the agent useful, so check the pieces are actually present
# rather than assuming the payload carried them.
$agentFiles = @{
    'redsight_actions\stage113_task_runner.py'  = 'multi-step task runner (plan, approve, cancel)'
    'app\ui\action_palette_stage113.py'         = 'TASK PLAN panel with per-step status'
    'app\ui\action_palette_stage113_wiring.py'  = '/agent command routed through the step-tracked runner'
}
foreach ($rel in $agentFiles.Keys) {
    $p = Join-Path $ProjectRoot $rel
    Add-RsCheck -Name "agent: $($agentFiles[$rel])" `
                -Status $(if (Test-Path -LiteralPath $p) { 'pass' } else { 'warn' }) `
                -Detail $(if (Test-Path -LiteralPath $p) { $rel } else { "missing: $rel" })
}

# The inherited skill catalog is what "advanced workflows" draws on.
$skillRoot = Join-Path $ProjectRoot 'data\heritage\hermes\skills'
$skillCount = 0
if (Test-Path -LiteralPath $skillRoot) {
    $skillCount = @(Get-ChildItem -LiteralPath $skillRoot -Recurse -Filter 'SKILL.md' -File -ErrorAction SilentlyContinue).Count
}
Add-RsCheck -Name 'agent: inherited skill catalog' `
            -Status $(if ($skillCount -gt 0) { 'pass' } else { 'warn' }) `
            -Detail "$skillCount skill(s) under data\heritage"

# If the backend is up, confirm the multi-step run API answers. Read-only: the
# health check must never start an agent run of its own.
$apiBase = 'http://127.0.0.1:8000'
$envApi = Get-RsEnvValue -Path (Join-Path $ProjectRoot '.env') -Key 'REDSIGHT_API_URL'
if ($envApi) { $apiBase = $envApi }
$agentApi = 'skip'
$agentDetail = 'backend not running - start RedSight and re-run to check'
try {
    $req = [System.Net.HttpWebRequest]::Create("$apiBase/agent/run")
    $req.Method = 'GET'
    $req.Timeout = 4000
    $resp = $req.GetResponse()
    $resp.Dispose()
    $agentApi = 'pass'
    $agentDetail = "$apiBase/agent/run answered"
} catch {
    if ($_.Exception.Response) {
        # A protocol response means the backend is up; 404 means the route is absent.
        $code = [int]$_.Exception.Response.StatusCode
        $_.Exception.Response.Dispose()
        if ($code -eq 404) {
            $agentApi = 'warn'
            $agentDetail = "backend is running but $apiBase/agent/run returned 404 - the multi-step run API is not registered"
        } else {
            $agentApi = 'pass'
            $agentDetail = "$apiBase/agent/run answered with HTTP $code"
        }
    }
}
Add-RsCheck -Name 'agent: multi-step run API' -Status $agentApi -Detail $agentDetail

# --- MCP servers ----------------------------------------------------------

$mcpConfig = Join-Path (Get-RsLocalAppData) 'RedSight\private\mcp-native.json'
$mcpCount = 0
if (Test-Path -LiteralPath $mcpConfig) {
    try {
        $mcpRaw = Get-Content -LiteralPath $mcpConfig -Raw | ConvertFrom-Json
        $servers = $mcpRaw.PSObject.Properties['mcp_servers']
        if ($servers -and $servers.Value) { $mcpCount = @($servers.Value.PSObject.Properties).Count }
    } catch { }
}
Add-RsCheck -Name 'MCP servers configured' `
            -Status $(if ($mcpCount -gt 0) { 'pass' } else { 'skip' }) `
            -Detail $(if ($mcpCount -gt 0) { "$mcpCount server(s) in $mcpConfig" }
                      else { 'none yet - add one in Settings -> MCP Servers by pasting a path' })

# --- Working directory ----------------------------------------------------

$wsPath = Get-RsEnvValue -Path (Join-Path $ProjectRoot '.env') -Key 'REDSIGHT_WORKSPACE'
if ($wsPath -and (Test-Path -LiteralPath $wsPath)) {
    $writable = $false
    try {
        $probe = Join-Path $wsPath '.redsight-health-probe'
        Set-Content -LiteralPath $probe -Value 'ok' -Encoding ascii -ErrorAction Stop
        Remove-Item -LiteralPath $probe -Force -ErrorAction SilentlyContinue
        $writable = $true
    } catch { }
    Add-RsCheck -Name 'working directory' -Required `
                -Status $(if ($writable) { 'pass' } else { 'fail' }) `
                -Detail $(if ($writable) { $wsPath } else { "not writable: $wsPath" })
} else {
    Add-RsCheck -Name 'working directory' -Status 'fail' -Required `
                -Detail 'REDSIGHT_WORKSPACE is not set or the folder is missing'
}

# --- Runtime mode ---------------------------------------------------------

$runtimeMode = Get-RsEnvValue -Path (Join-Path $ProjectRoot '.env') -Key 'REDSIGHT_RUNTIME_MODE'
if (-not $runtimeMode) { $runtimeMode = 'container' }
Add-RsCheck -Name 'runtime mode' -Status 'pass' `
            -Detail $(if ($runtimeMode -eq 'native') { 'native - backend in-process, embedded vector store, no Docker needed' }
                      else { 'container - Docker + WSL2 backend' })

# --- Shortcut -------------------------------------------------------------

$lnk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'RedSight.lnk'
Add-RsCheck -Name 'desktop shortcut' `
            -Status $(if (Test-Path -LiteralPath $lnk) { 'pass' } else { 'warn' }) `
            -Detail $lnk

# --- Result ---------------------------------------------------------------

$requiredFailed = @($checks | Where-Object { $_.Required -and $_.Status -eq 'fail' })
$warned = @($checks | Where-Object { $_.Status -eq 'warn' })

Write-RsLog ('=' * 70)
Write-RsLog ("{0} checks: {1} pass, {2} warn, {3} fail" -f $checks.Count,
             @($checks | Where-Object { $_.Status -eq 'pass' }).Count, $warned.Count,
             @($checks | Where-Object { $_.Status -eq 'fail' }).Count)

if ($requiredFailed.Count) {
    Write-RsLog 'RedSight is NOT ready to launch. Required checks failed:' -Level FAIL
    foreach ($c in $requiredFailed) { Write-RsLog "  - $($c.Name): $($c.Detail)" -Level FAIL }
    Write-RsLog 'Re-run setup to repair:' -Level INFO
    Write-RsLog "  powershell -ExecutionPolicy Bypass -File `"$ProjectRoot\scripts\windows\Bootstrap-RedSight.ps1`" -InstallDocker -EnableWsl" -Level INFO
} else {
    Write-RsLog 'RedSight is ready to launch.' -Level OK
}
Write-RsLog ('=' * 70)

if ($Json) {
    $checks | ConvertTo-Json -Depth 4
}

exit $(if ($requiredFailed.Count) { 1 } else { 0 })
