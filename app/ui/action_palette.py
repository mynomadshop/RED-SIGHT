from __future__ import annotations

import asyncio
import json
import subprocess
import time
import urllib.error
import urllib.request

from pathlib import Path

from PySide6.QtCore import QObject
from PySide6.QtCore import Qt

from PySide6.QtWidgets import QFrame
from PySide6.QtWidgets import QHBoxLayout
from PySide6.QtWidgets import QInputDialog
from PySide6.QtWidgets import QLabel
from PySide6.QtWidgets import QLineEdit
from PySide6.QtWidgets import QMessageBox
from PySide6.QtWidgets import QPlainTextEdit
from PySide6.QtWidgets import QPushButton
from PySide6.QtWidgets import QScrollArea
from PySide6.QtWidgets import QTextEdit
from PySide6.QtWidgets import QToolBar
from PySide6.QtWidgets import QWidget


GATEWAY = (
    "http://127.0.0.1:8765"
)


def _json_request(
    path: str,
    *,
    body=None,
    method=None,
    timeout=180,
):

    url = (
        GATEWAY
        + path
    )

    data = None

    headers = {}

    if body is not None:

        data = json.dumps(
            body
        ).encode(
            "utf-8"
        )

        headers[
            "Content-Type"
        ] = "application/json"

    if method is None:

        method = (
            "POST"
            if body is not None
            else "GET"
        )

    request = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method,
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=timeout,
        ) as response:

            raw = response.read().decode(
                "utf-8",
                errors="replace",
            )

            return (
                json.loads(
                    raw
                )
                if raw.strip()
                else {}
            )

    except urllib.error.HTTPError as exc:

        raw = exc.read().decode(
            "utf-8",
            errors="replace",
        )

        try:

            return json.loads(
                raw
            )

        except Exception:

            return {
                "ok":
                    False,

                "error":
                    raw
                    or str(
                        exc
                    ),
            }


async def _request_async(
    path: str,
    *,
    body=None,
    method=None,
    timeout=180,
):

    return await asyncio.to_thread(
        _json_request,
        path,
        body=body,
        method=method,
        timeout=timeout,
    )


def _gateway_alive():

    try:

        result = _json_request(
            "/health",
            timeout=2,
        )

        return (
            result.get(
                "status"
            )
            == "healthy"
        )

    except Exception:

        return False


def ensure_gateway(
    project_root: Path,
):

    if _gateway_alive():

        return True

    root = Path(
        project_root
    )

    pythonw = (
        root
        / ".venv-actions"
        / "Scripts"
        / "pythonw.exe"
    )

    python = (
        root
        / ".venv-actions"
        / "Scripts"
        / "python.exe"
    )

    executable = (
        pythonw
        if pythonw.exists()
        else python
    )

    if not executable.exists():

        return False

    flags = getattr(
        subprocess,
        "CREATE_NO_WINDOW",
        0,
    )

    try:

        subprocess.Popen(
            [
                str(
                    executable
                ),
                "-m",
                "uvicorn",
                "redsight_actions.gateway:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8765",
            ],
            cwd=str(
                root
            ),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )

    except Exception:

        return False

    for _ in range(
        30
    ):

        if _gateway_alive():

            return True

        time.sleep(
            0.25
        )

    return False


def _confirmation(
    window,
    title: str,
    text: str,
) -> bool:

    answer = QMessageBox.question(
        window,
        title,
        text,
        QMessageBox.StandardButton.Yes
        | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )

    return (
        answer
        == QMessageBox.StandardButton.Yes
    )


def _pretty(
    value,
):

    return json.dumps(
        value,
        indent=2,
        ensure_ascii=False,
        default=str,
    )


def _summary_prompt(
    original_command: str,
    result,
):

    serialized = _pretty(
        result
    )

    if len(
        serialized
    ) > 18000:

        serialized = (
            serialized[:18000]
            + "\n...<TRUNCATED>"
        )

    return (
        "A RedSight local action has already been executed. "
        "Present its result clearly to the user. "
        "Do not pretend any additional action occurred. "
        "Mention generated file paths, failed steps, or required configuration "
        "when relevant.\n\n"
        "ORIGINAL ACTION COMMAND:\n"
        + original_command
        + "\n\nACTION RESULT:\n"
        + serialized
    )


