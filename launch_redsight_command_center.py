# REDSIGHT_STAGE102_HIDPI_BEGIN
import os as _redsight_os
_redsight_os.environ.setdefault('QT_AUTO_SCREEN_SCALE_FACTOR', '1')
_redsight_os.environ.setdefault('QT_SCALE_FACTOR_ROUNDING_POLICY', 'PassThrough')
# REDSIGHT_STAGE102_HIDPI_END
from pathlib import Path
import asyncio
import csv
import io
import json
import os
import subprocess
import sys
import urllib.request

ROOT = r"C:\Users\walim\RedSight"

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# ------------------------------------------------------------
# Explicit local-service wiring
# ------------------------------------------------------------
os.environ["REDSIGHT_API_URL"] = "http://127.0.0.1:8000"
os.environ["REDSIGHT_API_BASE_URL"] = "http://127.0.0.1:8000"
os.environ["API_BASE_URL"] = "http://127.0.0.1:8000"

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
    QVBoxLayout,
)

from qasync import QEventLoop

from app.ui.command_center import CommandCenterMainWindow
from app.ui.action_palette_stage103 import install_action_hooks, attach_action_palette
install_action_hooks(CommandCenterMainWindow)
from app.ui.heritage_panel import attach_heritage_ui
def get_lm_model():
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:1234/v1/models",
            timeout=3.0,
        ) as response:
            data = json.load(response)

        models = data.get("data", [])

        if models:
            return models[0].get("id", "available")

        return "server online / no model listed"
    except Exception as exc:
        return "OFFLINE: " + str(exc)


def query_nvidia():
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    command = [
        "nvidia-smi",
        "--query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
        "--format=csv,noheader,nounits",
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=4,
        creationflags=creationflags,
    )

    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "nvidia-smi failed")

    rows = []

    reader = csv.reader(io.StringIO(result.stdout))

    for raw in reader:
        if len(raw) < 7:
            continue

        values = [value.strip() for value in raw]

        def number(value, default=0.0):
            try:
                return float(value)
            except Exception:
                return default

        used = number(values[3])
        total = number(values[4])
        vram_percent = (used / total * 100.0) if total else 0.0

        rows.append({
            "index": values[0],
            "name": values[1],
            "util": number(values[2]),
            "used": used,
            "total": total,
            "vram_percent": vram_percent,
            "temp": number(values[5]),
            "power": number(values[6]),
        })

    return rows


class LiveGpuDock(QDockWidget):
    def __init__(self, parent=None):
        super().__init__("LIVE DUAL-GPU TELEMETRY", parent)

        container = QWidget()
        layout = QVBoxLayout(container)

        self.connection = QLabel()
        self.connection.setText(
            "LM Studio: " + get_lm_model()
        )

        layout.addWidget(self.connection)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            "GPU",
            "Name",
            "GPU Util",
            "VRAM",
            "Temp",
            "Power",
        ])

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        layout.addWidget(self.table)

        self.summary = QLabel("Waiting for NVIDIA telemetry...")
        layout.addWidget(self.summary)

        self.setWidget(container)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)

        self.lm_timer = QTimer(self)
        self.lm_timer.timeout.connect(self.refresh_lm)
        self.lm_timer.start(10000)

        self.refresh()

    def refresh_lm(self):
        self.connection.setText(
            "LM Studio: " + get_lm_model()
        )

    def refresh(self):
        try:
            rows = query_nvidia()
        except Exception as exc:
            self.summary.setText("GPU telemetry error: " + str(exc))
            return

        self.table.setRowCount(len(rows))

        summary_parts = []

        for row_index, gpu in enumerate(rows):
            values = [
                "GPU " + str(gpu["index"]),
                gpu["name"],
                "{:.0f}%".format(gpu["util"]),
                "{:.0f}/{:.0f} MiB ({:.1f}%)".format(
                    gpu["used"],
                    gpu["total"],
                    gpu["vram_percent"],
                ),
                "{:.0f} C".format(gpu["temp"]),
                "{:.1f} W".format(gpu["power"]),
            ]

            for column, value in enumerate(values):
                self.table.setItem(
                    row_index,
                    column,
                    QTableWidgetItem(value),
                )

            summary_parts.append(
                "GPU{} {:.0f}% | VRAM {:.1f}%".format(
                    gpu["index"],
                    gpu["util"],
                    gpu["vram_percent"],
                )
            )

        self.summary.setText("   ||   ".join(summary_parts))


app = QApplication.instance()

if app is None:
    app = QApplication(sys.argv)

# ------------------------------------------------------------
# qasync provides the asyncio loop used by asyncio.create_task.
# This deliberately replaces PySide6.QtAsyncio/QAsyncioTask.
# ------------------------------------------------------------

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

loop = QEventLoop(app)
asyncio.set_event_loop(loop)

window = CommandCenterMainWindow()
# REDSIGHT_BRANDING_STAGE104_BEGIN
try:
    import ctypes as _redsight_ctypes
    from PySide6.QtGui import QIcon as _RedSightQIcon
    from PySide6.QtWidgets import QApplication as _RedSightQApplication
    _redsight_ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("RedSight.CommandCenter")
    _redsight_icon_path = Path(r"C:\Users\walim\RedSight\assets\redsight.ico")
    _redsight_icon = _RedSightQIcon(str(_redsight_icon_path))
    _redsight_app = _RedSightQApplication.instance()
    if _redsight_app is not None:
        _redsight_app.setApplicationName("REDSIGHT")
        _redsight_app.setApplicationDisplayName("REDSIGHT")
        _redsight_app.setOrganizationName("REDSIGHT")
        if not _redsight_icon.isNull():
            _redsight_app.setWindowIcon(_redsight_icon)
    window.setWindowTitle("REDSIGHT — Local Intelligence Command Center")
    if not _redsight_icon.isNull():
        window.setWindowIcon(_redsight_icon)
except Exception as _redsight_brand_error:
    print(f'REDSIGHT_BRANDING_WARNING={_redsight_brand_error}')
# REDSIGHT_BRANDING_STAGE104_END
attach_action_palette(window, Path(__file__).resolve().parent)
attach_heritage_ui(window, Path(__file__).resolve().parent)
# Force RedSight localhost backend where supported by the class.
for attr in (
    "_api_base_url",
    "api_base_url",
    "_base_url",
):
    if hasattr(window, attr):
        try:
            setattr(window, attr, "http://127.0.0.1:8000")
        except Exception:
            pass

# ------------------------------------------------------------
# Accurate host telemetry dock.
# ------------------------------------------------------------
gpu_dock = LiveGpuDock(window)
window.addDockWidget(
    Qt.DockWidgetArea.RightDockWidgetArea,
    gpu_dock,
)

# Keep references alive.
window._redsight_live_gpu_dock = gpu_dock
window._redsight_qasync_loop = loop

try:
    status = window.statusBar()
    status.showMessage(
        "RedSight API: 127.0.0.1:8000  |  "
        "LM Studio: 127.0.0.1:1234  |  "
        "qasync event loop active"
    )
except Exception:
    pass

window.show()

print("COMMAND_CENTER_WINDOW_SHOWN=YES", flush=True)
print("EVENT_LOOP=QASYNC", flush=True)
print("LM_STUDIO_MODEL=" + get_lm_model(), flush=True)

app.aboutToQuit.connect(loop.stop)

with loop:
    loop.run_forever()
