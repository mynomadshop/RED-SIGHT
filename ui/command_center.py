"""
RedSight - High-Performance Local AI Intelligence Platform
PySide6 Desktop UI - Main Window

Command Center with chat canvas, knowledge search, source citations,
tool approvals, and run timeline.
Immersive, inspectable, fast - as specified in the blueprint.
"""

from __future__ import annotations

import sys
import json
from datetime import datetime

import httpx
from PySide6.QtCore import Qt, QTimer, Signal, Slot, QUrl
from PySide6.QtGui import QFont, QColor, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QFormLayout,
    QComboBox,
    QScrollArea,
    QFrame,
    QSizePolicy,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QMessageBox,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QInputDialog,
)


# ─── API Client ──────────────────────────────────────────────────────

class RedSightAPI:
    """HTTP client for the RedSight FastAPI backend."""

    def __init__(self, base_url: str = "http://127.0.0.1:8000"):
        self.base_url = base_url
        self._client = httpx.AsyncClient(base_url=base_url, timeout=30)

    async def search(self, query: str, top_k: int = 20,
                     collections: list = None) -> dict:
        """Search knowledge base."""
        resp = await self._client.post(
            "/api/v1/search",
            json={"query": query, "top_k": top_k, "collections": collections},
        )
        resp.raise_for_status()
        return resp.json()

    async def list_collections(self) -> list:
        """List all collections."""
        resp = await self._client.get("/api/v1/collections")
        resp.raise_for_status()
        return resp.json().get("collections", [])

    async def get_collection_stats(self, collection: str) -> dict:
        """Get collection stats."""
        resp = await self._client.get(f"/api/v1/collections/{collection}/stats")
        resp.raise_for_status()
        return resp.json()

    async def get_chunk(self, chunk_id: str) -> dict:
        """Get chunk by ID."""
        resp = await self._client.get(f"/api/v1/chunks/{chunk_id}")
        resp.raise_for_status()
        return resp.json()

    async def index_file(self, path: str, collection: str = "knowledge_docs",
                         project: str = "default") -> dict:
        """Index a file."""
        resp = await self._client.post(
            "/api/v1/jobs/index",
            json={"path": path, "collection": collection, "project": project},
        )
        resp.raise_for_status()
        return resp.json()

    async def list_jobs(self, status: str = None) -> list:
        """List indexing jobs."""
        params = {}
        if status:
            params["status"] = status
        resp = await self._client.get("/api/v1/jobs", params=params)
        resp.raise_for_status()
        return resp.json().get("jobs", [])

    async def get_gpu_status(self) -> dict:
        """Get GPU status."""
        resp = await self._client.get("/api/v1/gpu/status")
        resp.raise_for_status()
        return resp.json()

    async def chat(self, message: str, model: str = None) -> str:
        """Send chat message via WebSocket."""
        async with self._client.websocket_connect("/ws/stream") as ws:
            await ws.send_json({"message": message, "model": model})
            response = ""
            while True:
                data = await ws.receive_json()
                if "token" in data:
                    response += data["token"]
                elif "done" in data:
                    break
                elif "error" in data:
                    raise Exception(data["error"])
            return response

    async def close(self):
        await self._client.aclose()


# ─── Source Viewer Widget ────────────────────────────────────────────

