$ErrorActionPreference = "Stop"

$Root  = "C:\Users\walim\RedSight"
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$Out   = Join-Path $Root ".repair-backups\stage7b-contracts-$Stamp.txt"

Set-Location $Root

function Show-File {
    param(
        [string]$RelativePath
    )

    $Path = Join-Path $Root $RelativePath

    Write-Host ""
    Write-Host "===================================================================="
    Write-Host " FILE: $RelativePath"
    Write-Host "===================================================================="

    if (Test-Path $Path) {
        Get-Content -LiteralPath $Path
    }
    else {
        Write-Host "MISSING: $Path"
    }
}

& {

    Write-Host "===================================================================="
    Write-Host " REDSIGHT STAGE-7B"
    Write-Host " EXACT CONTRACT AUDIT BEFORE REDSIGHT + C/D MIGRATION"
    Write-Host " READ ONLY"
    Write-Host "===================================================================="

    # ---------------------------------------------------------------
    # Core components we are about to wire together
    # ---------------------------------------------------------------

    Show-File "app\skills\registry.py"
    Show-File "app\skills\sandbox.py"

    Show-File "app\retrieval\drive_scanner.py"
    Show-File "app\retrieval\multi_drive_indexer.py"

    Show-File "app\ingestion\indexer.py"

    Show-File "app\tools\registry.py"
    Show-File "app\tools\builtin.py"

    Show-File "app\orchestration\agent.py"
    Show-File "app\orchestration\multi_agent.py"

    Show-File "app\memory\memory_store.py"

    Show-File "app\retrieval\qdrant_client.py"

    Show-File "app\config\settings.py"

    # ---------------------------------------------------------------
    # Existing interfaces
    # ---------------------------------------------------------------

    Show-File "app\core\interfaces.py"

    # ---------------------------------------------------------------
    # API route inventory
    # ---------------------------------------------------------------

    Write-Host ""
    Write-Host "===================================================================="
    Write-Host " REDSIGHT OPENAPI ROUTES"
    Write-Host "===================================================================="

    $ErrorActionPreference = "Continue"

    curl.exe `
        -s `
        http://127.0.0.1:8000/openapi.json

    $ErrorActionPreference = "Stop"

    # ---------------------------------------------------------------
    # Python/package dependencies
    # ---------------------------------------------------------------

    Show-File "pyproject.toml"

    # ---------------------------------------------------------------
    # Compose — confirm C/D visibility from container
    # ---------------------------------------------------------------

    Show-File "docker-compose.yml"
    Show-File "docker-compose.override.yml"

    # ---------------------------------------------------------------
    # Current container mounts
    # ---------------------------------------------------------------

    Write-Host ""
    Write-Host "===================================================================="
    Write-Host " REDSIGHT CONTAINER MOUNTS"
    Write-Host "===================================================================="

    docker inspect redsight `
        --format "{{range .Mounts}}{{println .Source `" -> `" .Destination `" RW=`" .RW}}{{end}}"

    # ---------------------------------------------------------------
    # Existing Qdrant collection information
    # ---------------------------------------------------------------

    Write-Host ""
    Write-Host "===================================================================="
    Write-Host " QDRANT COLLECTION DETAILS"
    Write-Host "===================================================================="

    $Collections = @(
        "knowledge_docs",
        "project_code",
        "project_decisions",
        "skills_index",
        "episodic_memory",
        "tool_catalog",
        "eval_corpus"
    )

    foreach ($Collection in $Collections) {

        Write-Host ""
        Write-Host "--- $Collection ---"

        curl.exe `
            -s `
            "http://127.0.0.1:6333/collections/$Collection"
    }

    # ---------------------------------------------------------------
    # Find MCP code inside RedSight specifically
    # ---------------------------------------------------------------

    Write-Host ""
    Write-Host "===================================================================="
    Write-Host " EXISTING REDSIGHT MCP IMPLEMENTATION"
    Write-Host "===================================================================="

    Get-ChildItem `
        (Join-Path $Root "app") `
        -Recurse `
        -File `
        -Filter "*.py" |
    Select-String `
        -Pattern `
        "FastMCP",
        "ClientSession",
        "StdioServerParameters",
        "mcp.client",
        "mcp.server",
        "MCPClient",
        "MCPServer",
        "list_tools",
        "call_tool" |
    Select-Object `
        Path,
        LineNumber,
        Line

    # ---------------------------------------------------------------
    # RedSight custom skill roots
    # ---------------------------------------------------------------

    Write-Host ""
    Write-Host "===================================================================="
    Write-Host " REDSIGHT USER/CUSTOM SKILL INVENTORY"
    Write-Host "===================================================================="

    $RedSightUserRoots = @(
        "$env:LOCALAPPDATA\redsight\skills",
        "$env:USERPROFILE\.redsight\skills"
    )

    foreach ($SkillRoot in $RedSightUserRoots) {

        Write-Host ""
        Write-Host "--- $SkillRoot ---"

        if (-not (Test-Path $SkillRoot)) {
            Write-Host "NOT PRESENT"
            continue
        }

        Get-ChildItem `
            $SkillRoot `
            -Recurse `
            -File `
            -Filter "SKILL.md" `
            -ErrorAction SilentlyContinue |
        Where-Object {
            $_.FullName -notmatch '\\\.archive\\'
        } |
        ForEach-Object {

            $Hash =
                Get-FileHash `
                    -LiteralPath $_.FullName `
                    -Algorithm SHA256

            [PSCustomObject]@{
                Path      = $_.FullName
                SHA256    = $Hash.Hash
                Size      = $_.Length
                Modified  = $_.LastWriteTime
            }
        } |
        Format-List
    }

    # ---------------------------------------------------------------
    # Bundled RedSight skill roots for dedupe
    # ---------------------------------------------------------------

    Write-Host ""
    Write-Host "===================================================================="
    Write-Host " REDSIGHT BUNDLED SKILL ROOTS"
    Write-Host "===================================================================="

    $RedSightAgent =
        Join-Path `
            $env:LOCALAPPDATA `
            "redsight\redsight-agent"

    foreach ($Path in @(
        (Join-Path $RedSightAgent "skills"),
        (Join-Path $RedSightAgent "optional-skills")
    )) {

        Write-Host "$Path exists=$(Test-Path $Path)"
    }

    # ---------------------------------------------------------------
    # RedSight memories
    # ---------------------------------------------------------------

    Write-Host ""
    Write-Host "===================================================================="
    Write-Host " REDSIGHT MEMORY SOURCES"
    Write-Host "===================================================================="

    foreach ($Path in @(
        "$env:LOCALAPPDATA\redsight\memories\MEMORY.md",
        "$env:LOCALAPPDATA\redsight\memories\USER.md"
    )) {

        if (Test-Path $Path) {

            Write-Host ""
            Write-Host "--- $Path ---"

            Get-Content `
                -LiteralPath $Path
        }
    }

    # ---------------------------------------------------------------
    # Current health
    # ---------------------------------------------------------------

    Write-Host ""
    Write-Host "===================================================================="
    Write-Host " CURRENT STACK"
    Write-Host "===================================================================="

    docker compose ps

    Write-Host ""

    curl.exe `
        -s `
        http://127.0.0.1:8000/api/v1/health

    Write-Host ""

    curl.exe `
        -s `
        http://127.0.0.1:6333/collections

    Write-Host ""

} 2>&1 |
Tee-Object `
    -FilePath $Out

Write-Host ""
Write-Host "===================================================================="
Write-Host " STAGE-7B COMPLETE"
Write-Host "===================================================================="
Write-Host ""
Write-Host "NO FILES MODIFIED"
Write-Host "NO QDRANT COLLECTIONS MODIFIED"
Write-Host "NO REDSIGHT SKILLS MODIFIED"
Write-Host "NO DRIVE DATA MODIFIED"
Write-Host ""
Write-Host "REPORT:"
Write-Host $Out
Write-Host ""
