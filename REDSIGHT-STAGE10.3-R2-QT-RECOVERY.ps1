Set-Location "C:\Users\walim\RedSight"
$ErrorActionPreference = "Stop"

# =====================================================================
# REDSIGHT STAGE 10.3 R2
# QT VALIDATION REPAIR + INLINE CHAT/ATTACHMENT VERIFICATION + SAFE RESTART
#
# This is a RECOVERY script.
# It does NOT rerun the failed Stage 10.3 installer from the beginning.
#
# It assumes the source-install portion already completed, which the prior
# log proved with STAGE103_SOURCE_INSTALL=PASS.
#
# Safety:
#   - no Qdrant delete/recreate
#   - no docker volume deletion
#   - no conversation DB deletion
#   - no source/user file deletion
#   - only RedSight-specific Python UI/gateway processes are terminated
# =====================================================================

$Root         = "C:\Users\walim\RedSight"
$UiPython     = Join-Path $Root ".venv-ui\Scripts\python.exe"
$ActionPython = Join-Path $Root ".venv-actions\Scripts\python.exe"
$Launcher     = Join-Path $Root "launch_redsight_command_center.py"
$Overlay      = Join-Path $Root "app\ui\action_palette_stage103.py"
$Stage102     = Join-Path $Root "app\ui\action_palette_stage102.py"
$Gateway10    = Join-Path $Root "redsight_actions\gateway_stage10.py"

$Stamp        = Get-Date -Format "yyyyMMdd-HHmmss"
$Diag         = Join-Path $Root ".repair-backups\stage103-r2-$Stamp"

New-Item -ItemType Directory -Path $Diag -Force | Out-Null

$GatewayOut = Join-Path $Diag "gateway.stdout.log"
$GatewayErr = Join-Path $Diag "gateway.stderr.log"
$UiOut      = Join-Path $Diag "command-center.stdout.log"
$UiErr      = Join-Path $Diag "command-center.stderr.log"

Write-Host ""
Write-Host "======================================================================"
Write-Host " REDSIGHT STAGE 10.3 R2"
Write-Host " QT VALIDATION REPAIR + SAFE FULL RELAUNCH"
Write-Host "======================================================================"
Write-Host ""

# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

function Invoke-NativeChecked {
    param(
        [Parameter(Mandatory=$true)][string]$Exe,
        [Parameter(Mandatory=$false)][string[]]$Arguments = @(),
        [Parameter(Mandatory=$true)][string]$Label
    )

    Write-Host ">> $Exe $($Arguments -join ' ')"

    $OldPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"

    & $Exe @Arguments
    $Code = $LASTEXITCODE

    $ErrorActionPreference = $OldPreference

    if ($Code -ne 0) {
        throw "$Label failed with exit code $Code."
    }
}

function Test-Http200 {
    param(
        [Parameter(Mandatory=$true)][string]$Url,
        [int]$TimeoutSeconds = 4
    )

    $OldPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"

    $Code = curl.exe `
        -s `
        -o NUL `
        -w "%{http_code}" `
        --max-time $TimeoutSeconds `
        $Url `
        2>$null

    $Exit = $LASTEXITCODE
    $ErrorActionPreference = $OldPreference

    return (($Exit -eq 0) -and ($Code -eq "200"))
}

function Wait-Http200 {
    param(
        [Parameter(Mandatory=$true)][string]$Url,
        [int]$Attempts = 60,
        [int]$DelayMilliseconds = 1000
    )

    for ($i = 1; $i -le $Attempts; $i++) {
        if (Test-Http200 -Url $Url -TimeoutSeconds 4) {
            return $true
        }

        Write-Host "Waiting for $Url ... $i/$Attempts"
        Start-Sleep -Milliseconds $DelayMilliseconds
    }

    return $false
}

# ---------------------------------------------------------------------
# 1. Required components
# ---------------------------------------------------------------------

Write-Host "=== Required components ==="

foreach ($Required in @(
    $UiPython,
    $ActionPython,
    $Launcher,
    $Overlay,
    $Stage102,
    $Gateway10
)) {
    if (-not (Test-Path -LiteralPath $Required)) {
        throw "Required Stage 10.3 component is missing: $Required"
    }

    Write-Host "PASS  $Required"
}

