from __future__ import annotations

import asyncio
import subprocess
import time

from pathlib import Path

from PySide6.QtCore import QTimer

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
)

from app.ui import action_palette_stage9 as s9


ROOT = Path(__file__).resolve().parents[2]

OLD_HANDLE = s9._handle_stage9_slash


def stage91_alive():

    try:

        data = s9.base._json_request(
            "/stage91/status",
            timeout=2,
        )

        return (
            str(
                data.get(
                    "stage",
                    "",
                )
            )
            == "9.1"
        )

    except Exception:

        return False


def ensure_gateway_stage91(
    project_root,
):

    if stage91_alive():
        return True

    root = Path(project_root)

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

    subprocess.Popen(
        [
            str(executable),
            "-m",
            "uvicorn",
            "redsight_actions.gateway_stage91:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8765",
            "--log-level",
            "warning",
        ],
        cwd=str(root),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
    )

    for _ in range(60):

        if stage91_alive():
            return True

        time.sleep(0.25)

    return False


s9.ensure_gateway_stage9 = (
    ensure_gateway_stage91
)

s9.base.ensure_gateway = (
    ensure_gateway_stage91
)


async def execute_long(
    tool,
    params,
):

    return await s9.base._request_async(
        "/tool/execute",
        body={
            "tool": tool,
            "params": params,
            "approved": False,
        },
        timeout=21600,
    )


