"""
RedSight - High-Performance Local AI Intelligence Platform
Semantic Memory

Stable facts, project knowledge, documents, and distilled concepts
with source provenance.
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class SemanticMemory:
    """
    Semantic memory store.
    
    Stores stable facts, project knowledge, documents, and distilled
    concepts with source provenance.
    """
    
    def __init__(self):
        self._store: List[Dict[str, Any]] = []
    
    async def store(self, fact: str, source_provenance: str,
                   project: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None,
                   trust_level: int = 1) -> str:
        """
        Store a semantic memory entry.
        
        Args:
            fact: The fact or knowledge to store
            source_provenance: Source path/URI for the fact
            project: Optional project identifier
            metadata: Additional metadata
            trust_level: Trust level (0-4)
        
        Returns memory_id.
        """
        # Generate stable ID from fact content
        fact_hash = hashlib.md5(fact.encode()).hexdigest()[:12]
        memory_id = f"sm_{fact_hash}"
        
        entry = {
            "memory_id": memory_id,
            "fact": fact,
            "source_provenance": source_provenance,
            "project": project,
            "metadata": metadata or {},
            "trust_level": trust_level,
            "timestamp": time.time(),
        }
        
        # Check for duplicates
        for existing in self._store:
            if existing.get("fact") == fact and existing.get("source_provenance") == source_provenance:
                logger.debug(f"Semantic memory already exists: {memory_id}")
                return memory_id
        
        self._store.append(entry)
        logger.debug(f"Semantic memory stored: {memory_id}")
        return memory_id
    
    async def query(self, query: str, trust_min: int = 1,
                   limit: int = 10) -> List[Dict[str, Any]]:
        """
        Query semantic memory.
        
        Simple keyword-based search (replace with vector search in Phase 2).
        """
        query_lower = query.lower()
        results = []
        
        for entry in self._store:
            if entry.get("trust_level", 0) < trust_min:
                continue
            
            # Simple keyword matching
            if any(term in entry.get("fact", "").lower() for term in query_lower.split()):
                results.append(entry)
        
        return results[:limit]
    
    async def get_by_project(self, project: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get all semantic memories for a project."""
        return [e for e in self._store if e.get("project") == project][:limit]
    
    async def get_by_id(self, memory_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific memory by ID."""
        for entry in self._store:
            if entry.get("memory_id") == memory_id:
                return entry
        return None
    
    async def update_trust_level(self, memory_id: str, new_level: int) -> bool:
        """Update the trust level of a memory entry."""
        for entry in self._store:
            if entry.get("memory_id") == memory_id:
                entry["trust_level"] = new_level
                entry["updated_at"] = time.time()
                return True
        return False
    
    async def count(self) -> int:
        """Get total count of semantic memories."""
        return len(self._store)
    
    async def clear(self) -> None:
        """Clear all semantic memories."""
        self._store.clear()
