<#
    Test-IssScript.ps1

    Static checks for installer\RedSight.iss.

    The Inno Setup compiler is Windows-only, so on any other platform this is the
    only thing standing between a typo and a failed build. It checks the classes
    of mistake that ISCC would reject or, worse, accept silently:

      * a Check:/{code:...} reference with no matching [Code] function
      * an unknown section name
      * an unknown flag in [Files]/[Dirs]/[Icons]/[Run]/[UninstallRun]
      * a missing required [Setup] directive
      * an unbalanced line continuation
      * a [Components]/[Tasks] name referenced from [Code] that does not exist

        pwsh -File installer/tests/Test-IssScript.ps1
#>

[CmdletBinding()]
param([string]$IssPath)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not $IssPath) { $IssPath = Join-Path (Split-Path -Parent $scriptDir) 'RedSight.iss' }
if (-not (Test-Path -LiteralPath $IssPath)) { throw "script not found: $IssPath" }

$script:Pass = 0
$script:Fail = 0
$script:Failures = New-Object System.Collections.Generic.List[string]

function Assert-True {
    param([Parameter(Mandatory)][string]$Name, [Parameter(Mandatory)][AllowNull()]$Condition, [string]$Detail = '')
    if ($Condition) {
        $script:Pass++
        Write-Host "  PASS  $Name" -ForegroundColor Green
    } else {
        $script:Fail++
        $script:Failures.Add("$Name $Detail")
        Write-Host "  FAIL  $Name $Detail" -ForegroundColor Red
    }
}

$raw = Get-Content -LiteralPath $IssPath -Raw
$lines = $raw -split "`r?`n"

Write-Host "`n== Linting $(Split-Path -Leaf $IssPath) ==" -ForegroundColor Cyan

# --------------------------------------------------------------------------
# Join continued lines so directives can be inspected whole.
# --------------------------------------------------------------------------
$logical = New-Object System.Collections.Generic.List[string]
$buffer = ''
foreach ($line in $lines) {
    $trimmed = $line.TrimEnd()
    if ($trimmed -match '\\$') {
        $buffer += ($trimmed.Substring(0, $trimmed.Length - 1))
    } else {
        $logical.Add($buffer + $trimmed)
        $buffer = ''
    }
}
Assert-True -Name 'no dangling line continuation at end of file' -Condition ($buffer -eq '')

# --------------------------------------------------------------------------
# Sections
# --------------------------------------------------------------------------
$knownSections = @(
    'Setup', 'Types', 'Components', 'Tasks', 'Dirs', 'Files', 'Icons', 'INI',
    'InstallDelete', 'Languages', 'Messages', 'CustomMessages', 'LangOptions',
    'Registry', 'Run', 'UninstallDelete', 'UninstallRun', 'Code', 'ISSigKeys'
)
$sections = @()
foreach ($l in $logical) {
    $m = [regex]::Match($l.Trim(), '^\[([A-Za-z]+)\]$')
    if ($m.Success) { $sections += $m.Groups[1].Value }
}
$unknown = @($sections | Where-Object { $knownSections -notcontains $_ })
Assert-True -Name 'every section name is a real Inno Setup section' `
            -Condition ($unknown.Count -eq 0) -Detail "(unknown: $($unknown -join ', '))"
foreach ($required in @('Setup', 'Files', 'Run', 'Code')) {
    Assert-True -Name "[$required] section present" -Condition ($sections -contains $required)
}

# Track which section each logical line belongs to.
$current = ''
$bySection = @{}
foreach ($s in $knownSections) { $bySection[$s] = New-Object System.Collections.Generic.List[string] }
foreach ($l in $logical) {
    $m = [regex]::Match($l.Trim(), '^\[([A-Za-z]+)\]$')
    if ($m.Success) { $current = $m.Groups[1].Value; continue }
    if ($current -and $bySection.ContainsKey($current)) { $bySection[$current].Add($l) }
}

# --------------------------------------------------------------------------
# Required [Setup] directives
# --------------------------------------------------------------------------
$setupText = ($bySection['Setup'] -join "`n")
foreach ($directive in @('AppName', 'AppVersion', 'DefaultDirName', 'OutputBaseFilename', 'AppId')) {
    Assert-True -Name "[Setup] defines $directive" -Condition ($setupText -match "(?m)^\s*$directive\s*=")
}

