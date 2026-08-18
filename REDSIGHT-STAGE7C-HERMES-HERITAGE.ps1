$ErrorActionPreference = "Stop"

# =====================================================================
# REDSIGHT STAGE-7C
# HERMES HERITAGE MIGRATION
#
# Migrates:
#   - SOUL.md
#   - MEMORY.md
#   - USER.md
#   - Local/self-taught skills
#   - Hermes cron/scheduled definitions
#   - MCP configuration/inventory
#   - Installed-skill inventory
#
# Adds:
#   - HERMES HERITAGE side panel
#   - REDSIGHT red brand/logo header
#   - Soul/Memory/User tabs
#   - Searchable Skills browser
#   - MCP server tab
#   - Automatic Hermes context injection into Command Center chat
#   - Read-only heritage mount into Docker
#   - Best-effort NON-DESTRUCTIVE RAG indexing
#
# Does NOT:
#   - delete Hermes
#   - delete Qdrant
#   - delete RedSight data
#   - call the destructive collection reindex endpoint
# =====================================================================

$Root       = "C:\Users\walim\RedSight"
$UI         = Join-Path $Root "app\ui\command_center.py"
$PanelPy    = Join-Path $Root "app\ui\heritage_panel.py"
$Launcher   = Join-Path $Root "launch_redsight_command_center.py"
$UiVenv     = Join-Path $Root ".venv-ui"
$UiPython   = Join-Path $UiVenv "Scripts\python.exe"
$Override   = Join-Path $Root "docker-compose.override.yml"

$HeritageRoot = Join-Path $Root "data\heritage\hermes"
$PrivateRoot  = Join-Path $env:LOCALAPPDATA "RedSight\private"

$Stamp      = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot = Join-Path $Root ".repair-backups\stage7c-hermes-$Stamp"

$Utf8 = New-Object System.Text.UTF8Encoding($false)

Set-Location $Root

New-Item -ItemType Directory -Path $BackupRoot -Force | Out-Null
New-Item -ItemType Directory -Path $PrivateRoot -Force | Out-Null

function Write-Utf8 {
    param(
        [string]$Path,
        [string]$Text
    )

    [System.IO.File]::WriteAllText(
        $Path,
        $Text,
        $script:Utf8
    )
}

function Test-DockerEngine {

    $ErrorActionPreference = "Continue"

    docker info `
        --format "{{.ServerVersion}}" `
        1>$null `
        2>$null

    $Code = $LASTEXITCODE

    $ErrorActionPreference = "Stop"

    return ($Code -eq 0)
}

Write-Host ""
Write-Host "===================================================================="
Write-Host " REDSIGHT STAGE-7C"
Write-Host " HERMES SOUL + MEMORY + SKILLS + MCP HERITAGE MIGRATION"
Write-Host "===================================================================="
Write-Host ""

# =====================================================================
# 1. VERIFY WINDOWS UI ENVIRONMENT
# =====================================================================

if (-not (Test-Path $UI)) {
    throw "Missing Command Center source: $UI"
}

if (-not (Test-Path $Launcher)) {
    throw "Missing qasync launcher: $Launcher"
}

if (-not (Test-Path $UiPython)) {
    throw "Missing UI Python environment: $UiPython"
}

if (-not (Test-Path $Override)) {
    throw "Missing docker-compose.override.yml"
}

# =====================================================================
# 2. DISCOVER REAL HERMES HOME
# =====================================================================

Write-Host "=== Discovering Hermes home ==="

$HermesCandidates = @()

if ($env:HERMES_HOME) {
    $HermesCandidates += $env:HERMES_HOME
}

$HermesCandidates += @(
    (Join-Path $env:LOCALAPPDATA "hermes"),
    (Join-Path $env:USERPROFILE ".hermes"),
    (Join-Path $env:APPDATA "hermes")
)

$HermesHome = $null

foreach ($Candidate in ($HermesCandidates | Select-Object -Unique)) {

    if (-not (Test-Path $Candidate)) {
        continue
    }

    if (
        (Test-Path (Join-Path $Candidate "config.yaml")) -or
        (Test-Path (Join-Path $Candidate "memories")) -or
        (Test-Path (Join-Path $Candidate "skills"))
    ) {

        $HermesHome = $Candidate
        break
    }
}

if (-not $HermesHome) {
    throw "Could not locate a valid Hermes home."
}

Write-Host "HERMES_HOME:"
Write-Host $HermesHome
Write-Host ""

# =====================================================================
# 3. BACKUP FILES WE WILL MODIFY
# =====================================================================

Write-Host "=== Creating RedSight backups ==="

Copy-Item `
    -LiteralPath $UI `
    -Destination (Join-Path $BackupRoot "command_center.py.before") `
    -Force

Copy-Item `
    -LiteralPath $Launcher `
    -Destination (Join-Path $BackupRoot "launcher.before.py") `
    -Force

Copy-Item `
    -LiteralPath $Override `
    -Destination (Join-Path $BackupRoot "docker-compose.override.yml.before") `
    -Force

if (Test-Path $PanelPy) {

    Copy-Item `
        -LiteralPath $PanelPy `
        -Destination (Join-Path $BackupRoot "heritage_panel.py.before") `
        -Force
}

Write-Host "Backup:"
Write-Host $BackupRoot
Write-Host ""

# =====================================================================
# 4. RECREATE ONLY THE DERIVED HERITAGE COPY
#
# The original Hermes files remain untouched.
# =====================================================================

if (Test-Path $HeritageRoot) {

    Remove-Item `
        -LiteralPath $HeritageRoot `
        -Recurse `
        -Force
}

New-Item `
    -ItemType Directory `
    -Path $HeritageRoot `
    -Force |
    Out-Null

New-Item `
    -ItemType Directory `
    -Path (Join-Path $HeritageRoot "memories") `
    -Force |
    Out-Null

New-Item `
    -ItemType Directory `
    -Path (Join-Path $HeritageRoot "skills") `
    -Force |
    Out-Null

New-Item `
    -ItemType Directory `
    -Path (Join-Path $HeritageRoot "context") `
    -Force |
    Out-Null

# =====================================================================
# 5. MIGRATE HERMES SOUL
# =====================================================================

Write-Host "===================================================================="
Write-Host " MIGRATING HERMES SOUL"
Write-Host "===================================================================="

$SoulCandidates = @(
    (Join-Path $HermesHome "SOUL.md"),
    (Join-Path $env:USERPROFILE ".hermes\SOUL.md")
) | Select-Object -Unique

$SoulSource = $null

foreach ($Candidate in $SoulCandidates) {

    if (Test-Path $Candidate) {

        $SoulSource = $Candidate
        break
    }
}

if ($SoulSource) {

    Copy-Item `
        -LiteralPath $SoulSource `
        -Destination (Join-Path $HeritageRoot "SOUL.md") `
        -Force

    Write-Host "SOUL migrated:"
    Write-Host $SoulSource
}
else {

    Write-Warning "No SOUL.md was found at the expected Hermes locations."

    Write-Utf8 `
        -Path (Join-Path $HeritageRoot "SOUL.md") `
        -Text "# Hermes Soul`r`n`r`nNo Hermes SOUL.md was found during migration."
}

Write-Host ""

# =====================================================================
# 6. MIGRATE MEMORY + USER PROFILE
# =====================================================================

Write-Host "===================================================================="
Write-Host " MIGRATING HERMES MEMORY"
Write-Host "===================================================================="

$MemoryRoot =
    Join-Path $HermesHome "memories"

foreach ($Name in @(
    "MEMORY.md",
    "USER.md"
)) {

    $Source =
        Join-Path $MemoryRoot $Name

    if (Test-Path $Source) {

        Copy-Item `
            -LiteralPath $Source `
            -Destination (Join-Path $HeritageRoot "memories\$Name") `
            -Force

        Write-Host "$Name migrated."
    }
    else {

        Write-Warning "$Name was not found at $Source"
    }
}

