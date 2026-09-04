from __future__ import annotations

# REDSIGHT_STAGE102_HIDPI_BEGIN
import os as _redsight_os
_redsight_os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
_redsight_os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")
# REDSIGHT_STAGE102_HIDPI_END

import asyncio
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("REDSIGHT_API_URL", "http://127.0.0.1:8000")
os.environ.setdefault("REDSIGHT_API_BASE_URL", "http://127.0.0.1:8000")
os.environ.setdefault("API_BASE_URL", "http://127.0.0.1:8000")
os.environ.setdefault("LM_STUDIO_URL", "http://127.0.0.1:1234")
os.environ.setdefault("LM_STUDIO_BASE_URL", "http://127.0.0.1:1234/v1")

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qasync import QEventLoop

# Keep this exact legacy import anchor: historical RedSight repair/heritage tools
# intentionally locate it when applying additive UI integrations.
from app.ui.command_center import CommandCenterMainWindow
from app.ui.action_palette_stage103 import attach_action_palette, install_action_hooks
from app.ui.heritage_panel import attach_heritage_ui
from app.ui.runtime_services import get_lm_model, query_nvidia
from app.ui.stable_command_center import StableCommandCenterMainWindow

CommandCenterMainWindow = StableCommandCenterMainWindow
install_action_hooks(CommandCenterMainWindow)

# REDSIGHT_STAGE112_UI_EXTENSION
# Installer overlays attach above this compatibility marker.


def configure_runtime_logging() -> None:
    local_appdata = Path(os.environ.get("LOCALAPPDATA", str(ROOT)))
    log_dir = local_appdata / "RedSight" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "desktop-runtime.log"
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    if not any(
        isinstance(handler, RotatingFileHandler)
        and Path(getattr(handler, "baseFilename", "")) == log_path
        for handler in root_logger.handlers
    ):
        handler = RotatingFileHandler(
            log_path,
            maxBytes=2 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        root_logger.addHandler(handler)


class LiveGpuDock(QDockWidget):
    """Dual-GPU telemetry that never waits for subprocess/network I/O on Qt."""

    def __init__(self, parent=None):
        super().__init__("LIVE DUAL-GPU TELEMETRY", parent)
        self._gpu_task: asyncio.Task | None = None
        self._lm_task: asyncio.Task | None = None

        container = QWidget()
        layout = QVBoxLayout(container)
        self.connection = QLabel("LM Studio: checking...")
        layout.addWidget(self.connection)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["GPU", "Name", "GPU Util", "VRAM", "Temp", "Power"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)

        self.summary = QLabel("Waiting for NVIDIA telemetry...")
        layout.addWidget(self.summary)
        self.setWidget(container)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1500)
        self.lm_timer = QTimer(self)
        self.lm_timer.timeout.connect(self.refresh_lm)
        self.lm_timer.start(10000)
        QTimer.singleShot(0, self.refresh)
        QTimer.singleShot(0, self.refresh_lm)

    @staticmethod
    def _task(factory):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return None
        return loop.create_task(factory())

    def refresh(self):
        if self._gpu_task is None or self._gpu_task.done():
            self._gpu_task = self._task(self._refresh_gpu)

    async def _refresh_gpu(self):
        try:
            rows = await asyncio.to_thread(query_nvidia)
        except Exception as exc:
            logging.getLogger(__name__).debug("GPU telemetry unavailable: %s", exc)
            self.summary.setText("GPU telemetry error: " + str(exc))
            return

        self.table.setRowCount(len(rows))
        summary = []
        for row_index, gpu in enumerate(rows):
            values = [
                f"GPU {gpu['index']}",
                str(gpu["name"]),
                f"{float(gpu['util']):.0f}%",
                f"{float(gpu['used']):.0f}/{float(gpu['total']):.0f} MiB ({float(gpu['vram_percent']):.1f}%)",
                f"{float(gpu['temp']):.0f} C",
                f"{float(gpu['power']):.1f} W",
            ]
            for column, value in enumerate(values):
                self.table.setItem(row_index, column, QTableWidgetItem(value))
            summary.append(
                f"GPU{gpu['index']} {float(gpu['util']):.0f}% | VRAM {float(gpu['vram_percent']):.1f}%"
            )
        self.summary.setText("   ||   ".join(summary) or "No NVIDIA GPUs reported")

    def refresh_lm(self):
        if self._lm_task is None or self._lm_task.done():
            self._lm_task = self._task(self._refresh_lm)

    async def _refresh_lm(self):
        self.connection.setText("LM Studio: " + await asyncio.to_thread(get_lm_model))

    def closeEvent(self, event):  # noqa: N802
        self.timer.stop()
        self.lm_timer.stop()
        for task in (self._gpu_task, self._lm_task):
            if task is not None and not task.done():
                task.cancel()
        super().closeEvent(event)


