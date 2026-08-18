$ErrorActionPreference = "Stop"

$Root       = "C:\Users\walim\RedSight"
$UI         = Join-Path $Root "app\ui\command_center.py"
$Server     = Join-Path $Root "app\server.py"
$Settings   = Join-Path $Root "app\config\settings.py"
$Dockerfile = Join-Path $Root "Dockerfile"
$Compose    = Join-Path $Root "docker-compose.yml"
$Override   = Join-Path $Root "docker-compose.override.yml"

$Stamp      = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot = Join-Path $Root ".repair-backups\stage3-fixed-$Stamp"

$Utf8 = New-Object System.Text.UTF8Encoding($false)

function Save-Utf8 {
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

function Backup-FileSafe {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        return
    }

    $Relative = $Path.Substring($script:Root.Length).TrimStart("\")
    $SafeName = $Relative -replace '[\\/:*?"<>|]', '__'

    Copy-Item `
        -LiteralPath $Path `
        -Destination (Join-Path $script:BackupRoot $SafeName) `
        -Force
}

Set-Location $Root

New-Item `
    -ItemType Directory `
    -Path $BackupRoot `
    -Force |
    Out-Null

Write-Host ""
Write-Host "================================================================="
Write-Host " REDSIGHT STAGE-3 FIXED REPAIR"
Write-Host " UI SYNTAX + BACKEND + PACKAGE + RUNTIME VALIDATION"
Write-Host "================================================================="
Write-Host ""

# =====================================================================
# 1. REQUIRED FILES
# =====================================================================

$Required = @(
    $UI,
    $Server,
    $Settings,
    $Dockerfile,
    $Compose,
    $Override
)

foreach ($File in $Required) {

    if (-not (Test-Path $File)) {
        throw "Required file missing: $File"
    }
}

Write-Host "Required source files: OK"
Write-Host ""

# =====================================================================
# 2. BACKUPS
# =====================================================================

Write-Host "=== Backing up files ==="

Backup-FileSafe $UI
Backup-FileSafe $Server
Backup-FileSafe $Settings
Backup-FileSafe $Dockerfile
Backup-FileSafe $Compose
Backup-FileSafe $Override

Write-Host "Backup:"
Write-Host $BackupRoot
Write-Host ""

# =====================================================================
# 3. STOP RESTART LOOP
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
# 4. DISPLAY UI FAILURE REGION
# =====================================================================

Write-Host "================================================================="
Write-Host " COMMAND CENTER SOURCE AROUND FAILURE"
Write-Host "================================================================="

$UiOriginalLines = [System.IO.File]::ReadAllLines($UI)

$ContextStart = [Math]::Max(1, 460)
$ContextEnd   = [Math]::Min($UiOriginalLines.Length, 510)

$ContextFile = Join-Path $BackupRoot "ui-context-before-repair.txt"

$Context = @()

for ($n = $ContextStart; $n -le $ContextEnd; $n++) {

    $Context += (
        "{0,4}: {1}" -f
        $n,
        $UiOriginalLines[$n - 1]
    )
}

$Context |
    Set-Content $ContextFile

$Context |
    ForEach-Object {
        Write-Host $_
    }

Write-Host ""

# =====================================================================
# 5. REPAIR INVALID async-with INSIDE SYNCHRONOUS UI METHOD
# =====================================================================

Write-Host "================================================================="
Write-Host " REPAIRING UI ASYNC/SYNC SYNTAX"
Write-Host "================================================================="

$Lines = [System.Collections.Generic.List[string]]::new()

foreach ($Line in [System.IO.File]::ReadAllLines($UI)) {
    [void]$Lines.Add($Line)
}

$PatchCount = 0

for ($i = 0; $i -lt $Lines.Count; $i++) {

    if (
        $Lines[$i] -notmatch
        '^(\s*)async\s+with\s+httpx\.AsyncClient\b'
    ) {
        continue
    }

    $AsyncIndent =
        ([regex]::Match(
            $Lines[$i],
            '^(\s*)'
        )).Groups[1].Value.Length

    $FunctionIndex   = -1
    $FunctionIndent  = -1
    $FunctionName    = ""
    $FunctionIsAsync = $false

    for ($j = $i - 1; $j -ge 0; $j--) {

        $FunctionMatch =
            [regex]::Match(
                $Lines[$j],
                '^(\s*)(async\s+def|def)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\('
            )

        if (-not $FunctionMatch.Success) {
            continue
        }

        $CandidateIndent =
            $FunctionMatch.Groups[1].Value.Length

        if ($CandidateIndent -ge $AsyncIndent) {
            continue
        }

        $FunctionIndex  = $j
        $FunctionIndent = $CandidateIndent
        $FunctionName   = $FunctionMatch.Groups[3].Value

        $FunctionIsAsync =
            $FunctionMatch.Groups[2].Value.StartsWith("async")

        break
    }

    if ($FunctionIndex -lt 0) {
        throw "Could not locate enclosing function for async-with at line $($i + 1)."
    }

    Write-Host ""
    Write-Host "Found:"
    Write-Host "  line     : $($i + 1)"
    Write-Host "  function : $FunctionName"
    Write-Host "  async def: $FunctionIsAsync"

    if ($FunctionIsAsync) {

        throw `
            "async with is already inside async def. This points to indentation corruption. Automatic repair stopped."
    }

    $FunctionEnd = $Lines.Count - 1

    for ($k = $FunctionIndex + 1; $k -lt $Lines.Count; $k++) {

        if ($Lines[$k].Trim().Length -eq 0) {
            continue
        }

        $CurrentIndent =
            ([regex]::Match(
                $Lines[$k],
                '^(\s*)'
            )).Groups[1].Value.Length

        if ($CurrentIndent -le $FunctionIndent) {

            $FunctionEnd = $k - 1
            break
        }
    }

    # Convert async HTTP client to synchronous HTTP client.
    $Lines[$i] =
        [regex]::Replace(
            $Lines[$i],
            'async\s+with\s+httpx\.AsyncClient',
            'with httpx.Client'
        )

    # Remove await ONLY from HTTP client calls inside same function.
    for ($k = $i + 1; $k -le $FunctionEnd; $k++) {

        $Lines[$k] =
            [regex]::Replace(
                $Lines[$k],
                '\bawait\s+client\.',
                'client.'
            )
    }

    # Refuse to save if other async constructs remain in same sync def.
    $UnexpectedAsync = @()

    for ($k = $FunctionIndex + 1; $k -le $FunctionEnd; $k++) {

        if (
            $Lines[$k] -match
            '\bawait\b|\basync\s+for\b|\basync\s+with\b'
        ) {

            $UnexpectedAsync += (
                "{0}: {1}" -f
                ($k + 1),
                $Lines[$k]
            )
        }
    }

    if ($UnexpectedAsync.Count -gt 0) {

        Write-Host ""
        Write-Host "Additional async constructs remain:"

        $UnexpectedAsync |
            ForEach-Object {
                Write-Host $_
            }

        throw `
            "UI function requires manual coroutine restructuring. Source has NOT been overwritten."
    }

    $PatchCount++
}

if ($PatchCount -gt 0) {

    [System.IO.File]::WriteAllLines(
        $UI,
        $Lines,
        $Utf8
    )

    Write-Host ""
    Write-Host "UI async/sync repairs applied: $PatchCount"
}

if ($PatchCount -eq 0) {

    Write-Host ""
    Write-Host "No invalid async-with statement currently needs repair."
}

Write-Host ""

# =====================================================================
# 6. VERIFY STAGE-2 RetrievalConfig FIX
# =====================================================================

Write-Host "=== Verifying enable_embeddings compatibility ==="

$ServerText = [System.IO.File]::ReadAllText($Server)

if (
    $ServerText.Contains(
        'settings.retrieval.enable_embeddings'
    )
) {

    Write-Host "Unsafe enable_embeddings access found. Repairing."

    $ServerText =
        $ServerText.Replace(
            'settings.retrieval.enable_embeddings',
            'getattr(settings.retrieval, "enable_embeddings", False)'
        )

    Save-Utf8 `
        -Path $Server `
        -Text $ServerText
}

$UnsafeEnable =
    Get-ChildItem `
        (Join-Path $Root "app") `
        -Recurse `
        -File `
        -Filter "*.py" |
    Select-String `
        -Pattern 'settings\.retrieval\.enable_embeddings'

if ($UnsafeEnable) {

    throw "Unsafe RetrievalConfig enable_embeddings reference remains."
}

Write-Host "enable_embeddings compatibility: OK"
Write-Host ""

# =====================================================================
# 7. CREATE AST VALIDATOR WITHOUT HERE-STRINGS
# =====================================================================

Write-Host "=== Creating read-only AST validator ==="

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
    '        ast.parse(text, filename=str(path), mode="exec")'
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
    '        print(f"OFFSET={exc.offset}")'
    '        print(f"ERROR={exc.msg}")'
    '        if exc.text:'
    '            print(f"SOURCE={exc.text.rstrip()}")'
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

Write-Host "Validator created."
Write-Host ""

# =====================================================================
# 8. AST CHECK — NO PYC / NO __pycache__
# =====================================================================

Write-Host "================================================================="
Write-Host " PYTHON AST VALIDATION"
Write-Host "================================================================="

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

$AstExit = $LASTEXITCODE

$ErrorActionPreference = "Stop"

if ($AstExit -ne 0) {

    throw `
        "A genuine Python syntax error remains. No rebuild performed."
}

Write-Host ""
Write-Host "Python AST validation: PASS"
Write-Host ""

# =====================================================================
# 9. ENSURE BOTH SOURCE PACKAGES ARE COPIED INTO FINAL IMAGE
# =====================================================================

Write-Host "=== Checking Docker source-package COPY statements ==="

$DockerText =
    [System.IO.File]::ReadAllText($Dockerfile)

$HasAppCopy =
    $DockerText -match
    '(?m)^\s*COPY\s+app/\s+app/\s*$'

$HasRedsightCopy =
    $DockerText -match
    '(?m)^\s*COPY\s+redsight/\s+redsight/\s*$'

if (-not $HasAppCopy) {

    throw "Dockerfile is missing COPY app/ app/"
}

if (
    (Test-Path (Join-Path $Root "redsight")) -and
    (-not $HasRedsightCopy)
) {

    $DockerText =
        $DockerText.Replace(
            "COPY app/ app/",
            "COPY app/ app/`r`nCOPY redsight/ redsight/"
        )

    Save-Utf8 `
        -Path $Dockerfile `
        -Text $DockerText

    Write-Host "Added:"
    Write-Host "  COPY redsight/ redsight/"
}

if ($HasRedsightCopy) {

    Write-Host "COPY redsight/ redsight/ already exists."
}

Write-Host ""

# =====================================================================
# 10. COMPOSE VALIDATION
# =====================================================================

Write-Host "=== Validating Compose ==="

$ResolvedCompose =
    Join-Path $BackupRoot "compose-resolved.yml"

$ErrorActionPreference = "Continue"

docker compose `
    -f $Compose `
    -f $Override `
    config `
    1> $ResolvedCompose

$ComposeExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

if ($ComposeExit -ne 0) {

    throw "Docker Compose configuration is invalid."
}

Write-Host "Compose: PASS"
Write-Host ""

# =====================================================================
# 11. BUILD WITH CACHE
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

    throw "RedSight image build failed."
}

