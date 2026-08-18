
from __future__ import annotations

import asyncio
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app.ui import action_palette_stage91 as s91
from app.ui import command_center as command_center


ROOT = Path(__file__).resolve().parents[2]

OLD_LOOKS_ACTIONABLE = s91.s9._looks_actionable


def _request(path: str, *, body=None, method=None, timeout=30):
    return s91.s9.base._json_request(
        path,
        body=body,
        method=method,
        timeout=timeout,
    )


def _active_task_exists() -> bool:
    try:
        result = _request(
            "/memory/session/active",
            timeout=1,
        )
        session = result.get("session", {})
        return bool(session.get("active_task"))
    except Exception:
        return False


def looks_actionable_stage10(message: str) -> bool:
    if OLD_LOOKS_ACTIONABLE(message):
        return True
    normalized = " ".join(str(message).strip().lower().split()).strip(" .!?")
    if normalized in {
        "yes", "yes do it", "do it", "continue", "continue it",
        "continue that", "proceed", "go ahead", "approved", "i approve",
        "retry", "retry it", "finish it", "complete it", "carry on",
        "resume", "resume it",
    }:
        return _active_task_exists()
    if len(normalized) < 70 and any(
        phrase in normalized
        for phrase in ("continue", "go ahead", "do it", "proceed", "resume", "retry")
    ):
        return _active_task_exists()
    return False


s91.s9._looks_actionable = looks_actionable_stage10


