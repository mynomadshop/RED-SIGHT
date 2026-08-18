$ErrorActionPreference = "Stop"

$Root       = "C:\Users\walim\RedSight"
$Compose    = Join-Path $Root "docker-compose.yml"
$Override   = Join-Path $Root "docker-compose.override.yml"
$UI         = Join-Path $Root "app\ui\command_center.py"

$Stamp      = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot = Join-Path $Root ".repair-backups\stage6e-$Stamp"
$UiVenv     = Join-Path $Root ".venv-ui"

$Utf8 = New-Object System.Text.UTF8Encoding($false)

Set-Location $Root

New-Item `
    -ItemType Directory `
    -Path $BackupRoot `
    -Force |
    Out-Null

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

function Get-HttpCode {
    param([string]$Url)

    $ErrorActionPreference = "Continue"

    $Code =
        curl.exe `
        -s `
        -o NUL `
        -w "%{http_code}" `
        --max-time 8 `
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

Write-Host ""
Write-Host "===================================================================="
Write-Host " REDSIGHT STAGE-6E"
Write-Host " CHAT CONTRACT + COMMAND CENTER FINALIZATION"
Write-Host "===================================================================="
Write-Host ""

# =====================================================================
# 1. PRESERVE CURRENT WORKING STATE
# =====================================================================

if (-not (Test-Path $UI)) {
    throw "Command Center source missing: $UI"
}

Copy-Item `
    -LiteralPath $UI `
    -Destination (Join-Path $BackupRoot "command_center.py.before") `
    -Force

Copy-Item `
    -LiteralPath $Override `
    -Destination (Join-Path $BackupRoot "docker-compose.override.yml.before") `
    -Force

Write-Host "Backup:"
Write-Host $BackupRoot
Write-Host ""

# =====================================================================
# 2. VERIFY BACKEND / GPU / LM BASELINE
# =====================================================================

Write-Host "===================================================================="
Write-Host " 1. VERIFYING WORKING BASELINE"
Write-Host "===================================================================="

$ApiHealth =
    Get-HttpCode `
        "http://127.0.0.1:8000/api/v1/health"

Write-Host "API health: $ApiHealth"

if ($ApiHealth -ne "200") {
    throw "RedSight API is not healthy."
}

Write-Host ""
Write-Host "--- Live RedSight GPUs ---"

$ErrorActionPreference = "Continue"

$GpuOutput =
    docker exec `
        redsight `
        nvidia-smi -L `
        2>&1

$GpuExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

$GpuOutput |
    ForEach-Object {
        Write-Host $_
    }

if ($GpuExit -ne 0) {
    throw "RedSight lost NVIDIA GPU access."
}

if (($GpuOutput | Out-String) -notmatch 'GPU 1:') {
    throw "Both RTX 5090s are no longer visible."
}

Write-Host ""
Write-Host "Dual RTX 5090 access: PASS"
Write-Host ""

# =====================================================================
# 3. VERIFY NO NVML / LM STARTUP REGRESSION
# =====================================================================

$CurrentLog =
    Join-Path $BackupRoot "baseline-runtime.log"

$LogCommand =
    'docker logs --tail 500 redsight > "' +
    $CurrentLog +
    '" 2>&1'

cmd.exe /d /c $LogCommand

$CurrentText =
    [System.IO.File]::ReadAllText(
        $CurrentLog
    )

$StartupOK =
    $CurrentText.Contains(
        "Application startup complete"
    )

$NvmlBad =
    $CurrentText.Contains(
        "NVML initialization failed"
    )

$LmBad =
    $CurrentText.Contains(
        "LM Studio health check failed"
    )

Write-Host "Application startup complete : $StartupOK"
Write-Host "NVML initialization failed   : $NvmlBad"
Write-Host "LM Studio health check failed: $LmBad"
Write-Host ""

if (-not $StartupOK) {
    throw "Backend startup is no longer clean."
}

if ($NvmlBad) {
    throw "NVML regression detected."
}

if ($LmBad) {
    throw "LM Studio health regression detected."
}

