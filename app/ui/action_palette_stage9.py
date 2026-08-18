from __future__ import annotations

import asyncio
import subprocess
import time
from pathlib import Path


from PySide6.QtWidgets import QPushButton
from PySide6.QtWidgets import QScrollArea


from app.ui import action_palette as base


ROOT = Path(__file__).resolve().parents[2]


def ensure_gateway_stage9(
    project_root,
):

    if base._gateway_alive():

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
                "redsight_actions.gateway_stage9:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8765",
                "--log-level",
                "warning",
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
        40
    ):

        if base._gateway_alive():

            return True

        time.sleep(
            0.25
        )

    return False


# Make the original Stage-8 palette use the Stage-9 gateway whenever
# it attempts to auto-heal the local action service.
base.ensure_gateway = (
    ensure_gateway_stage9
)


def _looks_actionable(
    message: str,
) -> bool:

    text = (
        str(message)
        .strip()
        .lower()
    )

    if not text:

        return False

    # Ordinary conversation must remain ordinary conversation.
    if text in {
        "hi",
        "hello",
        "hey",
        "hello there",
        "thanks",
        "thank you",
        "ok",
        "okay",
    }:

        return False

    direct_phrases = (
        "can you scan",
        "please scan",
        "scan my",
        "scan the",
        "inventory my",
        "index my",
        "index the",
        "learn from my",
        "learn from the",
        "search my files",
        "find my file",
        "find a file",
        "read my file",
        "read the file",
        "browse to",
        "open the website",
        "search the web",
        "research the",
        "research latest",
        "look online",
        "create a pdf",
        "generate a pdf",
        "make a pdf",
        "schedule a",
        "schedule this",
        "set up a cron",
        "create a cron",
        "automate this",
        "automate the",
        "run powershell",
        "write this file",
        "save this file",
    )

    if any(
        phrase in text
        for phrase in direct_phrases
    ):

        return True

    action_verbs = (
        "scan",
        "inventory",
        "index",
        "ingest",
        "research",
        "browse",
        "automate",
        "schedule",
        "download",
        "upload",
        "create",
        "generate",
        "write",
        "read",
        "find",
        "search",
        "organize",
    )

    action_targets = (
        "system",
        "computer",
        "drive",
        "c:",
        "d:",
        "onedrive",
        "one drive",
        "folder",
        "folders",
        "file",
        "files",
        "website",
        "web",
        "browser",
        "pdf",
        "cron",
        "task",
        "tasks",
        "powershell",
    )

    return (
        any(
            verb in text
            for verb in action_verbs
        )
        and
        any(
            target in text
            for target in action_targets
        )
    )


async def _handle_stage9_slash(
    window,
    command: str,
):

    stripped = (
        command.strip()
    )

    parts = stripped.split(
        " ",
        1,
    )

    slash = parts[
        0
    ].lower()

    argument = (
        parts[1].strip()
        if len(parts) > 1
        else ""
    )

    if slash == "/skills":

        return await base._execute_tool(
            "skills.list",
            {
                "query":
                    argument,

                "limit":
                    100,
            },
        )

    if slash == "/roots":

        return await base._execute_tool(
            "system.roots",
            {},
        )

    if slash == "/scan":

        scope = (
            argument
            or "all"
        )

        return await base._execute_tool(
            "system.scan",
            {
                "scope":
                    scope,

                "max_files":
                    250000,

                "max_seconds":
                    300,
            },
        )

    if slash == "/onedrive":

        scan = await base._execute_tool(
            "system.scan",
            {
                "scope":
                    "onedrive",

                "max_files":
                    250000,

                "max_seconds":
                    300,
            },
        )

        index = await base._execute_tool(
            "rag.index",
            {
                "paths": [
                    "onedrive"
                ],

                "collection":
                    "knowledge_docs",

                "project":
                    "onedrive",
            },
        )

        return {
            "ok":
                bool(
                    scan.get(
                        "ok",
                        False,
                    )
                )
                and bool(
                    index.get(
                        "ok",
                        False,
                    )
                ),

            "scan":
                scan,

            "index":
                index,
        }

    if slash in {
        "/index",
        "/learn",
    }:

        paths = [
            argument
            or "onedrive"
        ]

        return await base._execute_tool(
            "rag.index",
            {
                "paths":
                    paths,

                "collection":
                    "knowledge_docs",

                "project":
                    "personal-knowledge",
            },
        )

    if slash in {
        "/help",
        "/actions",
    }:

        original = await base._handle_slash(
            window,
            command,
        )

        text = str(
            original.get(
                "help",
                ""
            )
        )

        text += (
            "\n/skills [QUERY]"
            "\n/roots"
            "\n/scan [all|user|onedrive|d|PATH]"
            "\n/onedrive"
            "\n/index [onedrive|user|d|PATH]"
            "\n/learn [onedrive|user|d|PATH]"
        )

        original[
            "help"
        ] = text

        return original

    return await base._handle_slash(
        window,
        command,
    )