class SourceCard(QFrame):
    """Display a single retrieved source with provenance."""

    def __init__(self, result: dict, parent=None):
        super().__init__(parent)
        self.result = result
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # Header
        header = QHBoxLayout()
        title = QLabel(self.result.get("heading") or self.result.get("source_path", "Unknown"))
        title.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        title.setWordWrap(True)
        title.setStyleSheet("color: #818cf8;")
        header.addWidget(title)

        # Score badge
        score = self.result.get("score", 0)
        score_label = QLabel(f"Score: {score:.4f}")
        score_label.setStyleSheet("color: #0f0; font-size: 10px;")
        header.addWidget(score_label)
        header.addStretch()

        # Collection badge
        coll = self.result.get("collection", "")
        coll_label = QLabel(coll)
        coll_label.setStyleSheet("color: #888; font-size: 10px; background: #1a1a2a; padding: 2px 6px; border-radius: 3px;")
        header.addWidget(coll_label)
        layout.addLayout(header)

        # Page number
        if self.result.get("page_number"):
            page_label = QLabel(f"Page {self.result['page_number']}")
            page_label.setStyleSheet("color: #666; font-size: 10px;")
            layout.addWidget(page_label)

        # Content preview
        content = self.result.get("content", "")
        preview = content[:300] + ("..." if len(content) > 300 else "")
        content_label = QTextEdit()
        content_label.setPlainText(preview)
        content_label.setReadOnly(True)
        content_label.setMaximumHeight(150)
        content_label.setStyleSheet("""
            QTextEdit {
                background-color: #0d0d15;
                color: #ccc;
                border: 1px solid #2a2a3a;
                border-radius: 4px;
                padding: 6px;
                font-family: Consolas;
                font-size: 10px;
            }
        """)
        layout.addWidget(content_label)

        # Source path
        source = self.result.get("source_path", "")
        if source:
            source_label = QLabel(f"📄 {source}")
            source_label.setStyleSheet("color: #555; font-size: 9px;")
            source_label.setWordWrap(True)
            layout.addWidget(source_label)

        # Chunk ID
        chunk_id = self.result.get("chunk_id", "")
        if chunk_id:
            cid_label = QLabel(f"ID: {chunk_id}")
            cid_label.setStyleSheet("color: #444; font-size: 9px;")
            layout.addWidget(cid_label)

        layout.addStretch()


class SourceViewerPanel(QScrollArea):
    """Panel for displaying retrieved sources."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
        """)

        self.container = QWidget()
        self.setLayout = QVBoxLayout(self.container)
        self.setLayout().setContentsMargins(0, 0, 0, 0)
        self.setLayout().setSpacing(8)
        self.setLayout().addStretch()

        self.setWidget(self.container)
        self.cards = []

    def clear(self):
        """Clear all source cards."""
        for card in self.cards:
            card.deleteLater()
        self.cards.clear()
        # Remove stretch
        while self.setLayout().count():
            item = self.setLayout().takeAt(0)
            if item.widget() and item.widget() != self.cards:
                item.widget().deleteLater()
        self.setLayout().addStretch()

    def add_results(self, results: list):
        """Add search results as source cards."""
        self.clear()
        if not results:
            empty = QLabel("No results found. Try a different query or index some documents.")
            empty.setStyleSheet("color: #666; font-style: italic; padding: 20px;")
            self.setLayout().insertWidget(0, empty)
            return

        for r in results:
            card = SourceCard(r)
            self.cards.append(card)
            self.setLayout().insertWidget(self.setLayout().count() - 1, card)


# ─── Knowledge Search Widget ─────────────────────────────────────────