Write-Host ""

# =====================================================================
# 7. MIGRATE USEFUL CONTEXT FILES
# =====================================================================

Write-Host "=== Migrating context/instruction files ==="

foreach ($Name in @(
    "AGENTS.md",
    "HERMES.md",
    ".hermes.md",
    "CLAUDE.md"
)) {

    foreach ($Base in @(
        $HermesHome,
        $env:USERPROFILE,
        $Root
    )) {

        $Candidate =
            Join-Path $Base $Name

        if (-not (Test-Path $Candidate)) {
            continue
        }

        $SafeBase =
            (
                Split-Path $Base -Leaf
            ) -replace '[^A-Za-z0-9_.-]', '_'

        $Destination =
            Join-Path `
                (Join-Path $HeritageRoot "context") `
                ($SafeBase + "-" + $Name)

        Copy-Item `
            -LiteralPath $Candidate `
            -Destination $Destination `
            -Force
    }
}

# =====================================================================
# 8. MIGRATE SELF-TAUGHT / LOCAL SKILLS
# =====================================================================

Write-Host ""
Write-Host "===================================================================="
Write-Host " MIGRATING HERMES SKILLS"
Write-Host "===================================================================="

$SkillRoots = @(
    [PSCustomObject]@{
        Name = "hermes-home"
        Path = (Join-Path $HermesHome "skills")
    },

    [PSCustomObject]@{
        Name = "dot-hermes"
        Path = (Join-Path $env:USERPROFILE ".hermes\skills")
    }
)

foreach ($SkillRoot in $SkillRoots) {

    if (-not (Test-Path $SkillRoot.Path)) {

        Write-Host "Not present: $($SkillRoot.Path)"
        continue
    }

    $Destination =
        Join-Path `
            (Join-Path $HeritageRoot "skills") `
            $SkillRoot.Name

    New-Item `
        -ItemType Directory `
        -Path $Destination `
        -Force |
        Out-Null

    Write-Host ""
    Write-Host "Copying:"
    Write-Host $SkillRoot.Path
    Write-Host " -> "
    Write-Host $Destination

    $ErrorActionPreference = "Continue"

    robocopy `
        $SkillRoot.Path `
        $Destination `
        /E `
        /COPY:DAT `
        /DCOPY:DAT `
        /R:1 `
        /W:1 `
        /XD `
            ".archive" `
            "__pycache__" `
            ".git" `
            "node_modules" `
        /XF `
            "*.pyc" `
        /NFL `
        /NDL `
        /NJH `
        /NJS `
        /NP

    $RoboExit =
        $LASTEXITCODE

    $ErrorActionPreference = "Stop"

    # Robocopy 0-7 = success / nonfatal copy differences.
    if ($RoboExit -gt 7) {
        throw "Skill migration failed for $($SkillRoot.Path), robocopy exit $RoboExit"
    }
}

# =====================================================================
# 9. MIGRATE HERMES CRON / AUTOMATION DEFINITIONS
# =====================================================================

$CronSource =
    Join-Path $HermesHome "cron"

if (Test-Path $CronSource) {

    Write-Host ""
    Write-Host "Migrating Hermes cron definitions..."

    Copy-Item `
        -LiteralPath $CronSource `
        -Destination (Join-Path $HeritageRoot "cron") `
        -Recurse `
        -Force
}

# =====================================================================
# 10. PRESERVE PRIVATE HERMES CONFIG OUTSIDE THE REDSIGHT REPOSITORY
#
# This keeps MCP environment/header secrets out of the visible UI/RAG.
# =====================================================================

Write-Host ""
Write-Host "===================================================================="
Write-Host " MIGRATING MCP CONFIGURATION"
Write-Host "===================================================================="

$HermesConfig =
    Join-Path $HermesHome "config.yaml"

$PrivateConfig =
    Join-Path $PrivateRoot "hermes-config.yaml"

if (Test-Path $HermesConfig) {

    Copy-Item `
        -LiteralPath $HermesConfig `
        -Destination $PrivateConfig `
        -Force

    Write-Host "Private Hermes configuration preserved at:"
    Write-Host $PrivateConfig

    $ErrorActionPreference = "Continue"

    icacls `
        $PrivateRoot `
        /inheritance:r `
        /grant:r "$env:USERNAME:(OI)(CI)F" `
        1>$null `
        2>$null

    $ErrorActionPreference = "Stop"
}
else {

    Write-Warning "Hermes config.yaml was not found."
}

# =====================================================================
# 11. EXPORT LIVE HERMES MCP + SKILL INVENTORIES
# =====================================================================

$HermesExe =
    Get-Command hermes `
        -ErrorAction SilentlyContinue

$McpInventory =
    Join-Path $HeritageRoot "MCP_SERVERS.md"

$SkillInventory =
    Join-Path $HeritageRoot "INSTALLED_SKILLS.txt"

$McpRaw = ""

if ($HermesExe) {

    Write-Host ""
    Write-Host "Reading Hermes MCP server inventory..."

    $ErrorActionPreference = "Continue"

    $McpLines =
        & hermes mcp list 2>&1

    $McpExit =
        $LASTEXITCODE

    $ErrorActionPreference = "Stop"

    $McpRaw =
        $McpLines | Out-String

    Write-Utf8 `
        -Path $McpInventory `
        -Text (
            "# Migrated Hermes MCP Servers`r`n`r`n" +
            "Source HERMES_HOME: $HermesHome`r`n`r`n" +
            "```text`r`n" +
            $McpRaw +
            "`r`n```"
        )

    Write-Host $McpRaw

    Write-Host ""
    Write-Host "Reading Hermes installed-skill inventory..."

    $ErrorActionPreference = "Continue"

    $SkillLines =
        & hermes skills list 2>&1

    $ErrorActionPreference = "Stop"

    Write-Utf8 `
        -Path $SkillInventory `
        -Text ($SkillLines | Out-String)
}
else {

    Write-Warning "hermes executable was not found in PATH."

    Write-Utf8 `
        -Path $McpInventory `
        -Text "# Migrated Hermes MCP Servers`r`n`r`nHermes CLI unavailable during migration."
}

# =====================================================================
# 12. BUILD SEARCHABLE SKILL CATALOG
# =====================================================================

Write-Host ""
Write-Host "===================================================================="
Write-Host " BUILDING REDSIGHT SKILL CATALOG"
Write-Host "===================================================================="

$Catalog = @()

$SkillFiles =
    Get-ChildItem `
        (Join-Path $HeritageRoot "skills") `
        -Recurse `
        -File `
        -Filter "SKILL.md" `
        -ErrorAction SilentlyContinue

foreach ($SkillFile in $SkillFiles) {

    $Content =
        Get-Content `
            -LiteralPath $SkillFile.FullName `
            -Raw `
            -ErrorAction SilentlyContinue

    if ($null -eq $Content) {
        continue
    }

    $SkillName =
        $SkillFile.Directory.Name

    $NameMatch =
        [regex]::Match(
            $Content,
            '(?im)^\s*name\s*:\s*["'']?(.+?)["'']?\s*$'
        )

    if ($NameMatch.Success) {
        $SkillName = $NameMatch.Groups[1].Value.Trim()
    }

    $Description = ""

    $DescriptionMatch =
        [regex]::Match(
            $Content,
            '(?im)^\s*description\s*:\s*["'']?(.+?)["'']?\s*$'
        )

    if ($DescriptionMatch.Success) {

        $Description =
            $DescriptionMatch.Groups[1].Value.Trim()
    }

    if (-not $Description) {

        $Paragraphs =
            $Content `
                -split "(`r`n|`n){2,}"

        foreach ($Paragraph in $Paragraphs) {

            $Candidate =
                $Paragraph.Trim()

            if (-not $Candidate) {
                continue
            }

            if ($Candidate.StartsWith("---")) {
                continue
            }

            if ($Candidate.StartsWith("#")) {
                continue
            }

            if ($Candidate.Length -gt 20) {

                $Description =
                    $Candidate.Replace("`r", " ").Replace("`n", " ")

                if ($Description.Length -gt 350) {
                    $Description = $Description.Substring(0,350)
                }

                break
            }
        }
    }

    $Hash =
        Get-FileHash `
            -LiteralPath $SkillFile.FullName `
            -Algorithm SHA256

    $Relative =
        $SkillFile.FullName.Substring(
            $HeritageRoot.Length
        ).TrimStart("\")

    $Source =
        "unknown"

    if ($Relative -like "skills\hermes-home\*") {
        $Source = "hermes-home"
    }

    if ($Relative -like "skills\dot-hermes\*") {
        $Source = "dot-hermes"
    }

    $Catalog +=
        [PSCustomObject]@{
            Name         = $SkillName
            Description  = $Description
            Source       = $Source
            RelativePath = $Relative
            SHA256       = $Hash.Hash
            Size         = $SkillFile.Length
            Modified     = $SkillFile.LastWriteTime.ToString("o")
        }
}

$Catalog =
    $Catalog |
    Sort-Object Name, Source

$CatalogPath =
    Join-Path $HeritageRoot "skills_catalog.json"

$Catalog |
    ConvertTo-Json -Depth 8 |
    Set-Content `
        -LiteralPath $CatalogPath `
        -Encoding UTF8

Write-Host "Migrated SKILL.md files: $($Catalog.Count)"
Write-Host ""

# =====================================================================
# 13. BUILD HERITAGE MANIFEST
# =====================================================================

$Manifest =
    [PSCustomObject]@{
        migrated_at       = (Get-Date).ToString("o")
        source             = "Hermes Agent"
        hermes_home        = $HermesHome
        soul_present       = (Test-Path (Join-Path $HeritageRoot "SOUL.md"))
        memory_present     = (Test-Path (Join-Path $HeritageRoot "memories\MEMORY.md"))
        user_present       = (Test-Path (Join-Path $HeritageRoot "memories\USER.md"))
        skill_count        = $Catalog.Count
        mcp_inventory      = $McpInventory
        private_config     = $PrivateConfig
        cron_present       = (Test-Path (Join-Path $HeritageRoot "cron"))
        mode               = "preserved + visible + RAG candidate + chat-context inheritance"
    }

$Manifest |
    ConvertTo-Json -Depth 8 |
    Set-Content `
        -LiteralPath (Join-Path $HeritageRoot "heritage_manifest.json") `
        -Encoding UTF8

# =====================================================================
# 14. PERSIST READ-ONLY HERITAGE MOUNT INTO REDSIGHT CONTAINER
# =====================================================================

Write-Host "===================================================================="
Write-Host " ADDING READ-ONLY HERITAGE MOUNT"
Write-Host "===================================================================="

$Lines =
    New-Object `
        'System.Collections.Generic.List[string]'

Get-Content `
    -LiteralPath $Override |
ForEach-Object {

    [void]$Lines.Add($_)
}

$RedStart = -1
$RedEnd   = $Lines.Count - 1

for ($i = 0; $i -lt $Lines.Count; $i++) {

    if ($Lines[$i] -match '^\s{2}redsight:\s*$') {

        $RedStart = $i
        break
    }
}

if ($RedStart -lt 0) {
    throw "Could not locate redsight service in docker-compose.override.yml"
}

for ($i = $RedStart + 1; $i -lt $Lines.Count; $i++) {

    if ($Lines[$i] -match '^\s{2}[A-Za-z0-9_.-]+:\s*$') {

        $RedEnd = $i - 1
        break
    }
}

$MountLine =
    '      - "./data/heritage:/heritage:ro"'

$MountExists =
    $false

for ($i = $RedStart; $i -le $RedEnd; $i++) {

    if ($Lines[$i] -match 'data/heritage:/heritage:ro') {

        $MountExists = $true
        break
    }
}

if (-not $MountExists) {

    $VolumeIndex = -1

    for ($i = $RedStart + 1; $i -le $RedEnd; $i++) {

        if ($Lines[$i] -match '^\s{4}volumes:\s*$') {

            $VolumeIndex = $i
            break
        }
    }

    if ($VolumeIndex -ge 0) {

        $Lines.Insert(
            $VolumeIndex + 1,
            $MountLine
        )
    }
    else {

        $InsertIndex = $RedStart + 1

        for ($i = $RedStart + 1; $i -le $RedEnd; $i++) {

            if ($Lines[$i] -match '^\s{4}environment:\s*$') {

                $InsertIndex = $i
                break
            }
        }

        $Lines.Insert(
            $InsertIndex,
            '    volumes:'
        )

        $Lines.Insert(
            $InsertIndex + 1,
            $MountLine
        )
    }

    [System.IO.File]::WriteAllLines(
        $Override,
        $Lines,
        $Utf8
    )

    Write-Host "Heritage mount added."
}
else {

    Write-Host "Heritage mount already configured."
}

Write-Host ""

# =====================================================================
# 15. MAKE HERMES SOUL / MEMORY / RELEVANT SKILLS FUNCTIONAL IN CHAT
#
# This does not pretend to execute a SKILL.md.
#
# Instead:
#   SOUL -> system identity/context
#   MEMORY/USER -> inherited personal context
#   relevant SKILL.md -> procedural guidance selected per prompt
#   MCP inventory -> available ecosystem awareness
# =====================================================================

Write-Host "===================================================================="
Write-Host " WIRING HERMES HERITAGE INTO COMMAND CENTER CHAT"
Write-Host "===================================================================="

$UiText =
    [System.IO.File]::ReadAllText($UI)

$BeginMarker =
    "# REDSIGHT_HERITAGE_CONTEXT_BEGIN"

$EndMarker =
    "# REDSIGHT_HERITAGE_CONTEXT_END"

$MarkerPattern =
    '(?s)' +
    [regex]::Escape($BeginMarker) +
    '.*?' +
    [regex]::Escape($EndMarker) +
    '\s*'

$UiText =
    [regex]::Replace(
        $UiText,
        $MarkerPattern,
        ""
    )

$HelperLines = @(
    '# REDSIGHT_HERITAGE_CONTEXT_BEGIN'
    'def _redsight_heritage_messages(message):'
    '    from pathlib import Path'
    '    import json'
    '    import re'
    ''
    '    root = Path(__file__).resolve().parents[2] / "data" / "heritage" / "hermes"'
    ''
    '    parts = ['
    '        "You are RedSight. You have inherited selected identity, memory, user-profile, procedural skill, and MCP context from the user''s Hermes Agent. Use it when relevant. Current user instructions always take precedence. A SKILL.md describes procedure; do not claim a tool was executed merely because a skill describes it."'
    '    ]'
    ''
    '    def add_text(label, path, limit):'
    '        try:'
    '            text = path.read_text(encoding="utf-8", errors="replace").strip()'
    '        except Exception:'
    '            return'
    '        if text:'
    '            parts.append("[" + label + "]\n" + text[:limit])'
    ''
    '    add_text("Inherited Hermes SOUL", root / "SOUL.md", 6000)'
    '    add_text("Inherited Hermes MEMORY", root / "memories" / "MEMORY.md", 6000)'
    '    add_text("Inherited Hermes USER profile", root / "memories" / "USER.md", 5000)'
    ''
    '    try:'
    '        catalog = json.loads((root / "skills_catalog.json").read_text(encoding="utf-8-sig"))'
    '    except Exception:'
    '        catalog = []'
    ''
    '    terms = set(re.findall(r"[a-zA-Z0-9_+.-]{3,}", str(message).lower()))'
    '    scored = []'
    ''
    '    for item in catalog:'
    '        hay = ("{} {} {}".format(item.get("Name", ""), item.get("Description", ""), item.get("Source", ""))).lower()'
    '        score = sum(1 for term in terms if term in hay)'
    '        if score:'
    '            scored.append((score, item))'
    ''
    '    scored.sort(key=lambda pair: pair[0], reverse=True)'
    ''
    '    for _, item in scored[:3]:'
    '        relative = item.get("RelativePath", "")'
    '        if not relative:'
    '            continue'
    '        path = root / relative'
    '        try:'
    '            skill_text = path.read_text(encoding="utf-8", errors="replace").strip()'
    '        except Exception:'
    '            continue'
    '        if skill_text:'
    '            parts.append("[Relevant inherited Hermes skill: {}]\n{}".format(item.get("Name", "skill"), skill_text[:4000]))'
    ''
    '    add_text("Migrated MCP server inventory", root / "MCP_SERVERS.md", 3000)'
    ''
    '    system_context = "\n\n".join(parts)'
    ''
    '    return ['
    '        {"role": "system", "content": system_context},'
    '        {"role": "user", "content": str(message)},'
    '    ]'
    '# REDSIGHT_HERITAGE_CONTEXT_END'
    ''
)

$Helper =
    $HelperLines -join "`r`n"

$ClassMatch =
    [regex]::Match(
        $UiText,
        '(?m)^class\s+CommandCenterMainWindow\b'
    )

if (-not $ClassMatch.Success) {
    throw "CommandCenterMainWindow class was not found."
}

$UiText =
    $UiText.Insert(
        $ClassMatch.Index,
        $Helper + "`r`n"
    )

if (
    $UiText.Contains(
        'json={"messages": _redsight_heritage_messages(message), "stream": False}'
    )
) {

    Write-Host "Heritage request context was already wired."
}
else {

    $OriginalRequest =
        'json={"messages": [{"role": "user", "content": message}], "stream": False}'

    if ($UiText.Contains($OriginalRequest)) {

        $UiText =
            $UiText.Replace(
                $OriginalRequest,
                'json={"messages": _redsight_heritage_messages(message), "stream": False}'
            )
    }
    else {

        $RequestPattern =
            'json\s*=\s*\{\s*"messages"\s*:\s*\[\s*\{\s*"role"\s*:\s*"user"\s*,\s*"content"\s*:\s*message\s*\}\s*\]\s*,\s*"stream"\s*:\s*False\s*\}'

        $NewUiText =
            [regex]::Replace(
                $UiText,
                $RequestPattern,
                'json={"messages": _redsight_heritage_messages(message), "stream": False}',
                1
            )

        if ($NewUiText -eq $UiText) {

            Write-Host ""
            Write-Host "Current _send_to_api context:"
            Write-Host ""

            Select-String `
                -Path $UI `
                -Pattern "_send_to_api" `
                -Context 0,65

            throw "Could not safely locate the current chat messages payload."
        }

        $UiText = $NewUiText
    }
}

[System.IO.File]::WriteAllText(
    $UI,
    $UiText,
    $Utf8
)

Write-Host "Hermes context injection: ENABLED"
Write-Host ""

# =====================================================================
# 16. BUILD HERMES HERITAGE SIDE PANEL + REDSIGHT LOGO
# =====================================================================

Write-Host "===================================================================="
Write-Host " BUILDING HERMES HERITAGE SIDE PANEL + REDSIGHT LOGO"
Write-Host "===================================================================="

$PanelLines = @(
    'from __future__ import annotations'
    ''
    'import json'
    'from pathlib import Path'
    ''
    'from PySide6.QtCore import Qt'
    'from PySide6.QtGui import QFont'
    'from PySide6.QtWidgets import ('
    '    QDockWidget,'
    '    QLabel,'
    '    QLineEdit,'
    '    QListWidget,'
    '    QSplitter,'
    '    QTabWidget,'
    '    QTextBrowser,'
    '    QToolBar,'
    '    QVBoxLayout,'
    '    QWidget,'
    ')'
    ''
    ''
    'def _read(path: Path) -> str:'
    '    try:'
    '        return path.read_text(encoding="utf-8-sig", errors="replace")'
    '    except Exception as exc:'
    '        return "Unavailable: " + str(exc)'
    ''
    ''
    'class HermesHeritageDock(QDockWidget):'
    '    def __init__(self, root: Path, parent=None):'
    '        super().__init__("HERMES HERITAGE", parent)'
    '        self.root = root'
    '        self.catalog = []'
    ''
    '        self.setObjectName("RedSightHermesHeritageDock")'
    '        self.setMinimumWidth(440)'
    ''
    '        tabs = QTabWidget()'
    ''
    '        self.overview = QTextBrowser()'
    '        self.soul = QTextBrowser()'
    '        self.memory = QTextBrowser()'
    '        self.mcp = QTextBrowser()'
    ''
    '        tabs.addTab(self.overview, "Overview")'
    '        tabs.addTab(self.soul, "Soul")'
    '        tabs.addTab(self.memory, "Memory")'
    '        tabs.addTab(self._build_skills_tab(), "Skills")'
    '        tabs.addTab(self.mcp, "MCP")'
    ''
    '        holder = QWidget()'
    '        layout = QVBoxLayout(holder)'
    '        layout.setContentsMargins(6, 6, 6, 6)'
    '        layout.addWidget(tabs)'
    ''
    '        self.setWidget(holder)'
    ''
    '        self.setStyleSheet("""'
    '        QDockWidget {'
    '            color: #FFFFFF;'
    '            font-weight: 700;'
    '        }'
    '        QDockWidget::title {'
    '            background: #17090B;'
    '            color: #FF3B3B;'
    '            padding: 8px;'
    '            border-bottom: 1px solid #7A2424;'
    '        }'
    '        QTabWidget::pane {'
    '            border: 1px solid #493238;'
    '            background: #0B0F14;'
    '        }'
    '        QTabBar::tab {'
    '            background: #171C22;'
    '            color: #DDE4EA;'
    '            padding: 7px 9px;'
    '        }'
    '        QTabBar::tab:selected {'
    '            background: #8B171C;'
    '            color: white;'
    '        }'
    '        QTextBrowser, QListWidget, QLineEdit {'
    '            background: #0D1218;'
    '            color: #F3F6F8;'
    '            border: 1px solid #38444F;'
    '            selection-background-color: #A51D24;'
    '            selection-color: white;'
    '        }'
    '        QLineEdit {'
    '            padding: 7px;'
    '            border-radius: 5px;'
    '        }'
    '        """)'
    ''
    '        self.refresh()'
    ''
    '    def _build_skills_tab(self):'
    '        widget = QWidget()'
    '        layout = QVBoxLayout(widget)'
    ''
    '        self.skill_search = QLineEdit()'
    '        self.skill_search.setPlaceholderText("Search inherited Hermes skills...")'
    ''
    '        splitter = QSplitter(Qt.Orientation.Vertical)'
    ''
    '        self.skill_list = QListWidget()'
    '        self.skill_detail = QTextBrowser()'
    ''
    '        splitter.addWidget(self.skill_list)'
    '        splitter.addWidget(self.skill_detail)'
    '        splitter.setSizes([260, 420])'
    ''
    '        layout.addWidget(self.skill_search)'
    '        layout.addWidget(splitter)'
    ''
    '        self.skill_search.textChanged.connect(self._filter_skills)'
    '        self.skill_list.currentRowChanged.connect(self._show_skill)'
    ''
    '        return widget'
    ''
    '    def refresh(self):'
    '        manifest_path = self.root / "heritage_manifest.json"'
    ''
    '        try:'
    '            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))'
    '        except Exception:'
    '            manifest = {}'
    ''
    '        self.overview.setPlainText('
    '            "REDSIGHT HERMES HERITAGE\n\n"'
    '            "Migrated: {}\n"'
    '            "Hermes home: {}\n"'
    '            "Skills: {}\n"'
    '            "SOUL: {}\n"'
    '            "MEMORY: {}\n"'
    '            "USER: {}\n"'
    '            "Cron: {}\n\n"'
    '            "Soul, memory and relevant skill procedures are injected into Command Center chat context automatically."'
    '            .format('
    '                manifest.get("migrated_at", "unknown"),'
    '                manifest.get("hermes_home", "unknown"),'
    '                manifest.get("skill_count", 0),'
    '                manifest.get("soul_present", False),'
    '                manifest.get("memory_present", False),'
    '                manifest.get("user_present", False),'
    '                manifest.get("cron_present", False),'
    '            )'
    '        )'
    ''
    '        self.soul.setPlainText(_read(self.root / "SOUL.md"))'
    ''
    '        memory = _read(self.root / "memories" / "MEMORY.md")'
    '        user = _read(self.root / "memories" / "USER.md")'
    ''
    '        self.memory.setPlainText('
    '            "=== MEMORY.md ===\n\n" + memory +'
    '            "\n\n=== USER.md ===\n\n" + user'
    '        )'
    ''
    '        self.mcp.setPlainText(_read(self.root / "MCP_SERVERS.md"))'
    ''
    '        try:'
    '            self.catalog = json.loads('
    '                (self.root / "skills_catalog.json").read_text(encoding="utf-8-sig")'
    '            )'
    '        except Exception:'
    '            self.catalog = []'
    ''
    '        self._filter_skills(self.skill_search.text())'
    ''
    '    def _filter_skills(self, text):'
    '        query = str(text).strip().lower()'
    '        self.skill_list.clear()'
    '        self._visible_skills = []'
    ''
    '        for skill in self.catalog:'
    '            hay = ("{} {} {}".format('
    '                skill.get("Name", ""),'
    '                skill.get("Description", ""),'
    '                skill.get("Source", ""),'
    '            )).lower()'
    ''
    '            if query and query not in hay:'
    '                continue'
    ''
    '            self._visible_skills.append(skill)'
    '            self.skill_list.addItem('
    '                "{}   [{}]".format('
    '                    skill.get("Name", "skill"),'
    '                    skill.get("Source", "unknown"),'
    '                )'
    '            )'
    ''
    '        if self.skill_list.count():'
    '            self.skill_list.setCurrentRow(0)'
    ''
    '    def _show_skill(self, row):'
    '        if row < 0 or row >= len(getattr(self, "_visible_skills", [])):'
    '            return'
    ''
    '        item = self._visible_skills[row]'
    '        path = self.root / item.get("RelativePath", "")'
    ''
    '        header = ('
    '            "NAME: {}\n"'
    '            "SOURCE: {}\n"'
    '            "SHA256: {}\n"'
    '            "PATH: {}\n\n"'
    '        ).format('
    '            item.get("Name", ""),'
    '            item.get("Source", ""),'
    '            item.get("SHA256", ""),'
    '            item.get("RelativePath", ""),'
    '        )'
    ''
    '        self.skill_detail.setPlainText(header + _read(path))'
    ''
    ''
    'def attach_heritage_ui(window, root):'
    '    root = Path(root)'
    '    heritage_root = root / "data" / "heritage" / "hermes"'
    ''
    '    toolbar = QToolBar("RedSight Brand", window)'
    '    toolbar.setObjectName("RedSightBrandToolbar")'
    '    toolbar.setMovable(False)'
    '    toolbar.setFloatable(False)'
    ''
    '    logo = QLabel("REDSIGHT")'
    '    logo_font = QFont("Bahnschrift SemiBold", 28, QFont.Weight.Black)'
    '    logo_font.setItalic(True)'
    '    logo.setFont(logo_font)'
    '    logo.setStyleSheet('
    '        "color:#FF2A2A;"'
    '        "background:transparent;"'
    '        "font-weight:900;"'
    '        "padding:3px 12px 3px 8px;"'
    '    )'
    ''
    '    subtitle = QLabel("  AGENTIC INTELLIGENCE  •  LOCAL FIRST")'
    '    subtitle.setStyleSheet('
    '        "color:#D7DDE3;"'
    '        "font-weight:600;"'
    '        "padding-left:4px;"'
    '    )'
    ''
    '    toolbar.setStyleSheet('
    '        "QToolBar {"'
    '        "background:#080C11;"'
    '        "border-bottom:1px solid #6E191D;"'
    '        "spacing:4px;"'
    '        "}"'
    '    )'
    ''
    '    toolbar.addWidget(logo)'
    '    toolbar.addWidget(subtitle)'
    ''
    '    window.addToolBar('
    '        Qt.ToolBarArea.TopToolBarArea,'
    '        toolbar,'
    '    )'
    ''
    '    dock = HermesHeritageDock(heritage_root, window)'
    ''
    '    window.addDockWidget('
    '        Qt.DockWidgetArea.LeftDockWidgetArea,'
    '        dock,'
    '    )'
    ''
    '    window._redsight_brand_toolbar = toolbar'
    '    window._redsight_heritage_dock = dock'
    ''
    '    return dock'
)

[System.IO.File]::WriteAllLines(
    $PanelPy,
    $PanelLines,
    $Utf8
)

Write-Host "Heritage side-panel module created:"
Write-Host $PanelPy
Write-Host ""

# =====================================================================
# 17. ATTACH PANEL TO EXISTING QASYNC LAUNCHER
# =====================================================================

$LauncherText =
    [System.IO.File]::ReadAllText(
        $Launcher
    )

$ImportAnchor =
    "from app.ui.command_center import CommandCenterMainWindow"

$HeritageImport =
    "from app.ui.heritage_panel import attach_heritage_ui"

if (-not $LauncherText.Contains($HeritageImport)) {

    if (-not $LauncherText.Contains($ImportAnchor)) {
        throw "Could not locate CommandCenterMainWindow import in launcher."
    }

    $LauncherText =
        $LauncherText.Replace(
            $ImportAnchor,
            $ImportAnchor + "`r`n" + $HeritageImport
        )
}

$WindowAnchor =
    "window = CommandCenterMainWindow()"

$AttachLine =
    "attach_heritage_ui(window, ROOT)"

if (-not $LauncherText.Contains($AttachLine)) {

    if (-not $LauncherText.Contains($WindowAnchor)) {
        throw "Could not locate CommandCenterMainWindow creation in launcher."
    }

    $LauncherText =
        $LauncherText.Replace(
            $WindowAnchor,
            $WindowAnchor + "`r`n" + $AttachLine
        )
}

[System.IO.File]::WriteAllText(
    $Launcher,
    $LauncherText,
    $Utf8
)

# =====================================================================
# 18. PYTHON SYNTAX / IMPORT VALIDATION
# =====================================================================

Write-Host "=== Validating Python ==="

$Validate =
    Join-Path $BackupRoot "validate_stage7c.py"

$ValidateLines = @(
    'import ast'
    'import pathlib'
    'import sys'
    ''
    'root = pathlib.Path(r"C:\Users\walim\RedSight")'
    ''
    'for relative in ['
    '    "app/ui/command_center.py",'
    '    "app/ui/heritage_panel.py",'
    '    "launch_redsight_command_center.py",'
    ']:'
    '    path = root / relative'
    '    source = path.read_text(encoding="utf-8-sig")'
    '    ast.parse(source, filename=str(path))'
    '    print("AST_OK=" + relative)'
    ''
    'sys.path.insert(0, str(root))'
    'import app.ui.command_center'
    'import app.ui.heritage_panel'
    'print("HERITAGE_IMPORT=OK")'
)

[System.IO.File]::WriteAllLines(
    $Validate,
    $ValidateLines,
    $Utf8
)

& $UiPython $Validate

if ($LASTEXITCODE -ne 0) {
    throw "Stage-7C Python validation failed."
}

Write-Host ""

# =====================================================================
# 19. ENSURE DOCKER DESKTOP IS ONLINE
# =====================================================================

Write-Host "===================================================================="
Write-Host " STARTING / VERIFYING DOCKER"
Write-Host "===================================================================="

if (-not (Test-DockerEngine)) {

    Write-Host "Docker engine is offline. Starting Docker Desktop..."

    $ErrorActionPreference = "Continue"

    docker desktop start --detach

    $ErrorActionPreference = "Stop"

    for ($i = 1; $i -le 60; $i++) {

        if (Test-DockerEngine) {
            break
        }

        Write-Host "Waiting for Docker... $i/60"
        Start-Sleep -Seconds 2
    }
}

if (-not (Test-DockerEngine)) {
    throw "Docker Desktop Linux engine is unavailable."
}

Write-Host "Docker engine: ONLINE"
Write-Host ""

# =====================================================================
# 20. VALIDATE COMPOSE
# =====================================================================

$ErrorActionPreference = "Continue"

docker compose config `
    1> (Join-Path $BackupRoot "compose-resolved.yml")

$ComposeCheck =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

if ($ComposeCheck -ne 0) {
    throw "Docker Compose validation failed."
}

Write-Host "Compose validation: PASS"
Write-Host ""

# =====================================================================
# 21. RECREATE REDSIGHT ONLY
#
# Qdrant data is NOT reset.
# =====================================================================

Write-Host "===================================================================="
Write-Host " RESTARTING REDSIGHT BACKEND"
Write-Host "===================================================================="

$ErrorActionPreference = "Continue"

docker compose up `
    -d `
    --force-recreate `
    redsight

$StartExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

if ($StartExit -ne 0) {
    throw "RedSight recreation failed."
}

# =====================================================================
# 22. WAIT FOR HEALTH
# =====================================================================

$Healthy = $false

for ($i = 1; $i -le 60; $i++) {

    $ErrorActionPreference = "Continue"

    $Code =
        curl.exe `
            -s `
            -o NUL `
            -w "%{http_code}" `
            --max-time 4 `
            http://127.0.0.1:8000/api/v1/health `
            2>$null

    $ErrorActionPreference = "Stop"

    Write-Host "RedSight health: $Code"

    if ($Code -eq "200") {

        $Healthy = $true
        break
    }

    Start-Sleep -Seconds 2
}

if (-not $Healthy) {

    docker logs `
        --tail 180 `
        redsight

    throw "RedSight did not become healthy."
}

Write-Host ""
Write-Host "RedSight backend: HEALTHY"
Write-Host ""

# =====================================================================
# 23. VERIFY HERITAGE MOUNT
# =====================================================================

Write-Host "=== Heritage mount inside RedSight ==="

$ErrorActionPreference = "Continue"

docker exec `
    redsight `
    sh -lc `
    "ls -la /heritage/hermes && echo HERITAGE_MOUNT=PASS"

$MountExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

if ($MountExit -ne 0) {
    throw "Heritage volume is not visible inside RedSight."
}

Write-Host ""

# =====================================================================
# 24. NON-DESTRUCTIVE RAG INGESTION
#
# Uses normal indexing jobs.
# DOES NOT call /collections/{collection}/reindex.
# =====================================================================

Write-Host "===================================================================="
Write-Host " NON-DESTRUCTIVE HERMES RAG INGESTION"
Write-Host "===================================================================="

function Invoke-HeritageIndex {

    param(
        [string[]]$Paths,
        [string]$Collection
    )

    if (-not $Paths -or $Paths.Count -eq 0) {
        return
    }

    $Body =
        @{
            paths      = $Paths
            collection = $Collection
            project    = "hermes-heritage"
        } |
        ConvertTo-Json `
            -Depth 6

    Write-Host ""
    Write-Host "Indexing into: $Collection"
    Write-Host "Paths:"
    $Paths | ForEach-Object { Write-Host "  $_" }

    try {

        $Result =
            Invoke-RestMethod `
                -Uri "http://127.0.0.1:8000/api/v1/jobs/index/batch" `
                -Method Post `
                -ContentType "application/json" `
                -Body $Body `
                -TimeoutSec 600

        $Result |
            ConvertTo-Json -Depth 12 |
            Set-Content `
                -LiteralPath (
                    Join-Path `
                        $BackupRoot `
                        ("index-" + $Collection + ".json")
                ) `
                -Encoding UTF8

        Write-Host "Index request completed."
    }
    catch {

        Write-Warning (
            "RAG ingestion into $Collection did not complete: " +
            $_.Exception.Message
        )

        Write-Warning "Migration remains intact; this did not delete existing vectors."
    }
}

$KnowledgePaths = @()

if (Test-Path (Join-Path $HeritageRoot "SOUL.md")) {
    $KnowledgePaths += "/heritage/hermes/SOUL.md"
}

if (Test-Path (Join-Path $HeritageRoot "memories")) {
    $KnowledgePaths += "/heritage/hermes/memories"
}

if (Test-Path (Join-Path $HeritageRoot "context")) {
    $KnowledgePaths += "/heritage/hermes/context"
}

Invoke-HeritageIndex `
    -Paths $KnowledgePaths `
    -Collection "knowledge_docs"

if ($Catalog.Count -gt 0) {

    Invoke-HeritageIndex `
        -Paths @("/heritage/hermes/skills") `
        -Collection "skills_index"
}

Invoke-HeritageIndex `
    -Paths @("/heritage/hermes/MCP_SERVERS.md") `
    -Collection "tool_catalog"

Write-Host ""

# =====================================================================
# 25. CLOSE ONLY OLD COMMAND CENTER PROCESSES
# =====================================================================

Write-Host "=== Closing old Command Center ==="

$UiProcesses =
    @(
        Get-CimInstance `
            Win32_Process `
            -ErrorAction SilentlyContinue |
        Where-Object {

            $_.Name -match '^python(w)?\.exe$' -and
            $_.CommandLine -and
            (
                $_.CommandLine -match
                    'launch_redsight_command_center\.py' -or

                $_.CommandLine -match
                    'app\.ui\.command_center'
            )
        }
    )

foreach ($Process in $UiProcesses) {

    Write-Host "Stopping UI PID $($Process.ProcessId)"

    Stop-Process `
        -Id $Process.ProcessId `
        -Force `
        -ErrorAction SilentlyContinue
}

Start-Sleep -Seconds 1

# =====================================================================
# 26. LAUNCH NEW COMMAND CENTER
# =====================================================================

Write-Host ""
Write-Host "===================================================================="
Write-Host " LAUNCHING REDSIGHT COMMAND CENTER"
Write-Host "===================================================================="

$UiStdout =
    Join-Path $BackupRoot "command-center.stdout.log"

$UiStderr =
    Join-Path $BackupRoot "command-center.stderr.log"

$UiProcess =
    Start-Process `
        -FilePath $UiPython `
        -ArgumentList @(
            $Launcher
        ) `
        -WorkingDirectory $Root `
        -RedirectStandardOutput $UiStdout `
        -RedirectStandardError $UiStderr `
        -PassThru

Start-Sleep -Seconds 6

$UiProcess.Refresh()

if ($UiProcess.HasExited) {

    Write-Host ""
    Write-Host "COMMAND CENTER EXITED DURING STARTUP"
    Write-Host ""

    if (Test-Path $UiStdout) {

        Write-Host "=== STDOUT ==="

        Get-Content `
            $UiStdout `
            -Tail 120
    }

    if (Test-Path $UiStderr) {

        Write-Host ""
        Write-Host "=== STDERR ==="

        Get-Content `
            $UiStderr `
            -Tail 180
    }

    throw "Command Center failed to launch."
}

Write-Host ""
Write-Host "COMMAND_CENTER_LAUNCHED=YES"
Write-Host "PID=$($UiProcess.Id)"
Write-Host ""

# =====================================================================
# 27. FINAL STATUS
# =====================================================================

Write-Host "===================================================================="
Write-Host " FINAL REDSIGHT HERITAGE STATUS"
Write-Host "===================================================================="

docker compose ps

Write-Host ""

docker inspect `
    redsight `
    --format "redsight status={{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} restarts={{.RestartCount}}"

Write-Host ""

docker inspect `
    redsight-qdrant `
    --format "qdrant status={{.State.Status}} health={{.State.Health.Status}}"

Write-Host ""

docker exec `
    redsight `
    nvidia-smi -L

Write-Host ""
Write-Host "Hermes source home       : $HermesHome"
Write-Host "Hermes skills migrated   : $($Catalog.Count)"
Write-Host "Hermes SOUL migrated     : $(Test-Path (Join-Path $HeritageRoot 'SOUL.md'))"
Write-Host "Hermes MEMORY migrated   : $(Test-Path (Join-Path $HeritageRoot 'memories\MEMORY.md'))"
Write-Host "Hermes USER migrated     : $(Test-Path (Join-Path $HeritageRoot 'memories\USER.md'))"
Write-Host "Hermes MCP inventory     : $(Test-Path $McpInventory)"
Write-Host "Private MCP/config copy  : $PrivateConfig"
Write-Host "RAG heritage mount       : /heritage/hermes"
Write-Host "Command Center PID       : $($UiProcess.Id)"
Write-Host ""
Write-Host "UI additions:"
Write-Host "  REDSIGHT red logo / brand header"
Write-Host "  HERMES HERITAGE left-side panel"
Write-Host "  Soul tab"
Write-Host "  Memory + User tab"
Write-Host "  Searchable Skills tab"
Write-Host "  MCP server tab"
Write-Host ""
Write-Host "Chat inheritance:"
Write-Host "  SOUL       -> system/personality context"
Write-Host "  MEMORY     -> personal/environment context"
Write-Host "  USER       -> user-profile context"
Write-Host "  SKILL.md   -> prompt-selected procedural context"
Write-Host "  MCP list   -> available ecosystem awareness"
Write-Host ""
Write-Host "Backups / diagnostics:"
Write-Host $BackupRoot
Write-Host ""
Write-Host "Qdrant volumes/data were NOT deleted."
Write-Host "Original Hermes data was NOT modified."
Write-Host ""
Write-Host "===================================================================="
Write-Host " STAGE-7C COMPLETE"
Write-Host "===================================================================="
Write-Host ""

