"""
RedSight - High-Performance Local AI Intelligence Platform
API Routes - Health Check

Basic health and status endpoints.
"""

from fastapi import APIRouter

from app.config.settings import get_settings

router = APIRouter()


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    settings = get_settings()
    return {
        "status": "healthy",
        "service": "redsight",
        "version": settings.platform.version,
    }


@router.get("/status")
async def system_status():
    """System status endpoint."""
    from app.server import gpu_telemetry, lmstudio_provider

    settings = get_settings()
    status = {
        "lmstudio_connected": False,
        "gpu_telemetry_active": gpu_telemetry is not None,
        "mode": settings.platform.mode,
    }
    
    if lmstudio_provider:
        status["lmstudio_connected"] = await lmstudio_provider.health_check()
    
    if gpu_telemetry:
        gpus = gpu_telemetry.get_gpu_status()
        status["gpus"] = [g.to_dict() for g in gpus]
    
    return status
