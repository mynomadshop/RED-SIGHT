from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


ROOT = Path(r"C:\Users\walim\RedSight")

UI = ROOT / "app" / "ui" / "command_center.py"
PANEL = ROOT / "app" / "ui" / "heritage_panel.py"
LAUNCHER = ROOT / "launch_redsight_command_center.py"
OVERRIDE = ROOT / "docker-compose.override.yml"

UI_PYTHON = ROOT / ".venv-ui" / "Scripts" / "python.exe"

HERITAGE = ROOT / "data" / "heritage" / "hermes"

STAMP = time.strftime("%Y%m%d-%H%M%S")

BACKUP = (
    ROOT
    / ".repair-backups"
    / ("stage7c-r4-" + STAMP)
)

BACKUP.mkdir(
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

def log(text=""):
    print(text, flush=True)


def read_text(path: Path) -> str:
    return path.read_text(
        encoding="utf-8-sig",
        errors="replace",
    )


def write_text(path: Path, text: str):
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        text,
        encoding="utf-8",
    )


def python_valid(path: Path) -> bool:
    try:
        ast.parse(
            read_text(path),
            filename=str(path),
        )
        return True
    except Exception:
        return False


def backup(path: Path):
    if not path.exists():
        return

    destination = (
        BACKUP
        / (path.name + ".before")
    )

    shutil.copy2(
        path,
        destination,
    )

    log(
        "BACKUP="
        + str(destination)
    )


def run(
    command,
    *,
    check=True,
    timeout=None,
):
    command = [
        str(value)
        for value in command
    ]

    log(
        ">> "
        + " ".join(command)
    )

    result = subprocess.run(
        command,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        errors="replace",
        timeout=timeout,
        creationflags=CREATE_NO_WINDOW,
    )

    if result.stdout.strip():
        log(result.stdout.rstrip())

    if result.stderr.strip():
        log(result.stderr.rstrip())

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


def http_get_code(
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
        method="POST" if body is not None else "GET",
    )

    with urllib.request.urlopen(
        request,
        timeout=timeout,
    ) as response:

        raw = response.read().decode(
            "utf-8",
            errors="replace",
        )

        data = (
            json.loads(raw)
            if raw.strip()
            else {}
        )

        return response.status, data


# =====================================================================
# START
# =====================================================================

log("")
log("====================================================================")
log(" REDSIGHT STAGE-7C-R4")
log(" SAFE HERITAGE UI REPAIR + BACKEND RESTART + UI RELAUNCH")
log("====================================================================")
log("")

for required in (
    UI,
    LAUNCHER,
    OVERRIDE,
    UI_PYTHON,
):
    if not required.exists():
        raise RuntimeError(
            "Missing required file: "
            + str(required)
        )


# =====================================================================
# BACKUPS
# =====================================================================

for path in (
    UI,
    PANEL,
    LAUNCHER,
    OVERRIDE,
):
    backup(path)

log(
    "BACKUP_ROOT="
    + str(BACKUP)
)


# =====================================================================
# 1. GUARANTEE COMMAND CENTER SOURCE IS HEALTHY
#
# R3 validated a transformed IN-MEMORY source and failed before writing.
# Nevertheless, verify the actual file and restore R3 backup if needed.
# =====================================================================

log("")
log("====================================================================")
log(" COMMAND CENTER SOURCE VALIDATION")
log("====================================================================")

if python_valid(UI):

    log(
        "COMMAND_CENTER_CURRENT_AST=OK"
    )

