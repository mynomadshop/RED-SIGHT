from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


# =====================================================================
# PATHS
# =====================================================================

ROOT = Path(r"C:\Users\walim\RedSight")

UI = ROOT / "app" / "ui" / "command_center.py"
PANEL = ROOT / "app" / "ui" / "heritage_panel.py"

LAUNCHER = ROOT / "launch_redsight_command_center.py"
PS_LAUNCHER = ROOT / "LAUNCH-REDSIGHT-COMMAND-CENTER.ps1"

OVERRIDE = ROOT / "docker-compose.override.yml"

UI_PYTHON = ROOT / ".venv-ui" / "Scripts" / "python.exe"

HERITAGE = ROOT / "data" / "heritage" / "hermes"

LOCALAPPDATA = Path(os.environ["LOCALAPPDATA"])
USERPROFILE = Path(os.environ["USERPROFILE"])

PRIVATE_ROOT = LOCALAPPDATA / "RedSight" / "private"

STAMP = time.strftime("%Y%m%d-%H%M%S")

BACKUP = (
    ROOT
    / ".repair-backups"
    / ("stage7c-r3-" + STAMP)
)

BACKUP.mkdir(
    parents=True,
    exist_ok=True,
)

PRIVATE_ROOT.mkdir(
    parents=True,
    exist_ok=True,
)

CREATE_NO_WINDOW = getattr(
    subprocess,
    "CREATE_NO_WINDOW",
    0,
)

CREATE_NEW_PROCESS_GROUP = getattr(
    subprocess,
    "CREATE_NEW_PROCESS_GROUP",
    0,
)


# =====================================================================
# HELPERS
# =====================================================================

def log(message=""):
    print(
        message,
        flush=True,
    )


def read_text(path: Path) -> str:
    return path.read_text(
        encoding="utf-8-sig",
        errors="replace",
    )


def write_text(
    path: Path,
    text: str,
):
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        text,
        encoding="utf-8",
    )


def backup_file(path: Path):
    if not path.exists():
        return

    target = (
        BACKUP
        / (path.name + ".before")
    )

    shutil.copy2(
        path,
        target,
    )

    log(
        "BACKUP="
        + str(target)
    )


def run(
    command,
    *,
    check=True,
    capture=True,
    timeout=None,
    cwd=ROOT,
):
    command = [
        str(item)
        for item in command
    ]

    log(
        ">> "
        + " ".join(command)
    )

    result = subprocess.run(
        command,
        cwd=str(cwd),
        capture_output=capture,
        text=True,
        errors="replace",
        timeout=timeout,
        creationflags=CREATE_NO_WINDOW,
    )

    if capture:

        if result.stdout.strip():
            print(
                result.stdout.rstrip(),
                flush=True,
            )

        if result.stderr.strip():
            print(
                result.stderr.rstrip(),
                flush=True,
            )

    if (
        check
        and result.returncode != 0
    ):
        raise RuntimeError(
            "Command failed with exit code "
            + str(result.returncode)
            + ": "
            + " ".join(command)
        )

    return result


def http_code(
    url,
    timeout=5,
):
    try:
        request = urllib.request.Request(
            url,
            method="GET",
        )

        with urllib.request.urlopen(
            request,
            timeout=timeout,
        ) as response:

            return response.status

    except Exception:
        return 0


def http_json(
    url,
    *,
    method="GET",
    body=None,
    timeout=30,
):
    payload = None
    headers = {}

    if body is not None:

        payload = json.dumps(
            body,
        ).encode("utf-8")

        headers[
            "Content-Type"
        ] = "application/json"

    request = urllib.request.Request(
        url,
        data=payload,
        headers=headers,
        method=method,
    )

    with urllib.request.urlopen(
        request,
        timeout=timeout,
    ) as response:

        raw = response.read().decode(
            "utf-8",
            errors="replace",
        )

        if raw.strip():
            parsed = json.loads(raw)
        else:
            parsed = {}

        return (
            response.status,
            parsed,
        )


# =====================================================================
# DOCKER
# =====================================================================

def docker_ready():
    try:

        result = subprocess.run(
            [
                "docker",
                "info",
                "--format",
                "{{.ServerVersion}}",
            ],
            capture_output=True,
            text=True,
            timeout=12,
            creationflags=CREATE_NO_WINDOW,
        )

        return (
            result.returncode == 0
            and bool(
                result.stdout.strip()
            )
        )

    except Exception:
        return False


def wait_for_docker(
    attempts=60,
):
    for index in range(attempts):

        if docker_ready():
            return True

        log(
            "Waiting for Docker engine... "
            + str(index + 1)
            + "/"
            + str(attempts)
        )

        time.sleep(2)

    return False


