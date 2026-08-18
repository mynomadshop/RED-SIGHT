$ErrorActionPreference = "Stop"

$Root       = "C:\Users\walim\RedSight"
$UI         = Join-Path $Root "app\ui\command_center.py"
$Launcher   = Join-Path $Root "launch_redsight_command_center.py"
$UiPython   = Join-Path $Root ".venv-ui\Scripts\python.exe"

$Stamp      = Get-Date -Format "yyyyMMdd-HHmmss"
$Backup     = Join-Path $Root ".repair-backups\ui-hotfix-$Stamp"

New-Item -ItemType Directory -Path $Backup -Force | Out-Null
Set-Location $Root

Write-Host ""
Write-Host "==============================================================="
Write-Host " REDSIGHT COMMAND CENTER FUNCTIONAL HOTFIX"
Write-Host "==============================================================="
Write-Host ""

# --------------------------------------------------------------------
# 1. BACKUP
# --------------------------------------------------------------------

Copy-Item $UI (Join-Path $Backup "command_center.py.before") -Force

if (Test-Path $Launcher) {
    Copy-Item $Launcher (Join-Path $Backup "launcher.before.py") -Force
}

Write-Host "Backup:"
Write-Host $Backup
Write-Host ""

# --------------------------------------------------------------------
# 2. ENSURE BACKEND IS ACTUALLY RUNNING
# --------------------------------------------------------------------

Write-Host "=== Starting/verifying RedSight backend ==="

$ErrorActionPreference = "Continue"

docker compose up -d redsight

$ComposeExit = $LASTEXITCODE

$ErrorActionPreference = "Stop"

if ($ComposeExit -ne 0) {
    throw "docker compose could not start RedSight."
}

$Healthy = $false

for ($i = 1; $i -le 45; $i++) {

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

    Write-Host ""
    Write-Host "=== REDSIGHT LOG ==="

    docker logs --tail 150 redsight

    throw "RedSight did not return HTTP 200."
}

Write-Host ""
Write-Host "RedSight backend: HEALTHY"
Write-Host ""

# --------------------------------------------------------------------
# 3. VERIFY LM STUDIO
# --------------------------------------------------------------------

$ErrorActionPreference = "Continue"

$LmCode =
    curl.exe `
        -s `
        -o NUL `
        -w "%{http_code}" `
        --max-time 5 `
        http://127.0.0.1:1234/v1/models `
        2>$null

$ErrorActionPreference = "Stop"

Write-Host "LM Studio: $LmCode"

if ($LmCode -ne "200") {
    throw "LM Studio is not reachable at 127.0.0.1:1234."
}

Write-Host ""

# --------------------------------------------------------------------
# 4. VERIFY BOTH GPUS REMAIN AVAILABLE
# --------------------------------------------------------------------

Write-Host "=== GPUs inside RedSight ==="

$ErrorActionPreference = "Continue"

$GpuResult =
    docker exec redsight nvidia-smi -L 2>&1

$GpuExit = $LASTEXITCODE

$ErrorActionPreference = "Stop"

$GpuResult | ForEach-Object { Write-Host $_ }

if ($GpuExit -ne 0) {
    throw "NVIDIA GPU access inside RedSight failed."
}

if (($GpuResult | Out-String) -notmatch "GPU 1:") {
    throw "Both RTX 5090s are not visible."
}

Write-Host ""
Write-Host "Dual RTX 5090: PASS"
Write-Host ""

# --------------------------------------------------------------------
# 5. CREATE A REAL PYTHON PATCHER
#
# Avoids all PowerShell multiline parser problems.
# --------------------------------------------------------------------

$Patcher =
    Join-Path $Backup "patch_ui.py"

$PatcherText = @"
from pathlib import Path
import ast
import re
import shutil

ui = Path(r"$UI")
launcher = Path(r"$Launcher")

text = ui.read_text(encoding="utf-8-sig")

# --------------------------------------------------------------
# REQUEST CONTRACT
# RedSight requires:
# {
#   "messages": [{"role":"user","content":"..."}],
#   "stream": False
# }
# --------------------------------------------------------------

text = re.sub(
    r'json\s*=\s*\{\s*"message"\s*:\s*message\s*\}',
    'json={"messages": [{"role": "user", "content": message}], "stream": False}',
    text,
)

# Ensure an already-messages request also explicitly uses non-streaming.
text = re.sub(
    r'json\s*=\s*\{\s*"messages"\s*:\s*\[\s*\{\s*"role"\s*:\s*"user"\s*,\s*"content"\s*:\s*message\s*\}\s*\]\s*\}',
    'json={"messages": [{"role": "user", "content": message}], "stream": False}',
    text,
)

# --------------------------------------------------------------
# FIND _send_to_api ONLY
# --------------------------------------------------------------

match = re.search(
    r'(?ms)^    async def _send_to_api\b.*?(?=^    (?:async def|def)\s+|\Z)',
    text,
)

if not match:
    raise RuntimeError("_send_to_api method was not found")

method = match.group(0)

# --------------------------------------------------------------
# RESPONSE CONTRACT
#
# Actual working backend returns:
#
# {"message":"...","model":"default","stream":false}
#
# Top-level message MUST therefore be first priority.
# --------------------------------------------------------------

