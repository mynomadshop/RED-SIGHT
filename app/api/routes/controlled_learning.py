"""
RedSight - High-Performance Local AI Intelligence Platform
Controlled Learning API Routes

Endpoints for content ingestion, promotion, feedback, and learning analytics.
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(tags=["controlled-learning"])

# Global references — set by server.py
_learning_engine = None


def set_learning_engine(engine):
    global _learning_engine
    _learning_engine = engine


# ── Content Ingestion ─────────────────────────────────────────────────

@router.post("/learn/ingest", summary="Ingest content")
async def ingest_content(request_data: Dict[str, Any]):
    """Ingest content into the learning system."""
    if not _learning_engine:
        raise HTTPException(status_code=503, detail="Learning engine not initialized")
    
    try:
        content = request_data.get("content", "")
        source = request_data.get("source", "unknown")
        category = request_data.get("category", "general")
        trust_level_str = request_data.get("trust_level", "RAW")
        context = request_data.get("context")
        
        from app.learning import TrustLevel
        try:
            trust_level = TrustLevel[trust_level_str.upper()]
        except KeyError:
            raise HTTPException(status_code=400, detail=f"Invalid trust level: {trust_level_str}")
        
        event_id = await _learning_engine.ingest(
            content=content,
            source=source,
            category=category,
            trust_level=trust_level,
            context=context,
        )
        
        if event_id is None:
            raise HTTPException(status_code=403, detail="Content blocked by safety boundaries")
        
        return {"event_id": event_id, "status": "ingested"}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to ingest content: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/learn/ingest-batch", summary="Ingest content batch")
async def ingest_batch(request_data: Dict[str, Any]):
    """Ingest multiple content items at once."""
    if not _learning_engine:
        raise HTTPException(status_code=503, detail="Learning engine not initialized")
    
    try:
        items = request_data.get("items", [])
        event_ids = await _learning_engine.ingest_batch(items)
        return {"event_ids": event_ids, "count": len(event_ids)}
    
    except Exception as e:
        logger.error(f"Failed to ingest batch: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Promotion Management ─────────────────────────────────────────────

@router.post("/learn/promote", summary="Request promotion")
async def request_promotion(request_data: Dict[str, Any]):
    """Request to promote content to a higher trust level."""
    if not _learning_engine:
        raise HTTPException(status_code=503, detail="Learning engine not initialized")
    
    try:
        event_id = request_data.get("event_id")
        target_trust_str = request_data.get("target_trust", "VALIDATED")
        reason = request_data.get("reason", "")
        requested_by = request_data.get("requested_by", "system")
        context = request_data.get("context")
        
        from app.learning import TrustLevel
        try:
            target_trust = TrustLevel[target_trust_str.upper()]
        except KeyError:
            raise HTTPException(status_code=400, detail=f"Invalid trust level: {target_trust_str}")
        
        request_id = await _learning_engine.request_promotion(
            event_id=event_id,
            target_trust=target_trust,
            reason=reason,
            requested_by=requested_by,
            context=context,
        )
        
        if request_id is None:
            raise HTTPException(status_code=400, detail="Promotion request failed")
        
        return {"request_id": request_id}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to request promotion: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/learn/promotions/{request_id}/approve", summary="Approve promotion")
async def approve_promotion(request_id: str, request_data: Dict[str, Any]):
    """Approve a pending promotion request."""
    if not _learning_engine:
        raise HTTPException(status_code=503, detail="Learning engine not initialized")
    
    try:
        approved_by = request_data.get("approved_by", "user")
        success = await _learning_engine.approve_promotion(request_id, approved_by)
        
        if not success:
            raise HTTPException(status_code=404, detail=f"Promotion request {request_id} not found or not pending")
        
        return {"request_id": request_id, "approved": True}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to approve promotion: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/learn/promotions/{request_id}/reject", summary="Reject promotion")
async def reject_promotion(request_id: str, request_data: Dict[str, Any]):
    """Reject a pending promotion request."""
    if not _learning_engine:
        raise HTTPException(status_code=503, detail="Learning engine not initialized")
    
    try:
        reason = request_data.get("reason", "")
        success = await _learning_engine.reject_promotion(request_id, reason)
        
        if not success:
            raise HTTPException(status_code=404, detail=f"Promotion request {request_id} not found or not pending")
        
        return {"request_id": request_id, "rejected": True}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to reject promotion: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/learn/revoke", summary="Revoke promotion")
async def revoke_promotion(request_data: Dict[str, Any]):
    """Revoke a promotion (downgrade trust level)."""
    if not _learning_engine:
        raise HTTPException(status_code=503, detail="Learning engine not initialized")
    
    try:
        event_id = request_data.get("event_id")
        success = await _learning_engine.revoke_promotion(event_id)
        
        if not success:
            raise HTTPException(status_code=404, detail=f"Event {event_id} not found or already revoked")
        
        return {"event_id": event_id, "revoked": True}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to revoke promotion: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Feedback ──────────────────────────────────────────────────────────

@router.post("/learn/feedback", summary="Submit feedback")
async def submit_feedback(request_data: Dict[str, Any]):
    """Submit feedback for learned content."""
    if not _learning_engine:
        raise HTTPException(status_code=503, detail="Learning engine not initialized")
    
    try:
        content_hash = request_data.get("content_hash")
        score = request_data.get("score", 0.5)
        category = request_data.get("category", "quality")
        comment = request_data.get("comment")
        
        feedback_id = await _learning_engine.submit_feedback(
            content_hash=content_hash,
            score=score,
            category=category,
            comment=comment,
        )
        
        return {"feedback_id": feedback_id}
    
    except Exception as e:
        logger.error(f"Failed to submit feedback: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Query & Analysis ─────────────────────────────────────────────────

@router.get("/learn/events/{event_id}", summary="Get learning event")
async def get_event(event_id: str):
    """Get a learning event by ID."""
    if not _learning_engine:
        raise HTTPException(status_code=503, detail="Learning engine not initialized")
    
    try:
        event = await _learning_engine.get_event(event_id)
        if not event:
            raise HTTPException(status_code=404, detail=f"Event {event_id} not found")
        return event
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get event: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/learn/query", summary="Query learned content")
async def query_content(
    query: str = "",
    trust_min: str = "RAW",
    category: Optional[str] = None,
    limit: int = 50,
):
    """Query learned content."""
    if not _learning_engine:
        raise HTTPException(status_code=503, detail="Learning engine not initialized")
    
    try:
        from app.learning import TrustLevel
        try:
            trust_level = TrustLevel[trust_min.upper()]
        except KeyError:
            raise HTTPException(status_code=400, detail=f"Invalid trust level: {trust_min}")
        
        results = await _learning_engine.query(
            query=query,
            trust_min=trust_level,
            category=category,
            limit=limit,
        )
        
        return {"results": results, "count": len(results)}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to query: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/learn/promotions", summary="Get promotion requests")
async def get_promotions(status: Optional[str] = None, limit: int = 50):
    """Get promotion requests."""
    if not _learning_engine:
        raise HTTPException(status_code=503, detail="Learning engine not initialized")
    
    try:
        from app.learning import PromotionStatus
        status_filter = PromotionStatus(status) if status else None
        
        promotions = await _learning_engine.get_promotions(
            status=status_filter,
            limit=limit,
        )
        
        return {"promotions": promotions, "count": len(promotions)}
    
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
    except Exception as e:
        logger.error(f"Failed to get promotions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/learn/stats", summary="Get learning statistics")
async def get_stats():
    """Get learning statistics."""
    if not _learning_engine:
        raise HTTPException(status_code=503, detail="Learning engine not initialized")
    
    try:
        stats = await _learning_engine.get_stats()
        return stats
    
    except Exception as e:
        logger.error(f"Failed to get stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Initialization Check ─────────────────────────────────────────────

@router.get("/learn/health", summary="Check learning subsystem health")
async def learn_health():
    """Check if learning subsystem is properly initialized."""
    engine_ok = _learning_engine is not None
    
    return {
        "learning_engine": "ok" if engine_ok else "not_initialized",
        "ready": engine_ok,
    }
