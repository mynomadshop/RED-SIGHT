$ErrorActionPreference = "Stop"

$Root       = "C:\Users\walim\RedSight"
$UiPython   = Join-Path $Root ".venv-ui\Scripts\python.exe"
$Override   = Join-Path $Root "docker-compose.override.yml"
$Launcher   = Join-Path $Root "launch_redsight_command_center.py"
$UI         = Join-Path $Root "app\ui\command_center.py"

$Stamp      = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot = Join-Path $Root ".repair-backups\stage7c-r2-$Stamp"
$PythonFile = Join-Path $BackupRoot "stage7c_r2_migrate.py"

$Utf8 = New-Object System.Text.UTF8Encoding($false)

Set-Location $Root

New-Item `
    -ItemType Directory `
    -Path $BackupRoot `
    -Force |
    Out-Null

Write-Host ""
Write-Host "===================================================================="
Write-Host " REDSIGHT STAGE-7C-R2"
Write-Host " SAFE HERMES HERITAGE MIGRATION + UI + RAG"
Write-Host "===================================================================="
Write-Host ""

foreach ($Required in @(
    $UiPython,
    $Override,
    $Launcher,
    $UI
)) {
    if (-not (Test-Path $Required)) {
        throw "Required file missing: $Required"
    }
}

# ---------------------------------------------------------------------
# Backup anything this stage can modify.
# ---------------------------------------------------------------------

Copy-Item `
    $UI `
    (Join-Path $BackupRoot "command_center.py.before") `
    -Force

Copy-Item `
    $Launcher `
    (Join-Path $BackupRoot "launcher.before.py") `
    -Force

Copy-Item `
    $Override `
    (Join-Path $BackupRoot "docker-compose.override.yml.before") `
    -Force

$Panel =
    Join-Path $Root "app\ui\heritage_panel.py"