# Elevation and platform gating are load-bearing for this installer: setup
# installs Docker Desktop and enables Windows features.
Assert-True -Name '[Setup] requires administrator privileges' `
            -Condition ($setupText -match '(?m)^\s*PrivilegesRequired\s*=\s*admin')
Assert-True -Name '[Setup] restricts to x64' `
            -Condition ($setupText -match '(?m)^\s*ArchitecturesAllowed\s*=')
Assert-True -Name '[Setup] sets a MinVersion for the WSL2 floor' `
            -Condition ($setupText -match '(?m)^\s*MinVersion\s*=')

# --------------------------------------------------------------------------
# [Code] functions vs. Check: / {code:...} references
# --------------------------------------------------------------------------
$codeStart = $raw.IndexOf('[Code]')
$codeText = if ($codeStart -ge 0) { $raw.Substring($codeStart) } else { '' }

$defined = New-Object System.Collections.Generic.List[string]
foreach ($m in [regex]::Matches($codeText, '(?im)^\s*(?:function|procedure)\s+([A-Za-z_][A-Za-z0-9_]*)')) {
    $defined.Add($m.Groups[1].Value)
}
Write-Host "        [Code] defines: $($defined -join ', ')" -ForegroundColor DarkGray

# Inno's own event functions do not need to be referenced.
$referenced = New-Object System.Collections.Generic.List[string]
foreach ($m in [regex]::Matches($raw, '(?i)\bCheck:\s*([A-Za-z_][A-Za-z0-9_]*)')) {
    $referenced.Add($m.Groups[1].Value)
}
foreach ($m in [regex]::Matches($raw, '\{code:([A-Za-z_][A-Za-z0-9_]*)')) {
    $referenced.Add($m.Groups[1].Value)
}
$referenced = @($referenced | Sort-Object -Unique)
Write-Host "        referenced    : $($referenced -join ', ')" -ForegroundColor DarkGray

$missing = @($referenced | Where-Object { $defined -notcontains $_ })
Assert-True -Name 'every Check:/{code:} reference resolves to a [Code] function' `
            -Condition ($missing.Count -eq 0) -Detail "(missing: $($missing -join ', '))"

# --------------------------------------------------------------------------
# [Components] / [Tasks] names referenced from [Code]
# --------------------------------------------------------------------------
function Get-EntryNames {
    param([string[]]$Entries)
    $names = New-Object System.Collections.Generic.List[string]
    foreach ($e in $Entries) {
        $m = [regex]::Match($e, '(?i)\bName:\s*"([^"]+)"')
        if ($m.Success) { $names.Add($m.Groups[1].Value) }
    }
    return $names
}

$componentNames = Get-EntryNames -Entries $bySection['Components']
$taskNames = Get-EntryNames -Entries $bySection['Tasks']
Write-Host "        components    : $($componentNames -join ', ')" -ForegroundColor DarkGray
Write-Host "        tasks         : $($taskNames -join ', ')" -ForegroundColor DarkGray

