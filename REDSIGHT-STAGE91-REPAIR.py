from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess
import time
from pathlib import Path


ROOT = Path(r"C:\Users\walim\RedSight")

G9 = ROOT / "redsight_actions" / "gateway_stage9.py"
G91 = ROOT / "redsight_actions" / "gateway_stage91.py"

P9 = ROOT / "app" / "ui" / "action_palette_stage9.py"
P91 = ROOT / "app" / "ui" / "action_palette_stage91.py"

LAUNCHER = ROOT / "launch_redsight_command_center.py"

ACTION_PY = ROOT / ".venv-actions" / "Scripts" / "python.exe"
ACTION_PYW = ROOT / ".venv-actions" / "Scripts" / "pythonw.exe"
UI_PY = ROOT / ".venv-ui" / "Scripts" / "python.exe"

STAMP = time.strftime("%Y%m%d-%H%M%S")

BACKUP = (
    ROOT
    / ".repair-backups"
    / ("stage91-repair-" + STAMP)
)

BACKUP.mkdir(
    parents=True,
    exist_ok=True,
)


def log(text=""):
    print(text, flush=True)


def read(path):
    return Path(path).read_text(
        encoding="utf-8-sig",
        errors="replace",
    )


def write(path, text):
    Path(path).write_text(
        text,
        encoding="utf-8",
    )


def backup(path):
    path = Path(path)

    if path.exists():
        shutil.copy2(
            path,
            BACKUP / (path.name + ".before"),
        )


for required in (
    G9,
    P9,
    LAUNCHER,
    ACTION_PY,
    UI_PY,
):

    if not required.exists():

        raise RuntimeError(
            "Missing required Stage-9 component: "
            + str(required)
        )


for path in (
    G91,
    P91,
    LAUNCHER,
):

    backup(path)


# ==============================================================
# STAGE 9.1 GATEWAY OVERLAY
# ==============================================================

