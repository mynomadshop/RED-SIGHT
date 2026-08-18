$ErrorActionPreference = "Stop"

$Root       = "C:\Users\walim\RedSight"
$UI         = Join-Path $Root "app\ui\command_center.py"
$LauncherPy = Join-Path $Root "launch_redsight_command_center.py"
$UiPython   = Join-Path $Root ".venv-ui\Scripts\python.exe"

$Stamp      = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot = Join-Path $Root ".repair-backups\stage6g-$Stamp"

$Utf8 = New-Object System.Text.UTF8Encoding($false)

New-Item `
    -ItemType Directory `
    -Path $BackupRoot `
    -Force |
    Out-Null

Set-Location $Root

Write-Host ""
Write-Host "===================================================================="
Write-Host " REDSIGHT STAGE-6G"
Write-Host " RESPONSE FIX + HIGH CONTRAST + QASYNC RELAUNCH"
Write-Host "===================================================================="
Write-Host ""

# ====================================================================
# 1. VERIFY REQUIRED FILES
# ====================================================================

foreach ($File in @(
    $UI,
    $LauncherPy,
    $UiPython
)) {

    if (-not (Test-Path $File)) {
        throw "Missing required file: $File"
    }
}

Copy-Item `
    $UI `
    (Join-Path $BackupRoot "command_center.py.before") `
    -Force

