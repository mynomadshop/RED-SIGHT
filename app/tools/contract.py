"""
RedSight - High-Performance Local AI Intelligence Platform
Tool Contract

Defines the structure of a tool with name, description, schema,
permissions, and execution logic.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ToolContract:
    """
    Tool Contract - Defines a tool's structure and execution.
    
    Tools are the atomic operations an agent can perform. Each tool
    has a name, schema, permissions, and execution logic.
    """
    
    name: str
    description: str
    schema: Dict[str, Any]  # JSON Schema for parameters
    permissions: List[str] = field(default_factory=list)
    timeout_seconds: int = 60
    requires_confirmation: bool = False
    is_destructive: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert contract to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "schema": self.schema,
            "permissions": self.permissions,
            "timeout_seconds": self.timeout_seconds,
            "requires_confirmation": self.requires_confirmation,
            "is_destructive": self.is_destructive,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolContract":
        """Create a contract from a dictionary."""
        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            schema=data.get("schema", {}),
            permissions=data.get("permissions", []),
            timeout_seconds=data.get("timeout_seconds", 60),
            requires_confirmation=data.get("requires_confirmation", False),
            is_destructive=data.get("is_destructive", False),
        )
    
    def validate_params(self, params: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        Validate parameters against schema.
        
        Returns (is_valid, error_message).
        """
        # Simple validation - check required fields
        required = self.schema.get("required", [])
        properties = self.schema.get("properties", {})
        
        for field_name in required:
            if field_name not in params:
                return False, f"Missing required parameter: {field_name}"
        
        # Check types
        for field_name, value in params.items():
            if field_name in properties:
                expected_type = properties[field_name].get("type")
                if expected_type and not self._check_type(value, expected_type):
                    return False, f"Parameter {field_name} must be of type {expected_type}"
        
        return True, None
    
    def _check_type(self, value: Any, expected_type: str) -> bool:
        """Check if a value matches the expected type."""
        type_map = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "array": list,
            "object": dict,
        }
        
        expected = type_map.get(expected_type)
        if not expected:
            return True  # Unknown type, assume valid
        
        return isinstance(value, expected)
