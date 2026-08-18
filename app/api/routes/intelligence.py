"""
RedSight - High-Performance Local AI Intelligence Platform
API Routes - Project Intelligence (Phase 4)

Endpoints for project indexing, architecture queries,
decision memory, and project context.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter()


# Global project intelligence instance (set by server.py)
_project_intelligence = None


def set_project_intelligence(pi):
    """Set the project intelligence instance (called from server.py)."""
    global _project_intelligence
    _project_intelligence = pi


@router.get("/projects/stats")
async def get_project_stats():
    """Get overall project intelligence statistics."""
    if not _project_intelligence:
        raise HTTPException(status_code=503, detail="Project intelligence not initialized")

    try:
        stats = await _project_intelligence.get_project_stats()
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/projects/index")
async def index_project(project_root: str, max_files: int = 500):
    """Index a project and extract architecture."""
    if not _project_intelligence:
        raise HTTPException(status_code=503, detail="Project intelligence not initialized")

    try:
        context = await _project_intelligence.index_project(project_root, max_files)
        return {
            "project_root": context.project_root,
            "total_files": context.total_files,
            "total_symbols": context.total_symbols,
            "file_types": context.file_types,
            "top_dependencies": context.top_dependencies,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects/architecture/search")
async def search_architecture(query: str, limit: int = 10):
    """Search architecture nodes by name or path."""
    if not _project_intelligence:
        raise HTTPException(status_code=503, detail="Project intelligence not initialized")

    try:
        nodes = await _project_intelligence.search_architecture(query, limit)
        return {
            "query": query,
            "results": [
                {
                    "name": n.name,
                    "type": n.type,
                    "path": n.path,
                    "dependencies": n.dependencies,
                }
                for n in nodes
            ],
            "count": len(nodes),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects/architecture/dependencies")
async def get_dependencies(symbol_key: str):
    """Get dependencies for a symbol."""
    if not _project_intelligence:
        raise HTTPException(status_code=503, detail="Project intelligence not initialized")

    try:
        deps = await _project_intelligence.get_dependencies(symbol_key)
        return {"symbol": symbol_key, "dependencies": deps}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects/architecture/dependents")
async def get_dependents(symbol_key: str):
    """Get dependents for a symbol."""
    if not _project_intelligence:
        raise HTTPException(status_code=503, detail="Project intelligence not initialized")

    try:
        dependents = await _project_intelligence.get_dependents(symbol_key)
        return {"symbol": symbol_key, "dependents": dependents}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/projects/decisions/record")
async def record_decision(
    context: str,
    decision: str,
    rationale: str,
    tags: Optional[List[str]] = None,
    user_confirmed: bool = False,
):
    """Record a project decision."""
    if not _project_intelligence:
        raise HTTPException(status_code=503, detail="Project intelligence not initialized")

    try:
        decision_id = await _project_intelligence.record_decision(
            context=context,
            decision=decision,
            rationale=rationale,
            tags=tags,
            user_confirmed=user_confirmed,
        )
        return {"decision_id": decision_id, "success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects/decisions/search")
async def search_decisions(query: str, tags: Optional[str] = None, limit: int = 10):
    """Query project decisions."""
    if not _project_intelligence:
        raise HTTPException(status_code=503, detail="Project intelligence not initialized")

    try:
        tag_list = tags.split(",") if tags else None
        results = await _project_intelligence.query_decisions(query, tag_list, limit)
        return {
            "query": query,
            "results": [
                {
                    "id": d.decision_id,
                    "context": d.context,
                    "decision": d.decision,
                    "rationale": d.rationale,
                    "outcome": d.outcome,
                    "tags": d.tags,
                    "confirmed": d.user_confirmed,
                }
                for d in results
            ],
            "count": len(results),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects/context/export")
async def export_context(project_root: str):
    """Export project context as JSON."""
    if not _project_intelligence:
        raise HTTPException(status_code=503, detail="Project intelligence not initialized")

    try:
        context = await _project_intelligence.export_context(project_root)
        if not context:
            raise HTTPException(status_code=404, detail=f"Project not indexed: {project_root}")
        return context
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
