"""
RedSight - High-Performance Local AI Intelligence Platform
Episodic Memory

Completed task decisions, outcomes, and user-approved results.
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class EpisodicMemory:
    """
    Episodic memory store.
    
    Stores what happened in completed tasks: decisions, outcomes,
    and user-approved results.
    """
    
    def __init__(self):
        self._store: List[Dict[str, Any]] = []
    
    async def store(self, task_id: str, decision: str, outcome: str,
                   user_approved: bool = False, metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        Store an episodic memory entry.
        
        Returns memory_id.
        """
        memory_id = f"ep_{task_id}_{int(time.time())}"
        entry = {
            "memory_id": memory_id,
            "task_id": task_id,
            "decision": decision,
            "outcome": outcome,
            "user_approved": user_approved,
            "metadata": metadata or {},
            "timestamp": time.time(),
        }
        self._store.append(entry)
        logger.debug(f"Episodic memory stored: {memory_id}")
        return memory_id
    
    async def query(self, query: str, task_id: Optional[str] = None,
                   limit: int = 10) -> List[Dict[str, Any]]:
        """
        Query episodic memory.
        
        Simple keyword-based search (replace with vector search in Phase 2).
        """
        query_lower = query.lower()
        results = []
        
        for entry in self._store:
            if task_id and entry.get("task_id") != task_id:
                continue
            
            # Simple keyword matching
            text = f"{entry.get('decision', '')} {entry.get('outcome', '')}"
            if any(term in text.lower() for term in query_lower.split()):
                results.append(entry)
        
        return results[:limit]
    
    async def get_by_task(self, task_id: str) -> List[Dict[str, Any]]:
        """Get all episodic memories for a task."""
        return [e for e in self._store if e.get("task_id") == task_id]
    
    async def get_by_id(self, memory_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific memory by ID."""
        for entry in self._store:
            if entry.get("memory_id") == memory_id:
                return entry
        return None
    
    async def clear(self) -> None:
        """Clear all episodic memories."""
        self._store.clear()
    
    async def count(self) -> int:
        """Get total count of episodic memories."""
        return len(self._store)
