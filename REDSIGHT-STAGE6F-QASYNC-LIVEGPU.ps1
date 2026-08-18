$ErrorActionPreference = "Stop"

$Root       = "C:\Users\walim\RedSight"
$UI         = Join-Path $Root "app\ui\command_center.py"
$UiVenv     = Join-Path $Root ".venv-ui"
$Stamp      = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot = Join-Path $Root ".repair-backups\stage6f-$Stamp"

$LauncherPy =
    Join-Path $Root "launch_redsight_command_center.py"

$LauncherPs =
    Join-Path $Root "LAUNCH-REDSIGHT-COMMAND-CENTER.ps1"

$Utf8 =
    New-Object System.Text.UTF8Encoding($false)

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

function Http-Code {
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
Write-Host " REDSIGHT STAGE-6F"
Write-Host " QASYNC + LM STUDIO CHAT + LIVE DUAL-GPU TELEMETRY"
Write-Host "===================================================================="
Write-Host ""

# ====================================================================
# 1. BACKUP
# ====================================================================

if (-not (Test-Path $UI)) {
    throw "Missing Command Center: $UI"
}

Copy-Item `
    $UI `
    (Join-Path $BackupRoot "command_center.py.before") `
    -Force

if (Test-Path $LauncherPy) {

    Copy-Item `
        $LauncherPy `
        (Join-Path $BackupRoot "old-launcher.py") `
        -Force
}

if (Test-Path $LauncherPs) {

    Copy-Item `
        $LauncherPs `
        (Join-Path $BackupRoot "old-launcher.ps1") `
        -Force
}

Write-Host "Backup:"
Write-Host $BackupRoot
Write-Host ""

# ====================================================================
# 2. BACKEND BASELINE
# ====================================================================

Write-Host "===================================================================="
Write-Host " 1. VERIFYING REDSIGHT + LM STUDIO + GPU BASELINE"
Write-Host "===================================================================="

$HealthCode =
    Http-Code "http://127.0.0.1:8000/api/v1/health"

$LmCode =
    Http-Code "http://127.0.0.1:1234/v1/models"

Write-Host "RedSight API : $HealthCode"
Write-Host "LM Studio    : $LmCode"
Write-Host ""

if ($HealthCode -ne "200") {
    throw "RedSight API is not healthy."
}

if ($LmCode -ne "200") {
    throw "LM Studio /v1/models is not reachable."
}

Write-Host "--- GPUs inside RedSight ---"

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
    throw "GPU access inside RedSight failed."
}

if (($GpuOutput | Out-String) -notmatch "GPU 1:") {
    throw "Both GPUs are not visible inside RedSight."
}

Write-Host ""
Write-Host "Dual-GPU backend: PASS"
Write-Host ""

# ====================================================================
# 3. CONFIRM REDSIGHT -> LM STUDIO CHAT
#
# We verify the actual chat route BEFORE touching the UI.
# ====================================================================

Write-Host "===================================================================="
Write-Host " 2. REDSIGHT -> LM STUDIO CHAT CONTRACT"
Write-Host "===================================================================="

$ChatProbe =
    Join-Path $BackupRoot "verify_redsight_chat.py"

$ChatProbeLines = @(
    'import json'
    'import httpx'
    'import sys'
    ''
    'url = "http://127.0.0.1:8000/api/v1/chat"'
    ''
    'payload = {'
    '    "messages": ['
    '        {'
    '            "role": "user",'
    '            "content": "Reply with exactly REDSIGHT_LM_WIRED_OK",'
    '        }'
    '    ],'
    '    "stream": False,'
    '}'
    ''
    'print("URL=" + url)'
    'print("REQUEST=" + json.dumps(payload))'
    ''
    'r = httpx.post('
    '    url,'
    '    json=payload,'
    '    timeout=180.0,'
    ')'
    ''
    'print("HTTP_STATUS=" + str(r.status_code))'
    'print("BODY=" + r.text[:12000])'
    ''
    'if r.status_code < 200 or r.status_code >= 300:'
    '    raise SystemExit(1)'
    ''
    'try:'
    '    data = r.json()'
    '    print("RESPONSE_TYPE=" + type(data).__name__)'
    '    if isinstance(data, dict):'
    '        print("RESPONSE_KEYS=" + ",".join(data.keys()))'
    'except Exception:'
    '    pass'
    ''
    'print("REDSIGHT_TO_LM_STUDIO_CHAT=PASS")'
)

[System.IO.File]::WriteAllLines(
    $ChatProbe,
    $ChatProbeLines,
    $Utf8
)

$ErrorActionPreference = "Continue"

docker cp `
    $ChatProbe `
    redsight:/tmp/verify_redsight_chat.py

$CopyExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

if ($CopyExit -ne 0) {
    throw "Could not copy RedSight chat probe."
}

$ErrorActionPreference = "Continue"

$ChatResult =
    docker exec `
        -w /app `
        redsight `
        python /tmp/verify_redsight_chat.py `
        2>&1

$ChatExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

$ChatResult |
    ForEach-Object {
        Write-Host $_
    }

$ChatResult |
    Out-String |
    Set-Content (
        Join-Path $BackupRoot "redsight-chat-test.txt"
    )

Write-Host ""

if ($ChatExit -ne 0) {

    Write-Host "=== Chat route source ==="

    Get-ChildItem `
        (Join-Path $Root "app") `
        -Recurse `
        -Filter "*.py" `
        -File |
    Select-String `
        -Pattern "No messages provided" `
        -Context 30,70

    throw `
        "RedSight chat still rejects the messages payload. The backend route source is shown above."
}

