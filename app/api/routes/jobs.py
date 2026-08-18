"""
RedSight - High-Performance Local AI Intelligence Platform
Job Routes - Indexing Jobs

Manages indexing job lifecycle: create, process, re-index, list.
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

from app.ingestion.indexer import Indexer

logger = logging.getLogger(__name__)

router = APIRouter()

# Global indexer instance (set by server startup)
_indexer: Optional[Indexer] = None


def set_indexer(indexer: Indexer):
    """Set the global indexer instance."""
    global _indexer
    _indexer = indexer


@router.post("/jobs/index")
async def create_index_job(request: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create and run an indexing job.

    Accepts:
    - path: file or directory to index
    - collection: target collection
    - project: project identifier
    """
    if not _indexer:
        raise HTTPException(
            status_code=503,
            detail="Indexer not initialized. Server not started?",
        )

    path = request.get("path", "")
    collection = request.get("collection", "knowledge_docs")
    project = request.get("project", "default")

    if not path:
        raise HTTPException(status_code=400, detail="No path provided")

    try:
        job_id = await _indexer.create_job(path, collection, project)
        result = await _indexer.process_job(job_id)
        return result
    except Exception as e:
        logger.error(f"Index job failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/jobs/index/batch")
async def batch_index(request: Dict[str, Any]) -> Dict[str, Any]:
    """
    Index multiple files in batch.

    Accepts:
    - paths: list of file/directory paths
    - collection: target collection
    - project: project identifier
    """
    if not _indexer:
        raise HTTPException(
            status_code=503,
            detail="Indexer not initialized. Server not started?",
        )

    paths = request.get("paths", [])
    collection = request.get("collection", "knowledge_docs")
    project = request.get("project", "default")

    if not paths:
        raise HTTPException(status_code=400, detail="No paths provided")

    try:
        results = await _indexer.index_files(paths, collection, project)
        return {
            "jobs": results,
            "count": len(results),
        }
    except Exception as e:
        logger.error(f"Batch index failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/collections/{collection}/reindex")
async def reindex_collection(collection: str) -> Dict[str, Any]:
    """
    Re-index an entire collection.

    Deletes existing data and re-indexes all sources.
    """
    if not _indexer:
        raise HTTPException(
            status_code=503,
            detail="Indexer not initialized. Server not started?",
        )

    if not _indexer._metadata:
        raise HTTPException(
            status_code=501,
            detail="Metadata DB required for re-indexing",
        )

    try:
        job_ids = await _indexer.reindex_collection(collection)
        return {
            "collection": collection,
            "status": "cleared",
            "job_ids": job_ids,
            "message": f"Collection '{collection}' cleared. Add files and run indexing.",
        }
    except Exception as e:
        logger.error(f"Re-index failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jobs")
async def list_jobs(
    status: Optional[str] = None,
    limit: int = 50,
) -> Dict[str, Any]:
    """List indexing jobs."""
    if not _indexer:
        return {"jobs": [], "count": 0}

    try:
        jobs = await _indexer.list_jobs(status=status, limit=limit)
        return {
            "jobs": jobs,
            "count": len(jobs),
        }
    except Exception as e:
        logger.error(f"Failed to list jobs: {e}")
        return {"jobs": [], "count": 0, "error": str(e)}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str) -> Dict[str, Any]:
    """Get job details."""
    if not _indexer:
        raise HTTPException(status_code=503, detail="Indexer not initialized")

    try:
        job = await _indexer.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
        return job
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get job: {e}")
        raise HTTPException(status_code=500, detail=str(e))
