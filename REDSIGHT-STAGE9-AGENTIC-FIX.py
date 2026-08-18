from __future__ import annotations

import ast
import os
import re
import shutil
import textwrap
import time
from pathlib import Path


ROOT = Path(r"C:\Users\walim\RedSight")

GATEWAY9 = ROOT / "redsight_actions" / "gateway_stage9.py"
PALETTE9 = ROOT / "app" / "ui" / "action_palette_stage9.py"
LAUNCHER = ROOT / "launch_redsight_command_center.py"
OVERRIDE = ROOT / "docker-compose.override.yml"

STAMP = time.strftime("%Y%m%d-%H%M%S")

BACKUP = (
    ROOT
    / ".repair-backups"
    / ("stage9-source-" + STAMP)
)

BACKUP.mkdir(
    parents=True,
    exist_ok=True,
)


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


def backup(path: Path):
    if path.exists():
        shutil.copy2(
            path,
            BACKUP / (path.name + ".before"),
        )


for item in (
    GATEWAY9,
    PALETTE9,
    LAUNCHER,
    OVERRIDE,
):
    backup(item)


# ======================================================================
# STAGE-9 ACTION GATEWAY OVERLAY
# ======================================================================

GATEWAY_SOURCE = r'''
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from collections import Counter
from pathlib import Path
from typing import Any


import httpx

from redsight_actions import gateway as base


app = base.app

ROOT = Path(__file__).resolve().parents[1]

USERPROFILE = Path(
    os.environ.get(
        "USERPROFILE",
        r"C:\Users\walim",
    )
)

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

INVENTORY_DB = (
    ACTION_HOME
    / "system-inventory.sqlite"
)


# ======================================================================
# NEW TOOL REGISTRY
# ======================================================================

base.TOOL_SPECS.update(
    {
        "system.roots": {
            "description":
                "Discover the Windows user profile, OneDrive roots, "
                "and available C/D knowledge roots.",
            "risk":
                "read",
            "approval":
                False,
            "agent":
                True,
            "params":
                "",
        },

        "system.scan": {
            "description":
                "Perform a real read-only metadata inventory of the "
                "Windows computer, a user directory, D drive, OneDrive, "
                "or an explicit C/D path. Stores a persistent inventory "
                "database and JSON summary. Does not modify source files.",
            "risk":
                "read",
            "approval":
                False,
            "agent":
                True,
            "params":
                "scope:'all'|'user'|'onedrive'|'d'|PATH, "
                "max_files?:int, max_seconds?:int",
        },

        "rag.index": {
            "description":
                "Index an approved host directory into RedSight RAG using "
                "the existing RedSight indexing API. Supports aliases "
                "'onedrive', 'user', 'd', and 'all-knowledge'. "
                "Original files remain read-only.",
            "risk":
                "knowledge_write",
            "approval":
                False,
            "agent":
                True,
            "params":
                "paths:list[str]|str, collection?:str, project?:str",
        },
    }
)


# Save original Stage-8 functions before monkey-patching.
_STAGE8_EXECUTE = base.execute_tool_core
_STAGE8_PLAN = base.create_agent_plan
_STAGE8_EXEC_PLAN = base.execute_agent_plan


# ======================================================================
# ONEDRIVE / ROOT DISCOVERY
# ======================================================================

def _unique_paths(
    values: list[Path],
) -> list[Path]:

    result = []
    seen = set()

    for value in values:

        try:
            value = Path(value)
        except Exception:
            continue

        if not value.exists():
            continue

        key = os.path.normcase(
            os.path.abspath(
                str(value)
            )
        )

        if key in seen:
            continue

        seen.add(key)
        result.append(value)

    return result


def discover_onedrive_roots() -> list[Path]:

    candidates = []

    for variable in (
        "OneDrive",
        "OneDriveConsumer",
        "OneDriveCommercial",
    ):

        value = os.environ.get(
            variable
        )

        if value:

            candidates.append(
                Path(value)
            )

    candidates.append(
        USERPROFILE
        / "OneDrive"
    )

    try:

        for item in USERPROFILE.glob(
            "OneDrive*"
        ):

            if item.is_dir():

                candidates.append(
                    item
                )

    except Exception:

        pass

    return _unique_paths(
        candidates
    )


def roots_result():

    onedrive = discover_onedrive_roots()

    return {
        "ok":
            True,

        "user_profile":
            str(
                USERPROFILE
            ),

        "c_drive":
            "C:\\",

        "d_drive":
            (
                "D:\\"
                if Path("D:/").exists()
                else None
            ),

        "onedrive_roots":
            [
                str(path)
                for path in onedrive
            ],

        "docker_rag_mounts": {
            "user":
                "/host/user",

            "d":
                (
                    "/host/d"
                    if Path("D:/").exists()
                    else None
                ),
        },
    }


# ======================================================================
# SYSTEM SCANNER
# ======================================================================

SKIP_DIRS = {
    "$recycle.bin",
    "system volume information",
    "windows",
    "program files",
    "program files (x86)",
    "programdata",
    "recovery",
    "$winreagent",
    "__pycache__",
    "node_modules",
    ".git",
    ".svn",
    ".hg",
    ".venv",
    "venv",
    ".cache",
    "temp",
    "tmp",
    ".ssh",
    ".gnupg",
}

SENSITIVE_NAMES = {
    "id_rsa",
    "id_ed25519",
    "credentials",
    "credentials.json",
    "cookies",
    "cookies.sqlite",
    "login data",
    "web data",
    "ntuser.dat",
}

KNOWLEDGE_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".pdf",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
    ".csv",
    ".json",
    ".jsonl",
    ".yaml",
    ".yml",
    ".xml",
    ".html",
    ".htm",
    ".py",
    ".ps1",
    ".psm1",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".sql",
    ".ipynb",
    ".toml",
    ".ini",
    ".cfg",
    ".log",
}


def resolve_scan_roots(
    scope: str,
) -> list[Path]:

    value = (
        str(scope or "all")
        .strip()
    )

    lowered = value.lower()

    if lowered in {
        "all",
        "system",
        "computer",
        "entire system",
    }:

        roots = [
            Path("C:/"),
        ]

        if Path("D:/").exists():

            roots.append(
                Path("D:/")
            )

        return roots

    if lowered in {
        "user",
        "profile",
        "home",
    }:

        return [
            USERPROFILE
        ]

    if lowered in {
        "onedrive",
        "one drive",
    }:

        roots = discover_onedrive_roots()

        if not roots:

            raise FileNotFoundError(
                "No OneDrive root was discovered."
            )

        return roots

    if lowered in {
        "d",
        "d:",
        "d:\\",
    }:

        root = Path("D:/")

        if not root.exists():

            raise FileNotFoundError(
                "D: drive is not available."
            )

        return [
            root
        ]

    path = base.validated_path(
        value
    )

    if not path.exists():

        raise FileNotFoundError(
            str(path)
        )

    return [
        path
    ]


def system_scan(
    params: dict[str, Any],
):

    scope = str(
        params.get(
            "scope",
            "all",
        )
    )

    max_files = min(
        max(
            int(
                params.get(
                    "max_files",
                    250000,
                )
            ),
            100,
        ),
        1000000,
    )

    max_seconds = min(
        max(
            int(
                params.get(
                    "max_seconds",
                    300,
                )
            ),
            10,
        ),
        1800,
    )

    roots = resolve_scan_roots(
        scope
    )

    scan_id = (
        time.strftime(
            "%Y%m%d-%H%M%S"
        )
        + "-"
        + str(
            os.getpid()
        )
    )

    connection = sqlite3.connect(
        str(
            INVENTORY_DB
        )
    )

    connection.execute(
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

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_files_scan
        ON files(scan_id)
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_files_extension
        ON files(extension)
        """
    )

    started = time.monotonic()

    file_count = 0
    directory_count = 0
    total_bytes = 0
    knowledge_count = 0

    errors = 0

    extensions = Counter()
    roots_summary = Counter()

    sample_knowledge = []

    complete = True
    stop_reason = None

    try:

        for root in roots:

            root_text = str(
                root
            )

            for current, dirs, files in os.walk(
                root,
                topdown=True,
                onerror=lambda _error: None,
            ):

                directory_count += 1

                # Remove known unsafe/noisy trees before recursion.
                safe_dirs = []

                for directory in dirs:

                    lower = (
                        directory
                        .strip()
                        .lower()
                    )

                    if lower in SKIP_DIRS:

                        continue

                    safe_dirs.append(
                        directory
                    )

                dirs[:] = safe_dirs

                for filename in files:

                    if (
                        time.monotonic()
                        - started
                        >= max_seconds
                    ):

                        complete = False
                        stop_reason = (
                            "max_seconds reached"
                        )
                        break

                    if file_count >= max_files:

                        complete = False
                        stop_reason = (
                            "max_files reached"
                        )
                        break

                    if filename.lower() in SENSITIVE_NAMES:

                        continue

                    path = (
                        Path(current)
                        / filename
                    )

                    try:

                        stat = path.stat()

                    except Exception:

                        errors += 1
                        continue

                    extension = (
                        path.suffix
                        .lower()
                    )

                    candidate = (
                        extension
                        in KNOWLEDGE_EXTENSIONS
                    )

                    file_count += 1

                    total_bytes += int(
                        stat.st_size
                    )

                    extensions[
                        extension
                        or "<none>"
                    ] += 1

                    roots_summary[
                        root_text
                    ] += 1

                    if candidate:

                        knowledge_count += 1

                        if (
                            len(
                                sample_knowledge
                            )
                            < 200
                        ):

                            sample_knowledge.append(
                                str(path)
                            )

                    connection.execute(
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
                            int(
                                stat.st_size
                            ),
                            float(
                                stat.st_mtime
                            ),
                            extension,
                            1
                            if candidate
                            else 0,
                        ),
                    )

                    if (
                        file_count
                        % 1000
                        == 0
                    ):

                        connection.commit()

                if not complete:

                    break

            if not complete:

                break

        connection.commit()

    finally:

        connection.close()

    elapsed = (
        time.monotonic()
        - started
    )

    report = {
        "ok":
            True,

        "scan_id":
            scan_id,

        "scope":
            scope,

        "roots":
            [
                str(path)
                for path in roots
            ],

        "complete":
            complete,

        "stop_reason":
            stop_reason,

        "elapsed_seconds":
            round(
                elapsed,
                2,
            ),

        "files_seen":
            file_count,

        "directories_seen":
            directory_count,

        "total_bytes":
            total_bytes,

        "knowledge_candidates":
            knowledge_count,

        "errors_skipped":
            errors,

        "top_extensions":
            extensions.most_common(
                30
            ),

        "files_by_root":
            dict(
                roots_summary
            ),

        "knowledge_samples":
            sample_knowledge,

        "inventory_database":
            str(
                INVENTORY_DB
            ),

        "note":
            (
                "Protected operating-system, credential, cache, "
                "virtual-environment, node_modules and similar trees "
                "are deliberately excluded from recursive scanning."
            ),
    }

    report_path = (
        OUTPUT_HOME
        / (
            "system-scan-"
            + scan_id
            + ".json"
        )
    )

    report_path.write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report[
        "report_path"
    ] = str(
        report_path
    )

    return report


# ======================================================================
# HOST WINDOWS PATH -> DOCKER RAG PATH
# ======================================================================

def _is_relative_to(
    path: Path,
    parent: Path,
) -> bool:

    try:

        path.resolve().relative_to(
            parent.resolve()
        )

        return True

    except Exception:

        return False


def map_host_to_container(
    path: Path,
) -> str:

    path = Path(
        os.path.abspath(
            str(path)
        )
    )

    if _is_relative_to(
        path,
        USERPROFILE,
    ):

        relative = path.resolve().relative_to(
            USERPROFILE.resolve()
        )

        if str(relative) == ".":

            return "/host/user"

        return (
            "/host/user/"
            + relative.as_posix()
        )

    d_root = Path("D:/")

    if (
        d_root.exists()
        and _is_relative_to(
            path,
            d_root,
        )
    ):

        relative = path.resolve().relative_to(
            d_root.resolve()
        )

        if str(relative) == ".":

            return "/host/d"

        return (
            "/host/d/"
            + relative.as_posix()
        )

    raise ValueError(
        "RAG indexing is currently limited to the "
        "Windows user profile and D: read-only Docker mounts."
    )


def resolve_rag_paths(
    raw_paths: Any,
) -> list[Path]:

    if isinstance(
        raw_paths,
        str,
    ):

        raw_paths = [
            raw_paths
        ]

    if not isinstance(
        raw_paths,
        list,
    ):

        raise ValueError(
            "paths must be a string or list."
        )

    results = []

    for raw in raw_paths:

        value = str(
            raw
        ).strip()

        lowered = value.lower()

        if lowered in {
            "onedrive",
            "one drive",
        }:

            results.extend(
                discover_onedrive_roots()
            )

        elif lowered in {
            "user",
            "profile",
        }:

            results.append(
                USERPROFILE
            )

        elif lowered in {
            "d",
            "d:",
            "d:\\",
        }:

            if Path("D:/").exists():

                results.append(
                    Path("D:/")
                )

        elif lowered in {
            "all-knowledge",
            "knowledge",
        }:

            results.append(
                USERPROFILE
            )

            if Path("D:/").exists():

                results.append(
                    Path("D:/")
                )

        else:

            path = base.validated_path(
                value
            )

            if not path.exists():

                raise FileNotFoundError(
                    str(path)
                )

            results.append(
                path
            )

    return _unique_paths(
        results
    )


async def rag_index(
    params: dict[str, Any],
):

    paths = resolve_rag_paths(
        params.get(
            "paths",
            [
                "onedrive"
            ],
        )
    )

    if not paths:

        return {
            "ok":
                False,

            "error":
                "No matching indexable host paths were discovered.",
        }

    collection = str(
        params.get(
            "collection",
            "knowledge_docs",
        )
    ).strip()

    project = str(
        params.get(
            "project",
            "host-knowledge",
        )
    ).strip()

    results = []

    async with httpx.AsyncClient(
        timeout=600.0,
    ) as client:

        for path in paths:

            container_path = map_host_to_container(
                path
            )

            try:

                response = await client.post(
                    base.REDSIGHT_URL
                    + "/api/v1/jobs/index/batch",

                    json={
                        "paths": [
                            container_path
                        ],

                        "collection":
                            collection,

                        "project":
                            project,
                    },
                )

                try:

                    payload = response.json()

                except Exception:

                    payload = {
                        "text":
                            response.text[
                                :5000
                            ]
                    }

                results.append(
                    {
                        "host_path":
                            str(path),

                        "container_path":
                            container_path,

                        "status_code":
                            response.status_code,

                        "ok":
                            response.is_success,

                        "response":
                            payload,
                    }
                )

            except Exception as exc:

                results.append(
                    {
                        "host_path":
                            str(path),

                        "container_path":
                            container_path,

                        "ok":
                            False,

                        "error":
                            repr(exc),
                    }
                )

    return {
        "ok":
            all(
                bool(
                    item.get(
                        "ok",
                        False,
                    )
                )
                for item in results
            ),

        "collection":
            collection,

        "project":
            project,

        "results":
            results,
    }


# ======================================================================
# TOOL EXECUTION OVERLAY
# ======================================================================

async def execute_tool_stage9(
    tool: str,
    params: dict[str, Any],
    *,
    approved: bool = False,
):

    if tool == "system.roots":

        result = roots_result()

        base.audit(
            tool,
            params,
            approved=approved,
            ok=True,
        )

        return result

    if tool == "system.scan":

        try:

            result = system_scan(
                params
            )

            base.audit(
                tool,
                params,
                approved=approved,
                ok=True,
            )

            return result

        except Exception as exc:

            base.audit(
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

    if tool == "rag.index":

        try:

            result = await rag_index(
                params
            )

            base.audit(
                tool,
                params,
                approved=approved,
                ok=bool(
                    result.get(
                        "ok",
                        False,
                    )
                ),
            )

            return result

        except Exception as exc:

            base.audit(
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

    return await _STAGE8_EXECUTE(
        tool,
        params,
        approved=approved,
    )


base.execute_tool_core = (
    execute_tool_stage9
)


# ======================================================================
# DETERMINISTIC AGENT ROUTING
# ======================================================================

def _contains_any(
    text: str,
    terms: tuple[str, ...],
) -> bool:

    return any(
        term in text
        for term in terms
    )


def forced_agent_steps(
    goal: str,
) -> list[dict[str, Any]]:

    lower = (
        str(goal)
        .strip()
        .lower()
    )

    steps = []

    scan_requested = _contains_any(
        lower,
        (
            "scan",
            "inventory",
            "inspect my files",
            "inspect my system",
            "inspect my computer",
            "map my files",
            "map my system",
        ),
    )

    onedrive_requested = _contains_any(
        lower,
        (
            "onedrive",
            "one drive",
        ),
    )

    whole_system = _contains_any(
        lower,
        (
            "entire system",
            "whole system",
            "entire computer",
            "whole computer",
            "all drives",
            "drive c and drive d",
            "c drive and d drive",
        ),
    )

    learn_requested = _contains_any(
        lower,
        (
            "learn from",
            "index",
            "rag",
            "knowledge base",
            "add to your knowledge",
            "remember these files",
            "ingest",
        ),
    )

    web_requested = _contains_any(
        lower,
        (
            "research",
            "web search",
            "search the web",
            "latest information",
            "latest info",
            "look online",
            "internet",
        ),
    )

    if scan_requested:

        if whole_system:

            scope = "all"

        elif onedrive_requested:

            scope = "onedrive"

        else:

            scope = "user"

        steps.append(
            {
                "tool":
                    "system.scan",

                "params": {
                    "scope":
                        scope,

                    "max_files":
                        250000,

                    "max_seconds":
                        300,
                },

                "reason":
                    (
                        "Perform a real read-only filesystem inventory "
                        "before reasoning about the computer's contents."
                    ),

                "requires_approval":
                    False,
            }
        )

    if learn_requested:

        if whole_system:

            index_paths = [
                "user",
                "d",
            ]

            if onedrive_requested:

                index_paths.insert(
                    0,
                    "onedrive",
                )

        elif onedrive_requested:

            index_paths = [
                "onedrive"
            ]

        else:

            index_paths = [
                "user"
            ]

        # Deduplicate while retaining order.
        clean_paths = []

        for path in index_paths:

            if path not in clean_paths:

                clean_paths.append(
                    path
                )

        steps.append(
            {
                "tool":
                    "rag.index",

                "params": {
                    "paths":
                        clean_paths,

                    "collection":
                        "knowledge_docs",

                    "project":
                        "personal-knowledge",
                },

                "reason":
                    (
                        "Index the knowledge-bearing host directories "
                        "into RedSight's existing RAG infrastructure."
                    ),

                "requires_approval":
                    False,
            }
        )

    if web_requested:

        steps.append(
            {
                "tool":
                    "web.search",

                "params": {
                    "query":
                        goal,

                    "count":
                        10,
                },

                "reason":
                    (
                        "Use live web results because the request "
                        "explicitly asks for external research."
                    ),

                "requires_approval":
                    False,
            }
        )

    return steps


async def create_agent_plan_stage9(
    goal: str,
):

    forced = forced_agent_steps(
        goal
    )

    model_plan = {
        "steps":
            [],

        "summary":
            "",
    }

    # For clear scan/index requests the deterministic tools are more
    # reliable than asking the LLM whether it believes it has access.
    if forced:

        try:

            candidate = await _STAGE8_PLAN(
                goal
            )

            if isinstance(
                candidate,
                dict,
            ):

                model_plan = candidate

        except Exception:

            pass

    else:

        return await _STAGE8_PLAN(
            goal
        )

    merged = []

    seen = set()

    for step in (
        forced
        + list(
            model_plan.get(
                "steps",
                []
            )
        )
    ):

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

        if not base.tool_agent_allowed(
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

        seen.add(
            signature
        )

        merged.append(
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
                    base.tool_requires_approval(
                        tool
                    ),
            }
        )

    return {
        "steps":
            merged[:8],

        "summary":
            (
                str(
                    model_plan.get(
                        "summary",
                        ""
                    )
                )[:1000]
                or "RedSight generated an executable local action plan."
            ),

        "requires_approval":
            any(
                step[
                    "requires_approval"
                ]
                for step in merged
            ),
    }


base.create_agent_plan = (
    create_agent_plan_stage9
)


# ======================================================================
# HEALTH / DISCOVERY ENDPOINTS
# ======================================================================

@app.get(
    "/stage9/roots"
)
async def stage9_roots():

    return roots_result()


@app.get(
    "/stage9/status"
)
async def stage9_status():

    return {
        "ok":
            True,

        "stage":
            9,

        "natural_action_routing":
            True,

        "system_scan":
            True,

        "rag_index":
            True,

        "onedrive_roots":
            [
                str(path)
                for path
                in discover_onedrive_roots()
            ],

        "inventory_database":
            str(
                INVENTORY_DB
            ),

        "tool_count":
            len(
                base.TOOL_SPECS
            ),
    }
'''

