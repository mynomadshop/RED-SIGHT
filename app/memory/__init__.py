"""
RedSight - High-Performance Local AI Intelligence Platform
Memory Module

Exports memory store classes and utilities.
"""

from app.memory.memory_store import (
    MemoryType,
    MemoryPriority,
    MemoryEntry,
    MemoryStoreConfig,
    BaseMemoryStore,
    WorkingMemoryStore,
    EpisodicMemoryStore,
    SemanticMemoryStore,
    ProceduralMemoryStore,
)

# MemoryStore is an alias for the combined memory system
class MemoryStore:
    """Combined memory store that manages all memory types."""
    def __init__(self, metadata_db=None, vector_client=None):
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

__all__ = [
    "MemoryStore",
    "MemoryType",
    "MemoryPriority",
    "MemoryEntry",
    "MemoryStoreConfig",
    "BaseMemoryStore",
    "WorkingMemoryStore",
    "EpisodicMemoryStore",
    "SemanticMemoryStore",
    "ProceduralMemoryStore",
]