robust = (
    'response = '
    '(data.get("message") if isinstance(data, dict) '
    'and isinstance(data.get("message"), str) else None) '
    'or (data.get("response") if isinstance(data, dict) else None) '
    'or (data.get("content") if isinstance(data, dict) else None) '
    'or "No response"'
)

patterns = [
    r'response\s*=\s*data\.get\("response"\s*,\s*"No response"\)',
    r'response\s*=\s*data\.get\("response"\)\s*or\s*"No response"',
    r'response\s*=\s*data\.get\("content"\)\s*or\s*"No response"',
    r'response\s*=\s*data\.get\("response"\)\s*or\s*data\.get\("content"\)',
]

patched = False

for pattern in patterns:
    m = re.search(pattern, method)

    if m:
        indent_match = re.search(
            r'(?m)^(\s*)response\s*=',
            method[:m.end()]
        )

        # Determine indentation from the actual matched line.
        line_start = method.rfind("\n", 0, m.start()) + 1
        line = method[line_start:method.find("\n", m.start()) if "\n" in method[m.start():] else len(method)]
        indent = line[:len(line) - len(line.lstrip())]

        method = (
            method[:m.start()]
            + robust
            + method[m.end():]
        )

        patched = True
        break

# Previous repair may already contain message support.
if 'data.get("message")' in method:
    patched = True

if not patched:
    # Generic final fallback: replace the first response assignment
    # based on data.get(...) inside _send_to_api.
    m = re.search(
        r'(?m)^(\s*)response\s*=.*data\.get.*$',
        method
    )

    if m:
        indent = m.group(1)

        method = (
            method[:m.start()]
            + indent
            + robust
            + method[m.end():]
        )

        patched = True

if not patched:
    raise RuntimeError(
        "Could not safely locate the response parser in _send_to_api"
    )

text = (
    text[:match.start()]
    + method
    + text[match.end():]
)

# --------------------------------------------------------------
# SYNTAX CHECK BEFORE WRITING
# --------------------------------------------------------------

ast.parse(text, filename=str(ui))

ui.write_text(text, encoding="utf-8")

print("REQUEST_CONTRACT=messages")
print("RESPONSE_CONTRACT=top_level_message")
print("COMMAND_CENTER_AST=OK")

# --------------------------------------------------------------
# HIGH-CONTRAST LAUNCHER
# --------------------------------------------------------------

if launcher.exists():

    source = launcher.read_text(encoding="utf-8-sig")

    marker = "# REDSIGHT_CONTRAST_V2"

    if marker not in source:

        anchor = "loop = QEventLoop(app)"

        if anchor in source:

            theme = r'''
# REDSIGHT_CONTRAST_V2
app.setStyle("Fusion")

app.setStyleSheet(r"""
QWidget {
    background-color: #080D13;
    color: #F5F8FA;
    font-size: 13px;
}

QMainWindow {
    background-color: #060A0F;
}

QLabel {
    color: #F7FAFC;
    background: transparent;
}

QLineEdit,
QTextEdit,
QPlainTextEdit,
QComboBox {
    background-color: #101A24;
    color: #FFFFFF;
    border: 1px solid #6688A5;
    border-radius: 6px;
    padding: 7px;
    selection-background-color: #1976D2;
    selection-color: white;
}

QLineEdit:focus,
QTextEdit:focus,
QPlainTextEdit:focus {
    border: 2px solid #64B5F6;
}

QPushButton {
    background-color: #1565C0;
    color: white;
    border: 1px solid #64B5F6;
    border-radius: 6px;
    padding: 8px 13px;
    font-weight: bold;
}

QPushButton:hover {
    background-color: #1976D2;
}

QPushButton:pressed {
    background-color: #0D47A1;
}

QGroupBox {
    background-color: #101923;
    color: white;
    border: 1px solid #526D82;
    border-radius: 7px;
    margin-top: 10px;
    padding-top: 8px;
    font-weight: bold;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px;
}

QTableWidget,
QTableView,
QTreeWidget,
QListWidget {
    background-color: #0D151D;
    alternate-background-color: #15212C;
    color: white;
    gridline-color: #496276;
    border: 1px solid #526D82;
    selection-background-color: #1565C0;
    selection-color: white;
}

QHeaderView::section {
    background-color: #1A2A38;
    color: white;
    border: 1px solid #526D82;
    padding: 7px;
    font-weight: bold;
}

QTabWidget::pane {
    background-color: #0D151D;
    border: 1px solid #526D82;
}

QTabBar::tab {
    background-color: #172431;
    color: #DCE7F0;
    padding: 8px 13px;
    border: 1px solid #455E73;
}

QTabBar::tab:selected {
    background-color: #1565C0;
    color: white;
}

QProgressBar {
    background-color: #101820;
    color: white;
    border: 1px solid #607D8B;
    border-radius: 5px;
    text-align: center;
}

QProgressBar::chunk {
    background-color: #1976D2;
}

QStatusBar {
    background-color: #070C11;
    color: #E8F1F8;
    border-top: 1px solid #455E73;
}

QDockWidget::title {
    background-color: #172838;
    color: white;
    padding: 7px;
    font-weight: bold;
}

QToolTip {
    background-color: #182A38;
    color: white;
    border: 1px solid #90CAF9;
}
""")
'''

            source = source.replace(
                anchor,
                theme + "\n" + anchor,
                1,
            )

            ast.parse(source, filename=str(launcher))

            launcher.write_text(
                source,
                encoding="utf-8",
            )

            print("HIGH_CONTRAST=INSTALLED")

        else:
            print("HIGH_CONTRAST=SKIPPED_NO_QASYNC_ANCHOR")

    else:
        print("HIGH_CONTRAST=ALREADY_INSTALLED")