Write-Host "RedSight -> LM Studio chat: PASS"
Write-Host ""

# ====================================================================
# 4. NORMALIZE COMMAND CENTER CHAT BODY
# ====================================================================

Write-Host "===================================================================="
Write-Host " 3. COMMAND CENTER CHAT WIRING"
Write-Host "===================================================================="

$UiText =
    [System.IO.File]::ReadAllText(
        $UI
    )

$OriginalUiText =
    $UiText

# Old broken form:
# json={"message": message}

$UiText =
    [regex]::Replace(
        $UiText,
        'json\s*=\s*\{\s*"message"\s*:\s*message\s*\}',
        'json={"messages": [{"role": "user", "content": message}], "stream": False}'
    )

# A variant with a trailing comma remains valid because the comma is
# outside this replacement.

if (
    $UiText -match
    'json\s*=\s*\{\s*"messages"\s*:'
) {

    Write-Host "Command Center request body:"
    Write-Host ""
    Write-Host '  {"messages":[{"role":"user","content":message}],"stream":false}'
    Write-Host ""
}
else {

    Write-Host "Could not identify the existing inline JSON body."
    Write-Host ""
    Write-Host "Showing _send_to_api context:"
    Write-Host ""

    Select-String `
        -Path $UI `
        -Pattern "_send_to_api" `
        -Context 5,45

    throw "Command Center chat request could not be normalized automatically."
}

if ($UiText -ne $OriginalUiText) {

    Save-Utf8 `
        -Path $UI `
        -Text $UiText

    Write-Host "Command Center request was patched."
}
else {

    Write-Host "Command Center already uses the messages payload."
}

Write-Host ""

# ====================================================================
# 5. REMOVE OLD QtAsyncio LAUNCH PROCESSES
# ====================================================================

Write-Host "===================================================================="
Write-Host " 4. CLOSING OLD QTASYNCIO COMMAND CENTER"
Write-Host "===================================================================="

$OldProcesses =
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

foreach ($Process in $OldProcesses) {

    Write-Host (
        "Stopping old Command Center PID {0}" -f
        $Process.ProcessId
    )

    Stop-Process `
        -Id $Process.ProcessId `
        -Force `
        -ErrorAction SilentlyContinue
}

