"""
RedSight - High-Performance Local AI Intelligence Platform
API Routes - GPU Status

GPU telemetry and status endpoints.
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/gpu/status")
async def get_gpu_status():
    """Get current status of all GPUs."""
    from app.server import gpu_telemetry
    
    if not gpu_telemetry:
        return {"error": "GPU telemetry not initialized"}
    
    gpus = gpu_telemetry.get_gpu_status()
    return {
        "gpus": [g.to_dict() for g in gpus],
        "total_free_vram_mb": gpu_telemetry.get_total_free_vram(),
        "total_used_vram_mb": gpu_telemetry.get_total_used_vram(),
    }


@router.get("/gpu/summary")
async def get_gpu_summary():
    """Get GPU summary for UI display."""
    from app.server import gpu_telemetry
    
    if not gpu_telemetry:
        return {"error": "GPU telemetry not initialized"}
    
    return gpu_telemetry.get_gpu_summary()