# ---------------------------------------------------------------------
# 2. Back up the already-installed Stage 10.3 source + launcher
# ---------------------------------------------------------------------

Copy-Item -LiteralPath $Overlay  -Destination (Join-Path $Diag "action_palette_stage103.py.before") -Force
Copy-Item -LiteralPath $Launcher -Destination (Join-Path $Diag "launch_redsight_command_center.py.before") -Force

Write-Host ""
Write-Host "BACKUP=$Diag"

# ---------------------------------------------------------------------
# 3. Dependency validation / repair
# ---------------------------------------------------------------------

Write-Host ""
Write-Host "=== Stage 10.3 dependency validation ==="

$OldPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"

& $UiPython -c "import pymupdf,docx,openpyxl,pptx,PySide6,qasync,httpx; print('STAGE103_DEPS=PASS')"
$DepCode = $LASTEXITCODE

$ErrorActionPreference = $OldPreference

if ($DepCode -ne 0) {
    Write-Host "Repairing only the Stage 10.3 attachment/UI dependencies..."

    Invoke-NativeChecked `
        -Exe $UiPython `
        -Arguments @(
            "-m","pip","install",
            "PyMuPDF>=1.24,<2",
            "python-docx>=1.1,<2",
            "openpyxl>=3.1,<4",
            "python-pptx>=1.0,<2",
            "PySide6>=6.7,<7",
            "qasync>=0.27,<1",
            "httpx>=0.27,<1"
        ) `
        -Label "Stage 10.3 dependency repair"

    Invoke-NativeChecked `
        -Exe $UiPython `
        -Arguments @(
            "-c",
            "import pymupdf,docx,openpyxl,pptx,PySide6,qasync,httpx; print('STAGE103_DEPS=PASS')"
        ) `
        -Label "Stage 10.3 dependency revalidation"
}

# ---------------------------------------------------------------------
# 4. Source-aware micro repair
#
# PyMuPDF now warns that `fitz` is deprecated. Replace only the two exact
# Stage 10.3 PDF-parser references. Also validate launcher integration.
# ---------------------------------------------------------------------

Write-Host ""
Write-Host "=== Stage 10.3 source integrity repair ==="

$PatchPy = Join-Path $Diag "repair-stage103-source.py"

$PatchCode = @'
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(r"C:\Users\walim\RedSight")
OVERLAY = ROOT / "app" / "ui" / "action_palette_stage103.py"
LAUNCHER = ROOT / "launch_redsight_command_center.py"

source = OVERLAY.read_text(encoding="utf-8-sig", errors="replace")

# Modern PyMuPDF module name; prevents the deprecation warning seen in the log.
source = source.replace("    import fitz\n", "    import pymupdf\n")
source = source.replace("    with fitz.open(path) as document:\n", "    with pymupdf.open(path) as document:\n")

required_markers = (
    "def _install_inline_bubble_view",
    "def _install_attachment_controls",
    "def _build_attachment_context",
    "def _send_dispatch",
    "def install_action_hooks",
    "def attach_action_palette",
)

missing = [marker for marker in required_markers if marker not in source]
if missing:
    raise RuntimeError("Stage 10.3 overlay is incomplete; missing: " + ", ".join(missing))

ast.parse(source, filename=str(OVERLAY))

tmp = OVERLAY.with_suffix(".py.r2.tmp")
tmp.write_text(source, encoding="utf-8")
tmp.replace(OVERLAY)

launcher = LAUNCHER.read_text(encoding="utf-8-sig", errors="replace")

# Stage 10.3 source installation already succeeded. Do not rewrite the launcher
# unless its expected integration is absent or duplicated.
stage103_import = (
    "from app.ui.action_palette_stage103 "
    "import install_action_hooks, attach_action_palette"
)

