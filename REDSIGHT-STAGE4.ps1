$ErrorActionPreference = "Stop"

$Root       = "C:\Users\walim\RedSight"
$Server     = Join-Path $Root "app\server.py"
$Compose    = Join-Path $Root "docker-compose.yml"
$Override   = Join-Path $Root "docker-compose.override.yml"
$Stamp      = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot = Join-Path $Root ".repair-backups\stage4-$Stamp"

$Utf8 = New-Object System.Text.UTF8Encoding($false)

Set-Location $Root

New-Item `
    -ItemType Directory `
    -Path $BackupRoot `
    -Force |
    Out-Null

Write-Host ""
Write-Host "================================================================="
Write-Host " REDSIGHT STAGE-4 UNDEFINED-SYMBOL REPAIR"
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
# 3. DISCOVER EVERY set_source_viewer REFERENCE
# =====================================================================

Write-Host "================================================================="
Write-Host " DISCOVERING set_source_viewer"
Write-Host "================================================================="
Write-Host ""

$PythonFiles = @(
    Get-ChildItem `
        (Join-Path $Root "app") `
        -Recurse `
        -File `
        -Filter "*.py"
)

$AllReferences = @(
    $PythonFiles |
    Select-String `
        -Pattern '\bset_source_viewer\b'
)

Write-Host "All references:"
Write-Host ""

if ($AllReferences.Count -eq 0) {
    throw "No set_source_viewer references were found anywhere under app\."
}