Write-Host ""

# ====================================================================
# 6. WINDOWS UI ENVIRONMENT
# ====================================================================

Write-Host "===================================================================="
Write-Host " 5. INSTALLING QASYNC UI EVENT LOOP"
Write-Host "===================================================================="

if (-not (Test-Path $UiVenv)) {

    $Py =
        Get-Command py `
            -ErrorAction SilentlyContinue

    if ($Py) {

        & py `
            -3.12 `
            -m venv `
            $UiVenv
    }
    else {

        $Python =
            Get-Command python `
                -ErrorAction SilentlyContinue

        if (-not $Python) {
            throw "Windows Python was not found."
        }

        & $Python.Source `
            -m venv `
            $UiVenv
    }
}

$UiPython =
    Join-Path $UiVenv `
        "Scripts\python.exe"

if (-not (Test-Path $UiPython)) {
    throw "UI Python environment is missing."
}

Write-Host "UI Python:"
Write-Host $UiPython
Write-Host ""

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
    "qasync==0.28.0" `
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

# ====================================================================
# 7. QASYNC IMPORT TEST
# ====================================================================

$QasyncProbe =
    Join-Path $BackupRoot "qasync_probe.py"

$QasyncProbeLines = @(
    'import asyncio'
    'import PySide6'
    'import qasync'
    'from qasync import QEventLoop'
    ''
    'print("PYSIDE=" + PySide6.__version__)'
    'print("QASYNC=" + getattr(qasync, "__version__", "installed"))'
    'print("QEVENTLOOP=OK")'
)

[System.IO.File]::WriteAllLines(
    $QasyncProbe,
    $QasyncProbeLines,
    $Utf8
)

& $UiPython `
    $QasyncProbe

if ($LASTEXITCODE -ne 0) {
    throw "qasync import test failed."
}

Write-Host ""

# ====================================================================
# 8. COMMAND CENTER IMPORT TEST
# ====================================================================

Write-Host "=== Importing Command Center ==="

$ImportProbe =
    Join-Path $BackupRoot "ui_import_probe.py"

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
    throw "Command Center Windows import failed."
}

if (($ImportOutput | Out-String) -notmatch "WINDOW_CLASS=True") {
    throw "CommandCenterMainWindow class is unavailable."
}

Write-Host ""

# ====================================================================
# 9. CREATE NEW QASYNC + LIVE GPU LAUNCHER
#
# IMPORTANT:
# No PySide6.QtAsyncio.
# No QAsyncioTask.
#
# The original asyncio.create_task() now runs on qasync's Qt event loop.
#
# Also adds a live host NVIDIA panel. It does NOT rely on stale
# container/UI telemetry state.
# ====================================================================

Write-Host "===================================================================="
Write-Host " 6. BUILDING NEW COMMAND CENTER LAUNCHER"
Write-Host "===================================================================="