$badComponentRefs = New-Object System.Collections.Generic.List[string]
foreach ($m in [regex]::Matches($codeText, "WizardIsComponentSelected\('([^']+)'\)")) {
    if ($componentNames -notcontains $m.Groups[1].Value) { $badComponentRefs.Add($m.Groups[1].Value) }
}
Assert-True -Name 'WizardIsComponentSelected only names declared components' `
            -Condition ($badComponentRefs.Count -eq 0) -Detail "(bad: $($badComponentRefs -join ', '))"

$badTaskRefs = New-Object System.Collections.Generic.List[string]
foreach ($m in [regex]::Matches($codeText, "WizardIsTaskSelected\('([^']+)'\)")) {
    if ($taskNames -notcontains $m.Groups[1].Value) { $badTaskRefs.Add($m.Groups[1].Value) }
}
Assert-True -Name 'WizardIsTaskSelected only names declared tasks' `
            -Condition ($badTaskRefs.Count -eq 0) -Detail "(bad: $($badTaskRefs -join ', '))"

# Components referenced from other sections must exist too.
$badSectionComponents = New-Object System.Collections.Generic.List[string]
foreach ($sec in @('Files', 'Icons', 'Run', 'Dirs')) {
    foreach ($e in $bySection[$sec]) {
        $m = [regex]::Match($e, '(?i)\bComponents:\s*([A-Za-z0-9_ ]+)')
        if (-not $m.Success) { continue }
        foreach ($c in ($m.Groups[1].Value -split '\s+' | Where-Object { $_ })) {
            if ($componentNames -notcontains $c) { $badSectionComponents.Add("$sec -> $c") }
        }
    }
}
Assert-True -Name 'Components: references in other sections resolve' `
            -Condition ($badSectionComponents.Count -eq 0) -Detail "($($badSectionComponents -join '; '))"

# --------------------------------------------------------------------------
# Flags
# --------------------------------------------------------------------------
$validFlags = @{
    'Files' = @('ignoreversion', 'recursesubdirs', 'createallsubdirs', 'confirmoverwrite',
                'deleteafterinstall', 'dontcopy', 'external', 'onlyifdoesntexist',
                'onlyifdestfileexists', 'overwritereadonly', 'promptifolder', 'replacesameversion',
                'restartreplace', 'sharedfile', 'skipifsourcedoesntexist', 'sortfilesbyextension',
                'sortfilesbyname', 'touch', 'uninsneveruninstall', 'uninsremovereadonly',
                'uninsrestartdelete', 'nocompression', 'noencryption', 'noregerror', 'setntfscompression',
                'unsetntfscompression', 'solidbreak', 'is64bit', 'is32bit', 'gacinstall', 'regserver',
                'regtypelib', 'sign', 'signonce', 'signcheck', 'download', 'extractarchive')
    'Dirs' = @('deleteafterinstall', 'uninsalwaysuninstall', 'uninsneveruninstall', 'setntfscompression',
               'unsetntfscompression')
    'Icons' = @('createonlyiffileexists', 'closeonexit', 'dontcloseonexit', 'excludefromshowinnewinstall',
                'foldershortcut', 'preventpinning', 'runmaximized', 'runminimized', 'uninsneveruninstall',
                'useapppaths')
    'Run' = @('hidewizard', 'nowait', 'postinstall', 'runascurrentuser', 'runasoriginaluser',
              'runhidden', 'runmaximized', 'runminimized', 'shellexec', 'skipifdoesntexist',
              'skipifnotsilent', 'skipifsilent', 'unchecked', 'waituntilidle', 'waituntilterminated',
              'dontlogparameters', 'logoutput', '64bit', '32bit')
    'UninstallRun' = @('hidewizard', 'nowait', 'runascurrentuser', 'runasoriginaluser', 'runhidden',
                       'runmaximized', 'runminimized', 'shellexec', 'skipifdoesntexist',
                       'waituntilidle', 'waituntilterminated', 'dontlogparameters', 'logoutput',
                       '64bit', '32bit')
    'Components' = @('checkablealone', 'dontinheritcheck', 'exclusive', 'fixed', 'restart', 'disablenouninstallwarning')
    'Tasks' = @('checkablealone', 'checkedonce', 'dontinheritcheck', 'exclusive', 'restart', 'unchecked')
    'Types' = @('iscustom')
}

$badFlags = New-Object System.Collections.Generic.List[string]
foreach ($sec in $validFlags.Keys) {
    foreach ($e in $bySection[$sec]) {
        $m = [regex]::Match($e, '(?i)\bFlags:\s*([A-Za-z0-9_ ]+)')
        if (-not $m.Success) { continue }
        foreach ($flag in ($m.Groups[1].Value -split '\s+' | Where-Object { $_ })) {
            if ($validFlags[$sec] -notcontains $flag.ToLowerInvariant()) {
                $badFlags.Add("[$sec] $flag")
            }
        }
    }
}
Assert-True -Name 'every Flags: value is valid for its section' `
            -Condition ($badFlags.Count -eq 0) -Detail "($($badFlags -join '; '))"

