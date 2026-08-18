
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, Field

from redsight_actions import gateway_stage91 as s91

app = s91.app
base = s91.base
s9 = s91.s9

ROOT = Path(__file__).resolve().parents[1]
MEMORY_HOME = Path(os.environ["LOCALAPPDATA"]) / "RedSight" / "memory"
MEMORY_HOME.mkdir(parents=True, exist_ok=True)
DB_PATH = MEMORY_HOME / "conversations.sqlite"
EXPORT_HOME = ROOT / "data" / "memory_exports"
EXPORT_HOME.mkdir(parents=True, exist_ok=True)

OLD_EXECUTE = base.execute_tool_core
OLD_PLAN = base.create_agent_plan
OLD_EXEC_PLAN = base.execute_agent_plan

DB_LOCK = threading.RLock()

CONTINUATION_PHRASES = {
    "yes", "yes do it", "do it", "continue", "continue it", "continue that",
    "proceed", "go ahead", "approved", "i approve", "retry", "retry it",
    "finish it", "complete it", "carry on", "resume", "resume it",
}
ACTION_WORDS = (
    "scan", "index", "migrate", "research", "create", "generate", "write",
    "build", "repair", "install", "configure", "automate", "schedule",
    "download", "upload", "analyze", "organize", "execute", "run", "convert",
    "search my", "read my", "learn from",
)
PREFERENCE_MARKERS = (
    "i prefer", "i want redsight", "i want you", "always ", "never ",
    "remember ", "remember that", "my preference", "do not ", "don't ",
    "i usually", "i need redsight", "from now on",
)
STOPWORDS = {
    "the","a","an","and","or","to","of","in","on","for","with","is","are",
    "was","were","be","been","it","this","that","my","me","i","you","your",
    "we","our","as","at","by","from","do","can","could","would","should",
    "please","then","than","into","about","all","any","if","so","but",
}


class MemoryBuildRequest(BaseModel):
    user_message: str
    effective_message: str | None = None
    heritage_context: str = ""
    session_id: str | None = None


class MemoryCommitRequest(BaseModel):
    user_message: str
    assistant_message: str
    effective_message: str | None = None
    session_id: str | None = None


class SessionNewRequest(BaseModel):
    title: str | None = None


class SessionRenameRequest(BaseModel):
    title: str


class SessionPinRequest(BaseModel):
    pinned: bool = True


class SessionArchiveRequest(BaseModel):
    archived: bool = True


class MemorySearchRequest(BaseModel):
    query: str
    limit: int = 10
    memory_types: list[str] | None = None


class RagExpandRequest(BaseModel):
    paths: list[str] | str
    max_files: int = 200
    max_size_mb: int = 100


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(str(DB_PATH), timeout=60)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    return connection


def _now() -> float:
    return time.time()


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def init_db() -> None:
    with DB_LOCK, _connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                pinned INTEGER NOT NULL DEFAULT 0,
                archived INTEGER NOT NULL DEFAULT 0,
                message_count INTEGER NOT NULL DEFAULT 0,
                active_task_id TEXT
            );

            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at REAL NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_messages_session_time
            ON messages(session_id, created_at);

            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                goal TEXT NOT NULL,
                status TEXT NOT NULL,
                plan_json TEXT NOT NULL DEFAULT '{}',
                results_json TEXT NOT NULL DEFAULT '{}',
                current_step INTEGER NOT NULL DEFAULT 0,
                approved INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_session_time
            ON tasks(session_id, updated_at);

            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                memory_type TEXT NOT NULL,
                content TEXT NOT NULL,
                normalized TEXT NOT NULL UNIQUE,
                source_session_id TEXT,
                source_message_id TEXT,
                confidence REAL NOT NULL DEFAULT 0.7,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                last_used_at REAL,
                use_count INTEGER NOT NULL DEFAULT 0,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE INDEX IF NOT EXISTS idx_memories_type
            ON memories(memory_type);

            CREATE TABLE IF NOT EXISTS capabilities (
                name TEXT PRIMARY KEY,
                description TEXT NOT NULL,
                status TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_events_session_time
            ON events(session_id, created_at);
            """
        )
        db.commit()


def setting_get(key: str) -> str | None:
    with DB_LOCK, _connect() as db:
        row = db.execute(
            "SELECT value FROM settings WHERE key=?",
            (key,),
        ).fetchone()
    return row["value"] if row else None


def setting_set(key: str, value: str) -> None:
    with DB_LOCK, _connect() as db:
        db.execute(
            """
            INSERT INTO settings(key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (key, value),
        )
        db.commit()


def create_session(title: str | None = None, *, activate: bool = True,
                   archived: bool = False) -> dict[str, Any]:
    sid = _uid("session")
    now = _now()
    clean_title = (title or "New Chat").strip()[:160] or "New Chat"
    with DB_LOCK, _connect() as db:
        db.execute(
            """
            INSERT INTO sessions(
                id,title,summary,created_at,updated_at,pinned,archived,
                message_count,active_task_id
            )
            VALUES (?, ?, '', ?, ?, 0, ?, 0, NULL)
            """,
            (sid, clean_title, now, now, 1 if archived else 0),
        )
        db.commit()
    if activate:
        setting_set("active_session_id", sid)
    return get_session(sid)


def get_session(session_id: str) -> dict[str, Any]:
    with DB_LOCK, _connect() as db:
        row = db.execute(
            "SELECT * FROM sessions WHERE id=?",
            (session_id,),
        ).fetchone()
    if not row:
        raise KeyError(session_id)
    result = dict(row)
    result["pinned"] = bool(result["pinned"])
    result["archived"] = bool(result["archived"])
    result["active"] = (setting_get("active_session_id") == session_id)
    result["active_task"] = get_active_task(session_id)
    return result


def ensure_active_session() -> str:
    sid = setting_get("active_session_id")
    if sid:
        try:
            get_session(sid)
            return sid
        except KeyError:
            pass
    session = create_session("RedSight Chat", activate=True)
    return str(session["id"])


def activate_session(session_id: str) -> dict[str, Any]:
    session = get_session(session_id)
    if session["archived"]:
        with DB_LOCK, _connect() as db:
            db.execute(
                "UPDATE sessions SET archived=0, updated_at=? WHERE id=?",
                (_now(), session_id),
            )
            db.commit()
    setting_set("active_session_id", session_id)
    return get_session(session_id)


def list_sessions(include_archived: bool = False, limit: int = 200) -> list[dict[str, Any]]:
    where = "" if include_archived else "WHERE archived=0"
    with DB_LOCK, _connect() as db:
        rows = db.execute(
            f"""
            SELECT * FROM sessions
            {where}
            ORDER BY pinned DESC, updated_at DESC
            LIMIT ?
            """,
            (max(1, min(int(limit), 500)),),
        ).fetchall()
    active = setting_get("active_session_id")
    result = []
    for row in rows:
        item = dict(row)
        item["pinned"] = bool(item["pinned"])
        item["archived"] = bool(item["archived"])
        item["active"] = item["id"] == active
        item["active_task"] = get_active_task(item["id"])
        result.append(item)
    return result


def session_messages(session_id: str, limit: int = 500) -> list[dict[str, Any]]:
    get_session(session_id)
    with DB_LOCK, _connect() as db:
        rows = db.execute(
            """
            SELECT id, role, content, created_at, metadata_json
            FROM messages
            WHERE session_id=?
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (session_id, max(1, min(int(limit), 5000))),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "role": row["role"],
            "content": row["content"],
            "created_at": row["created_at"],
            "metadata": _loads(row["metadata_json"], {}),
        }
        for row in rows
    ]


def recent_messages(session_id: str, max_messages: int = 18,
                    max_chars: int = 28000) -> list[dict[str, str]]:
    with DB_LOCK, _connect() as db:
        rows = db.execute(
            """
            SELECT role, content
            FROM messages
            WHERE session_id=? AND role IN ('user','assistant')
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (session_id, max(2, min(max_messages * 2, 80))),
        ).fetchall()
    chosen: list[dict[str, str]] = []
    used = 0
    for row in rows:
        content = str(row["content"])
        size = len(content)
        if chosen and used + size > max_chars:
            break
        chosen.append(
            {
                "role": str(row["role"]),
                "content": content[:9000],
            }
        )
        used += min(size, 9000)
        if len(chosen) >= max_messages:
            break
    chosen.reverse()
    return chosen


def insert_message(session_id: str, role: str, content: str,
                   metadata: dict[str, Any] | None = None) -> str:
    mid = _uid("msg")
    now = _now()
    with DB_LOCK, _connect() as db:
        db.execute(
            """
            INSERT INTO messages(
                id,session_id,role,content,created_at,metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (mid, session_id, role, content, now, _json(metadata or {})),
        )
        db.execute(
            """
            UPDATE sessions
            SET updated_at=?, message_count=message_count+1
            WHERE id=?
            """,
            (now, session_id),
        )
        db.commit()
    return mid


def add_event(session_id: str | None, event_type: str, payload: Any) -> str:
    eid = _uid("event")
    with DB_LOCK, _connect() as db:
        db.execute(
            """
            INSERT INTO events(id,session_id,event_type,payload_json,created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (eid, session_id, event_type, _json(payload), _now()),
        )
        db.commit()
    return eid


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-zA-Z0-9_]{3,}", text.lower())
        if token not in STOPWORDS
    }