if launcher.count(stage103_import) != 1:
    # Normalize only action-palette integration lines.
    launcher = re.sub(
        r"(?m)^from app\.ui\.action_palette(?:_stage9|_stage91|_stage10|_stage101|_stage102|_stage103)? "
        r"import install_action_hooks, attach_action_palette\s*$\n?",
        "",
        launcher,
    )
    launcher = re.sub(
        r"(?m)^\s*install_action_hooks\(CommandCenterMainWindow\)\s*$\n?",
        "",
        launcher,
    )
    launcher = re.sub(
        r"(?m)^\s*attach_action_palette\(.*?\)\s*$\n?",
        "",
        launcher,
    )

    if not re.search(r"(?m)^from pathlib import Path\s*$", launcher):
        future = re.search(r"(?m)^from __future__ import .+$", launcher)
        if future:
            launcher = (
                launcher[:future.end()]
                + "\nfrom pathlib import Path"
                + launcher[future.end():]
            )
        else:
            launcher = "from pathlib import Path\n" + launcher

    command_import = re.search(
        r"(?m)^from app\.ui\.command_center import CommandCenterMainWindow\s*$",
        launcher,
    )
    if not command_import:
        raise RuntimeError("CommandCenterMainWindow import not found in launcher.")

    integration = (
        "\nfrom app.ui.action_palette_stage103 "
        "import install_action_hooks, attach_action_palette\n"
        "install_action_hooks(CommandCenterMainWindow)"
    )

    launcher = (
        launcher[:command_import.end()]
        + integration
        + launcher[command_import.end():]
    )

    window_match = re.search(
        r"(?m)^([ \t]*)window\s*=\s*CommandCenterMainWindow\(\)\s*$",
        launcher,
    )
    if not window_match:
        raise RuntimeError("CommandCenterMainWindow() construction not found.")

    indent = window_match.group(1)

    launcher = (
        launcher[:window_match.end()]
        + "\n"
        + indent
        + "attach_action_palette(window, Path(__file__).resolve().parent)"
        + launcher[window_match.end():]
    )

ast.parse(launcher, filename=str(LAUNCHER))

# Final hard checks: exactly one Stage 10.3 integration.
if launcher.count(stage103_import) != 1:
    raise RuntimeError("Stage 10.3 launcher import count is not exactly one.")

if launcher.count("install_action_hooks(CommandCenterMainWindow)") != 1:
    raise RuntimeError("Stage 10.3 install_action_hooks call count is not exactly one.")

if launcher.count("attach_action_palette(window, Path(__file__).resolve().parent)") != 1:
    raise RuntimeError("Stage 10.3 attach_action_palette call count is not exactly one.")

LAUNCHER.write_text(launcher, encoding="utf-8")

print("STAGE103_SOURCE_INTEGRITY=PASS")
print("LAUNCHER_STAGE103_SINGLE_INTEGRATION=PASS")
print("PYMUPDF_MODERN_IMPORT=PASS")
'@

[System.IO.File]::WriteAllText(
    $PatchPy,
    $PatchCode,
    (New-Object System.Text.UTF8Encoding($false))
)

Invoke-NativeChecked `
    -Exe $UiPython `
    -Arguments @($PatchPy) `
    -Label "Stage 10.3 source integrity repair"

# ---------------------------------------------------------------------
# 5. Python compilation
# ---------------------------------------------------------------------

Write-Host ""
Write-Host "=== Python compilation ==="

Invoke-NativeChecked `
    -Exe $UiPython `
    -Arguments @("-m","py_compile",$Overlay) `
    -Label "Stage 10.3 overlay compilation"