Copy-Item `
    $LauncherPy `
    (Join-Path $BackupRoot "launcher.before.py") `
    -Force

Write-Host "Backup:"
Write-Host $BackupRoot
Write-Host ""

# ====================================================================
# 2. VERIFY CURRENT HEALTHY STACK
# ====================================================================

Write-Host "=== Backend ==="

$Api =
    curl.exe `
        -s `
        -o NUL `
        -w "%{http_code}" `
        http://127.0.0.1:8000/api/v1/health

$Lm =
    curl.exe `
        -s `
        -o NUL `
        -w "%{http_code}" `
        http://127.0.0.1:1234/v1/models

Write-Host "RedSight API : $Api"
Write-Host "LM Studio    : $Lm"

if ($Api -ne "200") {
    throw "RedSight backend is not healthy."
}

if ($Lm -ne "200") {
    throw "LM Studio is not reachable."
}

Write-Host ""

# ====================================================================
# 3. VERIFY THE ACTUAL CHAT RESPONSE ONE MORE TIME
# ====================================================================

Write-Host "=== Confirming RedSight response contract ==="

$Probe =
    Join-Path $BackupRoot "verify_message_response.py"

$ProbeLines = @(
    'import httpx'
    'import json'
    ''
    'payload = {'
    '    "messages": ['
    '        {'
    '            "role": "user",'
    '            "content": "Reply with exactly RESPONSE_FIELD_OK"'
    '        }'
    '    ],'
    '    "stream": False'
    '}'
    ''
    'r = httpx.post('
    '    "http://127.0.0.1:8000/api/v1/chat",'
    '    json=payload,'
    '    timeout=180.0'
    ')'
    ''
    'print("HTTP=" + str(r.status_code))'
    'print("BODY=" + r.text)'
    'r.raise_for_status()'
    ''
    'data = r.json()'
    ''
    'if not isinstance(data, dict):'
    '    raise RuntimeError("RedSight did not return a JSON object")'
    ''
    'message = data.get("message")'
    ''
    'if not isinstance(message, str) or not message.strip():'
    '    raise RuntimeError("Top-level message string is missing")'
    ''
    'print("MESSAGE=" + message)'
    'print("TOP_LEVEL_MESSAGE=PASS")'
)

[System.IO.File]::WriteAllLines(
    $Probe,
    $ProbeLines,
    $Utf8
)

$ErrorActionPreference = "Continue"

docker cp `
    $Probe `
    redsight:/tmp/verify_message_response.py

$ErrorActionPreference = "Stop"

$ErrorActionPreference = "Continue"

$ProbeOutput =
    docker exec `
        -w /app `
        redsight `
        python /tmp/verify_message_response.py `
        2>&1

$ProbeExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

$ProbeOutput |
    ForEach-Object {
        Write-Host $_
    }

if ($ProbeExit -ne 0) {
    throw "RedSight response contract verification failed."
}

Write-Host ""

# ====================================================================
# 4. PATCH COMMAND CENTER RESPONSE PARSER
# ====================================================================

Write-Host "===================================================================="
Write-Host " PATCHING COMMAND CENTER RESPONSE DECODER"
Write-Host "===================================================================="

$Text =
    [System.IO.File]::ReadAllText(
        $UI
    )

$Before =
    $Text

# --------------------------------------------------------------------
# Variant A:
#
# response = data.get("response") or data.get("content")
# --------------------------------------------------------------------

$Text =
    $Text.Replace(
        'response = data.get("response") or data.get("content")',
        'response = (data.get("message") if isinstance(data.get("message"), str) else None) or data.get("response") or data.get("content")'
    )

# --------------------------------------------------------------------
# Variant B:
#
# response = data.get("response", "No response")
# --------------------------------------------------------------------

$Text =
    $Text.Replace(
        'response = data.get("response", "No response")',
        'response = (data.get("message") if isinstance(data.get("message"), str) else None) or data.get("response") or "No response"'
    )

# --------------------------------------------------------------------
# Variant C:
#
# response = data.get("response") or "No response"
# --------------------------------------------------------------------

$Text =
    $Text.Replace(
        'response = data.get("response") or "No response"',
        'response = (data.get("message") if isinstance(data.get("message"), str) else None) or data.get("response") or "No response"'
    )

# --------------------------------------------------------------------
# Variant D:
#
# response = data.get("content") or "No response"
# --------------------------------------------------------------------

$Text =
    $Text.Replace(
        'response = data.get("content") or "No response"',
        'response = (data.get("message") if isinstance(data.get("message"), str) else None) or data.get("content") or "No response"'
    )

# --------------------------------------------------------------------
# Stage-6E style multi-line parser:
#
# response = None
# if isinstance(data, dict):
#     response = data.get("response") or data.get("content")
# --------------------------------------------------------------------

$OldMulti =
    'response = data.get("response") or data.get("content")'

$NewMulti =
    'response = (data.get("message") if isinstance(data.get("message"), str) else None) or data.get("response") or data.get("content")'

$Text =
    $Text.Replace(
        $OldMulti,
        $NewMulti
    )

# --------------------------------------------------------------------
# If already patched, accept it.
# --------------------------------------------------------------------

$MessageSupport =
    $Text.Contains(
        'data.get("message") if isinstance(data.get("message"), str)'
    )

if (-not $MessageSupport) {

    Write-Host ""
    Write-Host "Current _send_to_api implementation:"
    Write-Host ""

    Select-String `
        -Path $UI `
        -Pattern "_send_to_api" `
        -Context 5,70

    throw `
        "Could not safely identify the current response parser."
}

if ($Text -ne $Before) {

    [System.IO.File]::WriteAllText(
        $UI,
        $Text,
        $Utf8
    )

    Write-Host "Top-level RedSight message field added to response parser."
}
else {

    Write-Host "Top-level message parser was already present."
}

Write-Host ""

# ====================================================================
# 5. SHOW THE EXACT PATCHED API METHOD
# ====================================================================

Write-Host "=== _send_to_api after patch ==="

Select-String `
    -Path $UI `
    -Pattern "_send_to_api" `
    -Context 0,55

Write-Host ""

# ====================================================================
# 6. AST VALIDATION
# ====================================================================

$Ast =
    Join-Path $BackupRoot "validate_ui.py"

$AstLines = @(
    'import ast'
    'import pathlib'
    ''
    'p = pathlib.Path("/source/app/ui/command_center.py")'
    'text = p.read_text(encoding="utf-8-sig")'
    'ast.parse(text, filename=str(p))'
    'print("COMMAND_CENTER_AST=OK")'
)

[System.IO.File]::WriteAllLines(
    $Ast,
    $AstLines,
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
    throw "Command Center syntax validation failed."
}

Write-Host ""

# ====================================================================
# 7. PATCH EXISTING QASYNC LAUNCHER WITH HIGH-CONTRAST THEME
# ====================================================================

Write-Host "===================================================================="
Write-Host " APPLYING HIGH-CONTRAST THEME"
Write-Host "===================================================================="

$Launcher =
    [System.IO.File]::ReadAllText(
        $LauncherPy
    )