# --------------------------------------------------------------------------
# Preprocessor defines used by the build must be declared or defaulted
# --------------------------------------------------------------------------
foreach ($def in @('AppVersion', 'PayloadDir', 'OutputDir', 'OutputBase')) {
    Assert-True -Name "preprocessor symbol $def is defined or guarded" `
                -Condition ($raw -match "(?m)^\s*#(?:define|ifndef)\s+$def\b")
}

# --------------------------------------------------------------------------
# The bootstrap must actually be invoked, with the project root
# --------------------------------------------------------------------------
$runText = ($bySection['Run'] -join "`n")
Assert-True -Name '[Run] invokes Bootstrap-RedSight.ps1' -Condition ($runText -match 'Bootstrap-RedSight\.ps1')
Assert-True -Name '[Run] passes -ProjectRoot to the bootstrap' -Condition ($runText -match '-ProjectRoot')
Assert-True -Name '[Run] passes the wizard-derived arguments' -Condition ($runText -match '\{code:GetBootstrapArgs\}')
Assert-True -Name '[Run] waits for the bootstrap to finish' -Condition ($runText -match 'waituntilterminated')
Assert-True -Name '[Run] uses powershell.exe rather than a bare .ps1' `
            -Condition ($runText -match 'powershell\.exe')

# A .ps1 as an [Icons] Filename opens in an editor instead of running.
$iconFilenames = @()
foreach ($e in $bySection['Icons']) {
    $m = [regex]::Match($e, '(?i)\bFilename:\s*"([^"]+)"')
    if ($m.Success) { $iconFilenames += $m.Groups[1].Value }
}
$ps1Targets = @($iconFilenames | Where-Object { $_ -like '*.ps1' })
Assert-True -Name 'no shortcut targets a .ps1 directly' `
            -Condition ($ps1Targets.Count -eq 0) -Detail "($($ps1Targets -join ', '))"

# --------------------------------------------------------------------------
# Pascal begin/end balance in [Code]
# --------------------------------------------------------------------------
$stripped = [regex]::Replace($codeText, "'[^']*'", "''")             # string literals
$stripped = [regex]::Replace($stripped, '(?s)\{[^}]*\}', ' ')        # { comments }
$stripped = [regex]::Replace($stripped, '(?m)//.*$', ' ')            # // comments
$beginCount = ([regex]::Matches($stripped, '(?i)\bbegin\b')).Count
$endCount = ([regex]::Matches($stripped, '(?i)\bend\b')).Count
Assert-True -Name '[Code] begin/end are balanced' `
            -Condition ($beginCount -eq $endCount) -Detail "(begin=$beginCount end=$endCount)"

# --------------------------------------------------------------------------
Write-Host ("`n" + ('=' * 60)) -ForegroundColor Cyan
Write-Host ("  {0} passed, {1} failed" -f $script:Pass, $script:Fail) -ForegroundColor $(if ($script:Fail) { 'Red' } else { 'Green' })
Write-Host ('=' * 60) -ForegroundColor Cyan
if ($script:Fail) {
    foreach ($f in $script:Failures) { Write-Host "  - $f" -ForegroundColor Red }
    exit 1
}
exit 0
