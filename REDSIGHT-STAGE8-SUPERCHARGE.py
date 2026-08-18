from __future__ import annotations

import ast
import json
import os
import re
import shutil
import textwrap
import time
from pathlib import Path


ROOT = Path(r"C:\Users\walim\RedSight")

ACTION_PACKAGE = ROOT / "redsight_actions"
ACTION_INIT = ACTION_PACKAGE / "__init__.py"
GATEWAY = ACTION_PACKAGE / "gateway.py"

UI_ACTIONS = ROOT / "app" / "ui" / "action_palette.py"

LAUNCHER = ROOT / "launch_redsight_command_center.py"

HERITAGE_ACTIONS = (
    ROOT
    / "data"
    / "heritage"
    / "redsight-actions"
)

TOOL_CATALOG = (
    HERITAGE_ACTIONS
    / "TOOL_CATALOG.md"
)

ACTION_MANIFEST = (
    HERITAGE_ACTIONS
    / "action_manifest.json"
)

LOCALAPPDATA = Path(
    os.environ["LOCALAPPDATA"]
)

APPDATA = Path(
    os.environ["APPDATA"]
)

ACTION_HOME = (
    LOCALAPPDATA
    / "RedSight"
    / "actions"
)

OUTPUT_HOME = (
    ROOT
    / "outputs"
    / "actions"
)

STAMP = time.strftime(
    "%Y%m%d-%H%M%S"
)

BACKUP = (
    ROOT
    / ".repair-backups"
    / ("stage8-" + STAMP)
)

BACKUP.mkdir(
    parents=True,
    exist_ok=True,
)

ACTION_PACKAGE.mkdir(
    parents=True,
    exist_ok=True,
)

HERITAGE_ACTIONS.mkdir(
    parents=True,
    exist_ok=True,
)

ACTION_HOME.mkdir(
    parents=True,
    exist_ok=True,
)

OUTPUT_HOME.mkdir(
    parents=True,
    exist_ok=True,
)


def log(text=""):
    print(text, flush=True)


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


for item in (
    GATEWAY,
    UI_ACTIONS,
    LAUNCHER,
):
    backup(item)


# ====================================================================
# ACTION GATEWAY
# ====================================================================

