"""
RedSight - High-Performance Local AI Intelligence Platform
Audit Logger

Immutable-ish run records with who/what/when, tool inputs,
outputs, permissions, and result status.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from app.core.interfaces import AuditAction, AuditEvent

logger = logging.getLogger(__name__)


class AuditLogger:
    """
    Audit Logger - Maintains immutable-ish run records.

    Records:
    - Who/what/when
    - Tool inputs and outputs
    - Permissions used
    - Result status
    """

    def __init__(self, log_path: Optional[str] = None):
        self.log_path = log_path
        self._events: List[AuditEvent] = []

        if log_path:
            try:
                with open(log_path, "r") as f:
                    self._events = [
                        AuditEvent(**json.loads(line))
                        for line in f
                        if line.strip()
                    ]
                logger.info(f"Audit log loaded: {len(self._events)} events")
            except FileNotFoundError:
                logger.info("Audit log file not found, starting fresh")
            except Exception as e:
                logger.warning(f"Failed to load audit log: {e}")

    async def record(self, event: AuditEvent) -> None:
        """Record an audit event."""
        self._events.append(event)

        if self.log_path:
            try:
                with open(self.log_path, "a") as f:
                    f.write(json.dumps(event.to_dict()) + "\n")
            except Exception as e:
                logger.error(f"Failed to write audit log: {e}")

        logger.debug(f"Audit event recorded: {event.action.value}")

    async def query(self, actor: Optional[str] = None,
                   action: Optional[AuditAction] = None,
                   start_time: Optional[float] = None,
                   end_time: Optional[float] = None,
                   limit: int = 100) -> List[AuditEvent]:
        """Query audit events with filters."""
        results = self._events

        if actor:
            results = [e for e in results if e.actor == actor]
        if action:
            results = [e for e in results if e.action == action]
        if start_time:
            results = [e for e in results if e.timestamp >= start_time]
        if end_time:
            results = [e for e in results if e.timestamp <= end_time]

        results.sort(key=lambda e: e.timestamp, reverse=True)
        return results[:limit]

    async def export(self, format: str = "json",
                    start_time: Optional[float] = None,
                    end_time: Optional[float] = None) -> str:
        """Export audit trail in specified format."""
        events = await self.query(
            start_time=start_time,
            end_time=end_time,
            limit=10000,
        )

        if format == "json":
            return json.dumps([e.to_dict() for e in events], indent=2)
        elif format == "csv":
            lines = ["event_id,action,timestamp,actor,result,error"]
            for e in events:
                lines.append(
                    f'{e.event_id},{e.action.value},{e.timestamp},'
                    f'{e.actor},{e.result},{e.error or ""}'
                )
            return "\n".join(lines)
        elif format == "text":
            lines = []
            for e in events:
                lines.append(
                    f"[{e.timestamp}] {e.actor} | {e.action.value} | "
                    f"{e.result} | {e.details}"
                )
            return "\n".join(lines)
        else:
            raise ValueError(f"Unsupported export format: {format}")

    async def get_recent_violations(self, limit: int = 20) -> List[AuditEvent]:
        """Get recent security violations."""
        return await self.query(
            action=AuditAction.SECURITY_VIOLATION,
            limit=limit,
        )

    async def get_event_count(self) -> int:
        """Get total number of audit events."""
        return len(self._events)

    async def clear(self) -> None:
        """Clear all audit events (not recommended in production)."""
        self._events.clear()
        if self.log_path:
            with open(self.log_path, "w") as f:
                pass
        logger.warning("Audit log cleared")

    async def get_tool_stats(self) -> Dict[str, Any]:
        """Get statistics about tool calls."""
        events = await self.query(
            action=AuditAction.TOOL_CALL,
            limit=10000,
        )

        stats = {
            "total_calls": len(events),
            "successful": 0,
            "failed": 0,
            "timeouts": 0,
            "by_tool": {},
        }

        for e in events:
            tool = e.details.get("tool", "unknown")
            stats["by_tool"][tool] = stats["by_tool"].get(tool, 0) + 1

            if e.result == "success":
                stats["successful"] += 1
            elif e.result == "timeout":
                stats["timeouts"] += 1
            else:
                stats["failed"] += 1

        return stats

    async def get_skill_stats(self) -> Dict[str, Any]:
        """Get statistics about skill executions."""
        events = await self.query(
            action=AuditAction.SKILL_EXECUTION,
            limit=10000,
        )

        stats = {
            "total_executions": len(events),
            "successful": 0,
            "failed": 0,
            "by_skill": {},
        }

        for e in events:
            skill = e.details.get("skill_id", "unknown")
            stats["by_skill"][skill] = stats["by_skill"].get(skill, 0) + 1

            if e.result == "success":
                stats["successful"] += 1
            else:
                stats["failed"] += 1

        return stats
