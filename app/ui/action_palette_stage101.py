from __future__ import annotations

import asyncio
import html
import json
import os
import re
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from PySide6.QtCore import Qt, QTimer
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
)

from app.ui import action_palette_stage10 as s10
from app.ui import command_center


ROOT = Path(__file__).resolve().parents[2]
LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
LOG_DIR = LOCALAPPDATA / "RedSight" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
CHAT_LOG = LOG_DIR / "chat-ui-stage101.log"

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


class MessageBubble(QFrame):
    def __init__(self, role: str, content: str, created_at: float | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("RedSightMessageBubble")
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Minimum)

        user = role == "user"
        assistant = role == "assistant"

        if user:
            background = "#7B1B22"
            border = "#E84750"
            label_color = "#FFD6D8"
            title = "YOU"
        elif assistant:
            background = "#151D26"
            border = "#50677A"
            label_color = "#FF4A52"
            title = "REDSIGHT"
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
                border-radius:11px;
            }}
            QLabel {{
                background:transparent;
                border:none;
                color:#F6F8FA;
            }}
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(11, 8, 11, 9)
        layout.setSpacing(4)

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

        body = QLabel(str(content))
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body.setMinimumWidth(240)
        body.setMaximumWidth(820)
        body.setStyleSheet(
            "color:#F6F8FA;font-size:13px;line-height:1.25;background:transparent;border:none;"
        )

        layout.addWidget(header)
        layout.addWidget(body)


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
                # identified confidently, Stage 10.1 falls back to its own
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

    sound_button = QPushButton("🔊 Sounds")
    sound_button.setCheckable(True)
    sound_button.setChecked(True)
    sound_button.setToolTip("Toggle distinct send/receive/error sounds.")

    def insert_command(text: str):
        widget = getattr(window, "_redsight_chat_input", None)
        if widget is not None:
            try:
                s10.s91.s9.base._set_widget_text(widget, text)
                return
            except Exception:
                pass
        asyncio.create_task(window._send_to_api(text))

    new_button.clicked.connect(lambda: insert_command("/new"))
    reset_button.clicked.connect(lambda: insert_command("/reset"))

    def toggle_sound(checked: bool):
        window._redsight_sounds_enabled = bool(checked)
        sound_button.setText("🔊 Sounds" if checked else "🔇 Muted")

    sound_button.toggled.connect(toggle_sound)

    layout.addWidget(new_button)
    layout.addWidget(reset_button)
    layout.addWidget(sound_button)

    window._redsight_stage101_new_button = new_button
    window._redsight_stage101_reset_button = reset_button
    window._redsight_stage101_sound_button = sound_button


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


async def _send_dispatch(self, message):
    original = str(message).strip()
    if not original:
        return None

    if bool(getattr(self, "_redsight_stage101_inflight", False)):
        view = getattr(self, "_redsight_bubble_view", None)
        if view is not None:
            view.append_local(
                "assistant",
                "RedSight is still processing the previous request. Wait for it to finish before sending another action.",
            )
        return None

    self._redsight_stage101_inflight = True
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

        if original.lower().startswith("/errors"):
            try:
                text = CHAT_LOG.read_text(encoding="utf-8", errors="replace")
                assistant = (
                    "Recent RedSight UI diagnostics:\n\n"
                    + (text[-12000:] if text.strip() else "No Stage 10.1 UI errors have been logged.")
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
                    "\n/sessions"
                    "\n    List saved RedSight conversations."
                    "\n/errors"
                    "\n    Show detailed Stage 10.1 UI diagnostics."
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
        self._redsight_stage101_inflight = False


def install_action_hooks(command_center_class):
    if getattr(command_center_class, "_redsight_stage101_installed", False):
        return

    # Stage 10.1 deliberately replaces the nested Stage 8/9/9.1/10 send-wrapper
    # chain with one deterministic dispatcher. Action handlers and memory APIs
    # are retained, but each user turn can produce only one final assistant turn.
    command_center_class._send_to_api = _send_dispatch
    command_center_class._redsight_stage101_installed = True


def attach_action_palette(window, project_root):
    # Reuse the established Stage 9.1 action palette, processing indicator,
    # and Stage 10 CHATS & MEMORY dock, but not their nested send wrappers.
    palette = s10.attach_action_palette(window, project_root)

    window._redsight_sounds_enabled = True

    if not hasattr(window, "_redsight_stage101_controls_added"):
        _add_controls(window, palette)
        window._redsight_stage101_controls_added = True

    _install_bubble_view(window)

    return palette