gateway_source = r'''
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time

from collections import Counter
from pathlib import Path
from typing import Any

from redsight_actions import gateway_stage9 as s9


app = s9.app
base = s9.base

OLD_EXECUTE = base.execute_tool_core
OLD_PLAN = base.create_agent_plan


base.TOOL_SPECS["system.scan.full"] = {
    "description":
        (
            "Complete read-only filesystem inventory without "
            "the Stage-9 250000-file default limit."
        ),

    "risk":
        "read",

    "approval":
        False,

    "agent":
        True,

    "params":
        (
            "scope:'all'|'user'|'onedrive'|'d'|PATH, "
            "max_files?:int where 0 means unlimited, "
            "max_seconds?:int where 0 means unlimited"
        ),
}


PROGRESS = {
    "active": False,
    "status": "idle",
    "scan_id": None,
    "scope": None,
    "current_root": None,
    "current_path": None,
    "files_seen": 0,
    "directories_seen": 0,
    "knowledge_candidates": 0,
    "bytes_seen": 0,
    "started_at": None,
}


NOISE_DIRS = {
    "adobetemp",
    "package cache",
    "softwaredistribution",
    "inetcache",
    "crashdumps",
    "shadercache",
    "glcache",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}


def progress_update(**values):
    PROGRESS.update(values)


def progress_snapshot():

    result = dict(PROGRESS)

    started = result.get("started_at")

    if started:

        result["elapsed_seconds"] = round(
            max(
                0.0,
                time.time() - float(started),
            ),
            1,
        )

    else:

        result["elapsed_seconds"] = 0.0

    return result


def full_scan(params: dict[str, Any]):

    scope = str(
        params.get(
            "scope",
            "all",
        )
    ).strip()

    raw_max_files = int(
        params.get(
            "max_files",
            0,
        )
        or 0
    )

    raw_max_seconds = int(
        params.get(
            "max_seconds",
            0,
        )
        or 0
    )

    max_files = (
        None
        if raw_max_files <= 0
        else raw_max_files
    )

    max_seconds = (
        None
        if raw_max_seconds <= 0
        else raw_max_seconds
    )

    roots = s9.resolve_scan_roots(
        scope
    )

    scan_id = (
        time.strftime("%Y%m%d-%H%M%S")
        + "-"
        + str(os.getpid())
    )

    started_epoch = time.time()
    started_mono = time.monotonic()

    skip_dirs = {
        str(item).lower()
        for item in (
            set(s9.SKIP_DIRS)
            | NOISE_DIRS
        )
    }

    files_seen = 0
    directories_seen = 0
    knowledge = 0
    bytes_seen = 0
    errors = 0

    extensions = Counter()
    files_by_root = Counter()

    samples = []

    complete = True
    stop_reason = None

    progress_update(
        active=True,
        status="starting",
        scan_id=scan_id,
        scope=scope,
        current_root=None,
        current_path=None,
        files_seen=0,
        directories_seen=0,
        knowledge_candidates=0,
        bytes_seen=0,
        started_at=started_epoch,
    )

    db = sqlite3.connect(
        str(s9.INVENTORY_DB),
        timeout=60,
    )

    try:

        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=NORMAL")
        except Exception:
            pass

        db.execute(
            """
            CREATE TABLE IF NOT EXISTS files (
                path TEXT PRIMARY KEY,
                scan_id TEXT NOT NULL,
                root TEXT NOT NULL,
                size INTEGER,
                modified REAL,
                extension TEXT,
                knowledge_candidate INTEGER NOT NULL DEFAULT 0
            )
            """
        )

        db.execute(
            """
            CREATE TABLE IF NOT EXISTS scan_runs (
                scan_id TEXT PRIMARY KEY,
                started REAL,
                completed REAL,
                scope TEXT,
                roots TEXT,
                files_seen INTEGER,
                directories_seen INTEGER,
                knowledge_candidates INTEGER,
                bytes_seen INTEGER,
                complete INTEGER,
                stop_reason TEXT
            )
            """
        )

        for root in roots:

            root_text = str(root)

            progress_update(
                status="scanning",
                current_root=root_text,
                current_path=root_text,
            )

            for current, dirs, files in os.walk(
                root,
                topdown=True,
                onerror=lambda _error: None,
            ):

                directories_seen += 1

                dirs[:] = [
                    d
                    for d in dirs
                    if d.strip().lower()
                    not in skip_dirs
                ]

                current_path = Path(current)

                for filename in files:

                    if (
                        max_files is not None
                        and files_seen >= max_files
                    ):

                        complete = False
                        stop_reason = "max_files reached"
                        break

                    if (
                        max_seconds is not None
                        and (
                            time.monotonic()
                            - started_mono
                        )
                        >= max_seconds
                    ):

                        complete = False
                        stop_reason = "max_seconds reached"
                        break

                    if (
                        filename.lower()
                        in s9.SENSITIVE_NAMES
                    ):

                        continue

                    path = current_path / filename

                    try:
                        stat = path.stat()
                    except Exception:
                        errors += 1
                        continue

                    extension = path.suffix.lower()

                    candidate = (
                        extension
                        in s9.KNOWLEDGE_EXTENSIONS
                    )

                    files_seen += 1
                    bytes_seen += int(stat.st_size)

                    extensions[
                        extension or "<none>"
                    ] += 1

                    files_by_root[
                        root_text
                    ] += 1

                    if candidate:

                        knowledge += 1

                        if len(samples) < 250:

                            samples.append(
                                str(path)
                            )

                    db.execute(
                        """
                        INSERT INTO files(
                            path,
                            scan_id,
                            root,
                            size,
                            modified,
                            extension,
                            knowledge_candidate
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(path)
                        DO UPDATE SET
                            scan_id=excluded.scan_id,
                            root=excluded.root,
                            size=excluded.size,
                            modified=excluded.modified,
                            extension=excluded.extension,
                            knowledge_candidate=excluded.knowledge_candidate
                        """,
                        (
                            str(path),
                            scan_id,
                            root_text,
                            int(stat.st_size),
                            float(stat.st_mtime),
                            extension,
                            1 if candidate else 0,
                        ),
                    )

                    if files_seen % 500 == 0:

                        progress_update(
                            current_path=str(path),
                            files_seen=files_seen,
                            directories_seen=directories_seen,
                            knowledge_candidates=knowledge,
                            bytes_seen=bytes_seen,
                        )

                    if files_seen % 5000 == 0:
                        db.commit()

                if not complete:
                    break

            if not complete:
                break

        elapsed = (
            time.monotonic()
            - started_mono
        )

        db.execute(
            """
            INSERT OR REPLACE INTO scan_runs(
                scan_id,
                started,
                completed,
                scope,
                roots,
                files_seen,
                directories_seen,
                knowledge_candidates,
                bytes_seen,
                complete,
                stop_reason
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                scan_id,
                started_epoch,
                time.time(),
                scope,
                json.dumps(
                    [
                        str(root)
                        for root in roots
                    ]
                ),
                files_seen,
                directories_seen,
                knowledge,
                bytes_seen,
                1 if complete else 0,
                stop_reason,
            ),
        )

        db.commit()

    finally:

        db.close()

    elapsed = (
        time.monotonic()
        - started_mono
    )

    report = {
        "ok": True,
        "scan_id": scan_id,
        "scope": scope,
        "roots": [
            str(root)
            for root in roots
        ],
        "complete": complete,
        "stop_reason": stop_reason,
        "unlimited_file_mode":
            max_files is None,
        "unlimited_time_mode":
            max_seconds is None,
        "elapsed_seconds":
            round(elapsed, 2),
        "files_seen": files_seen,
        "directories_seen":
            directories_seen,
        "knowledge_candidates":
            knowledge,
        "total_bytes":
            bytes_seen,
        "errors_skipped":
            errors,
        "files_by_root":
            dict(files_by_root),
        "top_extensions":
            extensions.most_common(40),
        "knowledge_samples":
            samples,
        "inventory_database":
            str(s9.INVENTORY_DB),
    }

    output = (
        s9.OUTPUT_HOME
        / (
            "system-full-scan-"
            + scan_id
            + ".json"
        )
    )

    output.write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report["report_path"] = str(output)

    progress_update(
        active=False,
        status=(
            "complete"
            if complete
            else "limited"
        ),
        current_path=None,
        files_seen=files_seen,
        directories_seen=
            directories_seen,
        knowledge_candidates=
            knowledge,
        bytes_seen=bytes_seen,
    )

    return report


async def execute_stage91(
    tool,
    params,
    *,
    approved=False,
):

    if tool == "system.scan.full":

        try:

            result = await asyncio.to_thread(
                full_scan,
                dict(params),
            )

            base.audit(
                tool,
                params,
                approved=approved,
                ok=bool(
                    result.get("ok")
                ),
            )

            return result

        except Exception as exc:

            progress_update(
                active=False,
                status="failed",
            )

            return {
                "ok": False,
                "tool": tool,
                "error": str(exc),
            }

    return await OLD_EXECUTE(
        tool,
        params,
        approved=approved,
    )


base.execute_tool_core = (
    execute_stage91
)


async def plan_stage91(goal):

    plan = await OLD_PLAN(goal)

    if not isinstance(plan, dict):

        return plan

    lower = str(goal).lower()

    scan_intent = any(
        word in lower
        for word in (
            "scan",
            "inventory",
            "inspect",
        )
    )

    result = []
    scan_added = False
    seen = set()

    for original in plan.get(
        "steps",
        [],
    ):

        if not isinstance(
            original,
            dict,
        ):
            continue

        step = dict(original)

        tool = str(
            step.get(
                "tool",
                "",
            )
        )

        params = step.get(
            "params",
            {},
        )

        if not isinstance(params, dict):
            params = {}

        params = dict(params)

        if (
            scan_intent
            and tool
            in {
                "system.scan",
                "system.scan.full",
            }
        ):

            if scan_added:
                continue

            tool = "system.scan.full"

            params[
                "max_files"
            ] = 0

            params[
                "max_seconds"
            ] = 0

            scan_added = True

        signature = (
            tool,
            json.dumps(
                params,
                sort_keys=True,
                default=str,
            ),
        )

        if signature in seen:
            continue

        seen.add(signature)

        result.append(
            {
                "tool": tool,
                "params": params,
                "reason": str(
                    step.get(
                        "reason",
                        "",
                    )
                )[:500],
                "requires_approval":
                    base.tool_requires_approval(
                        tool
                    ),
            }
        )

    return {
        "steps": result[:8],
        "summary": str(
            plan.get(
                "summary",
                "",
            )
        )[:1000],
        "requires_approval":
            any(
                item[
                    "requires_approval"
                ]
                for item
                in result
            ),
    }


base.create_agent_plan = (
    plan_stage91
)


@app.get("/stage91/status")
async def status():

    return {
        "ok": True,
        "stage": "9.1",
        "full_system_scan": True,
        "unlimited_file_scan": True,
        "live_progress": True,
        "processing_indicator": True,
        "tool_count":
            len(base.TOOL_SPECS),
        "onedrive_roots": [
            str(path)
            for path
            in s9.discover_onedrive_roots()
        ],
    }


@app.get("/stage91/progress")
async def progress():

    return progress_snapshot()
'''

