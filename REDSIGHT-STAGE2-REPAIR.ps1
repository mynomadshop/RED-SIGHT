$ErrorActionPreference = "Stop"

$Root       = "C:\Users\walim\RedSight"
$Server     = Join-Path $Root "app\server.py"
$Settings   = Join-Path $Root "app\config\settings.py"
$Compose    = Join-Path $Root "docker-compose.yml"
$Override   = Join-Path $Root "docker-compose.override.yml"
$PyProject  = Join-Path $Root "pyproject.toml"

$Stamp      = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot = Join-Path $Root ".repair-backups\stage2-$Stamp"

$Utf8 = New-Object System.Text.UTF8Encoding($false)

Set-Location $Root
New-Item -ItemType Directory -Path $BackupRoot -Force | Out-Null

function Write-Utf8 {
    param([string]$Path,[string]$Text)
    [System.IO.File]::WriteAllText($Path,$Text,$script:Utf8)
}

function Backup-One {
    param([string]$Path)

    if (Test-Path $Path) {
        $Name = $Path.Substring($script:Root.Length).TrimStart("\")
        $Name = $Name -replace '[\\/:*?"<>|]','__'
        Copy-Item $Path (Join-Path $script:BackupRoot $Name) -Force
    }
}

Write-Host ""
Write-Host "================================================================="
Write-Host " REDSIGHT STAGE-2 SOURCE CONTRACT REPAIR"
Write-Host "================================================================="
Write-Host ""

# ---------------------------------------------------------------------
# 1. BACKUP
# ---------------------------------------------------------------------

Write-Host "=== Backing up current source ==="

Backup-One $Server
Backup-One $Settings
Backup-One $Compose
Backup-One $Override
Backup-One $PyProject

Write-Host "Backup:"
Write-Host $BackupRoot
Write-Host ""

# ---------------------------------------------------------------------
# 2. STOP RESTART LOOP
# ---------------------------------------------------------------------

Write-Host "=== Stopping RedSight restart loop ==="

$ErrorActionPreference = "Continue"

docker compose `
    -f $Compose `
    -f $Override `
    stop redsight

$ErrorActionPreference = "Stop"

Write-Host ""

# ---------------------------------------------------------------------
# 3. CAPTURE GIT / REPOSITORY STATE
# ---------------------------------------------------------------------

Write-Host "=== Inspecting repository state ==="

$GitReport = Join-Path $BackupRoot "git-state.txt"

$ErrorActionPreference = "Continue"

@(
    "============================================================"
    "GIT STATUS"
    "============================================================"
) | Set-Content $GitReport

git status --short 2>&1 |
    Out-String |
    Add-Content $GitReport

"`n=== BRANCH ===" |
    Add-Content $GitReport

git branch --show-current 2>&1 |
    Out-String |
    Add-Content $GitReport

"`n=== REMOTES ===" |
    Add-Content $GitReport

git remote -v 2>&1 |
    Out-String |
    Add-Content $GitReport

"`n=== RECENT COMMITS ===" |
    Add-Content $GitReport

git log -8 --oneline --decorate 2>&1 |
    Out-String |
    Add-Content $GitReport

"`n=== IMPORTANT FILE DIFF ===" |
    Add-Content $GitReport

git diff -- `
    app/server.py `
    app/config/settings.py `
    pyproject.toml `
    Dockerfile `
    docker-compose.yml `
    docker-compose.override.yml `
    2>&1 |
    Out-String |
    Add-Content $GitReport

$ErrorActionPreference = "Stop"

Write-Host "Git report saved."
Write-Host ""

# ---------------------------------------------------------------------
# 4. DISCOVER PACKAGE LAYOUT
# ---------------------------------------------------------------------

Write-Host "=== Discovering RedSight package layout ==="

$HasApp      = Test-Path (Join-Path $Root "app")
$HasRedsight = Test-Path (Join-Path $Root "redsight")

Write-Host "app\ directory      : $HasApp"
Write-Host "redsight\ directory : $HasRedsight"
Write-Host ""

if ($HasApp) {
    Write-Host "app package files:"
    Get-ChildItem (Join-Path $Root "app") `
        -Recurse `
        -File `
        -Filter "*.py" |
        Select-Object -ExpandProperty FullName |
        ForEach-Object {
            $_.Substring($Root.Length).TrimStart("\")
        } |
        Select-Object -First 60
}

Write-Host ""

if ($HasRedsight) {
    Write-Host "redsight package files:"
    Get-ChildItem (Join-Path $Root "redsight") `
        -Recurse `
        -File `
        -Filter "*.py" |
        Select-Object -ExpandProperty FullName |
        ForEach-Object {
            $_.Substring($Root.Length).TrimStart("\")
        } |
        Select-Object -First 60
}

Write-Host ""

# ---------------------------------------------------------------------
# 5. READ ACTUAL RetrievalConfig CLASS
# ---------------------------------------------------------------------

Write-Host "================================================================="
Write-Host " RETRIEVAL CONFIG SCHEMA ANALYSIS"
Write-Host "================================================================="

$SettingsText = [System.IO.File]::ReadAllText($Settings)

$ClassMatch = [regex]::Match(
    $SettingsText,
    '(?ms)^class\s+RetrievalConfig\b.*?(?=^class\s+[A-Za-z_][A-Za-z0-9_]*\b|\z)'
)

if (-not $ClassMatch.Success) {
    throw "Could not locate class RetrievalConfig in app\config\settings.py"
}

$RetrievalClass = $ClassMatch.Value

$RetrievalClass |
    Set-Content (Join-Path $BackupRoot "RetrievalConfig-current.txt")

Write-Host ""
Write-Host "Actual RetrievalConfig:"
Write-Host "-----------------------------------------------------------------"
Write-Host $RetrievalClass
Write-Host "-----------------------------------------------------------------"
Write-Host ""

# ---------------------------------------------------------------------
# 6. EXTRACT REAL CONFIG FIELDS
# ---------------------------------------------------------------------

$FieldMatches = [regex]::Matches(
    $RetrievalClass,
    '(?m)^\s+([A-Za-z_][A-Za-z0-9_]*)\s*:\s*[^=\r\n]+(?:=|$)'
)

$RealFields = @()

foreach ($M in $FieldMatches) {
    $Name = $M.Groups[1].Value

    if ($Name -notin $RealFields) {
        $RealFields += $Name
    }
}

Write-Host "Fields that actually exist:"
$RealFields |
    Sort-Object |
    ForEach-Object {
        Write-Host "  $_"
    }

Write-Host ""

# ---------------------------------------------------------------------
# 7. FIND EVERY RETRIEVAL FIELD EXPECTED BY APPLICATION CODE
# ---------------------------------------------------------------------

Write-Host "=== Scanning application for settings.retrieval.* usage ==="

$References = @{}

$SourceFiles = @(
    Get-ChildItem `
        (Join-Path $Root "app") `
        -Recurse `
        -File `
        -Filter "*.py"
)

foreach ($File in $SourceFiles) {

    $Text = [System.IO.File]::ReadAllText($File.FullName)

    $Matches = [regex]::Matches(
        $Text,
        'settings\.retrieval\.([A-Za-z_][A-Za-z0-9_]*)'
    )

    foreach ($M in $Matches) {

        $Field = $M.Groups[1].Value

        if (-not $References.ContainsKey($Field)) {
            $References[$Field] = @()
        }

        $References[$Field] += $File.FullName
    }
}

$ExpectedFields = @(
    $References.Keys |
    Sort-Object
)

Write-Host ""
Write-Host "Application expects:"
foreach ($Field in $ExpectedFields) {
    Write-Host "  $Field"
}

# ---------------------------------------------------------------------
# 8. COMPARE SOURCE CONTRACT WITH REAL MODEL
# ---------------------------------------------------------------------

$MissingFields = @()

foreach ($Field in $ExpectedFields) {

    if ($Field -notin $RealFields) {
        $MissingFields += $Field
    }
}

Write-Host ""
Write-Host "================================================================="
Write-Host " MISSING RetrievalConfig FIELDS"
Write-Host "================================================================="

if ($MissingFields.Count -eq 0) {
    Write-Host "No direct RetrievalConfig mismatches remain."
}

if ($MissingFields.Count -gt 0) {

    foreach ($Field in $MissingFields) {
        Write-Host "  MISSING -> $Field"
    }
}

$MissingFields |
    Set-Content (Join-Path $BackupRoot "missing-retrieval-fields.txt")

Write-Host ""

# ---------------------------------------------------------------------
# 9. SAFE COMPATIBILITY DEFAULT GENERATOR
#
# This is intentionally conservative:
#
# feature switches -> False
# optional strings/objects -> None
# Qdrant vector fields -> Docker-compatible values
#
# This keeps stale optional features from killing the whole backend.
# ---------------------------------------------------------------------

function Get-PythonDefault {
    param([string]$Name)

    if ($Name -eq "vector_backend_url") {
        return 'None'
    }

    if ($Name -eq "vector_backend_host") {
        return '"qdrant"'
    }

    if ($Name -eq "vector_backend_port") {
        return '6333'
    }

    if ($Name -eq "vector_backend_embedded") {
        return 'False'
    }

    if ($Name -match '^enable_') {
        return 'False'
    }

    if ($Name -match '^use_') {
        return 'False'
    }

    if ($Name -match '^allow_') {
        return 'False'
    }

    if ($Name -match '^require_') {
        return 'False'
    }

    if ($Name -match '_enabled$') {
        return 'False'
    }

    return 'None'
}

# ---------------------------------------------------------------------
# 10. PATCH ALL STALE RetrievalConfig DIRECT ACCESSES
# ---------------------------------------------------------------------

Write-Host "=== Repairing stale RetrievalConfig accesses ==="

$PatchedFiles = @()

foreach ($File in $SourceFiles) {

    $Original = [System.IO.File]::ReadAllText($File.FullName)
    $Code = $Original

    foreach ($Field in $MissingFields) {

        $Needle = "settings.retrieval.$Field"

        if ($Code.Contains($Needle)) {

            $Default = Get-PythonDefault $Field

            $Replacement =
                "getattr(settings.retrieval, `"$Field`", $Default)"

            $Code = $Code.Replace(
                $Needle,
                $Replacement
            )

            Write-Host "Compatibility repair:"
            Write-Host "  $Field -> default $Default"
        }
    }

    if ($Code -ne $Original) {

        $Relative =
            $File.FullName.Substring($Root.Length).TrimStart("\")

        $Safe =
            "pre-stage2__" +
            ($Relative -replace '[\\/:*?"<>|]','__')

        Copy-Item `
            $File.FullName `
            (Join-Path $BackupRoot $Safe) `
            -Force

        Write-Utf8 `
            -Path $File.FullName `
            -Text $Code

        $PatchedFiles += $File.FullName

        Write-Host "Patched file:"
        Write-Host "  $Relative"
    }
}

Write-Host ""
Write-Host "Files patched: $($PatchedFiles.Count)"
Write-Host ""

# ---------------------------------------------------------------------
# 11. EXPLICITLY PROTECT enable_embeddings
# ---------------------------------------------------------------------

$ServerText = [System.IO.File]::ReadAllText($Server)

$ServerText = $ServerText.Replace(
    'settings.retrieval.enable_embeddings',
    'getattr(settings.retrieval, "enable_embeddings", False)'
)

Write-Utf8 `
    -Path $Server `
    -Text $ServerText

Write-Host "enable_embeddings now has a safe False fallback."
Write-Host ""

# ---------------------------------------------------------------------
# 12. REMOVE ACCIDENTAL NESTED getattr DAMAGE
#
# Previous scripts already patched vector fields.
# Normalize any duplicated nested compatibility expressions.
# ---------------------------------------------------------------------

$ServerText = [System.IO.File]::ReadAllText($Server)

$ServerText = $ServerText.Replace(
    'getattr(getattr(settings.retrieval, "enable_embeddings", False), "enable_embeddings", False)',
    'getattr(settings.retrieval, "enable_embeddings", False)'
)

Write-Utf8 `
    -Path $Server `
    -Text $ServerText

# ---------------------------------------------------------------------
# 13. VERIFY NO DIRECT MISSING ACCESS REMAINS
# ---------------------------------------------------------------------

Write-Host "=== Verifying source contract ==="

$RemainingProblems = @()

foreach ($File in $SourceFiles) {

    $Text = [System.IO.File]::ReadAllText($File.FullName)

    foreach ($Field in $MissingFields) {

        $Needle = "settings.retrieval.$Field"

        if ($Text.Contains($Needle)) {
            $RemainingProblems += "$($File.FullName): $Field"
        }
    }
}

if ($RemainingProblems.Count -gt 0) {

    Write-Host ""
    Write-Host "Unsafe references remain:"

    $RemainingProblems |
        ForEach-Object {
            Write-Host $_
        }

    throw "Not all incompatible RetrievalConfig references were repaired."
}

Write-Host "All currently detectable RetrievalConfig accesses are guarded."
Write-Host ""

# ---------------------------------------------------------------------
# 14. PYTHON SYNTAX CHECK BEFORE BUILD
# ---------------------------------------------------------------------

Write-Host "=== Python syntax validation ==="

$ErrorActionPreference = "Continue"

docker run `
    --rm `
    -v "${Root}:/source:ro" `
    redsight-redsight `
    python -m compileall -q /source/app

$CompileExit = $LASTEXITCODE

$ErrorActionPreference = "Stop"

if ($CompileExit -ne 0) {
    throw "Python syntax validation failed. Build stopped."
}

Write-Host "Python syntax: OK"
Write-Host ""

# ---------------------------------------------------------------------
# 15. REPORT PYPROJECT / SOURCE NAMESPACE MISMATCH
# ---------------------------------------------------------------------

Write-Host "================================================================="
Write-Host " PACKAGE NAMESPACE ANALYSIS"
Write-Host "================================================================="

$PyText = [System.IO.File]::ReadAllText($PyProject)

$ReferencesRedsightNamespace =
    $PyText -match 'redsight\.[A-Za-z_]'

if ($ReferencesRedsightNamespace -and -not $HasRedsight -and $HasApp) {

    Write-Host ""
    Write-Host "SOURCE MIGRATION MISMATCH DETECTED:"
    Write-Host ""
    Write-Host "pyproject.toml points to redsight.*"
    Write-Host "but repository source is currently under app\."
    Write-Host ""
    Write-Host "This does NOT block uvicorn app.server,"
    Write-Host "but it CAN break console/UI entry points."
    Write-Host ""

    "pyproject references redsight.*, but root\redsight is absent and root\app exists." |
        Set-Content (Join-Path $BackupRoot "PACKAGE-MISMATCH-DETECTED.txt")
}

# ---------------------------------------------------------------------
# 16. REBUILD BACKEND USING CACHE
# ---------------------------------------------------------------------

Write-Host "================================================================="
Write-Host " REBUILDING REDSIGHT"
Write-Host "================================================================="

$ErrorActionPreference = "Continue"

docker compose `
    -f $Compose `
    -f $Override `
    build redsight

$BuildExit = $LASTEXITCODE

$ErrorActionPreference = "Stop"

if ($BuildExit -ne 0) {
    throw "RedSight image build failed."
}

Write-Host ""

# ---------------------------------------------------------------------
# 17. RECREATE REDSIGHT
# ---------------------------------------------------------------------

Write-Host "=== Recreating RedSight ==="

$ErrorActionPreference = "Continue"

docker compose `
    -f $Compose `
    -f $Override `
    up -d `
    --force-recreate `
    redsight

$StartExit = $LASTEXITCODE

$ErrorActionPreference = "Stop"

if ($StartExit -ne 0) {
    throw "RedSight container recreation failed."
}

Write-Host ""

# ---------------------------------------------------------------------
# 18. WAIT AND MONITOR RESTART COUNT
# ---------------------------------------------------------------------

Write-Host "=== Monitoring startup ==="

$InitialRestarts = -1

for ($i = 1; $i -le 15; $i++) {

    $ErrorActionPreference = "Continue"

    $State = docker inspect redsight `
        --format "{{.State.Status}}" `
        2>$null

    $Health = docker inspect redsight `
        --format "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}" `
        2>$null

    $Restarts = docker inspect redsight `
        --format "{{.RestartCount}}" `
        2>$null

    $ErrorActionPreference = "Stop"

    if ($InitialRestarts -lt 0) {
        $InitialRestarts = [int]$Restarts
    }

    Write-Host "state=$State health=$Health restarts=$Restarts"

    Start-Sleep -Seconds 2
}

Write-Host ""

# ---------------------------------------------------------------------
# 19. CAPTURE LOGS WITHOUT POWERSHELL NativeCommandError NOISE
# ---------------------------------------------------------------------

$LogFile = Join-Path $BackupRoot "redsight-stage2.log"

Write-Host "=== Capturing clean Docker logs ==="

$Cmd =
    'docker logs --tail 400 redsight > "' +
    $LogFile +
    '" 2>&1'

cmd.exe /d /c $Cmd

$Log = ""

if (Test-Path $LogFile) {
    $Log = [System.IO.File]::ReadAllText($LogFile)
}

Write-Host ""
Write-Host "Log file:"
Write-Host $LogFile
Write-Host ""

# ---------------------------------------------------------------------
# 20. PRINT ONLY IMPORTANT STARTUP LINES
# ---------------------------------------------------------------------

Write-Host "================================================================="
Write-Host " IMPORTANT STARTUP RESULTS"
Write-Host "================================================================="

$ImportantPatterns = @(
    "Application startup complete",
    "Application startup failed",
    "AttributeError",
    "TypeError",
    "ValueError",
    "Connection",
    "Qdrant",
    "LM Studio",
    "NVML",
    "ERROR:",
    "Traceback"
)

foreach ($Pattern in $ImportantPatterns) {

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

# ---------------------------------------------------------------------
# 21. DETERMINE CORE STARTUP RESULT
# ---------------------------------------------------------------------

$StartupOK =
    $Log.Contains("Application startup complete")

$StartupFailed =
    $Log.Contains("Application startup failed")

$RetrievalAttributeCrash =
    $Log.Contains("'RetrievalConfig' object has no attribute")

Write-Host "Application startup complete : $StartupOK"
Write-Host "Application startup failed   : $StartupFailed"
Write-Host "Retrieval attribute crash    : $RetrievalAttributeCrash"
Write-Host ""

# ---------------------------------------------------------------------
# 22. HTTP TEST
# ---------------------------------------------------------------------

function Http-Code {
    param([string]$Url)

    $ErrorActionPreference = "Continue"

    $Code = curl.exe `
        -s `
        -o NUL `
        -w "%{http_code}" `
        --max-time 4 `
        $Url

    $ErrorActionPreference = "Stop"

    return "$Code"
}

$RootCode    = Http-Code "http://127.0.0.1:8000/"
$DocsCode    = Http-Code "http://127.0.0.1:8000/docs"
$OpenApiCode = Http-Code "http://127.0.0.1:8000/openapi.json"

Write-Host "HTTP /             : $RootCode"
Write-Host "HTTP /docs         : $DocsCode"
Write-Host "HTTP /openapi.json : $OpenApiCode"
Write-Host ""

# ---------------------------------------------------------------------
# 23. QDRANT
# ---------------------------------------------------------------------

Write-Host "=== Qdrant ==="

$ErrorActionPreference = "Continue"

curl.exe -fsS http://127.0.0.1:6333/readyz

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host ""

# ---------------------------------------------------------------------
# 24. LM STUDIO NETWORK TEST FROM AN INDEPENDENT CONTAINER
#
# Doesn't depend on RedSight remaining alive.
# ---------------------------------------------------------------------

Write-Host "=== Docker -> LM Studio ==="

$ErrorActionPreference = "Continue"

docker run `
    --rm `
    --add-host host.docker.internal:host-gateway `
    redsight-redsight `
    python -c "import socket; s=socket.create_connection(('host.docker.internal',1234),3); print('LM_STUDIO_NETWORK=OK'); s.close()"

$LmExit = $LASTEXITCODE

$ErrorActionPreference = "Stop"

Write-Host "LM Studio network result: $LmExit"
Write-Host ""

# ---------------------------------------------------------------------
# 25. GPU TEST FROM INDEPENDENT CONTAINER
# ---------------------------------------------------------------------

Write-Host "=== Docker GPU passthrough ==="

$GpuLog = Join-Path $BackupRoot "docker-gpu-test.txt"

$ErrorActionPreference = "Continue"

$GpuResult = docker run `
    --rm `
    --gpus all `
    redsight-redsight `
    python -c "import pynvml; pynvml.nvmlInit(); print('GPU_COUNT='+str(pynvml.nvmlDeviceGetCount())); [print(i,pynvml.nvmlDeviceGetName(pynvml.nvmlDeviceGetHandleByIndex(i))) for i in range(pynvml.nvmlDeviceGetCount())]" `
    2>&1

$GpuExit = $LASTEXITCODE

$ErrorActionPreference = "Stop"

$GpuResult |
    Out-String |
    Set-Content $GpuLog

Write-Host "Docker GPU exit code: $GpuExit"

$GpuResult |
    ForEach-Object {
        Write-Host $_
    }

Write-Host ""

# ---------------------------------------------------------------------
# 26. DISCOVER ACTUAL UI
# ---------------------------------------------------------------------

Write-Host "================================================================="
Write-Host " UI DISCOVERY"
Write-Host "================================================================="

$CommandCenter =
    Join-Path $Root "app\ui\command_center.py"

$UiExists =
    Test-Path $CommandCenter

Write-Host "app\ui\command_center.py exists: $UiExists"

if ($UiExists) {

    $UiText =
        [System.IO.File]::ReadAllText($CommandCenter)

    $HasMain =
        $UiText -match '(?m)^def\s+main\s*\('

    Write-Host "command_center.py has main(): $HasMain"

    if ($HasMain) {

        $Launcher =
            Join-Path $Root "Start-RedSight-UI.ps1"

        $LauncherText = @"
Set-Location "$Root"

Write-Host "Starting RedSight Command Center..."

`$env:REDSIGHT_SERVER_URL = "http://127.0.0.1:8000"

if (Get-Command py -ErrorAction SilentlyContinue) {
    py -3.12 -m app.ui.command_center
    exit
}

if (Get-Command python -ErrorAction SilentlyContinue) {
    python -m app.ui.command_center
    exit
}

Write-Host "Python was not found on PATH."
"@

        Write-Utf8 `
            -Path $Launcher `
            -Text $LauncherText

        Write-Host ""
        Write-Host "Created Windows UI launcher:"
        Write-Host $Launcher
    }
}

Write-Host ""

# ---------------------------------------------------------------------
# 27. FINAL STATUS
# ---------------------------------------------------------------------

Write-Host "================================================================="
Write-Host " FINAL CONTAINER STATUS"
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

# ---------------------------------------------------------------------
# 28. RESULT
# ---------------------------------------------------------------------

Write-Host "================================================================="

if ($StartupOK) {
    Write-Host " REDSIGHT BACKEND STARTED SUCCESSFULLY"
}

if (-not $StartupOK) {
    Write-Host " REDSIGHT STILL HAS A LATER STARTUP BLOCKER"
}

Write-Host "================================================================="
Write-Host ""

Write-Host "Stage-2 diagnostics:"
Write-Host $BackupRoot
Write-Host ""

Write-Host "Most important file if startup still fails:"
Write-Host $LogFile
Write-Host ""

Write-Host "DO NOT delete Qdrant volumes."
Write-Host ""
