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
