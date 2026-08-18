"""
RedSight - High-Performance Local AI Intelligence Platform
Working Memory

Short-lived memory for current task state and scratch context.
Not automatically persisted.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional


class WorkingMemory:
    """
    Working memory store.
    
    Short-lived, TTL-based memory for current task state.
    Not automatically persisted to disk.
    """
    
    def __init__(self):
        self._store: Dict[str, tuple[Any, float]] = {}  # key -> (value, expiry)
    
    def _now(self) -> float:
        return time.time()
    
    def _check_ttl(self, key: str) -> bool:
        """Check if entry has expired. Returns True if expired."""
        if key not in self._store:
            return False
        value, expiry = self._store[key]
        if expiry and self._now() > expiry:
            del self._store[key]
            return True
        return False
    
    async def store(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        """Store a value with optional TTL."""
        expiry = self._now() + ttl_seconds if ttl_seconds else None
        self._store[key] = (value, expiry)
    
    async def get(self, key: str) -> Optional[Any]:
        """Retrieve a value, removing if expired."""
        if self._check_ttl(key):
            return None
        value, _ = self._store.get(key, (None, None))
        return value
    
    async def delete(self, key: str) -> bool:
        """Delete a key."""
        if key in self._store:
            del self._store[key]
            return True
        return False
    
    async def clear(self) -> None:
        """Clear all entries."""
        self._store.clear()
    
    async def keys(self) -> list[str]:
        """Get all non-expired keys."""
        expired = []
        for key in list(self._store.keys()):
            if self._check_ttl(key):
                expired.append(key)
            else:
                expired.remove(key)
        for key in expired:
            self._store.pop(key, None)
        return list(self._store.keys())
    
    async def size(self) -> int:
        """Get current number of entries."""
        return len(self._store)