if (Test-Path $Panel) {
    Copy-Item `
        $Panel `
        (Join-Path $BackupRoot "heritage_panel.py.before") `
        -Force
}

Write-Host "Backup:"
Write-Host $BackupRoot
Write-Host ""

# =====================================================================
# Build a real Python migration program.
#
# IMPORTANT:
# We use a DOUBLE-QUOTED PowerShell here-string inside this generated
# .ps1. The Python code contains no PowerShell variables, so the quote
# collisions that broke Stage-7C are eliminated.
# =====================================================================

$PythonCode = @"
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path


ROOT = Path(sys.argv[1]).resolve()
HERITAGE = ROOT / "data" / "heritage" / "hermes"
PANEL = ROOT / "app" / "ui" / "heritage_panel.py"
COMMAND_CENTER = ROOT / "app" / "ui" / "command_center.py"
LAUNCHER = ROOT / "launch_redsight_command_center.py"
OVERRIDE = ROOT / "docker-compose.override.yml"

LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA", ""))
USERPROFILE = Path(os.environ.get("USERPROFILE", ""))
APPDATA = Path(os.environ.get("APPDATA", ""))

PRIVATE_ROOT = LOCALAPPDATA / "RedSight" / "private"
PRIVATE_ROOT.mkdir(parents=True, exist_ok=True)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig", errors="replace")
    except Exception:
        return ""


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def discover_hermes_home() -> Path:
    candidates = []

    env_home = os.environ.get("HERMES_HOME")
    if env_home:
        candidates.append(Path(env_home))

    candidates.extend(
        [
            LOCALAPPDATA / "hermes",
            USERPROFILE / ".hermes",
            APPDATA / "hermes",
        ]
    )

    seen = set()

    for candidate in candidates:
        try:
            candidate = candidate.resolve()
        except Exception:
            pass

        key = str(candidate).lower()
        if key in seen:
            continue
        seen.add(key)

        if not candidate.exists():
            continue

        if (
            (candidate / "config.yaml").exists()
            or (candidate / "memories").exists()
            or (candidate / "skills").exists()
        ):
            return candidate

    raise RuntimeError("Could not locate Hermes home")


HERMES_HOME = discover_hermes_home()

print("HERMES_HOME=" + str(HERMES_HOME))

# ---------------------------------------------------------------------
# Recreate derived RedSight heritage copy only.
# Original Hermes is untouched.
# ---------------------------------------------------------------------

if HERITAGE.exists():
    shutil.rmtree(HERITAGE)

(HERITAGE / "memories").mkdir(parents=True, exist_ok=True)
(HERITAGE / "skills").mkdir(parents=True, exist_ok=True)
(HERITAGE / "context").mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------
# SOUL
# ---------------------------------------------------------------------

soul_candidates = [
    HERMES_HOME / "SOUL.md",
    USERPROFILE / ".hermes" / "SOUL.md",
]

soul_source = next((p for p in soul_candidates if p.exists()), None)

if soul_source is None:
    try:
        soul_source = next(
            p
            for p in HERMES_HOME.rglob("SOUL.md")
            if ".archive" not in str(p).lower()
        )
    except StopIteration:
        soul_source = None

if soul_source:
    shutil.copy2(soul_source, HERITAGE / "SOUL.md")
    print("SOUL_SOURCE=" + str(soul_source))
else:
    write_text(
        HERITAGE / "SOUL.md",
        "# Hermes Soul\n\nNo SOUL.md was found during migration.\n",
    )
    print("SOUL_SOURCE=NOT_FOUND")

# ---------------------------------------------------------------------
# MEMORY / USER
# ---------------------------------------------------------------------

for name in ("MEMORY.md", "USER.md"):
    candidates = [
        HERMES_HOME / "memories" / name,
        HERMES_HOME / name,
        USERPROFILE / ".hermes" / "memories" / name,
    ]

    source = next((p for p in candidates if p.exists()), None)

    if source:
        shutil.copy2(source, HERITAGE / "memories" / name)
        print(name + "_SOURCE=" + str(source))
    else:
        print(name + "_SOURCE=NOT_FOUND")

# ---------------------------------------------------------------------
# Additional useful instruction/context files
# ---------------------------------------------------------------------

for filename in (
    "AGENTS.md",
    "HERMES.md",
    ".hermes.md",
    "CLAUDE.md",
):
    for base in (HERMES_HOME, USERPROFILE, ROOT):
        candidate = base / filename

        if not candidate.exists():
            continue

        safe_base = re.sub(
            r"[^A-Za-z0-9_.-]+",
            "_",
            base.name or "root",
        )

        destination = (
            HERITAGE
            / "context"
            / (safe_base + "-" + filename)
        )

        shutil.copy2(candidate, destination)

# ---------------------------------------------------------------------
# Local/self-taught Hermes skills.
# ---------------------------------------------------------------------

skill_roots = [
    ("hermes-home", HERMES_HOME / "skills"),
    ("dot-hermes", USERPROFILE / ".hermes" / "skills"),
]

ignore = shutil.ignore_patterns(
    ".archive",
    "__pycache__",
    ".git",
    "node_modules",
    "*.pyc",
)

for label, source in skill_roots:
    if not source.exists():
        print("SKILL_ROOT_MISSING=" + str(source))
        continue

    destination = HERITAGE / "skills" / label

    shutil.copytree(
        source,
        destination,
        dirs_exist_ok=True,
        ignore=ignore,
    )

    print(
        "SKILL_ROOT_COPIED="
        + str(source)
        + " -> "
        + str(destination)
    )

# ---------------------------------------------------------------------
# Cron / scheduled agent definitions.
# ---------------------------------------------------------------------

cron_source = HERMES_HOME / "cron"

if cron_source.exists():
    shutil.copytree(
        cron_source,
        HERITAGE / "cron",
        dirs_exist_ok=True,
        ignore=ignore,
    )
    print("CRON_MIGRATED=True")
else:
    print("CRON_MIGRATED=False")

# ---------------------------------------------------------------------
# Preserve complete Hermes config privately.
# Do NOT put secrets into RAG or visible UI.
# ---------------------------------------------------------------------

config_source = HERMES_HOME / "config.yaml"
private_config = PRIVATE_ROOT / "hermes-config.yaml"

if config_source.exists():
    shutil.copy2(config_source, private_config)
    print("PRIVATE_CONFIG=" + str(private_config))

# ---------------------------------------------------------------------
# Live Hermes inventories.
# ---------------------------------------------------------------------

def run_hermes(*args: str) -> str:
    try:
        completed = subprocess.run(
            ["hermes", *args],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=120,
        )

        output = (
            (completed.stdout or "")
            + ("\n" + completed.stderr if completed.stderr else "")
        ).strip()

        return output
    except Exception as exc:
        return "Hermes command unavailable: " + repr(exc)


mcp_output = run_hermes("mcp", "list")

write_text(
    HERITAGE / "MCP_SERVERS.md",
    (
        "# Migrated Hermes MCP Servers\n\n"
        "Source: "
        + str(HERMES_HOME)
        + "\n\n```text\n"
        + mcp_output
        + "\n```\n"
    ),
)

skill_inventory = run_hermes("skills", "list")

write_text(
    HERITAGE / "INSTALLED_SKILLS.txt",
    skill_inventory + "\n",
)

# ---------------------------------------------------------------------
# Sanitized MCP configuration.
#
# Preserve names/transport/command/args/URL but never expose secret
# environment variable VALUES or HTTP header VALUES.
# ---------------------------------------------------------------------

sanitized_mcp = {}

if config_source.exists():
    try:
        import yaml

        raw_config = yaml.safe_load(
            config_source.read_text(
                encoding="utf-8-sig",
                errors="replace",
            )
        ) or {}

        raw_servers = raw_config.get("mcp_servers", {}) or {}

        if isinstance(raw_servers, dict):
            for name, value in raw_servers.items():
                if not isinstance(value, dict):
                    sanitized_mcp[name] = {
                        "configured": True,
                    }
                    continue

                clean = {}

                for field in (
                    "transport",
                    "command",
                    "args",
                    "url",
                    "cwd",
                    "enabled",
                ):
                    if field in value:
                        clean[field] = value[field]

                env = value.get("env")
                if isinstance(env, dict):
                    clean["env_keys"] = sorted(env.keys())

                headers = value.get("headers")
                if isinstance(headers, dict):
                    clean["header_keys"] = sorted(headers.keys())

                sanitized_mcp[name] = clean

    except Exception as exc:
        sanitized_mcp = {
            "_parse_error": repr(exc),
        }

