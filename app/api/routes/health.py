"""
RedSight - High-Performance Local AI Intelligence Platform
API Routes - Health Check

Basic health and status endpoints.
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "redsight",
        "version": "0.1.0",
    }


@router.get("/status")
async def system_status():
    """System status endpoint."""
    from app.server import gpu_telemetry, lmstudio_provider
    
    status = {
        "lmstudio_connected": False,
        "gpu_telemetry_active": gpu_telemetry is not None,
        "mode": "local_preferred",
    }
    
    if lmstudio_provider:
        status["lmstudio_connected"] = await lmstudio_provider.health_check()
    
    if gpu_telemetry:
        gpus = gpu_telemetry.get_gpu_status()
        status["gpus"] = [g.to_dict() for g in gpus]
    
    return status
