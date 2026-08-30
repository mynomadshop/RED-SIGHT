<#
    Apply-AppOverlay.ps1

    Copies the RedSight application overlay into a staged payload and wires it
    into the Command Center launcher.

    The overlay follows the convention the codebase already uses for additive
    features: a new app\ui\action_palette_stageNNN module exposing install(),
    called from launch_redsight_command_center.py inside a try/except so a
    failure in the extension can never stop the UI from starting.

    Three things are installed:

      * app\ui\action_palette_stage114_mcp.py   MCP servers in Settings
      * app\ui\action_palette_stage115_lmstudio.py
                                                LM Studio endpoint in Settings,
                                                redirected status probes, and
                                                the responsiveness fixes
      * redsight_bootstrap.py                   the shared runtime configuration
                                                setup copies into each
                                                virtualenv's site-packages

    and app\models\lmstudio.py gains an appended Stage 11.5 block that makes a
    chat request name a model LM Studio actually has.

    Idempotent: running it twice injects nothing the second time.

        pwsh -File installer/app-overlay/Apply-AppOverlay.ps1 -PayloadDir <staging>
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$PayloadDir,
    [string]$OverlayDir
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not $OverlayDir) { $OverlayDir = $scriptDir }

. (Join-Path (Join-Path (Split-Path -Parent $scriptDir) 'scripts') 'RedSight-Common.ps1')

if (-not (Test-Path -LiteralPath $PayloadDir)) { throw "payload directory not found: $PayloadDir" }

# --------------------------------------------------------------------------
# 1. Copy the overlay modules
# --------------------------------------------------------------------------

