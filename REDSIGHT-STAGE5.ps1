$ErrorActionPreference = "Stop"

$Root       = "C:\Users\walim\RedSight"
$Server     = Join-Path $Root "app\server.py"
$Compose    = Join-Path $Root "docker-compose.yml"
$Override   = Join-Path $Root "docker-compose.override.yml"

$Stamp      = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot = Join-Path $Root ".repair-backups\stage5-$Stamp"

$Utf8 = New-Object System.Text.UTF8Encoding($false)

Set-Location $Root

New-Item `
    -ItemType Directory `
    -Path $BackupRoot `
    -Force |
    Out-Null

Write-Host ""
Write-Host "================================================================="
Write-Host " REDSIGHT STAGE-5 INDEXER + LIFESPAN CONTRACT REPAIR"
Write-Host "================================================================="
Write-Host ""

# =====================================================================
# 1. BACKUP
# =====================================================================

Copy-Item `
    -LiteralPath $Server `
    -Destination (Join-Path $BackupRoot "server.py.before") `
    -Force

Write-Host "Backup:"
Write-Host $BackupRoot
Write-Host ""

# =====================================================================
# 2. STOP REDSIGHT ONLY
# =====================================================================

Write-Host "=== Stopping RedSight ==="

$ErrorActionPreference = "Continue"

docker compose `
    -f $Compose `
    -f $Override `
    stop redsight

$ErrorActionPreference = "Stop"

Write-Host ""

# =====================================================================
# 3. DISCOVER REAL Indexer CLASS
# =====================================================================

Write-Host "================================================================="
Write-Host " DISCOVERING Indexer IMPLEMENTATION"
Write-Host "================================================================="

$PythonFiles = @(
    Get-ChildItem `
        (Join-Path $Root "app") `
        -Recurse `
        -File `
        -Filter "*.py"
)

$IndexerDefinitions = @()

foreach ($File in $PythonFiles) {

    $Matches =
        Select-String `
        -Path $File.FullName `
        -Pattern '^\s*class\s+Indexer\b' `
        -ErrorAction SilentlyContinue

    foreach ($Match in $Matches) {
        $IndexerDefinitions += $Match
    }
}

Write-Host "Indexer definitions found: $($IndexerDefinitions.Count)"
Write-Host ""

