$ErrorActionPreference = "Stop"

$Root       = "C:\Users\walim\RedSight"
$UI         = Join-Path $Root "app\ui\command_center.py"
$Server     = Join-Path $Root "app\server.py"
$Dockerfile = Join-Path $Root "Dockerfile"
$Compose    = Join-Path $Root "docker-compose.yml"
$Override   = Join-Path $Root "docker-compose.override.yml"

$Stamp      = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot = Join-Path $Root ".repair-backups\stage3b-$Stamp"

$Utf8 = New-Object System.Text.UTF8Encoding($false)

Set-Location $Root

New-Item `
    -ItemType Directory `
    -Path $BackupRoot `
    -Force |
    Out-Null

Write-Host ""
Write-Host "================================================================="
Write-Host " REDSIGHT STAGE-3B TARGETED REPAIR"
Write-Host "================================================================="
Write-Host ""

# ---------------------------------------------------------------------
# BACKUP
# ---------------------------------------------------------------------

Copy-Item `
    -LiteralPath $UI `
    -Destination (Join-Path $BackupRoot "command_center.py.before") `
    -Force

Copy-Item `
    -LiteralPath $Server `
    -Destination (Join-Path $BackupRoot "server.py.before") `
    -Force

Copy-Item `
    -LiteralPath $Dockerfile `
    -Destination (Join-Path $BackupRoot "Dockerfile.before") `
    -Force

Write-Host "Backup:"
Write-Host $BackupRoot
Write-Host ""

# ---------------------------------------------------------------------
# STOP ONLY REDSIGHT
# ---------------------------------------------------------------------

Write-Host "=== Stopping RedSight ==="

$ErrorActionPreference = "Continue"

docker compose `
    -f $Compose `
    -f $Override `
    stop redsight

$ErrorActionPreference = "Stop"

Write-Host ""

# ---------------------------------------------------------------------
# TARGETED UI FIX
#
# Leave _send_to_api async.
# Repair ONLY the 5-second dashboard HTTP block.
# ---------------------------------------------------------------------

Write-Host "=== Repairing _update_dashboard() ==="

$UiText = [System.IO.File]::ReadAllText($UI)

if (-not $UiText.Contains('def _update_dashboard(self):')) {
    throw "_update_dashboard() was not found."
}

$OldWith =
    '            async with httpx.AsyncClient(timeout=5.0) as client:'

$NewWith =
    '            with httpx.Client(timeout=5.0) as client:'

$OldGet =
    '                resp = await client.get(f"{self._api_base_url}/api/v1/health")'

$NewGet =
    '                resp = client.get(f"{self._api_base_url}/api/v1/health")'

$WithCount =
    ([regex]::Matches(
        $UiText,
        [regex]::Escape($OldWith)
    )).Count

$GetCount =
    ([regex]::Matches(
        $UiText,
        [regex]::Escape($OldGet)
    )).Count

Write-Host "Invalid dashboard async-with occurrences: $WithCount"
Write-Host "Invalid dashboard await-get occurrences : $GetCount"

if ($WithCount -gt 1) {
    throw "More than one matching dashboard async-with block exists. Stopping for safety."
}

if ($GetCount -gt 1) {
    throw "More than one matching dashboard await-get call exists. Stopping for safety."
}

if ($WithCount -eq 1) {

    $UiText =
        $UiText.Replace(
            $OldWith,
            $NewWith
        )

    Write-Host "Converted dashboard AsyncClient -> Client"
}

if ($GetCount -eq 1) {

    $UiText =
        $UiText.Replace(
            $OldGet,
            $NewGet
        )

    Write-Host "Converted dashboard await client.get -> client.get"
}

[System.IO.File]::WriteAllText(
    $UI,
    $UiText,
    $Utf8
)

Write-Host ""

# ---------------------------------------------------------------------
# SHOW BOTH FUNCTIONS AFTER FIX
# ---------------------------------------------------------------------

Write-Host "=== Verifying async and sync UI methods ==="

$UiLines = [System.IO.File]::ReadAllLines($UI)

for ($n = 455; $n -le [Math]::Min(505,$UiLines.Length); $n++) {

    Write-Host (
        "{0,4}: {1}" -f
        $n,
        $UiLines[$n - 1]
    )
}

Write-Host ""

# ---------------------------------------------------------------------
# VERIFY THE CORRECT ASYNC FUNCTION REMAINS ASYNC
# ---------------------------------------------------------------------

$UiText = [System.IO.File]::ReadAllText($UI)

if (-not $UiText.Contains('async def _send_to_api(self, message: str):')) {
    throw "_send_to_api is no longer async. Stopping."
}

if (-not $UiText.Contains('async with httpx.AsyncClient(timeout=30.0) as client:')) {
    throw "Valid AsyncClient block inside _send_to_api was unexpectedly altered."
}

Write-Host "_send_to_api async implementation preserved: YES"
Write-Host ""

# ---------------------------------------------------------------------
# VERIFY enable_embeddings PATCH
# ---------------------------------------------------------------------

Write-Host "=== Verifying RetrievalConfig compatibility ==="

$ServerText =
    [System.IO.File]::ReadAllText($Server)

if ($ServerText.Contains('settings.retrieval.enable_embeddings')) {

    $ServerText =
        $ServerText.Replace(
            'settings.retrieval.enable_embeddings',
            'getattr(settings.retrieval, "enable_embeddings", False)'
        )

    [System.IO.File]::WriteAllText(
        $Server,
        $ServerText,
        $Utf8
    )

    Write-Host "Repaired enable_embeddings access."
}

$Unsafe =
    Select-String `
    -Path $Server `
    -Pattern 'settings\.retrieval\.enable_embeddings' `
    -ErrorAction SilentlyContinue