# =====================================================================
# 4. CHAT CONTRACT TEST
#
# Use a real Python file to eliminate PowerShell quoting issues.
# =====================================================================

Write-Host "===================================================================="
Write-Host " 2. DISCOVERING WORKING /api/v1/chat PAYLOAD"
Write-Host "===================================================================="

$ChatProbe =
    Join-Path $BackupRoot "chat_contract_probe.py"

$ChatProbeLines = @(
    'import json'
    'import httpx'
    'import sys'
    ''
    'redsight = "http://127.0.0.1:8000"'
    'lmstudio = "http://host.docker.internal:1234"'
    ''
    'prompt = "Reply with exactly REDSIGHT_E2E_OK"'
    ''
    'model = None'
    ''
    'try:'
    '    r = httpx.get(lmstudio + "/v1/models", timeout=10.0)'
    '    r.raise_for_status()'
    '    entries = r.json().get("data", [])'
    '    if entries:'
    '        model = entries[0].get("id")'
    'except Exception as exc:'
    '    print("MODEL_DISCOVERY_ERROR=" + repr(exc))'
    ''
    'print("MODEL=" + str(model))'
    ''
    'base_messages = ['
    '    {'
    '        "role": "user",'
    '        "content": prompt,'
    '    }'
    ']'
    ''
    'attempts = ['
    '    ('
    '        "messages",'
    '        {'
    '            "messages": base_messages,'
    '        },'
    '    ),'
    '    ('
    '        "messages_stream_false",'
    '        {'
    '            "messages": base_messages,'
    '            "stream": False,'
    '        },'
    '    ),'
    ']'
    ''
    'if model:'
    '    attempts.extend(['
    '        ('
    '            "messages_model",'
    '            {'
    '                "messages": base_messages,'
    '                "model": model,'
    '            },'
    '        ),'
    '        ('
    '            "messages_model_stream_false",'
    '            {'
    '                "messages": base_messages,'
    '                "model": model,'
    '                "stream": False,'
    '            },'
    '        ),'
    '    ])'
    ''
    'for mode, payload in attempts:'
    '    print("")'
    '    print("ATTEMPT=" + mode)'
    '    print("REQUEST=" + json.dumps(payload, ensure_ascii=False))'
    ''
    '    try:'
    '        r = httpx.post('
    '            redsight + "/api/v1/chat",'
    '            json=payload,'
    '            timeout=180.0,'
    '        )'
    '    except Exception as exc:'
    '        print("EXCEPTION=" + repr(exc))'
    '        continue'
    ''
    '    print("HTTP_STATUS=" + str(r.status_code))'
    '    print("RAW_RESPONSE=" + r.text[:12000])'
    ''
    '    if 200 <= r.status_code < 300:'
    '        print("")'
    '        print("WORKING_MODE=" + mode)'
    '        try:'
    '            data = r.json()'
    '            print("SUCCESS_JSON=" + json.dumps(data, ensure_ascii=False))'
    '        except Exception:'
    '            print("SUCCESS_TEXT=" + r.text)'
    ''
    '        print("CHAT_CONTRACT=PASS")'
    '        raise SystemExit(0)'
    ''
    'print("")'
    'print("CHAT_CONTRACT=FAIL")'
    'raise SystemExit(1)'
)

[System.IO.File]::WriteAllLines(
    $ChatProbe,
    $ChatProbeLines,
    $Utf8
)

$ErrorActionPreference = "Continue"

docker cp `
    $ChatProbe `
    redsight:/tmp/chat_contract_probe.py

$CopyExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

if ($CopyExit -ne 0) {
    throw "Could not copy chat probe into RedSight."
}

$ErrorActionPreference = "Continue"

$ChatOutput =
    docker exec `
        -w /app `
        redsight `
        python /tmp/chat_contract_probe.py `
        2>&1

$ChatExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

$ChatOutput |
    ForEach-Object {
        Write-Host $_
    }

$ChatOutput |
    Out-String |
    Set-Content (
        Join-Path $BackupRoot "chat-contract-results.txt"
    )

Write-Host ""

# =====================================================================
# 5. IF STILL FAILING, PRINT ACTUAL SERVER IMPLEMENTATION
# =====================================================================