class ConversationDock(QDockWidget):

    def __init__(self, window):
        super().__init__("CHATS & MEMORY", window)

        self.window = window
        self.setObjectName("RedSightConversationMemoryDock")
        self.setMinimumWidth(390)
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
        )

        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(7, 7, 7, 7)
        layout.setSpacing(6)

        self.status = QLabel("Persistent Memory")
        self.status.setStyleSheet(
            "color:#FF454D;font-weight:900;font-size:13px;"
        )
        layout.addWidget(self.status)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search chat sessions...")
        self.search.textChanged.connect(self.refresh)
        layout.addWidget(self.search)

        self.sessions = QListWidget()
        self.sessions.itemSelectionChanged.connect(self.preview_selected)
        self.sessions.itemDoubleClicked.connect(lambda _item: self.open_selected())
        layout.addWidget(self.sessions, 2)

        row1 = QHBoxLayout()

        new_button = QPushButton("+ New Chat")
        new_button.clicked.connect(self.new_chat)
        row1.addWidget(new_button)

        open_button = QPushButton("Open")
        open_button.clicked.connect(self.open_selected)
        row1.addWidget(open_button)

        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.refresh)
        row1.addWidget(refresh_button)

        layout.addLayout(row1)

        row2 = QHBoxLayout()

        rename_button = QPushButton("Rename")
        rename_button.clicked.connect(self.rename_selected)
        row2.addWidget(rename_button)

        pin_button = QPushButton("Pin/Unpin")
        pin_button.clicked.connect(self.toggle_pin)
        row2.addWidget(pin_button)

        archive_button = QPushButton("Archive")
        archive_button.clicked.connect(self.archive_selected)
        row2.addWidget(archive_button)

        layout.addLayout(row2)

        self.task_label = QLabel("Active task: none")
        self.task_label.setWordWrap(True)
        self.task_label.setStyleSheet(
            "color:#D7DEE6;background:#101820;border:1px solid #35424D;"
            "border-radius:5px;padding:6px;"
        )
        layout.addWidget(self.task_label)

        self.transcript = QTextBrowser()
        self.transcript.setPlaceholderText(
            "Select a session to preview its persistent transcript."
        )
        layout.addWidget(self.transcript, 3)

        self.setWidget(host)

        self.setStyleSheet(
            """
            QDockWidget {
                color:#FFFFFF;
                font-weight:800;
            }
            QWidget {
                background:#0A1016;
                color:#EEF2F5;
            }
            QListWidget, QTextBrowser, QLineEdit {
                background:#0E171F;
                color:#F5F7F8;
                border:1px solid #40505F;
                border-radius:5px;
            }
            QListWidget::item {
                padding:6px;
            }
            QListWidget::item:selected {
                background:#8E1F26;
                color:white;
            }
            QPushButton {
                background:#18222C;
                color:#FFFFFF;
                border:1px solid #536576;
                border-radius:5px;
                padding:5px 8px;
                font-weight:700;
            }
            QPushButton:hover {
                background:#A12129;
                border-color:#E34950;
            }
            """
        )

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(8000)
        self.refresh_timer.timeout.connect(self.refresh)
        self.refresh_timer.start()

        self.refresh()

    def selected_id(self):
        item = self.sessions.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def refresh(self):
        selected = self.selected_id()
        try:
            result = _request(
                "/memory/sessions",
                timeout=5,
            )
            sessions = result.get("sessions", [])
        except Exception as exc:
            self.status.setText("Memory gateway unavailable")
            return

        query = self.search.text().strip().lower()
        self.sessions.blockSignals(True)
        self.sessions.clear()
        selected_row = -1

        for session in sessions:
            title = str(session.get("title", "Chat"))
            task = session.get("active_task")
            haystack = (
                title + " "
                + str(session.get("summary", ""))
                + " "
                + str(task.get("goal", "") if isinstance(task, dict) else "")
            ).lower()
            if query and query not in haystack:
                continue

            prefix = ""
            if session.get("active"):
                prefix += "● "
            if session.get("pinned"):
                prefix += "★ "

            updated = session.get("updated_at")
            timestamp = ""
            if updated:
                try:
                    timestamp = datetime.fromtimestamp(float(updated)).strftime("%m/%d %H:%M")
                except Exception:
                    pass

            count = int(session.get("message_count", 0))
            task_mark = " ⚡" if task else ""
            text = f"{prefix}{title}{task_mark}\n{timestamp} • {count} messages"

            item = QListWidgetItem(text)
            item.setData(
                Qt.ItemDataRole.UserRole,
                session.get("id"),
            )
            item.setToolTip(
                str(session.get("summary") or title)[:1200]
            )
            self.sessions.addItem(item)

            if session.get("id") == selected:
                selected_row = self.sessions.count() - 1
            elif selected is None and session.get("active"):
                selected_row = self.sessions.count() - 1

        self.sessions.blockSignals(False)

        if selected_row >= 0:
            self.sessions.setCurrentRow(selected_row)
        elif self.sessions.count() > 0:
            self.sessions.setCurrentRow(0)

        self.update_active_status()

    def update_active_status(self):
        try:
            result = _request(
                "/memory/session/active",
                timeout=4,
            )
            session = result.get("session", {})
            title = session.get("title", "Chat")
            count = session.get("message_count", 0)
            self.status.setText(
                f"ACTIVE • {title} • {count} messages"
            )
            task = session.get("active_task")
            if task:
                self.task_label.setText(
                    "Active task: "
                    + str(task.get("goal", ""))[:900]
                    + "\nStatus: "
                    + str(task.get("status", "active"))
                )
            else:
                self.task_label.setText("Active task: none")
        except Exception:
            pass

    def preview_selected(self):
        sid = self.selected_id()
        if not sid:
            return
        try:
            result = _request(
                f"/memory/sessions/{sid}",
                timeout=8,
            )
        except Exception as exc:
            self.transcript.setPlainText("Could not load session: " + repr(exc))
            return

        session = result.get("session", {})
        messages = result.get("messages", [])
        parts = [
            str(session.get("title", "Chat")),
            "",
            "ROLLING SUMMARY",
            str(session.get("summary") or "(not generated yet)"),
            "",
            "TRANSCRIPT",
            "",
        ]

        for message in messages:
            role = str(message.get("role", "")).upper()
            content = str(message.get("content", ""))
            parts.append(f"{role}\n{content}\n")

        self.transcript.setPlainText("\n".join(parts))
        task = session.get("active_task")
        if task:
            self.task_label.setText(
                "Selected session task: "
                + str(task.get("goal", ""))[:900]
                + "\nStatus: "
                + str(task.get("status", "active"))
            )

    def new_chat(self):
        try:
            result = _request(
                "/memory/sessions/new",
                body={"title": "New Chat"},
                timeout=8,
            )
            session = result.get("session", {})
            self.refresh()
            self.select_session(session.get("id"))
            self.status.setText("ACTIVE • New Chat")
        except Exception as exc:
            QMessageBox.warning(
                self,
                "RedSight Memory",
                "Could not create a new chat:\n\n" + repr(exc),
            )

    def select_session(self, sid):
        if not sid:
            return
        for row in range(self.sessions.count()):
            item = self.sessions.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == sid:
                self.sessions.setCurrentRow(row)
                break

    def open_selected(self):
        sid = self.selected_id()
        if not sid:
            return
        try:
            result = _request(
                f"/memory/sessions/{sid}/activate",
                body={},
                timeout=8,
            )
            session = result.get("session", {})
            self.refresh()
            self.select_session(sid)
            self.status.setText(
                "ACTIVE • " + str(session.get("title", "Chat"))
            )
            self.preview_selected()
        except Exception as exc:
            QMessageBox.warning(
                self,
                "RedSight Memory",
                "Could not open session:\n\n" + repr(exc),
            )

    def rename_selected(self):
        sid = self.selected_id()
        if not sid:
            return
        current = self.sessions.currentItem().text().splitlines()[0]
        title, accepted = QInputDialog.getText(
            self,
            "Rename RedSight Chat",
            "Session name:",
            text=current.replace("● ", "").replace("★ ", "").replace(" ⚡", ""),
        )
        if not accepted or not title.strip():
            return
        try:
            _request(
                f"/memory/sessions/{sid}/rename",
                body={"title": title.strip()},
                timeout=8,
            )
            self.refresh()
            self.select_session(sid)
        except Exception as exc:
            QMessageBox.warning(self, "Rename failed", repr(exc))

    def toggle_pin(self):
        sid = self.selected_id()
        if not sid:
            return
        try:
            detail = _request(
                f"/memory/sessions/{sid}",
                timeout=6,
            )
            pinned = bool(detail.get("session", {}).get("pinned"))
            _request(
                f"/memory/sessions/{sid}/pin",
                body={"pinned": not pinned},
                timeout=6,
            )
            self.refresh()
            self.select_session(sid)
        except Exception as exc:
            QMessageBox.warning(self, "Pin failed", repr(exc))

    def archive_selected(self):
        sid = self.selected_id()
        if not sid:
            return
        answer = QMessageBox.question(
            self,
            "Archive chat",
            "Archive this chat session? The transcript and memory remain stored.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            _request(
                f"/memory/sessions/{sid}/archive",
                body={"archived": True},
                timeout=8,
            )
            self.refresh()
        except Exception as exc:
            QMessageBox.warning(self, "Archive failed", repr(exc))