class KnowledgeSearchWidget(QWidget):
    """Knowledge search interface."""

    search_requested = Signal(str, list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        # Search bar
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search knowledge base...")
        self.search_input.returnPressed.connect(self.perform_search)
        self.search_input.setStyleSheet("""
            QLineEdit {
                background-color: #1a1a2a;
                color: #e0e0e0;
                border: 1px solid #2a2a3a;
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 12px;
            }
            QLineEdit:focus {
                border: 1px solid #6366f1;
            }
        """)
        search_layout.addWidget(self.search_input)

        self.search_btn = QPushButton("Search")
        self.search_btn.clicked.connect(self.perform_search)
        search_layout.addWidget(self.search_btn)

        layout.addLayout(search_layout)

        # Collections filter
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Collections:"))
        self.collection_combo = QComboBox()
        self.collection_combo.setEditable(True)
        self.collection_combo.setPlaceholderText("All collections")
        filter_layout.addWidget(self.collection_combo)
        filter_layout.addStretch()
        layout.addLayout(filter_layout)

        # Results count
        self.results_label = QLabel("")
        self.results_label.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(self.results_label)

    def perform_search(self):
        query = self.search_input.text().strip()
        if not query:
            return

        collections = []
        selected = self.collection_combo.currentText()
        if selected and selected.lower() != "all collections":
            collections = [c.strip() for c in selected.split(",")]

        self.search_requested.emit(query, collections)


# ─── Indexing Widget ─────────────────────────────────────────────────

class IndexingWidget(QWidget):
    """File indexing interface."""

    index_requested = Signal(str, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        # Path input
        form = QFormLayout()
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("Path to file or directory...")
        form.addRow("Path:", self.path_input)

        self.collection_combo = QComboBox()
        self.collection_combo.addItems([
            "knowledge_docs", "project_code", "project_decisions",
            "skills_index", "episodic_memory", "tool_catalog", "eval_corpus",
        ])
        form.addRow("Collection:", self.collection_combo)

        self.project_input = QLineEdit()
        self.project_input.setText("default")
        self.project_input.setPlaceholderText("Project identifier")
        form.addRow("Project:", self.project_input)

        layout.addLayout(form)

        # Index button
        self.index_btn = QPushButton("📚 Index Files")
        self.index_btn.clicked.connect(self.do_index)
        self.index_btn.setStyleSheet("""
            QPushButton {
                background-color: #6366f1;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 16px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #818cf8; }
            QPushButton:disabled { background-color: #444; }
        """)
        layout.addWidget(self.index_btn)

        # Status
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(self.status_label)

        # Job list
        self.jobs_label = QLabel("Recent Jobs:")
        self.jobs_label.setStyleSheet("color: #aaa; font-size: 11px; font-weight: bold;")
        layout.addWidget(self.jobs_label)

        self.job_list = QTableWidget()
        self.job_list.setColumnCount(4)
        self.job_list.setHorizontalHeaderLabels(["Job ID", "Status", "Chunks", "Collection"])
        self.job_list.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.job_list.setStyleSheet("""
            QTableWidget {
                background-color: #12121a;
                color: #ccc;
                border: 1px solid #2a2a3a;
                border-radius: 4px;
                gridline-color: #2a2a3a;
            }
            QTableWidget::item { padding: 4px; }
            QHeaderView::section {
                background-color: #1a1a2a;
                color: #888;
                border: none;
                padding: 4px;
            }
        """)
        layout.addWidget(self.job_list)
        layout.addStretch()

    def do_index(self):
        path = self.path_input.text().strip()
        collection = self.collection_combo.currentText()
        project = self.project_input.text().strip() or "default"
        if not path:
            self.status_label.setText("❌ Please enter a path")
            return
        self.index_requested.emit(path, collection, project)

    def update_status(self, message: str):
        self.status_label.setText(message)

    def add_job(self, job_id: str, status: str, chunks: int, collection: str):
        row = self.job_list.rowCount()
        self.job_list.insertRow(row)
        self.job_list.setItem(row, 0, QTableWidgetItem(job_id))
        self.job_list.setItem(row, 1, QTableWidgetItem(status))
        self.job_list.setItem(row, 2, QTableWidgetItem(str(chunks)))
        self.job_list.setItem(row, 3, QTableWidgetItem(collection))


# ─── GPU Monitor Widget ──────────────────────────────────────────────

class GpuMonitorWidget(QWidget):
    """Real-time GPU monitoring widget."""

    def __init__(self, api: RedSightAPI, parent=None):
        super().__init__(parent)
        self.api = api
        self.setup_ui()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_gpu_status)
        self.timer.start(5000)

    def setup_ui(self):
        layout = QVBoxLayout(self)

        label = QLabel("GPU Status")
        label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        layout.addWidget(label)

        self.gpu_label = QLabel("Connecting...")
        self.gpu_label.setStyleSheet("color: #888;")
        layout.addWidget(self.gpu_label)

        self.vram_bar = QProgressBar()
        self.vram_bar.setRange(0, 100)
        self.vram_bar.setValue(0)
        layout.addWidget(self.vram_bar)

    async def update_gpu_status(self):
        try:
            status = await self.api.get_gpu_status()
            gpus = status.get("gpus", [])
            if gpus:
                gpu = gpus[0]
                name = gpu.get("name", "Unknown")
                util = gpu.get("utilization_percent", 0)
                temp = gpu.get("temperature_c", 0)
                used = gpu.get("used_vram_mb", 0)
                total = gpu.get("total_vram_mb", 1)
                pct = (used / total * 100) if total > 0 else 0

                self.gpu_label.setText(
                    f"{name} | {util:.0f}% | {temp:.0f}°C | "
                    f"{used:.0f}/{total:.0f} MB VRAM"
                )
                self.gpu_label.setStyleSheet("color: #0f0;")
                self.vram_bar.setValue(int(pct))
            else:
                self.gpu_label.setText("No GPUs detected")
                self.gpu_label.setStyleSheet("color: #f88;")
        except Exception as e:
            self.gpu_label.setText(f"Error: {str(e)[:40]}")
            self.gpu_label.setStyleSheet("color: #f88;")


# ─── Model Status Widget ─────────────────────────────────────────────

class ModelStatusWidget(QWidget):
    """Model status and selection widget."""

    def __init__(self, api: RedSightAPI, parent=None):
        super().__init__(parent)
        self.api = api
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        label = QLabel("Model Status")
        label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        layout.addWidget(label)

        self.model_label = QLabel("Checking...")
        self.model_label.setStyleSheet("color: #888;")
        layout.addWidget(self.model_label)

        self.model_combo = QLineEdit("default-model")
        self.model_combo.setPlaceholderText("Model ID")
        layout.addWidget(self.model_combo)


# ─── Chat Canvas ─────────────────────────────────────────────────────

class ChatCanvas(QPlainTextEdit):
    """Chat canvas with streaming support."""

    message_sent = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        self.setPlaceholderText("Ask anything... (connected to local AI)")
        font = QFont("Consolas", 11)
        self.setFont(font)
        self.setReadOnly(True)

    def append_message(self, role: str, content: str):
        """Append a message to the chat canvas."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        prefix = f"[{timestamp}] {role.upper()}: "
        self.appendPlainText(prefix + content)
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

    def keyPressEvent(self, event):
        """Handle Enter key to send message."""
        if event.key() == Qt.Key.Key_Return and not event.modifiers().testFlag(Qt.KeyboardModifier.ShiftModifier):
            text = self.toPlainText().strip()
            if text:
                self.message_sent.emit(text)
                self.clear()
        else:
            super().keyPressEvent(event)


# ─── Command Center Main Window ──────────────────────────────────────

class CommandCenter(QMainWindow):
    """
    RedSight Command Center - Main UI Window

    The central hub for all AI interactions:
    - Chat/task canvas
    - Knowledge search & source inspection
    - File indexing
    - Tool approvals
    - Run timeline
    - GPU and model status
    """

    def __init__(self):
        super().__init__()
        self.api = RedSightAPI()
        self.setup_ui()
        self.setup_docks()
        self.setup_statusbar()
        self.load_style()

    def setup_ui(self):
        """Initialize the main UI components."""
        self.setWindowTitle("RedSight - Command Center")
        self.setMinimumSize(1400, 900)

        # Central widget with splitter
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QHBoxLayout(central)

        # Left: Chat canvas
        self.chat = ChatCanvas()
        self.chat.message_sent.connect(self.handle_message)
        main_layout.addWidget(self.chat, stretch=3)

        # Right: Tabs for knowledge, sources, indexing, tools, timeline
        self.right_tabs = QTabWidget()

        # Knowledge Search tab
        self.knowledge_search = KnowledgeSearchWidget()
        self.knowledge_search.search_requested.connect(self.handle_search)
        self.right_tabs.addTab(self.knowledge_search, "🔍 Knowledge")

        # Sources tab
        self.sources_panel = SourceViewerPanel()
        self.right_tabs.addTab(self.sources_panel, "📄 Sources")

        # Indexing tab
        self.indexing = IndexingWidget()
        self.indexing.index_requested.connect(self.handle_index)
        self.right_tabs.addTab(self.indexing, "📚 Index")

        # Tools tab
        self.tools = QTextEdit()
        self.tools.setPlaceholderText("Tool executions will appear here...")
        self.tools.setReadOnly(True)
        self.right_tabs.addTab(self.tools, "🔧 Tools")

        # Timeline tab
        self.timeline = QTextEdit()
        self.timeline.setPlaceholderText("Run timeline will appear here...")
        self.timeline.setReadOnly(True)
        self.right_tabs.addTab(self.timeline, "⏱️ Timeline")

        main_layout.addWidget(self.right_tabs, stretch=2)

    def setup_docks(self):
        """Setup dock widgets for GPU and model status."""
        gpu_dock = QDockWidget("GPU Monitor", self)
        self.gpu_widget = GpuMonitorWidget(self.api)
        gpu_dock.setWidget(self.gpu_widget)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, gpu_dock)

        model_dock = QDockWidget("Model Status", self)
        self.model_widget = ModelStatusWidget(self.api)
        model_dock.setWidget(self.model_widget)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, model_dock)

    def setup_statusbar(self):
        """Setup status bar with quick info."""
        self.statusbar = QStatusBar()
        self.setStatusBar(self.statusbar)

        self.status_label = QLabel("Ready")
        self.statusbar.addWidget(self.status_label)

        self.progress = QProgressBar()
        self.progress.setFixedWidth(150)
        self.statusbar.addPermanentWidget(self.progress)

    def load_style(self):
        """Apply Dark Core aesthetic styling."""
        self.setStyleSheet("""
            QMainWindow { background-color: #0a0a0f; }
            QPlainTextEdit, QTextEdit {
                background-color: #12121a;
                color: #e0e0e0;
                border: 1px solid #2a2a3a;
                border-radius: 6px;
                padding: 8px;
            }
            QTabWidget::pane {
                border: 1px solid #2a2a3a;
                background-color: #12121a;
            }
            QTabBar::tab {
                background-color: #1a1a2a;
                color: #888;
                padding: 8px 16px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:selected {
                background-color: #2a2a3a;
                color: #fff;
            }
            QLabel { color: #e0e0e0; }
            QProgressBar {
                border: 1px solid #2a2a3a;
                border-radius: 4px;
                text-align: center;
                background-color: #1a1a2a;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #6366f1, stop:1 #8b5cf6);
                border-radius: 3px;
            }
            QDockWidget {
                titlebar-close-icon: none;
                titlebar-normal-icon: none;
            }
            QDockWidget::title {
                background-color: #1a1a2a;
                color: #888;
                padding: 6px;
                text-align: center;
            }
            QLineEdit {
                background-color: #1a1a2a;
                color: #e0e0e0;
                border: 1px solid #2a2a3a;
                border-radius: 4px;
                padding: 6px;
            }
            QPushButton {
                background-color: #6366f1;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #818cf8; }
        """)

    # ─── Handlers ──────────────────────────────────────────────────

    @Slot(str)
    async def handle_message(self, message: str):
        """Handle user message - send to API and display response."""
        self.chat.append_message("user", message)
        self.status_label.setText("Processing...")
        self.progress.setValue(30)

        try:
            # Try chat via WebSocket
            response = await self.api.chat(message)
            self.chat.append_message("assistant", response)
            self.status_label.setText("Ready")
            self.progress.setValue(0)
        except Exception as e:
            # Fallback: try search if chat fails
            self.chat.append_message("error", f"Chat error: {str(e)}")
            self.status_label.setText("Chat unavailable — try Knowledge Search")

    async def handle_search(self, query: str, collections: list):
        """Handle knowledge search."""
        self.status_label.setText(f"Searching: {query}")
        self.progress.setValue(20)

        try:
            result = await self.api.search(query, top_k=20, collections=collections or None)
            self.progress.setValue(80)

            # Display results
            self.sources_panel.add_results(result.get("results", []))

            count = result.get("count", 0)
            self.knowledge_search.results_label.setText(
                f"{count} results for '{query}'"
            )

            # Log to timeline
            ts = datetime.now().strftime("%H:%M:%S")
            self.timeline.appendPlainText(
                f"[{ts}] 🔍 Search: '{query}' → {count} results"
            )

            self.status_label.setText(f"Search complete: {count} results")
            self.progress.setValue(0)

        except Exception as e:
            self.sources_panel.add_results([])
            self.status_label.setText(f"Search error: {str(e)}")
            self.knowledge_search.results_label.setText("Search failed")

    async def handle_index(self, path: str, collection: str, project: str):
        """Handle file indexing."""
        self.indexing.update_status(f"Indexing {path}...")
        self.status_label.setText(f"Indexing: {path}")
        self.progress.setValue(50)

        try:
            result = await self.api.index_file(path, collection, project)
            self.progress.setValue(100)

            status = result.get("status", "unknown")
            chunks = result.get("chunks_created", 0)
            job_id = result.get("job_id", "")

            self.indexing.add_job(job_id, status, chunks, collection)
            self.indexing.update_status(f"✅ {status}: {chunks} chunks")

            ts = datetime.now().strftime("%H:%M:%S")
            self.timeline.appendPlainText(
                f"[{ts}] 📚 Indexed: {path} → {collection} ({chunks} chunks)"
            )

            self.status_label.setText(f"Indexed: {chunks} chunks")

        except Exception as e:
            self.indexing.update_status(f"❌ Error: {str(e)}")
            self.status_label.setText(f"Index error: {str(e)}")

        self.progress.setValue(0)

    async def closeEvent(self, event):
        """Clean up on close."""
        await self.api.close()
        event.accept()


def main():
    """Main entry point for the PySide6 UI."""
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    window = CommandCenter()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
