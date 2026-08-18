"""
RedSight - High-Performance Local AI Intelligence Platform
Command Center UI (PySide6 Desktop Application)

A professional desktop application for interacting with the RedSight platform:
- Real-time GPU monitoring dashboard
- Chat interface with streaming responses
- Source citation cards
- Agent task management
- System health overview
- Model selection and configuration
"""

from __future__ import annotations

import sys
import logging
from typing import Optional

# PySide6 imports
try:
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QTextEdit, QLineEdit, QPushButton, QTabWidget,
        QGroupBox, QProgressBar, QComboBox, QSplitter, QScrollArea,
        QFrame, QStatusBar, QMenuBar, QMenu, QMessageBox, QFileDialog,
        QListWidget, QListWidgetItem, QTreeWidget, QTreeWidgetItem,
        QTableWidget, QTableWidgetItem, QHeaderView, QCheckBox,
        QSpinBox, QDoubleSpinBox, QSlider, QLCDNumber, QDateEdit,
        QTimeEdit, QDateTimeEdit, QCalendarWidget, QDockWidget,
        QToolBar, QToolButton, QSizePolicy, QStackedWidget,
    )
    from PySide6.QtCore import Qt, QThread, Signal, QTimer, QSize, QRect, QPropertyAnimation, QEasingCurve
    from PySide6.QtGui import (
        QIcon, QPixmap, QFont, QColor, QTextCursor, QKeySequence,
        QAction, QPalette, QBrush, QPainter, QPen, QLinearGradient,
        QRadialGradient, QStandardItemModel, QStandardItem, QMovie,
    )
    HAS_PYSIDE6 = True
except ImportError:
    HAS_PYSIDE6 = False
    logger = logging.getLogger(__name__)
    logger.warning("PySide6 not installed. Run: pip install PySide6")


