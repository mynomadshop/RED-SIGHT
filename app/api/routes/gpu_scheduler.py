"""
RedSight - High-Performance Local AI Intelligence Platform
GPU Scheduler API Routes

Endpoints for GPU telemetry, job scheduling, and workload management.
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

# Router instance — wired into server.py
router = APIRouter(tags=["gpu_scheduler"])

# Global references — set by server.py during startup
_gpu_telemetry = None
_job_scheduler = None


def set_gpu_telemetry(telemetry):
    global _gpu_telemetry
    _gpu_telemetry = telemetry


def set_job_scheduler(scheduler):
    global _job_scheduler
    _job_scheduler = scheduler


# ─── GPU Telemetry Endpoints ───────────────────────────────────────────

@router.get("/scheduler/gpu/status", summary="Get scheduler GPU status")
async def get_gpu_status():
    """Get real-time status of all GPUs."""
    if not _gpu_telemetry:
        raise HTTPException(status_code=503, detail="GPU telemetry not initialized")
    
    try:
        status = _gpu_telemetry.get_gpu_status()
        return {
            "gpus": [gpu.to_dict() for gpu in status],
            "total_free_vram_mb": _gpu_telemetry.get_total_free_vram(),
            "total_used_vram_mb": _gpu_telemetry.get_total_used_vram(),
        }
    except Exception as e:
        logger.error(f"Failed to get GPU status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/scheduler/gpu/summary", summary="Get scheduler GPU summary")
async def get_gpu_summary():
    """Get GPU summary optimized for UI display."""
    if not _gpu_telemetry:
        raise HTTPException(status_code=503, detail="GPU telemetry not initialized")
    
    try:
        return _gpu_telemetry.get_gpu_summary()
    except Exception as e:
        logger.error(f"Failed to get GPU summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/gpu/best-for-model", summary="Find best GPU for model")
async def get_best_gpu_for_model(required_vram_mb: float = 1024.0, prefer_loaded: bool = True):
    """Find the best GPU for a model based on VRAM requirements."""
    if not _gpu_telemetry:
        raise HTTPException(status_code=503, detail="GPU telemetry not initialized")
    
    try:
        gpu_idx = _gpu_telemetry.get_best_gpu_for_model(required_vram_mb, prefer_loaded)
        return {
            "best_gpu_index": gpu_idx,
            "required_vram_mb": required_vram_mb,
        }
    except Exception as e:
        logger.error(f"Failed to find best GPU: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── Job Scheduling Endpoints ──────────────────────────────────────────

@router.post("/scheduler/jobs/submit", summary="Submit a scheduled job")
async def submit_job(request_data: Dict[str, Any]):
    """Submit a job to the GPU scheduler."""
    if not _job_scheduler:
        raise HTTPException(status_code=503, detail="Job scheduler not initialized")
    
    try:
        job_id = await _job_scheduler.submit_job(
            job_type=request_data.get("job_type", "inference"),
            payload=request_data.get("payload", {}),
            priority=request_data.get("priority", "normal"),
            gpu_affinity=request_data.get("gpu_affinity"),
            vram_reservation_mb=request_data.get("vram_reservation_mb"),
            timeout_seconds=request_data.get("timeout_seconds"),
        )
        return {"job_id": job_id, "status": "queued"}
    except Exception as e:
        logger.error(f"Failed to submit job: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/scheduler/jobs/cancel", summary="Cancel a scheduled job")
async def cancel_job(request_data: Dict[str, Any]):
    """Cancel a running or queued job."""
    if not _job_scheduler:
        raise HTTPException(status_code=503, detail="Job scheduler not initialized")
    
    job_id = request_data.get("job_id", "")
    
    try:
        success = await _job_scheduler.cancel_job(job_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found or cannot be cancelled")
        return {"job_id": job_id, "cancelled": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to cancel job: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/scheduler/jobs/queue-depth", summary="Get scheduler queue depth")
async def get_queue_depth():
    """Get the current queue depth."""
    if not _job_scheduler:
        raise HTTPException(status_code=503, detail="Job scheduler not initialized")
    
    try:
        depth = await _job_scheduler.get_queue_depth()
        return {"queue_depth": depth}
    except Exception as e:
        logger.error(f"Failed to get queue depth: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/scheduler/jobs/{job_id}", summary="Get scheduled job status")
async def get_job_status(job_id: str):
    """Get the current status and details of a job."""
    if not _job_scheduler:
        raise HTTPException(status_code=503, detail="Job scheduler not initialized")
    
    try:
        status = await _job_scheduler.get_job_status(job_id)
        if "error" in status:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        return status
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get job status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/scheduler/jobs", summary="List scheduled jobs")
async def list_jobs(status: Optional[str] = None, limit: int = 50):
    """List jobs with optional status filter."""
    if not _job_scheduler:
        raise HTTPException(status_code=503, detail="Job scheduler not initialized")
    
    try:
        from app.core.interfaces import JobStatus
        status_filter = JobStatus(status) if status else None
        jobs = await _job_scheduler.list_jobs(status=status_filter, limit=limit)
        return {"jobs": jobs, "count": len(jobs)}
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
    except Exception as e:
        logger.error(f"Failed to list jobs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── Benchmark Endpoints ───────────────────────────────────────────────

@router.post("/benchmarks/run", summary="Run a benchmark")
async def run_benchmark(
    profile_name: str,
    model_id: str,
    backend: str,
    test_cases: List[Dict[str, Any]],
):
    """Run a benchmark and return results."""
    if not _job_scheduler:
        raise HTTPException(status_code=503, detail="Job scheduler not initialized")
    
    try:
        result = await _job_scheduler.run_benchmark(
            profile_name=profile_name,
            model_id=model_id,
            backend=backend,
            test_cases=test_cases,
        )
        return result.to_dict()
    except Exception as e:
        logger.error(f"Failed to run benchmark: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/benchmarks/profiles", summary="Get benchmark profiles")
async def get_benchmark_profiles():
    """Get all recorded benchmark profiles."""
    if not _job_scheduler:
        raise HTTPException(status_code=503, detail="Job scheduler not initialized")
    
    try:
        profiles = _job_scheduler.get_benchmark_profiles()
        return {"profiles": profiles, "count": len(profiles)}
    except Exception as e:
        logger.error(f"Failed to get benchmark profiles: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/benchmarks/history", summary="Get benchmark history")
async def get_benchmark_history():
    """Get all benchmark results."""
    if not _job_scheduler:
        raise HTTPException(status_code=503, detail="Job scheduler not initialized")
    
    try:
        history = _job_scheduler.get_benchmark_history()
        return {"history": history, "count": len(history)}
    except Exception as e:
        logger.error(f"Failed to get benchmark history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── Initialization Check ──────────────────────────────────────────────

@router.get("/gpu/health", summary="Check GPU subsystem health")
async def gpu_health():
    """Check if GPU subsystem is properly initialized."""
    telemetry_ok = _gpu_telemetry is not None
    scheduler_ok = _job_scheduler is not None
    
    return {
        "gpu_telemetry": "ok" if telemetry_ok else "not_initialized",
        "job_scheduler": "ok" if scheduler_ok else "not_initialized",
        "ready": telemetry_ok and scheduler_ok,
    }