configure_runtime_logging()
app = QApplication.instance() or QApplication(sys.argv)
app.setStyle("Fusion")
app.setStyleSheet(
    """
QWidget { background-color: #080D13; color: #F5F8FA; font-size: 13px; }
QMainWindow { background-color: #060A0F; }
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox {
    background-color: #101A24; color: #FFFFFF; border: 1px solid #6688A5;
    border-radius: 6px; padding: 7px;
}
QPushButton {
    background-color: #1565C0; color: white; border: 1px solid #64B5F6;
    border-radius: 6px; padding: 8px 13px; font-weight: bold;
}
QPushButton:hover { background-color: #1976D2; }
QTableWidget, QTableView, QTreeWidget, QListWidget {
    background-color: #0D151D; color: white; gridline-color: #496276;
    border: 1px solid #526D82;
}
QHeaderView::section { background-color: #1A2A38; color: white; padding: 7px; font-weight: bold; }
QTabBar::tab { background-color: #172431; color: #DCE7F0; padding: 8px 13px; }
QTabBar::tab:selected { background-color: #1565C0; color: white; }
QStatusBar { background-color: #070C11; color: #E8F1F8; }
QDockWidget::title { background-color: #172838; color: white; padding: 7px; font-weight: bold; }
"""
)

loop = QEventLoop(app)
asyncio.set_event_loop(loop)
window = CommandCenterMainWindow()

# REDSIGHT_BRANDING_STAGE104_BEGIN
try:
    import ctypes as _redsight_ctypes
    from PySide6.QtGui import QIcon as _RedSightQIcon

    if sys.platform == "win32":
        _redsight_ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("RedSight.CommandCenter")
    icon = _RedSightQIcon(str(ROOT / "assets" / "redsight.ico"))
    app.setApplicationName("REDSIGHT")
    app.setApplicationDisplayName("REDSIGHT")
    app.setOrganizationName("REDSIGHT")
    window.setWindowTitle("REDSIGHT — Local Intelligence Command Center")
    if not icon.isNull():
        app.setWindowIcon(icon)
        window.setWindowIcon(icon)
except Exception as exc:
    logging.getLogger(__name__).warning("REDSIGHT branding warning: %s", exc)
# REDSIGHT_BRANDING_STAGE104_END

attach_action_palette(window, ROOT)
attach_heritage_ui(window, ROOT)
for attr in ("_api_base_url", "api_base_url", "_base_url"):
    if hasattr(window, attr):
        setattr(window, attr, os.environ["REDSIGHT_API_BASE_URL"])

gpu_dock = LiveGpuDock(window)
window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, gpu_dock)
window._redsight_live_gpu_dock = gpu_dock
window._redsight_qasync_loop = loop
window.statusBar().showMessage(
    "RedSight API: 127.0.0.1:8000  |  LM Studio: 127.0.0.1:1234  |  qasync event loop active"
)
window.show()
print("COMMAND_CENTER_WINDOW_SHOWN=YES", flush=True)
print("EVENT_LOOP=QASYNC", flush=True)
print("PROJECT_ROOT=" + str(ROOT), flush=True)

app.aboutToQuit.connect(loop.stop)
with loop:
    loop.run_forever()