GATEWAY_SOURCE = textwrap.dedent(
    GATEWAY_SOURCE
).lstrip()

ast.parse(
    GATEWAY_SOURCE,
    filename=str(
        GATEWAY9
    ),
)

write_text(
    GATEWAY9,
    GATEWAY_SOURCE,
)


# ======================================================================
# STAGE-9 UI / NATURAL LANGUAGE ROUTER
# ======================================================================

PALETTE_SOURCE = r'''
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
'''

PALETTE_SOURCE = textwrap.dedent(
    PALETTE_SOURCE
).lstrip()

ast.parse(
    PALETTE_SOURCE,
    filename=str(
        PALETTE9
    ),
)

write_text(
    PALETTE9,
    PALETTE_SOURCE,
)


# ======================================================================
# PATCH LAUNCHER TO LOAD STAGE-9 OVERLAY
# ======================================================================

launcher = read_text(
    LAUNCHER
)

# Remove either Stage-8 or prior Stage-9 action imports/calls.
launcher = re.sub(
    r"(?m)^from app\.ui\.action_palette(?:_stage9)? "
    r"import install_action_hooks, attach_action_palette\s*$\n?",
    "",
    launcher,
)

launcher = re.sub(
    r"(?m)^\s*install_action_hooks\(CommandCenterMainWindow\)\s*$\n?",
    "",
    launcher,
)