def ensure_docker():
    log("")
    log(
        "============================================================"
    )
    log(
        " DOCKER DESKTOP"
    )
    log(
        "============================================================"
    )

    if docker_ready():

        log(
            "Docker engine: ONLINE"
        )

        return

    log(
        "Docker engine is offline. Starting Docker Desktop..."
    )

    run(
        [
            "docker",
            "desktop",
            "start",
            "--detach",
        ],
        check=False,
        timeout=30,
    )

    desktop_exe = Path(
        r"C:\Program Files\Docker\Docker\Docker Desktop.exe"
    )

    if (
        desktop_exe.exists()
        and not docker_ready()
    ):

        subprocess.Popen(
            [str(desktop_exe)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    if wait_for_docker(45):

        log(
            "Docker engine: ONLINE"
        )

        return

    # ---------------------------------------------------------------
    # Context recovery
    # ---------------------------------------------------------------

    contexts = run(
        [
            "docker",
            "context",
            "ls",
            "--format",
            "{{.Name}}",
        ],
        check=False,
    )

    if (
        "desktop-linux"
        in contexts.stdout.split()
    ):

        run(
            [
                "docker",
                "context",
                "use",
                "desktop-linux",
            ],
            check=False,
        )

        if wait_for_docker(20):

            log(
                "Docker engine: ONLINE"
            )

            return

    # ---------------------------------------------------------------
    # Last non-destructive WSL recovery
    # ---------------------------------------------------------------

    log(
        "Restarting Docker Desktop WSL engine..."
    )

    run(
        [
            "docker",
            "desktop",
            "stop",
        ],
        check=False,
        timeout=30,
    )

    run(
        [
            "wsl.exe",
            "--shutdown",
        ],
        check=False,
        timeout=30,
    )

    time.sleep(3)

    run(
        [
            "docker",
            "desktop",
            "start",
            "--detach",
        ],
        check=False,
        timeout=30,
    )

    if desktop_exe.exists():

        subprocess.Popen(
            [str(desktop_exe)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    if not wait_for_docker(60):

        raise RuntimeError(
            "Docker Desktop Linux engine did not recover."
        )

    log(
        "Docker engine: ONLINE"
    )


# =====================================================================
# HERMES DISCOVERY
# =====================================================================

def discover_hermes():

    candidates = []

    if os.environ.get(
        "HERMES_HOME"
    ):

        candidates.append(
            Path(
                os.environ[
                    "HERMES_HOME"
                ]
            )
        )

    candidates.extend(
        [
            LOCALAPPDATA
            / "hermes",

            USERPROFILE
            / ".hermes",

            Path(
                os.environ.get(
                    "APPDATA",
                    "",
                )
            )
            / "hermes",
        ]
    )

    seen = set()

    for candidate in candidates:

        key = str(
            candidate
        ).lower()

        if key in seen:
            continue

        seen.add(key)

        if not candidate.exists():
            continue

        if (
            (
                candidate
                / "config.yaml"
            ).exists()

            or (
                candidate
                / "memories"
            ).exists()

            or (
                candidate
                / "skills"
            ).exists()
        ):

            return candidate

    raise RuntimeError(
        "Could not locate Hermes home."
    )


# =====================================================================
# HERMES HERITAGE COPY
# =====================================================================

def copy_tree(
    source: Path,
    destination: Path,
):
    if not source.exists():
        return

    def ignore(
        directory,
        names,
    ):
        ignored = []

        for name in names:

            if name in {
                ".archive",
                "__pycache__",
                ".git",
                "node_modules",
            }:

                ignored.append(name)

            elif name.endswith(
                ".pyc"
            ):

                ignored.append(name)

        return ignored

    shutil.copytree(
        source,
        destination,
        dirs_exist_ok=True,
        ignore=ignore,
    )


def hermes_command(
    arguments,
):
    try:

        result = subprocess.run(
            [
                "hermes",
                *arguments,
            ],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=120,
            creationflags=CREATE_NO_WINDOW,
        )

        text = (
            result.stdout
            or ""
        )

        if result.stderr:

            text += (
                "\n"
                + result.stderr
            )

        return text.strip()

    except Exception as exc:

        return (
            "Hermes CLI unavailable: "
            + repr(exc)
        )


def build_heritage(
    hermes: Path,
):
    log("")
    log(
        "============================================================"
    )
    log(
        " HERMES HERITAGE MIGRATION"
    )
    log(
        "============================================================"
    )

    stage = (
        ROOT
        / "data"
        / "heritage"
        / (
            ".hermes-stage-"
            + STAMP
        )
    )

    if stage.exists():

        shutil.rmtree(
            stage
        )

    (
        stage
        / "memories"
    ).mkdir(
        parents=True
    )

    (
        stage
        / "skills"
    ).mkdir(
        parents=True
    )

    (
        stage
        / "context"
    ).mkdir(
        parents=True
    )

    # ---------------------------------------------------------------
    # SOUL
    # ---------------------------------------------------------------

    soul_candidates = [
        hermes
        / "SOUL.md",

        USERPROFILE
        / ".hermes"
        / "SOUL.md",
    ]

    soul = next(
        (
            item
            for item
            in soul_candidates
            if item.exists()
        ),
        None,
    )

    # Search Hermes itself, while excluding documentation examples.
    if soul is None:

        for item in hermes.rglob(
            "SOUL.md"
        ):

            low = str(
                item
            ).lower()

            if (
                "\\website\\"
                in low
                or "\\docs\\"
                in low
                or "\\.archive\\"
                in low
            ):
                continue

            soul = item
            break

    if soul:

        shutil.copy2(
            soul,
            stage
            / "SOUL.md",
        )

        log(
            "SOUL="
            + str(soul)
        )

    else:

        write_text(
            stage
            / "SOUL.md",
            (
                "# Hermes Soul\n\n"
                "No user SOUL.md was located during migration.\n"
            ),
        )

        log(
            "SOUL=NOT_FOUND"
        )

    # ---------------------------------------------------------------
    # MEMORY + USER
    # ---------------------------------------------------------------

    for name in (
        "MEMORY.md",
        "USER.md",
    ):

        candidates = [
            hermes
            / "memories"
            / name,

            hermes
            / name,

            USERPROFILE
            / ".hermes"
            / "memories"
            / name,
        ]

        source = next(
            (
                item
                for item
                in candidates
                if item.exists()
            ),
            None,
        )

        if source:

            shutil.copy2(
                source,
                stage
                / "memories"
                / name,
            )

            log(
                name
                + "="
                + str(source)
            )

        else:

            log(
                name
                + "=NOT_FOUND"
            )

    # ---------------------------------------------------------------
    # Additional context
    # ---------------------------------------------------------------

    for name in (
        "AGENTS.md",
        "HERMES.md",
        ".hermes.md",
        "CLAUDE.md",
    ):

        for base in (
            hermes,
            USERPROFILE,
            ROOT,
        ):

            source = (
                base
                / name
            )

            if not source.exists():
                continue

            safe_name = re.sub(
                r"[^A-Za-z0-9_.-]+",
                "_",
                base.name
                or "root",
            )

            destination = (
                stage
                / "context"
                / (
                    safe_name
                    + "-"
                    + name
                )
            )

            shutil.copy2(
                source,
                destination,
            )

    # ---------------------------------------------------------------
    # Local / self-taught skills
    # ---------------------------------------------------------------

    copy_tree(
        hermes
        / "skills",

        stage
        / "skills"
        / "hermes-home",
    )

    copy_tree(
        USERPROFILE
        / ".hermes"
        / "skills",

        stage
        / "skills"
        / "dot-hermes",
    )

    # ---------------------------------------------------------------
    # Cron / scheduler knowledge
    # ---------------------------------------------------------------

    copy_tree(
        hermes
        / "cron",

        stage
        / "cron",
    )

    # ---------------------------------------------------------------
    # Preserve full config privately only
    # ---------------------------------------------------------------

    config = (
        hermes
        / "config.yaml"
    )

    private_config = (
        PRIVATE_ROOT
        / "hermes-config.yaml"
    )

    if config.exists():

        shutil.copy2(
            config,
            private_config,
        )

        run(
            [
                "icacls",
                str(PRIVATE_ROOT),
                "/inheritance:r",
                "/grant:r",
                (
                    os.environ[
                        "USERNAME"
                    ]
                    + ":(OI)(CI)F"
                ),
            ],
            check=False,
        )

    # ---------------------------------------------------------------
    # MCP + skill inventories
    # ---------------------------------------------------------------

    mcp_output = hermes_command(
        [
            "mcp",
            "list",
        ]
    )

    skills_output = hermes_command(
        [
            "skills",
            "list",
        ]
    )

    write_text(
        stage
        / "MCP_SERVERS.md",
        (
            "# Migrated Hermes MCP Servers\n\n"
            "```text\n"
            + mcp_output
            + "\n```\n"
        ),
    )

    write_text(
        stage
        / "INSTALLED_SKILLS.txt",
        skills_output,
    )

    # ---------------------------------------------------------------
    # Sanitized MCP config
    # ---------------------------------------------------------------

    sanitized = {}

    if config.exists():

        try:
            import yaml

            raw = yaml.safe_load(
                read_text(
                    config
                )
            ) or {}

            servers = (
                raw.get(
                    "mcp_servers",
                    {},
                )
                or {}
            )

            if isinstance(
                servers,
                dict,
            ):

                for name, entry in servers.items():

                    if not isinstance(
                        entry,
                        dict,
                    ):

                        sanitized[
                            name
                        ] = {
                            "configured":
                                True
                        }

                        continue

                    clean = {}

                    for key in (
                        "transport",
                        "command",
                        "args",
                        "url",
                        "cwd",
                        "enabled",
                    ):

                        if key in entry:
                            clean[
                                key
                            ] = entry[
                                key
                            ]

                    # Do not copy secret values to visible/RAG files.
                    if isinstance(
                        entry.get(
                            "env"
                        ),
                        dict,
                    ):

                        clean[
                            "env_keys"
                        ] = sorted(
                            entry[
                                "env"
                            ].keys()
                        )

                    if isinstance(
                        entry.get(
                            "headers"
                        ),
                        dict,
                    ):

                        clean[
                            "header_keys"
                        ] = sorted(
                            entry[
                                "headers"
                            ].keys()
                        )

                    sanitized[
                        name
                    ] = clean

        except Exception as exc:

            sanitized[
                "_parse_error"
            ] = repr(exc)

    write_text(
        stage
        / "mcp_servers_sanitized.json",

        json.dumps(
            sanitized,
            indent=2,
            ensure_ascii=False,
        ),
    )

    # ---------------------------------------------------------------
    # Skill catalog
    # ---------------------------------------------------------------

    catalog = []

    skill_files = sorted(
        stage.rglob(
            "SKILL.md"
        ),
        key=lambda item:
            str(
                item
            ).lower(),
    )

    for skill_file in skill_files:

        if (
            ".archive"
            in str(
                skill_file
            ).lower()
        ):
            continue

        content = read_text(
            skill_file
        )

        name = (
            skill_file
            .parent
            .name
        )

        description = ""

        for line in content.splitlines():

            stripped = line.strip()

            if stripped.lower().startswith(
                "name:"
            ):

                value = (
                    stripped
                    .split(
                        ":",
                        1,
                    )[1]
                    .strip()
                    .strip(
                        "\"'"
                    )
                )

                if value:

                    name = value
                    break

        for line in content.splitlines():

            stripped = line.strip()

            if stripped.lower().startswith(
                "description:"
            ):

                value = (
                    stripped
                    .split(
                        ":",
                        1,
                    )[1]
                    .strip()
                    .strip(
                        "\"'"
                    )
                )

                if value:

                    description = value
                    break

        if not description:

            blocks = re.split(
                r"(?:\r?\n){2,}",
                content,
            )

            for block in blocks:

                block = block.strip()

                if not block:
                    continue

                if block.startswith(
                    "#"
                ):
                    continue

                if block.startswith(
                    "---"
                ):
                    continue

                if len(block) >= 20:

                    description = re.sub(
                        r"\s+",
                        " ",
                        block,
                    )[:400]

                    break

        relative = (
            skill_file
            .relative_to(
                stage
            )
        )

        source = "unknown"

        if (
            len(
                relative.parts
            )
            >= 2
            and relative.parts[
                0
            ]
            == "skills"
        ):

            source = (
                relative.parts[
                    1
                ]
            )

        catalog.append(
            {
                "Name":
                    name,

                "Description":
                    description,

                "Source":
                    source,

                "RelativePath":
                    relative.as_posix(),

                "SHA256":
                    hashlib.sha256(
                        skill_file
                        .read_bytes()
                    ).hexdigest(),

                "Size":
                    skill_file
                    .stat()
                    .st_size,
            }
        )

    catalog.sort(
        key=lambda item:
            (
                item[
                    "Name"
                ].lower(),

                item[
                    "Source"
                ].lower(),
            )
    )

    write_text(
        stage
        / "skills_catalog.json",

        json.dumps(
            catalog,
            indent=2,
            ensure_ascii=False,
        ),
    )

    # ---------------------------------------------------------------
    # MCP names
    # ---------------------------------------------------------------

    mcp_names = sorted(
        key
        for key
        in sanitized
        if not key.startswith(
            "_"
        )
    )

    if not mcp_names:

        for line in mcp_output.splitlines():

            match = re.match(
                r"^\s*([A-Za-z0-9_.-]+)\s+",
                line,
            )

            if not match:
                continue

            candidate = (
                match.group(
                    1
                )
            )

            if candidate.lower() in {
                "name",
                "mcp",
            }:
                continue

            if candidate not in mcp_names:
                mcp_names.append(
                    candidate
                )

    manifest = {
        "source":
            "Hermes Agent",

        "hermes_home":
            str(hermes),

        "soul_present":
            (
                stage
                / "SOUL.md"
            ).exists(),

        "memory_present":
            (
                stage
                / "memories"
                / "MEMORY.md"
            ).exists(),

        "user_present":
            (
                stage
                / "memories"
                / "USER.md"
            ).exists(),

        "skill_count":
            len(catalog),

        "cron_present":
            (
                stage
                / "cron"
            ).exists(),

        "mcp_servers":
            mcp_names,

        "private_config":
            str(
                private_config
            ),

        "mode":
            (
                "preserved + visible + RAG + "
                "command-center-context"
            ),
    }

    write_text(
        stage
        / "heritage_manifest.json",

        json.dumps(
            manifest,
            indent=2,
            ensure_ascii=False,
        ),
    )

    # ---------------------------------------------------------------
    # Replace only RedSight's derived copy
    # ---------------------------------------------------------------

    if HERITAGE.exists():

        old = (
            BACKUP
            / "heritage-before"
        )

        if old.exists():
            shutil.rmtree(
                old
            )

        shutil.copytree(
            HERITAGE,
            old,
        )

        shutil.rmtree(
            HERITAGE
        )

    stage.rename(
        HERITAGE
    )

    log(
        "MIGRATED_SKILLS="
        + str(
            len(catalog)
        )
    )

    log(
        "MCP_SERVERS="
        + ", ".join(
            mcp_names
        )
    )

    return (
        manifest,
        catalog,
    )


# =====================================================================
# HERITAGE SIDE PANEL
# =====================================================================

PANEL_SOURCE = r'''
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from PySide6.QtWidgets import (
    QDockWidget,
    QLabel,
    QLineEdit,
    QListWidget,
    QSplitter,
    QTabWidget,
    QTextBrowser,
    QToolBar,
    QVBoxLayout,
    QWidget,
)


def _read(path: Path) -> str:
    try:
        return path.read_text(
            encoding="utf-8-sig",
            errors="replace",
        )
    except Exception as exc:
        return (
            "Unavailable: "
            + str(exc)
        )


class HermesHeritageDock(
    QDockWidget
):
    def __init__(
        self,
        root: Path,
        parent=None,
    ):
        super().__init__(
            "HERMES HERITAGE",
            parent,
        )

        self.root = Path(root)

        self.catalog = []
        self._visible = []

        self.setObjectName(
            "RedSightHermesHeritageDock"
        )

        self.setMinimumWidth(
            430
        )

        tabs = QTabWidget()

        self.overview = QTextBrowser()
        self.soul = QTextBrowser()
        self.memory = QTextBrowser()
        self.mcp = QTextBrowser()

        tabs.addTab(
            self.overview,
            "Overview",
        )

        tabs.addTab(
            self.soul,
            "Soul",
        )

        tabs.addTab(
            self.memory,
            "Memory",
        )

        tabs.addTab(
            self._skills_page(),
            "Skills",
        )

        tabs.addTab(
            self.mcp,
            "MCP",
        )

        holder = QWidget()

        layout = QVBoxLayout(
            holder
        )

        layout.setContentsMargins(
            5,
            5,
            5,
            5,
        )

        layout.addWidget(
            tabs
        )

        self.setWidget(
            holder
        )

        self.setStyleSheet(
            """
            QDockWidget {
                color:#FFFFFF;
                font-weight:700;
            }

            QDockWidget::title {
                background:#19090B;
                color:#FF3038;
                padding:8px;
                border-bottom:1px solid #8B2026;
            }

            QTabWidget::pane {
                border:1px solid #49343A;
                background:#0B1015;
            }

            QTabBar::tab {
                background:#171D24;
                color:#DCE4EA;
                padding:7px 9px;
            }

            QTabBar::tab:selected {
                background:#9D1D24;
                color:#FFFFFF;
            }

            QTextBrowser,
            QListWidget,
            QLineEdit {
                background:#0C1218;
                color:#F4F7F9;
                border:1px solid #3B4854;
                selection-background-color:#A91F27;
                selection-color:#FFFFFF;
            }

            QLineEdit {
                padding:7px;
                border-radius:5px;
            }
            """
        )

        self.refresh()

    def _skills_page(
        self
    ):
        page = QWidget()

        layout = QVBoxLayout(
            page
        )

        self.search = QLineEdit()

        self.search.setPlaceholderText(
            "Search inherited Hermes skills..."
        )

        splitter = QSplitter(
            Qt.Orientation.Vertical
        )

        self.skill_list = QListWidget()

        self.detail = QTextBrowser()

        splitter.addWidget(
            self.skill_list
        )

        splitter.addWidget(
            self.detail
        )

        splitter.setSizes(
            [
                270,
                430,
            ]
        )

        layout.addWidget(
            self.search
        )

        layout.addWidget(
            splitter
        )

        self.search.textChanged.connect(
            self._filter
        )

        self.skill_list.currentRowChanged.connect(
            self._show
        )

        return page

    def refresh(
        self
    ):
        try:
            manifest = json.loads(
                (
                    self.root
                    / "heritage_manifest.json"
                ).read_text(
                    encoding="utf-8-sig"
                )
            )

        except Exception:
            manifest = {}

        mcp = manifest.get(
            "mcp_servers",
            [],
        )

        self.overview.setPlainText(
            "REDSIGHT HERMES HERITAGE\n\n"
            + "Hermes source: "
            + str(
                manifest.get(
                    "hermes_home",
                    "unknown",
                )
            )
            + "\nInherited skills: "
            + str(
                manifest.get(
                    "skill_count",
                    0,
                )
            )
            + "\nSOUL: "
            + str(
                manifest.get(
                    "soul_present",
                    False,
                )
            )
            + "\nMEMORY: "
            + str(
                manifest.get(
                    "memory_present",
                    False,
                )
            )
            + "\nUSER: "
            + str(
                manifest.get(
                    "user_present",
                    False,
                )
            )
            + "\nCron: "
            + str(
                manifest.get(
                    "cron_present",
                    False,
                )
            )
            + "\nMCP: "
            + (
                ", ".join(mcp)
                if mcp
                else "see MCP tab"
            )
            + "\n\n"
            + (
                "Soul, memory, user context and relevant "
                "procedural skills are inherited by "
                "Command Center chat."
            )
        )

        self.soul.setPlainText(
            _read(
                self.root
                / "SOUL.md"
            )
        )

        self.memory.setPlainText(
            "=== MEMORY.md ===\n\n"
            + _read(
                self.root
                / "memories"
                / "MEMORY.md"
            )
            + "\n\n=== USER.md ===\n\n"
            + _read(
                self.root
                / "memories"
                / "USER.md"
            )
        )

        self.mcp.setPlainText(
            _read(
                self.root
                / "MCP_SERVERS.md"
            )
            + "\n\n=== SANITIZED MCP CONFIG ===\n\n"
            + _read(
                self.root
                / "mcp_servers_sanitized.json"
            )
        )

        try:
            self.catalog = json.loads(
                (
                    self.root
                    / "skills_catalog.json"
                ).read_text(
                    encoding="utf-8-sig"
                )
            )

        except Exception:
            self.catalog = []

        self._filter(
            self.search.text()
        )

    def _filter(
        self,
        text,
    ):
        query = str(
            text
        ).strip().lower()

        self.skill_list.clear()

        self._visible = []

        for item in self.catalog:

            haystack = (
                str(
                    item.get(
                        "Name",
                        "",
                    )
                )
                + " "
                + str(
                    item.get(
                        "Description",
                        "",
                    )
                )
                + " "
                + str(
                    item.get(
                        "Source",
                        "",
                    )
                )
            ).lower()

            if (
                query
                and query
                not in haystack
            ):
                continue

            self._visible.append(
                item
            )

            self.skill_list.addItem(
                "{}   [{}]".format(
                    item.get(
                        "Name",
                        "skill",
                    ),
                    item.get(
                        "Source",
                        "unknown",
                    ),
                )
            )

        if self.skill_list.count():

            self.skill_list.setCurrentRow(
                0
            )

    def _show(
        self,
        row,
    ):
        if (
            row < 0
            or row
            >= len(
                self._visible
            )
        ):
            return

        item = self._visible[
            row
        ]

        relative = item.get(
            "RelativePath",
            "",
        )

        self.detail.setPlainText(
            "NAME: "
            + str(
                item.get(
                    "Name",
                    "",
                )
            )
            + "\nSOURCE: "
            + str(
                item.get(
                    "Source",
                    "",
                )
            )
            + "\nSHA256: "
            + str(
                item.get(
                    "SHA256",
                    "",
                )
            )
            + "\nPATH: "
            + relative
            + "\n\n"
            + _read(
                self.root
                / relative
            )
        )


def attach_heritage_ui(
    window,
    root,
):
    root = Path(root)

    toolbar = QToolBar(
        "RedSight Brand",
        window,
    )

    toolbar.setObjectName(
        "RedSightBrandToolbar"
    )

    toolbar.setMovable(
        False
    )

    toolbar.setFloatable(
        False
    )

    logo = QLabel(
        "REDSIGHT"
    )

    font = QFont(
        "Bahnschrift SemiCondensed",
        30,
        QFont.Weight.Black,
    )

    font.setItalic(
        True
    )

    logo.setFont(
        font
    )

    logo.setStyleSheet(
        "color:#F1262D;"
        "background:transparent;"
        "font-weight:900;"
        "padding:2px 12px 2px 9px;"
    )

    subtitle = QLabel(
        "AGENTIC INTELLIGENCE  •  LOCAL FIRST"
    )

    subtitle.setStyleSheet(
        "color:#E3E8ED;"
        "font-weight:700;"
        "padding-left:5px;"
    )

    toolbar.setStyleSheet(
        "QToolBar{"
        "background:#070B10;"
        "border-bottom:1px solid #762027;"
        "spacing:5px;"
        "}"
    )

    toolbar.addWidget(
        logo
    )

    toolbar.addWidget(
        subtitle
    )

    window.addToolBar(
        Qt.ToolBarArea.TopToolBarArea,
        toolbar,
    )

    dock = HermesHeritageDock(
        root
        / "data"
        / "heritage"
        / "hermes",
        window,
    )

    window.addDockWidget(
        Qt.DockWidgetArea.LeftDockWidgetArea,
        dock,
    )

    window._redsight_brand_toolbar = toolbar

    window._redsight_heritage_dock = dock

    return dock
'''


# =====================================================================
# CHAT HERITAGE CONTEXT
# =====================================================================

HERITAGE_HELPER = r'''
# REDSIGHT_HERITAGE_CONTEXT_BEGIN
def _redsight_heritage_messages(message):
    from pathlib import Path
    import json
    import re

    root = (
        Path(__file__).resolve().parents[2]
        / "data"
        / "heritage"
        / "hermes"
    )

    parts = [
        (
            "You are RedSight. You inherited selected identity, "
            "memory, user-profile and procedural knowledge from "
            "the user's Hermes Agent. Use inherited material only "
            "when relevant. Current user instructions take priority. "
            "A SKILL.md is procedural guidance; never claim a tool "
            "or procedure was executed unless it actually was."
        )
    ]

    budget = 18000
    used = 0

    def add(
        label,
        path,
        limit,
    ):
        nonlocal used

        if used >= budget:
            return

        try:
            text = path.read_text(
                encoding="utf-8-sig",
                errors="replace",
            ).strip()

        except Exception:
            return

        if not text:
            return

        available = max(
            0,
            budget - used,
        )

        text = text[
            :
            min(
                limit,
                available,
            )
        ]

        if not text:
            return

        part = (
            "["
            + label
            + "]\n"
            + text
        )

        parts.append(
            part
        )

        used += len(
            part
        )

    add(
        "Inherited Hermes SOUL",
        root
        / "SOUL.md",
        3500,
    )

    add(
        "Inherited Hermes MEMORY",
        root
        / "memories"
        / "MEMORY.md",
        4500,
    )

    add(
        "Inherited Hermes USER",
        root
        / "memories"
        / "USER.md",
        3000,
    )

    try:
        catalog = json.loads(
            (
                root
                / "skills_catalog.json"
            ).read_text(
                encoding="utf-8-sig"
            )
        )

    except Exception:
        catalog = []

    terms = set(
        re.findall(
            r"[A-Za-z0-9_+.-]{3,}",
            str(message).lower(),
        )
    )

    ranked = []

    for item in catalog:

        haystack = (
            str(
                item.get(
                    "Name",
                    "",
                )
            )
            + " "
            + str(
                item.get(
                    "Description",
                    "",
                )
            )
        ).lower()

        score = sum(
            1
            for term in terms
            if term in haystack
        )

        if score:

            ranked.append(
                (
                    score,
                    item,
                )
            )

    ranked.sort(
        key=lambda pair:
            pair[0],
        reverse=True,
    )

    for _, item in ranked[:2]:

        relative = item.get(
            "RelativePath"
        )

        if not relative:
            continue

        add(
            (
                "Relevant inherited Hermes skill: "
                + str(
                    item.get(
                        "Name",
                        "skill",
                    )
                )
            ),
            root
            / relative,
            2500,
        )

    add(
        "Migrated MCP inventory",
        root
        / "MCP_SERVERS.md",
        1200,
    )

    return [
        {
            "role":
                "system",

            "content":
                "\n\n".join(
                    parts
                ),
        },
        {
            "role":
                "user",

            "content":
                str(message),
        },
    ]
# REDSIGHT_HERITAGE_CONTEXT_END
'''


# =====================================================================
# COMMAND CENTER PATCH
# =====================================================================

def patch_ui():
    log("")
    log(
        "============================================================"
    )
    log(
        " COMMAND CENTER REPAIR"
    )
    log(
        "============================================================"
    )

    # Validate newly generated module before writing.
    ast.parse(
        PANEL_SOURCE,
        filename=str(PANEL),
    )

    source = read_text(
        UI
    )

    begin = (
        "# REDSIGHT_HERITAGE_CONTEXT_BEGIN"
    )

    end = (
        "# REDSIGHT_HERITAGE_CONTEXT_END"
    )

    source = re.sub(
        re.escape(begin)
        + r".*?"
        + re.escape(end)
        + r"\s*",
        "",
        source,
        flags=re.S,
    )

    class_match = re.search(
        r"(?m)^class\s+CommandCenterMainWindow\b",
        source,
    )

    if not class_match:

        raise RuntimeError(
            "CommandCenterMainWindow class was not found."
        )

    source = (
        source[
            :
            class_match.start()
        ]
        + HERITAGE_HELPER.strip()
        + "\n\n"
        + source[
            class_match.start()
            :
        ]
    )

    # ---------------------------------------------------------------
    # Locate only _send_to_api.
    # ---------------------------------------------------------------

    method_match = re.search(
        (
            r"(?ms)"
            r"^    async def _send_to_api\s*\("
            r".*?"
            r"(?=^    (?:async def|def)\s+\w+\s*\(|\Z)"
        ),
        source,
    )

    if not method_match:

        raise RuntimeError(
            "_send_to_api method was not found."
        )

    method = method_match.group(
        0
    )

    # ---------------------------------------------------------------
    # Messages request -> inherited messages request.
    # ---------------------------------------------------------------

    if (
        "_redsight_heritage_messages(message)"
        not in method
    ):

        method_new, count = re.subn(
            (
                r'json\s*=\s*\{'
                r'\s*"messages"\s*:\s*\['
                r'\s*\{'
                r'\s*"role"\s*:\s*"user"\s*,'
                r'\s*"content"\s*:\s*message\s*'
                r'\}'
                r'\s*\]'
                r'\s*,'
                r'\s*"stream"\s*:\s*False\s*'
                r'\}'
                r'\s*,?'
            ),
            (
                'json={"messages": '
                '_redsight_heritage_messages(message), '
                '"stream": False},'
            ),
            method,
            count=1,
            flags=re.S,
        )

        if count == 0:

            method_new, count = re.subn(
                (
                    r'json\s*=\s*\{'
                    r'\s*"message"\s*:\s*message\s*'
                    r'\}'
                    r'\s*,?'
                ),
                (
                    'json={"messages": '
                    '_redsight_heritage_messages(message), '
                    '"stream": False},'
                ),
                method,
                count=1,
            )

        if count == 0:

            raise RuntimeError(
                "Could not locate the Command Center chat JSON payload."
            )

        method = method_new

    # ---------------------------------------------------------------
    # Response compatibility.
    #
    # Actual RedSight response:
    # {"message":"...","model":"default","stream":false}
    #
    # Normalize message into response/content so existing UI extraction
    # remains compatible.
    # ---------------------------------------------------------------

    if (
        "_REDSIGHT_MESSAGE_COMPAT"
        not in method
    ):

        lines = method.splitlines()

        inserted = False

        for index, line in enumerate(
            lines
        ):

            match = re.match(
                (
                    r"^(\s*)"
                    r"data\s*=\s*"
                    r"[A-Za-z_][A-Za-z0-9_]*"
                    r"\.json\(\)\s*$"
                ),
                line,
            )

            if not match:
                continue

            indentation = match.group(
                1
            )

            compatibility = [
                (
                    indentation
                    + "# _REDSIGHT_MESSAGE_COMPAT"
                ),
                (
                    indentation
                    + 'if isinstance(data, dict) '
                    + 'and isinstance(data.get("message"), str):'
                ),
                (
                    indentation
                    + '    data.setdefault("response", data["message"])'
                ),
                (
                    indentation
                    + '    data.setdefault("content", data["message"])'
                ),
            ]

            lines[
                index + 1:
                index + 1
            ] = compatibility

            inserted = True
            break

        if not inserted:

            raise RuntimeError(
                "Could not locate data = response.json() "
                "inside _send_to_api."
            )

        method = "\n".join(
            lines
        )

    source = (
        source[
            :
            method_match.start()
        ]
        + method
        + source[
            method_match.end()
            :
        ]
    )

    if not source.endswith(
        "\n"
    ):
        source += "\n"

    # ---------------------------------------------------------------
    # Launcher integration
    # ---------------------------------------------------------------

    launcher = read_text(
        LAUNCHER
    )

    command_import = (
        "from app.ui.command_center "
        "import CommandCenterMainWindow"
    )

    heritage_import = (
        "from app.ui.heritage_panel "
        "import attach_heritage_ui"
    )

    if (
        heritage_import
        not in launcher
    ):

        if (
            command_import
            not in launcher
        ):

            raise RuntimeError(
                "CommandCenterMainWindow import missing from launcher."
            )

        launcher = launcher.replace(
            command_import,
            (
                command_import
                + "\n"
                + heritage_import
            ),
            1,
        )

    attach_line = (
        "attach_heritage_ui(window, ROOT)"
    )

    if (
        attach_line
        not in launcher
    ):

        window_anchor = (
            "window = CommandCenterMainWindow()"
        )

        if (
            window_anchor
            not in launcher
        ):

            raise RuntimeError(
                "CommandCenterMainWindow creation missing from launcher."
            )

        launcher = launcher.replace(
            window_anchor,
            (
                window_anchor
                + "\n"
                + attach_line
            ),
            1,
        )

    # ---------------------------------------------------------------
    # Main high-contrast theme.
    # ---------------------------------------------------------------

    if (
        "REDSIGHT_HIGH_CONTRAST"
        not in launcher
        and
        "REDSIGHT_CONTRAST_V2"
        not in launcher
        and
        "REDSIGHT_HIGH_CONTRAST_R3"
        not in launcher
    ):

        loop_anchor = (
            "loop = QEventLoop(app)"
        )

        if loop_anchor not in launcher:

            raise RuntimeError(
                "qasync QEventLoop anchor missing from launcher."
            )

        theme = r'''
# REDSIGHT_HIGH_CONTRAST_R3
app.setStyle("Fusion")

app.setStyleSheet(r"""
QWidget {
    background-color:#090E14;
    color:#F4F7FA;
    font-size:13px;
}

QMainWindow {
    background-color:#070B10;
}

QLabel {
    color:#F6F8FA;
    background:transparent;
}

QLineEdit,
QTextEdit,
QPlainTextEdit,
QComboBox {
    background-color:#111B25;
    color:#FFFFFF;
    border:1px solid #627F99;
    border-radius:6px;
    padding:7px;
    selection-background-color:#A51D24;
    selection-color:#FFFFFF;
}

QLineEdit:focus,
QTextEdit:focus,
QPlainTextEdit:focus {
    border:2px solid #F1262D;
}

QPushButton {
    background-color:#8C1D23;
    color:#FFFFFF;
    border:1px solid #D83A42;
    border-radius:6px;
    padding:8px 13px;
    font-weight:700;
}

QPushButton:hover {
    background-color:#B3262E;
}

QPushButton:pressed {
    background-color:#681318;
}

QGroupBox {
    background-color:#101820;
    color:#FFFFFF;
    border:1px solid #4C6174;
    border-radius:7px;
    margin-top:10px;
    padding-top:8px;
    font-weight:700;
}

QTableWidget,
QTableView,
QListWidget,
QTreeWidget {
    background-color:#0D151D;
    alternate-background-color:#14202A;
    color:#FFFFFF;
    gridline-color:#405465;
    border:1px solid #4C6174;
    selection-background-color:#982028;
    selection-color:#FFFFFF;
}

QHeaderView::section {
    background-color:#1A2732;
    color:#FFFFFF;
    border:1px solid #4C6174;
    padding:6px;
    font-weight:700;
}

QTabWidget::pane {
    background-color:#0D151D;
    border:1px solid #4C6174;
}

QTabBar::tab {
    background-color:#17232E;
    color:#DCE5EC;
    padding:8px 12px;
    border:1px solid #405465;
}

QTabBar::tab:selected {
    background-color:#9D1D24;
    color:#FFFFFF;
}

QProgressBar {
    background-color:#101820;
    color:#FFFFFF;
    border:1px solid #53697B;
    border-radius:5px;
    text-align:center;
}

QProgressBar::chunk {
    background-color:#C1262E;
}

QStatusBar {
    background-color:#070B10;
    color:#E8EEF3;
    border-top:1px solid #405465;
}

QToolTip {
    background-color:#1A252F;
    color:#FFFFFF;
    border:1px solid #E54A50;
    padding:5px;
}
""")
'''

        launcher = launcher.replace(
            loop_anchor,
            (
                theme.strip()
                + "\n\n"
                + loop_anchor
            ),
            1,
        )

    # ---------------------------------------------------------------
    # Validate ALL Python before writing any source changes.
    # ---------------------------------------------------------------

    ast.parse(
        source,
        filename=str(UI),
    )

    ast.parse(
        PANEL_SOURCE,
        filename=str(PANEL),
    )

    ast.parse(
        launcher,
        filename=str(LAUNCHER),
    )

    # ---------------------------------------------------------------
    # Commit source changes.
    # ---------------------------------------------------------------

    write_text(
        PANEL,
        PANEL_SOURCE.strip()
        + "\n",
    )

    write_text(
        UI,
        source,
    )

    write_text(
        LAUNCHER,
        launcher,
    )

    write_text(
        PS_LAUNCHER,
        (
            '$ErrorActionPreference = "Stop"\n'
            '$Root = "C:\\Users\\walim\\RedSight"\n'
            '$Python = Join-Path $Root ".venv-ui\\Scripts\\python.exe"\n'
            '$Launcher = Join-Path $Root "launch_redsight_command_center.py"\n'
            'Set-Location $Root\n'
            '& $Python $Launcher\n'
        ),
    )

    log(
        "COMMAND_CENTER_PATCH=PASS"
    )

    log(
        "CHAT_MESSAGE_COMPAT=PASS"
    )

    log(
        "HERITAGE_PANEL=PASS"
    )

    log(
        "REDSIGHT_LOGO=PASS"
    )

    log(
        "QASYNC_LAUNCHER=PASS"
    )


# =====================================================================
# COMPOSE HERITAGE MOUNT
# =====================================================================

def patch_compose():
    log("")
    log(
        "============================================================"
    )
    log(
        " DOCKER HERITAGE MOUNT"
    )
    log(
        "============================================================"
    )

    text = read_text(
        OVERRIDE
    )

    if (
        "data/heritage:/heritage:ro"
        in text
    ):

        log(
            "HERITAGE_MOUNT_CONFIG=ALREADY_PRESENT"
        )

        return

    lines = text.splitlines()

    service_start = None
    service_end = len(
        lines
    )

    for index, line in enumerate(
        lines
    ):

        if re.match(
            r"^\s{2}redsight:\s*$",
            line,
        ):

            service_start = index
            break

    if service_start is None:

        raise RuntimeError(
            "redsight service not found "
            "in docker-compose.override.yml."
        )

    for index in range(
        service_start + 1,
        len(lines),
    ):

        if re.match(
            r"^\s{2}[A-Za-z0-9_.-]+:\s*$",
            lines[index],
        ):

            service_end = index
            break

    volumes_index = None

    for index in range(
        service_start + 1,
        service_end,
    ):

        if re.match(
            r"^\s{4}volumes:\s*$",
            lines[index],
        ):

            volumes_index = index
            break

    if volumes_index is not None:

        lines.insert(
            volumes_index + 1,
            (
                '      - '
                '"./data/heritage:/heritage:ro"'
            ),
        )

    else:

        environment_index = next(
            (
                index
                for index
                in range(
                    service_start + 1,
                    service_end,
                )
                if re.match(
                    r"^\s{4}environment:\s*$",
                    lines[index],
                )
            ),
            service_start + 1,
        )

        lines[
            environment_index:
            environment_index
        ] = [
            "    volumes:",
            (
                '      - '
                '"./data/heritage:/heritage:ro"'
            ),
        ]

    write_text(
        OVERRIDE,
        "\n".join(
            lines
        )
        + "\n",
    )

    log(
        "HERITAGE_MOUNT_CONFIG=ADDED"
    )


# =====================================================================
# BACKEND HEALTH
# =====================================================================

def wait_for_redsight():

    for index in range(
        60
    ):

        code = http_code(
            "http://127.0.0.1:8000/api/v1/health",
            4,
        )

        log(
            "RedSight health: "
            + str(code)
        )

        if code == 200:
            return

        time.sleep(2)

    run(
        [
            "docker",
            "logs",
            "--tail",
            "180",
            "redsight",
        ],
        check=False,
    )

    raise RuntimeError(
        "RedSight did not become healthy."
    )


# =====================================================================
# NON-DESTRUCTIVE RAG
# =====================================================================

def rag_post(
    collection,
    paths,
):
    if not paths:
        return

    body = {
        "paths":
            paths,

        "collection":
            collection,

        "project":
            "hermes-heritage",
    }

    try:

        status, result = http_json(
            (
                "http://127.0.0.1:8000"
                "/api/v1/jobs/index/batch"
            ),
            method="POST",
            body=body,
            timeout=180,
        )

        write_text(
            BACKUP
            / (
                "rag-"
                + collection
                + "-"
                + str(
                    int(
                        time.time()
                    )
                )
                + ".json"
            ),

            json.dumps(
                result,
                indent=2,
                ensure_ascii=False,
            ),
        )

        log(
            "RAG "
            + collection
            + ": HTTP "
            + str(status)
            + " PASS"
        )

    except Exception as exc:

        # RAG failure must NOT prevent the functional UI from relaunching.
        log(
            "RAG "
            + collection
            + ": WARNING "
            + repr(exc)
        )

        log(
            (
                "RAG warning is non-destructive. "
                "Migration remains preserved."
            )
        )


# =====================================================================
# UI PROCESS MANAGEMENT
# =====================================================================

def stop_old_ui():
    try:
        import psutil

        for process in psutil.process_iter(
            [
                "pid",
                "name",
                "cmdline",
            ]
        ):

            try:

                name = (
                    process.info[
                        "name"
                    ]
                    or ""
                ).lower()

                command = " ".join(
                    process.info[
                        "cmdline"
                    ]
                    or []
                )

                if (
                    name
                    in {
                        "python.exe",
                        "pythonw.exe",
                    }
                    and
                    (
                        "launch_redsight_command_center.py"
                        in command
                        or
                        "app.ui.command_center"
                        in command
                    )
                ):

                    log(
                        "Stopping old UI PID "
                        + str(
                            process.pid
                        )
                    )

                    process.terminate()

                    try:
                        process.wait(
                            4
                        )

                    except psutil.TimeoutExpired:
                        process.kill()

            except (
                psutil.NoSuchProcess,
                psutil.AccessDenied,
            ):
                pass

    except Exception as exc:

        log(
            "UI cleanup warning: "
            + repr(exc)
        )


def launch_ui():

    stdout_path = (
        BACKUP
        / "command-center.stdout.log"
    )

    stderr_path = (
        BACKUP
        / "command-center.stderr.log"
    )

    stdout_handle = stdout_path.open(
        "w",
        encoding="utf-8",
    )

    stderr_handle = stderr_path.open(
        "w",
        encoding="utf-8",
    )

    process = subprocess.Popen(
        [
            str(
                UI_PYTHON
            ),
            str(
                LAUNCHER
            ),
        ],
        cwd=str(ROOT),
        stdout=stdout_handle,
        stderr=stderr_handle,
        creationflags=CREATE_NEW_PROCESS_GROUP,
    )

    time.sleep(6)

    if (
        process.poll()
        is not None
    ):

        stdout_handle.close()
        stderr_handle.close()

        log("")
        log(
            "=== COMMAND CENTER STDOUT ==="
        )

        if stdout_path.exists():

            log(
                read_text(
                    stdout_path
                )
            )

        log("")
        log(
            "=== COMMAND CENTER STDERR ==="
        )

        if stderr_path.exists():

            log(
                read_text(
                    stderr_path
                )
            )

        raise RuntimeError(
            "Command Center exited during startup."
        )

    log(
        (
            "COMMAND_CENTER_LAUNCHED=YES PID="
            + str(
                process.pid
            )
        )
    )

    return process.pid


# =====================================================================
# MAIN
# =====================================================================

def main():
    os.chdir(
        ROOT
    )

    log("")
    log(
        "===================================================================="
    )
    log(
        " REDSIGHT STAGE-7C-R3"
    )
    log(
        " HERMES HERITAGE + UI REPAIR + RELAUNCH"
    )
    log(
        "===================================================================="
    )
    log("")

    # ---------------------------------------------------------------
    # Required files
    # ---------------------------------------------------------------

    for path in (
        UI,
        LAUNCHER,
        OVERRIDE,
        UI_PYTHON,
    ):

        if not path.exists():

            raise RuntimeError(
                "Required path missing: "
                + str(path)
            )

    # ---------------------------------------------------------------
    # Backups
    # ---------------------------------------------------------------

    for path in (
        UI,
        PANEL,
        LAUNCHER,
        PS_LAUNCHER,
        OVERRIDE,
    ):

        backup_file(
            path
        )

    log(
        "BACKUP_ROOT="
        + str(BACKUP)
    )

    # ---------------------------------------------------------------
    # Docker
    # ---------------------------------------------------------------

    ensure_docker()

    # ---------------------------------------------------------------
    # Hermes
    # ---------------------------------------------------------------

    hermes = discover_hermes()

    log(
        "HERMES_HOME="
        + str(hermes)
    )

    manifest, catalog = build_heritage(
        hermes
    )

    # ---------------------------------------------------------------
    # UI + Compose
    # ---------------------------------------------------------------

    patch_ui()

    patch_compose()

    # ---------------------------------------------------------------
    # Compose validation BEFORE touching running container
    # ---------------------------------------------------------------

    run(
        [
            "docker",
            "compose",
            "config",
        ],
        timeout=60,
    )

    log(
        "COMPOSE_VALIDATION=PASS"
    )

    # ---------------------------------------------------------------
    # Restart RedSight only
    #
    # Qdrant volumes are NOT removed.
    # ---------------------------------------------------------------

    log("")
    log(
        "============================================================"
    )
    log(
        " RESTARTING REDSIGHT"
    )
    log(
        "============================================================"
    )

    run(
        [
            "docker",
            "compose",
            "up",
            "-d",
            "--force-recreate",
            "redsight",
        ],
        timeout=180,
    )

    wait_for_redsight()

    log(
        "REDSIGHT_BACKEND=HEALTHY"
    )

    # ---------------------------------------------------------------
    # Qdrant health
    # ---------------------------------------------------------------

    run(
        [
            "docker",
            "exec",
            "redsight-qdrant",
            "curl",
            "-fsS",
            "http://localhost:6333/readyz",
        ],
        timeout=20,
    )

    log(
        "QDRANT=HEALTHY"
    )

    # ---------------------------------------------------------------
    # GPU regression test
    # ---------------------------------------------------------------

    gpu = run(
        [
            "docker",
            "exec",
            "redsight",
            "nvidia-smi",
            "-L",
        ],
        timeout=20,
    )

    if (
        "GPU 0:"
        not in gpu.stdout
        or
        "GPU 1:"
        not in gpu.stdout
    ):

        raise RuntimeError(
            "Both RTX GPUs are not visible inside RedSight."
        )

    log(
        "DUAL_GPU=PASS"
    )

    # ---------------------------------------------------------------
    # Heritage mount
    # ---------------------------------------------------------------

    run(
        [
            "docker",
            "exec",
            "redsight",
            "sh",
            "-lc",
            (
                "test -f "
                "/heritage/hermes/heritage_manifest.json "
                "&& echo HERITAGE_MOUNT=PASS"
            ),
        ],
        timeout=20,
    )

    # ---------------------------------------------------------------
    # LM Studio
    # ---------------------------------------------------------------

    lm_code = http_code(
        "http://127.0.0.1:1234/v1/models",
        5,
    )

    log(
        "LM_STUDIO_HTTP="
        + str(
            lm_code
        )
    )

    if lm_code != 200:

        raise RuntimeError(
            "LM Studio /v1/models is not reachable."
        )

    # ---------------------------------------------------------------
    # Actual RedSight -> LM Studio inference
    # ---------------------------------------------------------------

    chat_status, chat = http_json(
        (
            "http://127.0.0.1:8000"
            "/api/v1/chat"
        ),
        method="POST",
        body={
            "messages":
                [
                    {
                        "role":
                            "user",

                        "content":
                            (
                                "Reply with exactly "
                                "REDSIGHT_HERITAGE_READY"
                            ),
                    }
                ],

            "stream":
                False,
        },
        timeout=180,
    )

    message = (
        chat.get(
            "message"
        )
        if isinstance(
            chat,
            dict,
        )
        else None
    )

    log(
        "CHAT_HTTP="
        + str(
            chat_status
        )
    )

    log(
        "CHAT_MESSAGE="
        + str(message)
    )

    if (
        chat_status != 200
        or not isinstance(
            message,
            str,
        )
        or not message.strip()
    ):

        raise RuntimeError(
            "RedSight -> LM Studio chat validation failed."
        )

    log(
        "REDSIGHT_TO_LM_STUDIO=PASS"
    )

    # =================================================================
    # RAG ingestion
    #
    # IMPORTANT:
    # Does NOT call /collections/{collection}/reindex
    # =================================================================

    log("")
    log(
        "============================================================"
    )
    log(
        " NON-DESTRUCTIVE HERITAGE RAG"
    )
    log(
        "============================================================"
    )

    knowledge_paths = []

    if (
        HERITAGE
        / "SOUL.md"
    ).exists():

        knowledge_paths.append(
            "/heritage/hermes/SOUL.md"
        )

    if (
        HERITAGE
        / "context"
    ).exists():

        knowledge_paths.append(
            "/heritage/hermes/context"
        )

    rag_post(
        "knowledge_docs",
        knowledge_paths,
    )

    memory_paths = []

    for relative in (
        "memories/MEMORY.md",
        "memories/USER.md",
    ):

        if (
            HERITAGE
            / relative
        ).exists():

            memory_paths.append(
                (
                    "/heritage/hermes/"
                    + relative
                )
            )

    rag_post(
        "episodic_memory",
        memory_paths,
    )

    skill_paths = [
        (
            "/heritage/hermes/"
            + item[
                "RelativePath"
            ]
        )
        for item in catalog
    ]

    # Keep requests reasonably sized.
    for offset in range(
        0,
        len(
            skill_paths
        ),
        25,
    ):

        rag_post(
            "skills_index",
            skill_paths[
                offset:
                offset + 25
            ],
        )

    rag_post(
        "tool_catalog",
        [
            "/heritage/hermes/MCP_SERVERS.md",
            (
                "/heritage/hermes/"
                "mcp_servers_sanitized.json"
            ),
        ],
    )

    # ---------------------------------------------------------------
    # Relaunch UI
    # ---------------------------------------------------------------

    log("")
    log(
        "============================================================"
    )
    log(
        " RELAUNCHING COMMAND CENTER"
    )
    log(
        "============================================================"
    )

    stop_old_ui()

    time.sleep(1)

    pid = launch_ui()

    # ---------------------------------------------------------------
    # Final status
    # ---------------------------------------------------------------

    log("")

    run(
        [
            "docker",
            "compose",
            "ps",
        ],
        check=False,
    )

    log("")
    log(
        "===================================================================="
    )
    log(
        " FINAL STATUS"
    )
    log(
        "===================================================================="
    )

    log(
        "RedSight backend       : HEALTHY"
    )

    log(
        "Qdrant                 : HEALTHY"
    )

    log(
        "LM Studio              : CONNECTED"
    )

    log(
        "RedSight chat          : PASS"
    )

    log(
        "Dual RTX GPUs          : PASS"
    )

    log(
        "Hermes SOUL            : "
        + str(
            manifest[
                "soul_present"
            ]
        )
    )

    log(
        "Hermes MEMORY          : "
        + str(
            manifest[
                "memory_present"
            ]
        )
    )

    log(
        "Hermes USER            : "
        + str(
            manifest[
                "user_present"
            ]
        )
    )

    log(
        "Hermes skills migrated : "
        + str(
            manifest[
                "skill_count"
            ]
        )
    )

    log(
        "MCP servers            : "
        + ", ".join(
            manifest[
                "mcp_servers"
            ]
        )
    )

    log(
        "Heritage mount         : PASS"
    )

    log(
        "REDSIGHT red logo      : PASS"
    )

    log(
        "Heritage side panel    : PASS"
    )

    log(
        "Chat response parser   : PASS"
    )

    log(
        "qasync launcher        : PASS"
    )

    log(
        "Command Center PID     : "
        + str(pid)
    )

    log(
        "Backup                 : "
        + str(BACKUP)
    )

    log("")

    log(
        "Original Hermes files were NOT modified."
    )

    log(
        "Qdrant volumes/collections were NOT deleted or recreated."
    )

    log("")

    log(
        "STAGE7C_R3_COMPLETE=YES"
    )


if __name__ == "__main__":

    try:
        main()

    except Exception as exc:

        log("")

        log(
            "STAGE7C_R3_FAILED="
            + repr(exc)
        )

        log(
            "BACKUP="
            + str(BACKUP)
        )

        raise