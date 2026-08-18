"""
RedSight - High-Performance Local AI Intelligence Platform
Tool Registry

Manages tool contracts, permissions, and execution.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from app.tools.contract import ToolContract

logger = logging.getLogger(__name__)


class ToolRegistry:
    """
    Tool Registry - Manages tool contracts and execution.
    
    Provides typed tool interface with permission checks.
    """
    
    def __init__(self):
        self._tools: Dict[str, ToolContract] = {}
    
    async def register(self, contract: ToolContract) -> str:
        """
        Register a tool.
        
        Returns tool name.
        """
        self._tools[contract.name] = contract
        logger.info(f"Tool registered: {contract.name}")
        return contract.name
    
    async def unregister(self, tool_name: str) -> bool:
        """Unregister a tool."""
        if tool_name not in self._tools:
            return False
        
        del self._tools[tool_name]
        logger.info(f"Tool unregistered: {tool_name}")
        return True
    
    async def get(self, tool_name: str) -> Optional[ToolContract]:
        """Get a tool by name."""
        return self._tools.get(tool_name)
    
    async def list_all(self) -> List[ToolContract]:
        """List all registered tools."""
        return list(self._tools.values())
    
    async def execute(self, tool_name: str, params: Dict[str, Any],
                     permissions: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Execute a tool with given parameters.
        
        Checks permissions and validates parameters before execution.
        """
        contract = self._tools.get(tool_name)
        if not contract:
            raise ValueError(f"Tool {tool_name} not found")
        
        # Check permissions
        if permissions:
            required = contract.permissions
            if not all(p in permissions for p in required):
                raise PermissionError(
                    f"Insufficient permissions for tool {tool_name}. "
                    f"Required: {required}, Have: {permissions}"
                )
        
        # Validate parameters
        is_valid, error = contract.validate_params(params)
        if not is_valid:
            raise ValueError(f"Invalid parameters for tool {tool_name}: {error}")
        
        # Check if confirmation is required
        if contract.requires_confirmation and not params.get("_confirmed"):
            raise ValueError(
                f"Tool {tool_name} requires confirmation. "
                f"Set _confirmed=True to proceed."
            )
        
        # Actually execute the tool by calling its execute method
        # Tools should have an 'execute' attribute that is callable
        tool_obj = getattr(self, f"_impl_{tool_name}", None)
        if tool_obj and callable(tool_obj):
            try:
                result = tool_obj(params)
                return {
                    "tool_name": tool_name,
                    "status": "success",
                    "params": params,
                    "output": result,
                    "success": True,
                }
            except Exception as e:
                return {
                    "tool_name": tool_name,
                    "status": "error",
                    "params": params,
                    "output": None,
                    "success": False,
                    "error": str(e),
                }
        
        # If no implementation found, raise an error instead of returning simulated data
        raise RuntimeError(
            f"No implementation found for tool '{tool_name}'. "
            f"Register an implementation via register_implementation(name, func)."
        )
    
    def register_implementation(self, tool_name: str, func: Callable) -> None:
        """Register a function as the implementation for a tool."""
        setattr(self, f"_impl_{tool_name}", func)
        logger.info(f"Implementation registered for tool: {tool_name}")
    
    async def check_permission(self, tool_name: str,
                              permissions: List[str]) -> bool:
        """Check if permissions are sufficient for a tool."""
        contract = self._tools.get(tool_name)
        if not contract:
            return False
        
        return all(p in permissions for p in contract.permissions)