Invoke-NativeChecked `
    -Exe $UiPython `
    -Arguments @("-m","py_compile",$Launcher) `
    -Label "Command Center launcher compilation"

# ---------------------------------------------------------------------
# 6. Corrected static validator
#
# THIS IS THE EXACT FAILURE FROM THE PREVIOUS RUN:
# a QWidget/MessageBubble was instantiated before QApplication existed.
# ---------------------------------------------------------------------

Write-Host ""
Write-Host "=== Corrected Qt-aware static/file-context validation ==="

$StaticPy = Join-Path $Diag "validate-stage103-r2-static.py"

$StaticCode = @'
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from pathlib import Path
import tempfile
import sys

ROOT = Path(r"C:\Users\walim\RedSight")
sys.path.insert(0, str(ROOT))

# QApplication MUST exist before constructing any QWidget.
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])

from app.ui import action_palette_stage103 as u
from app.ui.command_center import CommandCenterMainWindow

bubble = u.s102.MessageBubble("user", "x")
assert bubble is not None
bubble.deleteLater()

assert CommandCenterMainWindow is not None

with tempfile.TemporaryDirectory() as folder:
    sample = Path(folder) / "redsight-attachment-test.txt"
    sample.write_text(
        "REDSIGHT_ATTACHMENT_CONTEXT_OK\n"
        "This file proves Stage 10.3 local file extraction works.",
        encoding="utf-8",
    )

    context, metadata = u._build_attachment_context([str(sample)])

    assert "REDSIGHT_ATTACHMENT_CONTEXT_OK" in context
    assert metadata
    assert metadata[0]["name"] == sample.name

u.install_action_hooks(CommandCenterMainWindow)

assert (
    CommandCenterMainWindow._send_to_api.__module__
    == "app.ui.action_palette_stage103"
)

print("QAPPLICATION_BEFORE_QWIDGET=PASS")
print("STAGE103_IMPORT=PASS")
print("FILE_CONTEXT_EXTRACTION=PASS")
print("SINGLE_CHAT_DISPATCHER=PASS")
'@

[System.IO.File]::WriteAllText(
    $StaticPy,
    $StaticCode,
    (New-Object System.Text.UTF8Encoding($false))
)

Invoke-NativeChecked `
    -Exe $UiPython `
    -Arguments @($StaticPy) `
    -Label "Corrected Stage 10.3 Qt/static validation"

# ---------------------------------------------------------------------
# 7. Docker
# ---------------------------------------------------------------------

Write-Host ""
Write-Host "=== Docker Desktop ==="

$OldPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"

docker info 1>$null 2>$null
$DockerOK = ($LASTEXITCODE -eq 0)

$ErrorActionPreference = $OldPreference

if (-not $DockerOK) {
    $DockerDesktop = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"

    if (Test-Path $DockerDesktop) {
        Write-Host "Starting Docker Desktop..."
        Start-Process -FilePath $DockerDesktop | Out-Null
    }
    else {
        $OldPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        docker desktop start --detach 1>$null 2>$null
        $ErrorActionPreference = $OldPreference
    }

    for ($i = 1; $i -le 90; $i++) {
        $OldPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        docker info 1>$null 2>$null
        $DockerOK = ($LASTEXITCODE -eq 0)
        $ErrorActionPreference = $OldPreference

        if ($DockerOK) {
            break
        }

        Write-Host "Waiting for Docker... $i/90"
        Start-Sleep -Seconds 2
    }
}

if (-not $DockerOK) {
    throw "Docker Desktop Linux engine did not become available."
}

Write-Host "DOCKER=ONLINE"

# ---------------------------------------------------------------------
# 8. Start Qdrant safely and restart ONLY RedSight backend
# ---------------------------------------------------------------------

Write-Host ""
Write-Host "=== RedSight backend / Qdrant ==="

Invoke-NativeChecked `
    -Exe "docker" `
    -Arguments @("compose","up","-d","qdrant") `
    -Label "Qdrant start/verify"

$OldPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"

docker compose restart redsight
$RestartCode = $LASTEXITCODE

$ErrorActionPreference = $OldPreference

if ($RestartCode -ne 0) {
    Invoke-NativeChecked `
        -Exe "docker" `
        -Arguments @("compose","up","-d","redsight") `
        -Label "RedSight backend start"
}