write_text(
    HERITAGE / "mcp_servers_sanitized.json",
    json.dumps(
        sanitized_mcp,
        indent=2,
        ensure_ascii=False,
    ),
)

# ---------------------------------------------------------------------
# Searchable SKILL.md catalog
# ---------------------------------------------------------------------

catalog = []

for skill_file in sorted(
    HERITAGE.rglob("SKILL.md"),
    key=lambda p: str(p).lower(),
):
    if ".archive" in str(skill_file).lower():
        continue

    content = read_text(skill_file)

    name = skill_file.parent.name
    description = ""

    name_match = re.search(
        r"(?im)^\s*name\s*:\s*[\"']?(.+?)[\"']?\s*\Z",
        content,
    )

    # Front matter lines are normally not at EOF, so also use per-line.
    for line in content.splitlines():
        stripped = line.strip()

        if stripped.lower().startswith("name:"):
            candidate = stripped.split(":", 1)[1].strip().strip("\"'")
            if candidate:
                name = candidate
                break

    for line in content.splitlines():
        stripped = line.strip()

        if stripped.lower().startswith("description:"):
            candidate = stripped.split(":", 1)[1].strip().strip("\"'")
            if candidate:
                description = candidate
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

            if block.startswith("---"):
                continue

            if block.startswith("#"):
                continue

            if len(block) >= 20:
                description = re.sub(
                    r"\s+",
                    " ",
                    block,
                )[:400]
                break

    digest = hashlib.sha256(
        skill_file.read_bytes()
    ).hexdigest()

    relative = skill_file.relative_to(HERITAGE)

    parts = relative.parts
    source = "unknown"

    if len(parts) >= 2 and parts[0] == "skills":
        source = parts[1]

    catalog.append(
        {
            "Name": name,
            "Description": description,
            "Source": source,
            "RelativePath": str(relative),
            "SHA256": digest,
            "Size": skill_file.stat().st_size,
            "Modified": skill_file.stat().st_mtime,
        }
    )

catalog.sort(
    key=lambda item: (
        item["Name"].lower(),
        item["Source"].lower(),
    )
)

write_text(
    HERITAGE / "skills_catalog.json",
    json.dumps(
        catalog,
        indent=2,
        ensure_ascii=False,
    ),
)

print("MIGRATED_SKILL_COUNT=" + str(len(catalog)))

# ---------------------------------------------------------------------
# Heritage manifest
# ---------------------------------------------------------------------

manifest = {
    "source": "Hermes Agent",
    "hermes_home": str(HERMES_HOME),
    "soul_present": (HERITAGE / "SOUL.md").exists(),
    "memory_present": (
        HERITAGE / "memories" / "MEMORY.md"
    ).exists(),
    "user_present": (
        HERITAGE / "memories" / "USER.md"
    ).exists(),
    "skill_count": len(catalog),
    "cron_present": (HERITAGE / "cron").exists(),
    "mcp_servers": sorted(
        key
        for key in sanitized_mcp.keys()
        if not key.startswith("_")
    ),
    "private_config": str(private_config),
    "mode": (
        "preserved + visible + RAG + "
        "command-center-context-inheritance"
    ),
}

write_text(
    HERITAGE / "heritage_manifest.json",
    json.dumps(
        manifest,
        indent=2,
        ensure_ascii=False,
    ),
)

# =====================================================================
# COMMAND CENTER HERITAGE CONTEXT
# =====================================================================

command_source = read_text(COMMAND_CENTER)

begin = "# REDSIGHT_HERITAGE_CONTEXT_BEGIN"
end = "# REDSIGHT_HERITAGE_CONTEXT_END"

command_source = re.sub(
    re.escape(begin)
    + r".*?"
    + re.escape(end)
    + r"\s*",
    "",
    command_source,
    flags=re.S,
)

helper = r'''
# REDSIGHT_HERITAGE_CONTEXT_BEGIN
def _extract_redsight_message(data):
    if not isinstance(data, dict):
        return None

    message = data.get("message")

    if isinstance(message, str) and message.strip():
        return message.strip()

    for key in (
        "response",
        "content",
        "answer",
        "reply",
        "text",
        "output",
        "result",
    ):
        value = data.get(key)

        if isinstance(value, str) and value.strip():
            return value.strip()

    choices = data.get("choices")

    if isinstance(choices, list) and choices:
        first = choices[0]

        if isinstance(first, dict):
            msg = first.get("message")

            if isinstance(msg, dict):
                content = msg.get("content")

                if isinstance(content, str) and content.strip():
                    return content.strip()

    return None


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
            "You are RedSight. You have inherited selected identity, "
            "memory, user-profile and procedural knowledge from the "
            "user's Hermes Agent. Use inherited material when relevant. "
            "Current user instructions have priority. SKILL.md files "
            "describe procedures; never claim a procedure or MCP tool "
            "was executed unless it actually was."
        )
    ]

    budget = 20000
    used = 0

    def add_file(label, path, limit):
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

        room = max(0, budget - used)
        text = text[: min(limit, room)]

        if not text:
            return

        part = "[" + label + "]\n" + text
        parts.append(part)
        used += len(part)

    add_file(
        "Inherited Hermes SOUL",
        root / "SOUL.md",
        4000,
    )

    add_file(
        "Inherited Hermes MEMORY",
        root / "memories" / "MEMORY.md",
        5000,
    )

    add_file(
        "Inherited Hermes USER profile",
        root / "memories" / "USER.md",
        3000,
    )

    try:
        catalog = json.loads(
            (root / "skills_catalog.json").read_text(
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
            str(item.get("Name", ""))
            + " "
            + str(item.get("Description", ""))
        ).lower()

        score = sum(
            1
            for term in terms
            if term in haystack
        )

        if score:
            ranked.append((score, item))

    ranked.sort(
        key=lambda pair: pair[0],
        reverse=True,
    )

    for _, item in ranked[:2]:
        relative = item.get("RelativePath")

        if not relative:
            continue

        add_file(
            "Relevant inherited Hermes skill: "
            + str(item.get("Name", "skill")),
            root / relative,
            3000,
        )

    add_file(
        "Migrated MCP inventory",
        root / "MCP_SERVERS.md",
        1500,
    )

    return [
        {
            "role": "system",
            "content": "\n\n".join(parts),
        },
        {
            "role": "user",
            "content": str(message),
        },
    ]
# REDSIGHT_HERITAGE_CONTEXT_END
'''

