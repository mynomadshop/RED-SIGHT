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
from typing import Any, Literal
from urllib.parse import urlparse
from zoneinfo import ZoneInfo


import httpx

from fastapi import FastAPI
from fastapi import HTTPException, Query

from pydantic import BaseModel, ConfigDict
from pydantic import Field

from app.security.local_api import auth_headers, configure_local_api_security
from redsight_actions import mcp_native_stage111 as native_mcp
from redsight_actions.tool_planning import (
    build_agent_tool_schemas,
    decode_native_tool_steps,
)

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
    / "redsight"
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
    os.environ.get("REDSIGHT_API_BASE_URL", "http://127.0.0.1:8000")
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
            "List RED-SIGHT skills.",
        "risk": "read",
        "approval": False,
        "agent": True,
        "params":
            "query?:str, limit?:int",
    },

    "skills.invoke": {
        "description":
            "Load a configured RED-SIGHT skill and use it as procedural "
            "knowledge for a RedSight model request.",
        "risk": "model",
        "approval": False,
        "agent": True,
        "params":
            "skill:str, instruction:str",
    },

    "mcp.list": {
        "description":
            "List configured RED-SIGHT MCP server definitions.",
        "risk": "read",
        "approval": False,
        "agent": True,
        "params":
            "",
    },

    "mcp.test": {
        "description":
            "Test a configured MCP server and list its tools.",
        "risk": "read",
        "approval": False,
        "agent": True,
        "params":
            "name:str",
    },

    "mcp.native.test": {
        "description":
            "Test a configured native MCP server and list its tools.",
        "risk": "read",
        "approval": False,
        "agent": True,
        "params":
            "name:str",
    },

    "mcp.call": {
        "description":
            "Call a tool exposed by an explicitly configured MCP server.",
        "risk": "external_action",
        "approval": True,
        "agent": True,
        "params":
            "server:str, tool:str, arguments?:dict",
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

class GatewayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ToolExecuteRequest(GatewayRequest):

    tool: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9_.-]+$")

    params: dict[str, Any] = Field(
        default_factory=dict,
        max_length=100,
    )

    approved: bool = False


class BraveKeyRequest(GatewayRequest):

    api_key: str = Field(min_length=10, max_length=4096)


class AgentPlanRequest(GatewayRequest):

    goal: str = Field(min_length=1, max_length=20_000)


class AgentExecuteRequest(GatewayRequest):

    run_id: str | None = Field(default=None, max_length=64)

    goal: str = Field(min_length=1, max_length=20_000)

    plan: list[dict[str, Any]] = Field(min_length=1, max_length=50)

    approved: bool = False


class TaskCreateRequest(GatewayRequest):

    name: str = Field(min_length=1, max_length=200)

    tool: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9_.-]+$")

    params: dict[str, Any] = Field(
        default_factory=dict,
        max_length=100,
    )

    cron: str | None = Field(default=None, max_length=200)

    run_at: str | None = Field(default=None, max_length=100)

    timezone: str | None = Field(default=None, max_length=100)

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
# REDSIGHT SKILLS
# ====================================================================

def _skill_roots() -> list[Path]:

    roots = [
        HERITAGE / "skills",
        ROOT / "skills",
    ]
    configured = os.environ.get("REDSIGHT_SKILLS_DIR", "")
    roots.extend(
        Path(value).expanduser()
        for value in configured.split(os.pathsep)
        if value.strip()
    )
    workspace = os.environ.get("REDSIGHT_WORKSPACE", "").strip()
    if workspace:
        roots.append(Path(workspace).expanduser() / "skills")

    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        try:
            key = str(root.resolve())
        except OSError:
            continue
        if key not in seen:
            seen.add(key)
            unique.append(root)
    return unique