if (-not (Wait-Http200 `
    -Url "http://127.0.0.1:8000/api/v1/health" `
    -Attempts 75 `
    -DelayMilliseconds 1500
)) {
    Write-Host ""
    Write-Host "=== REDSIGHT BACKEND LOG ==="

    $OldPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    docker logs --tail 250 redsight
    $ErrorActionPreference = $OldPreference

    throw "RedSight backend failed health validation."
}

Write-Host "REDSIGHT_BACKEND=HEALTHY"

$OldPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"

docker exec redsight-qdrant curl -fsS http://localhost:6333/readyz
$QdrantExit = $LASTEXITCODE

$ErrorActionPreference = $OldPreference

if ($QdrantExit -ne 0) {
    throw "Qdrant failed readiness validation."
}

Write-Host ""
Write-Host "QDRANT=HEALTHY"

# ---------------------------------------------------------------------
# 9. Restart Stage 10 Action/Memory Gateway
# ---------------------------------------------------------------------

Write-Host ""
Write-Host "=== Stage 10 Action / Memory Gateway ==="

Get-CimInstance Win32_Process |
    Where-Object {
        $_.Name -match '^python(w)?\.exe$' -and
        $_.CommandLine -and
        (
            $_.CommandLine -match 'redsight_actions\.gateway:app' -or
            $_.CommandLine -match 'redsight_actions\.gateway_stage9:app' -or
            $_.CommandLine -match 'redsight_actions\.gateway_stage91:app' -or
            $_.CommandLine -match 'redsight_actions\.gateway_stage10:app'
        )
    } |
    ForEach-Object {
        Write-Host "Stopping stale gateway PID $($_.ProcessId)"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }

Start-Sleep -Milliseconds 800

$GatewayProcess = Start-Process `
    -FilePath $ActionPython `
    -ArgumentList @(
        "-m",
        "uvicorn",
        "redsight_actions.gateway_stage10:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8765",
        "--log-level",
        "warning"
    ) `
    -WorkingDirectory $Root `
    -RedirectStandardOutput $GatewayOut `
    -RedirectStandardError $GatewayErr `
    -PassThru

if (-not (Wait-Http200 `
    -Url "http://127.0.0.1:8765/memory/status" `
    -Attempts 60 `
    -DelayMilliseconds 500
)) {
    Write-Host ""
    Write-Host "=== GATEWAY STDOUT ==="

    if (Test-Path $GatewayOut) {
        Get-Content $GatewayOut -Tail 160
    }

    Write-Host ""
    Write-Host "=== GATEWAY STDERR ==="

    if (Test-Path $GatewayErr) {
        Get-Content $GatewayErr -Tail 250
    }

    throw "Stage 10 Action/Memory Gateway failed to restart."
}

Write-Host "ACTION_MEMORY_GATEWAY=HEALTHY"

# ---------------------------------------------------------------------
# 10. GPU + LM Studio
# ---------------------------------------------------------------------

Write-Host ""
Write-Host "=== GPU / LM Studio ==="

$OldPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"

$Gpu = docker exec redsight nvidia-smi -L
$GpuCode = $LASTEXITCODE

$ErrorActionPreference = $OldPreference

if (
    $GpuCode -ne 0 -or
    ($Gpu | Out-String) -notmatch "GPU 0:" -or
    ($Gpu | Out-String) -notmatch "GPU 1:"
) {
    throw "Dual-GPU validation failed."
}

$Gpu
Write-Host "DUAL_GPU=PASS"

$LmReady = Test-Http200 `
    -Url "http://127.0.0.1:1234/v1/models" `
    -TimeoutSeconds 5

if ($LmReady) {
    Write-Host "LM_STUDIO=CONNECTED"
}
else {
    Write-Warning "LM Studio Local Server is not reachable on port 1234. RedSight will launch, but inference will not work until LM Studio Local Server is running."
}

# ---------------------------------------------------------------------
# 11. Deep offscreen Command Center integration test
# ---------------------------------------------------------------------

Write-Host ""
Write-Host "=== Deep Stage 10.3 inline-chat UI test ==="

$OffscreenPy = Join-Path $Diag "validate-stage103-r2-offscreen.py"

$OffscreenCode = @'
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from pathlib import Path
import sys

ROOT = Path(r"C:\Users\walim\RedSight")
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication, QDockWidget

app = QApplication.instance() or QApplication([])

from app.ui.command_center import CommandCenterMainWindow
from app.ui import action_palette_stage103 as u

u.install_action_hooks(CommandCenterMainWindow)

window = CommandCenterMainWindow()
u.attach_action_palette(window, ROOT)

assert hasattr(window, "_redsight_bubble_view")
assert hasattr(window, "_redsight_attach_button")
assert hasattr(window, "_redsight_attachment_tray")
assert hasattr(window, "_redsight_chat_input")

