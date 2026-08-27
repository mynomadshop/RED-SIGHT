<#
    Apply-AppOverlay.ps1

    Copies the RedSight application overlay into a staged payload and wires it
    into the Command Center launcher.

    The overlay follows the convention the codebase already uses for additive
    features: a new app\ui\action_palette_stageNNN module exposing install(),
    called from launch_redsight_command_center.py inside a try/except so a
    failure in the extension can never stop the UI from starting.

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
        $rel = $file.FullName.Substring($overlayApp.Length).TrimStart('\', '/')
        $dest = Join-Path (Join-Path $PayloadDir 'app') $rel
        New-Item -ItemType Directory -Path (Split-Path -Parent $dest) -Force -ErrorAction SilentlyContinue | Out-Null
        Copy-Item -LiteralPath $file.FullName -Destination $dest -Force
        Write-RsLog "    + app\$rel" -Level DEBUG
        $copied++
    }
}
Write-RsLog "copied $copied overlay module(s) into the payload" -Level OK

# --------------------------------------------------------------------------
# 2. Wire the MCP settings extension into the launcher
# --------------------------------------------------------------------------

$marker = '# REDSIGHT_STAGE114_MCP_SETTINGS'
$hook = @(
    $marker,
    'try:',
    '    from app.ui import action_palette_stage114_mcp as _rs114',
    '    _rs114.install()',
    'except Exception:',
    '    import traceback',
    '    traceback.print_exc()',
    ''
)

$launcher = Join-Path $PayloadDir 'launch_redsight_command_center.py'
if (-not (Test-Path -LiteralPath $launcher)) {
    Write-RsLog "launcher not found at $launcher - the MCP settings tab will not be wired in" -Level WARN
    return
}

$lines = @(Get-Content -LiteralPath $launcher)
if ($lines -contains $marker) {
    Write-RsLog 'launcher already wired for the MCP settings tab' -Level OK
    return
}

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
    Write-RsLog 'no anchor found in the launcher; appending the hook at the end' -Level WARN
    $anchorIndex = $lines.Count
}

$out = New-Object System.Collections.Generic.List[string]
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($i -eq $anchorIndex) {
        foreach ($h in $hook) { $out.Add($h) }
    }
    $out.Add($lines[$i])
}
if ($anchorIndex -ge $lines.Count) {
    foreach ($h in $hook) { $out.Add($h) }
}

Set-Content -LiteralPath $launcher -Value $out.ToArray() -Encoding utf8
Write-RsLog "wired the MCP settings tab into $(Split-Path -Leaf $launcher) at line $($anchorIndex + 1)" -Level OK
