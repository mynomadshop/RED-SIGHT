from __future__ import annotations

import asyncio
import html
import json
import os
import re
import threading
import time
import traceback
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from PySide6.QtCore import Qt, QTimer, QPoint, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QColor, QPainter, QPen, QKeySequence, QShortcut, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QGridLayout,
    QGroupBox,
    QMessageBox,
    QTabWidget,
    QToolBar,
    QLineEdit,
)

from app.ui import action_palette_stage10 as s10
from app.ui import command_center


ROOT = Path(__file__).resolve().parents[2]
LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
LOG_DIR = LOCALAPPDATA / "RedSight" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
CHAT_LOG = LOG_DIR / "chat-ui-stage102.log"

BACKEND_URL = "http://127.0.0.1:8000"
GATEWAY_URL = "http://127.0.0.1:8765"

RESET_PHRASES = {
    "new chat",
    "new conversation",
    "start a new chat",
    "start a new conversation",
    "start new chat",
    "start new conversation",
    "reset chat",
    "reset conversation",
    "reset our chat",
    "reset our conversation",
    "reset our convo",
    "clear conversation",
    "clear our conversation",
    "start fresh",
    "start fresh chat",
    "start a fresh chat",
    "i want to start a new conversation",
    "i want to start a new chat",
}


def _log_error(context: str, exc: BaseException, extra: str = "") -> None:
    try:
        with CHAT_LOG.open("a", encoding="utf-8") as handle:
            handle.write("\n" + "=" * 88 + "\n")
            handle.write(datetime.now().isoformat(timespec="seconds") + "\n")
            handle.write("CONTEXT: " + context + "\n")
            handle.write("TYPE: " + type(exc).__name__ + "\n")
            detail = str(exc).strip() or repr(exc)
            handle.write("DETAIL: " + detail + "\n")
            if extra:
                handle.write("EXTRA: " + extra[:10000] + "\n")
            handle.write(traceback.format_exc() + "\n")
    except Exception:
        pass


def _error_text(context: str, exc: BaseException, extra: str = "") -> str:
    detail = str(exc).strip() or repr(exc)
    parts = [
        "RedSight could not complete this request.",
        "",
        "Stage: " + context,
        "Error type: " + type(exc).__name__,
        "Detail: " + detail,
    ]
    if extra:
        parts.extend(["", "Additional detail:", extra[:3000]])
    parts.extend(["", "Diagnostic log:", str(CHAT_LOG)])
    return "\n".join(parts)


def _play_tone(kind: str, window=None) -> None:
    if window is not None and not bool(getattr(window, "_redsight_sounds_enabled", True)):
        return

    def worker():
        try:
            import winsound
            if kind == "send":
                winsound.Beep(760, 65)
            elif kind == "receive":
                winsound.Beep(980, 65)
                winsound.Beep(1240, 85)
            elif kind == "error":
                winsound.Beep(330, 90)
                winsound.Beep(220, 130)
        except Exception:
            try:
                QApplication.beep()
            except Exception:
                pass

    threading.Thread(target=worker, daemon=True).start()


def _request(path: str, *, body=None, method=None, timeout=30):
    return s10._request(path, body=body, method=method, timeout=timeout)


async def _request_async(path: str, *, body=None, method=None, timeout=30):
    return await s10.s91.s9.base._request_async(
        path,
        body=body,
        method=method,
        timeout=timeout,
    )