def _skill_metadata(path: Path) -> dict[str, Any]:

    text = path.read_text(encoding="utf-8-sig", errors="replace")[:32_000]
    name = path.parent.name.replace("-", " ").replace("_", " ").strip()
    description = ""
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for line in lines[1:]:
            if line.strip() == "---":
                break
            key, separator, value = line.partition(":")
            if not separator:
                continue
            cleaned = value.strip().strip("\"'")
            if key.strip().lower() == "name" and cleaned:
                name = cleaned
            elif key.strip().lower() == "description" and cleaned:
                description = cleaned
    if not name:
        heading = next((line[2:].strip() for line in lines if line.startswith("# ")), "")
        name = heading or "skill"
    if not description:
        description = next(
            (
                line.strip()
                for line in lines
                if line.strip()
                and not line.lstrip().startswith(("#", "---", "name:", "description:"))
            ),
            "Procedural RED-SIGHT skill",
        )
    return {
        "Name": name[:200],
        "Description": description[:1_000],
        "RelativePath": path.name,
        "Source": "discovered",
        "_Path": str(path.resolve()),
    }


def _catalog_item_path(item: dict[str, Any]) -> Path | None:

    internal = str(item.get("_Path", "")).strip()
    if internal:
        path = Path(internal)
        return path if path.is_file() else None
    relative = str(item.get("RelativePath", "")).strip()
    if not relative:
        return None
    try:
        path = (HERITAGE / relative).resolve()
        if not path.is_relative_to(HERITAGE.resolve()) or not path.is_file():
            return None
        return path
    except OSError:
        return None


def public_skill(item: dict[str, Any]) -> dict[str, Any]:

    return {
        str(key): value
        for key, value in item.items()
        if not str(key).startswith("_")
    }


def load_skill_catalog():

    path = (
        HERITAGE
        / "skills_catalog.json"
    )

    catalog: list[dict[str, Any]] = []
    if path.is_file() and path.stat().st_size <= 2_000_000:
        try:
            stored = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(stored, list):
                catalog.extend(item for item in stored if isinstance(item, dict))
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass

    known_paths = {
        str(skill_path.resolve())
        for item in catalog
        if (skill_path := _catalog_item_path(item)) is not None
    }
    for root in _skill_roots():
        if not root.is_dir():
            continue
        try:
            candidates = root.rglob("SKILL.md")
            for number, skill_path in enumerate(candidates):
                if number >= 1_000:
                    break
                resolved = str(skill_path.resolve())
                if resolved in known_paths or skill_path.stat().st_size > 1_000_000:
                    continue
                catalog.append(_skill_metadata(skill_path))
                known_paths.add(resolved)
        except OSError:
            continue
    return catalog


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
            [public_skill(item) for item in catalog[:limit]],
    }


async def redsight_chat(
    messages: list[dict[str, str]],
    *,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | None = None,
):
    payload: dict[str, Any] = {"messages": messages, "stream": False}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice or "auto"
    response = await _redsight_client().post(
        "/api/v1/chat",
        json=payload,
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
            "No configured RED-SIGHT skill matched: "
            + requested
        )

    item = matches[0]

    skill_path = _catalog_item_path(item)
    if skill_path is None:
        raise FileNotFoundError("The configured skill file is unavailable")

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
                        "You are RedSight using a RED-SIGHT "
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

        "native_servers":
            native_mcp.sanitized_server_definitions(),

        "servers":
            manifest.get(
                "mcp_servers",
                [],
            ),

        "config":
            sanitized,
    }