async def handle_stage91(
    window,
    command,
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

    if slash == "/scan":

        scope = (
            argument
            or "all"
        )

        if scope.lower() in {
            "full",
            "system",
            "computer",
            "entire",
        }:
            scope = "all"

        return await execute_long(
            "system.scan.full",
            {
                "scope": scope,
                "max_files": 0,
                "max_seconds": 0,
            },
        )

    if slash == "/onedrive":

        scan = await execute_long(
            "system.scan.full",
            {
                "scope": "onedrive",
                "max_files": 0,
                "max_seconds": 0,
            },
        )

        if not scan.get(
            "ok",
            False,
        ):
            return scan

        index = await s9.base._request_async(
            "/tool/execute",
            body={
                "tool": "rag.index",
                "params": {
                    "paths": [
                        "onedrive"
                    ],
                    "collection":
                        "knowledge_docs",
                    "project":
                        "onedrive",
                },
                "approved":
                    False,
            },
            timeout=21600,
        )

        return {
            "ok":
                bool(scan.get("ok"))
                and bool(
                    index.get("ok")
                ),
            "scan": scan,
            "index": index,
        }

    if slash == "/agent":

        if not argument:

            return {
                "ok": False,
                "error":
                    "Use /agent GOAL",
            }

        plan = await s9.base._request_async(
            "/agent/plan",
            body={
                "goal":
                    argument,
            },
            timeout=300,
        )

        steps = plan.get(
            "steps",
            [],
        )

        if not steps:
            return plan

        approved = False

        if plan.get(
            "requires_approval"
        ):

            if window is None:

                return {
                    "ok": False,
                    "requires_approval":
                        True,
                    "plan": plan,
                }

            if not s9.base._confirmation(
                window,
                "Approve RedSight agent plan",
                (
                    "This plan contains one or "
                    "more state-changing actions.\n\n"
                    + s9.base._pretty(
                        plan
                    )[:7000]
                    + "\n\nProceed?"
                ),
            ):

                return {
                    "ok": False,
                    "cancelled": True,
                    "plan": plan,
                }

            approved = True

        return await s9.base._request_async(
            "/agent/execute",
            body={
                "goal":
                    argument,
                "plan":
                    steps,
                "approved":
                    approved,
            },
            timeout=21600,
        )

    return await OLD_HANDLE(
        window,
        command,
    )


s9._handle_stage9_slash = (
    handle_stage91
)


class ProcessingIndicator(QFrame):

    def __init__(
        self,
        parent=None,
    ):

        super().__init__(parent)

        self.started = None
        self.description = (
            "PROCESSING"
        )

        self.busy = False

        self.setObjectName(
            "RedSightProcessing91"
        )

        self.setStyleSheet(
            """
            QFrame#RedSightProcessing91 {
                background:#190B0E;
                border:1px solid #D72E38;
                border-radius:6px;
            }

            QLabel {
                color:#FF4C55;
                font-weight:900;
                background:transparent;
            }

            QProgressBar {
                background:#0D141B;
                border:1px solid #6C3137;
                border-radius:4px;
                max-height:10px;
            }

            QProgressBar::chunk {
                background:#E52D37;
            }
            """
        )

        layout = QHBoxLayout(
            self
        )

        layout.setContentsMargins(
            7,
            3,
            7,
            3,
        )

        self.label = QLabel(
            "REDSIGHT • READY"
        )

        self.bar = QProgressBar()

        self.bar.setRange(
            0,
            0,
        )

        self.bar.setMinimumWidth(
            105
        )

        self.bar.setMaximumWidth(
            150
        )

        layout.addWidget(
            self.label
        )

        layout.addWidget(
            self.bar
        )

        self.timer = QTimer(
            self
        )

        self.timer.setInterval(
            1000
        )

        self.timer.timeout.connect(
            self.tick
        )

        self.hide()

    def begin(
        self,
        description,
    ):

        self.description = (
            description
            or "PROCESSING"
        ).upper()

        self.started = (
            time.monotonic()
        )

        self.label.setText(
            "REDSIGHT • "
            + self.description
            + " • 00:00"
        )

        self.show()
        self.timer.start()

    def finish(self):

        self.timer.stop()
        self.hide()
        self.started = None

    def elapsed(self):

        if self.started is None:
            return "00:00"

        seconds = int(
            time.monotonic()
            - self.started
        )

        return (
            f"{seconds // 60:02d}:"
            f"{seconds % 60:02d}"
        )

    def tick(self):

        if self.busy:
            return

        self.busy = True

        asyncio.create_task(
            self.poll()
        )

    async def poll(self):

        try:

            status = await s9.base._request_async(
                "/stage91/progress",
                timeout=2,
            )

            if status.get(
                "active"
            ):

                files = int(
                    status.get(
                        "files_seen",
                        0,
                    )
                )

                dirs = int(
                    status.get(
                        "directories_seen",
                        0,
                    )
                )

                knowledge = int(
                    status.get(
                        "knowledge_candidates",
                        0,
                    )
                )

                self.label.setText(
                    (
                        "REDSIGHT • SCANNING • "
                        f"{files:,} files • "
                        f"{dirs:,} folders • "
                        f"{knowledge:,} knowledge • "
                        + self.elapsed()
                    )
                )

            else:

                self.label.setText(
                    "REDSIGHT • "
                    + self.description
                    + " • "
                    + self.elapsed()
                )

        except Exception:

            self.label.setText(
                "REDSIGHT • "
                + self.description
                + " • "
                + self.elapsed()
            )

        finally:

            self.busy = False


def description(message):

    text = str(message).lower()

    if "scan" in text:
        return "SCANNING SYSTEM"

    if "onedrive" in text:
        return "PROCESSING ONEDRIVE"

    if (
        "index" in text
        or "rag" in text
        or "learn from" in text
    ):
        return "INDEXING KNOWLEDGE"

    if (
        "research" in text
        or "/web" in text
    ):
        return "SEARCHING WEB"

    if "browser" in text:
        return "BROWSER AUTOMATION"

    if "pdf" in text:
        return "GENERATING PDF"

    return "PROCESSING"


def install_action_hooks(
    command_center_class,
):

    if getattr(
        command_center_class,
        "_redsight_stage91_installed",
        False,
    ):
        return

    s9.install_action_hooks(
        command_center_class
    )

    previous = (
        command_center_class
        ._send_to_api
    )

    async def wrapped(
        self,
        message,
    ):

        indicator = getattr(
            self,
            "_redsight_processing91",
            None,
        )

        if indicator is not None:

            indicator.begin(
                description(message)
            )

        try:

            return await previous(
                self,
                message,
            )

        finally:

            if indicator is not None:
                indicator.finish()

    command_center_class._send_to_api = (
        wrapped
    )

    command_center_class._redsight_stage91_installed = (
        True
    )


def attach_action_palette(
    window,
    project_root,
):

    ensure_gateway_stage91(
        project_root
    )

    palette = (
        s9.attach_action_palette(
            window,
            project_root,
        )
    )

    if hasattr(
        window,
        "_redsight_processing91",
    ):
        return palette

    indicator = ProcessingIndicator(
        window
    )

    if palette.layout():

        palette.layout().addWidget(
            indicator
        )

    window._redsight_processing91 = (
        indicator
    )

    return palette