class GPUStatusWidget(QWidget):
    """Real-time GPU status display."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._gpu_data = {}
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Title
        title = QLabel("GPU Status")
        title.setFont(QFont("Segoe UI", 12, QFont.Bold))
        layout.addWidget(title)
        
        # GPU cards
        self._gpu_cards = []
        for i in range(4):  # Max 4 GPUs
            card = self._create_gpu_card(i)
            layout.addWidget(card)
            self._gpu_cards.append(card)
    
    def _create_gpu_card(self, index: int) -> QFrame:
        card = QFrame()
        card.setFrameShape(QFrame.StyledPanel)
        card.setStyleSheet("""
            QFrame {
                background-color: #1a1a2e;
                border: 1px solid #16213e;
                border-radius: 8px;
                padding: 10px;
            }
        """)
        
        layout = QVBoxLayout(card)
        
        # GPU name
        name_label = QLabel(f"GPU {index}")
        name_label.setFont(QFont("Segoe UI", 10, QFont.Bold))
        name_label.setStyleSheet("color: #e94560;")
        layout.addWidget(name_label)
        
        # VRAM usage
        vram_label = QLabel("VRAM: 0 / 0 MB")
        vram_label.setStyleSheet("color: #eee;")
        layout.addWidget(vram_label)
        
        # VRAM bar
        vram_bar = QProgressBar()
        vram_bar.setRange(0, 100)
        vram_bar.setValue(0)
        vram_bar.setStyleSheet("""
            QProgressBar {
                background-color: #16213e;
                border: none;
                height: 8px;
                border-radius: 4px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #e94560, stop:1 #0f3460);
                border-radius: 4px;
            }
        """)
        layout.addWidget(vram_bar)
        
        # Temperature
        temp_label = QLabel("Temp: --°C")
        temp_label.setStyleSheet("color: #aaa;")
        layout.addWidget(temp_label)
        
        # Utilization
        util_label = QLabel("Utilization: 0%")
        util_label.setStyleSheet("color: #aaa;")
        layout.addWidget(util_label)
        
        return card
    
    def update_gpu(self, index: int, data: dict):
        """Update GPU card with new data."""
        if index >= len(self._gpu_cards):
            return
        
        card = self._gpu_cards[index]
        widgets = card.findChildren(QLabel)
        bars = card.findChildren(QProgressBar)
        
        if len(widgets) >= 4 and len(bars) >= 1:
            vram = data.get("vram_used", 0)
            total = data.get("vram_total", 0)
            if total > 0:
                widgets[1].setText(f"VRAM: {vram} / {total} MB")
                bars[0].setValue(int((vram / total) * 100))
            
            temp = data.get("temperature", 0)
            if temp > 0:
                widgets[2].setText(f"Temp: {temp}°C")
            
            util = data.get("utilization", 0)
            widgets[3].setText(f"Utilization: {util}%")


class ChatWidget(QWidget):
    """Chat interface with streaming support."""
    
    message_sent = Signal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Chat history
        self._chat_history = QTextEdit()
        self._chat_history.setReadOnly(True)
        self._chat_history.setFont(QFont("Consolas", 10))
        self._chat_history.setStyleSheet("""
            QTextEdit {
                background-color: #0f0f23;
                color: #eee;
                border: 1px solid #16213e;
                border-radius: 8px;
                padding: 10px;
            }
        """)
        layout.addWidget(self._chat_history)
        
        # Input area
        input_layout = QHBoxLayout()
        
        self._message_input = QLineEdit()
        self._message_input.setPlaceholderText("Type your message...")
        self._message_input.setFont(QFont("Segoe UI", 10))
        self._message_input.setStyleSheet("""
            QLineEdit {
                background-color: #1a1a2e;
                color: #eee;
                border: 1px solid #16213e;
                border-radius: 8px;
                padding: 10px;
            }
            QLineEdit:focus {
                border: 1px solid #e94560;
            }
        """)
        input_layout.addWidget(self._message_input)
        
        # Send button
        self._send_button = QPushButton("Send")
        self._send_button.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self._send_button.setStyleSheet("""
            QPushButton {
                background-color: #e94560;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 10px 20px;
            }
            QPushButton:hover {
                background-color: #c73e54;
            }
            QPushButton:pressed {
                background-color: #a83246;
            }
        """)
        self._send_button.clicked.connect(self._on_send)
        input_layout.addWidget(self._send_button)
        
        layout.addLayout(input_layout)
        
        # Connect enter key
        self._message_input.returnPressed.connect(self._on_send)
    
    def _on_send(self):
        """Handle send button click."""
        message = self._message_input.text().strip()
        if message:
            self.message_sent.emit(message)
            self._message_input.clear()
            
            # Add user message to chat
            self._add_message("You", message, "#e94560")
    
    def _add_message(self, sender: str, message: str, color: str = "#eee"):
        """Add a message to the chat history."""
        self._chat_history.append(f'<span style="color: {color}; font-weight: bold;">{sender}:</span> {message}')
        self._chat_history.verticalScrollBar().setValue(
            self._chat_history.verticalScrollBar().maximum()
        )
    
    def add_assistant_message(self, message: str):
        """Add an assistant message."""
        self._add_message("Assistant", message, "#4ecca3")
    
    def clear_chat(self):
        """Clear chat history."""
        self._chat_history.clear()


class HealthDashboardWidget(QWidget):
    """System health dashboard."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Title
        title = QLabel("System Health")
        title.setFont(QFont("Segoe UI", 12, QFont.Bold))
        layout.addWidget(title)
        
        # Health status
        self._health_status = QLabel("Status: Healthy")
        self._health_status.setFont(QFont("Segoe UI", 11))
        self._health_status.setStyleSheet("color: #4ecca3;")
        layout.addWidget(self._health_status)
        
        # Metrics
        metrics_layout = QHBoxLayout()
        
        # CPU metric
        cpu_group = QGroupBox("CPU")
        cpu_layout = QVBoxLayout(cpu_group)
        self._cpu_label = QLabel("0%")
        self._cpu_label.setFont(QFont("Segoe UI", 14, QFont.Bold))
        self._cpu_label.setAlignment(Qt.AlignCenter)
        cpu_layout.addWidget(self._cpu_label)
        metrics_layout.addWidget(cpu_group)
        
        # Memory metric
        mem_group = QGroupBox("Memory")
        mem_layout = QVBoxLayout(mem_group)
        self._mem_label = QLabel("0%")
        self._mem_label.setFont(QFont("Segoe UI", 14, QFont.Bold))
        self._mem_label.setAlignment(Qt.AlignCenter)
        mem_layout.addWidget(self._mem_label)
        metrics_layout.addWidget(mem_group)
        
        # Disk metric
        disk_group = QGroupBox("Disk")
        disk_layout = QVBoxLayout(disk_group)
        self._disk_label = QLabel("0%")
        self._disk_label.setFont(QFont("Segoe UI", 14, QFont.Bold))
        self._disk_label.setAlignment(Qt.AlignCenter)
        disk_layout.addWidget(self._disk_label)
        metrics_layout.addWidget(disk_group)
        
        layout.addLayout(metrics_layout)
        
        # Alerts list
        alerts_group = QGroupBox("Active Alerts")
        alerts_layout = QVBoxLayout(alerts_group)
        self._alerts_list = QListWidget()
        self._alerts_list.setStyleSheet("""
            QListWidget {
                background-color: #1a1a2e;
                color: #eee;
                border: 1px solid #16213e;
                border-radius: 8px;
            }
        """)
        alerts_layout.addWidget(self._alerts_list)
        layout.addWidget(alerts_group)
    
    def update_health(self, health_data: dict):
        """Update health dashboard with new data."""
        status = health_data.get("status", "unknown")
        self._health_status.setText(f"Status: {status.capitalize()}")
        
        if status == "healthy":
            self._health_status.setStyleSheet("color: #4ecca3;")
        elif status == "degraded":
            self._health_status.setStyleSheet("color: #ffa500;")
        else:
            self._health_status.setStyleSheet("color: #e94560;")
        
        metrics = health_data.get("metrics", {})
        self._cpu_label.setText(f"{metrics.get('cpu_percent', 0):.0f}%")
        self._mem_label.setText(f"{metrics.get('memory_percent', 0):.0f}%")
        self._disk_label.setText(f"{metrics.get('disk_percent', 0):.0f}%")
        
        # Update alerts
        self._alerts_list.clear()
        for alert in health_data.get("active_alerts", []):
            item = QListWidgetItem(f"[{alert['severity'].upper()}] {alert['message']}")
            if alert['severity'] == 'critical':
                item.setForeground(QColor('#e94560'))
            elif alert['severity'] == 'warning':
                item.setForeground(QColor('#ffa500'))
            else:
                item.setForeground(QColor('#4ecca3'))
            self._alerts_list.addItem(item)