Write-Host ""

# =====================================================================
# 12. CHECK IMPORTS INSIDE IMAGE
# =====================================================================

Write-Host "=== Testing image imports ==="

$ErrorActionPreference = "Continue"

docker run `
    --rm `
    redsight-redsight `
    python -c "import app; import app.server; import redsight; print('APP_IMPORT=OK'); print('REDSIGHT_IMPORT=OK')"

$ImportExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

if ($ImportExit -ne 0) {

    throw "Python package import test failed inside built image."
}

Write-Host ""

# =====================================================================
# 13. START REDSIGHT
# =====================================================================

Write-Host "=== Recreating RedSight ==="

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

    throw "RedSight container startup command failed."
}

Write-Host ""

# =====================================================================
# 14. WATCH FOR RESTART LOOP
# =====================================================================

Write-Host "=== Watching startup ==="

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

    Start-Sleep -Seconds 2
}

Write-Host ""

# =====================================================================
# 15. CLEAN LOG CAPTURE
# =====================================================================

$LogFile =
    Join-Path $BackupRoot "redsight-stage3-fixed.log"

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

Write-Host "================================================================="
Write-Host " IMPORTANT REDSIGHT LOG RESULTS"
Write-Host "================================================================="

$Patterns = @(
    "Application startup complete",
    "Application startup failed",
    "AttributeError",
    "ImportError",
    "ModuleNotFoundError",
    "SyntaxError",
    "TypeError",
    "ValueError",
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
# 16. HTTP TESTS
# =====================================================================

function Get-HttpStatus {

    param([string]$Url)

    $ErrorActionPreference = "Continue"

    $Value =
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

    return "$Value"
}

Write-Host "=== HTTP endpoint tests ==="

$RootCode =
    Get-HttpStatus "http://127.0.0.1:8000/"

$DocsCode =
    Get-HttpStatus "http://127.0.0.1:8000/docs"

$OpenApiCode =
    Get-HttpStatus "http://127.0.0.1:8000/openapi.json"

$HealthCode =
    Get-HttpStatus "http://127.0.0.1:8000/health"

Write-Host "/             = $RootCode"
Write-Host "/docs         = $DocsCode"
Write-Host "/openapi.json = $OpenApiCode"
Write-Host "/health       = $HealthCode"
Write-Host ""

# =====================================================================
# 17. QDRANT
# =====================================================================

Write-Host "=== Qdrant ==="

$ErrorActionPreference = "Continue"

$Qdrant =
    curl.exe `
    -fsS `
    http://127.0.0.1:6333/readyz `
    2>&1

$QdrantExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

Write-Host "Exit code: $QdrantExit"
Write-Host $Qdrant
Write-Host ""

# =====================================================================
# 18. ACTUAL LM STUDIO HTTP API TEST
# =====================================================================

Write-Host "=== Docker -> LM Studio OpenAI API ==="

$ErrorActionPreference = "Continue"

$LmOutput =
    docker run `
    --rm `
    --add-host host.docker.internal:host-gateway `
    redsight-redsight `
    python -c "import httpx; u='http://host.docker.internal:1234/v1/models'; r=httpx.get(u,timeout=5); print('HTTP_STATUS='+str(r.status_code)); print(r.text[:1500])" `
    2>&1

$LmExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

Write-Host "LM Studio test exit: $LmExit"

$LmOutput |
    ForEach-Object {
        Write-Host $_
    }

Write-Host ""

# =====================================================================
# 19. DISCOVER WHICH LM STUDIO SETTINGS REDSIGHT ACTUALLY USES
# =====================================================================

Write-Host "=== LM Studio configuration references ==="

Get-ChildItem `
    (Join-Path $Root "app") `
    -Recurse `
    -File `
    -Filter "*.py" |
    Select-String `
        -Pattern `
        "LM_STUDIO",
        "lm_studio",
        "localhost:1234",
        "127.0.0.1:1234",
        "base_url" |
    Select-Object -First 80

Write-Host ""

# =====================================================================
# 20. DOCKER GPU TEST
# =====================================================================

Write-Host "=== Docker GPU passthrough ==="

$GpuFile =
    Join-Path $BackupRoot "gpu-direct-test.txt"

$ErrorActionPreference = "Continue"

$GpuOutput =
    docker run `
    --rm `
    --gpus all `
    redsight-redsight `
    python -c "import torch; print('CUDA_AVAILABLE='+str(torch.cuda.is_available())); print('GPU_COUNT='+str(torch.cuda.device_count())); [print(str(i)+'='+torch.cuda.get_device_name(i)) for i in range(torch.cuda.device_count())]" `
    2>&1

$GpuExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

$GpuOutput |
    Out-String |
    Set-Content $GpuFile

Write-Host "GPU test exit code: $GpuExit"

$GpuOutput |
    ForEach-Object {
        Write-Host $_
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
    --format "redsight_status={{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} restarts={{.RestartCount}}"

Write-Host ""

docker inspect redsight-qdrant `
    --format "qdrant_status={{.State.Status}} health={{.State.Health.Status}}"

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "================================================================="

if ($StartupOK) {

    Write-Host " REDSIGHT BACKEND STARTUP: SUCCESS"
}

if (-not $StartupOK) {

    Write-Host " REDSIGHT BACKEND STARTUP: NEW BLOCKER REMAINS"
}

Write-Host "================================================================="
Write-Host ""

Write-Host "Diagnostics:"
Write-Host $BackupRoot
Write-Host ""

Write-Host "Main backend log:"
Write-Host $LogFile
Write-Host ""

Write-Host "Original UI failure context:"
Write-Host $ContextFile
Write-Host ""

Write-Host "GPU diagnostic:"
Write-Host $GpuFile
Write-Host ""

Write-Host "Qdrant volumes were NOT deleted."
Write-Host ""
