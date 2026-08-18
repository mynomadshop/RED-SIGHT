"""
RedSight - High-Performance Local AI Intelligence Platform
Model/Tool Router

Routes tasks to the best available model or tool based on capability,
VRAM, latency, and policy.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.config.capability_registry import CapabilityRegistry
from app.config.settings import get_settings
from app.core.interfaces import Capability, ModelInfo

logger = logging.getLogger(__name__)


class ModelToolRouter:
    """
    Model/Tool Router - Selects the best model/tool for a task.
    
    Routes based on:
    1. Privacy policy (local-only mode)
    2. Required capability (reasoning, coding, etc.)
    3. Resource state (VRAM, queue depth)
    4. Performance benchmarks
    """
    
    def __init__(self, capability_registry: Optional[CapabilityRegistry] = None):
        self._registry = capability_registry or CapabilityRegistry()
        self._settings = get_settings()
    
    async def select_model(self, capability: Capability,
                          context: Optional[Dict[str, Any]] = None) -> Optional[ModelInfo]:
        """
        Select the best model for a given capability.
        
        Args:
            capability: Required capability (reasoning, coding, etc.)
            context: Optional context (task type, urgency, etc.)
        
        Returns the best available ModelInfo, or None.
        """
        context = context or {}
        
        # Check privacy policy
        if self._settings.is_local_only:
            # Only return local models
            models = [m for m in self._registry.get_models_by_capability(capability)
                     if m.backend == "lmstudio"]
        else:
            models = self._registry.get_models_by_capability(capability)
        
        if not models:
            logger.warning(f"No models available for capability: {capability}")
            return None
        
        # Score and rank models
        scored = []
        for model in models:
            score = self._score_model(model, capability, context)
            scored.append((score, model))
        
        # Sort by score (descending)
        scored.sort(key=lambda x: x[0], reverse=True)
        
        best_score, best_model = scored[0]
        logger.debug(f"Selected model {best_model.model_id} (score: {best_score:.2f}) "
                    f"for capability {capability.value}")
        
        return best_model
    
    def _score_model(self, model: ModelInfo, capability: Capability,
                    context: Dict[str, Any]) -> float:
        """
        Score a model for a given capability and context.
        
        Factors:
        - Is loaded (affinity bonus)
        - VRAM headroom
        - Benchmark performance (if available)
        - Context size
        """
        score = 0.0
        
        # Loaded models get affinity bonus
        if model.is_loaded:
            score += 50.0
        
        # VRAM headroom bonus
        headroom_gb = self._settings.routing.vram_headroom_gb_per_gpu
        if model.vram_usage_mb < (model.total_vram_mb - headroom_gb * 1024):
            score += 20.0
        
        # Context size bonus (larger is better for complex tasks)
        if context.get("complexity") == "high":
            score += model.context_size / 10000.0
        
        # Capability match bonus
        if capability in model.capabilities:
            score += 10.0
        
        return score
    
    async def select_tool(self, tool_name: str,
                         permissions: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
        """
        Select and validate a tool for execution.
        
        Args:
            tool_name: Name of the tool to execute
            permissions: Required permissions
        
        Returns tool definition if available and permitted.
        """
        # Look up the tool in the capability registry
        try:
            tools = self._registry.get_tools()
            for tool in tools:
                if tool.get("name") == tool_name:
                    # Check permissions
                    if permissions:
                        required = tool.get("permissions", [])
                        if not all(p in permissions for p in required):
                            logger.warning(
                                f"Insufficient permissions for tool {tool_name}. "
                                f"Required: {required}, Have: {permissions}"
                            )
                            return None
                    
                    return {
                        "name": tool_name,
                        "available": True,
                        "permissions": tool.get("permissions", []),
                        "description": tool.get("description", ""),
                        "schema": tool.get("schema", {}),
                    }
        except Exception as e:
            logger.error(f"Error looking up tool {tool_name}: {e}")
        
        # If not found in registry, check if it's a known builtin tool
        from app.tools.builtin import get_builtin_tool_descriptions
        builtin_tools = get_builtin_tool_descriptions()
        for tool in builtin_tools:
            if tool.get("name") == tool_name:
                return {
                    "name": tool_name,
                    "available": True,
                    "permissions": tool.get("permissions", []),
                    "description": tool.get("description", ""),
                    "schema": tool.get("schema", {}),
                }
        
        # Tool not found
        logger.warning(f"Tool {tool_name} not found in registry or builtin tools")
        return None
    
    def register_model(self, model: ModelInfo) -> None:
        """Register a model in the capability registry."""
        self._registry.register_model(model)
    
    def get_available_capabilities(self) -> List[str]:
        """Get all available capabilities."""
        return [cap.value for cap in Capability]