# REDSIGHT_STAGE10_CONTEXT_BEGIN
_REDSIGHT_STAGE10_ORIGINAL_MESSAGE = None
_REDSIGHT_STAGE10_LAST_EFFECTIVE = None
_REDSIGHT_STAGE10_LAST_SESSION_ID = None


def _redsight_stage10_set_original_message(message):
    global _REDSIGHT_STAGE10_ORIGINAL_MESSAGE
    _REDSIGHT_STAGE10_ORIGINAL_MESSAGE = message


def _redsight_stage10_json_request(path, body, timeout=8):
    import json
    import urllib.request

    data = json.dumps(body).encode("utf-8")

    request = urllib.request.Request(
        "http://127.0.0.1:8765" + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(
        request,
        timeout=timeout,
    ) as response:
        raw = response.read().decode(
            "utf-8",
            errors="replace",
        )
        return json.loads(raw) if raw.strip() else {}


def _redsight_stage10_messages(message):
    global _REDSIGHT_STAGE10_LAST_EFFECTIVE
    global _REDSIGHT_STAGE10_LAST_SESSION_ID

    effective = str(message)

    original = (
        str(_REDSIGHT_STAGE10_ORIGINAL_MESSAGE)
        if _REDSIGHT_STAGE10_ORIGINAL_MESSAGE is not None
        else effective
    )

    _REDSIGHT_STAGE10_LAST_EFFECTIVE = effective

    try:
        legacy = _redsight_heritage_messages(effective)
    except Exception:
        legacy = [
            {"role": "user", "content": effective}
        ]

    heritage_context = ""

    if (
        isinstance(legacy, list)
        and legacy
        and isinstance(legacy[0], dict)
        and legacy[0].get("role") == "system"
    ):
        heritage_context = str(
            legacy[0].get(
                "content",
                "",
            )
        )

    try:
        result = _redsight_stage10_json_request(
            "/memory/build",
            {
                "user_message": original,
                "effective_message": effective,
                "heritage_context": heritage_context,
            },
            timeout=10,
        )

        messages = result.get(
            "messages"
        )

        if isinstance(messages, list) and messages:
            _REDSIGHT_STAGE10_LAST_SESSION_ID = result.get(
                "session_id"
            )
            return messages

    except Exception:
        pass

    return legacy


def _redsight_stage10_commit(data):
    global _REDSIGHT_STAGE10_LAST_EFFECTIVE
    global _REDSIGHT_STAGE10_LAST_SESSION_ID

    try:
        if not isinstance(data, dict):
            return

        assistant = data.get(
            "message"
        )

        if not isinstance(assistant, str) or not assistant.strip():
            return

        effective = str(
            _REDSIGHT_STAGE10_LAST_EFFECTIVE
            or ""
        )

        original = (
            str(_REDSIGHT_STAGE10_ORIGINAL_MESSAGE)
            if _REDSIGHT_STAGE10_ORIGINAL_MESSAGE is not None
            else effective
        )

        _redsight_stage10_json_request(
            "/memory/commit",
            {
                "user_message": original,
                "assistant_message": assistant,
                "effective_message": effective,
                "session_id": _REDSIGHT_STAGE10_LAST_SESSION_ID,
            },
            timeout=12,
        )

    except Exception:
        pass


# REDSIGHT_STAGE10_CONTEXT_END

class CommandCenterMainWindow(QMainWindow):
    """Main Command Center window."""
    
    def __init__(self, api_base_url: str = "http://127.0.0.1:8000"):
        super().__init__()
        self._api_base_url = api_base_url
        self._setup_ui()
        self._setup_menu()
        self._update_timer = QTimer()
        self._update_timer.timeout.connect(self._update_dashboard)
        self._update_timer.start(5000)  # Update every 5 seconds
    
    def _setup_ui(self):
        """Setup main UI."""
        self.setWindowTitle("RedSight Command Center")
        self.setGeometry(100, 100, 1400, 900)
        self.setStyleSheet("""
            QMainWindow {
                background-color: #0f0f23;
            }
            QStatusBar {
                background-color: #1a1a2e;
                color: #eee;
            }
        """)
        
        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        
        # Tab widget
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #16213e;
                border-radius: 8px;
                background-color: #0f0f23;
            }
            QTabBar::tab {
                background-color: #1a1a2e;
                color: #eee;
                padding: 10px 20px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:selected {
                background-color: #e94560;
                color: white;
            }
        """)
        main_layout.addWidget(self._tabs)
        
        # Chat tab
        chat_tab = ChatWidget()
        chat_tab.message_sent.connect(self._on_chat_message)
        self._tabs.addTab(chat_tab, "Chat")
        
        # Dashboard tab
        dashboard_tab = QWidget()
        dashboard_layout = QVBoxLayout(dashboard_tab)
        
        # GPU and Health side by side
        split = QSplitter(Qt.Horizontal)
        
        gpu_widget = GPUStatusWidget()
        split.addWidget(gpu_widget)
        
        health_widget = HealthDashboardWidget()
        split.addWidget(health_widget)
        
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 1)
        
        dashboard_layout.addWidget(split)
        self._tabs.addTab(dashboard_tab, "Dashboard")
        
        # Status bar
        self.statusBar().showMessage("Connected to RedSight API")
    
    def _setup_menu(self):
        """Setup menu bar."""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu("File")
        
        exit_action = QAction("Exit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # View menu
        view_menu = menubar.addMenu("View")
        
        refresh_action = QAction("Refresh", self)
        refresh_action.setShortcut("F5")
        refresh_action.triggered.connect(self._update_dashboard)
        view_menu.addAction(refresh_action)
        
        # Help menu
        help_menu = menubar.addMenu("Help")
        
        about_action = QAction("About", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)
    
    def _on_chat_message(self, message: str):
        """Handle chat message."""
        # Send to API (placeholder - would use httpx in production)
        self.statusBar().showMessage(f"Sending: {message[:50]}...")
        
        # Simulate response (in production, would await API response)
        import asyncio
        asyncio.create_task(self._send_to_api(message))
    
    async def _send_to_api(self, message: str):
        """Send message to API and display response."""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{self._api_base_url}/api/v1/chat",
                    json={"messages": _redsight_stage10_messages(message), "stream": False},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    _redsight_stage10_commit(data)
                    response = None
                    if isinstance(data, dict):
                        response = (data.get("message") if isinstance(data, dict) and isinstance(data.get("message"), str) else None) or (data.get("response") if isinstance(data, dict) else None) or (data.get("content") if isinstance(data, dict) else None) or "No response"
                        if not response and isinstance(data.get("message"), dict):
                            response = data["message"].get("content")
                        if not response and isinstance(data.get("choices"), list) and data["choices"]:
                            first = data["choices"][0]
                            if isinstance(first, dict):
                                msg = first.get("message")
                                if isinstance(msg, dict):
                                    response = msg.get("content")
                                if not response:
                                    response = first.get("text")
                    response = response or "No response"
                    
                    # Find chat tab and add response
                    chat_tab = self._tabs.widget(0)
                    if isinstance(chat_tab, ChatWidget):
                        chat_tab.add_assistant_message(response)
        except Exception as e:
            # Find chat tab and add error
            chat_tab = self._tabs.widget(0)
            if isinstance(chat_tab, ChatWidget):
                chat_tab.add_assistant_message(f"Error: {e}")
        
        self.statusBar().showMessage("Ready")
    
    def _update_dashboard(self):
        """Update dashboard with latest data."""
        try:
            import httpx
            with httpx.Client(timeout=5.0) as client:
                # Get health
                resp = client.get(f"{self._api_base_url}/api/v1/health")
                if resp.status_code == 200:
                    health_data = resp.json()
                    
                    # Update health widget
                    health_tab = self._tabs.widget(1)
                    if health_tab:
                        for widget in health_tab.findChildren(HealthDashboardWidget):
                            widget.update_health(health_data)
        except Exception:
            pass
    
    def _show_about(self):
        """Show about dialog."""
        QMessageBox.about(
            self,
            "About RedSight Command Center",
            "RedSight Command Center v1.0\n\n"
            "High-Performance Local AI Intelligence Platform\n\n"
            "Phase 8: Cloud Adapters, Multi-Agent, UI, Monitoring",
        )


def run_command_center(api_base_url: str = "http://127.0.0.1:8000"):
    """Run the Command Center application."""
    if not HAS_PYSIDE6:
        print("Error: PySide6 is required. Install with: pip install PySide6")
        return
    
    app = QApplication(sys.argv)
    app.setApplicationName("RedSight Command Center")
    app.setStyle("Fusion")
    
    window = CommandCenterMainWindow(api_base_url)
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    run_command_center()
