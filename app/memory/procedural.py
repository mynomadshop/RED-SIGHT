"""
RedSight - High-Performance Local AI Intelligence Platform
Procedural Memory

Skills, workflows, tool recipes, and reusable procedures with
versions and tests.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ProceduralMemory:
    """
    Procedural memory store.
    
    Stores skills, workflows, tool recipes, and reusable procedures
    with versions and tests.
    """
    
    def __init__(self):
        self._store: List[Dict[str, Any]] = []
    
    async def store(self, skill_id: str, version: str, workflow: Dict[str, Any],
                   metadata: Optional[Dict[str, Any]] = None,
                   trust_level: int = 2) -> str:
        """
        Store a procedural memory entry.
        
        Args:
            skill_id: Skill identifier
            version: Semantic version
            workflow: Workflow definition
            metadata: Additional metadata
            trust_level: Trust level (0-4)
        
        Returns memory_id.
        """
        memory_id = f"pm_{skill_id}_{version.replace('.', '_')}"
        
        entry = {
            "memory_id": memory_id,
            "skill_id": skill_id,
            "version": version,
            "workflow": workflow,
            "metadata": metadata or {},
            "trust_level": trust_level,
            "timestamp": time.time(),
        }
        
        # Check for existing version
        for existing in self._store:
            if existing.get("skill_id") == skill_id and existing.get("version") == version:
                logger.debug(f"Procedural memory version exists: {memory_id}")
                return memory_id
        
        self._store.append(entry)
        logger.debug(f"Procedural memory stored: {memory_id}")
        return memory_id
    
    async def get_by_skill(self, skill_id: str) -> List[Dict[str, Any]]:
        """Get all versions of a skill."""
        return [e for e in self._store if e.get("skill_id") == skill_id]
    
    async def get_latest_version(self, skill_id: str) -> Optional[Dict[str, Any]]:
        """Get the latest version of a skill."""
        versions = await self.get_by_skill(skill_id)
        if not versions:
            return None
        # Sort by timestamp descending
        versions.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        return versions[0]
    
    async def query(self, query: str, trust_min: int = 1,
                   limit: int = 10) -> List[Dict[str, Any]]:
        """
        Query procedural memory.
        
        Simple keyword-based search (replace with vector search in Phase 2).
        """
        query_lower = query.lower()
        results = []
        
        for entry in self._store:
            if entry.get("trust_level", 0) < trust_min:
                continue
            
            # Search in workflow and metadata
            text = f"{entry.get('skill_id', '')} {str(entry.get('workflow', ''))}"
            if any(term in text.lower() for term in query_lower.split()):
                results.append(entry)
        
        return results[:limit]
    
    async def get_by_id(self, memory_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific memory by ID."""
        for entry in self._store:
            if entry.get("memory_id") == memory_id:
                return entry
        return None
    
    async def count(self) -> int:
        """Get total count of procedural memories."""
        return len(self._store)
    
    async def clear(self) -> None:
        """Clear all procedural memories."""
        self._store.clear()