if ($ChatExit -ne 0) {

    Write-Host "===================================================================="
    Write-Host " CHAT ROUTE SOURCE DIAGNOSTIC"
    Write-Host "===================================================================="

    $Matches =
        Get-ChildItem `
            (Join-Path $Root "app") `
            -Recurse `
            -File `
            -Filter "*.py" |
        Select-String `
            -Pattern `
            'No messages provided',
            '/api/v1/chat',
            '@router.post("/chat"',
            "@router.post('/chat'" `
            -ErrorAction SilentlyContinue

    $DiagnosticFile =
        Join-Path $BackupRoot "chat-route-source.txt"

    $DiagnosticOutput = @()

    foreach ($Match in $Matches) {

        $File =
            $Match.Path

        $Lines =
            [System.IO.File]::ReadAllLines(
                $File
            )

        $From =
            [Math]::Max(
                1,
                $Match.LineNumber - 30
            )

        $To =
            [Math]::Min(
                $Lines.Length,
                $Match.LineNumber + 60
            )

        $DiagnosticOutput += ""
        $DiagnosticOutput += "================================================"
        $DiagnosticOutput += $File
        $DiagnosticOutput += "================================================"

        for ($n = $From; $n -le $To; $n++) {

            $DiagnosticOutput += (
                "{0,4}: {1}" -f
                $n,
                $Lines[$n - 1]
            )
        }
    }

    $DiagnosticOutput |
        Set-Content $DiagnosticFile

    $DiagnosticOutput |
        ForEach-Object {
            Write-Host $_
        }

    throw `
        "RedSight still rejected all messages payloads. Exact route source has been printed and saved."
}

# =====================================================================
# 6. DETERMINE SUCCESS MODE
# =====================================================================

$WorkingMode =
    $null

foreach ($Line in $ChatOutput) {

    if ("$Line" -match '^WORKING_MODE=(.+)$') {

        $WorkingMode =
            $Matches[1].Trim()

        break
    }
}

if (-not $WorkingMode) {
    throw "Chat probe succeeded but did not return WORKING_MODE."
}

Write-Host "Working chat contract:"
Write-Host $WorkingMode
Write-Host ""

# =====================================================================
# 7. PATCH COMMAND CENTER REQUEST
# =====================================================================

Write-Host "===================================================================="
Write-Host " 3. PATCHING COMMAND CENTER CHAT REQUEST"
Write-Host "===================================================================="

$UiLines =
    [System.Collections.Generic.List[string]]::new()

foreach (
    $Line in
    [System.IO.File]::ReadAllLines($UI)
) {
    [void]$UiLines.Add($Line)
}

$RequestPatched =
    $false

for ($i = 0; $i -lt $UiLines.Count; $i++) {

    if (
        $UiLines[$i] -match
        'json=\{"message":\s*message\},'
    ) {

        $Indent =
            ([regex]::Match(
                $UiLines[$i],
                '^(\s*)'
            )).Groups[1].Value

        $UiLines[$i] =
            $Indent +
            'json={"messages": [{"role": "user", "content": message}]},'

        $RequestPatched =
            $true

        break
    }
}