async def mcp_test(
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

    return await native_mcp.test_server(name)


async def mcp_call(
    params: dict[str, Any],
):

    server = str(
        params.get("server")
        or params.get("name")
        or ""
    ).strip()
    tool = str(
        params.get("tool")
        or ""
    ).strip()
    arguments = params.get("arguments", {})

    if not server:
        raise ValueError("server is required")
    if not tool:
        raise ValueError("tool is required")
    if not isinstance(arguments, dict):
        raise ValueError("arguments must be an object")

    return await native_mcp.call_tool(server, tool, arguments)


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

        elif tool in {"mcp.test", "mcp.native.test"}:

            result = await mcp_test(
                params
            )

        elif tool == "mcp.call":

            result = await mcp_call(
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


def agent_tool_schemas(*, exclude: set[str] | None = None) -> list[dict[str, Any]]:
    """Return native provider function definitions for agent-allowed tools."""
    return build_agent_tool_schemas(TOOL_SPECS, exclude=exclude)


def native_tool_steps(
    raw: str,
    *,
    exclude: set[str] | None = None,
) -> tuple[list[dict[str, Any]], str] | None:
    """Decode provider-native function calls into the governed plan format."""
    return decode_native_tool_steps(
        raw,
        TOOL_SPECS,
        agent_allowed=tool_agent_allowed,
        requires_approval=tool_requires_approval,
        exclude=exclude,
    )


async def create_agent_plan(
    goal: str,
):

    catalog = {name: spec for name, spec in agent_tool_catalog().items()
               if name not in {"skills.invoke", "skills.execute"}}

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
        ],
        tools=agent_tool_schemas(exclude={"skills.invoke", "skills.execute"}),
        tool_choice="auto",
    )

    native = native_tool_steps(raw, exclude={"skills.invoke", "skills.execute"})
    if native is not None:
        steps, summary = native
        return {
            "steps": steps,
            "summary": summary or "Plan selected through native provider tool calling.",
            "requires_approval": any(step["requires_approval"] for step in steps),
        }

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


async def _runtime_chat(messages, **kwargs):
    return await redsight_chat(messages, **kwargs)


async def _runtime_execute(tool, params, **kwargs):
    # Look up at execution time so the Stage 10 skills/MCP overlay is included.
    return await execute_tool_core(tool, params, **kwargs)


from redsight_actions.agent_runtime import AgentRuntime

AGENT_RUNTIME = AgentRuntime(
    chat=_runtime_chat,
    execute=_runtime_execute,
    tool_specs=lambda: TOOL_SPECS,
    allowed=tool_agent_allowed,
    requires_approval=tool_requires_approval,
    max_steps=int(os.environ.get("REDSIGHT_AGENT_MAX_STEPS", "16")),
    concurrency=int(os.environ.get("REDSIGHT_AGENT_CONCURRENCY", "2")),
)


async def execute_agent_plan(goal: str, plan: list[dict[str, Any]], *, approved: bool,
                             run_id: str | None = None):
    return await AGENT_RUNTIME.run(goal, plan, approved=approved, run_id=run_id,
                                   exclude={"skills.invoke", "skills.execute"})


# ====================================================================
# FASTAPI
# ====================================================================

app = FastAPI(
    title="RedSight Action Gateway",
    version="1.0.0",
)

_LOCAL_AUTH_HEADERS = auth_headers()
configure_local_api_security(
    app,
    public_paths={"/health"},
    header_name=next(iter(_LOCAL_AUTH_HEADERS)),
    allowed_origins=(),
)

_REDSIGHT_CLIENT: httpx.AsyncClient | None = None


def _redsight_client() -> httpx.AsyncClient:
    """Reuse loopback connections so every agent step avoids a new TCP setup."""
    global _REDSIGHT_CLIENT
    if _REDSIGHT_CLIENT is None or _REDSIGHT_CLIENT.is_closed:
        _REDSIGHT_CLIENT = httpx.AsyncClient(
            base_url=REDSIGHT_URL,
            headers=_LOCAL_AUTH_HEADERS,
            timeout=httpx.Timeout(180.0, connect=3.0, pool=3.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            trust_env=False,
        )
    return _REDSIGHT_CLIENT


@app.on_event("shutdown")
async def close_gateway_clients() -> None:
    global _REDSIGHT_CLIENT
    if _REDSIGHT_CLIENT is not None:
        await _REDSIGHT_CLIENT.aclose()
        _REDSIGHT_CLIENT = None


@app.get(
    "/health"
)
async def health():

    return {
        "status":
            "healthy",

        "service":
            "redsight-action-gateway",
        "instance_id": os.environ.get("REDSIGHT_INSTANCE_ID", ""),
        "pid": os.getpid(),

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
        run_id=request.run_id,
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
    confirm: Literal["delete"] = Query(..., description="Explicit deletion confirmation"),
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