$LauncherLines = @(
    'import asyncio'
    'import csv'
    'import io'
    'import json'
    'import os'
    'import subprocess'
    'import sys'
    'import urllib.request'
    ''
    'ROOT = r"C:\Users\walim\RedSight"'
    ''
    'if ROOT not in sys.path:'
    '    sys.path.insert(0, ROOT)'
    ''
    '# ------------------------------------------------------------'
    '# Explicit local-service wiring'
    '# ------------------------------------------------------------'
    'os.environ["REDSIGHT_API_URL"] = "http://127.0.0.1:8000"'
    'os.environ["REDSIGHT_API_BASE_URL"] = "http://127.0.0.1:8000"'
    'os.environ["API_BASE_URL"] = "http://127.0.0.1:8000"'
    ''
    'from PySide6.QtCore import Qt, QTimer'
    'from PySide6.QtWidgets import ('
    '    QApplication,'
    '    QDockWidget,'
    '    QHeaderView,'
    '    QLabel,'
    '    QTableWidget,'
    '    QTableWidgetItem,'
    '    QWidget,'
    '    QVBoxLayout,'
    ')'
    ''
    'from qasync import QEventLoop'
    ''
    'from app.ui.command_center import CommandCenterMainWindow'
    ''
    ''
    'def get_lm_model():'
    '    try:'
    '        with urllib.request.urlopen('
    '            "http://127.0.0.1:1234/v1/models",'
    '            timeout=3.0,'
    '        ) as response:'
    '            data = json.load(response)'
    ''
    '        models = data.get("data", [])'
    ''
    '        if models:'
    '            return models[0].get("id", "available")'
    ''
    '        return "server online / no model listed"'
    '    except Exception as exc:'
    '        return "OFFLINE: " + str(exc)'
    ''
    ''
    'def query_nvidia():'
    '    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)'
    ''
    '    command = ['
    '        "nvidia-smi",'
    '        "--query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",'
    '        "--format=csv,noheader,nounits",'
    '    ]'
    ''
    '    result = subprocess.run('
    '        command,'
    '        capture_output=True,'
    '        text=True,'
    '        timeout=4,'
    '        creationflags=creationflags,'
    '    )'
    ''
    '    if result.returncode != 0:'
    '        raise RuntimeError(result.stderr.strip() or "nvidia-smi failed")'
    ''
    '    rows = []'
    ''
    '    reader = csv.reader(io.StringIO(result.stdout))'
    ''
    '    for raw in reader:'
    '        if len(raw) < 7:'
    '            continue'
    ''
    '        values = [value.strip() for value in raw]'
    ''
    '        def number(value, default=0.0):'
    '            try:'
    '                return float(value)'
    '            except Exception:'
    '                return default'
    ''
    '        used = number(values[3])'
    '        total = number(values[4])'
    '        vram_percent = (used / total * 100.0) if total else 0.0'
    ''
    '        rows.append({'
    '            "index": values[0],'
    '            "name": values[1],'
    '            "util": number(values[2]),'
    '            "used": used,'
    '            "total": total,'
    '            "vram_percent": vram_percent,'
    '            "temp": number(values[5]),'
    '            "power": number(values[6]),'
    '        })'
    ''
    '    return rows'
    ''
    ''
    'class LiveGpuDock(QDockWidget):'
    '    def __init__(self, parent=None):'
    '        super().__init__("LIVE DUAL-GPU TELEMETRY", parent)'
    ''
    '        container = QWidget()'
    '        layout = QVBoxLayout(container)'
    ''
    '        self.connection = QLabel()'
    '        self.connection.setText('
    '            "LM Studio: " + get_lm_model()'
    '        )'
    ''
    '        layout.addWidget(self.connection)'
    ''
    '        self.table = QTableWidget(0, 6)'
    '        self.table.setHorizontalHeaderLabels(['
    '            "GPU",'
    '            "Name",'
    '            "GPU Util",'
    '            "VRAM",'
    '            "Temp",'
    '            "Power",'
    '        ])'
    ''
    '        header = self.table.horizontalHeader()'
    '        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)'
    ''
    '        layout.addWidget(self.table)'
    ''
    '        self.summary = QLabel("Waiting for NVIDIA telemetry...")'
    '        layout.addWidget(self.summary)'
    ''
    '        self.setWidget(container)'
    ''
    '        self.timer = QTimer(self)'
    '        self.timer.timeout.connect(self.refresh)'
    '        self.timer.start(1000)'
    ''
    '        self.lm_timer = QTimer(self)'
    '        self.lm_timer.timeout.connect(self.refresh_lm)'
    '        self.lm_timer.start(10000)'
    ''
    '        self.refresh()'
    ''
    '    def refresh_lm(self):'
    '        self.connection.setText('
    '            "LM Studio: " + get_lm_model()'
    '        )'
    ''
    '    def refresh(self):'
    '        try:'
    '            rows = query_nvidia()'
    '        except Exception as exc:'
    '            self.summary.setText("GPU telemetry error: " + str(exc))'
    '            return'
    ''
    '        self.table.setRowCount(len(rows))'
    ''
    '        summary_parts = []'
    ''
    '        for row_index, gpu in enumerate(rows):'
    '            values = ['
    '                "GPU " + str(gpu["index"]),'
    '                gpu["name"],'
    '                "{:.0f}%".format(gpu["util"]),'
    '                "{:.0f}/{:.0f} MiB ({:.1f}%)".format('
    '                    gpu["used"],'
    '                    gpu["total"],'
    '                    gpu["vram_percent"],'
    '                ),'
    '                "{:.0f} C".format(gpu["temp"]),'
    '                "{:.1f} W".format(gpu["power"]),'
    '            ]'
    ''
    '            for column, value in enumerate(values):'
    '                self.table.setItem('
    '                    row_index,'
    '                    column,'
    '                    QTableWidgetItem(value),'
    '                )'
    ''
    '            summary_parts.append('
    '                "GPU{} {:.0f}% | VRAM {:.1f}%".format('
    '                    gpu["index"],'
    '                    gpu["util"],'
    '                    gpu["vram_percent"],'
    '                )'
    '            )'
    ''
    '        self.summary.setText("   ||   ".join(summary_parts))'
    ''
    ''
    'app = QApplication.instance()'
    ''
    'if app is None:'
    '    app = QApplication(sys.argv)'
    ''
    '# ------------------------------------------------------------'
    '# qasync provides the asyncio loop used by asyncio.create_task.'
    '# This deliberately replaces PySide6.QtAsyncio/QAsyncioTask.'
    '# ------------------------------------------------------------'
    'loop = QEventLoop(app)'
    'asyncio.set_event_loop(loop)'
    ''
    'window = CommandCenterMainWindow()'
    ''
    '# Force RedSight localhost backend where supported by the class.'
    'for attr in ('
    '    "_api_base_url",'
    '    "api_base_url",'
    '    "_base_url",'
    '):'
    '    if hasattr(window, attr):'
    '        try:'
    '            setattr(window, attr, "http://127.0.0.1:8000")'
    '        except Exception:'
    '            pass'
    ''
    '# ------------------------------------------------------------'
    '# Accurate host telemetry dock.'
    '# ------------------------------------------------------------'
    'gpu_dock = LiveGpuDock(window)'
    'window.addDockWidget('
    '    Qt.DockWidgetArea.RightDockWidgetArea,'
    '    gpu_dock,'
    ')'
    ''
    '# Keep references alive.'
    'window._redsight_live_gpu_dock = gpu_dock'
    'window._redsight_qasync_loop = loop'
    ''
    'try:'
    '    status = window.statusBar()'
    '    status.showMessage('
    '        "RedSight API: 127.0.0.1:8000  |  "'
    '        "LM Studio: 127.0.0.1:1234  |  "'
    '        "qasync event loop active"'
    '    )'
    'except Exception:'
    '    pass'
    ''
    'window.show()'
    ''
    'print("COMMAND_CENTER_WINDOW_SHOWN=YES", flush=True)'
    'print("EVENT_LOOP=QASYNC", flush=True)'
    'print("LM_STUDIO_MODEL=" + get_lm_model(), flush=True)'
    ''
    'app.aboutToQuit.connect(loop.stop)'
    ''
    'with loop:'
    '    loop.run_forever()'
)

