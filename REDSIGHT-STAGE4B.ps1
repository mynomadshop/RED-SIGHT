$ErrorActionPreference = "Stop"

$Root       = "C:\Users\walim\RedSight"
$Server     = Join-Path $Root "app\server.py"
$Compose    = Join-Path $Root "docker-compose.yml"
$Override   = Join-Path $Root "docker-compose.override.yml"

$Stamp      = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot = Join-Path $Root ".repair-backups\stage4b-$Stamp"

$Utf8 = New-Object System.Text.UTF8Encoding($false)

Set-Location $Root

New-Item `
    -ItemType Directory `
    -Path $BackupRoot `
    -Force |
    Out-Null

Write-Host ""
Write-Host "================================================================="
Write-Host " REDSIGHT STAGE-4B ALIAS + UNDEFINED-NAME REPAIR"
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

Write-Host "=== Stopping RedSight restart loop ==="

$ErrorActionPreference = "Continue"

docker compose `
    -f $Compose `
    -f $Override `
    stop redsight

$ErrorActionPreference = "Stop"

Write-Host ""

# =====================================================================
# 3. VERIFY THE IMPORT ALIAS
# =====================================================================

Write-Host "=== Verifying set_source_viewer alias ==="

$ServerText =
    [System.IO.File]::ReadAllText($Server)

$ExpectedImport =
    'from app.api.routes.sources import set_source_viewer as set_sources'

if (-not $ServerText.Contains($ExpectedImport)) {

    Write-Host ""
    Write-Host "Expected alias import was not found:"
    Write-Host $ExpectedImport
    Write-Host ""

    throw "Source layout changed. Automatic repair stopped."
}

Write-Host "Alias import found:"
Write-Host ""
Write-Host "  $ExpectedImport"
Write-Host ""

# =====================================================================
# 4. COUNT BAD AND GOOD CALLS
# =====================================================================

$BadPattern =
    '(?m)^(\s*)set_source_viewer\(source_viewer\)\s*$'

$GoodPattern =
    '(?m)^(\s*)set_sources\(source_viewer\)\s*$'

$BadCount =
    ([regex]::Matches(
        $ServerText,
        $BadPattern
    )).Count

$GoodCount =
    ([regex]::Matches(
        $ServerText,
        $GoodPattern
    )).Count

Write-Host "Bad set_source_viewer(source_viewer) calls : $BadCount"
Write-Host "Good set_sources(source_viewer) calls      : $GoodCount"
Write-Host ""

if ($BadCount -gt 1) {
    throw "More than one bad source-viewer registration call exists. Stopping for safety."
}

# =====================================================================
# 5. PATCH EXACT BUG
# =====================================================================

if ($BadCount -eq 1) {

    $ServerText =
        [regex]::Replace(
            $ServerText,
            $BadPattern,
            '$1set_sources(source_viewer)'
        )

    [System.IO.File]::WriteAllText(
        $Server,
        $ServerText,
        $Utf8
    )

    Write-Host "Patched:"
    Write-Host ""
    Write-Host "  set_source_viewer(source_viewer)"
    Write-Host "                  ->"
    Write-Host "  set_sources(source_viewer)"
    Write-Host ""
}

if ($BadCount -eq 0 -and $GoodCount -gt 0) {

    Write-Host "Correct alias call is already present."
    Write-Host ""
}

# =====================================================================
# 6. VERIFY SOURCE AFTER PATCH
# =====================================================================

$ServerText =
    [System.IO.File]::ReadAllText($Server)

$BadRemaining =
    ([regex]::Matches(
        $ServerText,
        $BadPattern
    )).Count

$GoodNow =
    ([regex]::Matches(
        $ServerText,
        $GoodPattern
    )).Count

if ($BadRemaining -gt 0) {
    throw "Bad set_source_viewer(source_viewer) call still remains."
}

if ($GoodNow -eq 0) {
    throw "Expected set_sources(source_viewer) call was not created."
}

Write-Host "Source-viewer registration repair: PASS"
Write-Host ""

# =====================================================================
# 7. DISPLAY REPAIRED CONTEXT
# =====================================================================

Write-Host "=== Repaired server.py context ==="

$Lines =
    [System.IO.File]::ReadAllLines($Server)

$FoundLine = -1

for ($i = 0; $i -lt $Lines.Length; $i++) {

    if ($Lines[$i] -match 'set_sources\(source_viewer\)') {

        $FoundLine =
            $i + 1

        break
    }
}