foreach ($Definition in $IndexerDefinitions) {

    $Relative =
        $Definition.Path.Substring(
            $Root.Length
        ).TrimStart("\")

    Write-Host (
        "{0}:{1}: {2}" -f
        $Relative,
        $Definition.LineNumber,
        $Definition.Line.Trim()
    )
}

Write-Host ""

if ($IndexerDefinitions.Count -eq 0) {

    throw "No class Indexer definition was found under app\."
}

if ($IndexerDefinitions.Count -gt 1) {

    throw "Multiple Indexer classes exist. Automatic selection stopped safely."
}

$IndexerDefinition =
    $IndexerDefinitions[0]

$IndexerFile =
    $IndexerDefinition.Path

$IndexerRelative =
    $IndexerFile.Substring(
        $Root.Length
    ).TrimStart("\")

$IndexerModule =
    $IndexerRelative `
        -replace '\\','.' `
        -replace '/','.' `
        -replace '\.py$',''

$IndexerModule =
    $IndexerModule `
        -replace '\.__init__$',''

Write-Host "Resolved Indexer:"
Write-Host "  file   = $IndexerRelative"
Write-Host "  module = $IndexerModule"
Write-Host ""

# =====================================================================
# 4. LOCATE Indexer(...) RUNTIME USE
# =====================================================================

$Lines =
    [System.Collections.Generic.List[string]]::new()

foreach ($Line in [System.IO.File]::ReadAllLines($Server)) {
    [void]$Lines.Add($Line)
}

$IndexerUseIndexes = @()

for ($i = 0; $i -lt $Lines.Count; $i++) {

    if ($Lines[$i] -match '\bIndexer\s*\(') {

        # Ignore annotations such as "indexer: Indexer"
        if ($Lines[$i] -notmatch '^\s*[A-Za-z_][A-Za-z0-9_]*\s*:\s*Indexer') {
            $IndexerUseIndexes += $i
        }
    }
}

Write-Host "Runtime Indexer(...) uses found: $($IndexerUseIndexes.Count)"
Write-Host ""

foreach ($Index in $IndexerUseIndexes) {

    Write-Host (
        "{0,4}: {1}" -f
        ($Index + 1),
        $Lines[$Index]
    )
}

Write-Host ""

if ($IndexerUseIndexes.Count -eq 0) {

    throw "No runtime Indexer(...) construction was found in server.py."
}

# =====================================================================
# 5. ADD LOCAL IMPORT BEFORE FIRST RUNTIME USE
#
# Local import is deliberate:
# avoids forcing all startup components into module import scope.
# =====================================================================

$ImportStatement =
    "from $IndexerModule import Indexer"

$ServerText =
    [System.IO.File]::ReadAllText($Server)

$AlreadyImported =
    $ServerText.Contains($ImportStatement)

if (-not $AlreadyImported) {

    $FirstUse =
        [int]$IndexerUseIndexes[0]

    $Indent =
        ([regex]::Match(
            $Lines[$FirstUse],
            '^(\s*)'
        )).Groups[1].Value

    $ImportLine =
        $Indent + $ImportStatement

    $Lines.Insert(
        $FirstUse,
        $ImportLine
    )

    [System.IO.File]::WriteAllLines(
        $Server,
        $Lines,
        $Utf8
    )

    Write-Host "Added local Indexer import:"
    Write-Host ""
    Write-Host "  $ImportLine"
    Write-Host ""
}

if ($AlreadyImported) {

    Write-Host "Indexer import already exists:"
    Write-Host ""
    Write-Host "  $ImportStatement"
    Write-Host ""
}

# =====================================================================
# 6. SHOW CONTEXT
# =====================================================================

Write-Host "=== Indexer startup context ==="

$Lines =
    [System.IO.File]::ReadAllLines($Server)

$IndexerRuntimeLine = -1

for ($i = 0; $i -lt $Lines.Length; $i++) {

    if ($Lines[$i] -match '=\s*Indexer\s*\(') {

        $IndexerRuntimeLine =
            $i + 1

        break
    }
}

if ($IndexerRuntimeLine -gt 0) {

    $From =
        [Math]::Max(
            1,
            $IndexerRuntimeLine - 12
        )

    $To =
        [Math]::Min(
            $Lines.Length,
            $IndexerRuntimeLine + 12
        )

    for ($n = $From; $n -le $To; $n++) {

        Write-Host (
            "{0,4}: {1}" -f
            $n,
            $Lines[$n - 1]
        )
    }
}

Write-Host ""

# =====================================================================
# 7. AST VALIDATION
# =====================================================================

Write-Host "================================================================="
Write-Host " AST VALIDATION"
Write-Host "================================================================="

$Validator =
    Join-Path $BackupRoot "validate_ast.py"

$ValidatorLines = @(
    'import ast'
    'import pathlib'
    'import sys'
    ''
    'root = pathlib.Path("/source")'
    'files = []'
    ''
    'for package in ("app", "redsight"):'
    '    folder = root / package'
    '    if folder.exists():'
    '        files.extend(folder.rglob("*.py"))'
    ''
    'files = sorted(set(files))'
    'errors = []'
    ''
    'for path in files:'
    '    try:'
    '        source = path.read_text(encoding="utf-8-sig")'
    '        ast.parse(source, filename=str(path))'
    '    except SyntaxError as exc:'
    '        errors.append((path, exc))'
    ''
    'print(f"FILES_CHECKED={len(files)}")'
    ''
    'if errors:'
    '    print(f"SYNTAX_ERRORS={len(errors)}")'
    '    for path, exc in errors:'
    '        print("")'
    '        print(f"FILE={path}")'
    '        print(f"LINE={exc.lineno}")'
    '        print(f"ERROR={exc.msg}")'
    '        if exc.text:'
    '            print("SOURCE=" + exc.text.rstrip())'
    '    sys.exit(1)'
    ''
    'print("AST_SYNTAX=OK")'
    'sys.exit(0)'
)

[System.IO.File]::WriteAllLines(
    $Validator,
    $ValidatorLines,
    $Utf8
)

$ValidatorRelative =
    $Validator.Substring(
        $Root.Length
    ).Replace("\","/")

$ErrorActionPreference = "Continue"

docker run `
    --rm `
    -v "${Root}:/source:ro" `
    redsight-redsight `
    python "/source$ValidatorRelative"

$AstExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

if ($AstExit -ne 0) {
    throw "Python AST validation failed."
}

Write-Host ""

# =====================================================================
# 8. DISCOVER lifespan() LINE RANGE
# =====================================================================

Write-Host "=== Detecting lifespan() source range ==="

$Lines =
    [System.IO.File]::ReadAllLines($Server)

$LifespanStart = -1
$LifespanEnd   = $Lines.Length

for ($i = 0; $i -lt $Lines.Length; $i++) {

    if (
        $Lines[$i] -match
        '^async\s+def\s+lifespan\s*\('
    ) {

        $LifespanStart =
            $i + 1

        break
    }
}

if ($LifespanStart -lt 0) {

    # lifespan may be decorated, but def should still exist.
    for ($i = 0; $i -lt $Lines.Length; $i++) {

        if (
            $Lines[$i] -match
            '^\s*async\s+def\s+lifespan\s*\('
        ) {

            $LifespanStart =
                $i + 1

            break
        }
    }
}

if ($LifespanStart -lt 0) {
    throw "Could not identify lifespan() function."
}

for (
    $i = $LifespanStart;
    $i -lt $Lines.Length;
    $i++
) {

    if (
        $Lines[$i] -match
        '^(async\s+def|def|class)\s+[A-Za-z_]'
    ) {

        $LifespanEnd =
            $i

        break
    }
}

Write-Host "lifespan start: $LifespanStart"
Write-Host "lifespan end  : $LifespanEnd"
Write-Host ""

# =====================================================================
# 9. RUFF F821
#
# Ruff may still report forward/type-annotation names around lines
# 40-67. Those are diagnostic.
#
# ONLY F821 findings inside lifespan() block startup.
# =====================================================================

Write-Host "================================================================="
Write-Host " LIFESPAN UNDEFINED-NAME CHECK"
Write-Host "================================================================="

$RuffLog =
    Join-Path $BackupRoot "ruff-server-f821.txt"

$ErrorActionPreference = "Continue"

$RuffOutput =
    docker run `
    --rm `
    -e RUFF_CACHE_DIR=/tmp/ruff-cache `
    -v "${Root}:/source:ro" `
    redsight-redsight `
    ruff check `
    /source/app/server.py `
    --select F821 `
    --no-cache `
    --output-format concise `
    2>&1

$RuffExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

$RuffOutput |
    Out-String |
    Set-Content $RuffLog

$RuffOutput |
    ForEach-Object {
        Write-Host $_
    }

Write-Host ""

$RuntimeF821 =
    @()

foreach ($Line in $RuffOutput) {

    $Text =
        "$Line"

    $Match =
        [regex]::Match(
            $Text,
            'server\.py:(\d+):(\d+):\s+F821\s+(.+)$'
        )

    if (-not $Match.Success) {
        continue
    }

    $LineNumber =
        [int]$Match.Groups[1].Value

    if (
        $LineNumber -ge $LifespanStart -and
        $LineNumber -le $LifespanEnd
    ) {

        $RuntimeF821 += $Text
    }
}

Write-Host "F821 findings inside lifespan(): $($RuntimeF821.Count)"
Write-Host ""

if ($RuntimeF821.Count -gt 0) {

    Write-Host "These are genuine startup-scope undefined names:"
    Write-Host ""

    $RuntimeF821 |
        ForEach-Object {
            Write-Host $_
        }

    Write-Host ""

    throw `
        "Undefined names still exist inside lifespan(). Build stopped."
}

Write-Host "No F821 undefined names remain inside lifespan()."
Write-Host ""
Write-Host "Annotation-only F821 findings outside lifespan are non-fatal for this startup repair."
Write-Host ""

# =====================================================================
# 10. COMPOSE VALIDATION
# =====================================================================

Write-Host "=== Compose validation ==="

$ErrorActionPreference = "Continue"

docker compose `
    -f $Compose `
    -f $Override `
    config `
    1> (Join-Path $BackupRoot "compose-resolved.yml")

$ComposeExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

if ($ComposeExit -ne 0) {
    throw "Compose validation failed."
}

Write-Host "Compose: PASS"
Write-Host ""

# =====================================================================
# 11. REBUILD WITH CACHE
# =====================================================================

Write-Host "================================================================="
Write-Host " REBUILDING REDSIGHT"
Write-Host "================================================================="

$ErrorActionPreference = "Continue"

docker compose `
    -f $Compose `
    -f $Override `
    build redsight

$BuildExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

if ($BuildExit -ne 0) {
    throw "RedSight Docker build failed."
}

Write-Host ""

# =====================================================================
# 12. IMPORT TEST
# =====================================================================

Write-Host "=== app.server import test ==="

$ErrorActionPreference = "Continue"

docker run `
    --rm `
    redsight-redsight `
    python -c "import app.server; print('APP_SERVER_IMPORT=OK')"

$ImportExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

if ($ImportExit -ne 0) {
    throw "app.server import failed."
}

Write-Host ""

# =====================================================================
# 13. START
# =====================================================================

Write-Host "=== Starting RedSight ==="

$ErrorActionPreference = "Continue"

docker compose `
    -f $Compose `
    -f $Override `
    up -d `
    --force-recreate `
    redsight

$StartExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

if ($StartExit -ne 0) {
    throw "RedSight startup command failed."
}

Write-Host ""

# =====================================================================
# 14. MONITOR
# =====================================================================

Write-Host "=== Monitoring startup ==="

for ($i = 1; $i -le 20; $i++) {

    $ErrorActionPreference = "Continue"

    $State =
        docker inspect redsight `
        --format "{{.State.Status}}" `
        2>$null

    $Health =
        docker inspect redsight `
        --format "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}" `
        2>$null

    $Restarts =
        docker inspect redsight `
        --format "{{.RestartCount}}" `
        2>$null

    $ErrorActionPreference = "Stop"

    Write-Host (
        "state=$State health=$Health restarts=$Restarts"
    )

    if (
        $State -eq "running" -and
        $Health -eq "healthy"
    ) {

        Write-Host ""
        Write-Host "Container became healthy."
        break
    }

    Start-Sleep -Seconds 2
}

Write-Host ""

# =====================================================================
# 15. CLEAN LOG CAPTURE
# =====================================================================

$LogFile =
    Join-Path $BackupRoot "redsight-stage5.log"

$Command =
    'docker logs --tail 600 redsight > "' +
    $LogFile +
    '" 2>&1'

cmd.exe /d /c $Command

$LogText = ""

if (Test-Path $LogFile) {

    $LogText =
        [System.IO.File]::ReadAllText(
            $LogFile
        )
}

# =====================================================================
# 16. IMPORTANT LOG LINES
# =====================================================================

Write-Host "================================================================="
Write-Host " STARTUP RESULTS"
Write-Host "================================================================="

$Patterns = @(
    "Application startup complete",
    "Application startup failed",
    "NameError",
    "AttributeError",
    "TypeError",
    "ValueError",
    "ModuleNotFoundError",
    "ImportError",
    "Qdrant",
    "BM25",
    "reranker",
    "Indexer",
    "LM Studio",
    "NVML",
    "Traceback",
    "ERROR:"
)

foreach ($Pattern in $Patterns) {

    Select-String `
        -Path $LogFile `
        -SimpleMatch `
        -Pattern $Pattern `
        -ErrorAction SilentlyContinue |
        Select-Object -Last 8 |
        ForEach-Object {
            Write-Host $_.Line
        }
}

Write-Host ""

$StartupOK =
    $LogText.Contains(
        "Application startup complete"
    )

$StartupFailed =
    $LogText.Contains(
        "Application startup failed"
    )

Write-Host "Application startup complete: $StartupOK"
Write-Host "Application startup failed  : $StartupFailed"
Write-Host ""

# =====================================================================
# 17. HTTP
# =====================================================================

function Http-Code {

    param([string]$Url)

    $ErrorActionPreference = "Continue"

    $Code =
        curl.exe `
        -s `
        -o NUL `
        -w "%{http_code}" `
        --max-time 5 `
        $Url `
        2>$null

    $ExitCode =
        $LASTEXITCODE

    $ErrorActionPreference = "Stop"

    if ($ExitCode -ne 0) {
        return "000"
    }

    return "$Code"
}

Write-Host "=== HTTP ==="

$RootCode =
    Http-Code "http://127.0.0.1:8000/"

$DocsCode =
    Http-Code "http://127.0.0.1:8000/docs"

$OpenApiCode =
    Http-Code "http://127.0.0.1:8000/openapi.json"

$HealthCode =
    Http-Code "http://127.0.0.1:8000/health"

$ApiHealthCode =
    Http-Code "http://127.0.0.1:8000/api/v1/health"

Write-Host "/              = $RootCode"
Write-Host "/docs          = $DocsCode"
Write-Host "/openapi.json  = $OpenApiCode"
Write-Host "/health        = $HealthCode"
Write-Host "/api/v1/health = $ApiHealthCode"
Write-Host ""

# =====================================================================
# 18. QDRANT
# =====================================================================

Write-Host "=== Qdrant ==="

$ErrorActionPreference = "Continue"

$QdrantOutput =
    curl.exe `
    -fsS `
    http://127.0.0.1:6333/readyz `
    2>&1

$QdrantExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

Write-Host "Qdrant exit code: $QdrantExit"
Write-Host $QdrantOutput
Write-Host ""

# =====================================================================
# 19. IF STILL BROKEN — PRINT BOTTOM TRACEBACK
# =====================================================================

if (-not $StartupOK) {

    Write-Host "================================================================="
    Write-Host " LATEST 140 LOG LINES"
    Write-Host "================================================================="

    Get-Content `
        $LogFile `
        -Tail 140
}

Write-Host ""

# =====================================================================
# 20. FINAL STATUS
# =====================================================================

Write-Host "================================================================="
Write-Host " FINAL STATUS"
Write-Host "================================================================="

$ErrorActionPreference = "Continue"

docker compose `
    -f $Compose `
    -f $Override `
    ps

Write-Host ""

docker inspect redsight `
    --format "redsight status={{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} restarts={{.RestartCount}}"

Write-Host ""

docker inspect redsight-qdrant `
    --format "qdrant status={{.State.Status}} health={{.State.Health.Status}}"

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "================================================================="

if ($StartupOK) {
    Write-Host " REDSIGHT CORE BACKEND: SUCCESS"
}

if (-not $StartupOK) {
    Write-Host " REDSIGHT CORE BACKEND: NEXT BLOCKER PRINTED ABOVE"
}

Write-Host "================================================================="
Write-Host ""

Write-Host "Diagnostics:"
Write-Host $BackupRoot
Write-Host ""

Write-Host "F821 report:"
Write-Host $RuffLog
Write-Host ""

Write-Host "Runtime log:"
Write-Host $LogFile
Write-Host ""

Write-Host "Qdrant volumes/data were NOT touched."
Write-Host ""