if ($Unsafe) {
    throw "Unsafe enable_embeddings access remains."
}

Write-Host "RetrievalConfig compatibility: OK"
Write-Host ""

# ---------------------------------------------------------------------
# CREATE AST VALIDATOR
# NO compileall
# NO pyc
# NO __pycache__
# ---------------------------------------------------------------------

Write-Host "=== Creating AST-only Python validator ==="

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
    '        print(f"OFFSET={e.offset}")'
    '        print(f"ERROR={e.msg}")'
    '        if e.text:'
    '            print("SOURCE=" + e.text.rstrip())'
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

Write-Host ""

# ---------------------------------------------------------------------
# AST VALIDATE
# ---------------------------------------------------------------------

Write-Host "================================================================="
Write-Host " AST VALIDATION"
Write-Host "================================================================="

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
    throw "A genuine Python syntax error remains. Build stopped."
}

Write-Host ""
Write-Host "ALL PYTHON SOURCE SYNTAX: PASS"
Write-Host ""

# ---------------------------------------------------------------------
# ENSURE redsight WRAPPER PACKAGE GETS COPIED INTO IMAGE
# ---------------------------------------------------------------------

Write-Host "=== Checking Dockerfile source packages ==="

$DockerText =
    [System.IO.File]::ReadAllText($Dockerfile)

$HasRedsightCopy =
    $DockerText -match
    '(?m)^\s*COPY\s+redsight/\s+redsight/\s*$'

if (
    (Test-Path (Join-Path $Root "redsight")) -and
    (-not $HasRedsightCopy)
) {

    if (-not $DockerText.Contains("COPY app/ app/")) {
        throw "Expected COPY app/ app/ line was not found."
    }

    $DockerText =
        $DockerText.Replace(
            "COPY app/ app/",
            "COPY app/ app/`r`nCOPY redsight/ redsight/"
        )

    [System.IO.File]::WriteAllText(
        $Dockerfile,
        $DockerText,
        $Utf8
    )

    Write-Host "Added Dockerfile line:"
    Write-Host "  COPY redsight/ redsight/"
}

if ($HasRedsightCopy) {
    Write-Host "redsight/ package already copied."
}

Write-Host ""

# ---------------------------------------------------------------------
# COMPOSE VALIDATION
# ---------------------------------------------------------------------

Write-Host "=== Validating Compose ==="

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
    throw "Compose configuration validation failed."
}

Write-Host "Compose: PASS"
Write-Host ""

# ---------------------------------------------------------------------
# REBUILD WITH CACHE
# ---------------------------------------------------------------------

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

# ---------------------------------------------------------------------
# IMAGE IMPORT TEST
# ---------------------------------------------------------------------

Write-Host "=== Testing built image imports ==="

$ErrorActionPreference = "Continue"

docker run `
    --rm `
    redsight-redsight `
    python -c "import app; import app.server; import redsight; print('APP=OK'); print('APP_SERVER=OK'); print('REDSIGHT=OK')"

$ImportExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

if ($ImportExit -ne 0) {
    throw "Built image Python import test failed."
}

Write-Host ""

# ---------------------------------------------------------------------
# START REDSIGHT
# ---------------------------------------------------------------------

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
    throw "RedSight startup failed."
}

Write-Host ""

# ---------------------------------------------------------------------
# WATCH RESTART COUNT
# ---------------------------------------------------------------------

Write-Host "=== Watching backend startup ==="

for ($i = 1; $i -le 15; $i++) {

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

# ---------------------------------------------------------------------
# LOGS
# ---------------------------------------------------------------------

$LogFile =
    Join-Path $BackupRoot "redsight.log"

$Command =
    'docker logs --tail 400 redsight > "' +
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
Write-Host " REDSIGHT STARTUP RESULTS"
Write-Host "================================================================="

$Patterns = @(
    "Application startup complete",
    "Application startup failed",
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
        Select-Object -Last 6 |
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

# ---------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------

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

    $Exit =
        $LASTEXITCODE

    $ErrorActionPreference = "Stop"

    if ($Exit -ne 0) {
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

Write-Host "/             = $RootCode"
Write-Host "/docs         = $DocsCode"
Write-Host "/openapi.json = $OpenApiCode"
Write-Host "/health       = $HealthCode"
Write-Host ""

# ---------------------------------------------------------------------
# QDRANT
# ---------------------------------------------------------------------

Write-Host "=== Qdrant ==="

$ErrorActionPreference = "Continue"

curl.exe `
    -fsS `
    http://127.0.0.1:6333/readyz

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host ""

# ---------------------------------------------------------------------
# SHOW BOTTOM OF LOG IF STILL BROKEN
# ---------------------------------------------------------------------

if (-not $StartupOK) {

    Write-Host "================================================================="
    Write-Host " LATEST 80 LOG LINES"
    Write-Host "================================================================="

    Get-Content `
        $LogFile `
        -Tail 80
}

Write-Host ""

# ---------------------------------------------------------------------
# FINAL CONTAINER STATUS
# ---------------------------------------------------------------------

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
Write-Host "Main log:"
Write-Host $LogFile
Write-Host ""
Write-Host "Qdrant volumes were NOT touched."
Write-Host ""