if ($FoundLine -gt 0) {

    $From =
        [Math]::Max(
            1,
            $FoundLine - 12
        )

    $To =
        [Math]::Min(
            $Lines.Length,
            $FoundLine + 10
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
# 8. AST VALIDATION
# =====================================================================

Write-Host "================================================================="
Write-Host " PYTHON AST VALIDATION"
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
    '        text = path.read_text(encoding="utf-8-sig")'
    '        ast.parse(text, filename=str(path))'
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
    throw "AST syntax validation failed."
}

Write-Host ""

# =====================================================================
# 9. RUFF F821 WITHOUT WRITING CACHE
# =====================================================================

Write-Host "================================================================="
Write-Host " SERVER UNDEFINED-NAME CHECK"
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
Write-Host "Ruff exit code: $RuffExit"
Write-Host ""

if ($RuffExit -ne 0) {

    Write-Host "Ruff found an undefined-name problem or another linter failure."
    Write-Host ""
    Write-Host "Report:"
    Write-Host $RuffLog
    Write-Host ""

    throw "server.py did not pass F821 validation."
}

Write-Host "server.py undefined-name scan: PASS"
Write-Host ""

# =====================================================================
# 10. OPTIONAL BROADER F821 SCAN
#
# Diagnostic only.
# Does NOT stop build because unrelated dormant modules may contain
# unfinished code that does not affect backend startup.
# =====================================================================

Write-Host "=== Broader app F821 diagnostic ==="

$RuffAllLog =
    Join-Path $BackupRoot "ruff-app-f821.txt"

$ErrorActionPreference = "Continue"

$RuffAllOutput =
    docker run `
    --rm `
    -e RUFF_CACHE_DIR=/tmp/ruff-cache `
    -v "${Root}:/source:ro" `
    redsight-redsight `
    ruff check `
    /source/app `
    --select F821 `
    --no-cache `
    --output-format concise `
    2>&1

$RuffAllExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

$RuffAllOutput |
    Out-String |
    Set-Content $RuffAllLog

Write-Host "Full app F821 diagnostic exit: $RuffAllExit"

if ($RuffAllExit -ne 0) {

    Write-Host "Non-server F821 findings were saved for later review:"
    Write-Host $RuffAllLog
}

if ($RuffAllExit -eq 0) {

    Write-Host "Entire app package passes F821."
}

Write-Host ""

# =====================================================================
# 11. COMPOSE VALIDATION
# =====================================================================

Write-Host "=== Docker Compose validation ==="

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
    throw "Docker Compose validation failed."
}

Write-Host "Compose: PASS"
Write-Host ""

# =====================================================================
# 12. REBUILD WITH CACHE
# =====================================================================

Write-Host "================================================================="
Write-Host " REBUILDING REDSIGHT WITH CACHE"
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
# 13. IMPORT TEST
# =====================================================================

Write-Host "=== Importing rebuilt app.server ==="

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
# 14. START REDSIGHT
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
# 15. MONITOR RESTARTS
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

        Write-Host "Container became healthy."
        break
    }

    Start-Sleep -Seconds 2
}

Write-Host ""

# =====================================================================
# 16. CAPTURE CLEAN LOG
# =====================================================================

$LogFile =
    Join-Path $BackupRoot "redsight-stage4b.log"

$LogCommand =
    'docker logs --tail 500 redsight > "' +
    $LogFile +
    '" 2>&1'

cmd.exe /d /c $LogCommand

$LogText = ""

if (Test-Path $LogFile) {

    $LogText =
        [System.IO.File]::ReadAllText(
            $LogFile
        )
}

# =====================================================================
# 17. IMPORTANT LOG RESULTS
# =====================================================================

Write-Host "================================================================="
Write-Host " IMPORTANT STARTUP RESULTS"
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
# 18. HTTP TESTS
# =====================================================================

function Get-HttpCode {

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

    $CurlExit =
        $LASTEXITCODE

    $ErrorActionPreference = "Stop"

    if ($CurlExit -ne 0) {
        return "000"
    }

    return "$Code"
}

Write-Host "=== HTTP ==="

$RootCode =
    Get-HttpCode "http://127.0.0.1:8000/"

$DocsCode =
    Get-HttpCode "http://127.0.0.1:8000/docs"

$OpenApiCode =
    Get-HttpCode "http://127.0.0.1:8000/openapi.json"

$HealthCode =
    Get-HttpCode "http://127.0.0.1:8000/health"

$ApiHealthCode =
    Get-HttpCode "http://127.0.0.1:8000/api/v1/health"

Write-Host "/              = $RootCode"
Write-Host "/docs          = $DocsCode"
Write-Host "/openapi.json  = $OpenApiCode"
Write-Host "/health        = $HealthCode"
Write-Host "/api/v1/health = $ApiHealthCode"
Write-Host ""

# =====================================================================
# 19. QDRANT
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
# 20. IF STILL BROKEN, PRINT BOTTOM-MOST TRACEBACK
# =====================================================================

if (-not $StartupOK) {

    Write-Host "================================================================="
    Write-Host " LATEST 120 LOG LINES"
    Write-Host "================================================================="

    Get-Content `
        $LogFile `
        -Tail 120
}

Write-Host ""

# =====================================================================
# 21. FINAL STATUS
# =====================================================================

Write-Host "================================================================="
Write-Host " FINAL REDSIGHT STATUS"
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

    Write-Host " REDSIGHT CORE BACKEND: NEXT RUNTIME BLOCKER SHOWN ABOVE"
}

Write-Host "================================================================="
Write-Host ""

Write-Host "Diagnostics:"
Write-Host $BackupRoot
Write-Host ""

Write-Host "Server F821 report:"
Write-Host $RuffLog
Write-Host ""

Write-Host "Full-app F821 diagnostic:"
Write-Host $RuffAllLog
Write-Host ""

Write-Host "Runtime log:"
Write-Host $LogFile
Write-Host ""

Write-Host "Qdrant volumes/data were NOT touched."
Write-Host ""