launcher = re.sub(
    r"(?m)^\s*attach_action_palette\(.*?\)\s*$\n?",
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

integration = (
    "\n"
    "from app.ui.action_palette_stage9 "
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

attach = (
    indent
    + "attach_action_palette("
    + "window, Path(__file__).resolve().parent"
    + ")"
)

launcher = (
    launcher[:window_match.end()]
    + "\n"
    + attach
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


# ======================================================================
# ADD READ-ONLY HOST DATA MOUNTS
#
# We deliberately mount:
#   C:\Users\walim -> /host/user  READ ONLY
#   D:\             -> /host/d     READ ONLY
#
# We do NOT mount C:\Windows or the whole C drive into RedSight RAG.
# Host-side system.scan can still inventory C:, but RAG focuses on
# personal/project knowledge.
# ======================================================================

compose = read_text(
    OVERRIDE
)

need_user = (
    "/host/user"
    not in compose
)

need_d = (
    Path("D:/").exists()
    and
    "/host/d"
    not in compose
)

if need_user or need_d:

    lines = compose.splitlines()

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
            "redsight service not found in docker-compose.override.yml"
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

    mount_lines = []

    if need_user:

        mount_lines.extend(
            [
                "      - type: bind",
                '        source: "C:/Users/walim"',
                "        target: /host/user",
                "        read_only: true",
            ]
        )

    if need_d:

        mount_lines.extend(
            [
                "      - type: bind",
                '        source: "D:/"',
                "        target: /host/d",
                "        read_only: true",
            ]
        )

    if volumes_index is not None:

        insert_at = (
            volumes_index
            + 1
        )

        lines[
            insert_at:
            insert_at
        ] = mount_lines

    else:

        environment_index = None

        for index in range(
            service_start + 1,
            service_end,
        ):

            if re.match(
                r"^\s{4}environment:\s*$",
                lines[index],
            ):

                environment_index = index
                break

        if environment_index is None:

            environment_index = (
                service_start
                + 1
            )

        lines[
            environment_index:
            environment_index
        ] = (
            [
                "    volumes:",
            ]
            + mount_lines
        )

    write_text(
        OVERRIDE,
        "\n".join(
            lines
        )
        + "\n",
    )


# ======================================================================
# STARTUP FILE
# ======================================================================

startup_dir = (
    Path(
        os.environ["APPDATA"]
    )
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

pythonw = (
    ROOT
    / ".venv-actions"
    / "Scripts"
    / "pythonw.exe"
)

python = (
    ROOT
    / ".venv-actions"
    / "Scripts"
    / "python.exe"
)

exe = (
    pythonw
    if pythonw.exists()
    else python
)

startup = (
    startup_dir
    / "RedSight-Action-Gateway.cmd"
)

write_text(
    startup,
    (
        "@echo off\n"
        'cd /d "C:\\Users\\walim\\RedSight"\n'
        'start "" /min "'
        + str(exe)
        + '" -m uvicorn '
        + "redsight_actions.gateway_stage9:app "
        + "--host 127.0.0.1 "
        + "--port 8765 "
        + "--log-level warning\n"
    ),
)

manual = (
    ROOT
    / "START-REDSIGHT-ACTIONS.cmd"
)

write_text(
    manual,
    (
        "@echo off\n"
        'cd /d "C:\\Users\\walim\\RedSight"\n'
        '"'
        + str(python)
        + '" -m uvicorn '
        + "redsight_actions.gateway_stage9:app "
        + "--host 127.0.0.1 "
        + "--port 8765 "
        + "--log-level info\n"
    ),
)


# ======================================================================
# FINAL STATIC VALIDATION
# ======================================================================

for path in (
    GATEWAY9,
    PALETTE9,
    LAUNCHER,
):

    ast.parse(
        read_text(
            path
        ),
        filename=str(
            path
        ),
    )

print(
    "GATEWAY_STAGE9_SOURCE=PASS"
)

print(
    "PALETTE_STAGE9_SOURCE=PASS"
)

print(
    "LAUNCHER_STAGE9_SOURCE=PASS"
)

print(
    "SOURCE_BACKUP="
    + str(
        BACKUP
    )
)