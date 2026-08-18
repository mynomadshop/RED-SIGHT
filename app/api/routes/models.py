"""
RedSight - High-Performance Local AI Intelligence Platform
API Routes - Models

Model listing and selection endpoints.
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/models")
async def list_models():
    """List available models from LM Studio."""
    from app.server import lmstudio_provider
    
    if not lmstudio_provider:
        return {"error": "LM Studio provider not initialized"}
    
    models = await lmstudio_provider.list_models()
    return {
        "models": [m.to_dict() for m in models],
        "count": len(models),
    }


@router.get("/models/{model_id}")
async def get_model(model_id: str):
    """Get details for a specific model."""
    from app.server import lmstudio_provider
    
    if not lmstudio_provider:
        return {"error": "LM Studio provider not initialized"}
    
    models = await lmstudio_provider.list_models()
    for model in models:
        if model.model_id == model_id:
            return model.to_dict()
    
    return {"error": "Model not found", "model_id": model_id}
