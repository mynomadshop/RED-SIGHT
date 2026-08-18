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