foreach ($Ref in $AllReferences) {

    $Relative =
        $Ref.Path.Substring($Root.Length).TrimStart("\")

    Write-Host (
        "{0}:{1}: {2}" -f
        $Relative,
        $Ref.LineNumber,
        $Ref.Line.Trim()
    )
}

Write-Host ""

# =====================================================================
# 4. FIND ACTUAL FUNCTION DEFINITION
# =====================================================================

$Definitions = @()

foreach ($File in $PythonFiles) {

    $Matches =
        Select-String `
        -Path $File.FullName `
        -Pattern '^\s*(?:async\s+)?def\s+set_source_viewer\s*\(' `
        -ErrorAction SilentlyContinue

    foreach ($Match in $Matches) {
        $Definitions += $Match
    }
}

Write-Host "Function definitions found: $($Definitions.Count)"
Write-Host ""

foreach ($Def in $Definitions) {

    $Relative =
        $Def.Path.Substring($Root.Length).TrimStart("\")

    Write-Host (
        "{0}:{1}: {2}" -f
        $Relative,
        $Def.LineNumber,
        $Def.Line.Trim()
    )
}

Write-Host ""

# =====================================================================
# 5. SAFE DISCOVERY FAILURE
# =====================================================================

if ($Definitions.Count -eq 0) {

    Write-Host "No exact def set_source_viewer(...) was found."
    Write-Host ""
    Write-Host "Searching for related source-viewer APIs:"
    Write-Host ""

    $Related =
        $PythonFiles |
        Select-String `
            -Pattern `
            'source_viewer',
            'SourceViewer',
            'set_.*viewer',
            'viewer.*set' |
        Select-Object -First 100

    foreach ($Item in $Related) {

        $Relative =
            $Item.Path.Substring($Root.Length).TrimStart("\")

        Write-Host (
            "{0}:{1}: {2}" -f
            $Relative,
            $Item.LineNumber,
            $Item.Line.Trim()
        )
    }

    throw `
        "set_source_viewer has no exact definition. Automatic repair stopped safely."
}

if ($Definitions.Count -gt 1) {

    throw `
        "Multiple set_source_viewer definitions exist. Automatic import selection stopped safely."
}

# =====================================================================
# 6. DERIVE PYTHON MODULE FROM DEFINITION
# =====================================================================

$Definition =
    $Definitions[0]

$DefinitionFile =
    $Definition.Path

$DefinitionRelative =
    $DefinitionFile.Substring(
        $Root.Length
    ).TrimStart("\")

$DefinitionModule =
    $DefinitionRelative `
        -replace '\\','.' `
        -replace '/','.' `
        -replace '\.py$',''

$DefinitionModule =
    $DefinitionModule `
        -replace '\.__init__$',''

Write-Host "Resolved definition:"
Write-Host "  file   = $DefinitionRelative"
Write-Host "  module = $DefinitionModule"
Write-Host ""

if ($DefinitionFile -eq $Server) {

    throw `
        "set_source_viewer is defined inside server.py itself. That requires a different diagnosis."
}

# =====================================================================
# 7. LOCATE CALL IN server.py
# =====================================================================

$ServerLines =
    [System.Collections.Generic.List[string]]::new()

foreach ($Line in [System.IO.File]::ReadAllLines($Server)) {
    [void]$ServerLines.Add($Line)
}

$CallIndexes = @()

for ($i = 0; $i -lt $ServerLines.Count; $i++) {

    if (
        $ServerLines[$i] -match
        '^\s*set_source_viewer\s*\('
    ) {

        $CallIndexes += $i
    }
}

Write-Host "Direct calls in server.py: $($CallIndexes.Count)"
Write-Host ""

if ($CallIndexes.Count -eq 0) {
    throw "Could not find direct set_source_viewer(...) call in server.py."
}

# =====================================================================
# 8. ADD CORRECT IMPORT
#
# Import immediately before first usage. This avoids messing with
# __future__ imports or the existing top-level import organization.
# =====================================================================

$ImportStatement =
    "from $DefinitionModule import set_source_viewer"

$ServerText =
    [System.IO.File]::ReadAllText($Server)

$AlreadyImported =
    $ServerText.Contains($ImportStatement)

if (-not $AlreadyImported) {

    $FirstCallIndex =
        [int]$CallIndexes[0]

    $CallLine =
        $ServerLines[$FirstCallIndex]

    $Indent =
        ([regex]::Match(
            $CallLine,
            '^(\s*)'
        )).Groups[1].Value

    $IndentedImport =
        $Indent + $ImportStatement

    $ServerLines.Insert(
        $FirstCallIndex,
        $IndentedImport
    )

    [System.IO.File]::WriteAllLines(
        $Server,
        $ServerLines,
        $Utf8
    )

    Write-Host "Added:"
    Write-Host ""
    Write-Host "  $IndentedImport"
    Write-Host ""
}

if ($AlreadyImported) {

    Write-Host "Correct import already exists:"
    Write-Host ""
    Write-Host "  $ImportStatement"
    Write-Host ""
}

# =====================================================================
# 9. SHOW PATCHED SOURCE CONTEXT
# =====================================================================

Write-Host "=== Patched server context ==="
Write-Host ""

$NewLines =
    [System.IO.File]::ReadAllLines($Server)

$ViewerLine = -1

for ($i = 0; $i -lt $NewLines.Length; $i++) {

    if (
        $NewLines[$i] -match
        'set_source_viewer\s*\(source_viewer\)'
    ) {

        $ViewerLine =
            $i + 1

        break
    }
}

if ($ViewerLine -gt 0) {

    $From =
        [Math]::Max(
            1,
            $ViewerLine - 12
        )

    $To =
        [Math]::Min(
            $NewLines.Length,
            $ViewerLine + 8
        )

    for ($n = $From; $n -le $To; $n++) {

        Write-Host (
            "{0,4}: {1}" -f
            $n,
            $NewLines[$n - 1]
        )
    }
}

Write-Host ""

# =====================================================================
# 10. AST SYNTAX VALIDATION
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
    '    p = root / package'
    '    if p.exists():'
    '        files.extend(p.rglob("*.py"))'
    ''
    'files = sorted(set(files))'
    'errors = []'
    ''
    'for path in files:'
    '    try:'
    '        source = path.read_text(encoding="utf-8-sig")'
    '        ast.parse(source, filename=str(path))'
    '    except SyntaxError as e:'
    '        errors.append((path, e))'
    ''
    'print(f"FILES_CHECKED={len(files)}")'
    ''
    'if errors:'
    '    print(f"SYNTAX_ERRORS={len(errors)}")'
    '    for path, e in errors:'
    '        print("")'
    '        print(f"FILE={path}")'
    '        print(f"LINE={e.lineno}")'
    '        print(f"ERROR={e.msg}")'
    '        if e.text:'
    '            print("SOURCE=" + e.text.rstrip())'
    '    sys.exit(1)'
    ''
    'print("AST_SYNTAX=OK")'
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
    throw "AST validation failed."
}