def _parse_json(
    raw: str,
):

    try:

        value = json.loads(
            raw
        )

        if isinstance(
            value,
            dict,
        ):

            return value

    except Exception:

        pass

    return {}


async def _execute_tool(
    tool: str,
    params: dict,
    *,
    approved=False,
):

    return await _request_async(
        "/tool/execute",
        body={
            "tool":
                tool,

            "params":
                params,

            "approved":
                approved,
        },
        timeout=300,
    )


async def _handle_slash(
    window,
    command: str,
):

    stripped = command.strip()

    parts = stripped.split(
        " ",
        1,
    )

    slash = parts[0].lower()

    argument = (
        parts[1].strip()
        if len(parts) > 1
        else ""
    )

    if slash in {
        "/help",
        "/actions",
    }:

        return {
            "ok":
                True,

            "help":
                (
                    "/web QUERY\n"
                    "/browse URL\n"
                    "/browser JSON\n"
                    "/pdf TITLE | CONTENT\n"
                    "/skill SKILL | INSTRUCTION\n"
                    "/agent GOAL\n"
                    "/task CRON | TOOL | JSON_PARAMS\n"
                    "/tasks\n"
                    "/fsread PATH\n"
                    "/fswrite PATH | CONTENT\n"
                    "/mcp\n"
                    "/mcp-test SERVER\n"
                    "/tools\n"
                    "/ps POWERSHELL_COMMAND\n"
                    "/brave"
                ),
        }

    if slash == "/web":

        return await _execute_tool(
            "web.search",
            {
                "query":
                    argument,

                "count":
                    10,
            },
        )

    if slash == "/browse":

        return await _execute_tool(
            "browser.read",
            {
                "url":
                    argument,
            },
        )

    if slash == "/browser":

        payload = _parse_json(
            argument
        )

        if not payload:

            return {
                "ok":
                    False,

                "error":
                    (
                        "Use /browser with JSON, for example "
                        '{"url":"https://example.com","actions":[...]}'
                    ),
            }

        if not _confirmation(
            window,
            "Approve browser automation",
            (
                "RedSight is about to interact with a website.\n\n"
                + _pretty(
                    payload
                )[:6000]
                + "\n\nProceed?"
            ),
        ):

            return {
                "ok":
                    False,

                "cancelled":
                    True,
            }

        return await _execute_tool(
            "browser.automate",
            payload,
            approved=True,
        )

    if slash == "/pdf":

        if "|" in argument:

            title, content = (
                argument.split(
                    "|",
                    1,
                )
            )

        else:

            title = (
                "RedSight Report"
            )

            content = argument

        return await _execute_tool(
            "pdf.generate",
            {
                "title":
                    title.strip(),

                "content":
                    content.strip(),
            },
        )

    if slash == "/skill":

        if "|" not in argument:

            return {
                "ok":
                    False,

                "error":
                    (
                        "Use: /skill SKILL NAME | instruction"
                    ),
            }

        skill, instruction = (
            argument.split(
                "|",
                1,
            )
        )

        return await _execute_tool(
            "skills.invoke",
            {
                "skill":
                    skill.strip(),

                "instruction":
                    instruction.strip(),
            },
        )

    if slash == "/tools":

        return await _request_async(
            "/tools",
            timeout=20,
        )

    if slash == "/mcp":

        return await _execute_tool(
            "mcp.list",
            {},
        )

    if slash == "/mcp-test":

        return await _execute_tool(
            "mcp.test",
            {
                "name":
                    argument,
            },
        )

    if slash == "/fsread":

        return await _execute_tool(
            "filesystem.read",
            {
                "path":
                    argument,
            },
        )

    if slash == "/fswrite":

        if "|" not in argument:

            return {
                "ok":
                    False,

                "error":
                    (
                        "Use: /fswrite C:\\path\\file.txt | content"
                    ),
            }

        path, content = (
            argument.split(
                "|",
                1,
            )
        )

        if not _confirmation(
            window,
            "Approve filesystem write",
            (
                "RedSight will write this file:\n\n"
                + path.strip()
                + "\n\nProceed?"
            ),
        ):

            return {
                "ok":
                    False,

                "cancelled":
                    True,
            }

        return await _execute_tool(
            "filesystem.write",
            {
                "path":
                    path.strip(),

                "content":
                    content,

                "overwrite":
                    False,
            },
            approved=True,
        )

    if slash in {
        "/task",
        "/cron",
    }:

        fields = [
            item.strip()
            for item in argument.split(
                "|",
                2,
            )
        ]

        if len(
            fields
        ) < 3:

            return {
                "ok":
                    False,

                "error":
                    (
                        "Use: /task CRON | TOOL | JSON_PARAMS\n"
                        "Example: /task 0 9 * * 1-5 | web.search | "
                        '{"query":"AI news"}'
                    ),
            }

        cron, tool, raw_params = fields

        params = _parse_json(
            raw_params
        )

        if not _confirmation(
            window,
            "Approve scheduled task",
            (
                "Create persistent RedSight task?\n\n"
                "Cron: "
                + cron
                + "\nTool: "
                + tool
                + "\nParameters:\n"
                + _pretty(
                    params
                )[:5000]
            ),
        ):

            return {
                "ok":
                    False,

                "cancelled":
                    True,
            }

        return await _request_async(
            "/tasks/create",
            body={
                "name":
                    "RedSight "
                    + tool,

                "tool":
                    tool,

                "params":
                    params,

                "cron":
                    cron,

                "approved":
                    True,
            },
            timeout=30,
        )

    if slash == "/tasks":

        return await _request_async(
            "/tasks",
            timeout=20,
        )

    if slash == "/ps":

        if not _confirmation(
            window,
            "Approve PowerShell",
            (
                "RedSight is about to execute this PowerShell command:\n\n"
                + argument[:7000]
                + "\n\nProceed?"
            ),
        ):

            return {
                "ok":
                    False,

                "cancelled":
                    True,
            }

        return await _execute_tool(
            "system.powershell",
            {
                "command":
                    argument,
            },
            approved=True,
        )

    if slash == "/agent":

        if not argument:

            return {
                "ok":
                    False,

                "error":
                    "Use /agent GOAL",
            }

        plan = await _request_async(
            "/agent/plan",
            body={
                "goal":
                    argument,
            },
            timeout=180,
        )

        steps = plan.get(
            "steps",
            []
        )

        if not steps:

            return plan

        approved = False

        if plan.get(
            "requires_approval"
        ):

            detail = _pretty(
                plan
            )

            if not _confirmation(
                window,
                "Approve RedSight agent plan",
                (
                    "The agent plan contains one or more actions "
                    "that can modify local/external state.\n\n"
                    + detail[:7000]
                    + "\n\nApprove this plan?"
                ),
            ):

                return {
                    "ok":
                        False,

                    "cancelled":
                        True,

                    "plan":
                        plan,
                }

            approved = True

        return await _request_async(
            "/agent/execute",
            body={
                "goal":
                    argument,

                "plan":
                    steps,

                "approved":
                    approved,
            },
            timeout=600,
        )

    if slash == "/brave":

        return {
            "ok":
                True,

            "message":
                (
                    "Use the Brave Key button in the ACTIONS bar "
                    "to configure the API key securely."
                ),
        }

    return {
        "ok":
            False,

        "error":
            "Unknown RedSight slash action: "
            + slash,

        "hint":
            "Use /help",
    }


