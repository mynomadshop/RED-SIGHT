"""
RedSight - High-Performance Local AI Intelligence Platform
Memory API Routes

Provides REST endpoints for the advanced memory system:
- GET /api/v1/memory/{type} — List memory entries
- POST /api/v1/memory/{type} — Add memory entry
- GET /api/v1/memory/{type}/search — Search memory
- GET /api/v1/memory/stats — Get memory statistics
- DELETE /api/v1/memory/{type} — Clear memory type
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

from app.memory.memory_store import (
    MemoryStore, MemoryType, MemoryEntry, MemoryPriority,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Global reference set by server.py lifespan
memory_store: Optional[MemoryStore] = None


def set_memory_store(store: MemoryStore):
    """Set the global memory store reference."""
    global memory_store
    memory_store = store


# ─── Memory Type Endpoints ───────────────────────────────────────────

@router.get("/memory/working")
async def get_working_memory(
    limit: int = 50,
    offset: int = 0,
):
    """Get working memory entries."""
    if not memory_store:
        raise HTTPException(status_code=503, detail="Memory store not initialized")
    
    entries = await memory_store.working.list_entries(limit=limit, offset=offset)
    return {
        "memory_type": "working",
        "total": len(entries),
        "entries": [e.to_dict() for e in entries],
    }


@router.post("/memory/working")
async def add_working_memory(
    content: str,
    metadata: Optional[Dict[str, Any]] = None,
):
    """Add entry to working memory."""
    if not memory_store:
        raise HTTPException(status_code=503, detail="Memory store not initialized")
    
    entry_id = await memory_store.working.add(content, metadata)
    return {"id": entry_id, "status": "added"}


@router.get("/memory/episodic")
async def get_episodic_memory(
    limit: int = 50,
    offset: int = 0,
):
    """Get episodic memory entries."""
    if not memory_store:
        raise HTTPException(status_code=503, detail="Memory store not initialized")
    
    entries = await memory_store.episodic.list_entries(limit=limit, offset=offset)
    return {
        "memory_type": "episodic",
        "total": len(entries),
        "entries": [e.to_dict() for e in entries],
    }


@router.post("/memory/episodic")
async def add_episodic_memory(
    user_message: str,
    assistant_response: str,
    metadata: Optional[Dict[str, Any]] = None,
):
    """Add episode to episodic memory."""
    if not memory_store:
        raise HTTPException(status_code=503, detail="Memory store not initialized")
    
    entry_id = await memory_store.episodic.add_episode(
        user_message=user_message,
        assistant_response=assistant_response,
        metadata=metadata,
    )
    return {"id": entry_id, "status": "added"}


@router.get("/memory/semantic")
async def get_semantic_memory(
    limit: int = 50,
    offset: int = 0,
):
    """Get semantic memory entries."""
    if not memory_store:
        raise HTTPException(status_code=503, detail="Memory store not initialized")
    
    entries = await memory_store.semantic.list_entries(limit=limit, offset=offset)
    return {
        "memory_type": "semantic",
        "total": len(entries),
        "entries": [e.to_dict() for e in entries],
    }


@router.post("/memory/semantic")
async def add_semantic_memory(
    fact: str,
    category: str,
    confidence: float = 1.0,
    metadata: Optional[Dict[str, Any]] = None,
):
    """Add fact to semantic memory."""
    if not memory_store:
        raise HTTPException(status_code=503, detail="Memory store not initialized")
    
    entry_id = await memory_store.semantic.add_fact(
        fact=fact,
        category=category,
        confidence=confidence,
        metadata=metadata,
    )
    return {"id": entry_id, "status": "added"}


@router.get("/memory/procedural")
async def get_procedural_memory(
    limit: int = 50,
    offset: int = 0,
):
    """Get procedural memory entries."""
    if not memory_store:
        raise HTTPException(status_code=503, detail="Memory store not initialized")
    
    entries = await memory_store.procedural.list_entries(limit=limit, offset=offset)
    return {
        "memory_type": "procedural",
        "total": len(entries),
        "entries": [e.to_dict() for e in entries],
    }


@router.post("/memory/procedural")
async def add_procedural_memory(
    pattern_name: str,
    description: str,
    steps: List[str],
    success_rate: float = 1.0,
    metadata: Optional[Dict[str, Any]] = None,
):
    """Add pattern to procedural memory."""
    if not memory_store:
        raise HTTPException(status_code=503, detail="Memory store not initialized")
    
    entry_id = await memory_store.procedural.add_pattern(
        pattern_name=pattern_name,
        description=description,
        steps=steps,
        success_rate=success_rate,
        metadata=metadata,
    )
    return {"id": entry_id, "status": "added"}


# ─── Search Endpoints ────────────────────────────────────────────────

@router.get("/memory/search")
async def search_memory(
    query: str,
    memory_types: Optional[str] = None,  # Comma-separated
    limit: int = 20,
):
    """Search across all memory types."""
    if not memory_store:
        raise HTTPException(status_code=503, detail="Memory store not initialized")
    
    # Parse memory types
    types = None
    if memory_types:
        type_map = {
            "working": MemoryType.WORKING,
            "episodic": MemoryType.EPISODIC,
            "semantic": MemoryType.SEMANTIC,
            "procedural": MemoryType.PROCEDURAL,
        }
        types = [type_map[t.strip()] for t in memory_types.split(",") if t.strip() in type_map]
    
    results = await memory_store.search(
        query=query,
        memory_types=types,
        limit=limit,
    )
    return {
        "query": query,
        "total": len(results),
        "results": [e.to_dict() for e in results],
    }


@router.get("/memory/episodic/search")
async def search_episodes(
    query: str,
    limit: int = 10,
    min_relevance: float = 0.0,
):
    """Search episodic memory."""
    if not memory_store:
        raise HTTPException(status_code=503, detail="Memory store not initialized")
    
    results = await memory_store.episodic.search_episodes(
        query=query,
        limit=limit,
        min_relevance=min_relevance,
    )
    return {
        "query": query,
        "total": len(results),
        "results": results,
    }


# ─── Stats Endpoint ──────────────────────────────────────────────────

@router.get("/memory/stats")
async def get_memory_stats():
    """Get statistics for all memory stores."""
    if not memory_store:
        raise HTTPException(status_code=503, detail="Memory store not initialized")
    
    stats = await memory_store.get_stats()
    return stats


# ─── Clear Endpoints ─────────────────────────────────────────────────

@router.delete("/memory/working")
async def clear_working_memory():
    """Clear all working memory."""
    if not memory_store:
        raise HTTPException(status_code=503, detail="Memory store not initialized")
    
    await memory_store.working.clear()
    return {"status": "cleared", "memory_type": "working"}


@router.delete("/memory/episodic")
async def clear_episodic_memory():
    """Clear all episodic memory."""
    if not memory_store:
        raise HTTPException(status_code=503, detail="Memory store not initialized")
    
    await memory_store.episodic.clear()
    return {"status": "cleared", "memory_type": "episodic"}


@router.delete("/memory/semantic")
async def clear_semantic_memory():
    """Clear all semantic memory."""
    if not memory_store:
        raise HTTPException(status_code=503, detail="Memory store not initialized")
    
    await memory_store.semantic.clear()
    return {"status": "cleared", "memory_type": "semantic"}


@router.delete("/memory/procedural")
async def clear_procedural_memory():
    """Clear all procedural memory."""
    if not memory_store:
        raise HTTPException(status_code=503, detail="Memory store not initialized")
    
    await memory_store.procedural.clear()
    return {"status": "cleared", "memory_type": "procedural"}


@router.delete("/memory")
async def clear_all_memory():
    """Clear all memory types."""
    if not memory_store:
        raise HTTPException(status_code=503, detail="Memory store not initialized")
    
    await memory_store.clear_all()
    return {"status": "cleared", "memory_types": ["working", "episodic", "semantic", "procedural"]}