gateway_source = gateway_source.lstrip()

ast.parse(
    gateway_source,
    filename=str(G91),
)

write(
    G91,
    gateway_source,
)


# ==============================================================
# STAGE 9.1 UI OVERLAY
# ==============================================================

palette_source = r'''
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
'''

palette_source = palette_source.lstrip()

ast.parse(
    palette_source,
    filename=str(P91),
)

write(
    P91,
    palette_source,
)


# ==============================================================
# PATCH LAUNCHER
# ==============================================================

launcher = read(LAUNCHER)

launcher = re.sub(
    (
        r"(?m)^from app\.ui\.action_palette"
        r"(?:_stage9|_stage91)? "
        r"import install_action_hooks, attach_action_palette\s*$\n?"
    ),
    "",
    launcher,
)

launcher = re.sub(
    (
        r"(?m)^\s*install_action_hooks"
        r"\(CommandCenterMainWindow\)\s*$\n?"
    ),
    "",
    launcher,
)

launcher = re.sub(
    (
        r"(?m)^\s*attach_action_palette"
        r"\(.*?\)\s*$\n?"
    ),
    "",
    launcher,
)

command_import = re.search(
    (
        r"(?m)^from app\.ui\.command_center "
        r"import CommandCenterMainWindow\s*$"
    ),
    launcher,
)