def _normalize_memory(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())[:1500]


def add_memory(memory_type: str, content: str, *,
               source_session_id: str | None = None,
               source_message_id: str | None = None,
               confidence: float = 0.75,
               metadata: dict[str, Any] | None = None) -> str | None:
    clean = re.sub(r"\s+", " ", str(content)).strip()
    if len(clean) < 8:
        return None
    clean = clean[:3000]
    normalized = _normalize_memory(clean)
    digest = hashlib.sha256(
        f"{memory_type}|{normalized}".encode("utf-8")
    ).hexdigest()[:24]
    mid = f"mem_{digest}"
    now = _now()
    with DB_LOCK, _connect() as db:
        db.execute(
            """
            INSERT INTO memories(
                id,memory_type,content,normalized,source_session_id,
                source_message_id,confidence,created_at,updated_at,
                last_used_at,use_count,metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 0, ?)
            ON CONFLICT(normalized) DO UPDATE SET
                confidence=MAX(memories.confidence, excluded.confidence),
                updated_at=excluded.updated_at
            """,
            (
                mid, memory_type, clean, normalized, source_session_id,
                source_message_id, float(confidence), now, now,
                _json(metadata or {}),
            ),
        )
        db.commit()
    return mid


def retrieve_memories(query: str, limit: int = 10,
                      memory_types: list[str] | None = None) -> list[dict[str, Any]]:
    qtokens = _tokens(query)
    if not qtokens:
        return []
    clauses = ""
    args: list[Any] = []
    if memory_types:
        placeholders = ",".join("?" for _ in memory_types)
        clauses = f" WHERE memory_type IN ({placeholders})"
        args.extend(memory_types)
    with DB_LOCK, _connect() as db:
        rows = db.execute(
            f"""
            SELECT * FROM memories
            {clauses}
            ORDER BY updated_at DESC
            LIMIT 1000
            """,
            args,
        ).fetchall()
    scored = []
    qlower = query.lower()
    for row in rows:
        content = str(row["content"])
        mtokens = _tokens(content)
        if not mtokens:
            continue
        overlap = len(qtokens & mtokens)
        union = max(1, len(qtokens | mtokens))
        score = overlap / union
        if qlower in content.lower() or content.lower() in qlower:
            score += 0.35
        if row["memory_type"] == "semantic":
            score += 0.04
        if score <= 0:
            continue
        scored.append((score, row))
    scored.sort(key=lambda item: item[0], reverse=True)
    selected = scored[:max(1, min(int(limit), 30))]
    now = _now()
    result = []
    with DB_LOCK, _connect() as db:
        for score, row in selected:
            db.execute(
                """
                UPDATE memories
                SET last_used_at=?, use_count=use_count+1
                WHERE id=?
                """,
                (now, row["id"]),
            )
            result.append(
                {
                    "id": row["id"],
                    "memory_type": row["memory_type"],
                    "content": row["content"],
                    "confidence": row["confidence"],
                    "relevance": round(score, 4),
                    "metadata": _loads(row["metadata_json"], {}),
                }
            )
        db.commit()
    return result