def _extract_backend_message(data: Any) -> str:
    if isinstance(data, str):
        text = data.strip()
        if text:
            return text

    if not isinstance(data, dict):
        raise ValueError(
            "RedSight returned an unsupported response type: "
            + type(data).__name__
        )

    for key in ("message", "response", "content", "output", "text"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            nested = first.get("message")
            if isinstance(nested, dict):
                content = nested.get("content")
                if isinstance(content, str) and content.strip():
                    return content.strip()
            text = first.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()

    nested_data = data.get("data")
    if isinstance(nested_data, dict):
        for key in ("message", "response", "content", "output", "text"):
            value = nested_data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    raise ValueError(
        "RedSight returned HTTP success but no assistant text. "
        "Response keys: " + ", ".join(sorted(str(k) for k in data.keys()))
    )


def _heritage_context(original: str) -> str:
    try:
        legacy = command_center._redsight_heritage_messages(original)
        if isinstance(legacy, list):
            for item in legacy:
                if (
                    isinstance(item, dict)
                    and item.get("role") == "system"
                    and isinstance(item.get("content"), str)
                ):
                    return item["content"][:18000]
    except Exception as exc:
        _log_error("heritage-context", exc)
    return ""


async def _build_messages(original: str, effective: str) -> tuple[str, list[dict[str, str]]]:
    result = await _request_async(
        "/memory/build",
        body={
            "user_message": original,
            "effective_message": effective,
            "heritage_context": _heritage_context(original),
        },
        timeout=20,
    )

    messages = result.get("messages")
    sid = result.get("session_id")
    if not isinstance(messages, list) or not messages:
        raise RuntimeError("Stage 10 memory builder returned no messages.")
    if not isinstance(sid, str) or not sid:
        raise RuntimeError("Stage 10 memory builder returned no session id.")
    return sid, messages


async def _backend_chat(messages: list[dict[str, str]]) -> tuple[str, dict[str, Any]]:
    timeout = httpx.Timeout(600.0, connect=20.0)
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        response = await client.post(
            BACKEND_URL + "/api/v1/chat",
            json={"messages": messages, "stream": False},
        )

    raw = response.text
    if response.status_code < 200 or response.status_code >= 300:
        raise RuntimeError(
            f"RedSight backend HTTP {response.status_code}: "
            + (raw[:4000] if raw else "<empty body>")
        )

    try:
        data = response.json()
    except Exception as exc:
        raise RuntimeError(
            "RedSight backend returned non-JSON data after LM Studio completed. "
            "Body: " + raw[:4000]
        ) from exc

    assistant = _extract_backend_message(data)
    return assistant, data


async def _commit_turn(
    original: str,
    assistant: str,
    effective: str,
    session_id: str | None,
) -> dict[str, Any]:
    body = {
        "user_message": original,
        "assistant_message": assistant,
        "effective_message": effective,
        "session_id": session_id,
    }
    result = await _request_async(
        "/memory/commit",
        body=body,
        timeout=30,
    )
    if not result.get("ok"):
        raise RuntimeError("Persistent memory commit failed: " + json.dumps(result, default=str)[:3000])
    return result


def _normalize(text: str) -> str:
    return " ".join(str(text).strip().lower().split()).strip(" .!?")


def _is_reset_request(text: str) -> bool:
    stripped = str(text).strip()
    lowered = _normalize(stripped)
    if stripped.lower().split(" ", 1)[0] in {"/new", "/reset", "/clear"}:
        return True
    return len(lowered) <= 90 and lowered in RESET_PHRASES


def _action_error(result: Any) -> str | None:
    if not isinstance(result, dict):
        return None
    if result.get("ok") is False:
        error = result.get("error")
        if isinstance(error, str) and error.strip():
            return error.strip()
        detail = result.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
        return "The RedSight action reported failure without a detailed error string."
    return None


def _direct_result(command: str, result: Any) -> str | None:
    slash = command.strip().split(" ", 1)[0].lower()

    error = _action_error(result)
    if error:
        return (
            "RedSight action failed.\n\n"
            "Command: " + command + "\n"
            "Detail: " + error + "\n\n"
            "The full structured result was preserved in the active session."
        )

    if not isinstance(result, dict):
        return str(result)

    if slash in {"/help", "/actions"}:
        return str(result.get("help") or json.dumps(result, indent=2, default=str))

    if slash in {"/skills"}:
        skills = result.get("skills", [])
        lines = [
            f"Inherited skills: {result.get('total', result.get('count', len(skills)))} total",
            f"Returned: {result.get('returned', len(skills))}",
            "",
        ]
        for item in skills[:100]:
            if isinstance(item, dict):
                name = item.get("Name") or item.get("name") or item.get("skill_id") or "skill"
                description = item.get("Description") or item.get("description") or ""
                lines.append(f"• {name}" + (f" — {description}" if description else ""))
        return "\n".join(lines)

    if slash in {"/roots", "/tasks", "/mcp", "/tools"}:
        return json.dumps(result, indent=2, ensure_ascii=False, default=str)

    response = result.get("response")
    if isinstance(response, str) and response.strip():
        return response.strip()

    message = result.get("message")
    if isinstance(message, str) and message.strip():
        return message.strip()

    return None


def _effective_action_message(original: str, command: str, result: Any) -> str:
    packed = json.dumps(result, indent=2, ensure_ascii=False, default=str)
    if len(packed) > 26000:
        packed = packed[:26000] + "\n...<TRUNCATED>"
    return (
        "The user asked RedSight to perform an action. The action has already run. "
        "Use the result below as authoritative. Explain what actually happened, "
        "surface errors and generated paths, and do not claim any additional action "
        "occurred.\n\n"
        "ORIGINAL USER REQUEST:\n" + original + "\n\n"
        "ACTION COMMAND:\n" + command + "\n\n"
        "ACTION RESULT:\n" + packed
    )



class CrosshairLogo(QWidget):
    def __init__(self, size: int = 22, parent=None):
        super().__init__(parent)
        self._size = int(size)
        self.setFixedSize(self._size, self._size)
        self.setToolTip("RedSight")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        center = self.rect().center()
        red = QColor("#FF303A")
        soft = QColor("#FF5961")
        pen = QPen(red)
        pen.setWidthF(max(1.4, self._size / 12.0))
        painter.setPen(pen)
        radius = max(4, int(self._size * 0.30))
        painter.drawEllipse(center, radius, radius)
        pen2 = QPen(soft)
        pen2.setWidthF(max(1.0, self._size / 18.0))
        painter.setPen(pen2)
        inner = max(2, int(self._size * 0.12))
        painter.drawEllipse(center, inner, inner)
        gap = max(2, int(self._size * 0.10))
        arm = max(4, int(self._size * 0.42))
        painter.drawLine(center.x() - arm, center.y(), center.x() - gap, center.y())
        painter.drawLine(center.x() + gap, center.y(), center.x() + arm, center.y())
        painter.drawLine(center.x(), center.y() - arm, center.x(), center.y() - gap)
        painter.drawLine(center.x(), center.y() + gap, center.x(), center.y() + arm)


class MessageBubble(QFrame):
    def __init__(self, role: str, content: str, created_at: float | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("RedSightMessageBubble")
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Minimum)

        user = role == "user"
        assistant = role == "assistant"

        if user:
            background = "qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #164E9A,stop:0.52 #2169C8,stop:1 #123A75)"
            border = "#66A7FF"
            label_color = "#D8EAFF"
            title = "YOUR INPUT"
        elif assistant:
            background = "qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #7B1119,stop:0.48 #B71F2A,stop:1 #651017)"
            border = "#FF5964"
            label_color = "#FFE3E5"
            title = "REDSIGHT RESPONSE"
        else:
            background = "#242029"
            border = "#6E6074"
            label_color = "#D8CDD8"
            title = role.upper()

        self.setStyleSheet(
            f"""
            QFrame#RedSightMessageBubble {{
                background:{background};
                border:1px solid {border};
                border-radius:18px;
            }}
            QLabel {{
                background:transparent;
                border:none;
                color:#FFFFFF;
            }}
            """
        )

        self._assistant_role = assistant
        self._apply_shadow()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(6)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(7)

        if assistant:
            header_row.addWidget(CrosshairLogo(20, self))

        header = QLabel(title)
        header.setStyleSheet(
            f"color:{label_color};font-size:10px;font-weight:900;letter-spacing:1px;"
        )

        if created_at:
            try:
                stamp = datetime.fromtimestamp(float(created_at)).strftime("%H:%M")
                header.setText(title + "  •  " + stamp)
            except Exception:
                pass

        header_row.addWidget(header)
        header_row.addStretch(1)

        body = QLabel(str(content))
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body.setMinimumWidth(220)
        body.setMaximumWidth(860)
        if assistant:
            body.setStyleSheet(
                "color:#FFFFFF;font-family:'Segoe UI';font-size:13px;"
                "font-weight:700;font-style:italic;background:transparent;border:none;"
            )
        else:
            body.setStyleSheet(
                "color:#FFFFFF;font-family:'Segoe UI';font-size:13px;"
                "font-weight:500;background:transparent;border:none;"
            )

        self._body_label = body
        layout.addLayout(header_row)
        layout.addWidget(body)

        self._animated_once = False
        QTimer.singleShot(0, self._animate_in)

    def _apply_shadow(self):
        try:
            shadow = QGraphicsDropShadowEffect(self)
            shadow.setBlurRadius(22 if self._assistant_role else 18)
            shadow.setOffset(0, 4)
            shadow.setColor(QColor(0, 0, 0, 120))
            self.setGraphicsEffect(shadow)
            self._shadow_effect = shadow
        except Exception:
            pass

    def set_body_max_width(self, width: int):
        try:
            self._body_label.setMaximumWidth(max(300, int(width)))
        except Exception:
            pass

    def _animate_in(self):
        if self._animated_once:
            return
        self._animated_once = True
        try:
            # A soft 130 ms fade differentiates incoming/outgoing turns without
            # adding another animation dependency.
            effect = QGraphicsOpacityEffect(self)
            self.setGraphicsEffect(effect)
            animation = QPropertyAnimation(effect, b"opacity", self)
            animation.setDuration(130)
            animation.setStartValue(0.18)
            animation.setEndValue(1.0)
            animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._fade_animation = animation
            animation.finished.connect(self._apply_shadow)
            animation.start()
        except Exception:
            pass


class BubbleConversationView(QFrame):
    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        self._last_signature = None
        self._refreshing = False
        self.setObjectName("RedSightBubbleConversationView")
        self.setStyleSheet(
            """
            QFrame#RedSightBubbleConversationView {
                background:#080D12;
                border:1px solid #263541;
                border-radius:7px;
            }
            """
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setStyleSheet("QScrollArea { background:#080D12;border:none; }")

        host = QWidget()
        host.setStyleSheet("background:#080D12;")
        self.messages_layout = QVBoxLayout(host)
        self.messages_layout.setContentsMargins(12, 12, 12, 12)
        self.messages_layout.setSpacing(10)
        self.messages_layout.addStretch(1)

        self.scroll.setWidget(host)
        outer.addWidget(self.scroll)

        self.timer = QTimer(self)
        self.timer.setInterval(1800)
        self.timer.timeout.connect(self.schedule_refresh)
        self.timer.start()

    def _clear(self):
        while self.messages_layout.count() > 1:
            item = self.messages_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def render(self, messages: list[dict[str, Any]], force=False):
        signature = tuple(
            (str(item.get("id", "")), str(item.get("role", "")), len(str(item.get("content", ""))))
            for item in messages
        )
        if not force and signature == self._last_signature:
            return
        self._last_signature = signature
        self._clear()

        if not messages:
            empty = QLabel(
                "New RedSight conversation\n\n"
                "Your previous sessions remain saved in CHATS & MEMORY."
            )
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet("color:#7F909D;font-size:13px;padding:28px;")
            self.messages_layout.insertWidget(0, empty)
        else:
            index = 0
            for item in messages:
                role = str(item.get("role", "assistant"))
                content = str(item.get("content", ""))
                if not content:
                    continue
                bubble = MessageBubble(
                    role,
                    content,
                    item.get("created_at"),
                    self,
                )
                holder = QWidget()
                row = QHBoxLayout(holder)
                row.setContentsMargins(0, 0, 0, 0)
                if role == "user":
                    row.addStretch(1)
                    row.addWidget(bubble)
                else:
                    row.addWidget(bubble)
                    row.addStretch(1)
                self.messages_layout.insertWidget(index, holder)
                index += 1

        QTimer.singleShot(30, self.scroll_to_bottom)

    def append_local(self, role: str, content: str):
        bubble = MessageBubble(role, content, time.time(), self)
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        if role == "user":
            row.addStretch(1)
            row.addWidget(bubble)
        else:
            row.addWidget(bubble)
            row.addStretch(1)
        self.messages_layout.insertWidget(max(0, self.messages_layout.count() - 1), holder)
        self._last_signature = None
        QTimer.singleShot(30, self.scroll_to_bottom)

    def scroll_to_bottom(self):
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def schedule_refresh(self):
        if self._refreshing:
            return
        self._refreshing = True

        async def job():
            try:
                await self.refresh_async()
            finally:
                self._refreshing = False

        try:
            asyncio.create_task(job())
        except RuntimeError:
            self._refreshing = False

    async def refresh_async(self, force=False):
        try:
            active = await _request_async("/memory/session/active", timeout=5)
            session = active.get("session", {})
            sid = session.get("id")
            if not sid:
                return
            detail = await _request_async(
                f"/memory/sessions/{sid}",
                timeout=8,
            )
            messages = detail.get("messages", [])
            if isinstance(messages, list):
                self.render(messages, force=force)
        except Exception as exc:
            _log_error("bubble-refresh", exc)



SLASH_COMMANDS = [
    ("/new", "New persistent conversation"),
    ("/reset", "Reset conversation context; preserve long-term memory"),
    ("/clear", "Clear current conversation by starting a fresh session"),
    ("/restart", "Restart RedSight backend + action gateway + Command Center"),
    ("/skills", "Browse inherited and integrated skills"),
    ("/tools", "List RedSight integrated tools"),
    ("/actions", "Show the RedSight action command catalog"),
    ("/web ", "Search the web with configured Brave Search"),
    ("/browse ", "Read a public webpage"),
    ("/browser ", "Run approved browser automation"),
    ("/pdf ", "Generate a PDF artifact"),
    ("/agent ", "Run an agentic task"),
    ("/sessions", "List saved RedSight conversations"),
    ("/tasks", "List scheduled / persistent tasks"),
    ("/mcp", "Show migrated MCP server inventory"),
    ("/errors", "Show recent RedSight chat/UI diagnostics"),
    ("/help", "Show all RedSight slash commands"),
]


def _input_text(widget) -> str:
    try:
        if isinstance(widget, QLineEdit):
            return widget.text()
        if isinstance(widget, (QTextEdit, QPlainTextEdit)):
            return widget.toPlainText()
    except Exception:
        pass
    return ""


def _set_input_text(widget, text: str) -> None:
    try:
        s10.s91.s9.base._set_widget_text(widget, text)
    except Exception:
        if isinstance(widget, QLineEdit):
            widget.setText(text)
        elif isinstance(widget, (QTextEdit, QPlainTextEdit)):
            widget.setPlainText(text)
        widget.setFocus()


class SlashCommandPopup(QFrame):
    def __init__(self, window, input_widget):
        super().__init__(window, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.window = window
        self.input_widget = input_widget
        self.setObjectName("RedSightSlashCommandPopup")
        self.setMinimumWidth(440)
        self.setMaximumWidth(620)
        self.setStyleSheet(
            """
            QFrame#RedSightSlashCommandPopup {
                background:#0B1118;
                border:1px solid #FF3944;
                border-radius:12px;
            }
            QLabel {
                color:#EAF2F8;
                background:transparent;
            }
            QListWidget {
                background:#0E1721;
                color:#F6F9FB;
                border:none;
                outline:none;
                padding:4px;
            }
            QListWidget::item {
                padding:8px 10px;
                border-radius:7px;
            }
            QListWidget::item:selected {
                background:#8E1821;
                color:#FFFFFF;
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 9, 10, 10)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(7)
        header.addWidget(CrosshairLogo(21, self))
        title = QLabel("REDSIGHT ACTIONS  •  choose a command")
        title.setStyleSheet("font-weight:900;color:#FF5A63;letter-spacing:0.7px;")
        header.addWidget(title)
        header.addStretch(1)
        layout.addLayout(header)

        self.list = QListWidget()
        self.list.setMaximumHeight(340)
        self.list.itemActivated.connect(self._activate)
        self.list.itemClicked.connect(self._activate)
        layout.addWidget(self.list)

        hint = QLabel("Type after / to filter  •  click a command to insert it in the chat bar")
        hint.setStyleSheet("color:#8293A3;font-size:10px;")
        layout.addWidget(hint)

        self.refresh("/")

    def refresh(self, text: str):
        token = str(text).strip().lower()
        if " " in token:
            token = token.split(" ", 1)[0]
        self.list.clear()
        for command, description in SLASH_COMMANDS:
            base = command.strip()
            if token not in {"", "/"} and not base.lower().startswith(token):
                continue
            item = QListWidgetItem(f"{base:<12}  {description}")
            item.setData(Qt.ItemDataRole.UserRole, command)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)

    def _activate(self, item):
        command = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(command, str):
            return
        _set_input_text(self.input_widget, command)
        self.hide()

    def show_for_input(self):
        self.adjustSize()
        global_pos = self.input_widget.mapToGlobal(QPoint(0, self.input_widget.height() + 6))
        screen = self.input_widget.screen()
        if screen is not None:
            available = screen.availableGeometry()
            if global_pos.y() + self.height() > available.bottom():
                global_pos = self.input_widget.mapToGlobal(QPoint(0, -self.height() - 6))
            max_x = max(available.left(), available.right() - self.width())
            global_pos.setX(min(max(global_pos.x(), available.left()), max_x))
        self.move(global_pos)
        self.show()
        self.raise_()


def _install_slash_popup(window):
    if hasattr(window, "_redsight_slash_popup"):
        return window._redsight_slash_popup

    widget = getattr(window, "_redsight_chat_input", None)
    if widget is None:
        try:
            widget = s10.s91.s9.base._find_chat_input(window)
        except Exception:
            widget = None
    if widget is None:
        return None

    popup = SlashCommandPopup(window, widget)

    def changed(*_args):
        text = _input_text(widget)
        stripped = text.lstrip()
        if stripped.startswith("/") and " " not in stripped and "\n" not in stripped:
            popup.refresh(stripped)
            if popup.list.count():
                popup.show_for_input()
            else:
                popup.hide()
        else:
            popup.hide()

    try:
        widget.textChanged.connect(changed)
    except Exception:
        return None

    window._redsight_chat_input = widget
    window._redsight_slash_popup = popup
    return popup


async def _http_probe(url: str, *, json_expected: bool = False, timeout: float = 4.0):
    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            response = await client.get(url)
        if response.status_code < 200 or response.status_code >= 300:
            return False, f"HTTP {response.status_code}"
        if json_expected:
            try:
                return True, response.json()
            except Exception:
                return True, response.text[:300]
        return True, response.text[:300]
    except Exception as exc:
        return False, type(exc).__name__


async def _gpu_snapshot():
    def run():
        commands = [
            [
                "nvidia-smi",
                "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
                "--format=csv,noheader,nounits",
            ],
            [
                "docker",
                "exec",
                "redsight",
                "nvidia-smi",
                "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
                "--format=csv,noheader,nounits",
            ],
        ]
        last = ""
        for command in commands:
            try:
                proc = subprocess.run(
                    command,
                    cwd=str(ROOT),
                    capture_output=True,
                    text=True,
                    timeout=8,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    return proc.stdout.strip()
                last = proc.stderr.strip() or proc.stdout.strip()
            except Exception as exc:
                last = str(exc)
        return last or "GPU telemetry unavailable"

    return await asyncio.to_thread(run)


class DashboardLivePanel(QGroupBox):
    def __init__(self, window, parent=None):
        super().__init__("REDSIGHT LIVE SYSTEM STATUS", parent)
        self.window = window
        self._busy = False
        self.setObjectName("RedSightLiveDashboard")
        self.setStyleSheet(
            """
            QGroupBox#RedSightLiveDashboard {
                background:#0A121A;
                color:#FFFFFF;
                border:1px solid #7A2830;
                border-radius:10px;
                margin-top:12px;
                padding-top:10px;
                font-weight:900;
            }
            QGroupBox#RedSightLiveDashboard::title {
                subcontrol-origin:margin;
                left:12px;
                padding:0 6px;
                color:#FF4A54;
            }
            QLabel {
                color:#EFF5F9;
                background:#101C26;
                border:1px solid #2F4353;
                border-radius:8px;
                padding:8px;
            }
            """
        )

        grid = QGridLayout(self)
        grid.setContentsMargins(10, 12, 10, 10)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)

        self.labels = {}
        cards = [
            ("backend", "REDSIGHT CORE"),
            ("lmstudio", "LM STUDIO"),
            ("qdrant", "QDRANT"),
            ("gateway", "ACTION / MEMORY"),
            ("gpu0", "GPU 0"),
            ("gpu1", "GPU 1"),
            ("memory", "MEMORY"),
            ("tools", "TOOLS / TASKS"),
        ]
        for index, (key, title) in enumerate(cards):
            label = QLabel(f"{title}\nChecking…")
            label.setMinimumWidth(145)
            label.setWordWrap(True)
            grid.addWidget(label, index // 4, index % 4)
            self.labels[key] = (title, label)

        self.status = QLabel("Dashboard wiring active. Refreshes every 4 seconds.")
        self.status.setStyleSheet(
            "color:#9CB0C0;background:transparent;border:none;padding:2px 4px;font-size:10px;"
        )
        grid.addWidget(self.status, 2, 0, 1, 4)

        self.timer = QTimer(self)
        self.timer.setInterval(4000)
        self.timer.timeout.connect(self.schedule_refresh)
        self.timer.start()
        QTimer.singleShot(300, self.schedule_refresh)

    def _set(self, key: str, text: str, good: bool | None = None):
        title, label = self.labels[key]
        icon = "●" if good is True else ("○" if good is False else "◌")
        label.setText(f"{icon} {title}\n{text}")

    def schedule_refresh(self):
        if self._busy:
            return
        self._busy = True

        async def job():
            try:
                await self.refresh_async()
            finally:
                self._busy = False

        try:
            asyncio.create_task(job())
        except RuntimeError:
            self._busy = False

    async def refresh_async(self):
        backend_task = _http_probe(BACKEND_URL + "/api/v1/health", json_expected=True)
        lm_task = _http_probe("http://127.0.0.1:1234/v1/models", json_expected=True)
        q_task = _http_probe("http://127.0.0.1:6333/readyz")
        gateway_task = _http_probe(GATEWAY_URL + "/memory/status", json_expected=True)
        tools_task = _http_probe(GATEWAY_URL + "/tools", json_expected=True)
        gpu_task = _gpu_snapshot()

        backend, lm, qdrant, gateway, tools, gpu_text = await asyncio.gather(
            backend_task,
            lm_task,
            q_task,
            gateway_task,
            tools_task,
            gpu_task,
        )

        self._set("backend", "Healthy" if backend[0] else str(backend[1]), backend[0])

        if lm[0] and isinstance(lm[1], dict):
            models = lm[1].get("data", [])
            names = [str(x.get("id")) for x in models if isinstance(x, dict) and x.get("id")]
            self._set("lmstudio", (names[0][:34] if names else "Connected"), True)
        else:
            self._set("lmstudio", str(lm[1]), False)

        self._set("qdrant", "Ready" if qdrant[0] else str(qdrant[1]), qdrant[0])

        if gateway[0] and isinstance(gateway[1], dict):
            info = gateway[1]
            self._set(
                "gateway",
                f"Stage {info.get('stage','?')} • active session\n{str(info.get('active_session_id',''))[:16]}",
                True,
            )
            self._set(
                "memory",
                f"{info.get('sessions',0)} sessions • {info.get('messages',0)} messages\n"
                f"{info.get('memories',0)} memories",
                True,
            )
        else:
            self._set("gateway", str(gateway[1]), False)
            self._set("memory", "Gateway unavailable", False)

        if tools[0] and isinstance(tools[1], dict):
            listing = tools[1].get("tools", [])
            count = tools[1].get("count")
            if count is None and isinstance(listing, list):
                count = len(listing)
            tasks = "?"
            if gateway[0] and isinstance(gateway[1], dict):
                tasks = str(gateway[1].get("tasks", "?"))
            self._set("tools", f"{count if count is not None else '?'} tools • {tasks} tasks", True)
        else:
            self._set("tools", "Catalog probe unavailable", None)

        gpu_lines = [line.strip() for line in str(gpu_text).splitlines() if line.strip()]
        for index, key in enumerate(("gpu0", "gpu1")):
            if index < len(gpu_lines):
                parts = [x.strip() for x in gpu_lines[index].split(",")]
                if len(parts) >= 6:
                    text = (
                        f"{parts[0]}\n"
                        f"{parts[1]}% util • {parts[2]}/{parts[3]} MiB • {parts[4]}°C • {parts[5]} W"
                    )
                else:
                    text = gpu_lines[index][:120]
                self._set(key, text, True)
            else:
                self._set(key, "Not detected", False)

        self.status.setText(
            "Live RedSight dashboard • backend, model server, vector DB, action/memory gateway, "
            "dual-GPU telemetry, memory and tools"
        )


def _install_dashboard(window):
    existing = getattr(window, "_redsight_live_dashboard", None)
    if existing is not None:
        return existing

    panel = DashboardLivePanel(window)
    installed = False

    for tabs in window.findChildren(QTabWidget):
        try:
            for index in range(tabs.count()):
                if "dashboard" not in tabs.tabText(index).lower():
                    continue
                page = tabs.widget(index)
                layout = page.layout()
                if layout is not None:
                    try:
                        layout.insertWidget(0, panel)
                    except Exception:
                        layout.addWidget(panel)
                    installed = True
                    break
            if installed:
                break
        except Exception:
            continue

    if not installed:
        dock = QDockWidget("REDSIGHT DASHBOARD", window)
        dock.setObjectName("RedSightLiveDashboardDock")
        dock.setAllowedAreas(
            Qt.DockWidgetArea.TopDockWidgetArea
            | Qt.DockWidgetArea.BottomDockWidgetArea
            | Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
        )
        dock.setWidget(panel)
        window.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, dock)
        window._redsight_live_dashboard_dock = dock

    window._redsight_live_dashboard = panel
    return panel


def _install_branding(window):
    if hasattr(window, "_redsight_brand_toolbar"):
        return window._redsight_brand_toolbar

    window.setWindowTitle("RedSight • Local Intelligence Command Center")
    try:
        app = QApplication.instance()
        if app is not None:
            app.setApplicationName("RedSight")
            app.setApplicationDisplayName("RedSight")
            app.setOrganizationName("RedSight")
        icon_path = ROOT / "assets" / "redsight.ico"
        if icon_path.exists():
            window.setWindowIcon(QIcon(str(icon_path)))
            if app is not None:
                app.setWindowIcon(QIcon(str(icon_path)))
    except Exception:
        pass

    toolbar = QToolBar("RedSight Identity", window)
    toolbar.setObjectName("RedSightBrandToolbar")
    toolbar.setMovable(False)
    toolbar.setFloatable(False)
    toolbar.setStyleSheet(
        """
        QToolBar#RedSightBrandToolbar {
            background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #090D12,stop:0.5 #161016,stop:1 #090D12);
            border-bottom:1px solid #6F1D24;
            spacing:8px;
            padding:5px 10px;
        }
        """
    )
    toolbar.addWidget(CrosshairLogo(30, toolbar))
    name = QLabel("REDSIGHT")
    name.setStyleSheet(
        "color:#FF343F;font-family:'Segoe UI';font-size:20px;font-weight:1000;"
        "letter-spacing:2px;background:transparent;"
    )
    toolbar.addWidget(name)
    subtitle = QLabel("LOCAL INTELLIGENCE COMMAND CENTER")
    subtitle.setStyleSheet(
        "color:#A8B6C2;font-family:'Segoe UI';font-size:10px;font-weight:700;"
        "letter-spacing:1px;background:transparent;padding-left:4px;"
    )
    toolbar.addWidget(subtitle)

    window.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)

    # Visible branding only. Never mutate semantic role names in model payloads.
    for cls in (QLabel, QPushButton, QGroupBox):
        for widget in window.findChildren(cls):
            try:
                text = widget.text() if hasattr(widget, "text") else widget.title()
                if not isinstance(text, str) or not text:
                    continue
                replaced = re.sub(r"\bAssistant\b", "RedSight", text, flags=re.I)
                if replaced != text:
                    if hasattr(widget, "setText"):
                        widget.setText(replaced)
                    elif hasattr(widget, "setTitle"):
                        widget.setTitle(replaced)
            except Exception:
                continue

    for dock in window.findChildren(QDockWidget):
        try:
            title = dock.windowTitle()
            replaced = re.sub(r"\bAssistant\b", "RedSight", title, flags=re.I)
            if replaced != title:
                dock.setWindowTitle(replaced)
        except Exception:
            continue

    window._redsight_brand_toolbar = toolbar
    return toolbar


def _fit_to_screen(window):
    screen = window.screen() or QApplication.primaryScreen()
    if screen is None:
        return
    available = screen.availableGeometry()
    target_w = max(820, int(available.width() * 0.94))
    target_h = max(580, int(available.height() * 0.92))
    window.setMinimumSize(min(820, available.width()), min(580, available.height()))
    if not window.isFullScreen() and not window.isMaximized():
        window.resize(min(window.width(), target_w), min(window.height(), target_h))
        frame = window.frameGeometry()
        frame.moveCenter(available.center())
        window.move(frame.topLeft())

    for dock in window.findChildren(QDockWidget):
        try:
            if dock.minimumWidth() > int(available.width() * 0.33):
                dock.setMinimumWidth(max(250, int(available.width() * 0.25)))
        except Exception:
            pass

    view = getattr(window, "_redsight_bubble_view", None)
    if view is not None:
        try:
            bubble_width = max(360, min(860, int(view.width() * 0.72)))
            for bubble in view.findChildren(MessageBubble):
                bubble.set_body_max_width(bubble_width)
        except Exception:
            pass


def _toggle_fullscreen(window):
    if window.isFullScreen():
        window.showNormal()
        QTimer.singleShot(80, lambda: _fit_to_screen(window))
    else:
        window.showFullScreen()


def _install_adaptive_scaling(window):
    if hasattr(window, "_redsight_scale_timer"):
        return

    try:
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
    except Exception:
        pass

    timer = QTimer(window)
    timer.setInterval(900)
    timer.timeout.connect(lambda: _fit_to_screen(window))
    timer.start()
    window._redsight_scale_timer = timer

    shortcut_full = QShortcut(QKeySequence("F11"), window)
    shortcut_full.activated.connect(lambda: _toggle_fullscreen(window))
    window._redsight_f11_shortcut = shortcut_full

    shortcut_fit = QShortcut(QKeySequence("Ctrl+0"), window)
    shortcut_fit.activated.connect(lambda: _fit_to_screen(window))
    window._redsight_fit_shortcut = shortcut_fit

    QTimer.singleShot(100, lambda: _fit_to_screen(window))

def _is_inside_dock(widget: QWidget) -> bool:
    parent = widget.parentWidget()
    while parent is not None:
        if isinstance(parent, QDockWidget):
            return True
        parent = parent.parentWidget()
    return False


def _find_existing_transcript(window) -> QWidget | None:
    input_widget = None
    try:
        input_widget = s10.s91.s9.base._find_chat_input(window)
    except Exception:
        pass

    candidates: list[tuple[int, QWidget]] = []
    for cls in (QTextBrowser, QTextEdit, QPlainTextEdit):
        for widget in window.findChildren(cls):
            try:
                if widget is input_widget:
                    continue
                if _is_inside_dock(widget):
                    continue
                if widget.objectName() == "RedSightBubbleConversationView":
                    continue

                readonly = isinstance(widget, QTextBrowser) or bool(widget.isReadOnly())
                if not readonly:
                    continue

                name = (widget.objectName() or "").lower()
                score = int(widget.width() * widget.height() / 1000)
                strong = False
                for keyword in ("chat", "conversation", "message", "output", "response", "history"):
                    if keyword in name:
                        score += 5000
                        strong = True

                try:
                    text = widget.toPlainText().lower()
                    if "assistant:" in text or "you:" in text:
                        score += 4000
                        strong = True
                except Exception:
                    pass

                # Never hide an arbitrary dashboard/log widget merely because
                # it is large. If the current main transcript cannot be
                # identified confidently, Stage 10.2 falls back to its own
                # visible REDSIGHT CONVERSATION dock.
                if strong:
                    candidates.append((score, widget))
            except Exception:
                continue

    if not candidates:
        return None
    candidates.sort(key=lambda pair: pair[0], reverse=True)
    return candidates[0][1]


def _install_bubble_view(window):
    existing = getattr(window, "_redsight_bubble_view", None)
    if existing is not None:
        return existing

    candidate = _find_existing_transcript(window)
    bubble = BubbleConversationView(window)

    installed = False
    if candidate is not None:
        try:
            parent = candidate.parentWidget()
            layout = parent.layout() if parent is not None else None
            if layout is not None:
                index = layout.indexOf(candidate)
                if index >= 0:
                    layout.insertWidget(index, bubble)
                    candidate.hide()
                    window._redsight_original_transcript_widget = candidate
                    installed = True
        except Exception as exc:
            _log_error("bubble-replace", exc)

    if not installed:
        dock = QDockWidget("REDSIGHT CONVERSATION", window)
        dock.setObjectName("RedSightBubbleChatDock")
        dock.setAllowedAreas(
            Qt.DockWidgetArea.RightDockWidgetArea
            | Qt.DockWidgetArea.BottomDockWidgetArea
        )
        dock.setWidget(bubble)
        dock.setMinimumWidth(620)
        window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        window._redsight_bubble_chat_dock = dock

    window._redsight_bubble_view = bubble
    QTimer.singleShot(350, bubble.schedule_refresh)
    return bubble



def _add_controls(window, palette):
    layout = palette.layout() if palette is not None else None
    if layout is None:
        return

    new_button = QPushButton("＋ New Chat")
    new_button.setToolTip("Start a clean conversation while preserving previous sessions.")

    reset_button = QPushButton("Reset Chat")
    reset_button.setToolTip("Start a fresh conversation; persistent long-term memory is preserved.")

    restart_button = QPushButton("↻ Restart RedSight")
    restart_button.setToolTip("Restart the RedSight backend, action/memory gateway and Command Center.")

    fit_button = QPushButton("Fit Window")
    fit_button.setToolTip("Adapt the complete RedSight UI to the current screen. Shortcut: Ctrl+0.")

    fullscreen_button = QPushButton("Full Screen")
    fullscreen_button.setToolTip("Toggle RedSight fullscreen. Shortcut: F11.")

    sound_button = QPushButton("🔊 Sounds")
    sound_button.setCheckable(True)
    sound_button.setChecked(True)
    sound_button.setToolTip("Toggle distinct send/receive/error sounds.")

    def insert_command(text: str):
        widget = getattr(window, "_redsight_chat_input", None)
        if widget is not None:
            try:
                _set_input_text(widget, text)
                return
            except Exception:
                pass
        asyncio.create_task(window._send_to_api(text))

    new_button.clicked.connect(lambda: insert_command("/new"))
    reset_button.clicked.connect(lambda: insert_command("/reset"))
    restart_button.clicked.connect(lambda: insert_command("/restart"))
    fit_button.clicked.connect(lambda: _fit_to_screen(window))
    fullscreen_button.clicked.connect(lambda: _toggle_fullscreen(window))

    def toggle_sound(checked: bool):
        window._redsight_sounds_enabled = bool(checked)
        sound_button.setText("🔊 Sounds" if checked else "🔇 Muted")

    sound_button.toggled.connect(toggle_sound)

    for button in (
        new_button,
        reset_button,
        restart_button,
        fit_button,
        fullscreen_button,
        sound_button,
    ):
        layout.addWidget(button)

    window._redsight_stage102_new_button = new_button
    window._redsight_stage102_reset_button = reset_button
    window._redsight_stage102_restart_button = restart_button
    window._redsight_stage102_fit_button = fit_button
    window._redsight_stage102_fullscreen_button = fullscreen_button
    window._redsight_stage102_sound_button = sound_button


async def _new_session(window, original: str) -> str:
    result = await _request_async(
        "/memory/sessions/new",
        body={"title": "New Chat"},
        timeout=12,
    )
    session = result.get("session", {})
    sid = session.get("id")
    if not result.get("ok") or not sid:
        raise RuntimeError("Stage 10 did not create a new session: " + json.dumps(result, default=str)[:3000])

    dock = getattr(window, "_redsight_conversation_memory_dock", None)
    if dock is not None:
        QTimer.singleShot(50, dock.refresh)

    view = getattr(window, "_redsight_bubble_view", None)
    if view is not None:
        view.render([], force=True)
        view.append_local(
            "assistant",
            "New conversation started. Your previous conversation remains saved in CHATS & MEMORY. "
            "Long-term RedSight memory is preserved.",
        )

    return str(sid)


def _session_list_text(result: dict[str, Any]) -> str:
    sessions = result.get("sessions", [])
    lines = ["Saved RedSight sessions:", ""]
    for item in sessions[:50]:
        if not isinstance(item, dict):
            continue
        marker = "●" if item.get("active") else "○"
        pin = " 📌" if item.get("pinned") else ""
        lines.append(
            f"{marker} {item.get('title','New Chat')}{pin} "
            f"— {item.get('message_count',0)} messages"
        )
    return "\n".join(lines)



async def _restart_platform(window, original: str) -> str:
    answer = QMessageBox.question(
        window,
        "Restart RedSight",
        (
            "Restart the complete RedSight runtime now?\n\n"
            "This restarts the RedSight Docker backend, the local action/memory "
            "gateway, and the Command Center UI. Qdrant data, Docker volumes, "
            "conversation history and long-term memory are preserved."
        ),
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    if answer != QMessageBox.StandardButton.Yes:
        text = "RedSight restart cancelled."
        view = getattr(window, "_redsight_bubble_view", None)
        if view is not None:
            view.append_local("assistant", text)
        _play_tone("receive", window)
        return text

    restart_script = ROOT / "RESTART-REDSIGHT.ps1"
    if not restart_script.exists():
        raise RuntimeError("Restart helper is missing: " + str(restart_script))

    assistant = (
        "RedSight restart approved. The current Command Center will close and "
        "the launcher will bring the backend, action/memory gateway and UI back online."
    )

    try:
        session_id, _ = await _build_messages(original, original)
        await _commit_turn(original, assistant, original, session_id)
    except Exception as exc:
        _log_error("restart-memory-commit", exc)

    view = getattr(window, "_redsight_bubble_view", None)
    if view is not None:
        view.append_local("assistant", assistant)
    _play_tone("receive", window)

    flags = (
        getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        | getattr(subprocess, "DETACHED_PROCESS", 0)
        | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    )
    subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(restart_script),
        ],
        cwd=str(ROOT),
        creationflags=flags,
        close_fds=True,
    )

    QTimer.singleShot(900, QApplication.quit)
    return assistant


async def _send_dispatch(self, message):
    original = str(message).strip()
    if not original:
        return None

    if bool(getattr(self, "_redsight_stage102_inflight", False)):
        view = getattr(self, "_redsight_bubble_view", None)
        if view is not None:
            view.append_local(
                "assistant",
                "RedSight is still processing the previous request. Wait for it to finish before sending another action.",
            )
        return None

    self._redsight_stage102_inflight = True
    self._redsight_sounds_enabled = bool(getattr(self, "_redsight_sounds_enabled", True))

    view = getattr(self, "_redsight_bubble_view", None)
    indicator = getattr(self, "_redsight_processing91", None)

    if view is not None:
        view.append_local("user", original)

    _play_tone("send", self)

    if indicator is not None:
        try:
            indicator.begin(s10.s91.description(original))
        except Exception:
            try:
                indicator.begin("PROCESSING")
            except Exception:
                pass

    session_id: str | None = None
    effective = original

    try:
        if _is_reset_request(original):
            await _new_session(self, original)
            _play_tone("receive", self)
            return "New conversation started."

        if original.lower().split(" ", 1)[0] == "/restart":
            return await _restart_platform(self, original)

        if original.lower().startswith("/errors"):
            try:
                text = CHAT_LOG.read_text(encoding="utf-8", errors="replace")
                assistant = (
                    "Recent RedSight UI diagnostics:\n\n"
                    + (text[-12000:] if text.strip() else "No Stage 10.2 UI errors have been logged.")
                )
            except Exception as exc:
                assistant = _error_text("read-diagnostics", exc)
            if view is not None:
                view.append_local("assistant", assistant)
            _play_tone("receive", self)
            return assistant

        if original.lower().startswith("/sessions"):
            sessions = await _request_async("/memory/sessions", timeout=10)
            assistant = _session_list_text(sessions)
            if view is not None:
                view.append_local("assistant", assistant)
            _play_tone("receive", self)
            return assistant

        auto_agent = bool(getattr(self, "_redsight_agent_mode", False))
        is_slash = original.startswith("/")
        action_intent = auto_agent or s10.looks_actionable_stage10(original)

        if is_slash or action_intent:
            command = original if is_slash else "/agent " + original

            if command.split(" ", 1)[0].lower() in {"/new", "/reset", "/clear"}:
                await _new_session(self, original)
                _play_tone("receive", self)
                return "New conversation started."

            result = await s10.handle_stage10_slash(self, command)

            if command.split(" ", 1)[0].lower() in {"/help", "/actions"} and isinstance(result, dict):
                text = str(result.get("help", ""))
                additions = (
                    "\n/new"
                    "\n    Start a clean persistent conversation."
                    "\n/reset"
                    "\n    Start a fresh conversation without deleting long-term memory."
                    "\n/restart"
                    "\n    Restart RedSight core + action/memory gateway + Command Center."
                    "\n/sessions"
                    "\n    List saved RedSight conversations."
                    "\n/errors"
                    "\n    Show detailed Stage 10.2 UI diagnostics."
                )
                if "\n/new" not in text:
                    result["help"] = text + additions

            direct = _direct_result(command, result)
            if direct is not None:
                effective = _effective_action_message(original, command, result)
                sid, _messages = await _build_messages(original, effective)
                session_id = sid
                await _commit_turn(original, direct, effective, session_id)
                if view is not None:
                    await view.refresh_async(force=True)
                _play_tone("receive", self)
                return direct

            effective = _effective_action_message(original, command, result)

        session_id, messages = await _build_messages(original, effective)
        assistant, _data = await _backend_chat(messages)

        await _commit_turn(
            original,
            assistant,
            effective,
            session_id,
        )

        if view is not None:
            await view.refresh_async(force=True)

        dock = getattr(self, "_redsight_conversation_memory_dock", None)
        if dock is not None:
            QTimer.singleShot(100, dock.refresh)

        _play_tone("receive", self)
        return assistant

    except Exception as exc:
        _log_error("chat-dispatch", exc, "User input: " + original[:3000])
        assistant = _error_text("chat/action pipeline", exc)

        try:
            if session_id is None:
                built = await _request_async(
                    "/memory/build",
                    body={
                        "user_message": original,
                        "effective_message": effective,
                        "heritage_context": _heritage_context(original),
                    },
                    timeout=10,
                )
                session_id = built.get("session_id")

            await _commit_turn(
                original,
                assistant,
                effective,
                session_id,
            )
        except Exception as commit_exc:
            _log_error("error-turn-commit", commit_exc)

        if view is not None:
            try:
                await view.refresh_async(force=True)
            except Exception:
                view.append_local("assistant", assistant)

        _play_tone("error", self)
        return assistant

    finally:
        if indicator is not None:
            try:
                indicator.finish()
            except Exception:
                pass
        self._redsight_stage102_inflight = False



def install_action_hooks(command_center_class):
    if getattr(command_center_class, "_redsight_stage102_installed", False):
        return

    # Stage 10.2 keeps the deterministic Stage 10.2 dispatcher design:
    # one user turn -> one final assistant turn. No nested summarization wrappers.
    command_center_class._send_to_api = _send_dispatch
    command_center_class._redsight_stage102_installed = True


def attach_action_palette(window, project_root):
    # Reuse established Stage 10 actions + memory/session dock, without
    # re-installing the older nested send wrappers.
    palette = s10.attach_action_palette(window, project_root)

    window._redsight_sounds_enabled = True

    if not hasattr(window, "_redsight_stage102_controls_added"):
        _add_controls(window, palette)
        window._redsight_stage102_controls_added = True

    _install_bubble_view(window)
    _install_branding(window)
    _install_dashboard(window)
    _install_slash_popup(window)
    _install_adaptive_scaling(window)

    return palette
