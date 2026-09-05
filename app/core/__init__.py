"""Core interfaces and compatibility exports for RedSight."""

from __future__ import annotations

from importlib import import_module
from typing import Any

from app.core.interfaces import (
    Capability,
    ModelInfo,
    AuditEvent,
    AuditAction,
)


class AuthProvider:
    """Compatibility placeholder for the future authentication interface."""

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

_SECURITY_EXPORTS = {
    "SecurityPolicy": ("app.security.policy", "SecurityPolicy"),
    "SecretManager": ("app.security.secrets", "SecretManager"),
    "PermissionChecker": ("app.security.permissions", "PermissionChecker"),
    "AuditLogger": ("app.security.audit", "AuditLogger"),
}


def __getattr__(name: str) -> Any:
    """Load legacy security exports only when callers explicitly request them."""
    try:
        module_name, attribute = _SECURITY_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value