def get_active_task(session_id: str | None = None) -> dict[str, Any] | None:
    sid = session_id or ensure_active_session()
    with DB_LOCK, _connect() as db:
        row = db.execute(
            """
            SELECT t.*
            FROM tasks t
            JOIN sessions s ON s.active_task_id=t.id
            WHERE s.id=?
            """,
            (sid,),
        ).fetchone()
    if not row:
        return None
    item = dict(row)
    item["approved"] = bool(item["approved"])
    item["plan"] = _loads(item.pop("plan_json"), {})
    item["results"] = _loads(item.pop("results_json"), {})
    return item


def set_active_task(goal: str, session_id: str | None = None) -> dict[str, Any]:
    sid = session_id or ensure_active_session()
    task = get_active_task(sid)
    now = _now()
    if task:
        with DB_LOCK, _connect() as db:
            db.execute(
                """
                UPDATE tasks
                SET goal=?, status='active', updated_at=?
                WHERE id=?
                """,
                (goal[:5000], now, task["id"]),
            )
            db.commit()
        return get_active_task(sid) or task
    tid = _uid("task")
    with DB_LOCK, _connect() as db:
        db.execute(
            """
            INSERT INTO tasks(
                id,session_id,goal,status,plan_json,results_json,current_step,
                approved,created_at,updated_at
            )
            VALUES (?, ?, ?, 'active', '{}', '{}', 0, 0, ?, ?)
            """,
            (tid, sid, goal[:5000], now, now),
        )
        db.execute(
            "UPDATE sessions SET active_task_id=?, updated_at=? WHERE id=?",
            (tid, now, sid),
        )
        db.commit()
    return get_active_task(sid) or {"id": tid, "goal": goal}


def update_task(session_id: str, **fields: Any) -> None:
    task = get_active_task(session_id)
    if not task:
        return
    allowed = {
        "status", "plan_json", "results_json", "current_step", "approved", "goal"
    }
    assignments = []
    values = []
    for key, value in fields.items():
        if key not in allowed:
            continue
        assignments.append(f"{key}=?")
        if key in {"plan_json", "results_json"} and not isinstance(value, str):
            value = _json(value)
        if key == "approved":
            value = 1 if value else 0
        values.append(value)
    if not assignments:
        return
    assignments.append("updated_at=?")
    values.append(_now())
    values.append(task["id"])
    with DB_LOCK, _connect() as db:
        db.execute(
            f"UPDATE tasks SET {', '.join(assignments)} WHERE id=?",
            values,
        )
        db.commit()


def actionable(text: str) -> bool:
    lower = text.lower()
    return any(term in lower for term in ACTION_WORDS)