assert hasattr(window, "_redsight_inline_chat_stack"), (
    "Main vertical chat layout above the query input was not located."
)

assert not hasattr(window, "_redsight_bubble_chat_dock")
assert window.findChild(QDockWidget, "RedSightBubbleChatDock") is None

bubble = window._redsight_bubble_view
assert not isinstance(bubble.parentWidget(), QDockWidget)

button = window._redsight_attach_button
assert "Attach" in button.text()

# Verify tray is real and the query input remains attached to a UI parent.
assert window._redsight_attachment_tray.parentWidget() is not None
assert window._redsight_chat_input.parentWidget() is not None

window.close()

print("INLINE_CHAT_ABOVE_QUERY=PASS")
print("RIGHT_CHAT_DOCK_REMOVED=PASS")
print("ATTACH_BUTTON_IN_CHATBAR=PASS")
print("ATTACHMENT_TRAY=PASS")
print("OFFSCREEN_COMMAND_CENTER=PASS")
'@

[System.IO.File]::WriteAllText(
    $OffscreenPy,
    $OffscreenCode,
    (New-Object System.Text.UTF8Encoding($false))
)

Invoke-NativeChecked `
    -Exe $UiPython `
    -Arguments @($OffscreenPy) `
    -Label "Stage 10.3 offscreen Command Center validation"

# ---------------------------------------------------------------------
# 12. Real backend chat regression when LM Studio is available
# ---------------------------------------------------------------------

if ($LmReady) {
    Write-Host ""
    Write-Host "=== RedSight -> LM Studio chat regression ==="

    $ChatBody = @{
        messages = @(
            @{
                role = "user"
                content = "Reply with exactly REDSIGHT_STAGE103_R2_READY"
            }
        )
        stream = $false
    } | ConvertTo-Json -Depth 8

    $Chat = Invoke-RestMethod `
        -Uri "http://127.0.0.1:8000/api/v1/chat" `
        -Method Post `
        -ContentType "application/json" `
        -Body $ChatBody `
        -TimeoutSec 240

    if (-not $Chat.message) {
        $Chat | ConvertTo-Json -Depth 10 | Write-Host
        throw "RedSight chat endpoint returned no top-level message."
    }

    Write-Host "CHAT_MESSAGE=$($Chat.message)"
    Write-Host "CHAT_TRANSPORT=PASS"
}

# ---------------------------------------------------------------------
# 13. Terminate stale RedSight UI processes only
# ---------------------------------------------------------------------

Write-Host ""
Write-Host "=== Terminating stale RedSight Command Center processes ==="

Get-CimInstance Win32_Process |
    Where-Object {
        $_.Name -match '^python(w)?\.exe$' -and
        $_.CommandLine -and
        (
            $_.CommandLine -match 'launch_redsight_command_center\.py' -or
            $_.CommandLine -match 'app\.ui\.command_center'
        )
    } |
    ForEach-Object {
        Write-Host "Stopping stale UI PID $($_.ProcessId)"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }

Start-Sleep -Seconds 1

# ---------------------------------------------------------------------
# 14. Relaunch live Command Center
# ---------------------------------------------------------------------

Write-Host ""
Write-Host "======================================================================"
Write-Host " RELAUNCHING REDSIGHT COMMAND CENTER"
Write-Host "======================================================================"
Write-Host ""

$UiProcess = Start-Process `
    -FilePath $UiPython `
    -ArgumentList ('"' + $Launcher + '"') `
    -WorkingDirectory $Root `
    -RedirectStandardOutput $UiOut `
    -RedirectStandardError $UiErr `
    -PassThru

if ($null -eq $UiProcess) {
    throw "Command Center process could not be created."
}

$UiSurvived = $false