def install_action_hooks(
    command_center_class,
):

    if getattr(
        command_center_class,
        "_redsight_action_hooks_installed",
        False,
    ):

        return

    original_send = (
        command_center_class
        ._send_to_api
    )

    async def wrapped_send(
        self,
        message,
    ):

        text = str(
            message
        )

        auto_agent = bool(
            getattr(
                self,
                "_redsight_agent_mode",
                False,
            )
        )

        if (
            text.strip().startswith(
                "/"
            )
            or auto_agent
        ):

            command = text.strip()

            if (
                auto_agent
                and not command.startswith(
                    "/"
                )
            ):

                command = (
                    "/agent "
                    + command
                )

            try:

                result = await _handle_slash(
                    self,
                    command,
                )

            except Exception as exc:

                result = {
                    "ok":
                        False,

                    "error":
                        repr(
                            exc
                        ),
                }

            return await original_send(
                self,
                _summary_prompt(
                    command,
                    result,
                ),
            )

        return await original_send(
            self,
            message,
        )

    command_center_class._send_to_api = (
        wrapped_send
    )

    command_center_class._redsight_action_hooks_installed = (
        True
    )


def _set_widget_text(
    widget,
    text: str,
):

    if isinstance(
        widget,
        QLineEdit,
    ):

        widget.setText(
            text
        )

    elif isinstance(
        widget,
        (
            QTextEdit,
            QPlainTextEdit,
        ),
    ):

        widget.setPlainText(
            text
        )

    widget.setFocus()