Write-Host ""

# =====================================================================
# 11. RUFF F821 — FIND OTHER UNDEFINED NAMES NOW
# =====================================================================

Write-Host "================================================================="
Write-Host " UNDEFINED-NAME STATIC CHECK"
Write-Host "================================================================="

$RuffLog =
    Join-Path $BackupRoot "ruff-f821.txt"

$ErrorActionPreference = "Continue"

$RuffOutput =
    docker run `
    --rm `
    -v "${Root}:/source:ro" `
    redsight-redsight `
    ruff check `
    /source/app/server.py `
    --select F821 `
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

if ($RuffExit -eq 0) {

    Write-Host "Ruff F821 undefined-name scan: PASS"
}

if ($RuffExit -eq 127) {

    Write-Warning "Ruff executable was unavailable. Continuing with AST validation only."
}

if (
    $RuffExit -ne 0 -and
    $RuffExit -ne 127
) {

    Write-Host ""
    Write-Host "Additional undefined symbols exist in server.py."
    Write-Host "They are listed above and in:"
    Write-Host $RuffLog
    Write-Host ""

    throw `
        "Ruff found additional F821 undefined-name errors. Build stopped so they can be fixed together."
}

Write-Host ""

# =====================================================================
# 12. COMPOSE VALIDATION
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
# 13. REBUILD WITH CACHE
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
    throw "RedSight build failed."
}

Write-Host ""

# =====================================================================
# 14. IMPORT TEST
# =====================================================================

Write-Host "=== Import validation ==="

$ErrorActionPreference = "Continue"

docker run `
    --rm `
    redsight-redsight `
    python -c "import app.server; print('APP_SERVER_IMPORT=OK')"

$ImportExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

if ($ImportExit -ne 0) {
    throw "app.server import failed in rebuilt image."
}

Write-Host ""

# =====================================================================
# 15. START
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
    throw "RedSight start command failed."
}

Write-Host ""

# =====================================================================
# 16. MONITOR
# =====================================================================

Write-Host "=== Monitoring startup ==="

for ($i = 1; $i -le 18; $i++) {

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

    Start-Sleep -Seconds 2
}

Write-Host ""

# =====================================================================
# 17. CAPTURE CLEAN LOGS
# =====================================================================

$LogFile =
    Join-Path $BackupRoot "redsight-stage4.log"

$Command =
    'docker logs --tail 500 redsight > "' +
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

Write-Host "Application startup complete: $StartupOK"
Write-Host ""

# =====================================================================
# 18. HTTP
# =====================================================================

function Http-Code {

    param([string]$Url)

    $ErrorActionPreference = "Continue"

    $Result =
        curl.exe `
        -s `
        -o NUL `
        -w "%{http_code}" `
        --max-time 5 `
        $Url `
        2>$null

    $Exit =
        $LASTEXITCODE

    $ErrorActionPreference = "Stop"

    if ($Exit -ne 0) {
        return "000"
    }

    return "$Result"
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

Write-Host "/             = $RootCode"
Write-Host "/docs         = $DocsCode"
Write-Host "/openapi.json = $OpenApiCode"
Write-Host "/health       = $HealthCode"
Write-Host ""

# =====================================================================
# 19. QDRANT
# =====================================================================

Write-Host "=== Qdrant ==="

$ErrorActionPreference = "Continue"

curl.exe `
    -fsS `
    http://127.0.0.1:6333/readyz

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host ""

# =====================================================================
# 20. SHOW FINAL TRACEBACK AUTOMATICALLY IF NEEDED
# =====================================================================

if (-not $StartupOK) {

    Write-Host "================================================================="
    Write-Host " LATEST 100 REDSIGHT LOG LINES"
    Write-Host "================================================================="

    Get-Content `
        $LogFile `
        -Tail 100
}

Write-Host ""

# =====================================================================
# 21. FINAL STATUS
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
Write-Host "Diagnostics:"
Write-Host $BackupRoot
Write-Host ""
Write-Host "Ruff F821 report:"
Write-Host $RuffLog
Write-Host ""
Write-Host "Runtime log:"
Write-Host $LogFile
Write-Host ""
Write-Host "Qdrant data/volumes were NOT touched."
Write-Host ""
