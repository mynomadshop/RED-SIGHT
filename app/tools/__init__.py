"""
RedSight - High-Performance Local AI Intelligence Platform
Tools Package

Provides the tool execution framework:
- Tool contracts and schemas
- Tool registry and permission management
- Built-in tool implementations
- Test runner for tool validation
"""

from app.tools.contract import ToolContract
from app.tools.registry import ToolRegistry
from app.tools.test_runner import TestRunner, TestResult, TestSuite

def get_builtin_tool_descriptions() -> list:
    """Return a list of built-in tool descriptions."""
    from app.tools.builtin import BUILTIN_TOOLS
    return BUILTIN_TOOLS if isinstance(BUILTIN_TOOLS, list) else []

__all__ = [
    "ToolContract",
    "ToolRegistry",
    "get_builtin_tool_descriptions",
    "TestRunner",
    "TestResult",
    "TestSuite",
]