def _find_chat_input(
    window,
):

    candidates = []

    for cls in (
        QLineEdit,
        QTextEdit,
        QPlainTextEdit,
    ):

        for widget in window.findChildren(
            cls
        ):

            try:

                if isinstance(
                    widget,
                    QLineEdit,
                ) and widget.echoMode() == QLineEdit.EchoMode.Password:

                    continue

                if isinstance(
                    widget,
                    (
                        QTextEdit,
                        QPlainTextEdit,
                    ),
                ) and widget.isReadOnly():

                    continue

                name = (
                    widget.objectName()
                    or ""
                ).lower()

                placeholder = ""

                if hasattr(
                    widget,
                    "placeholderText"
                ):

                    placeholder = (
                        widget.placeholderText()
                        or ""
                    ).lower()

                combined = (
                    name
                    + " "
                    + placeholder
                )

                if (
                    "heritage"
                    in combined
                    or "inherited hermes"
                    in combined
                ):

                    continue

                score = 0

                for keyword in (
                    "chat",
                    "message",
                    "prompt",
                    "input",
                    "ask",
                ):

                    if keyword in combined:

                        score += 100

                if widget.width() >= 350:

                    score += 20

                if widget.isVisible():

                    score += 10

                candidates.append(
                    (
                        score,
                        widget.width(),
                        widget,
                    )
                )

            except Exception:

                continue

    if not candidates:

        return None

    candidates.sort(
        key=lambda item:
            (
                item[0],
                item[1],
            ),
        reverse=True,
    )

    return candidates[0][2]


def configure_brave_key(
    window,
):

    key, accepted = QInputDialog.getText(
        window,
        "Brave Search API Key",
        (
            "Enter your Brave Search API key.\n"
            "It is stored in the private local RedSight actions directory."
        ),
        QLineEdit.EchoMode.Password,
    )

    if not accepted:

        return

    key = key.strip()

    if not key:

        return

    result = _json_request(
        "/config/brave",
        body={
            "api_key":
                key,
        },
        timeout=15,
    )

    if result.get(
        "ok"
    ):

        QMessageBox.information(
            window,
            "Brave Search",
            "Brave Search API key configured.",
        )

    else:

        QMessageBox.warning(
            window,
            "Brave Search",
            (
                "Could not configure Brave Search:\n\n"
                + _pretty(
                    result
                )
            ),
        )


