"""
RedSight - High-Performance Local AI Intelligence Platform
Skills Package

Semantic discovery, manifest system, registry, and sandbox execution.
"""

from app.skills.discovery import SemanticSkillDiscovery
from app.skills.manifest import SkillManifest
from app.skills.registry import SkillRegistry
from app.skills.sandbox import SkillSandbox, ExecutionResult

__all__ = [
    "SemanticSkillDiscovery",
    "SkillManifest",
    "SkillRegistry",
    "SkillSandbox",
    "ExecutionResult",
]