GATEWAY_SOURCE = r'''
from __future__ import annotations

import asyncio
import fnmatch
import html
import ipaddress
import json
import logging
import os
import re
import shlex
import socket
import subprocess
import time
import uuid

from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo


import httpx

from fastapi import FastAPI
from fastapi import HTTPException

from pydantic import BaseModel
from pydantic import Field

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph
from reportlab.platypus import SimpleDocTemplate
from reportlab.platypus import Spacer

from tzlocal import get_localzone_name


ROOT = Path(__file__).resolve().parents[1]

LOCALAPPDATA = Path(
    os.environ["LOCALAPPDATA"]
)

ACTION_HOME = (
    LOCALAPPDATA
    / "RedSight"
    / "actions"
)

ACTION_HOME.mkdir(
    parents=True,
    exist_ok=True,
)

OUTPUT_HOME = (
    ROOT
    / "outputs"
    / "actions"
)

OUTPUT_HOME.mkdir(
    parents=True,
    exist_ok=True,
)

HERITAGE = (
    ROOT
    / "data"
    / "heritage"
    / "hermes"
)

SECRETS_FILE = (
    ACTION_HOME
    / "secrets.json"
)

AUDIT_FILE = (
    ACTION_HOME
    / "action-audit.jsonl"
)

TASK_RESULT_FILE = (
    ACTION_HOME
    / "scheduled-results.jsonl"
)

SCHEDULER_DB = (
    ACTION_HOME
    / "scheduler.sqlite"
)

GATEWAY_LOG = (
    ACTION_HOME
    / "gateway.log"
)


logging.basicConfig(
    filename=str(GATEWAY_LOG),
    level=logging.INFO,
    format=(
        "%(asctime)s "
        "%(levelname)s "
        "%(name)s "
        "%(message)s"
    ),
)

logger = logging.getLogger(
    "redsight.actions"
)


REDSIGHT_URL = (
    "http://127.0.0.1:8000"
)

BRAVE_URL = (
    "https://api.search.brave.com"
    "/res/v1/web/search"
)


# ====================================================================
# TOOL DEFINITIONS
# ====================================================================

TOOL_SPECS: dict[str, dict[str, Any]] = {

    "web.search": {
        "description":
            "Search the live web using Brave Search API.",
        "risk": "read",
        "approval": False,
        "agent": True,
        "params":
            "query:str, count:int<=20, freshness?:str",
    },

    "browser.read": {
        "description":
            "Open a public web page in Chromium and extract readable text.",
        "risk": "read",
        "approval": False,
        "agent": True,
        "params":
            "url:str, max_chars?:int",
    },

    "browser.automate": {
        "description":
            "Automate a public website with Playwright: goto/click/fill/"
            "press/wait/extract/screenshot.",
        "risk": "external_action",
        "approval": True,
        "agent": True,
        "params":
            "url:str, actions:list",
    },

    "pdf.generate": {
        "description":
            "Generate a PDF report in RedSight outputs.",
        "risk": "local_write",
        "approval": False,
        "agent": True,
        "params":
            "title:str, content:str, filename?:str",
    },

    "filesystem.list": {
        "description":
            "List a directory on C: or D:.",
        "risk": "read",
        "approval": False,
        "agent": True,
        "params":
            "path:str",
    },

    "filesystem.read": {
        "description":
            "Read a non-sensitive text file on C: or D:.",
        "risk": "read",
        "approval": False,
        "agent": True,
        "params":
            "path:str, max_chars?:int",
    },

    "filesystem.search": {
        "description":
            "Search filenames recursively under a C: or D: directory.",
        "risk": "read",
        "approval": False,
        "agent": True,
        "params":
            "root:str, pattern:str, max_results?:int, max_depth?:int",
    },

    "filesystem.write": {
        "description":
            "Write text to a file on C: or D:. Never deletes files.",
        "risk": "local_write",
        "approval": True,
        "agent": True,
        "params":
            "path:str, content:str, overwrite?:bool",
    },

    "skills.list": {
        "description":
            "List inherited Hermes skills.",
        "risk": "read",
        "approval": False,
        "agent": True,
        "params":
            "query?:str, limit?:int",
    },

    "skills.invoke": {
        "description":
            "Load a migrated Hermes skill and use it as procedural "
            "knowledge for a RedSight model request.",
        "risk": "model",
        "approval": False,
        "agent": True,
        "params":
            "skill:str, instruction:str",
    },

    "mcp.list": {
        "description":
            "List migrated Hermes MCP server definitions.",
        "risk": "read",
        "approval": False,
        "agent": True,
        "params":
            "",
    },

    "mcp.test": {
        "description":
            "Ask Hermes to test a configured MCP server connection.",
        "risk": "read",
        "approval": False,
        "agent": False,
        "params":
            "name:str",
    },

    "task.create": {
        "description":
            "Create a persistent one-time or cron scheduled RedSight tool task.",
        "risk": "automation",
        "approval": True,
        "agent": True,
        "params":
            "name:str, tool:str, params:dict, cron?:str, run_at?:ISO8601, "
            "timezone?:str",
    },

    "system.powershell": {
        "description":
            "Execute an explicitly user-approved PowerShell command.",
        "risk": "system",
        "approval": True,
        "agent": False,
        "params":
            "command:str, timeout?:int",
    },
}


# ====================================================================
# MODELS
# ====================================================================

class ToolExecuteRequest(BaseModel):

    tool: str

    params: dict[str, Any] = Field(
        default_factory=dict
    )

    approved: bool = False


class BraveKeyRequest(BaseModel):

    api_key: str


class AgentPlanRequest(BaseModel):

    goal: str


class AgentExecuteRequest(BaseModel):

    goal: str

    plan: list[dict[str, Any]]

    approved: bool = False


class TaskCreateRequest(BaseModel):

    name: str

    tool: str

    params: dict[str, Any] = Field(
        default_factory=dict
    )

    cron: str | None = None

    run_at: str | None = None

    timezone: str | None = None

    approved: bool = False


# ====================================================================
# SECRETS
# ====================================================================

def load_secrets() -> dict[str, Any]:

    if not SECRETS_FILE.exists():
        return {}

    try:

        return json.loads(
            SECRETS_FILE.read_text(
                encoding="utf-8"
            )
        )

    except Exception:

        return {}


def save_secrets(
    data: dict[str, Any]
):

    temporary = (
        SECRETS_FILE
        .with_suffix(
            ".tmp"
        )
    )

    temporary.write_text(
        json.dumps(
            data,
            indent=2,
        ),
        encoding="utf-8",
    )

    os.replace(
        temporary,
        SECRETS_FILE,
    )


def brave_key() -> str | None:

    env_key = os.environ.get(
        "BRAVE_SEARCH_API_KEY"
    )

    if env_key:
        return env_key.strip()

    key = load_secrets().get(
        "brave_search_api_key"
    )

    if isinstance(
        key,
        str,
    ) and key.strip():

        return key.strip()

    return None


# ====================================================================
# AUDIT
# ====================================================================

SENSITIVE_KEYS = {
    "password",
    "passwd",
    "token",
    "secret",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
}


def scrub(
    value: Any,
):

    if isinstance(
        value,
        dict,
    ):

        result = {}

        for key, item in value.items():

            if str(key).lower() in SENSITIVE_KEYS:

                result[key] = "<REDACTED>"

            elif (
                str(key).lower()
                in {
                    "content",
                    "command",
                }
                and isinstance(
                    item,
                    str,
                )
                and len(item) > 1000
            ):

                result[key] = (
                    item[:1000]
                    + "...<TRUNCATED>"
                )

            else:

                result[key] = scrub(
                    item
                )

        return result

    if isinstance(
        value,
        list,
    ):

        return [
            scrub(item)
            for item in value
        ]

    return value


def audit(
    tool: str,
    params: dict[str, Any],
    *,
    approved: bool,
    ok: bool,
    detail: str = "",
):

    record = {
        "timestamp":
            time.time(),

        "tool":
            tool,

        "approved":
            approved,

        "ok":
            ok,

        "params":
            scrub(params),

        "detail":
            detail[:1000],
    }

    with AUDIT_FILE.open(
        "a",
        encoding="utf-8",
    ) as file:

        file.write(
            json.dumps(
                record,
                ensure_ascii=False,
            )
            + "\n"
        )


# ====================================================================
# URL SECURITY
# ====================================================================

def validate_public_url(
    raw_url: str,
) -> str:

    parsed = urlparse(
        raw_url
    )

    if parsed.scheme not in {
        "http",
        "https",
    }:

        raise ValueError(
            "Only http/https URLs are allowed."
        )

    if not parsed.hostname:

        raise ValueError(
            "URL has no hostname."
        )

    hostname = (
        parsed.hostname
        .strip()
        .lower()
    )

    if hostname in {
        "localhost",
        "localhost.localdomain",
    }:

        raise ValueError(
            "Localhost URLs are blocked."
        )

    try:

        addresses = socket.getaddrinfo(
            hostname,
            parsed.port
            or (
                443
                if parsed.scheme == "https"
                else 80
            ),
        )

    except socket.gaierror as exc:

        raise ValueError(
            "Could not resolve hostname."
        ) from exc

    for address in addresses:

        ip_text = address[4][0]

        ip = ipaddress.ip_address(
            ip_text
        )

        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):

            raise ValueError(
                "Private/local network URLs are blocked."
            )

    return raw_url


# ====================================================================
# FILESYSTEM SECURITY
# ====================================================================

SENSITIVE_PATH_TERMS = (
    "\\.ssh\\",
    "\\.gnupg\\",
    "\\microsoft\\credentials\\",
    "\\microsoft\\protect\\",
    "\\chrome\\user data\\",
    "\\edge\\user data\\",
    "\\brave-browser\\user data\\",
)

SENSITIVE_FILE_NAMES = {
    ".env",
    "credentials",
    "credentials.json",
    "id_rsa",
    "id_ed25519",
    "cookies",
    "cookies.sqlite",
    "login data",
    "web data",
    "local state",
    "ntuser.dat",
}

WRITE_BLOCKED_PREFIXES = (
    "c:\\windows",
    "c:\\program files",
    "c:\\program files (x86)",
    "c:\\programdata",
    "c:\\system volume information",
    "c:\\$recycle.bin",
)


def validated_path(
    raw: str,
    *,
    write: bool = False,
) -> Path:

    path = Path(
        os.path.abspath(
            os.path.expandvars(
                os.path.expanduser(
                    raw
                )
            )
        )
    )

    drive = (
        path.drive.upper()
    )

    if drive not in {
        "C:",
        "D:",
    }:

        raise ValueError(
            "RedSight filesystem tools are limited to C: and D:."
        )

    lower = str(
        path
    ).lower()

    if any(
        term in lower
        for term in SENSITIVE_PATH_TERMS
    ):

        raise PermissionError(
            "Credential/security-store path is blocked."
        )

    if path.name.lower() in SENSITIVE_FILE_NAMES:

        raise PermissionError(
            "Sensitive credential file is blocked."
        )

    if write and any(
        lower.startswith(
            prefix
        )
        for prefix in WRITE_BLOCKED_PREFIXES
    ):

        raise PermissionError(
            "Writes to Windows/system directories are blocked."
        )

    return path


# ====================================================================
# WEB SEARCH
# ====================================================================

async def web_search(
    params: dict[str, Any],
):

    query = str(
        params.get(
            "query",
            ""
        )
    ).strip()

    if not query:

        raise ValueError(
            "query is required"
        )

    key = brave_key()

    if not key:

        return {
            "ok": False,
            "error":
                "Brave Search API key is not configured. "
                "Use the 'Brave Key' button in Command Center.",
            "needs_brave_key": True,
        }

    count = min(
        max(
            int(
                params.get(
                    "count",
                    10,
                )
            ),
            1,
        ),
        20,
    )

    request_params: dict[str, Any] = {
        "q":
            query,

        "count":
            count,

        "safesearch":
            str(
                params.get(
                    "safesearch",
                    "moderate",
                )
            ),

        "extra_snippets":
            "true",
    }

    freshness = params.get(
        "freshness"
    )

    if freshness:

        request_params[
            "freshness"
        ] = str(
            freshness
        )

    headers = {
        "Accept":
            "application/json",

        "X-Subscription-Token":
            key,
    }

    async with httpx.AsyncClient(
        timeout=30.0,
    ) as client:

        response = await client.get(
            BRAVE_URL,
            headers=headers,
            params=request_params,
        )

        response.raise_for_status()

        data = response.json()

    web = data.get(
        "web",
        {}
    )

    raw_results = web.get(
        "results",
        []
    )

    results = []

    for item in raw_results[:count]:

        results.append(
            {
                "title":
                    item.get(
                        "title"
                    ),

                "url":
                    item.get(
                        "url"
                    ),

                "description":
                    item.get(
                        "description"
                    ),

                "age":
                    item.get(
                        "age"
                    ),

                "extra_snippets":
                    item.get(
                        "extra_snippets",
                        [],
                    ),
            }
        )

    return {
        "ok":
            True,

        "query":
            query,

        "count":
            len(
                results
            ),

        "results":
            results,
    }


# ====================================================================
# BROWSER
# ====================================================================

async def browser_read(
    params: dict[str, Any],
):

    url = validate_public_url(
        str(
            params.get(
                "url",
                ""
            )
        )
    )

    max_chars = min(
        max(
            int(
                params.get(
                    "max_chars",
                    15000,
                )
            ),
            1000,
        ),
        50000,
    )

    from playwright.async_api import (
        async_playwright,
    )

    async with async_playwright() as playwright:

        browser = await playwright.chromium.launch(
            headless=True
        )

        try:

            page = await browser.new_page(
                viewport={
                    "width": 1440,
                    "height": 1000,
                }
            )

            await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=45000,
            )

            await page.wait_for_timeout(
                1000
            )

            title = await page.title()

            text = await page.locator(
                "body"
            ).inner_text(
                timeout=10000
            )

            return {
                "ok":
                    True,

                "url":
                    page.url,

                "title":
                    title,

                "text":
                    text[:max_chars],
            }

        finally:

            await browser.close()


async def browser_automate(
    params: dict[str, Any],
):

    url = validate_public_url(
        str(
            params.get(
                "url",
                ""
            )
        )
    )

    actions = params.get(
        "actions",
        []
    )

    if not isinstance(
        actions,
        list,
    ):

        raise ValueError(
            "actions must be a list"
        )

    if len(actions) > 20:

        raise ValueError(
            "Maximum 20 browser actions per execution."
        )

    from playwright.async_api import (
        async_playwright,
    )

    extracted = []

    screenshots = []

    async with async_playwright() as playwright:

        browser = await playwright.chromium.launch(
            headless=True
        )

        try:

            page = await browser.new_page(
                viewport={
                    "width": 1440,
                    "height": 1000,
                }
            )

            await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=45000,
            )

            for action in actions:

                if not isinstance(
                    action,
                    dict,
                ):
                    continue

                kind = str(
                    action.get(
                        "action",
                        ""
                    )
                ).strip().lower()

                if kind == "goto":

                    next_url = validate_public_url(
                        str(
                            action.get(
                                "url",
                                ""
                            )
                        )
                    )

                    await page.goto(
                        next_url,
                        wait_until="domcontentloaded",
                        timeout=45000,
                    )

                elif kind == "click":

                    selector = str(
                        action.get(
                            "selector",
                            ""
                        )
                    )

                    await page.locator(
                        selector
                    ).click(
                        timeout=15000
                    )

                elif kind == "fill":

                    selector = str(
                        action.get(
                            "selector",
                            ""
                        )
                    )

                    value = str(
                        action.get(
                            "value",
                            ""
                        )
                    )

                    await page.locator(
                        selector
                    ).fill(
                        value,
                        timeout=15000,
                    )

                elif kind == "press":

                    selector = str(
                        action.get(
                            "selector",
                            "body"
                        )
                    )

                    key = str(
                        action.get(
                            "key",
                            "Enter"
                        )
                    )

                    await page.locator(
                        selector
                    ).press(
                        key,
                        timeout=15000,
                    )

                elif kind == "wait":

                    milliseconds = min(
                        max(
                            int(
                                action.get(
                                    "milliseconds",
                                    1000,
                                )
                            ),
                            0,
                        ),
                        15000,
                    )

                    await page.wait_for_timeout(
                        milliseconds
                    )

                elif kind == "extract":

                    selector = str(
                        action.get(
                            "selector",
                            "body"
                        )
                    )

                    value = await page.locator(
                        selector
                    ).inner_text(
                        timeout=15000
                    )

                    extracted.append(
                        {
                            "selector":
                                selector,

                            "text":
                                value[:20000],
                        }
                    )

                elif kind == "screenshot":

                    name = str(
                        action.get(
                            "filename",
                            (
                                "browser-"
                                + str(
                                    int(
                                        time.time()
                                    )
                                )
                                + ".png"
                            ),
                        )
                    )

                    name = re.sub(
                        r"[^A-Za-z0-9_.-]+",
                        "_",
                        name,
                    )

                    if not name.lower().endswith(
                        ".png"
                    ):

                        name += ".png"

                    destination = (
                        OUTPUT_HOME
                        / name
                    )

                    await page.screenshot(
                        path=str(
                            destination
                        ),
                        full_page=True,
                    )

                    screenshots.append(
                        str(
                            destination
                        )
                    )

                else:

                    raise ValueError(
                        "Unsupported browser action: "
                        + kind
                    )

            title = await page.title()

            return {
                "ok":
                    True,

                "final_url":
                    page.url,

                "title":
                    title,

                "extracted":
                    extracted,

                "screenshots":
                    screenshots,
            }

        finally:

            await browser.close()


# ====================================================================
# PDF
# ====================================================================

def pdf_generate(
    params: dict[str, Any],
):

    title = str(
        params.get(
            "title",
            "RedSight Report",
        )
    ).strip()

    content = str(
        params.get(
            "content",
            ""
        )
    )

    requested = str(
        params.get(
            "filename",
            (
                "redsight-report-"
                + str(
                    int(
                        time.time()
                    )
                )
                + ".pdf"
            ),
        )
    )

    filename = re.sub(
        r"[^A-Za-z0-9_.-]+",
        "_",
        requested,
    )

    if not filename.lower().endswith(
        ".pdf"
    ):

        filename += ".pdf"

    destination = (
        OUTPUT_HOME
        / filename
    )

    styles = getSampleStyleSheet()

    document = SimpleDocTemplate(
        str(
            destination
        ),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=title,
        author="RedSight",
    )

    story = [
        Paragraph(
            html.escape(
                title
            ),
            styles["Title"],
        ),
        Spacer(
            1,
            8 * mm,
        ),
    ]

    for block in re.split(
        r"(?:\r?\n){2,}",
        content,
    ):

        clean = (
            block.strip()
        )

        if not clean:
            continue

        clean = html.escape(
            clean
        ).replace(
            "\n",
            "<br/>",
        )

        story.append(
            Paragraph(
                clean,
                styles["BodyText"],
            )
        )

        story.append(
            Spacer(
                1,
                4 * mm,
            )
        )

    document.build(
        story
    )

    return {
        "ok":
            True,

        "path":
            str(
                destination
            ),

        "title":
            title,
    }


# ====================================================================
# FILESYSTEM
# ====================================================================

def filesystem_list(
    params: dict[str, Any],
):

    path = validated_path(
        str(
            params.get(
                "path",
                ""
            )
        )
    )

    if not path.exists():

        raise FileNotFoundError(
            str(
                path
            )
        )

    if not path.is_dir():

        raise NotADirectoryError(
            str(
                path
            )
        )

    entries = []

    for item in sorted(
        path.iterdir(),
        key=lambda p:
            (
                not p.is_dir(),
                p.name.lower(),
            ),
    )[:500]:

        try:

            size = (
                item.stat().st_size
                if item.is_file()
                else None
            )

        except Exception:

            size = None

        entries.append(
            {
                "name":
                    item.name,

                "path":
                    str(
                        item
                    ),

                "type":
                    (
                        "directory"
                        if item.is_dir()
                        else "file"
                    ),

                "size":
                    size,
            }
        )

    return {
        "ok":
            True,

        "path":
            str(
                path
            ),

        "entries":
            entries,
    }


def filesystem_read(
    params: dict[str, Any],
):

    path = validated_path(
        str(
            params.get(
                "path",
                ""
            )
        )
    )

    if not path.is_file():

        raise FileNotFoundError(
            str(
                path
            )
        )

    max_chars = min(
        max(
            int(
                params.get(
                    "max_chars",
                    100000,
                )
            ),
            1000,
        ),
        500000,
    )

    content = path.read_text(
        encoding="utf-8",
        errors="replace",
    )

    return {
        "ok":
            True,

        "path":
            str(
                path
            ),

        "content":
            content[:max_chars],

        "truncated":
            len(content) > max_chars,
    }


def filesystem_search(
    params: dict[str, Any],
):

    root = validated_path(
        str(
            params.get(
                "root",
                ""
            )
        )
    )

    pattern = str(
        params.get(
            "pattern",
            "*"
        )
    ).strip()

    max_results = min(
        max(
            int(
                params.get(
                    "max_results",
                    100,
                )
            ),
            1,
        ),
        500,
    )

    max_depth = min(
        max(
            int(
                params.get(
                    "max_depth",
                    6,
                )
            ),
            1,
        ),
        12,
    )

    if not root.is_dir():

        raise NotADirectoryError(
            str(
                root
            )
        )

    results = []

    base_parts = len(
        root.parts
    )

    skip_names = {
        "$recycle.bin",
        "system volume information",
        "node_modules",
        "__pycache__",
        ".git",
    }

    for current, dirs, files in os.walk(
        root
    ):

        current_path = Path(
            current
        )

        depth = (
            len(
                current_path.parts
            )
            - base_parts
        )

        if depth >= max_depth:

            dirs[:] = []
            continue

        dirs[:] = [
            directory
            for directory in dirs
            if directory.lower()
            not in skip_names
        ]

        for name in (
            dirs
            + files
        ):

            if (
                fnmatch.fnmatch(
                    name.lower(),
                    pattern.lower(),
                )
                or pattern.lower()
                in name.lower()
            ):

                item = (
                    current_path
                    / name
                )

                try:

                    validated_path(
                        str(
                            item
                        )
                    )

                except Exception:

                    continue

                results.append(
                    str(
                        item
                    )
                )

                if (
                    len(results)
                    >= max_results
                ):

                    return {
                        "ok":
                            True,

                        "root":
                            str(
                                root
                            ),

                        "results":
                            results,

                        "truncated":
                            True,
                    }

    return {
        "ok":
            True,

        "root":
            str(
                root
            ),

        "results":
            results,

        "truncated":
            False,
    }


def filesystem_write(
    params: dict[str, Any],
):

    path = validated_path(
        str(
            params.get(
                "path",
                ""
            )
        ),
        write=True,
    )

    content = str(
        params.get(
            "content",
            ""
        )
    )

    overwrite = bool(
        params.get(
            "overwrite",
            False,
        )
    )

    if (
        path.exists()
        and not overwrite
    ):

        raise FileExistsError(
            (
                "Destination already exists. "
                "Set overwrite=true after reviewing the action."
            )
        )

    if len(
        content.encode(
            "utf-8"
        )
    ) > 5_000_000:

        raise ValueError(
            "Maximum filesystem.write payload is 5 MB."
        )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        content,
        encoding="utf-8",
    )

    return {
        "ok":
            True,

        "path":
            str(
                path
            ),

        "characters":
            len(
                content
            ),
    }


# ====================================================================
# HERMES SKILLS
# ====================================================================

def load_skill_catalog():

    path = (
        HERITAGE
        / "skills_catalog.json"
    )

    if not path.exists():

        return []

    try:

        return json.loads(
            path.read_text(
                encoding="utf-8-sig"
            )
        )

    except Exception:

        return []


def skills_list(
    params: dict[str, Any],
):

    catalog = load_skill_catalog()

    query = str(
        params.get(
            "query",
            ""
        )
    ).strip().lower()

    limit = min(
        max(
            int(
                params.get(
                    "limit",
                    100,
                )
            ),
            1,
        ),
        300,
    )

    if query:

        catalog = [
            item
            for item in catalog
            if query
            in (
                (
                    str(
                        item.get(
                            "Name",
                            ""
                        )
                    )
                    + " "
                    + str(
                        item.get(
                            "Description",
                            ""
                        )
                    )
                ).lower()
            )
        ]

    return {
        "ok":
            True,

        "count":
            min(
                len(
                    catalog
                ),
                limit,
            ),

        "skills":
            catalog[:limit],
    }


async def redsight_chat(
    messages: list[dict[str, str]],
):

    async with httpx.AsyncClient(
        timeout=180.0,
    ) as client:

        response = await client.post(
            REDSIGHT_URL
            + "/api/v1/chat",

            json={
                "messages":
                    messages,

                "stream":
                    False,
            },
        )

        response.raise_for_status()

        data = response.json()

    message = data.get(
        "message"
    )

    if not isinstance(
        message,
        str,
    ):

        raise RuntimeError(
            "RedSight returned no message string."
        )

    return message


async def skills_invoke(
    params: dict[str, Any],
):

    requested = str(
        params.get(
            "skill",
            ""
        )
    ).strip()

    instruction = str(
        params.get(
            "instruction",
            ""
        )
    ).strip()

    if not requested:

        raise ValueError(
            "skill is required"
        )

    if not instruction:

        raise ValueError(
            "instruction is required"
        )

    catalog = load_skill_catalog()

    exact = []

    partial = []

    for item in catalog:

        name = str(
            item.get(
                "Name",
                ""
            )
        )

        if name.lower() == requested.lower():

            exact.append(
                item
            )

        elif requested.lower() in name.lower():

            partial.append(
                item
            )

    matches = exact or partial

    if not matches:

        raise ValueError(
            "No migrated Hermes skill matched: "
            + requested
        )

    item = matches[0]

    relative = str(
        item.get(
            "RelativePath",
            ""
        )
    )

    skill_path = (
        HERITAGE
        / relative
    )

    skill_text = skill_path.read_text(
        encoding="utf-8-sig",
        errors="replace",
    )[:16000]

    response = await redsight_chat(
        [
            {
                "role":
                    "system",

                "content":
                    (
                        "You are RedSight using an inherited Hermes "
                        "procedural skill. Follow the useful procedure "
                        "but do not claim external actions occurred "
                        "unless an actual tool result says they occurred.\n\n"
                        "SKILL:\n"
                        + skill_text
                    ),
            },
            {
                "role":
                    "user",

                "content":
                    instruction,
            },
        ]
    )

    return {
        "ok":
            True,

        "skill":
            item.get(
                "Name"
            ),

        "response":
            response,
    }


# ====================================================================
# MCP INVENTORY / TEST
# ====================================================================

def mcp_list():

    manifest_path = (
        HERITAGE
        / "heritage_manifest.json"
    )

    sanitized_path = (
        HERITAGE
        / "mcp_servers_sanitized.json"
    )

    manifest = {}

    sanitized = {}

    if manifest_path.exists():

        try:

            manifest = json.loads(
                manifest_path.read_text(
                    encoding="utf-8-sig"
                )
            )

        except Exception:

            pass

    if sanitized_path.exists():

        try:

            sanitized = json.loads(
                sanitized_path.read_text(
                    encoding="utf-8-sig"
                )
            )

        except Exception:

            pass

    return {
        "ok":
            True,

        "servers":
            manifest.get(
                "mcp_servers",
                [],
            ),

        "config":
            sanitized,
    }


def mcp_test(
    params: dict[str, Any],
):

    name = str(
        params.get(
            "name",
            ""
        )
    ).strip()

    if not name:

        raise ValueError(
            "name is required"
        )

    result = subprocess.run(
        [
            "hermes",
            "mcp",
            "test",
            name,
        ],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=90,
    )

    return {
        "ok":
            result.returncode == 0,

        "server":
            name,

        "stdout":
            result.stdout[-12000:],

        "stderr":
            result.stderr[-6000:],

        "exit_code":
            result.returncode,
    }


# ====================================================================
# POWERSHELL
#
# User only. Never exposed to automatic agent planning.
# ====================================================================

POWERSHELL_BLOCKED = (
    "remove-item",
    "format-volume",
    "format.com",
    "diskpart",
    "clear-disk",
    "initialize-disk",
    "stop-computer",
    "restart-computer",
    "shutdown.exe",
    "bcdedit",
    "reg delete",
    "cipher /w",
    "rd /s",
    "rmdir /s",
)


def powershell_execute(
    params: dict[str, Any],
):

    command = str(
        params.get(
            "command",
            ""
        )
    ).strip()

    if not command:

        raise ValueError(
            "command is required"
        )

    lower = command.lower()

    if any(
        blocked in lower
        for blocked in POWERSHELL_BLOCKED
    ):

        raise PermissionError(
            "This destructive PowerShell pattern is blocked."
        )

    timeout = min(
        max(
            int(
                params.get(
                    "timeout",
                    120,
                )
            ),
            1,
        ),
        300,
    )

    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=timeout,
    )

    return {
        "ok":
            result.returncode == 0,

        "exit_code":
            result.returncode,

        "stdout":
            result.stdout[-20000:],

        "stderr":
            result.stderr[-10000:],
    }


# ====================================================================
# TASK SCHEDULER
# ====================================================================

LOCAL_TIMEZONE = (
    get_localzone_name()
)

SCHEDULER = BackgroundScheduler(
    timezone=LOCAL_TIMEZONE,
    jobstores={
        "default":
            SQLAlchemyJobStore(
                url=(
                    "sqlite:///"
                    + SCHEDULER_DB
                    .as_posix()
                )
            )
    },
)

SCHEDULER.start()


def tool_requires_approval(
    tool: str,
) -> bool:

    spec = TOOL_SPECS.get(
        tool
    )

    if not spec:
        return True

    return bool(
        spec.get(
            "approval"
        )
    )


def tool_agent_allowed(
    tool: str,
) -> bool:

    spec = TOOL_SPECS.get(
        tool
    )

    if not spec:
        return False

    return bool(
        spec.get(
            "agent"
        )
    )


def scheduled_tool_runner(
    tool: str,
    params: dict[str, Any],
    approved: bool,
):

    try:

        result = asyncio.run(
            execute_tool_core(
                tool,
                params,
                approved=approved,
            )
        )

        record = {
            "timestamp":
                time.time(),

            "tool":
                tool,

            "ok":
                bool(
                    result.get(
                        "ok",
                        False,
                    )
                ),

            "result":
                scrub(
                    result
                ),
        }

    except Exception as exc:

        record = {
            "timestamp":
                time.time(),

            "tool":
                tool,

            "ok":
                False,

            "error":
                repr(
                    exc
                ),
        }

    with TASK_RESULT_FILE.open(
        "a",
        encoding="utf-8",
    ) as file:

        file.write(
            json.dumps(
                record,
                ensure_ascii=False,
            )
            + "\n"
        )


def create_task_internal(
    params: dict[str, Any],
    *,
    approved: bool,
):

    name = str(
        params.get(
            "name",
            "RedSight Task",
        )
    ).strip()

    tool = str(
        params.get(
            "tool",
            ""
        )
    ).strip()

    tool_params = params.get(
        "params",
        {}
    )

    cron = params.get(
        "cron"
    )

    run_at = params.get(
        "run_at"
    )

    timezone = str(
        params.get(
            "timezone"
        )
        or LOCAL_TIMEZONE
    )

    if tool not in TOOL_SPECS:

        raise ValueError(
            "Unknown scheduled tool: "
            + tool
        )

    if (
        tool_requires_approval(
            tool
        )
        and not approved
    ):

        return {
            "ok":
                False,

            "requires_approval":
                True,

            "tool":
                tool,

            "reason":
                "The scheduled tool can create external/system side effects.",
        }

    if not cron and not run_at:

        raise ValueError(
            "cron or run_at is required"
        )

    task_id = (
        "redsight-"
        + uuid.uuid4().hex[:12]
    )

    if cron:

        trigger = CronTrigger.from_crontab(
            str(
                cron
            ),
            timezone=timezone,
        )

        schedule_type = "cron"

        schedule_value = str(
            cron
        )

    else:

        run_datetime = datetime.fromisoformat(
            str(
                run_at
            )
        )

        if run_datetime.tzinfo is None:

            run_datetime = run_datetime.replace(
                tzinfo=ZoneInfo(
                    timezone
                )
            )

        trigger = DateTrigger(
            run_date=run_datetime
        )

        schedule_type = "date"

        schedule_value = run_datetime.isoformat()

    job = SCHEDULER.add_job(
        scheduled_tool_runner,
        trigger=trigger,
        args=[
            tool,
            tool_params,
            approved,
        ],
        id=task_id,
        name=name,
        replace_existing=False,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )

    return {
        "ok":
            True,

        "task_id":
            task_id,

        "name":
            name,

        "tool":
            tool,

        "schedule_type":
            schedule_type,

        "schedule":
            schedule_value,

        "timezone":
            timezone,

        "next_run_time":
            (
                job.next_run_time.isoformat()
                if job.next_run_time
                else None
            ),
    }


def list_tasks():

    jobs = []

    for job in SCHEDULER.get_jobs():

        jobs.append(
            {
                "id":
                    job.id,

                "name":
                    job.name,

                "next_run_time":
                    (
                        job.next_run_time.isoformat()
                        if job.next_run_time
                        else None
                    ),

                "trigger":
                    str(
                        job.trigger
                    ),
            }
        )

    return jobs


# ====================================================================
# TOOL EXECUTION
# ====================================================================

async def execute_tool_core(
    tool: str,
    params: dict[str, Any],
    *,
    approved: bool = False,
):

    if tool not in TOOL_SPECS:

        return {
            "ok":
                False,

            "error":
                "Unknown tool: "
                + tool,
        }

    spec = TOOL_SPECS[
        tool
    ]

    if (
        bool(
            spec.get(
                "approval"
            )
        )
        and not approved
    ):

        return {
            "ok":
                False,

            "requires_approval":
                True,

            "tool":
                tool,

            "risk":
                spec.get(
                    "risk"
                ),

            "description":
                spec.get(
                    "description"
                ),
        }

    try:

        if tool == "web.search":

            result = await web_search(
                params
            )

        elif tool == "browser.read":

            result = await browser_read(
                params
            )

        elif tool == "browser.automate":

            result = await browser_automate(
                params
            )

        elif tool == "pdf.generate":

            result = pdf_generate(
                params
            )

        elif tool == "filesystem.list":

            result = filesystem_list(
                params
            )

        elif tool == "filesystem.read":

            result = filesystem_read(
                params
            )

        elif tool == "filesystem.search":

            result = filesystem_search(
                params
            )

        elif tool == "filesystem.write":

            result = filesystem_write(
                params
            )

        elif tool == "skills.list":

            result = skills_list(
                params
            )

        elif tool == "skills.invoke":

            result = await skills_invoke(
                params
            )

        elif tool == "mcp.list":

            result = mcp_list()

        elif tool == "mcp.test":

            result = mcp_test(
                params
            )

        elif tool == "task.create":

            result = create_task_internal(
                params,
                approved=approved,
            )

        elif tool == "system.powershell":

            result = powershell_execute(
                params
            )

        else:

            result = {
                "ok":
                    False,

                "error":
                    "No implementation for tool.",
            }

        audit(
            tool,
            params,
            approved=approved,
            ok=bool(
                result.get(
                    "ok",
                    False,
                )
            ),
            detail=str(
                result.get(
                    "error",
                    ""
                )
            ),
        )

        return result

    except Exception as exc:

        logger.exception(
            "Tool execution failed: %s",
            tool,
        )

        audit(
            tool,
            params,
            approved=approved,
            ok=False,
            detail=repr(
                exc
            ),
        )

        return {
            "ok":
                False,

            "tool":
                tool,

            "error":
                str(
                    exc
                ),
        }


# ====================================================================
# AGENT PLANNER
# ====================================================================

def agent_tool_catalog():

    return {
        name:
            {
                "description":
                    spec[
                        "description"
                    ],

                "params":
                    spec[
                        "params"
                    ],

                "approval":
                    spec[
                        "approval"
                    ],

                "risk":
                    spec[
                        "risk"
                    ],
            }

        for name, spec in TOOL_SPECS.items()

        if spec.get(
            "agent"
        )
    }


async def create_agent_plan(
    goal: str,
):

    catalog = agent_tool_catalog()

    system_prompt = (
        "You are the RedSight local action planner. "
        "Create the smallest safe plan needed to accomplish the user's goal. "
        "Only use tools from the provided catalog. "
        "Never invent tools. "
        "Prefer read-only tools. "
        "Do not use browser.automate unless website interaction is required. "
        "Do not create a scheduled task unless the user explicitly asked "
        "for future or recurring execution. "
        "Return ONLY JSON with this exact structure: "
        '{"steps":[{"tool":"tool.name","params":{},'
        '"reason":"short reason"}],"summary":"short description"}.'
        "\n\nTOOL CATALOG:\n"
        + json.dumps(
            catalog,
            indent=2,
        )
    )

    raw = await redsight_chat(
        [
            {
                "role":
                    "system",

                "content":
                    system_prompt,
            },
            {
                "role":
                    "user",

                "content":
                    goal,
            },
        ]
    )

    candidate = raw.strip()

    if candidate.startswith(
        "```"
    ):

        candidate = re.sub(
            r"^```(?:json)?\s*",
            "",
            candidate,
        )

        candidate = re.sub(
            r"\s*```$",
            "",
            candidate,
        )

    try:

        parsed = json.loads(
            candidate
        )

    except Exception:

        left = candidate.find(
            "{"
        )

        right = candidate.rfind(
            "}"
        )

        if (
            left < 0
            or right <= left
        ):

            return {
                "steps":
                    [],

                "summary":
                    "Planner did not return valid JSON.",

                "raw":
                    raw[:8000],
            }

        parsed = json.loads(
            candidate[
                left:
                right + 1
            ]
        )

    steps = []

    for step in parsed.get(
        "steps",
        []
    )[:8]:

        if not isinstance(
            step,
            dict,
        ):

            continue

        tool = str(
            step.get(
                "tool",
                ""
            )
        )

        if not tool_agent_allowed(
            tool
        ):

            continue

        params = step.get(
            "params",
            {}
        )

        if not isinstance(
            params,
            dict,
        ):

            params = {}

        steps.append(
            {
                "tool":
                    tool,

                "params":
                    params,

                "reason":
                    str(
                        step.get(
                            "reason",
                            ""
                        )
                    )[:500],

                "requires_approval":
                    tool_requires_approval(
                        tool
                    ),
            }
        )

    return {
        "steps":
            steps,

        "summary":
            str(
                parsed.get(
                    "summary",
                    ""
                )
            )[:1000],

        "requires_approval":
            any(
                step[
                    "requires_approval"
                ]
                for step in steps
            ),
    }


async def execute_agent_plan(
    goal: str,
    plan: list[dict[str, Any]],
    *,
    approved: bool,
):

    results = []

    for number, step in enumerate(
        plan[:8],
        start=1,
    ):

        tool = str(
            step.get(
                "tool",
                ""
            )
        )

        params = step.get(
            "params",
            {}
        )

        if not tool_agent_allowed(
            tool
        ):

            results.append(
                {
                    "step":
                        number,

                    "tool":
                        tool,

                    "ok":
                        False,

                    "error":
                        "Tool is not agent-allowed.",
                }
            )

            continue

        if (
            tool_requires_approval(
                tool
            )
            and not approved
        ):

            return {
                "ok":
                    False,

                "requires_approval":
                    True,

                "goal":
                    goal,

                "plan":
                    plan,

                "completed":
                    results,

                "pending_step":
                    number,
            }

        result = await execute_tool_core(
            tool,
            params,
            approved=(
                approved
                if tool_requires_approval(
                    tool
                )
                else False
            ),
        )

        results.append(
            {
                "step":
                    number,

                "tool":
                    tool,

                "reason":
                    step.get(
                        "reason",
                        ""
                    ),

                "result":
                    result,
            }
        )

        if not result.get(
            "ok",
            False,
        ):

            break

    return {
        "ok":
            True,

        "goal":
            goal,

        "results":
            results,
    }


# ====================================================================
# FASTAPI
# ====================================================================

app = FastAPI(
    title="RedSight Action Gateway",
    version="1.0.0",
)


@app.get(
    "/health"
)
async def health():

    return {
        "status":
            "healthy",

        "service":
            "redsight-action-gateway",

        "brave_configured":
            brave_key()
            is not None,

        "scheduler_running":
            SCHEDULER.running,

        "tool_count":
            len(
                TOOL_SPECS
            ),
    }


@app.get(
    "/tools"
)
async def tools():

    return {
        "tools":
            TOOL_SPECS
    }


@app.get(
    "/config/status"
)
async def config_status():

    return {
        "brave_search_configured":
            brave_key()
            is not None,

        "actions_home":
            str(
                ACTION_HOME
            ),

        "output_home":
            str(
                OUTPUT_HOME
            ),

        "timezone":
            LOCAL_TIMEZONE,
    }


@app.post(
    "/config/brave"
)
async def configure_brave(
    request: BraveKeyRequest,
):

    key = request.api_key.strip()

    if len(key) < 10:

        raise HTTPException(
            status_code=400,
            detail="API key appears invalid.",
        )

    secrets = load_secrets()

    secrets[
        "brave_search_api_key"
    ] = key

    save_secrets(
        secrets
    )

    return {
        "ok":
            True,

        "configured":
            True,
    }


@app.post(
    "/tool/execute"
)
async def tool_execute(
    request: ToolExecuteRequest,
):

    return await execute_tool_core(
        request.tool,
        request.params,
        approved=request.approved,
    )


@app.post(
    "/agent/plan"
)
async def agent_plan(
    request: AgentPlanRequest,
):

    plan = await create_agent_plan(
        request.goal
    )

    return {
        "ok":
            True,

        "goal":
            request.goal,

        **plan,
    }


@app.post(
    "/agent/execute"
)
async def agent_execute(
    request: AgentExecuteRequest,
):

    return await execute_agent_plan(
        request.goal,
        request.plan,
        approved=request.approved,
    )


@app.get(
    "/tasks"
)
async def tasks():

    return {
        "tasks":
            list_tasks()
    }


@app.post(
    "/tasks/create"
)
async def task_create(
    request: TaskCreateRequest,
):

    return create_task_internal(
        request.model_dump(),
        approved=request.approved,
    )


@app.post(
    "/tasks/{task_id}/pause"
)
async def task_pause(
    task_id: str,
):

    job = SCHEDULER.get_job(
        task_id
    )

    if not job:

        raise HTTPException(
            status_code=404,
            detail="Task not found",
        )

    SCHEDULER.pause_job(
        task_id
    )

    return {
        "ok":
            True,

        "task_id":
            task_id,

        "status":
            "paused",
    }


@app.post(
    "/tasks/{task_id}/resume"
)
async def task_resume(
    task_id: str,
):

    job = SCHEDULER.get_job(
        task_id
    )

    if not job:

        raise HTTPException(
            status_code=404,
            detail="Task not found",
        )

    SCHEDULER.resume_job(
        task_id
    )

    return {
        "ok":
            True,

        "task_id":
            task_id,

        "status":
            "resumed",
    }


@app.delete(
    "/tasks/{task_id}"
)
async def task_delete(
    task_id: str,
):

    job = SCHEDULER.get_job(
        task_id
    )

    if not job:

        raise HTTPException(
            status_code=404,
            detail="Task not found",
        )

    SCHEDULER.remove_job(
        task_id
    )

    return {
        "ok":
            True,

        "task_id":
            task_id,

        "status":
            "deleted",
    }
'''