def attach_action_palette(
    window,
    project_root,
):

    if hasattr(
        window,
        "_redsight_action_palette",
    ):

        return window._redsight_action_palette

    root = Path(
        project_root
    )

    ensure_gateway(
        root
    )

    window._redsight_agent_mode = (
        False
    )

    palette = QFrame(
        window
    )

    palette.setObjectName(
        "RedSightActionPalette"
    )

    palette.setMaximumHeight(
        58
    )

    palette.setStyleSheet(
        """
        QFrame#RedSightActionPalette {
            background-color:#0A0F15;
            border:1px solid #7D2228;
            border-radius:7px;
        }

        QLabel {
            color:#FF3A43;
            font-weight:900;
            padding-left:6px;
        }

        QPushButton {
            background-color:#191F27;
            color:#F4F7FA;
            border:1px solid #495865;
            border-radius:6px;
            padding:5px 9px;
            font-weight:650;
        }

        QPushButton:hover {
            background-color:#8F2027;
            border-color:#E54A51;
        }

        QPushButton:checked {
            background-color:#B0222B;
            color:white;
            border:1px solid #FF5A62;
        }

        QLineEdit {
            background-color:#101820;
            color:#FFFFFF;
            border:1px solid #586C7C;
            border-radius:6px;
            padding:6px;
        }
        """
    )

    main_layout = QHBoxLayout(
        palette
    )

    main_layout.setContentsMargins(
        5,
        4,
        5,
        4,
    )

    label = QLabel(
        "⚡ ACTIONS"
    )

    main_layout.addWidget(
        label
    )

    scroll = QScrollArea()

    scroll.setWidgetResizable(
        True
    )

    scroll.setHorizontalScrollBarPolicy(
        Qt.ScrollBarPolicy.ScrollBarAsNeeded
    )

    scroll.setVerticalScrollBarPolicy(
        Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )

    scroll.setFrameShape(
        QFrame.Shape.NoFrame
    )

    scroll.setMaximumHeight(
        44
    )

    button_host = QWidget()

    buttons_layout = QHBoxLayout(
        button_host
    )

    buttons_layout.setContentsMargins(
        1,
        1,
        1,
        1,
    )

    buttons_layout.setSpacing(
        4
    )

    scroll.setWidget(
        button_host
    )

    main_layout.addWidget(
        scroll,
        1,
    )

    command_box = QLineEdit()

    command_box.setPlaceholderText(
        "/web, /agent, /task..."
    )

    command_box.setMinimumWidth(
        210
    )

    command_box.setMaximumWidth(
        320
    )

    main_layout.addWidget(
        command_box
    )

    run_button = QPushButton(
        "RUN"
    )

    main_layout.addWidget(
        run_button
    )

    chat_input = _find_chat_input(
        window
    )

    window._redsight_chat_input = (
        chat_input
    )

    def target_widget():

        return (
            window._redsight_chat_input
            or command_box
        )

    def prefix(
        text,
    ):

        _set_widget_text(
            target_widget(),
            text,
        )

    def add_button(
        title,
        command_prefix=None,
    ):

        button = QPushButton(
            title
        )

        if command_prefix is not None:

            button.clicked.connect(
                lambda _checked=False, p=command_prefix:
                    prefix(
                        p
                    )
            )

        buttons_layout.addWidget(
            button
        )

        return button

    auto = add_button(
        "AUTO AGENT"
    )

    auto.setCheckable(
        True
    )

    def set_agent_mode(
        enabled,
    ):

        window._redsight_agent_mode = bool(
            enabled
        )

    auto.toggled.connect(
        set_agent_mode
    )

    add_button(
        "Web",
        "/web ",
    )

    add_button(
        "Browse",
        "/browse ",
    )

    add_button(
        "Browser Auto",
        '/browser {"url":"","actions":[]}',
    )

    add_button(
        "PDF",
        "/pdf Report | ",
    )

    add_button(
        "Skill",
        "/skill ",
    )

    add_button(
        "Agent",
        "/agent ",
    )

    add_button(
        "Cron",
        "/task 0 9 * * * | web.search | "
        '{"query":""}',
    )

    add_button(
        "Tasks",
        "/tasks",
    )

    add_button(
        "C:",
        "/fsread C:\\",
    )

    add_button(
        "D:",
        "/fsread D:\\",
    )

    add_button(
        "MCP",
        "/mcp",
    )

    add_button(
        "Tools",
        "/tools",
    )

    brave = add_button(
        "Brave Key"
    )

    brave.clicked.connect(
        lambda:
            configure_brave_key(
                window
            )
    )

    def submit_palette_command():

        text = (
            command_box.text()
            .strip()
        )

        if not text:

            return

        asyncio.create_task(
            window._send_to_api(
                text
            )
        )

    run_button.clicked.connect(
        submit_palette_command
    )

    command_box.returnPressed.connect(
        submit_palette_command
    )

    attached = False

    if chat_input is not None:

        try:

            parent = chat_input.parentWidget()

            layout = (
                parent.layout()
                if parent
                else None
            )

            if (
                layout is not None
                and hasattr(
                    layout,
                    "insertWidget"
                )
            ):

                index = layout.indexOf(
                    chat_input
                )

                if index < 0:

                    index = 0

                layout.insertWidget(
                    index,
                    palette,
                )

                attached = True

        except Exception:

            attached = False

    if not attached:

        toolbar = QToolBar(
            "RedSight Actions",
            window,
        )

        toolbar.setObjectName(
            "RedSightActionsToolbar"
        )

        toolbar.setMovable(
            False
        )

        toolbar.addWidget(
            palette
        )

        window.addToolBar(
            Qt.ToolBarArea.BottomToolBarArea,
            toolbar,
        )

        window._redsight_action_toolbar = (
            toolbar
        )

    window._redsight_action_palette = (
        palette
    )

    return palette