if not command_import:

    raise RuntimeError(
        "CommandCenterMainWindow import not found."
    )

launcher = (
    launcher[:command_import.end()]
    + "\n"
    + "from app.ui.action_palette_stage91 "
    + "import install_action_hooks, attach_action_palette\n"
    + "install_action_hooks(CommandCenterMainWindow)"
    + launcher[command_import.end():]
)

window_match = re.search(
    (
        r"(?m)^([ \t]*)"
        r"window\s*=\s*CommandCenterMainWindow\(\)\s*$"
    ),
    launcher,
)

if not window_match:

    raise RuntimeError(
        "Command Center construction not found."
    )

indent = window_match.group(1)

launcher = (
    launcher[:window_match.end()]
    + "\n"
    + indent
    + "attach_action_palette("
    + "window, Path(__file__).resolve().parent"
    + ")"
    + launcher[window_match.end():]
)

ast.parse(
    launcher,
    filename=str(LAUNCHER),
)

write(
    LAUNCHER,
    launcher,
)


# ==============================================================
# WINDOWS AUTOSTART
# ==============================================================

startup_dir = (
    Path(os.environ["APPDATA"])
    / "Microsoft"
    / "Windows"
    / "Start Menu"
    / "Programs"
    / "Startup"
)

startup_dir.mkdir(
    parents=True,
    exist_ok=True,
)

exe = (
    ACTION_PYW
    if ACTION_PYW.exists()
    else ACTION_PY
)

write(
    startup_dir
    / "RedSight-Action-Gateway.cmd",

    (
        "@echo off\n"
        'cd /d "C:\\Users\\walim\\RedSight"\n'
        'start "" /min "'
        + str(exe)
        + '" -m uvicorn '
        + "redsight_actions.gateway_stage91:app "
        + "--host 127.0.0.1 "
        + "--port 8765 "
        + "--log-level warning\n"
    ),
)


# ==============================================================
# STATIC VALIDATION
# ==============================================================

for path in (
    G91,
    P91,
    LAUNCHER,
):

    ast.parse(
        read(path),
        filename=str(path),
    )


subprocess.run(
    [
        str(ACTION_PY),
        "-m",
        "py_compile",
        str(G91),
    ],
    cwd=str(ROOT),
    check=True,
)

subprocess.run(
    [
        str(UI_PY),
        "-m",
        "py_compile",
        str(P91),
    ],
    cwd=str(ROOT),
    check=True,
)

subprocess.run(
    [
        str(UI_PY),
        "-m",
        "py_compile",
        str(LAUNCHER),
    ],
    cwd=str(ROOT),
    check=True,
)


log(
    "STAGE91_SOURCE_INSTALL=PASS"
)

log(
    "BACKUP="
    + str(BACKUP)
)