GATEWAY_SOURCE = textwrap.dedent(
    GATEWAY_SOURCE
).lstrip()

ast.parse(
    GATEWAY_SOURCE,
    filename=str(
        GATEWAY
    ),
)

write_text(
    ACTION_INIT,
    (
        '"""RedSight host-side action gateway."""\n'
    ),
)

write_text(
    GATEWAY,
    GATEWAY_SOURCE,
)

log(
    "ACTION_GATEWAY_SOURCE=PASS"
)


# ====================================================================
# ACTION PALETTE UI
# ====================================================================

ACTION_PALETTE_SOURCE = r'''
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
'''

ACTION_PALETTE_SOURCE = textwrap.dedent(
    ACTION_PALETTE_SOURCE
).lstrip()

ast.parse(
    ACTION_PALETTE_SOURCE,
    filename=str(
        UI_ACTIONS
    ),
)

write_text(
    UI_ACTIONS,
    ACTION_PALETTE_SOURCE,
)

log(
    "ACTION_PALETTE_SOURCE=PASS"
)


# ====================================================================
# TOOL CATALOG
# ====================================================================

TOOL_CATALOG_TEXT = r'''
# RedSight Action Tool Catalog

## Core Agentic Mode

`/agent <goal>`

RedSight plans a sequence of allowlisted tools using the local LM Studio
model and executes safe read-only steps automatically.

Any plan containing browser interaction, persistent scheduling, filesystem
writes, or similar state-changing actions requires user approval.

## Web

### web.search

Live Brave Search API integration.

Slash command:

`/web <query>`

Configuration:

Use the **Brave Key** button in the ACTIONS bar.

The API key is kept outside the RedSight repository.

### browser.read

Headless Chromium webpage reading/extraction.

Slash:

`/browse https://example.com`

### browser.automate

Playwright browser automation.

Supported actions:

- goto
- click
- fill
- press
- wait
- extract
- screenshot

State-changing browser automation requires approval.

## Documents

### pdf.generate

Generate a local PDF under:

`C:\Users\walim\RedSight\outputs\actions`

Slash:

`/pdf Title | content`

## Filesystem

- filesystem.list
- filesystem.read
- filesystem.search
- filesystem.write

Only C: and D: paths are accepted.

Known credential stores and sensitive credential filenames are blocked.

Writes require approval.

There is intentionally no general delete tool.

## Hermes Heritage

### skills.list

Search/list inherited Hermes skills.

### skills.invoke

Load an inherited SKILL.md and use it as procedural context.

Slash:

`/skill skill-name | instruction`

## MCP

### mcp.list

Show migrated MCP servers.

### mcp.test

Test an MCP server through the Hermes MCP subsystem.

Migrated servers currently include:

- filesystem_c
- filesystem_d
- github

## Automation

### task.create

Persistent scheduled tool actions using RedSight's Action Gateway.

Supports:

- standard 5-field cron schedules
- one-time ISO timestamps
- persistent SQLite-backed scheduling
- pause/resume/delete APIs

Slash example:

`/task 0 9 * * 1-5 | web.search | {"query":"latest AI news"}`

## Explicit System Action

### system.powershell

Available only through explicit slash invocation and approval.

It is not exposed to autonomous agent planning.

Destructive patterns such as disk formatting, shutdown, Remove-Item,
registry deletion, and similar commands are blocked.

Slash:

`/ps <command>`

## User Interface

Typing `/` in chat activates the action-capable path.

The ACTIONS palette provides:

- AUTO AGENT
- Web
- Browse
- Browser Auto
- PDF
- Skill
- Agent
- Cron
- Tasks
- C:
- D:
- MCP
- Tools
- Brave Key
'''