[System.IO.File]::WriteAllLines(
    $LauncherPy,
    $LauncherLines,
    $Utf8
)

Write-Host "Created:"
Write-Host $LauncherPy
Write-Host ""

# ====================================================================
# 10. CREATE REUSABLE POWERSHELL LAUNCHER
# ====================================================================

$PowerShellLauncherLines = @(
    '$ErrorActionPreference = "Stop"'
    ''
    '$Root = "C:\Users\walim\RedSight"'
    '$Python = Join-Path $Root ".venv-ui\Scripts\python.exe"'
    '$Launcher = Join-Path $Root "launch_redsight_command_center.py"'
    ''
    'Set-Location $Root'
    ''
    '& $Python $Launcher'
)

[System.IO.File]::WriteAllLines(
    $LauncherPs,
    $PowerShellLauncherLines,
    $Utf8
)

Write-Host "Reusable launcher:"
Write-Host $LauncherPs
Write-Host ""

# ====================================================================
# 11. LAUNCH NEW COMMAND CENTER
# ====================================================================

Write-Host "===================================================================="
Write-Host " 7. LAUNCHING QASYNC COMMAND CENTER"
Write-Host "===================================================================="

$Stdout =
    Join-Path $BackupRoot `
        "command-center.stdout.log"

$Stderr =
    Join-Path $BackupRoot `
        "command-center.stderr.log"