for ($i = 1; $i -le 15; $i++) {
    Start-Sleep -Seconds 1

    $UiProcess.Refresh()

    if ($UiProcess.HasExited) {
        Write-Host ""
        Write-Host "=== COMMAND CENTER STDOUT ==="

        if (Test-Path $UiOut) {
            Get-Content $UiOut -Tail 220
        }

        Write-Host ""
        Write-Host "=== COMMAND CENTER STDERR ==="

        if (Test-Path $UiErr) {
            Get-Content $UiErr -Tail 350
        }

        throw "RedSight Command Center exited during startup."
    }

    Write-Host "UI process alive: $i/15"

    if ($i -ge 10) {
        $UiSurvived = $true
        break
    }
}

if (-not $UiSurvived) {
    throw "Command Center did not survive the startup validation period."
}

# ---------------------------------------------------------------------
# 15. Try to bring the visible Command Center to foreground
# ---------------------------------------------------------------------

Add-Type @"
using System;
using System.Runtime.InteropServices;

public static class RedSightStage103Window {
    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);

    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);
}
"@ -ErrorAction SilentlyContinue

$WindowFound = $false

for ($i = 1; $i -le 12; $i++) {
    try {
        $Live = Get-Process -Id $UiProcess.Id -ErrorAction Stop
        $Live.Refresh()

        if ($Live.MainWindowHandle -ne 0) {
            [RedSightStage103Window]::ShowWindow(
                $Live.MainWindowHandle,
                9
            ) | Out-Null

            [RedSightStage103Window]::SetForegroundWindow(
                $Live.MainWindowHandle
            ) | Out-Null

            $WindowFound = $true
            Write-Host "WINDOW_FOREGROUND=PASS"
            break
        }
    }
    catch {
    }

    Start-Sleep -Milliseconds 500
}

if (-not $WindowFound) {
    Write-Warning "Command Center process is alive, but Windows did not expose its window handle during the foreground-check interval."
}

# ---------------------------------------------------------------------
# 16. Final health checks
# ---------------------------------------------------------------------

if (-not (Test-Http200 `
    -Url "http://127.0.0.1:8000/api/v1/health" `
    -TimeoutSeconds 5
)) {
    throw "Backend failed final health validation."
}

if (-not (Test-Http200 `
    -Url "http://127.0.0.1:8765/memory/status" `
    -TimeoutSeconds 5
)) {
    throw "Action/Memory Gateway failed final health validation."
}

$UiProcess.Refresh()

if ($UiProcess.HasExited) {
    throw "Command Center exited before final validation."
}

# ---------------------------------------------------------------------
# Final truthful success marker
# ---------------------------------------------------------------------

Write-Host ""
Write-Host "======================================================================"
Write-Host " REDSIGHT STAGE 10.3 R2 RECOVERY COMPLETE"
Write-Host "======================================================================"
Write-Host ""
Write-Host "Original Stage 10.3 source install      : PRESERVED"
Write-Host "QApplication-before-QWidget test        : PASS"
Write-Host "Stage 10.3 overlay compilation          : PASS"
Write-Host "Single chat dispatcher                  : PASS"
Write-Host "Inline red/blue chat above query        : PASS"
Write-Host "Right-side bubble chat dock             : REMOVED"
Write-Host "Attach button in query bar              : PASS"
Write-Host "Attachment tray above query             : PASS"
Write-Host "File-context extraction                 : PASS"
Write-Host "PyMuPDF modern import                   : PASS"
Write-Host "Persistent Stage 10 memory              : PRESERVED"
Write-Host "RedSight backend                        : HEALTHY"
Write-Host "Qdrant                                  : HEALTHY"
Write-Host "Action/Memory Gateway                   : HEALTHY"
Write-Host "Dual GPU                                : PASS"
if ($LmReady) {
    Write-Host "LM Studio                               : CONNECTED"
}
else {
    Write-Host "LM Studio                               : NOT CONNECTED"
}
Write-Host "Command Center                          : RUNNING"
Write-Host "Command Center PID                      : $($UiProcess.Id)"
Write-Host "Window detected                         : $WindowFound"
Write-Host ""
Write-Host "Diagnostics:"
Write-Host $Diag
Write-Host ""
Write-Host "No Qdrant collection was deleted."
Write-Host "No Docker volume was deleted."
Write-Host "No conversation database was deleted."
Write-Host ""
Write-Host "STAGE103_R2_RECOVERY_COMPLETE=YES"
