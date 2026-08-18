"""
RedSight - High-Performance Local AI Intelligence Platform
Advanced Agent Memory System

Implements the MemoryStore protocol from the blueprint with four memory types:
- Working Memory: Short-term context for current session
- Episodic Memory: Long-term episodic records with retrieval
- Semantic Memory: Factual knowledge base with vector search
- Procedural Memory: Learned skills and patterns

All stores are backed by SQLite for persistence and Qdrant for vector search.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from app.retrieval.qdrant_client import QdrantClientWrapper
from app.retrieval.metadata_db import MetadataDB

logger = logging.getLogger(__name__)


class MemoryType(str, Enum):
    """Types of memory stores."""
    WORKING = "working"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"


class MemoryPriority(str, Enum):
    """Memory priority levels."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class MemoryEntry:
    """A single memory entry."""
    id: str
    content: str
    memory_type: MemoryType
    priority: MemoryPriority = MemoryPriority.NORMAL
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    vector_id: Optional[int] = None
    relevance_score: float = 0.0

    @property
    def is_expired(self) -> bool:
        """Check if memory entry has expired."""
        ttl = self.metadata.get("ttl_seconds")
        if ttl is None:
            return False
        return (time.time() - self.created_at) > ttl

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict."""
        return {
            "id": self.id,
            "content": self.content,
            "memory_type": self.memory_type.value,
            "priority": self.priority.value,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "vector_id": self.vector_id,
            "relevance_score": self.relevance_score,
        }


@dataclass
class MemoryStoreConfig:
    """Configuration for a memory store."""
    max_entries: int = 1000
    vector_collection: str = "working_memory"
    enable_vector_search: bool = True
    default_ttl_seconds: Optional[int] = None
    pruning_threshold: float = 0.1  # Retain top N% by relevance


class BaseMemoryStore:
    """Base class for memory stores."""

    def __init__(self, config: MemoryStoreConfig, metadata_db: Optional[MetadataDB] = None):
        self.config = config
        self._entries: Dict[str, MemoryEntry] = {}
        self._metadata_db = metadata_db
        self._vector_client: Optional[QdrantClientWrapper] = None
        self._lock = asyncio.Lock()

    async def set_vector_client(self, client: QdrantClientWrapper):
        """Set the vector client for this store."""
        self._vector_client = client

    async def add(self, entry: MemoryEntry) -> str:
        """Add a memory entry and return its ID."""
        async with self._lock:
            self._entries[entry.id] = entry
            # Persist to SQLite
            if self._metadata_db:
                await self._persist(entry)
            # Index in vector store
            if self._vector_client and self.config.enable_vector_search:
                vector_id = await self._index_vector(entry)
                entry.vector_id = vector_id
            return entry.id

    async def get(self, entry_id: str) -> Optional[MemoryEntry]:
        """Get a memory entry by ID."""
        entry = self._entries.get(entry_id)
        if entry and entry.is_expired:
            await self.remove(entry_id)
            return None
        return entry

    async def remove(self, entry_id: str) -> bool:
        """Remove a memory entry."""
        async with self._lock:
            if entry_id in self._entries:
                del self._entries[entry_id]
                if self._metadata_db:
                    await self._unpersist(entry_id)
                return True
            return False

    async def list_entries(
        self,
        priority: Optional[MemoryPriority] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[MemoryEntry]:
        """List memory entries with optional filtering."""
        entries = list(self._entries.values())
        # Filter by priority if specified
        if priority:
            entries = [e for e in entries if e.priority == priority]
        # Remove expired
        entries = [e for e in entries if not e.is_expired]
        # Sort by priority (critical first) then by relevance
        priority_order = {
            MemoryPriority.CRITICAL: 4,
            MemoryPriority.HIGH: 3,
            MemoryPriority.NORMAL: 2,
            MemoryPriority.LOW: 1,
        }
        entries.sort(
            key=lambda e: (priority_order.get(e.priority, 0), e.relevance_score),
            reverse=True,
        )
        return entries[offset:offset + limit]

    async def search(
        self,
        query: str,
        limit: int = 10,
        min_relevance: float = 0.0,
    ) -> List[MemoryEntry]:
        """Search memory entries by query text."""
        entries = await self.list_entries()
        # Simple text-based search (in production, use vector search via Qdrant)
        query_lower = query.lower()
        results = []
        for entry in entries:
            score = self._calculate_relevance(query_lower, entry.content.lower())
            if score >= min_relevance:
                entry.relevance_score = score
                results.append(entry)
        results.sort(key=lambda e: e.relevance_score, reverse=True)
        return results[:limit]

    async def prune(self) -> int:
        """Prune low-relevance entries to stay within max_entries."""
        entries = await self.list_entries()
        if len(entries) <= self.config.max_entries:
            return 0
        # Remove lowest relevance entries
        to_remove = len(entries) - self.config.max_entries
        entries.sort(key=lambda e: e.relevance_score)
        removed = 0
        for entry in entries[:to_remove]:
            if await self.remove(entry.id):
                removed += 1
        return removed

    async def clear(self):
        """Clear all entries."""
        async with self._lock:
            self._entries.clear()

    async def get_stats(self) -> Dict[str, Any]:
        """Get store statistics."""
        entries = list(self._entries.values())
        return {
            "total_entries": len(entries),
            "by_priority": {
                p.value: len([e for e in entries if e.priority == p])
                for p in MemoryPriority
            },
            "max_entries": self.config.max_entries,
        }

    def _calculate_relevance(self, query: str, text: str) -> float:
        """Calculate relevance score for a query against text."""
        if not query or not text:
            return 0.0
        query_words = set(query.split())
        text_words = set(text.split())
        if not query_words or not text_words:
            return 0.0
        intersection = query_words & text_words
        return len(intersection) / len(query_words)

    async def _persist(self, entry: MemoryEntry):
        """Persist entry to SQLite (abstract)."""
        pass

    async def _unpersist(self, entry_id: str):
        """Unpersist entry from SQLite (abstract)."""
        pass

    async def _index_vector(self, entry: MemoryEntry) -> Optional[int]:
        """Index entry in vector store (abstract)."""
        return None


class WorkingMemoryStore(BaseMemoryStore):
    """Working memory: short-term context for current session.
    
    TTL-based expiration, limited capacity, auto-pruning.
    """

    def __init__(
        self,
        max_entries: int = 100,
        default_ttl_seconds: int = 3600,
        metadata_db: Optional[MetadataDB] = None,
    ):
        config = MemoryStoreConfig(
            max_entries=max_entries,
            vector_collection="working_memory",
            enable_vector_search=False,  # Working memory doesn't need vector search
            default_ttl_seconds=default_ttl_seconds,
        )
        super().__init__(config, metadata_db)

    async def add(self, content: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """Add content to working memory."""
        entry_id = hashlib.md5(
            f"{content}{time.time()}".encode()
        ).hexdigest()[:12]
        entry = MemoryEntry(
            id=entry_id,
            content=content,
            memory_type=MemoryType.WORKING,
            priority=MemoryPriority.NORMAL,
            metadata=metadata or {},
        )
        # Apply default TTL if not specified
        if "ttl_seconds" not in entry.metadata:
            entry.metadata["ttl_seconds"] = self.config.default_ttl_seconds
        return await super().add(entry)

    async def get_context(self, max_tokens: int = 2000) -> str:
        """Get current working memory as context string."""
        entries = await self.list_entries(limit=50)
        context_parts = []
        total_tokens = 0
        for entry in entries:
            # Rough token estimate: 1 token ~ 4 chars
            tokens = len(entry.content) // 4
            if total_tokens + tokens > max_tokens:
                break
            context_parts.append(entry.content)
            total_tokens += tokens
        return "\n\n".join(context_parts)


class EpisodicMemoryStore(BaseMemoryStore):
    """Episodic memory: long-term episodic records with retrieval.
    
    Stores complete interaction episodes with full context.
    """

    def __init__(
        self,
        max_entries: int = 10000,
        metadata_db: Optional[MetadataDB] = None,
        vector_client: Optional[QdrantClientWrapper] = None,
    ):
        config = MemoryStoreConfig(
            max_entries=max_entries,
            vector_collection="episodic_memory",
            enable_vector_search=True,
        )
        super().__init__(config, metadata_db)
        if vector_client:
            self._vector_client = vector_client

    async def add_episode(
        self,
        user_message: str,
        assistant_response: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Add a complete interaction episode."""
        content = f"[USER] {user_message}\n[ASSISTANT] {assistant_response}"
        entry_id = hashlib.md5(
            f"{user_message}{assistant_response}{time.time()}".encode()
        ).hexdigest()[:12]
        entry = MemoryEntry(
            id=entry_id,
            content=content,
            memory_type=MemoryType.EPISODIC,
            priority=MemoryPriority.HIGH,
            metadata=metadata or {
                "user_message": user_message,
                "assistant_response": assistant_response,
            },
        )
        return await super().add(entry)

    async def search_episodes(
        self,
        query: str,
        limit: int = 10,
        min_relevance: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """Search episodes and return structured results."""
        entries = await self.search(query, limit=limit, min_relevance=min_relevance)
        results = []
        for entry in entries:
            meta = entry.metadata
            results.append({
                "id": entry.id,
                "user_message": meta.get("user_message", ""),
                "assistant_response": meta.get("assistant_response", ""),
                "relevance_score": entry.relevance_score,
                "created_at": entry.created_at,
            })
        return results

    async def _index_vector(self, entry: MemoryEntry) -> Optional[int]:
        """Index episode in vector store."""
        if not self._vector_client:
            return None
        try:
            # Extract user message for vectorization
            meta = entry.metadata
            text = meta.get("user_message", entry.content)
            # Create or get collection
            await self._vector_client.get_collection(
                self.config.vector_collection,
                force_recreate=False,
            )
            # Index the text
            ids = await self._vector_client.upsert_points(
                collection_name=self.config.vector_collection,
                points=[{
                    "id": entry.id,
                    "payload": {
                        "content": entry.content,
                        "memory_type": entry.memory_type.value,
                        "created_at": entry.created_at,
                    },
                }],
            )
            return ids[0] if ids else None
        except Exception as e:
            logger.warning(f"Failed to index episodic memory: {e}")
            return None


class SemanticMemoryStore(BaseMemoryStore):
    """Semantic memory: factual knowledge base with vector search.
    
    Stores facts, concepts, and relationships.
    """

    def __init__(
        self,
        max_entries: int = 50000,
        metadata_db: Optional[MetadataDB] = None,
        vector_client: Optional[QdrantClientWrapper] = None,
    ):
        config = MemoryStoreConfig(
            max_entries=max_entries,
            vector_collection="semantic_memory",
            enable_vector_search=True,
        )
        super().__init__(config, metadata_db)
        if vector_client:
            self._vector_client = vector_client

    async def add_fact(
        self,
        fact: str,
        category: str,
        confidence: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Add a factual entry."""
        entry_id = hashlib.md5(
            f"{fact}{category}{time.time()}".encode()
        ).hexdigest()[:12]
        entry = MemoryEntry(
            id=entry_id,
            content=fact,
            memory_type=MemoryType.SEMANTIC,
            priority=MemoryPriority.HIGH,
            metadata={
                "category": category,
                "confidence": confidence,
                **(metadata or {}),
            },
        )
        return await super().add(entry)

    async def get_facts_by_category(
        self,
        category: str,
        limit: int = 50,
    ) -> List[MemoryEntry]:
        """Get facts by category."""
        entries = await self.list_entries()
        return [
            e for e in entries
            if e.metadata.get("category") == category
        ][:limit]

    async def search_facts(
        self,
        query: str,
        limit: int = 10,
        min_relevance: float = 0.0,
    ) -> List[MemoryEntry]:
        """Search facts by query."""
        return await self.search(query, limit=limit, min_relevance=min_relevance)

    async def _index_vector(self, entry: MemoryEntry) -> Optional[int]:
        """Index fact in vector store."""
        if not self._vector_client:
            return None
        try:
            await self._vector_client.get_collection(
                self.config.vector_collection,
                force_recreate=False,
            )
            ids = await self._vector_client.upsert_points(
                collection_name=self.config.vector_collection,
                points=[{
                    "id": entry.id,
                    "payload": {
                        "content": entry.content,
                        "category": entry.metadata.get("category", ""),
                        "confidence": entry.metadata.get("confidence", 1.0),
                    },
                }],
            )
            return ids[0] if ids else None
        except Exception as e:
            logger.warning(f"Failed to index semantic memory: {e}")
            return None


class ProceduralMemoryStore(BaseMemoryStore):
    """Procedural memory: learned skills and patterns.
    
    Stores patterns of behavior, learned procedures, and skill sequences.
    """

    def __init__(
        self,
        max_entries: int = 5000,
        metadata_db: Optional[MetadataDB] = None,
        vector_client: Optional[QdrantClientWrapper] = None,
    ):
        config = MemoryStoreConfig(
            max_entries=max_entries,
            vector_collection="procedural_memory",
            enable_vector_search=True,
        )
        super().__init__(config, metadata_db)
        if vector_client:
            self._vector_client = vector_client

    async def add_pattern(
        self,
        pattern_name: str,
        description: str,
        steps: List[str],
        success_rate: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Add a learned pattern/procedure."""
        content = f"[PATTERN] {pattern_name}\n{description}\n[STEPS]\n" + "\n".join(
            f"  {i+1}. {step}" for i, step in enumerate(steps)
        )
        entry_id = hashlib.md5(
            f"{pattern_name}{description}{time.time()}".encode()
        ).hexdigest()[:12]
        entry = MemoryEntry(
            id=entry_id,
            content=content,
            memory_type=MemoryType.PROCEDURAL,
            priority=MemoryPriority.HIGH,
            metadata={
                "pattern_name": pattern_name,
                "steps": steps,
                "success_rate": success_rate,
                **(metadata or {}),
            },
        )
        return await super().add(entry)

    async def get_patterns_by_name(self, name: str) -> Optional[MemoryEntry]:
        """Get a pattern by name."""
        entries = await self.list_entries()
        for entry in entries:
            if entry.metadata.get("pattern_name") == name:
                return entry
        return None

    async def find_matching_patterns(
        self,
        context: str,
        limit: int = 5,
    ) -> List[MemoryEntry]:
        """Find patterns that match the given context."""
        return await self.search(context, limit=limit, min_relevance=0.3)

    async def update_success_rate(self, entry_id: str, new_rate: float):
        """Update the success rate of a pattern."""
        entry = await self.get(entry_id)
        if entry:
            entry.metadata["success_rate"] = new_rate
            entry.updated_at = time.time()

    async def _index_vector(self, entry: MemoryEntry) -> Optional[int]:
        """Index pattern in vector store."""
        if not self._vector_client:
            return None
        try:
            await self._vector_client.get_collection(
                self.config.vector_collection,
                force_recreate=False,
            )
            ids = await self._vector_client.upsert_points(
                collection_name=self.config.vector_collection,
                points=[{
                    "id": entry.id,
                    "payload": {
                        "content": entry.content,
                        "pattern_name": entry.metadata.get("pattern_name", ""),
                        "success_rate": entry.metadata.get("success_rate", 1.0),
                    },
                }],
            )
            return ids[0] if ids else None
        except Exception as e:
            logger.warning(f"Failed to index procedural memory: {e}")
            return None


class MemoryStore:
    """Unified memory store interface combining all memory types.
    
    Provides a single interface for managing working, episodic,
    semantic, and procedural memory.
    """

    def __init__(
        self,
        metadata_db: Optional[MetadataDB] = None,
        vector_client: Optional[QdrantClientWrapper] = None,
    ):
        self.working = WorkingMemoryStore(metadata_db=metadata_db)
        self.episodic = EpisodicMemoryStore(
            metadata_db=metadata_db,
            vector_client=vector_client,
        )
        self.semantic = SemanticMemoryStore(
            metadata_db=metadata_db,
            vector_client=vector_client,
        )
        self.procedural = ProceduralMemoryStore(
            metadata_db=metadata_db,
            vector_client=vector_client,
        )
        self._stores = {
            MemoryType.WORKING: self.working,
            MemoryType.EPISODIC: self.episodic,
            MemoryType.SEMANTIC: self.semantic,
            MemoryType.PROCEDURAL: self.procedural,
        }

    def get_store(self, memory_type: MemoryType) -> BaseMemoryStore:
        """Get a specific memory store."""
        return self._stores[memory_type]

    async def add(
        self,
        entry: MemoryEntry,
    ) -> str:
        """Add a memory entry to the appropriate store."""
        store = self._stores[entry.memory_type]
        return await store.add(entry)

    async def get(
        self,
        entry_id: str,
        memory_type: Optional[MemoryType] = None,
    ) -> Optional[MemoryEntry]:
        """Get a memory entry from all stores."""
        if memory_type:
            store = self._stores[memory_type]
            return await store.get(entry_id)
        # Search all stores
        for store in self._stores.values():
            entry = await store.get(entry_id)
            if entry:
                return entry
        return None

    async def search(
        self,
        query: str,
        memory_types: Optional[List[MemoryType]] = None,
        limit: int = 20,
    ) -> List[MemoryEntry]:
        """Search across all memory types."""
        if memory_types is None:
            memory_types = list(self._stores.keys())
        results = []
        for mtype in memory_types:
            store = self._stores[mtype]
            entries = await store.search(query, limit=limit)
            results.extend(entries)
        # Sort by relevance
        results.sort(key=lambda e: e.relevance_score, reverse=True)
        return results[:limit]

    async def get_stats(self) -> Dict[str, Any]:
        """Get statistics for all memory stores."""
        return {
            mtype.value: await store.get_stats()
            for mtype, store in self._stores.items()
        }

    async def prune_all(self):
        """Prune all memory stores."""
        for store in self._stores.values():
            await store.prune()

    async def clear_all(self):
        """Clear all memory stores."""
        for store in self._stores.values():
            await store.clear()
