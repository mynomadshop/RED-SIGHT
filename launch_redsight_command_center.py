# REDSIGHT_STAGE102_HIDPI_BEGIN
import os as _redsight_os
_redsight_os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
_redsight_os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")
# REDSIGHT_STAGE102_HIDPI_END

from __future__ import annotations

import asyncio
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import os
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

from app.ui.action_palette_stage103 import attach_action_palette, install_action_hooks
from app.ui.heritage_panel import attach_heritage_ui
from app.ui.runtime_services import get_lm_model, query_nvidia
from app.ui.stable_command_center import StableCommandCenterMainWindow

CommandCenterMainWindow = StableCommandCenterMainWindow
install_action_hooks(CommandCenterMainWindow)

# REDSIGHT_STAGE112_UI_EXTENSION
# Additive UI extensions are injected above this line by the installer's app
# overlay. Keep the marker so current installer overlays remain compatible.


def configure_runtime_logging() -> None:
    """Keep a bounded desktop runtime log in addition to launcher stdout logs."""
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
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
        root_logger.addHandler(handler)


class LiveGpuDock(QDockWidget):
    """Live dual-GPU telemetry without blocking the Qt GUI thread."""

    def __init__(self, parent=None):
        super().__init__("LIVE DUAL-GPU TELEMETRY", parent)
        self._gpu_task: asyncio.Task | None = None
        self._lm_task: asyncio.Task | None = None

        container = QWidget()
        layout = QVBoxLayout(container)

        self.connection = QLabel("LM Studio: checking...")
        layout.addWidget(self.connection)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["GPU", "Name", "GPU Util", "VRAM", "Temp", "Power"]
        )
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

    def _create_task(self, coro):
        try:
            return asyncio.get_running_loop().create_task(coro)
        except RuntimeError:
            return None

    def refresh_lm(self):
        if self._lm_task is not None and not self._lm_task.done():
            return
        self._lm_task = self._create_task(self._refresh_lm_async())

    async def _refresh_lm_async(self):
        model = await asyncio.to_thread(get_lm_model)
        self.connection.setText("LM Studio: " + model)

    def refresh(self):
        if self._gpu_task is not None and not self._gpu_task.done():
            return
        self._gpu_task = self._create_task(self._refresh_gpu_async())

    async def _refresh_gpu_async(self):
        try:
            rows = await asyncio.to_thread(query_nvidia)
        except Exception as exc:
            logging.getLogger(__name__).debug("GPU telemetry unavailable: %s", exc)
            self.summary.setText("GPU telemetry error: " + str(exc))
            return

        self.table.setRowCount(len(rows))
        summary_parts = []
        for row_index, gpu in enumerate(rows):
            values = [
                "GPU " + str(gpu["index"]),
                str(gpu["name"]),
                "{:.0f}%".format(float(gpu["util"])),
                "{:.0f}/{:.0f} MiB ({:.1f}%)".format(
                    float(gpu["used"]),
                    float(gpu["total"]),
                    float(gpu["vram_percent"]),
                ),
                "{:.0f} C".format(float(gpu["temp"])),
                "{:.1f} W".format(float(gpu["power"])),
            ]
            for column, value in enumerate(values):
                self.table.setItem(row_index, column, QTableWidgetItem(value))

            summary_parts.append(
                "GPU{} {:.0f}% | VRAM {:.1f}%".format(
                    gpu["index"],
                    float(gpu["util"]),
                    float(gpu["vram_percent"]),
                )
            )

        self.summary.setText("   ||   ".join(summary_parts) or "No NVIDIA GPUs reported")

    def closeEvent(self, event):  # noqa: N802 - Qt API name
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
    r"""
QWidget {
    background-color: #080D13;
    color: #F5F8FA;
    font-size: 13px;
}
QMainWindow { background-color: #060A0F; }
QLabel { color: #F7FAFC; background: transparent; }
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox {
    background-color: #101A24;
    color: #FFFFFF;
    border: 1px solid #6688A5;
    border-radius: 6px;
    padding: 7px;
    selection-background-color: #1976D2;
    selection-color: white;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus { border: 2px solid #64B5F6; }
QPushButton {
    background-color: #1565C0;
    color: white;
    border: 1px solid #64B5F6;
    border-radius: 6px;
    padding: 8px 13px;
    font-weight: bold;
}
QPushButton:hover { background-color: #1976D2; }
QPushButton:pressed { background-color: #0D47A1; }
QGroupBox {
    background-color: #101923;
    color: white;
    border: 1px solid #526D82;
    border-radius: 7px;
    margin-top: 10px;
    padding-top: 8px;
    font-weight: bold;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
QTableWidget, QTableView, QTreeWidget, QListWidget {
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
QTabWidget::pane { background-color: #0D151D; border: 1px solid #526D82; }
QTabBar::tab {
    background-color: #172431;
    color: #DCE7F0;
    padding: 8px 13px;
    border: 1px solid #455E73;
}
QTabBar::tab:selected { background-color: #1565C0; color: white; }
QProgressBar {
    background-color: #101820;
    color: white;
    border: 1px solid #607D8B;
    border-radius: 5px;
    text-align: center;
}
QProgressBar::chunk { background-color: #1976D2; }
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
QToolTip { background-color: #182A38; color: white; border: 1px solid #90CAF9; }
"""
)

loop = QEventLoop(app)
asyncio.set_event_loop(loop)

window = CommandCenterMainWindow()

# REDSIGHT_BRANDING_STAGE104_BEGIN
try:
    import ctypes as _redsight_ctypes
    from PySide6.QtGui import QIcon as _RedSightQIcon
    from PySide6.QtWidgets import QApplication as _RedSightQApplication

    if sys.platform == "win32":
        _redsight_ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "RedSight.CommandCenter"
        )
    _redsight_icon_path = ROOT / "assets" / "redsight.ico"
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
    logging.getLogger(__name__).warning("REDSIGHT branding warning: %s", _redsight_brand_error)
# REDSIGHT_BRANDING_STAGE104_END

attach_action_palette(window, ROOT)
attach_heritage_ui(window, ROOT)

for attr in ("_api_base_url", "api_base_url", "_base_url"):
    if hasattr(window, attr):
        try:
            setattr(window, attr, os.environ["REDSIGHT_API_BASE_URL"])
        except Exception:
            pass

gpu_dock = LiveGpuDock(window)
window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, gpu_dock)
window._redsight_live_gpu_dock = gpu_dock
window._redsight_qasync_loop = loop

try:
    window.statusBar().showMessage(
        "RedSight API: 127.0.0.1:8000  |  LM Studio: 127.0.0.1:1234  |  qasync event loop active"
    )
except Exception:
    pass

window.show()
print("COMMAND_CENTER_WINDOW_SHOWN=YES", flush=True)
print("EVENT_LOOP=QASYNC", flush=True)
print("PROJECT_ROOT=" + str(ROOT), flush=True)

app.aboutToQuit.connect(loop.stop)
with loop:
    loop.run_forever()