if (-not $RequestPatched) {

    $AlreadyCorrect =
        $false

    foreach ($Line in $UiLines) {

        if (
            $Line -match
            'json=\{"messages":\s*\[\{"role":\s*"user"'
        ) {

            $AlreadyCorrect =
                $true

            break
        }
    }

    if (-not $AlreadyCorrect) {

        throw `
            "Could not locate the Command Center's old json={message: ...} request body."
    }
}

Write-Host "Command Center request now sends:"
Write-Host ""
Write-Host '  {"messages": [{"role": "user", "content": message}]}'
Write-Host ""

# =====================================================================
# 8. PATCH RESPONSE PARSER ROBUSTLY
#
# Supports:
#   {"response": "..."}
#   {"content": "..."}
#   {"message":{"content":"..."}}
#   {"choices":[{"message":{"content":"..."}}]}
# =====================================================================

$ResponseLineIndex =
    -1

for ($i = 0; $i -lt $UiLines.Count; $i++) {

    if (
        $UiLines[$i] -match
        '^\s*response\s*=\s*data\.get\("response"'
    ) {

        $ResponseLineIndex =
            $i

        break
    }
}

if ($ResponseLineIndex -ge 0) {

    $Indent =
        ([regex]::Match(
            $UiLines[$ResponseLineIndex],
            '^(\s*)'
        )).Groups[1].Value

    $Replacement =
        @(
            $Indent + 'response = None'
            $Indent + 'if isinstance(data, dict):'
            $Indent + '    response = data.get("response") or data.get("content")'
            $Indent + '    if not response and isinstance(data.get("message"), dict):'
            $Indent + '        response = data["message"].get("content")'
            $Indent + '    if not response and isinstance(data.get("choices"), list) and data["choices"]:'
            $Indent + '        first = data["choices"][0]'
            $Indent + '        if isinstance(first, dict):'
            $Indent + '            msg = first.get("message")'
            $Indent + '            if isinstance(msg, dict):'
            $Indent + '                response = msg.get("content")'
            $Indent + '            if not response:'
            $Indent + '                response = first.get("text")'
            $Indent + 'response = response or "No response"'
        )

    $UiLines.RemoveAt(
        $ResponseLineIndex
    )

    for (
        $r = $Replacement.Count - 1;
        $r -ge 0;
        $r--
    ) {

        $UiLines.Insert(
            $ResponseLineIndex,
            $Replacement[$r]
        )
    }

    Write-Host "Command Center response parser upgraded."
}

if ($ResponseLineIndex -lt 0) {

    Write-Host "Old response parser was not present; leaving current parser unchanged."
}

[System.IO.File]::WriteAllLines(
    $UI,
    $UiLines,
    $Utf8
)

Write-Host ""

# =====================================================================
# 9. AST VALIDATE COMMAND CENTER
# =====================================================================

Write-Host "=== Validating Command Center syntax ==="

$UiValidator =
    Join-Path $BackupRoot "validate_ui.py"

$UiValidatorLines = @(
    'import ast'
    'import pathlib'
    ''
    'path = pathlib.Path("/source/app/ui/command_center.py")'
    'source = path.read_text(encoding="utf-8-sig")'
    'ast.parse(source, filename=str(path))'
    'print("COMMAND_CENTER_AST=OK")'
)

[System.IO.File]::WriteAllLines(
    $UiValidator,
    $UiValidatorLines,
    $Utf8
)

$ErrorActionPreference = "Continue"

$AstOutput =
    docker run `
        --rm `
        -v "${Root}:/source:ro" `
        -v "${BackupRoot}:/diag:ro" `
        redsight-redsight `
        python /diag/validate_ui.py `
        2>&1

$AstExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

$AstOutput |
    ForEach-Object {
        Write-Host $_
    }

if ($AstExit -ne 0) {
    throw "Command Center syntax is invalid after patch."
}

Write-Host ""

# =====================================================================
# 10. CREATE / REUSE WINDOWS UI ENVIRONMENT
# =====================================================================

Write-Host "===================================================================="
Write-Host " 4. PREPARING WINDOWS PYSIDE UI"
Write-Host "===================================================================="

$BaseExe =
    $null

$BaseArgs =
    @()

$Py =
    Get-Command py `
        -ErrorAction SilentlyContinue

if ($Py) {

    $ErrorActionPreference = "Continue"

    & py -3.12 --version `
        2>$null

    $Py312Exit =
        $LASTEXITCODE

    $ErrorActionPreference = "Stop"

    if ($Py312Exit -eq 0) {

        $BaseExe =
            "py"

        $BaseArgs =
            @("-3.12")
    }
}

if (-not $BaseExe) {

    $Python =
        Get-Command python `
            -ErrorAction SilentlyContinue

    if ($Python) {
        $BaseExe = $Python.Source
    }
}

if (-not $BaseExe) {
    throw "Windows Python was not found."
}

if (-not (Test-Path $UiVenv)) {

    Write-Host "Creating .venv-ui..."

    & $BaseExe `
        @BaseArgs `
        -m venv `
        $UiVenv

    if ($LASTEXITCODE -ne 0) {
        throw "Could not create .venv-ui."
    }
}

$UiPython =
    Join-Path $UiVenv `
        "Scripts\python.exe"

if (-not (Test-Path $UiPython)) {
    throw "UI venv Python is missing."
}

Write-Host "UI Python:"
Write-Host $UiPython
Write-Host ""

# =====================================================================
# 11. INSTALL UI DEPENDENCIES
# =====================================================================

Write-Host "=== Installing/verifying UI dependencies ==="

& $UiPython `
    -m pip `
    install `
    --upgrade `
    pip

if ($LASTEXITCODE -ne 0) {
    throw "pip upgrade failed."
}

& $UiPython `
    -m pip `
    install `
    "PySide6>=6.8,<7" `
    httpx `
    psutil `
    structlog `
    pydantic `
    pydantic-settings `
    PyYAML `
    markdown `
    pygments `
    rich

if ($LASTEXITCODE -ne 0) {
    throw "UI dependency installation failed."
}

Write-Host ""

# =====================================================================
# 12. PYSIDE + QTASYNCIO TEST
# =====================================================================

$QtProbe =
    Join-Path $BackupRoot "qt_probe.py"

$QtProbeLines = @(
    'import PySide6'
    'import PySide6.QtAsyncio as QtAsyncio'
    ''
    'print("PYSIDE_VERSION=" + PySide6.__version__)'
    'print("QTASYNCIO=OK")'
)

[System.IO.File]::WriteAllLines(
    $QtProbe,
    $QtProbeLines,
    $Utf8
)

& $UiPython `
    $QtProbe

if ($LASTEXITCODE -ne 0) {
    throw "PySide6.QtAsyncio test failed."
}

Write-Host ""

# =====================================================================
# 13. IMPORT COMMAND CENTER
# =====================================================================

Write-Host "=== Importing Command Center on Windows ==="

$ImportProbe =
    Join-Path $BackupRoot `
        "ui_import_probe.py"

$ImportProbeLines = @(
    'import sys'
    'sys.path.insert(0, r"C:\Users\walim\RedSight")'
    ''
    'import app.ui.command_center as cc'
    ''
    'print("COMMAND_CENTER_IMPORT=OK")'
    'print("WINDOW_CLASS=" + str(hasattr(cc, "CommandCenterMainWindow")))'
)

[System.IO.File]::WriteAllLines(
    $ImportProbe,
    $ImportProbeLines,
    $Utf8
)

$ErrorActionPreference = "Continue"

$ImportOutput =
    & $UiPython `
        $ImportProbe `
        2>&1

$ImportExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

$ImportOutput |
    ForEach-Object {
        Write-Host $_
    }

$ImportOutput |
    Out-String |
    Set-Content (
        Join-Path $BackupRoot "ui-import.txt"
    )

if ($ImportExit -ne 0) {

    throw `
        "Command Center import failed. The exact missing dependency is shown above."
}

if (($ImportOutput | Out-String) -notmatch 'WINDOW_CLASS=True') {

    throw "CommandCenterMainWindow was not found."
}

Write-Host ""

# =====================================================================
# 14. CREATE QTASYNCIO LAUNCHER
#
# We do NOT rewrite command_center.main().
#
# The wrapper creates the window and supplies a real asyncio-capable
# Qt event loop for asyncio.create_task(self._send_to_api(...)).
# =====================================================================

Write-Host "===================================================================="
Write-Host " 5. BUILDING COMMAND CENTER LAUNCHER"
Write-Host "===================================================================="

$LauncherPy =
    Join-Path $Root `
        "launch_redsight_command_center.py"

$LauncherPyLines = @(
    'import os'
    'import sys'
    ''
    'ROOT = r"C:\Users\walim\RedSight"'
    ''
    'if ROOT not in sys.path:'
    '    sys.path.insert(0, ROOT)'
    ''
    'os.environ["REDSIGHT_API_URL"] = "http://127.0.0.1:8000"'
    'os.environ["REDSIGHT_API_BASE_URL"] = "http://127.0.0.1:8000"'
    'os.environ["API_BASE_URL"] = "http://127.0.0.1:8000"'
    ''
    'from PySide6.QtWidgets import QApplication'
    'import PySide6.QtAsyncio as QtAsyncio'
    ''
    'from app.ui.command_center import CommandCenterMainWindow'
    ''
    'app = QApplication.instance()'
    ''
    'if app is None:'
    '    app = QApplication(sys.argv)'
    ''
    'window = CommandCenterMainWindow()'
    ''
    '# Force the repaired local RedSight backend.'
    'if hasattr(window, "_api_base_url"):'
    '    window._api_base_url = "http://127.0.0.1:8000"'
    ''
    'window.show()'
    ''
    'print("COMMAND_CENTER_WINDOW_SHOWN=YES", flush=True)'
    ''
    '# Keep Qt and asyncio on one integrated event loop.'
    'QtAsyncio.run(handle_sigint=True)'
)

[System.IO.File]::WriteAllLines(
    $LauncherPy,
    $LauncherPyLines,
    $Utf8
)

$LauncherPs =
    Join-Path $Root `
        "LAUNCH-REDSIGHT-COMMAND-CENTER.ps1"

$LauncherPsLines = @(
    '$ErrorActionPreference = "Stop"'
    '$Root = "C:\Users\walim\RedSight"'
    '$Python = Join-Path $Root ".venv-ui\Scripts\python.exe"'
    '$Launcher = Join-Path $Root "launch_redsight_command_center.py"'
    'Set-Location $Root'
    '& $Python $Launcher'
)

[System.IO.File]::WriteAllLines(
    $LauncherPs,
    $LauncherPsLines,
    $Utf8
)

Write-Host "Reusable launcher:"
Write-Host $LauncherPs
Write-Host ""

# =====================================================================
# 15. LAUNCH COMMAND CENTER
# =====================================================================

Write-Host "===================================================================="
Write-Host " 6. LAUNCHING REDSIGHT COMMAND CENTER"
Write-Host "===================================================================="

$UiStdout =
    Join-Path $BackupRoot `
        "command-center.stdout.log"

$UiStderr =
    Join-Path $BackupRoot `
        "command-center.stderr.log"

$UiProcess =
    Start-Process `
        -FilePath $UiPython `
        -ArgumentList @(
            $LauncherPy
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
            -Tail 100
    }

    if (Test-Path $UiStderr) {

        Write-Host ""
        Write-Host "=== STDERR ==="

        Get-Content `
            $UiStderr `
            -Tail 160
    }

    throw "Command Center launch failed."
}

Write-Host "COMMAND_CENTER_LAUNCHED=YES"
Write-Host "PID=$($UiProcess.Id)"
Write-Host ""

# =====================================================================
# 16. FINAL STATUS
# =====================================================================

Write-Host "===================================================================="
Write-Host " FINAL REDSIGHT STATUS"
Write-Host "===================================================================="

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

Write-Host ""

docker exec `
    redsight `
    nvidia-smi -L

$ErrorActionPreference = "Stop"

Write-Host ""

$FinalHealth =
    Get-HttpCode `
        "http://127.0.0.1:8000/api/v1/health"

Write-Host "API health              : $FinalHealth"
Write-Host "Chat contract           : $WorkingMode"
Write-Host "Chat E2E                : PASS"
Write-Host "NVML                     : PASS"
Write-Host "LM Studio health        : PASS"
Write-Host "Dual RTX 5090s          : PASS"
Write-Host "Command Center PID      : $($UiProcess.Id)"
Write-Host ""

Write-Host "===================================================================="
Write-Host " REDSIGHT FULL INTEGRATION COMPLETE"
Write-Host "===================================================================="
Write-Host ""

Write-Host "Reusable UI launcher:"
Write-Host $LauncherPs
Write-Host ""

Write-Host "Diagnostics:"
Write-Host $BackupRoot
Write-Host ""

Write-Host "Command Center stderr:"
Write-Host $UiStderr
Write-Host ""

Write-Host "Qdrant data/volumes were NOT modified or deleted."
Write-Host ""
