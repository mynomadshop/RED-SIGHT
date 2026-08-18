"""
RedSight - High-Performance Local AI Intelligence Platform
Source Routes - Chunk Inspection

Endpoints for viewing retrieved chunks and source files.
"""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException

from app.retrieval.source_viewer import SourceViewer

logger = logging.getLogger(__name__)

router = APIRouter()

# Global source viewer instance (set by server startup)
_source_viewer: Optional[SourceViewer] = None


def set_source_viewer(viewer: SourceViewer):
    """Set the global source viewer instance."""
    global _source_viewer
    _source_viewer = viewer


@router.get("/sources/chunk/{chunk_id}")
async def get_chunk_detail(chunk_id: str) -> Dict[str, Any]:
    """Get full detail for a chunk including provenance."""
    if not _source_viewer:
        raise HTTPException(status_code=503, detail="Source viewer not initialized")

    try:
        detail = await _source_viewer.get_chunk_detail(chunk_id)
        if detail:
            return detail.to_dict()
        return {"error": f"Chunk not found: {chunk_id}"}
    except Exception as e:
        logger.error(f"Failed to get chunk: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sources/file/{source_path:path}")
async def get_source_info(source_path: str) -> Dict[str, Any]:
    """Get metadata about a source file."""
    if not _source_viewer:
        raise HTTPException(status_code=503, detail="Source viewer not initialized")

    try:
        info = await _source_viewer.get_source_file_info(source_path)
        if info:
            return info.to_dict()
        return {"error": f"Source not found: {source_path}"}
    except Exception as e:
        logger.error(f"Failed to get source info: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sources/file/{source_path:path}/preview")
async def preview_source(
    source_path: str,
    offset: int = 0,
    length: int = 500,
) -> Dict[str, Any]:
    """Preview content from a source file."""
    if not _source_viewer:
        raise HTTPException(status_code=503, detail="Source viewer not initialized")

    try:
        result = await _source_viewer.preview_content(source_path, offset, length)
        return result
    except Exception as e:
        logger.error(f"Failed to preview source: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sources/file/{source_path:path}/related")
async def get_related_chunks(
    source_path: str,
    exclude_chunk_id: Optional[str] = None,
    limit: int = 10,
) -> Dict[str, Any]:
    """Get other chunks from the same source file."""
    if not _source_viewer:
        raise HTTPException(status_code=503, detail="Source viewer not initialized")

    try:
        chunks = await _source_viewer.get_related_chunks(
            source_path, exclude_chunk_id=exclude_chunk_id, limit=limit
        )
        return {
            "source_path": source_path,
            "chunks": [c.to_dict() for c in chunks],
            "count": len(chunks),
        }
    except Exception as e:
        logger.error(f"Failed to get related chunks: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sources/navigation/{source_path:path}")
async def get_source_navigation(
    source_path: str,
    current_chunk_id: str,
) -> Dict[str, Any]:
    """Get navigation info for browsing chunks in a source file."""
    if not _source_viewer:
        raise HTTPException(status_code=503, detail="Source viewer not initialized")

    try:
        result = await _source_viewer.get_source_navigation(source_path, current_chunk_id)
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get navigation: {e}")
        raise HTTPException(status_code=500, detail=str(e))