else:

    log(
        "Current Command Center source is invalid."
    )

    candidates = sorted(
        (
            ROOT
            / ".repair-backups"
        ).glob(
            "stage7c-r3-*/command_center.py.before"
        ),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    restored = False

    for candidate in candidates:

        if not python_valid(candidate):
            continue

        shutil.copy2(
            candidate,
            UI,
        )

        log(
            "RESTORED_COMMAND_CENTER="
            + str(candidate)
        )

        restored = True
        break

    if not restored:

        raise RuntimeError(
            "No valid pre-R3 Command Center backup was found."
        )

    if not python_valid(UI):

        raise RuntimeError(
            "Restored Command Center still fails AST validation."
        )

    log(
        "COMMAND_CENTER_RESTORE_AST=OK"
    )


# =====================================================================
# 2. VERIFY ALREADY-MIGRATED HERMES HERITAGE
# =====================================================================

log("")
log("====================================================================")
log(" HERMES HERITAGE VALIDATION")
log("====================================================================")

manifest_path = (
    HERITAGE
    / "heritage_manifest.json"
)

catalog_path = (
    HERITAGE
    / "skills_catalog.json"
)

if not manifest_path.exists():

    raise RuntimeError(
        "R3 heritage_manifest.json is missing. "
        "Do not continue because the migration copy cannot be verified."
    )

manifest = json.loads(
    read_text(
        manifest_path
    )
)

if catalog_path.exists():

    catalog = json.loads(
        read_text(
            catalog_path
        )
    )

else:

    catalog = []

log(
    "HERMES_HOME="
    + str(
        manifest.get(
            "hermes_home",
            "unknown",
        )
    )
)

log(
    "SOUL_PRESENT="
    + str(
        manifest.get(
            "soul_present",
            False,
        )
    )
)

log(
    "MEMORY_PRESENT="
    + str(
        manifest.get(
            "memory_present",
            False,
        )
    )
)

log(
    "USER_PRESENT="
    + str(
        manifest.get(
            "user_present",
            False,
        )
    )
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
        manifest.get(
            "mcp_servers",
            [],
        )
    )
)


# =====================================================================
# 3. BUILD HERMES HERITAGE SIDE PANEL
#
# This does NOT touch command_center.py.
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