write_text(
    TOOL_CATALOG,
    textwrap.dedent(
        TOOL_CATALOG_TEXT
    ).lstrip(),
)

manifest = {
    "version":
        "1.0",

    "installed_at":
        time.strftime(
            "%Y-%m-%dT%H:%M:%S"
        ),

    "gateway":
        "http://127.0.0.1:8765",

    "features": [
        "Brave web search",
        "Playwright browser reading",
        "Playwright browser automation",
        "PDF generation",
        "C/D filesystem tools",
        "Hermes skill invocation",
        "Hermes MCP inventory/testing",
        "persistent cron tasks",
        "agent planning/execution",
        "explicit PowerShell execution",
        "chat action palette",
        "slash commands",
        "auto-agent mode",
    ],
}

write_text(
    ACTION_MANIFEST,
    json.dumps(
        manifest,
        indent=2,
    ),
)


# ====================================================================
# PATCH ONLY THE LAUNCHER
#
# command_center.py remains untouched.
# ====================================================================

launcher = read_text(
    LAUNCHER
)

# Remove previous action integration so this is idempotent.
launcher = re.sub(
    (
        r"(?m)^from app\.ui\.action_palette "
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

# Ensure pathlib.Path.
if not re.search(
    r"(?m)^from pathlib import Path\s*$",
    launcher,
):

    future = re.search(
        r"(?m)^from __future__ import .+$",
        launcher,
    )

    if future:

        launcher = (
            launcher[:future.end()]
            + "\nfrom pathlib import Path"
            + launcher[future.end():]
        )

    else:

        launcher = (
            "from pathlib import Path\n"
            + launcher
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
        "CommandCenterMainWindow import not found in launcher."
    )

integration = (
    "\n"
    "from app.ui.action_palette "
    "import install_action_hooks, attach_action_palette\n"
    "install_action_hooks(CommandCenterMainWindow)"
)

launcher = (
    launcher[:command_import.end()]
    + integration
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
        "CommandCenterMainWindow() construction not found."
    )

indent = window_match.group(
    1
)

attach_line = (
    indent
    + "attach_action_palette("
    + "window, Path(__file__).resolve().parent"
    + ")"
)

launcher = (
    launcher[:window_match.end()]
    + "\n"
    + attach_line
    + launcher[window_match.end():]
)

ast.parse(
    launcher,
    filename=str(
        LAUNCHER
    ),
)

write_text(
    LAUNCHER,
    launcher,
)

log(
    "ACTION_LAUNCHER_PATCH=PASS"
)


# ====================================================================
# STARTUP LAUNCHERS
# ====================================================================

ACTION_PYTHONW = (
    ROOT
    / ".venv-actions"
    / "Scripts"
    / "pythonw.exe"
)

ACTION_PYTHON = (
    ROOT
    / ".venv-actions"
    / "Scripts"
    / "python.exe"
)

python_exe = (
    ACTION_PYTHONW
    if ACTION_PYTHONW.exists()
    else ACTION_PYTHON
)

STARTUP_CMD = (
    APPDATA
    / "Microsoft"
    / "Windows"
    / "Start Menu"
    / "Programs"
    / "Startup"
    / "RedSight-Action-Gateway.cmd"
)

STARTUP_CMD.parent.mkdir(
    parents=True,
    exist_ok=True,
)

startup_text = (
    "@echo off\n"
    'cd /d "' + str(ROOT) + '"\n'
    'start "" /min "' + str(python_exe) + '" '
    "-m uvicorn redsight_actions.gateway:app "
    "--host 127.0.0.1 --port 8765\n"
)

write_text(
    STARTUP_CMD,
    startup_text,
)

manual_launcher = (
    ROOT
    / "START-REDSIGHT-ACTIONS.cmd"
)

write_text(
    manual_launcher,
    (
        "@echo off\n"
        'cd /d "' + str(ROOT) + '"\n'
        '"' + str(ACTION_PYTHON) + '" '
        "-m uvicorn redsight_actions.gateway:app "
        "--host 127.0.0.1 --port 8765\n"
    ),
)

log(
    "ACTION_STARTUP=PASS"
)


# ====================================================================
# FINAL STATIC VALIDATION
# ====================================================================

for path in (
    GATEWAY,
    UI_ACTIONS,
    LAUNCHER,
):

    source = read_text(
        path
    )

    ast.parse(
        source,
        filename=str(
            path
        ),
    )

    log(
        "AST_OK="
        + str(
            path.relative_to(
                ROOT
            )
        )
    )

log(
    "INSTALLER_BACKUP="
    + str(
        BACKUP
    )
)

log(
    "STAGE8_SOURCE_INSTALL=PASS"
)