def _skill_command(window, command: str):
    return asyncio.create_task(
        _handle_skill_command(window, command)
    )


async def _handle_skill_command(window, command: str):
    parts = command.strip().split(" ", 1)
    argument = parts[1].strip() if len(parts) > 1 else ""
    if "|" not in argument:
        return {
            "ok": False,
            "error": "Use: /skill SKILL NAME | instruction",
        }
    skill, instruction = argument.split("|", 1)
    result = await s91.s9.base._request_async(
        "/tool/execute",
        body={
            "tool": "skills.execute",
            "params": {
                "skill": skill.strip(),
                "instruction": instruction.strip(),
            },
            "approved": False,
        },
        timeout=1800,
    )
    if result.get("requires_approval"):
        if window is None:
            return result
        if not s91.s9.base._confirmation(
            window,
            "Approve skill-guided actions",
            (
                "This inherited skill wants to execute one or more "
                "state-changing RedSight tools.\n\n"
                + s91.s9.base._pretty(result.get("plan", []))[:7000]
                + "\n\nProceed?"
            ),
        ):
            return {"ok": False, "cancelled": True, "plan": result.get("plan")}
        result = await s91.s9.base._request_async(
            "/tool/execute",
            body={
                "tool": "skills.execute",
                "params": {
                    "skill": skill.strip(),
                    "instruction": instruction.strip(),
                },
                "approved": True,
            },
            timeout=1800,
        )
    return result


OLD_HANDLE = s91.s9._handle_stage9_slash


async def handle_stage10_slash(window, command: str):
    stripped = command.strip()
    parts = stripped.split(" ", 1)
    slash = parts[0].lower()

    if slash in {"/skill", "/skillx"}:
        return await _handle_skill_command(window, stripped)

    if slash in {"/help", "/actions"}:
        result = await OLD_HANDLE(window, command)
        text = str(result.get("help", ""))
        additions = (
            "\n/skillx SKILL | INSTRUCTION"
            "\n    Execute an inherited Hermes skill through governed RedSight tools."
        )
        if "/skillx " not in text:
            text += additions
        result["help"] = text
        return result

    return await OLD_HANDLE(window, command)


s91.s9._handle_stage9_slash = handle_stage10_slash


def install_action_hooks(command_center_class):

    if getattr(
        command_center_class,
        "_redsight_stage10_memory_installed",
        False,
    ):
        return

    s91.install_action_hooks(command_center_class)

    previous = command_center_class._send_to_api

    async def wrapped(self, message):

        original = str(message)

        try:
            command_center._redsight_stage10_set_original_message(original)
        except Exception:
            pass

        try:
            return await previous(self, message)
        finally:
            try:
                command_center._redsight_stage10_set_original_message(None)
            except Exception:
                pass
            dock = getattr(self, "_redsight_conversation_memory_dock", None)
            if dock is not None:
                QTimer.singleShot(200, dock.refresh)

    command_center_class._send_to_api = wrapped
    command_center_class._redsight_stage10_memory_installed = True


def attach_action_palette(window, project_root):

    palette = s91.attach_action_palette(
        window,
        project_root,
    )

    if hasattr(
        window,
        "_redsight_conversation_memory_dock",
    ):
        return palette

    dock = ConversationDock(window)

    window.addDockWidget(
        Qt.DockWidgetArea.LeftDockWidgetArea,
        dock,
    )

    heritage = window.findChild(
        QDockWidget,
        "RedSightHermesHeritageDock",
    )

    if heritage is not None:
        try:
            window.tabifyDockWidget(
                heritage,
                dock,
            )
            dock.raise_()
        except Exception:
            pass

    window._redsight_conversation_memory_dock = dock

    return palette