$overlayApp = Join-Path $OverlayDir 'app'
$copied = 0
if (Test-Path -LiteralPath $overlayApp) {
    foreach ($file in (Get-ChildItem -LiteralPath $overlayApp -Recurse -File)) {
        if ($file.Extension -eq '.pyc') { continue }
        $rel = $file.FullName.Substring($overlayApp.Length).TrimStart('\', '/')
        $dest = Join-Path (Join-Path $PayloadDir 'app') $rel
        New-Item -ItemType Directory -Path (Split-Path -Parent $dest) -Force -ErrorAction SilentlyContinue | Out-Null
        Copy-Item -LiteralPath $file.FullName -Destination $dest -Force
        Write-RsLog "    + app\$rel" -Level DEBUG
        $copied++
    }
}

# The runtime configuration module lives at the payload root so setup can copy
# it into each virtualenv's site-packages, where every RedSight process picks
# it up through a .pth file before any application code runs.
$bootstrap = Join-Path $OverlayDir 'redsight_bootstrap.py'
if (Test-Path -LiteralPath $bootstrap) {
    Copy-Item -LiteralPath $bootstrap -Destination (Join-Path $PayloadDir 'redsight_bootstrap.py') -Force
    Write-RsLog '    + redsight_bootstrap.py' -Level DEBUG
    $copied++
} else {
    Write-RsLog "the runtime configuration module is missing from $OverlayDir" -Level WARN
}

Write-RsLog "copied $copied overlay module(s) into the payload" -Level OK

# --------------------------------------------------------------------------
# 2. Append the LM Studio provider patch
# --------------------------------------------------------------------------
#
# The shipped provider sends the literal model id "default", because
# /api/v1/chat passes no model and settings.lmstudio.model_id is never read -
# so LM Studio answers 404 and the query never reaches the loaded model. Its
# base_url also defaults to a container-only hostname. Both are corrected by a
# block appended after the class definition, so nothing above it changes.

$patchMarker = '# REDSIGHT_STAGE115_MODEL_RESOLUTION'
$patchFile = Join-Path (Join-Path $OverlayDir 'patches') 'lmstudio_stage115.py'
$providerFile = Join-Path $PayloadDir 'app\models\lmstudio.py'

if (-not (Test-Path -LiteralPath $patchFile)) {
    Write-RsLog "the LM Studio provider patch is missing from $OverlayDir" -Level WARN
} elseif (-not (Test-Path -LiteralPath $providerFile)) {
    Write-RsLog "payload does not contain app\models\lmstudio.py - LM Studio will keep sending model 'default'" -Level WARN
} else {
    $existing = Get-Content -LiteralPath $providerFile -Raw
    if ($existing -like "*$patchMarker*") {
        Write-RsLog 'app\models\lmstudio.py is already patched' -Level OK
    } elseif ($existing -notmatch 'class\s+LmStudioProvider\b') {
        Write-RsLog 'app\models\lmstudio.py does not define LmStudioProvider - skipping the model-resolution patch' -Level WARN
    } else {
        $patch = Get-Content -LiteralPath $patchFile -Raw
        [System.IO.File]::AppendAllText($providerFile, $patch, (New-Object System.Text.UTF8Encoding($false)))
        Write-RsLog 'patched app\models\lmstudio.py to resolve a real LM Studio model' -Level OK
    }
}

# --------------------------------------------------------------------------
# 3. Wire the UI extensions into the launcher
# --------------------------------------------------------------------------

$hooks = @(
    [pscustomobject]@{
        Marker = '# REDSIGHT_STAGE114_MCP_SETTINGS'
        Module = 'action_palette_stage114_mcp'
        Alias  = '_rs114'
    },
    [pscustomobject]@{
        Marker = '# REDSIGHT_STAGE115_LMSTUDIO'
        Module = 'action_palette_stage115_lmstudio'
        Alias  = '_rs115'
    }
)

$launcher = Join-Path $PayloadDir 'launch_redsight_command_center.py'
if (-not (Test-Path -LiteralPath $launcher)) {
    Write-RsLog "launcher not found at $launcher - the Settings extensions will not be wired in" -Level WARN
    return
}

$lines = @(Get-Content -LiteralPath $launcher)

foreach ($hook in $hooks) {
    if ($lines -contains $hook.Marker) {
        Write-RsLog "launcher already wired for $($hook.Module)" -Level OK
        continue
    }

    $block = @(
        $hook.Marker,
        'try:',
        "    from app.ui import $($hook.Module) as $($hook.Alias)",
        "    $($hook.Alias).install()",
        'except Exception:',
        '    import traceback',
        '    traceback.print_exc()',
        ''
    )

    # Anchor on the existing Stage 11.2 UI extension block: it is already at the
    # point in the launcher where the UI modules are imported and patched. Both
    # hooks are monkey-patches, so relative order does not matter.
    $anchorIndex = -1
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i].Trim() -eq '# REDSIGHT_STAGE112_UI_EXTENSION') { $anchorIndex = $i; break }
    }

    if ($anchorIndex -lt 0) {
        # Fall back to just after the last top-level app.ui import.
        for ($i = 0; $i -lt $lines.Count; $i++) {
            if ($lines[$i] -match '^\s*from\s+app\.ui\s+import\s') { $anchorIndex = $i + 1 }
        }
    }

    if ($anchorIndex -lt 0) {
        # Appending at the end of the launcher is worse than failing: its last
        # statement runs the Qt event loop, so anything after it executes only
        # once the user has closed the window. The hooks would look installed
        # and do nothing.
        throw ("no injection point found in $(Split-Path -Leaf $launcher) for $($hook.Module). " +
               "Add a '# REDSIGHT_STAGE112_UI_EXTENSION' line after the app.ui imports, " +
               'or the Settings tabs and the responsiveness fixes will not be installed.')
    }

    $out = New-Object System.Collections.Generic.List[string]
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($i -eq $anchorIndex) {
            foreach ($h in $block) { $out.Add($h) }
        }
        $out.Add($lines[$i])
    }
    $lines = @($out.ToArray())
    Write-RsLog "wired $($hook.Module) into $(Split-Path -Leaf $launcher) at line $($anchorIndex + 1)" -Level OK
}

Set-Content -LiteralPath $launcher -Value $lines -Encoding utf8