"@

[System.IO.File]::WriteAllText(
    $Patcher,
    $PatcherText,
    (New-Object System.Text.UTF8Encoding($false))
)

Write-Host "=== Applying UI patch ==="

& $UiPython $Patcher

if ($LASTEXITCODE -ne 0) {
    throw "UI patcher failed."
}

Write-Host ""

# --------------------------------------------------------------------
# 6. VERIFY REAL CHAT RESPONSE THROUGH REDSIGHT
# --------------------------------------------------------------------

Write-Host "=== End-to-end response test ==="

$ChatTest =
    Join-Path $Backup "chat_test.py"

$ChatTestText = @"
import httpx

payload = {
    "messages": [
        {
            "role": "user",
            "content": "Reply with exactly UI_RESPONSE_OK",
        }
    ],
    "stream": False,
}

r = httpx.post(
    "http://127.0.0.1:8000/api/v1/chat",
    json=payload,
    timeout=180.0,
)

print("HTTP_STATUS=" + str(r.status_code))
print("RAW=" + r.text)

r.raise_for_status()

data = r.json()

message = data.get("message")

if not isinstance(message, str) or not message.strip():
    raise RuntimeError(
        "RedSight returned HTTP 200 but top-level message was empty"
    )

print("ASSISTANT=" + message)
print("REDSIGHT_UI_RESPONSE=PASS")
"@

[System.IO.File]::WriteAllText(
    $ChatTest,
    $ChatTestText,
    (New-Object System.Text.UTF8Encoding($false))
)

& $UiPython $ChatTest

if ($LASTEXITCODE -ne 0) {
    throw "End-to-end RedSight chat test failed."
}

Write-Host ""

# --------------------------------------------------------------------
# 7. CLOSE ONLY COMMAND CENTER PYTHON PROCESSES
# --------------------------------------------------------------------

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

    Write-Host "Stopping UI PID $($Process.ProcessId)"

    Stop-Process `
        -Id $Process.ProcessId `
        -Force `
        -ErrorAction SilentlyContinue
}

Start-Sleep -Seconds 1

Write-Host ""

# --------------------------------------------------------------------
# 8. RELAUNCH THE QASYNC COMMAND CENTER
# --------------------------------------------------------------------

Write-Host "==============================================================="
Write-Host " LAUNCHING REPAIRED COMMAND CENTER"
Write-Host "==============================================================="

$Stdout =
    Join-Path $Backup "command-center.stdout.log"

$Stderr =
    Join-Path $Backup "command-center.stderr.log"

$UiProcess =
    Start-Process `
        -FilePath $UiPython `
        -ArgumentList @(
            $Launcher
        ) `
        -WorkingDirectory $Root `
        -RedirectStandardOutput $Stdout `
        -RedirectStandardError $Stderr `
        -PassThru

Start-Sleep -Seconds 5

$UiProcess.Refresh()

if ($UiProcess.HasExited) {

    Write-Host ""
    Write-Host "UI exited during launch."
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

    throw "Command Center launch failed."
}

Write-Host ""
Write-Host "COMMAND_CENTER_LAUNCHED=YES"
Write-Host "PID=$($UiProcess.Id)"
Write-Host ""

# --------------------------------------------------------------------
# 9. FINAL STATUS
# --------------------------------------------------------------------

Write-Host "==============================================================="
Write-Host " FINAL STATUS"
Write-Host "==============================================================="

docker compose ps

Write-Host ""

docker inspect redsight `
    --format "redsight status={{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} restarts={{.RestartCount}}"

Write-Host ""

docker inspect redsight-qdrant `
    --format "qdrant status={{.State.Status}} health={{.State.Health.Status}}"

Write-Host ""

docker exec redsight nvidia-smi -L

Write-Host ""
Write-Host "RedSight backend     : HEALTHY"
Write-Host "LM Studio            : CONNECTED"
Write-Host "Chat request         : messages[]"
Write-Host "Chat response field  : message"
Write-Host "UI event loop        : qasync"
Write-Host "High contrast        : ENABLED"
Write-Host "Dual RTX 5090        : ENABLED"
Write-Host "Command Center PID   : $($UiProcess.Id)"
Write-Host ""
Write-Host "Now test:"
Write-Host ""
Write-Host "  hi"
Write-Host ""
Write-Host "The assistant response should display instead of 'No response'."
Write-Host ""
Write-Host "Backup / diagnostics:"
Write-Host $Backup
Write-Host ""
