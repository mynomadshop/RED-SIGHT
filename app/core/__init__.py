"""
RedSight - High-Performance Local AI Intelligence Platform
Core Package

Provides core system components:
- Interfaces and abstract base classes
- Configuration and settings
- Capability registry
- Security and authentication
"""

from app.core.interfaces import (
    Capability,
    ModelInfo,
    AuditEvent,
    AuditAction,
)

# SecurityPolicy and AuthProvider are defined in app.security module
from app.security.policy import SecurityPolicy
# AuthProvider is a stub for now - defined inline if needed
class AuthProvider:
    """Placeholder authentication provider interface."""
    pass

# SecretManager, PermissionChecker, AuditLogger are in app.security
from app.security.secrets import SecretManager
from app.security.permissions import PermissionChecker
from app.security.audit import AuditLogger

__all__ = [
    "Capability",
    "ModelInfo",
    "AuditEvent",
    "AuditAction",
    "SecurityPolicy",
    "AuthProvider",
    "SecretManager",
    "PermissionChecker",
    "AuditLogger",
]