def install_action_hooks(
    command_center_class,
):

    if getattr(
        command_center_class,
        "_redsight_stage9_hooks_installed",
        False,
    ):

        return

    original_send = (
        command_center_class
        ._send_to_api
    )

    async def stage9_send(
        self,
        message,
    ):

        text = str(
            message
        )

        stripped = (
            text.strip()
        )

        auto_agent = bool(
            getattr(
                self,
                "_redsight_agent_mode",
                False,
            )
        )

        is_slash = stripped.startswith(
            "/"
        )

        action_intent = (
            auto_agent
            or
            _looks_actionable(
                stripped
            )
        )

        if (
            is_slash
            or action_intent
        ):

            # Self-heal the gateway before issuing an action.
            gateway_ok = await asyncio.to_thread(
                ensure_gateway_stage9,
                ROOT,
            )

            if not gateway_ok:

                result = {
                    "ok":
                        False,

                    "error":
                        (
                            "RedSight Action Gateway could not "
                            "be started on 127.0.0.1:8765."
                        ),
                }

                return await original_send(
                    self,
                    base._summary_prompt(
                        stripped,
                        result,
                    ),
                )

            if is_slash:

                command = stripped

            else:

                command = (
                    "/agent "
                    + stripped
                )

            try:

                result = await _handle_stage9_slash(
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
                base._summary_prompt(
                    command,
                    result,
                ),
            )

        # Plain chat still goes straight to the existing RedSight
        # conversational path.
        return await original_send(
            self,
            message,
        )

    command_center_class._send_to_api = (
        stage9_send
    )

    command_center_class._redsight_stage9_hooks_installed = (
        True
    )


def attach_action_palette(
    window,
    project_root,
):

    palette = base.attach_action_palette(
        window,
        project_root,
    )

    if getattr(
        window,
        "_redsight_stage9_buttons_added",
        False,
    ):

        return palette

    scroll = palette.findChild(
        QScrollArea
    )

    if (
        scroll is not None
        and scroll.widget() is not None
        and scroll.widget().layout() is not None
    ):

        layout = (
            scroll.widget()
            .layout()
        )

        def target():

            widget = getattr(
                window,
                "_redsight_chat_input",
                None,
            )

            if widget is not None:

                return widget

            return None

        def add_button(
            label: str,
            command: str,
        ):

            button = QPushButton(
                label
            )

            def clicked():

                widget = target()

                if widget is not None:

                    base._set_widget_text(
                        widget,
                        command,
                    )

                else:

                    asyncio.create_task(
                        window._send_to_api(
                            command
                        )
                    )

            button.clicked.connect(
                clicked
            )

            layout.addWidget(
                button
            )

        add_button(
            "Scan",
            "/scan all",
        )

        add_button(
            "OneDrive",
            "/onedrive",
        )

        add_button(
            "Index",
            "/index onedrive",
        )

        add_button(
            "Skills",
            "/skills",
        )

        add_button(
            "Roots",
            "/roots",
        )

    window._redsight_stage9_buttons_added = (
        True
    )

    return palette