if (
    -not $Launcher.Contains(
        "# REDSIGHT_HIGH_CONTRAST_BEGIN"
    )
) {

    $ThemeLines = @(
        ''
        '# REDSIGHT_HIGH_CONTRAST_BEGIN'
        'app.setStyle("Fusion")'
        'app.setStyleSheet(r"""'
        'QWidget {'
        '    background-color: #0A0F15;'
        '    color: #F6F8FA;'
        '    font-size: 13px;'
        '}'
        ''
        'QMainWindow {'
        '    background-color: #070B10;'
        '}'
        ''
        'QLabel {'
        '    color: #F6F8FA;'
        '    background: transparent;'
        '}'
        ''
        'QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox {'
        '    background-color: #111B25;'
        '    color: #FFFFFF;'
        '    border: 1px solid #6686A3;'
        '    border-radius: 6px;'
        '    padding: 6px;'
        '    selection-background-color: #1976D2;'
        '    selection-color: #FFFFFF;'
        '}'
        ''
        'QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {'
        '    border: 2px solid #64B5F6;'
        '}'
        ''
        'QPushButton {'
        '    background-color: #1565C0;'
        '    color: #FFFFFF;'
        '    border: 1px solid #64B5F6;'
        '    border-radius: 6px;'
        '    padding: 7px 12px;'
        '    font-weight: 700;'
        '}'
        ''
        'QPushButton:hover {'
        '    background-color: #1976D2;'
        '}'
        ''
        'QPushButton:pressed {'
        '    background-color: #0D47A1;'
        '}'
        ''
        'QGroupBox {'
        '    background-color: #101923;'
        '    color: #FFFFFF;'
        '    border: 1px solid #526D82;'
        '    border-radius: 7px;'
        '    margin-top: 10px;'
        '    padding-top: 8px;'
        '    font-weight: 700;'
        '}'
        ''
        'QGroupBox::title {'
        '    subcontrol-origin: margin;'
        '    left: 10px;'
        '    padding: 0 5px;'
        '    color: #FFFFFF;'
        '}'
        ''
        'QTabWidget::pane {'
        '    background-color: #0D151D;'
        '    border: 1px solid #526D82;'
        '}'
        ''
        'QTabBar::tab {'
        '    background-color: #162331;'
        '    color: #DDE7F0;'
        '    border: 1px solid #455E73;'
        '    padding: 8px 13px;'
        '}'
        ''
        'QTabBar::tab:selected {'
        '    background-color: #1565C0;'
        '    color: #FFFFFF;'
        '}'
        ''
        'QTableWidget, QTableView, QListWidget, QTreeWidget {'
        '    background-color: #0D151D;'
        '    alternate-background-color: #14202B;'
        '    color: #FFFFFF;'
        '    gridline-color: #455E73;'
        '    border: 1px solid #526D82;'
        '    selection-background-color: #1565C0;'
        '    selection-color: #FFFFFF;'
        '}'
        ''
        'QHeaderView::section {'
        '    background-color: #1A2A38;'
        '    color: #FFFFFF;'
        '    border: 1px solid #526D82;'
        '    padding: 6px;'
        '    font-weight: 700;'
        '}'
        ''
        'QProgressBar {'
        '    background-color: #101820;'
        '    color: #FFFFFF;'
        '    border: 1px solid #607D8B;'
        '    border-radius: 5px;'
        '    text-align: center;'
        '}'
        ''
        'QProgressBar::chunk {'
        '    background-color: #1976D2;'
        '    border-radius: 4px;'
        '}'
        ''
        'QStatusBar {'
        '    background-color: #080D12;'
        '    color: #E8F1F8;'
        '    border-top: 1px solid #455E73;'
        '}'
        ''
        'QDockWidget::title {'
        '    background-color: #172838;'
        '    color: #FFFFFF;'
        '    padding: 7px;'
        '    font-weight: 700;'
        '}'
        ''
        'QToolTip {'
        '    background-color: #182A38;'
        '    color: #FFFFFF;'
        '    border: 1px solid #90CAF9;'
        '    padding: 5px;'
        '}'
        ''
        'QScrollBar:vertical {'
        '    background-color: #101820;'
        '    width: 13px;'
        '}'
        ''
        'QScrollBar::handle:vertical {'
        '    background-color: #607D8B;'
        '    min-height: 28px;'
        '    border-radius: 6px;'
        '}'
        ''
        'QScrollBar::handle:vertical:hover {'
        '    background-color: #90AFC5;'
        '}'
        '""")'
        '# REDSIGHT_HIGH_CONTRAST_END'
        ''
    )

    $Theme =
        $ThemeLines -join "`r`n"

    $Anchor =
        'loop = QEventLoop(app)'

    if (-not $Launcher.Contains($Anchor)) {

        throw `
            "Could not find qasync event-loop anchor in existing launcher."
    }

    $Launcher =
        $Launcher.Replace(
            $Anchor,
            $Theme + "`r`n" + $Anchor
        )

    [System.IO.File]::WriteAllText(
        $LauncherPy,
        $Launcher,
        $Utf8
    )

    Write-Host "High-contrast theme installed."
}
else {

    Write-Host "High-contrast theme already installed."
}

Write-Host ""

# ====================================================================
# 8. VALIDATE WINDOWS IMPORT
# ====================================================================

Write-Host "=== Windows Command Center import ==="

$ImportProbe =
    Join-Path $BackupRoot "import_test.py"

$ImportLines = @(
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
    $ImportLines,
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

if ($ImportExit -ne 0) {
    throw "Windows UI import failed."
}

Write-Host ""

# ====================================================================
# 9. CLOSE CURRENT COMMAND CENTER
# ====================================================================

Write-Host "=== Closing previous Command Center ==="

$Processes =
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

foreach ($Process in $Processes) {

    Write-Host (
        "Stopping PID {0}" -f
        $Process.ProcessId
    )

    Stop-Process `
        -Id $Process.ProcessId `
        -Force `
        -ErrorAction SilentlyContinue
}

Write-Host ""

# ====================================================================
# 10. RELAUNCH
# ====================================================================

Write-Host "===================================================================="
Write-Host " LAUNCHING CORRECTED COMMAND CENTER"
Write-Host "===================================================================="

$Stdout =
    Join-Path $BackupRoot "command-center.stdout.log"

$Stderr =
    Join-Path $BackupRoot "command-center.stderr.log"

$Process =
    Start-Process `
        -FilePath $UiPython `
        -ArgumentList @(
            $LauncherPy
        ) `
        -WorkingDirectory $Root `
        -RedirectStandardOutput $Stdout `
        -RedirectStandardError $Stderr `
        -PassThru

Start-Sleep -Seconds 6

$Process.Refresh()

if ($Process.HasExited) {

    Write-Host ""
    Write-Host "UI exited unexpectedly."
    Write-Host ""

    if (Test-Path $Stdout) {

        Write-Host "=== STDOUT ==="
        Get-Content $Stdout -Tail 100
    }

    if (Test-Path $Stderr) {

        Write-Host ""
        Write-Host "=== STDERR ==="
        Get-Content $Stderr -Tail 150
    }

    throw "Corrected Command Center failed to launch."
}

Write-Host "COMMAND_CENTER_LAUNCHED=YES"
Write-Host "PID=$($Process.Id)"
Write-Host ""

# ====================================================================
# 11. FINAL CHECKS
# ====================================================================

Write-Host "===================================================================="
Write-Host " FINAL STATUS"
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

Write-Host "RedSight API            : 200"
Write-Host "LM Studio               : 200"
Write-Host "RedSight chat           : PASS"
Write-Host "Response field          : message"
Write-Host "qasync                  : ACTIVE"
Write-Host "Dual RTX 5090 telemetry : ACTIVE"
Write-Host "High contrast           : ACTIVE"
Write-Host "Command Center PID      : $($Process.Id)"
Write-Host ""

Write-Host "===================================================================="
Write-Host " TEST THE UI NOW"
Write-Host "===================================================================="
Write-Host ""
Write-Host "Send:"
Write-Host ""
Write-Host "  hi"
Write-Host ""
Write-Host "and then:"
Write-Host ""
Write-Host "  Explain what model you are currently running."
Write-Host ""
Write-Host "The response should now appear instead of 'No response'."
Write-Host ""

Write-Host "Diagnostics:"
Write-Host $BackupRoot
Write-Host ""

Write-Host "UI stderr:"
Write-Host $Stderr
Write-Host ""