class_match = re.search(
    r"(?m)^class\s+CommandCenterMainWindow\b",
    command_source,
)

if not class_match:
    raise RuntimeError(
        "CommandCenterMainWindow class not found"
    )

command_source = (
    command_source[: class_match.start()]
    + helper
    + "\n\n"
    + command_source[class_match.start() :]
)

# ---------------------------------------------------------------------
# Locate _send_to_api and wire inherited messages.
# ---------------------------------------------------------------------

lines = command_source.splitlines()

method_start = None
method_end = len(lines)

for index, line in enumerate(lines):
    if re.match(
        r"^\s{4}async\s+def\s+_send_to_api\s*\(",
        line,
    ):
        method_start = index
        break

if method_start is None:
    raise RuntimeError(
        "_send_to_api method not found"
    )

for index in range(
    method_start + 1,
    len(lines),
):
    if re.match(
        r"^\s{4}(?:async\s+def|def)\s+\w+\s*\(",
        lines[index],
    ):
        method_end = index
        break

request_done = False

for index in range(
    method_start,
    method_end,
):
    line = lines[index]

    if (
        "json=" in line
        and '"messages"' in line
    ):
        indentation = line[: len(line) - len(line.lstrip())]

        lines[index] = (
            indentation
            + 'json={"messages": '
            + '_redsight_heritage_messages(message), '
            + '"stream": False},'
        )

        request_done = True
        break

if not request_done:
    raise RuntimeError(
        "Could not locate messages JSON request "
        "inside _send_to_api"
    )

# ---------------------------------------------------------------------
# Make absolutely sure RedSight top-level message responses work.
# ---------------------------------------------------------------------

parser_done = False

for index in range(
    method_start,
    method_end,
):
    stripped = lines[index].strip()

    if (
        stripped.startswith("response =")
        and "data.get(" in stripped
    ):
        indentation = (
            lines[index][
                : len(lines[index])
                - len(lines[index].lstrip())
            ]
        )

        lines[index] = (
            indentation
            + "response = "
            + "_extract_redsight_message(data) "
            + 'or "No response"'
        )

        parser_done = True
        break

if not parser_done:
    for index in range(
        method_start,
        method_end,
    ):
        if (
            'response = response or "No response"'
            in lines[index]
        ):
            indentation = (
                lines[index][
                    : len(lines[index])
                    - len(lines[index].lstrip())
                ]
            )

            lines[index] = (
                indentation
                + "response = response or "
                + "_extract_redsight_message(data) "
                + 'or "No response"'
            )

            parser_done = True
            break

command_source = "\n".join(lines) + "\n"

ast.parse(
    command_source,
    filename=str(COMMAND_CENTER),
)

write_text(
    COMMAND_CENTER,
    command_source,
)

print("COMMAND_CENTER_HERITAGE=PASS")

# =====================================================================
# HERMES HERITAGE SIDE PANEL + REDSIGHT BRAND
# =====================================================================

