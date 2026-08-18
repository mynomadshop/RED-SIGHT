"""
RedSight - High-Performance Local AI Intelligence Platform
Capability registry

Maps model capabilities to available models. Used by the model router
to select the best model for each task type.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from app.core.interfaces import Capability, ModelInfo


class CapabilityRegistry:
    """
    Registry that maps model capabilities to available models.
    
    Maintains a mapping from capability categories (reasoning, fast_chat,
    coding, vision, embedding, reranker, voice) to the best available
    model for each. Updated dynamically as models are loaded/unloaded.
    """
    
    def __init__(self):
        self._models: Dict[str, ModelInfo] = {}
        self._capability_map: Dict[Capability, List[str]] = {
            cap: [] for cap in Capability
        }
    
    def register_model(self, model: ModelInfo) -> None:
        """Register a model in the capability registry."""
        self._models[model.model_id] = model
        # Clear and rebuild capability map
        for cap in Capability:
            self._capability_map[cap] = []
        for mid, m in self._models.items():
            for cap in m.capabilities:
                if cap in self._capability_map:
                    self._capability_map[cap].append(mid)
    
    def unregister_model(self, model_id: str) -> None:
        """Remove a model from the registry."""
        self._models.pop(model_id, None)
        for cap in Capability:
            self._capability_map[cap] = [
                mid for mid in self._capability_map[cap] if mid != model_id
            ]
    
    def get_best_model(self, capability: Capability) -> Optional[ModelInfo]:
        """Get the best available model for a given capability."""
        model_ids = self._capability_map.get(capability, [])
        if not model_ids:
            return None
        # Prefer loaded models, then pick the first
        for mid in model_ids:
            model = self._models.get(mid)
            if model and model.is_loaded:
                return model
        # Fallback to any registered model
        return self._models.get(model_ids[0])
    
    def get_models_by_capability(self, capability: Capability) -> List[ModelInfo]:
        """Get all models that support a given capability."""
        model_ids = self._capability_map.get(capability, [])
        return [self._models[mid] for mid in model_ids if mid in self._models]
    
    def get_all_models(self) -> List[ModelInfo]:
        """Get all registered models."""
        return list(self._models.values())
    
    def get_loaded_models(self) -> List[ModelInfo]:
        """Get only loaded models."""
        return [m for m in self._models.values() if m.is_loaded]
    
    def update_model(self, model: ModelInfo) -> None:
        """Update an existing model's info (e.g., after loading/unloading)."""
        if model.model_id in self._models:
            self._models[model.model_id] = model
            # Update capability map
            for cap in Capability:
                self._capability_map[cap] = [
                    mid for mid in self._capability_map[cap] if mid != model.model_id
                ]
                if model.is_loaded and cap in model.capabilities:
                    self._capability_map[cap].append(model.model_id)
    
    def get_capability_summary(self) -> Dict[str, List[str]]:
        """Get a summary of capabilities and their models."""
        return {
            cap.value: [self._models[mid].name for mid in ids if mid in self._models]
            for cap, ids in self._capability_map.items()
        }