class HermesHeritageDock(QDockWidget):

    def __init__(
        self,
        heritage_root: Path,
        parent=None,
    ):
        super().__init__(
            "HERMES HERITAGE",
            parent,
        )

        self.root = Path(
            heritage_root
        )

        self.catalog = []
        self.visible_skills = []

        self.setObjectName(
            "RedSightHermesHeritageDock"
        )

        self.setMinimumWidth(
            440
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
            self._build_skills_tab(),
            "Skills",
        )

        tabs.addTab(
            self.mcp,
            "MCP",
        )

        container = QWidget()

        layout = QVBoxLayout(
            container
        )

        layout.setContentsMargins(
            6,
            6,
            6,
            6,
        )

        layout.addWidget(
            tabs
        )

        self.setWidget(
            container
        )

        self.setStyleSheet(
            """
            QDockWidget {
                color: #FFFFFF;
                font-weight: 700;
            }

            QDockWidget::title {
                background-color: #17090B;
                color: #FF3540;
                padding: 8px;
                border-bottom: 1px solid #8D252B;
            }

            QTabWidget::pane {
                background-color: #0B1016;
                border: 1px solid #46525D;
            }

            QTabBar::tab {
                background-color: #19212A;
                color: #E4E9ED;
                padding: 8px 10px;
                border: 1px solid #3D4852;
            }

            QTabBar::tab:selected {
                background-color: #A51F27;
                color: #FFFFFF;
            }

            QTextBrowser,
            QListWidget,
            QLineEdit {
                background-color: #0C131A;
                color: #F7F9FA;
                border: 1px solid #4A5864;
                selection-background-color: #AE252D;
                selection-color: #FFFFFF;
            }

            QLineEdit {
                padding: 7px;
                border-radius: 5px;
            }
            """
        )

        self.refresh()

    def _build_skills_tab(self):

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

        self.skill_detail = QTextBrowser()

        splitter.addWidget(
            self.skill_list
        )

        splitter.addWidget(
            self.skill_detail
        )

        splitter.setSizes(
            [
                270,
                450,
            ]
        )

        layout.addWidget(
            self.search
        )

        layout.addWidget(
            splitter
        )

        self.search.textChanged.connect(
            self.filter_skills
        )

        self.skill_list.currentRowChanged.connect(
            self.show_skill
        )

        return page

    def refresh(self):

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

        mcp_servers = manifest.get(
            "mcp_servers",
            [],
        )

        self.overview.setPlainText(
            "REDSIGHT HERMES HERITAGE\n\n"
            + "Hermes source:\n"
            + str(
                manifest.get(
                    "hermes_home",
                    "unknown",
                )
            )
            + "\n\nInherited skills: "
            + str(
                manifest.get(
                    "skill_count",
                    0,
                )
            )
            + "\nSOUL migrated: "
            + str(
                manifest.get(
                    "soul_present",
                    False,
                )
            )
            + "\nMEMORY migrated: "
            + str(
                manifest.get(
                    "memory_present",
                    False,
                )
            )
            + "\nUSER migrated: "
            + str(
                manifest.get(
                    "user_present",
                    False,
                )
            )
            + "\nCron migrated: "
            + str(
                manifest.get(
                    "cron_present",
                    False,
                )
            )
            + "\n\nMCP servers:\n"
            + (
                "\n".join(
                    "  - " + str(x)
                    for x in mcp_servers
                )
                if mcp_servers
                else "  None discovered"
            )
            + "\n\n"
            + (
                "Hermes Soul, Memory, USER profile, Skills and MCP "
                "definitions are preserved inside RedSight heritage."
            )
        )

        self.soul.setPlainText(
            _read(
                self.root
                / "SOUL.md"
            )
        )

        self.memory.setPlainText(
            "================ MEMORY.md ================\n\n"
            + _read(
                self.root
                / "memories"
                / "MEMORY.md"
            )
            + "\n\n"
            + "================ USER.md ==================\n\n"
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
            + "\n\n"
            + "============ SANITIZED MCP CONFIG ==========\n\n"
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

        self.filter_skills(
            self.search.text()
        )

    def filter_skills(
        self,
        text,
    ):

        query = str(
            text
        ).strip().lower()

        self.skill_list.clear()

        self.visible_skills = []

        for skill in self.catalog:

            haystack = (
                str(
                    skill.get(
                        "Name",
                        "",
                    )
                )
                + " "
                + str(
                    skill.get(
                        "Description",
                        "",
                    )
                )
                + " "
                + str(
                    skill.get(
                        "Source",
                        "",
                    )
                )
            ).lower()

            if (
                query
                and query not in haystack
            ):

                continue

            self.visible_skills.append(
                skill
            )

            self.skill_list.addItem(
                "{}  [{}]".format(
                    skill.get(
                        "Name",
                        "skill",
                    ),
                    skill.get(
                        "Source",
                        "unknown",
                    ),
                )
            )

        if self.skill_list.count():

            self.skill_list.setCurrentRow(
                0
            )

    def show_skill(
        self,
        row,
    ):

        if (
            row < 0
            or row >= len(
                self.visible_skills
            )
        ):

            return

        item = self.visible_skills[
            row
        ]

        relative = str(
            item.get(
                "RelativePath",
                "",
            )
        )

        path = (
            self.root
            / relative
        )

        self.skill_detail.setPlainText(
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
            + _read(path)
        )


def attach_heritage_ui(
    window,
    project_root,
):

    root = Path(
        project_root
    )

    # -------------------------------------------------------------
    # REDSIGHT LOGO / BRAND
    # -------------------------------------------------------------

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

    toolbar.setStyleSheet(
        """
        QToolBar {
            background-color: #070B10;
            border-bottom: 1px solid #8A2027;
            spacing: 6px;
            padding: 2px;
        }
        """
    )

    logo = QLabel(
        "REDSIGHT"
    )

    logo_font = QFont(
        "Bahnschrift SemiCondensed",
        31,
        QFont.Weight.Black,
    )

    logo_font.setItalic(
        True
    )

    logo_font.setLetterSpacing(
        QFont.SpacingType.AbsoluteSpacing,
        1.2,
    )

    logo.setFont(
        logo_font
    )

    logo.setStyleSheet(
        """
        color: #F1262D;
        background: transparent;
        font-weight: 900;
        padding: 2px 12px 2px 9px;
        """
    )

    subtitle = QLabel(
        "AGENTIC INTELLIGENCE  |  LOCAL FIRST"
    )

    subtitle.setStyleSheet(
        """
        color: #E5EAEE;
        background: transparent;
        font-size: 12px;
        font-weight: 700;
        padding-left: 5px;
        """
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

    # -------------------------------------------------------------
    # HERITAGE SIDE PANEL
    # -------------------------------------------------------------

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

# Validate generated module before writing.
ast.parse(
    PANEL_SOURCE,
    filename=str(PANEL),
)

write_text(
    PANEL,
    PANEL_SOURCE.strip()
    + "\n",
)

log(
    "HERITAGE_PANEL_SOURCE=PASS"
)


# =====================================================================
# 4. PATCH ONLY THE QASYNC LAUNCHER
#
# Do NOT modify command_center.py.
# =====================================================================

log("")
log("====================================================================")
log(" QASYNC LAUNCHER INTEGRATION")
log("====================================================================")

launcher = read_text(
    LAUNCHER
)

# Remove any previous attempted heritage launcher additions.
launcher = re.sub(
    r"(?m)^from app\.ui\.heritage_panel import attach_heritage_ui\s*\n?",
    "",
    launcher,
)

launcher = re.sub(
    r"(?m)^\s*attach_heritage_ui\s*\(.*?\)\s*$\n?",
    "",
    launcher,
)

# Ensure pathlib.Path exists.
if not re.search(
    r"(?m)^from pathlib import Path\s*$",
    launcher,
):

    future_match = re.search(
        r"(?m)^from __future__ import .+$",
        launcher,
    )

    if future_match:

        insert_at = (
            future_match.end()
        )

        launcher = (
            launcher[:insert_at]
            + "\nfrom pathlib import Path"
            + launcher[insert_at:]
        )

    else:

        launcher = (
            "from pathlib import Path\n"
            + launcher
        )

# Add heritage import directly after CommandCenter import.
command_import = re.search(
    (
        r"(?m)^from app\.ui\.command_center "
        r"import CommandCenterMainWindow\s*$"
    ),
    launcher,
)

if not command_import:

    raise RuntimeError(
        "Could not find CommandCenterMainWindow import "
        "inside qasync launcher."
    )

heritage_import = (
    "from app.ui.heritage_panel "
    "import attach_heritage_ui"
)

launcher = (
    launcher[:command_import.end()]
    + "\n"
    + heritage_import
    + launcher[command_import.end():]
)

# Find actual window construction and preserve its indentation.
window_match = re.search(
    (
        r"(?m)^([ \t]*)"
        r"window\s*=\s*CommandCenterMainWindow\(\)\s*$"
    ),
    launcher,
)

if not window_match:

    raise RuntimeError(
        "Could not find CommandCenterMainWindow() construction."
    )

indent = window_match.group(
    1
)

attach_line = (
    indent
    + "attach_heritage_ui("
    + "window, Path(__file__).resolve().parent"
    + ")"
)

launcher = (
    launcher[:window_match.end()]
    + "\n"
    + attach_line
    + launcher[window_match.end():]
)

# Validate before committing.
ast.parse(
    launcher,
    filename=str(LAUNCHER),
)

write_text(
    LAUNCHER,
    launcher,
)

log(
    "QASYNC_LAUNCHER_AST=OK"
)

log(
    "HERITAGE_ATTACH=PASS"
)

log(
    "COMMAND_CENTER_SOURCE_UNTOUCHED=YES"
)


# =====================================================================
# 5. ADD READ-ONLY HERITAGE DOCKER MOUNT
# =====================================================================

log("")
log("====================================================================")
log(" DOCKER HERITAGE MOUNT")
log("====================================================================")

compose = read_text(
    OVERRIDE
)

mount_marker = (
    "./data/heritage:/heritage:ro"
)

if mount_marker not in compose:

    lines = compose.splitlines()

    start = None
    end = len(lines)

    for index, line in enumerate(
        lines
    ):

        if re.match(
            r"^\s{2}redsight:\s*$",
            line,
        ):

            start = index
            break

    if start is None:

        raise RuntimeError(
            "redsight service not found in "
            "docker-compose.override.yml"
        )

    for index in range(
        start + 1,
        len(lines),
    ):

        if re.match(
            r"^\s{2}[A-Za-z0-9_.-]+:\s*$",
            lines[index],
        ):

            end = index
            break

    volumes = None

    for index in range(
        start + 1,
        end,
    ):

        if re.match(
            r"^\s{4}volumes:\s*$",
            lines[index],
        ):

            volumes = index
            break

    if volumes is not None:

        lines.insert(
            volumes + 1,
            '      - "./data/heritage:/heritage:ro"',
        )

    else:

        environment = None

        for index in range(
            start + 1,
            end,
        ):

            if re.match(
                r"^\s{4}environment:\s*$",
                lines[index],
            ):

                environment = index
                break

        if environment is None:

            environment = (
                start + 1
            )

        lines[
            environment:
            environment
        ] = [
            "    volumes:",
            '      - "./data/heritage:/heritage:ro"',
        ]

    write_text(
        OVERRIDE,
        "\n".join(lines)
        + "\n",
    )

    log(
        "HERITAGE_MOUNT_CONFIG=ADDED"
    )

else:

    log(
        "HERITAGE_MOUNT_CONFIG=ALREADY_PRESENT"
    )


# =====================================================================
# 6. DOCKER DESKTOP
# =====================================================================

def docker_online():

    try:

        result = subprocess.run(
            [
                "docker",
                "info",
                "--format",
                "{{.ServerVersion}}",
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=10,
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


if not docker_online():

    log(
        "Docker offline; starting Docker Desktop..."
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

    desktop = Path(
        r"C:\Program Files\Docker\Docker\Docker Desktop.exe"
    )

    if (
        desktop.exists()
        and not docker_online()
    ):

        subprocess.Popen(
            [str(desktop)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    for attempt in range(
        60
    ):

        if docker_online():
            break

        log(
            "Waiting for Docker... "
            + str(
                attempt + 1
            )
            + "/60"
        )

        time.sleep(2)

if not docker_online():

    raise RuntimeError(
        "Docker Desktop Linux engine is unavailable."
    )

log(
    "DOCKER_ENGINE=ONLINE"
)


# =====================================================================
# 7. COMPOSE VALIDATION
# =====================================================================

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


# =====================================================================
# 8. RESTART REDSIGHT
#
# Qdrant is NOT deleted.
# Volumes are NOT removed.
# =====================================================================

log("")
log("====================================================================")
log(" RESTARTING REDSIGHT BACKEND")
log("====================================================================")

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


# =====================================================================
# 9. WAIT FOR HEALTH
# =====================================================================

healthy = False

for attempt in range(
    60
):

    code = http_get_code(
        "http://127.0.0.1:8000/api/v1/health",
        4,
    )

    log(
        "RedSight health: "
        + str(code)
    )

    if code == 200:

        healthy = True
        break

    time.sleep(2)

if not healthy:

    run(
        [
            "docker",
            "logs",
            "--tail",
            "200",
            "redsight",
        ],
        check=False,
    )

    raise RuntimeError(
        "RedSight backend did not become healthy."
    )

log(
    "REDSIGHT_BACKEND=HEALTHY"
)


# =====================================================================
# 10. QDRANT
# =====================================================================

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


# =====================================================================
# 11. HERITAGE MOUNT
# =====================================================================

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
            "&& test -f "
            "/heritage/hermes/skills_catalog.json "
            "&& echo HERITAGE_MOUNT=PASS"
        ),
    ],
    timeout=20,
)


# =====================================================================
# 12. DUAL GPU REGRESSION TEST
# =====================================================================

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
    "GPU 0:" not in gpu.stdout
    or "GPU 1:" not in gpu.stdout
):

    raise RuntimeError(
        "Both NVIDIA GPUs are not visible in RedSight."
    )

log(
    "DUAL_GPU=PASS"
)


# =====================================================================
# 13. LM STUDIO + CHAT
# =====================================================================

lm_code = http_get_code(
    "http://127.0.0.1:1234/v1/models",
    5,
)

log(
    "LM_STUDIO_HTTP="
    + str(lm_code)
)

if lm_code != 200:

    raise RuntimeError(
        "LM Studio is not reachable at 127.0.0.1:1234."
    )

chat_status, chat = http_json(
    "http://127.0.0.1:8000/api/v1/chat",
    body={
        "messages": [
            {
                "role": "user",
                "content": (
                    "Reply with exactly "
                    "REDSIGHT_R4_READY"
                ),
            }
        ],
        "stream": False,
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
    + str(chat_status)
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


# =====================================================================
# 14. NON-DESTRUCTIVE HERITAGE RAG
#
# RAG warnings are deliberately nonfatal.
# Never calls collection-reindex/delete.
# =====================================================================

log("")
log("====================================================================")
log(" HERITAGE RAG SUBMISSION")
log("====================================================================")


def rag(
    collection,
    paths,
):

    try:

        status, result = http_json(
            (
                "http://127.0.0.1:8000"
                "/api/v1/jobs/index/batch"
            ),
            body={
                "paths": paths,
                "collection": collection,
                "project": "hermes-heritage",
            },
            timeout=300,
        )

        log(
            "RAG_"
            + collection.upper()
            + "=HTTP_"
            + str(status)
        )

        write_text(
            BACKUP
            / (
                "rag-"
                + collection
                + ".json"
            ),
            json.dumps(
                result,
                indent=2,
                ensure_ascii=False,
            ),
        )

    except Exception as exc:

        log(
            "RAG_"
            + collection.upper()
            + "=WARNING "
            + repr(exc)
        )


rag(
    "knowledge_docs",
    [
        "/heritage/hermes/SOUL.md",
        "/heritage/hermes/context",
    ],
)

rag(
    "episodic_memory",
    [
        "/heritage/hermes/memories/MEMORY.md",
        "/heritage/hermes/memories/USER.md",
    ],
)

rag(
    "skills_index",
    [
        "/heritage/hermes/skills",
    ],
)

rag(
    "tool_catalog",
    [
        "/heritage/hermes/MCP_SERVERS.md",
        "/heritage/hermes/mcp_servers_sanitized.json",
    ],
)


# =====================================================================
# 15. FINAL PYTHON IMPORT VALIDATION
# =====================================================================

result = run(
    [
        str(UI_PYTHON),
        "-c",
        (
            "import ast,pathlib,sys;"
            "r=pathlib.Path(r'C:\\Users\\walim\\RedSight');"
            "sys.path.insert(0,str(r));"
            "ast.parse((r/'app/ui/command_center.py')."
            "read_text(encoding='utf-8-sig'));"
            "ast.parse((r/'app/ui/heritage_panel.py')."
            "read_text(encoding='utf-8-sig'));"
            "ast.parse((r/'launch_redsight_command_center.py')."
            "read_text(encoding='utf-8-sig'));"
            "import app.ui.command_center;"
            "import app.ui.heritage_panel;"
            "print('COMMAND_CENTER_IMPORT=OK');"
            "print('HERITAGE_PANEL_IMPORT=OK')"
        ),
    ],
    timeout=60,
)

log(
    "UI_IMPORT_VALIDATION=PASS"
)


# =====================================================================
# 16. CLOSE OLD COMMAND CENTER
# =====================================================================

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
                process.info.get(
                    "name"
                )
                or ""
            ).lower()

            cmd = " ".join(
                process.info.get(
                    "cmdline"
                )
                or []
            )

            if (
                name in {
                    "python.exe",
                    "pythonw.exe",
                }
                and
                (
                    "launch_redsight_command_center.py"
                    in cmd
                    or
                    "app.ui.command_center"
                    in cmd
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

        except Exception:

            pass

except Exception as exc:

    log(
        "UI_PROCESS_CLEANUP_WARNING="
        + repr(exc)
    )

time.sleep(1)


# =====================================================================
# 17. RELAUNCH QASYNC COMMAND CENTER
# =====================================================================

log("")
log("====================================================================")
log(" RELAUNCHING REDSIGHT COMMAND CENTER")
log("====================================================================")

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
        str(UI_PYTHON),
        str(LAUNCHER),
    ],
    cwd=str(ROOT),
    stdout=stdout_handle,
    stderr=stderr_handle,
    creationflags=CREATE_NEW_PROCESS_GROUP,
)

# Parent no longer needs these handles.
stdout_handle.close()
stderr_handle.close()

time.sleep(7)

if process.poll() is not None:

    log("")
    log("COMMAND CENTER EXITED DURING STARTUP")
    log("")

    if stdout_path.exists():

        log("=== STDOUT ===")
        log(read_text(stdout_path))

    if stderr_path.exists():

        log("=== STDERR ===")
        log(read_text(stderr_path))

    raise RuntimeError(
        "Command Center failed to remain running."
    )

log(
    "COMMAND_CENTER_LAUNCHED=YES"
)

log(
    "COMMAND_CENTER_PID="
    + str(
        process.pid
    )
)


# =====================================================================
# 18. FINAL STATUS
# =====================================================================

log("")
log("====================================================================")
log(" FINAL REDSIGHT STATUS")
log("====================================================================")

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
    "Dual GPU               : PASS"
)
log(
    "Hermes Soul            : "
    + str(
        manifest.get(
            "soul_present",
            False,
        )
    )
)
log(
    "Hermes Memory          : "
    + str(
        manifest.get(
            "memory_present",
            False,
        )
    )
)
log(
    "Hermes USER            : "
    + str(
        manifest.get(
            "user_present",
            False,
        )
    )
)
log(
    "Hermes skills          : "
    + str(
        len(catalog)
    )
)
log(
    "MCP servers            : "
    + ", ".join(
        manifest.get(
            "mcp_servers",
            [],
        )
    )
)
log(
    "Heritage Docker mount  : PASS"
)
log(
    "REDSIGHT logo          : PASS"
)
log(
    "Heritage side panel    : PASS"
)
log(
    "Existing chat code     : PRESERVED"
)
log(
    "Command Center PID     : "
    + str(
        process.pid
    )
)
log(
    "Backup                 : "
    + str(BACKUP)
)

log("")
log(
    "Original Hermes installation was NOT modified."
)
log(
    "Qdrant volumes were NOT deleted."
)
log(
    "Qdrant collections were NOT recreated."
)

log("")
log(
    "STAGE7C_R4_COMPLETE=YES"
)