panel_source = r'''
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDockWidget,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
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
        return "Unavailable: " + str(exc)


class HermesHeritageDock(QDockWidget):
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
        self._visible_skills = []

        self.setObjectName(
            "RedSightHermesHeritageDock"
        )

        self.setMinimumWidth(430)

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
            self._build_skills(),
            "Skills",
        )

        tabs.addTab(
            self.mcp,
            "MCP",
        )

        holder = QWidget()
        layout = QVBoxLayout(holder)

        layout.setContentsMargins(
            5,
            5,
            5,
            5,
        )

        layout.addWidget(tabs)

        self.setWidget(holder)

        self.setStyleSheet(
            """
            QDockWidget {
                color: #FFFFFF;
                font-weight: 700;
            }

            QDockWidget::title {
                background: #19090B;
                color: #FF3038;
                padding: 8px;
                border-bottom: 1px solid #8B2026;
            }

            QTabWidget::pane {
                border: 1px solid #49343A;
                background: #0B1015;
            }

            QTabBar::tab {
                background: #171D24;
                color: #DCE4EA;
                padding: 7px 9px;
            }

            QTabBar::tab:selected {
                background: #9D1D24;
                color: #FFFFFF;
            }

            QTextBrowser,
            QListWidget,
            QLineEdit {
                background: #0C1218;
                color: #F4F7F9;
                border: 1px solid #3B4854;
                selection-background-color: #A91F27;
                selection-color: #FFFFFF;
            }

            QLineEdit {
                padding: 7px;
                border-radius: 5px;
            }
            """
        )

        self.refresh()

    def _build_skills(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        self.skill_search = QLineEdit()

        self.skill_search.setPlaceholderText(
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
            [270, 430]
        )

        layout.addWidget(
            self.skill_search
        )

        layout.addWidget(
            splitter
        )

        self.skill_search.textChanged.connect(
            self._filter_skills
        )

        self.skill_list.currentRowChanged.connect(
            self._show_skill
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
            + "Hermes source: "
            + str(
                manifest.get(
                    "hermes_home",
                    "unknown",
                )
            )
            + "\n"
            + "Inherited skills: "
            + str(
                manifest.get(
                    "skill_count",
                    0,
                )
            )
            + "\n"
            + "Soul migrated: "
            + str(
                manifest.get(
                    "soul_present",
                    False,
                )
            )
            + "\n"
            + "Memory migrated: "
            + str(
                manifest.get(
                    "memory_present",
                    False,
                )
            )
            + "\n"
            + "USER migrated: "
            + str(
                manifest.get(
                    "user_present",
                    False,
                )
            )
            + "\n"
            + "Cron migrated: "
            + str(
                manifest.get(
                    "cron_present",
                    False,
                )
            )
            + "\n"
            + "MCP servers: "
            + (
                ", ".join(mcp_servers)
                if mcp_servers
                else "see MCP tab"
            )
            + "\n\n"
            + "Soul, memory, user context and relevant "
            + "procedural skills are inherited by "
            + "Command Center chat."
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

        self._filter_skills(
            self.skill_search.text()
        )

    def _filter_skills(
        self,
        text,
    ):
        query = str(text).strip().lower()

        self.skill_list.clear()
        self._visible_skills = []

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

            self._visible_skills.append(
                skill
            )

            self.skill_list.addItem(
                "{}   [{}]".format(
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

    def _show_skill(
        self,
        row,
    ):
        if (
            row < 0
            or row
            >= len(
                self._visible_skills
            )
        ):
            return

        item = self._visible_skills[row]

        relative = item.get(
            "RelativePath",
            "",
        )

        path = (
            self.root
            / relative
        )

        header = (
            "NAME: {}\n"
            "SOURCE: {}\n"
            "SHA256: {}\n"
            "PATH: {}\n\n"
        ).format(
            item.get(
                "Name",
                "",
            ),
            item.get(
                "Source",
                "",
            ),
            item.get(
                "SHA256",
                "",
            ),
            relative,
        )

        self.skill_detail.setPlainText(
            header
            + _read(path)
        )


def attach_heritage_ui(
    window,
    root,
):
    root = Path(root)

    heritage = (
        root
        / "data"
        / "heritage"
        / "hermes"
    )

    toolbar = QToolBar(
        "RedSight Brand",
        window,
    )

    toolbar.setObjectName(
        "RedSightBrandToolbar"
    )

    toolbar.setMovable(False)
    toolbar.setFloatable(False)

    logo = QLabel(
        "REDSIGHT"
    )

    font = QFont(
        "Bahnschrift SemiCondensed",
        30,
        QFont.Weight.Black,
    )

    font.setItalic(True)

    logo.setFont(font)

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
        "font-weight:650;"
        "padding-left:5px;"
    )

    toolbar.setStyleSheet(
        "QToolBar {"
        "background:#070B10;"
        "border-bottom:1px solid #762027;"
        "spacing:5px;"
        "}"
    )

    toolbar.addWidget(logo)
    toolbar.addWidget(subtitle)

    window.addToolBar(
        Qt.ToolBarArea.TopToolBarArea,
        toolbar,
    )

    dock = HermesHeritageDock(
        heritage,
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

panel_source = textwrap.dedent(
    panel_source
).lstrip()

ast.parse(
    panel_source,
    filename=str(PANEL),
)

write_text(
    PANEL,
    panel_source,
)

print("HERITAGE_PANEL=PASS")

# =====================================================================
# Attach heritage UI to existing qasync launcher.
# =====================================================================

launcher_source = read_text(LAUNCHER)

command_import = (
    "from app.ui.command_center "
    "import CommandCenterMainWindow"
)

heritage_import = (
    "from app.ui.heritage_panel "
    "import attach_heritage_ui"
)

if heritage_import not in launcher_source:
    if command_import not in launcher_source:
        raise RuntimeError(
            "CommandCenterMainWindow import "
            "not found in launcher"
        )

    launcher_source = launcher_source.replace(
        command_import,
        command_import
        + "\n"
        + heritage_import,
        1,
    )

window_anchor = (
    "window = CommandCenterMainWindow()"
)

attach_line = (
    "attach_heritage_ui(window, ROOT)"
)

if attach_line not in launcher_source:
    if window_anchor not in launcher_source:
        raise RuntimeError(
            "CommandCenterMainWindow creation "
            "not found in launcher"
        )

    launcher_source = launcher_source.replace(
        window_anchor,
        window_anchor
        + "\n"
        + attach_line,
        1,
    )

ast.parse(
    launcher_source,
    filename=str(LAUNCHER),
)

write_text(
    LAUNCHER,
    launcher_source,
)

print("LAUNCHER_HERITAGE=PASS")

# =====================================================================
# Persist read-only heritage mount into existing Compose override.
# =====================================================================

compose_lines = read_text(
    OVERRIDE
).splitlines()

service_start = None
service_end = len(compose_lines)

for index, line in enumerate(
    compose_lines
):
    if re.match(
        r"^\s{2}redsight:\s*\Z",
        line,
    ):
        service_start = index
        break

if service_start is None:
    raise RuntimeError(
        "redsight service not found "
        "in docker-compose.override.yml"
    )

for index in range(
    service_start + 1,
    len(compose_lines),
):
    if re.match(
        r"^\s{2}[A-Za-z0-9_.-]+:\s*\Z",
        compose_lines[index],
    ):
        service_end = index
        break

block = compose_lines[
    service_start:service_end
]

mount_text = (
    "./data/heritage:/heritage:ro"
)

if not any(
    mount_text in line
    for line in block
):
    volume_index = None

    for index in range(
        service_start + 1,
        service_end,
    ):
        if re.match(
            r"^\s{4}volumes:\s*\Z",
            compose_lines[index],
        ):
            volume_index = index
            break

    if volume_index is not None:
        compose_lines.insert(
            volume_index + 1,
            '      - "./data/heritage:/heritage:ro"',
        )
    else:
        environment_index = None

        for index in range(
            service_start + 1,
            service_end,
        ):
            if re.match(
                r"^\s{4}environment:\s*\Z",
                compose_lines[index],
            ):
                environment_index = index
                break

        if environment_index is None:
            environment_index = (
                service_start + 1
            )

        compose_lines[
            environment_index:
            environment_index
        ] = [
            "    volumes:",
            '      - "./data/heritage:/heritage:ro"',
        ]

    write_text(
        OVERRIDE,
        "\n".join(
            compose_lines
        )
        + "\n",
    )

    print(
        "HERITAGE_COMPOSE_MOUNT=ADDED"
    )
else:
    print(
        "HERITAGE_COMPOSE_MOUNT=ALREADY_PRESENT"
    )

# ---------------------------------------------------------------------
# Final syntax validation.
# ---------------------------------------------------------------------

for path in (
    COMMAND_CENTER,
    PANEL,
    LAUNCHER,
):
    source = read_text(path)

    ast.parse(
        source,
        filename=str(path),
    )

    print(
        "AST_OK="
        + str(
            path.relative_to(ROOT)
        )
    )

print("STAGE7C_R2_MIGRATION=PASS")
"@

[System.IO.File]::WriteAllText(
    $PythonFile,
    $PythonCode,
    $Utf8
)

Write-Host "=== Running safe migration program ==="

& $UiPython `
    $PythonFile `
    $Root

if ($LASTEXITCODE -ne 0) {
    throw "Stage-7C-R2 migration program failed."
}

Write-Host ""

# =====================================================================
# Secure the private Hermes configuration copy.
# =====================================================================

$PrivateRoot =
    Join-Path $env:LOCALAPPDATA "RedSight\private"

if (Test-Path $PrivateRoot) {

    $ErrorActionPreference = "Continue"

    icacls `
        $PrivateRoot `
        /inheritance:r `
        /grant:r "$env:USERNAME:(OI)(CI)F" `
        1>$null `
        2>$null

    $ErrorActionPreference = "Stop"
}

# =====================================================================
# Docker recovery helper
# =====================================================================

function Test-Docker {

    $ErrorActionPreference = "Continue"

    docker info `
        1>$null `
        2>$null

    $Result =
        $LASTEXITCODE

    $ErrorActionPreference = "Stop"

    return ($Result -eq 0)
}

Write-Host "===================================================================="
Write-Host " VERIFYING DOCKER DESKTOP"
Write-Host "===================================================================="

if (-not (Test-Docker)) {

    Write-Host "Docker engine offline. Starting Docker Desktop..."

    $ErrorActionPreference = "Continue"

    docker desktop start --detach `
        2>$null

    $ErrorActionPreference = "Stop"

    if (
        -not (Test-Docker) -and
        (Test-Path "C:\Program Files\Docker\Docker\Docker Desktop.exe")
    ) {

        Start-Process `
            "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    }

    for ($i = 1; $i -le 60; $i++) {

        if (Test-Docker) {
            break
        }

        Write-Host "Waiting for Docker... $i/60"
        Start-Sleep -Seconds 2
    }
}

if (-not (Test-Docker)) {
    throw "Docker Desktop Linux engine is unavailable."
}

Write-Host "Docker engine: ONLINE"
Write-Host ""

# =====================================================================
# Validate Compose BEFORE touching running services.
# =====================================================================

Write-Host "=== Compose validation ==="

$ErrorActionPreference = "Continue"

docker compose config `
    1> (Join-Path $BackupRoot "compose-resolved.yml")

$ComposeExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

if ($ComposeExit -ne 0) {
    throw "docker compose config failed."
}

Write-Host "Compose: PASS"
Write-Host ""

# =====================================================================
# Restart RedSight only.
# Qdrant storage is not reset.
# =====================================================================

Write-Host "===================================================================="
Write-Host " RECREATING REDSIGHT WITH HERITAGE MOUNT"
Write-Host "===================================================================="

$ErrorActionPreference = "Continue"

docker compose up `
    -d `
    --force-recreate `
    redsight

$StartExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

if ($StartExit -ne 0) {
    throw "RedSight container recreation failed."
}

$Healthy =
    $false

for ($i = 1; $i -le 60; $i++) {

    $ErrorActionPreference = "Continue"

    $Code =
        curl.exe `
            -s `
            -o NUL `
            -w "%{http_code}" `
            --max-time 4 `
            http://127.0.0.1:8000/api/v1/health `
            2>$null

    $ErrorActionPreference = "Stop"

    Write-Host "RedSight health: $Code"

    if ($Code -eq "200") {

        $Healthy =
            $true

        break
    }

    Start-Sleep -Seconds 2
}

if (-not $Healthy) {

    Write-Host ""
    Write-Host "=== REDSIGHT LOG ==="

    docker logs `
        --tail 180 `
        redsight

    throw "RedSight did not become healthy."
}

Write-Host ""
Write-Host "RedSight backend: HEALTHY"
Write-Host ""

# =====================================================================
# Verify heritage mount.
# =====================================================================

Write-Host "=== Heritage mount ==="

$ErrorActionPreference = "Continue"

docker exec `
    redsight `
    sh -lc `
    "test -f /heritage/hermes/heritage_manifest.json && echo HERITAGE_MOUNT=PASS"

$MountExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

if ($MountExit -ne 0) {
    throw "Heritage mount verification failed."
}

Write-Host ""

# =====================================================================
# NON-DESTRUCTIVE RAG INGESTION
#
# We deliberately DO NOT use:
# /api/v1/collections/{collection}/reindex
#
# Only ordinary batch-index jobs are submitted.
# =====================================================================

Write-Host "===================================================================="
Write-Host " NON-DESTRUCTIVE HERMES RAG INGESTION"
Write-Host "===================================================================="

function Invoke-RagBatch {

    param(
        [string]$Collection,
        [string[]]$Paths
    )

    if (-not $Paths -or $Paths.Count -eq 0) {
        return
    }

    $Body =
        @{
            paths      = @($Paths)
            collection = $Collection
            project    = "hermes-heritage"
        } |
        ConvertTo-Json `
            -Depth 8

    Write-Host ""
    Write-Host "Collection: $Collection"
    Write-Host "Items: $($Paths.Count)"

    try {

        $Result =
            Invoke-RestMethod `
                -Uri "http://127.0.0.1:8000/api/v1/jobs/index/batch" `
                -Method Post `
                -ContentType "application/json" `
                -Body $Body `
                -TimeoutSec 600

        $Result |
            ConvertTo-Json -Depth 20 |
            Set-Content `
                -Path (
                    Join-Path `
                        $BackupRoot `
                        ("rag-" + $Collection + ".json")
                ) `
                -Encoding UTF8

        Write-Host "RAG request: PASS"
    }
    catch {

        Write-Warning (
            "RAG request for $Collection failed: "
            + $_.Exception.Message
        )

        Write-Warning (
            "Migration remains preserved. "
            + "No collection was deleted."
        )
    }
}

$HeritageRoot =
    Join-Path $Root "data\heritage\hermes"

$KnowledgePaths =
    @()

foreach ($Path in @(
    "SOUL.md",
    "context"
)) {

    if (Test-Path (Join-Path $HeritageRoot $Path)) {

        $KnowledgePaths +=
            (
                "/heritage/hermes/"
                + $Path.Replace("\","/")
            )
    }
}

Invoke-RagBatch `
    -Collection "knowledge_docs" `
    -Paths $KnowledgePaths

$MemoryPaths =
    @()

foreach ($Path in @(
    "memories\MEMORY.md",
    "memories\USER.md"
)) {

    if (Test-Path (Join-Path $HeritageRoot $Path)) {

        $MemoryPaths +=
            (
                "/heritage/hermes/"
                + $Path.Replace("\","/")
            )
    }
}

Invoke-RagBatch `
    -Collection "episodic_memory" `
    -Paths $MemoryPaths

$CatalogPath =
    Join-Path $HeritageRoot "skills_catalog.json"

if (Test-Path $CatalogPath) {

    $Catalog =
        Get-Content `
            $CatalogPath `
            -Raw |
        ConvertFrom-Json

    $SkillPaths =
        @(
            $Catalog |
            ForEach-Object {

                "/heritage/hermes/" +
                (
                    $_.RelativePath.ToString().Replace("\","/")
                )
            }
        )

    Invoke-RagBatch `
        -Collection "skills_index" `
        -Paths $SkillPaths
}

Invoke-RagBatch `
    -Collection "tool_catalog" `
    -Paths @(
        "/heritage/hermes/MCP_SERVERS.md",
        "/heritage/hermes/mcp_servers_sanitized.json"
    )

# =====================================================================
# Verify RedSight -> LM Studio chat before launching UI.
# =====================================================================

Write-Host ""
Write-Host "===================================================================="
Write-Host " VERIFYING REDSIGHT -> LM STUDIO"
Write-Host "===================================================================="

$ChatBody =
    @{
        messages =
            @(
                @{
                    role    = "user"
                    content = "Reply with exactly HERITAGE_READY"
                }
            )

        stream = $false
    } |
    ConvertTo-Json `
        -Depth 6

$Chat =
    Invoke-RestMethod `
        -Uri "http://127.0.0.1:8000/api/v1/chat" `
        -Method Post `
        -ContentType "application/json" `
        -Body $ChatBody `
        -TimeoutSec 180

Write-Host "Assistant:"
Write-Host $Chat.message
Write-Host ""

if (-not $Chat.message) {
    throw "RedSight returned no assistant message."
}

Write-Host "RedSight -> LM Studio: PASS"
Write-Host ""

# =====================================================================
# Close ONLY Command Center Python processes.
# =====================================================================

Write-Host "=== Closing old Command Center ==="

$Processes =
    @(
        Get-CimInstance `
            Win32_Process `
            -ErrorAction SilentlyContinue |
        Where-Object {

            $_.Name -match '^python(w)?\.exe$' -and
            $_.CommandLine -and
            (
                $_.CommandLine -match
                    'launch_redsight_command_center\.py' -or

                $_.CommandLine -match
                    'app\.ui\.command_center'
            )
        }
    )

foreach ($Process in $Processes) {

    Write-Host "Stopping PID $($Process.ProcessId)"

    Stop-Process `
        -Id $Process.ProcessId `
        -Force `
        -ErrorAction SilentlyContinue
}

Start-Sleep -Seconds 1

# =====================================================================
# Launch new Command Center.
# =====================================================================

Write-Host ""
Write-Host "===================================================================="
Write-Host " LAUNCHING REDSIGHT COMMAND CENTER"
Write-Host "===================================================================="

$UiStdout =
    Join-Path $BackupRoot "command-center.stdout.log"

$UiStderr =
    Join-Path $BackupRoot "command-center.stderr.log"

$UiProcess =
    Start-Process `
        -FilePath $UiPython `
        -ArgumentList @(
            $Launcher
        ) `
        -WorkingDirectory $Root `
        -RedirectStandardOutput $UiStdout `
        -RedirectStandardError $UiStderr `
        -PassThru

Start-Sleep -Seconds 6

$UiProcess.Refresh()

if ($UiProcess.HasExited) {

    Write-Host ""
    Write-Host "COMMAND CENTER FAILED TO START"
    Write-Host ""

    if (Test-Path $UiStdout) {

        Write-Host "=== STDOUT ==="

        Get-Content `
            $UiStdout `
            -Tail 120
    }

    if (Test-Path $UiStderr) {

        Write-Host ""
        Write-Host "=== STDERR ==="

        Get-Content `
            $UiStderr `
            -Tail 180
    }

    throw "Command Center failed to launch."
}

Write-Host ""
Write-Host "COMMAND_CENTER_LAUNCHED=YES"
Write-Host "PID=$($UiProcess.Id)"
Write-Host ""

# =====================================================================
# Final status
# =====================================================================

$Manifest =
    Get-Content `
        (Join-Path $HeritageRoot "heritage_manifest.json") `
        -Raw |
    ConvertFrom-Json

Write-Host "===================================================================="
Write-Host " FINAL REDSIGHT HERITAGE STATUS"
Write-Host "===================================================================="

docker compose ps

Write-Host ""

docker inspect `
    redsight `
    --format "redsight status={{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} restarts={{.RestartCount}}"

Write-Host ""

docker inspect `
    redsight-qdrant `
    --format "qdrant status={{.State.Status}} health={{.State.Health.Status}}"

Write-Host ""

docker exec `
    redsight `
    nvidia-smi -L

Write-Host ""
Write-Host "Hermes home             : $($Manifest.hermes_home)"
Write-Host "Hermes skills migrated  : $($Manifest.skill_count)"
Write-Host "SOUL migrated           : $($Manifest.soul_present)"
Write-Host "MEMORY migrated         : $($Manifest.memory_present)"
Write-Host "USER migrated           : $($Manifest.user_present)"
Write-Host "Cron migrated           : $($Manifest.cron_present)"
Write-Host "MCP servers discovered  : $($Manifest.mcp_servers -join ', ')"
Write-Host "Heritage Docker mount   : PASS"
Write-Host "RedSight -> LM Studio   : PASS"
Write-Host "Command Center PID      : $($UiProcess.Id)"
Write-Host ""
Write-Host "UI:"
Write-Host "  REDSIGHT bold red brand/logo"
Write-Host "  HERMES HERITAGE side panel"
Write-Host "  Overview"
Write-Host "  Soul"
Write-Host "  Memory / USER"
Write-Host "  Searchable Skills"
Write-Host "  MCP servers"
Write-Host ""
Write-Host "RAG collections submitted:"
Write-Host "  knowledge_docs"
Write-Host "  episodic_memory"
Write-Host "  skills_index"
Write-Host "  tool_catalog"
Write-Host ""
Write-Host "Original Hermes installation was NOT modified."
Write-Host "Qdrant volumes were NOT deleted or recreated."
Write-Host ""
Write-Host "Backup:"
Write-Host $BackupRoot
Write-Host ""
Write-Host "===================================================================="
Write-Host " STAGE-7C-R2 COMPLETE"
Write-Host "===================================================================="
Write-Host ""