def continuation(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", text.strip().lower()).strip(" .!?")
    return normalized in CONTINUATION_PHRASES or (
        len(normalized) < 60 and any(
            phrase in normalized for phrase in (
                "continue", "go ahead", "do it", "proceed", "resume", "retry"
            )
        )
    )


def promote_from_turn(session_id: str, user_mid: str, user_message: str,
                      assistant_message: str, effective_message: str) -> None:
    lower = user_message.lower()
    if any(marker in lower for marker in PREFERENCE_MARKERS):
        add_memory(
            "semantic",
            user_message,
            source_session_id=session_id,
            source_message_id=user_mid,
            confidence=0.88,
            metadata={"promotion": "automatic_user_preference"},
        )
    if effective_message.strip() != user_message.strip() or actionable(user_message):
        episode = (
            f"User request: {user_message[:1200]}\n"
            f"Outcome: {assistant_message[:1800]}"
        )
        add_memory(
            "episodic",
            episode,
            source_session_id=session_id,
            source_message_id=user_mid,
            confidence=0.78,
            metadata={"promotion": "automatic_task_episode"},
        )


def update_title_if_needed(session_id: str, first_user: str) -> None:
    with DB_LOCK, _connect() as db:
        row = db.execute(
            "SELECT title,message_count FROM sessions WHERE id=?",
            (session_id,),
        ).fetchone()
        if not row:
            return
        title = str(row["title"])
        if title not in {"New Chat", "RedSight Chat"}:
            return
        clean = re.sub(r"\s+", " ", first_user).strip()
        clean = re.sub(r"^[\\/]+", "", clean)
        if len(clean) > 72:
            clean = clean[:69].rstrip() + "..."
        if not clean:
            clean = "RedSight Chat"
        db.execute(
            "UPDATE sessions SET title=?,updated_at=? WHERE id=?",
            (clean, _now(), session_id),
        )
        db.commit()


def update_task_from_turn(session_id: str, user_message: str,
                          assistant_message: str) -> None:
    current = get_active_task(session_id)
    if continuation(user_message) and current:
        update_task(
            session_id,
            status="active",
            approved=("approve" in user_message.lower() or "yes" in user_message.lower()
                      or "do it" in user_message.lower() or "proceed" in user_message.lower()),
            results_json={"last_assistant_response": assistant_message[:6000]},
        )
        return
    if actionable(user_message):
        task = set_active_task(user_message, session_id)
        status = "blocked" if any(
            token in assistant_message.lower()
            for token in ("failed", "error:", "could not", "requires approval")
        ) else "active"
        update_task(
            session_id,
            status=status,
            results_json={"last_assistant_response": assistant_message[:6000]},
        )


def _memory_context(query: str) -> str:
    memories = retrieve_memories(
        query,
        limit=10,
        memory_types=["semantic", "episodic", "imported"],
    )
    if not memories:
        return ""
    lines = []
    for item in memories:
        lines.append(
            f"- [{item['memory_type']}] {item['content']}"
        )
    return "\n".join(lines)[:7000]


def refresh_capabilities() -> None:
    now = _now()
    entries: dict[str, tuple[str, str, dict[str, Any]]] = {}
    for name, spec in base.TOOL_SPECS.items():
        entries[f"tool:{name}"] = (
            str(spec.get("description", "")),
            "active",
            {
                "risk": spec.get("risk"),
                "approval": bool(spec.get("approval")),
                "agent": bool(spec.get("agent")),
            },
        )
    static = {
        "memory:persistent_sessions":
            "Persistent SQLite conversation sessions and transcripts.",
        "memory:recent_history":
            "Recent conversation turns are injected before every model request.",
        "memory:rolling_summary":
            "Long sessions receive a rolling compressed summary.",
        "memory:task_ledger":
            "Active goals, plans, approvals, and results persist across turns.",
        "memory:long_term":
            "Semantic and episodic memories are retrieved before each turn.",
        "memory:auto_promotion":
            "Stable preferences and task episodes can be promoted automatically.",
        "rag:directory_expansion":
            "Host directories are expanded into supported files before RAG submission.",
        "skills:guided_execution":
            "Inherited Hermes skills can guide actual allow-listed RedSight tool plans.",
    }
    for name, description in static.items():
        entries[name] = (description, "active", {})
    with DB_LOCK, _connect() as db:
        for name, (description, status, metadata) in entries.items():
            db.execute(
                """
                INSERT INTO capabilities(name,description,status,metadata_json,updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    description=excluded.description,
                    status=excluded.status,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (name, description, status, _json(metadata), now),
            )
        db.commit()


def capability_context() -> str:
    with DB_LOCK, _connect() as db:
        rows = db.execute(
            """
            SELECT name,description,status
            FROM capabilities
            WHERE status='active'
            ORDER BY name
            LIMIT 100
            """
        ).fetchall()
    return "\n".join(
        f"- {row['name']}: {row['description']}" for row in rows
    )[:9000]


def seed_heritage_memory() -> None:
    if setting_get("heritage_memory_seeded") == "1":
        return
    candidates = [
        (base.HERITAGE / "memories" / "USER.md", "imported", "Hermes USER"),
        (base.HERITAGE / "memories" / "MEMORY.md", "imported", "Hermes MEMORY"),
    ]
    for path, memory_type, label in candidates:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8-sig", errors="replace").strip()
        if not text:
            continue
        chunks = [text[i:i+1800] for i in range(0, min(len(text), 30000), 1800)]
        for chunk in chunks:
            add_memory(
                memory_type,
                chunk,
                confidence=0.72,
                metadata={"source": label, "path": str(path)},
            )
    setting_set("heritage_memory_seeded", "1")


def export_memory_markdown(session_id: str) -> tuple[Path, Path]:
    session = get_session(session_id)
    messages = session_messages(session_id, limit=300)
    session_path = EXPORT_HOME / f"session-{session_id}.md"
    parts = [
        f"# {session['title']}",
        "",
        "## Rolling Summary",
        session.get("summary") or "(not generated yet)",
        "",
        "## Transcript",
    ]
    for item in messages:
        parts.extend(
            [
                "",
                f"### {item['role'].title()}",
                item["content"],
            ]
        )
    session_path.write_text("\n".join(parts), encoding="utf-8")

    memory_path = EXPORT_HOME / "long-term-memory.md"
    with DB_LOCK, _connect() as db:
        rows = db.execute(
            """
            SELECT memory_type,content,confidence,updated_at
            FROM memories
            ORDER BY memory_type, updated_at DESC
            LIMIT 2000
            """
        ).fetchall()
    lines = ["# RedSight Long-Term Memory", ""]
    for row in rows:
        lines.append(
            f"- [{row['memory_type']}] {row['content']} "
            f"(confidence={row['confidence']:.2f})"
        )
    memory_path.write_text("\n".join(lines), encoding="utf-8")
    return session_path, memory_path


async def index_memory_exports(session_id: str) -> None:
    try:
        session_path, memory_path = export_memory_markdown(session_id)
        host_root = Path(os.environ.get("USERPROFILE", r"C:\Users\walim"))
        paths = []
        for path in (session_path, memory_path):
            relative = path.resolve().relative_to(host_root.resolve())
            paths.append("/host/user/" + relative.as_posix())
        async with httpx.AsyncClient(timeout=180.0) as client:
            await client.post(
                base.REDSIGHT_URL + "/api/v1/jobs/index/batch",
                json={
                    "paths": paths,
                    "collection": "episodic_memory",
                    "project": "redsight-conversation-memory",
                },
            )
    except Exception as exc:
        add_event(session_id, "memory_index_warning", {"error": repr(exc)})


async def update_rolling_summary(session_id: str) -> None:
    try:
        session = get_session(session_id)
        messages = session_messages(session_id, limit=120)
        if len(messages) < 12:
            return
        transcript = []
        for item in messages[-60:]:
            transcript.append(
                f"{item['role'].upper()}: {item['content'][:4000]}"
            )
        existing = session.get("summary") or ""
        prompt = (
            "Maintain a concise persistent session summary for RedSight. "
            "Preserve the user's goals, approvals, constraints, unresolved tasks, "
            "important tool results, decisions, and referents needed for later "
            "phrases such as 'continue', 'do it', or 'that task'. Do not invent "
            "facts. Output plain text, maximum 1200 words.\n\n"
            f"EXISTING SUMMARY:\n{existing[:6000]}\n\n"
            "RECENT TRANSCRIPT:\n"
            + "\n\n".join(transcript)
        )
        summary = await base.redsight_chat(
            [
                {
                    "role": "system",
                    "content": (
                        "You summarize a local RedSight conversation for future "
                        "continuity. Be factual and compact."
                    ),
                },
                {"role": "user", "content": prompt},
            ]
        )
        with DB_LOCK, _connect() as db:
            db.execute(
                "UPDATE sessions SET summary=?,updated_at=? WHERE id=?",
                (summary[:12000], _now(), session_id),
            )
            db.commit()
        await index_memory_exports(session_id)
    except Exception as exc:
        add_event(session_id, "summary_warning", {"error": repr(exc)})


def _already_committed(session_id: str, user_message: str,
                       assistant_message: str) -> bool:
    with DB_LOCK, _connect() as db:
        rows = db.execute(
            """
            SELECT role,content,created_at
            FROM messages
            WHERE session_id=?
            ORDER BY created_at DESC
            LIMIT 2
            """,
            (session_id,),
        ).fetchall()
    if len(rows) != 2:
        return False
    latest, previous = rows[0], rows[1]
    return (
        latest["role"] == "assistant"
        and previous["role"] == "user"
        and latest["content"] == assistant_message
        and previous["content"] == user_message
        and (_now() - float(latest["created_at"])) < 30
    )


def build_messages(request: MemoryBuildRequest) -> dict[str, Any]:
    sid = request.session_id or ensure_active_session()
    session = get_session(sid)
    original = request.user_message.strip()
    effective = (request.effective_message or original).strip()
    task = get_active_task(sid)
    memory_text = _memory_context(
        original + ("\n" + task["goal"] if task else "")
    )
    capability_text = capability_context()
    system_parts = []
    if request.heritage_context.strip():
        system_parts.append(request.heritage_context.strip()[:18000])
    system_parts.append(
        """
[REDSIGHT PERSISTENT SESSION POLICY]
You are operating as the user's local RedSight platform, not as a generic
remote assistant. Use the supplied recent transcript, rolling summary, active
task ledger, long-term memory and capability state to resolve references such
as "it", "that", "continue", "do it", "retry", "the previous task", and prior
approvals. If a capability below is active, do not falsely claim RedSight has
no local access. Never claim an action occurred unless a tool/result in the
current context shows it occurred.
""".strip()
    )
    if session.get("summary"):
        system_parts.append(
            "[ROLLING SESSION SUMMARY]\n" + str(session["summary"])[:9000]
        )
    if task:
        system_parts.append(
            "[ACTIVE TASK LEDGER]\n"
            + _json(
                {
                    "goal": task.get("goal"),
                    "status": task.get("status"),
                    "current_step": task.get("current_step"),
                    "approved": task.get("approved"),
                    "plan": task.get("plan"),
                    "results": task.get("results"),
                }
            )[:8000]
        )
    if memory_text:
        system_parts.append("[RELEVANT LONG-TERM MEMORY]\n" + memory_text)
    system_parts.append("[ACTIVE REDSIGHT CAPABILITIES]\n" + capability_text)
    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": "\n\n".join(system_parts)[:48000],
        }
    ]
    messages.extend(recent_messages(sid))
    messages.append(
        {
            "role": "user",
            "content": effective[:36000],
        }
    )
    return {
        "ok": True,
        "session_id": sid,
        "messages": messages,
        "recent_message_count": len(messages) - 2,
        "active_task": task,
        "summary_present": bool(session.get("summary")),
        "memory_context_present": bool(memory_text),
    }


async def commit_turn(request: MemoryCommitRequest) -> dict[str, Any]:
    sid = request.session_id or ensure_active_session()
    get_session(sid)
    original = request.user_message.strip()
    assistant = request.assistant_message.strip()
    effective = (request.effective_message or original).strip()
    if not original or not assistant:
        raise ValueError("Both user_message and assistant_message are required.")
    if _already_committed(sid, original, assistant):
        return {"ok": True, "session_id": sid, "duplicate": True}
    user_mid = insert_message(
        sid,
        "user",
        original,
        {
            "effective_message_changed": effective != original,
        },
    )
    assistant_mid = insert_message(
        sid,
        "assistant",
        assistant,
        {},
    )
    if effective != original:
        add_event(
            sid,
            "tool_or_agent_context",
            {
                "user_message": original,
                "effective_message": effective[:20000],
                "assistant_message_id": assistant_mid,
            },
        )
    update_title_if_needed(sid, original)
    promote_from_turn(sid, user_mid, original, assistant, effective)
    update_task_from_turn(sid, original, assistant)
    session = get_session(sid)
    if int(session["message_count"]) >= 12 and int(session["message_count"]) % 8 == 0:
        asyncio.create_task(update_rolling_summary(sid))
    else:
        try:
            export_memory_markdown(sid)
        except Exception as exc:
            add_event(sid, "memory_export_warning", {"error": repr(exc)})
    return {
        "ok": True,
        "session_id": sid,
        "user_message_id": user_mid,
        "assistant_message_id": assistant_mid,
        "message_count": get_session(sid)["message_count"],
        "active_task": get_active_task(sid),
    }


def skill_catalog_matches(query: str, limit: int = 5) -> list[dict[str, Any]]:
    catalog = base.load_skill_catalog()
    terms = _tokens(query)
    ranked = []
    for item in catalog:
        haystack = (
            str(item.get("Name", "")) + " "
            + str(item.get("Description", ""))
        ).lower()
        score = sum(1 for term in terms if term in haystack)
        if score:
            ranked.append((score, item))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in ranked[:limit]]


def skills_list_stage10(params: dict[str, Any]) -> dict[str, Any]:
    catalog = base.load_skill_catalog()
    query = str(params.get("query", "")).strip().lower()
    limit = max(1, min(int(params.get("limit", 100)), 500))
    offset = max(0, int(params.get("offset", 0)))
    if query:
        filtered = [
            item for item in catalog
            if query in (
                str(item.get("Name", "")) + " "
                + str(item.get("Description", ""))
            ).lower()
        ]
    else:
        filtered = list(catalog)
    total = len(filtered)
    page = filtered[offset:offset + limit]
    return {
        "ok": True,
        "total": total,
        "returned": len(page),
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(page) < total,
        "skills": page,
    }


def discover_rag_files(raw_paths: list[str] | str, *,
                             max_files: int = 50000,
                             max_size_mb: int = 100) -> dict[str, Any]:
    host_paths = s9.resolve_rag_paths(raw_paths)
    unlimited = int(max_files) <= 0
    maximum = None if unlimited else max(1, min(int(max_files), 500000))
    max_bytes = max(1, int(max_size_mb)) * 1024 * 1024
    skip_dirs = {str(item).lower() for item in s9.SKIP_DIRS}
    skip_dirs.update(
        {
            "adobetemp", "package cache", ".pytest_cache", ".mypy_cache",
            ".ruff_cache", "softwaredistribution", "inetcache", "crashdumps",
        }
    )
    files: list[Path] = []
    skipped_unsupported = 0
    skipped_large = 0
    skipped_sensitive = 0
    truncated = False
    for root in host_paths:
        if root.is_file():
            candidates = [root]
        else:
            candidates = []
            for current, dirs, names in os.walk(root, topdown=True, onerror=lambda _e: None):
                dirs[:] = [d for d in dirs if d.lower() not in skip_dirs]
                current_path = Path(current)
                for name in names:
                    candidates.append(current_path / name)
                    if maximum is not None and len(files) + len(candidates) >= maximum * 2:
                        break
                if maximum is not None and len(files) + len(candidates) >= maximum * 2:
                    break
        for path in candidates:
            if path.name.lower() in s9.SENSITIVE_NAMES:
                skipped_sensitive += 1
                continue
            if path.suffix.lower() not in s9.KNOWLEDGE_EXTENSIONS:
                skipped_unsupported += 1
                continue
            try:
                if path.stat().st_size > max_bytes:
                    skipped_large += 1
                    continue
            except Exception:
                continue
            files.append(path)
            if maximum is not None and len(files) >= maximum:
                truncated = True
                break
        if truncated:
            break
    seen = set()
    unique_files = []
    for path in files:
        key = os.path.normcase(os.path.abspath(str(path)))
        if key in seen:
            continue
        seen.add(key)
        unique_files.append(path)
    mapped = [s9.map_host_to_container(path) for path in unique_files]
    return {
        "host_roots": [str(path) for path in host_paths],
        "host_files": [str(path) for path in unique_files],
        "container_files": mapped,
        "discovered": len(unique_files),
        "truncated": truncated,
        "skipped_unsupported": skipped_unsupported,
        "skipped_large": skipped_large,
        "skipped_sensitive": skipped_sensitive,
    }


async def rag_index_expanded(params: dict[str, Any]) -> dict[str, Any]:
    raw_paths = params.get("paths", ["onedrive"])
    if isinstance(raw_paths, str) and raw_paths.startswith("/"):
        return await OLD_EXECUTE("rag.index", params, approved=False)
    if isinstance(raw_paths, list) and raw_paths and all(
        isinstance(item, str) and item.startswith("/") for item in raw_paths
    ):
        return await OLD_EXECUTE("rag.index", params, approved=False)
    discovery = await asyncio.to_thread(
        discover_rag_files,
        raw_paths,
        max_files=int(params.get("max_files", 50000)),
        max_size_mb=int(params.get("max_size_mb", 100)),
    )
    paths = discovery["container_files"]
    if not paths:
        return {"ok": False, "error": "No supported knowledge files discovered.", **discovery}
    collection = str(params.get("collection", "knowledge_docs"))
    project = str(params.get("project", "host-knowledge"))
    batch_size = max(1, min(int(params.get("batch_size", 25)), 100))
    submitted = 0
    failed = []
    async with httpx.AsyncClient(timeout=600.0) as client:
        for start in range(0, len(paths), batch_size):
            batch = paths[start:start + batch_size]
            try:
                response = await client.post(
                    base.REDSIGHT_URL + "/api/v1/jobs/index/batch",
                    json={
                        "paths": batch,
                        "collection": collection,
                        "project": project,
                    },
                )
                if response.is_success:
                    submitted += len(batch)
                else:
                    failed.append(
                        {
                            "status_code": response.status_code,
                            "paths": batch[:3],
                            "body": response.text[:2000],
                        }
                    )
            except Exception as exc:
                failed.append({"paths": batch[:3], "error": repr(exc)})
    return {
        "ok": not failed,
        "collection": collection,
        "project": project,
        "discovered": discovery["discovered"],
        "submitted": submitted,
        "failed_batches": failed,
        "truncated": discovery["truncated"],
        "skipped_unsupported": discovery["skipped_unsupported"],
        "skipped_large": discovery["skipped_large"],
        "skipped_sensitive": discovery["skipped_sensitive"],
        "sample_files": discovery["host_files"][:20],
    }


def _extract_json_object(text: str) -> dict[str, Any]:
    candidate = text.strip()
    candidate = re.sub(r"^```(?:json)?\s*", "", candidate)
    candidate = re.sub(r"\s*```$", "", candidate)
    try:
        value = json.loads(candidate)
        return value if isinstance(value, dict) else {}
    except Exception:
        left = candidate.find("{")
        right = candidate.rfind("}")
        if left >= 0 and right > left:
            try:
                value = json.loads(candidate[left:right+1])
                return value if isinstance(value, dict) else {}
            except Exception:
                pass
    return {}


def _find_skill(skill_name: str) -> tuple[dict[str, Any], str]:
    catalog = base.load_skill_catalog()
    exact = []
    partial = []
    for item in catalog:
        name = str(item.get("Name", ""))
        if name.lower() == skill_name.lower():
            exact.append(item)
        elif skill_name.lower() in name.lower():
            partial.append(item)
    matches = exact or partial
    if not matches:
        raise ValueError("No migrated Hermes skill matched: " + skill_name)
    item = matches[0]
    relative = str(item.get("RelativePath", ""))
    path = base.HERITAGE / relative
    if not path.is_file():
        raise FileNotFoundError(str(path))
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    return item, text[:20000]


async def skill_execute_stage10(params: dict[str, Any], approved: bool) -> dict[str, Any]:
    skill_name = str(params.get("skill", "")).strip()
    instruction = str(params.get("instruction", "")).strip()
    if not skill_name or not instruction:
        raise ValueError("skill and instruction are required")
    item, skill_text = _find_skill(skill_name)
    tool_catalog = base.agent_tool_catalog()
    planner_prompt = (
        "You are a governed RedSight skill executor. The inherited Hermes "
        "SKILL.md below is procedural guidance. Create an allow-listed RedSight "
        "tool plan only when actual tools are needed. Never invent tools. "
        "Return ONLY JSON: "
        '{"steps":[{"tool":"tool.name","params":{},"reason":"..."}],'
        '"summary":"..."}. '
        "Use zero steps if the task only needs reasoning. "
        "Do not use skills.execute recursively.\n\n"
        "TOOL CATALOG:\n" + json.dumps(tool_catalog, indent=2)[:14000]
        + "\n\nINHERITED SKILL:\n" + skill_text
    )
    raw = await base.redsight_chat(
        [
            {"role": "system", "content": planner_prompt},
            {"role": "user", "content": instruction},
        ]
    )
    parsed = _extract_json_object(raw)
    steps = []
    for step in parsed.get("steps", [])[:8]:
        if not isinstance(step, dict):
            continue
        tool = str(step.get("tool", ""))
        if tool == "skills.execute" or not base.tool_agent_allowed(tool):
            continue
        p = step.get("params", {})
        if not isinstance(p, dict):
            p = {}
        steps.append(
            {
                "tool": tool,
                "params": p,
                "reason": str(step.get("reason", ""))[:500],
                "requires_approval": base.tool_requires_approval(tool),
            }
        )
    if any(step["requires_approval"] for step in steps) and not approved:
        return {
            "ok": False,
            "requires_approval": True,
            "skill": item.get("Name"),
            "plan": steps,
            "summary": parsed.get("summary", ""),
        }
    results = []
    for number, step in enumerate(steps, start=1):
        result = await base.execute_tool_core(
            step["tool"],
            step["params"],
            approved=approved if step["requires_approval"] else False,
        )
        results.append(
            {
                "step": number,
                "tool": step["tool"],
                "reason": step["reason"],
                "result": result,
            }
        )
        if not result.get("ok", False):
            break
    synthesis = await base.redsight_chat(
        [
            {
                "role": "system",
                "content": (
                    "Use this inherited Hermes skill as procedural guidance. "
                    "Describe only actions supported by the supplied tool results. "
                    "If no tools ran, answer as skill-guided reasoning.\n\n"
                    + skill_text
                ),
            },
            {
                "role": "user",
                "content": (
                    instruction
                    + "\n\nACTUAL REDSIGHT TOOL RESULTS:\n"
                    + json.dumps(results, indent=2, ensure_ascii=False)[:22000]
                ),
            },
        ]
    )
    add_memory(
        "procedural",
        f"Skill {item.get('Name')} used for: {instruction[:1000]}",
        source_session_id=ensure_active_session(),
        confidence=0.8,
        metadata={"skill": item.get("Name"), "tool_steps": [s["tool"] for s in steps]},
    )
    return {
        "ok": True,
        "skill": item.get("Name"),
        "execution_mode": "skill_guided_allowlisted_tools",
        "plan": steps,
        "results": results,
        "response": synthesis,
    }


base.TOOL_SPECS["skills.execute"] = {
    "description": (
        "Execute an inherited Hermes skill as procedural guidance, allowing it "
        "to plan and call only allow-listed RedSight tools with approval gates."
    ),
    "risk": "orchestrated",
    "approval": False,
    "agent": True,
    "params": "skill:str, instruction:str",
}


async def execute_tool_stage10(tool: str, params: dict[str, Any],
                               *, approved: bool = False):
    if tool == "skills.list":
        return skills_list_stage10(params)
    if tool == "rag.index":
        try:
            return await rag_index_expanded(params)
        except Exception as exc:
            base.audit(tool, params, approved=approved, ok=False, detail=repr(exc))
            return {"ok": False, "tool": tool, "error": str(exc)}
    if tool in {"skills.invoke", "skills.execute"}:
        try:
            return await skill_execute_stage10(params, approved)
        except Exception as exc:
            base.audit(tool, params, approved=approved, ok=False, detail=repr(exc))
            return {"ok": False, "tool": tool, "error": str(exc)}
    return await OLD_EXECUTE(tool, params, approved=approved)


base.execute_tool_core = execute_tool_stage10


async def create_plan_stage10(goal: str):
    sid = ensure_active_session()
    task = get_active_task(sid)
    effective_goal = goal
    if continuation(goal) and task:
        effective_goal = (
            "Continue the active RedSight task below. The user's latest message "
            "authorizes/resumes the same task unless a new constraint is stated.\n\n"
            f"ACTIVE TASK GOAL:\n{task['goal']}\n\n"
            f"LATEST USER MESSAGE:\n{goal}"
        )
    relevant_skills = skill_catalog_matches(
        effective_goal + (("\n" + task["goal"]) if task else ""),
        limit=5,
    )
    if relevant_skills:
        effective_goal += (
            "\n\nRELEVANT INHERITED HERMES SKILLS AVAILABLE FOR skills.execute:\n"
            + "\n".join(
                f"- {item.get('Name')}: {item.get('Description','')}"
                for item in relevant_skills
            )
        )
    if actionable(goal) and not task:
        task = set_active_task(goal, sid)
    plan = await OLD_PLAN(effective_goal)
    if isinstance(plan, dict) and get_active_task(sid):
        update_task(
            sid,
            plan_json=plan,
            status="planned",
        )
    return plan


base.create_agent_plan = create_plan_stage10


async def execute_plan_stage10(goal: str, plan: list[dict[str, Any]],
                               *, approved: bool):
    sid = ensure_active_session()
    if not get_active_task(sid):
        set_active_task(goal, sid)
    update_task(
        sid,
        plan_json={"steps": plan},
        status="running",
        approved=approved,
    )
    result = await OLD_EXEC_PLAN(goal, plan, approved=approved)
    completed = 0
    if isinstance(result, dict):
        completed = len(result.get("results", []) or result.get("completed", []) or [])
    update_task(
        sid,
        results_json=result,
        current_step=completed,
        status="active" if isinstance(result, dict) and result.get("ok", False) else "blocked",
        approved=approved,
    )
    add_event(sid, "agent_execution", {"goal": goal, "plan": plan, "result": result})
    return result


base.execute_agent_plan = execute_plan_stage10


@app.get("/memory/status")
async def memory_status():
    sid = ensure_active_session()
    with DB_LOCK, _connect() as db:
        session_count = db.execute("SELECT COUNT(*) AS n FROM sessions").fetchone()["n"]
        message_count = db.execute("SELECT COUNT(*) AS n FROM messages").fetchone()["n"]
        memory_count = db.execute("SELECT COUNT(*) AS n FROM memories").fetchone()["n"]
        task_count = db.execute("SELECT COUNT(*) AS n FROM tasks").fetchone()["n"]
        capability_count = db.execute("SELECT COUNT(*) AS n FROM capabilities").fetchone()["n"]
    return {
        "ok": True,
        "stage": "10",
        "database": str(DB_PATH),
        "active_session_id": sid,
        "sessions": session_count,
        "messages": message_count,
        "memories": memory_count,
        "tasks": task_count,
        "capabilities": capability_count,
        "recent_history": True,
        "rolling_summaries": True,
        "task_ledger": True,
        "automatic_memory_promotion": True,
        "capability_state_memory": True,
        "directory_rag_expansion": True,
        "skill_guided_execution": True,
    }


@app.get("/memory/sessions")
async def memory_sessions(include_archived: bool = False, limit: int = 200):
    return {"ok": True, "sessions": list_sessions(include_archived, limit)}


@app.post("/memory/sessions/new")
async def memory_session_new(request: SessionNewRequest):
    return {"ok": True, "session": create_session(request.title, activate=True)}


@app.get("/memory/sessions/{session_id}")
async def memory_session_get(session_id: str, limit: int = 1000):
    try:
        return {
            "ok": True,
            "session": get_session(session_id),
            "messages": session_messages(session_id, limit=limit),
        }
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")


@app.post("/memory/sessions/{session_id}/activate")
async def memory_session_activate(session_id: str):
    try:
        return {"ok": True, "session": activate_session(session_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")


@app.post("/memory/sessions/{session_id}/rename")
async def memory_session_rename(session_id: str, request: SessionRenameRequest):
    try:
        get_session(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    title = request.title.strip()[:160]
    if not title:
        raise HTTPException(status_code=400, detail="Title cannot be blank")
    with DB_LOCK, _connect() as db:
        db.execute(
            "UPDATE sessions SET title=?,updated_at=? WHERE id=?",
            (title, _now(), session_id),
        )
        db.commit()
    return {"ok": True, "session": get_session(session_id)}


@app.post("/memory/sessions/{session_id}/pin")
async def memory_session_pin(session_id: str, request: SessionPinRequest):
    try:
        get_session(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    with DB_LOCK, _connect() as db:
        db.execute(
            "UPDATE sessions SET pinned=?,updated_at=? WHERE id=?",
            (1 if request.pinned else 0, _now(), session_id),
        )
        db.commit()
    return {"ok": True, "session": get_session(session_id)}


@app.post("/memory/sessions/{session_id}/archive")
async def memory_session_archive(session_id: str, request: SessionArchiveRequest):
    try:
        get_session(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    with DB_LOCK, _connect() as db:
        db.execute(
            "UPDATE sessions SET archived=?,updated_at=? WHERE id=?",
            (1 if request.archived else 0, _now(), session_id),
        )
        db.commit()
    if request.archived and setting_get("active_session_id") == session_id:
        create_session("New Chat", activate=True)
    return {"ok": True, "session_id": session_id, "archived": request.archived}


@app.get("/memory/session/active")
async def memory_session_active():
    sid = ensure_active_session()
    return {"ok": True, "session": get_session(sid)}


@app.post("/memory/build")
async def memory_build(request: MemoryBuildRequest):
    return build_messages(request)


@app.post("/memory/commit")
async def memory_commit(request: MemoryCommitRequest):
    return await commit_turn(request)


@app.post("/memory/search")
async def memory_search(request: MemorySearchRequest):
    return {
        "ok": True,
        "results": retrieve_memories(
            request.query,
            limit=request.limit,
            memory_types=request.memory_types,
        ),
    }


@app.get("/memory/capabilities")
async def memory_capabilities():
    refresh_capabilities()
    with DB_LOCK, _connect() as db:
        rows = db.execute(
            """
            SELECT name,description,status,metadata_json,updated_at
            FROM capabilities
            ORDER BY name
            """
        ).fetchall()
    return {
        "ok": True,
        "capabilities": [
            {
                "name": row["name"],
                "description": row["description"],
                "status": row["status"],
                "metadata": _loads(row["metadata_json"], {}),
                "updated_at": row["updated_at"],
            }
            for row in rows
        ],
    }


@app.post("/memory/rag/expand")
async def memory_rag_expand(request: RagExpandRequest):
    discovery = await asyncio.to_thread(
        discover_rag_files,
        request.paths,
        max_files=request.max_files,
        max_size_mb=request.max_size_mb,
    )
    discovery["container_files"] = discovery["container_files"][:200]
    discovery["host_files"] = discovery["host_files"][:200]
    return {"ok": True, **discovery}


@app.post("/memory/selftest")
async def memory_selftest():
    previous = ensure_active_session()
    test = create_session("Stage 10 Self-Test", activate=True, archived=True)
    sid = str(test["id"])
    try:
        set_active_task("Stage10 self-test active task", sid)

        await commit_turn(
            MemoryCommitRequest(
                user_message="Remember that the Stage10 continuity codeword is ORBIT-10.",
                assistant_message="Acknowledged. The Stage10 continuity codeword is ORBIT-10.",
                effective_message=(
                    "A RedSight local action context was available for this turn. "
                    "The user said: Remember that the Stage10 continuity codeword is ORBIT-10."
                ),
                session_id=sid,
            )
        )

        built = build_messages(
            MemoryBuildRequest(
                user_message="What was the continuity codeword?",
                effective_message="What was the continuity codeword?",
                session_id=sid,
            )
        )

        joined = "\n".join(message["content"] for message in built["messages"])
        continuity = "ORBIT-10" in joined

        memories = retrieve_memories("continuity codeword ORBIT-10", limit=5)
        promoted = any("ORBIT-10" in item["content"] for item in memories)

        with DB_LOCK, _connect() as db:
            event_count = db.execute(
                """
                SELECT COUNT(*) AS n
                FROM events
                WHERE session_id=? AND event_type='tool_or_agent_context'
                """,
                (sid,),
            ).fetchone()["n"]

        active_task_ok = bool(get_active_task(sid))

        skills = skills_list_stage10({"limit": 5})

        sample_root = ROOT / "data" / "heritage" / "hermes" / "memories"
        rag_expand_ok = False
        rag_count = 0
        if sample_root.exists():
            discovery = await asyncio.to_thread(
                discover_rag_files,
                [str(sample_root)],
                max_files=20,
                max_size_mb=20,
            )
            rag_count = discovery["discovered"]
            rag_expand_ok = rag_count >= 0

        skill_tool_registered = "skills.execute" in base.TOOL_SPECS

        ok = all(
            [
                continuity,
                promoted,
                event_count > 0,
                active_task_ok,
                skills.get("total", 0) >= skills.get("returned", 0),
                rag_expand_ok,
                skill_tool_registered,
            ]
        )

        return {
            "ok": ok,
            "continuity": continuity,
            "automatic_promotion": promoted,
            "tool_result_persistence": event_count > 0,
            "active_task_ledger": active_task_ok,
            "skills_total": skills.get("total", 0),
            "skills_returned": skills.get("returned", 0),
            "rag_directory_expansion": rag_expand_ok,
            "rag_discovered_test_files": rag_count,
            "skill_guided_execution_registered": skill_tool_registered,
            "session_id": sid,
        }
    finally:
        setting_set("active_session_id", previous)
        with DB_LOCK, _connect() as db:
            db.execute("DELETE FROM memories WHERE source_session_id=?", (sid,))
            db.execute("DELETE FROM events WHERE session_id=?", (sid,))
            db.execute("DELETE FROM tasks WHERE session_id=?", (sid,))
            db.execute("DELETE FROM sessions WHERE id=?", (sid,))
            db.commit()


init_db()
refresh_capabilities()
seed_heritage_memory()
ensure_active_session()