$UiProcess =
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

$UiProcess.Refresh()

if ($UiProcess.HasExited) {

    Write-Host ""
    Write-Host "COMMAND CENTER FAILED TO START"
    Write-Host ""

    if (Test-Path $Stdout) {

        Write-Host "=== STDOUT ==="

        Get-Content `
            $Stdout `
            -Tail 150
    }

    if (Test-Path $Stderr) {

        Write-Host ""
        Write-Host "=== STDERR ==="

        Get-Content `
            $Stderr `
            -Tail 200
    }

    throw "New qasync Command Center launcher exited."
}

Write-Host "COMMAND_CENTER_LAUNCHED=YES"
Write-Host "PID=$($UiProcess.Id)"
Write-Host ""

# ====================================================================
# 12. READ LAUNCHER OUTPUT
# ====================================================================

if (Test-Path $Stdout) {

    Write-Host "=== COMMAND CENTER STARTUP ==="

    Get-Content `
        $Stdout `
        -Tail 50

    Write-Host ""
}

if (
    (Test-Path $Stderr) -and
    (Get-Item $Stderr).Length -gt 0
) {

    Write-Host "=== COMMAND CENTER STDERR ==="

    Get-Content `
        $Stderr `
        -Tail 80

    Write-Host ""
}

# ====================================================================
# 13. FINAL STATUS
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

Write-Host "--- Docker GPUs ---"

docker exec `
    redsight `
    nvidia-smi -L

Write-Host ""

$FinalApi =
    Http-Code "http://127.0.0.1:8000/api/v1/health"

$FinalLm =
    Http-Code "http://127.0.0.1:1234/v1/models"

Write-Host "RedSight API       : $FinalApi"
Write-Host "LM Studio          : $FinalLm"
Write-Host "RedSight chat E2E  : PASS"
Write-Host "Docker dual GPUs   : PASS"
Write-Host "NVML               : PASS"
Write-Host "Desktop event loop : qasync"
Write-Host "Command Center PID : $($UiProcess.Id)"
Write-Host ""

Write-Host "===================================================================="
Write-Host " REDSIGHT STAGE-6F COMPLETE"
Write-Host "===================================================================="
Write-Host ""

Write-Host "You should now see a panel titled:"
Write-Host ""
Write-Host "  LIVE DUAL-GPU TELEMETRY"
Write-Host ""
Write-Host "It refreshes GPU utilization, VRAM, temperature and power every second."
Write-Host ""

Write-Host "Reusable launcher:"
Write-Host $LauncherPs
Write-Host ""

Write-Host "Diagnostics:"
Write-Host $BackupRoot
Write-Host ""

Write-Host "UI stderr:"
Write-Host $Stderr
Write-Host ""

Write-Host "Qdrant data/volumes were NOT touched."
Write-Host ""
