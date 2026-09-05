"""Secrets, scopes, policy, and audit services.

Security implementations depend on the core interface package.  Keeping these
exports lazy prevents importing :mod:`app.security` from recursively loading
``app.core`` while it is still being initialized.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = ["SecretManager", "SecurityPolicy", "AuditLogger"]

_EXPORTS = {
    "SecretManager": ("app.security.secrets", "SecretManager"),
    "SecurityPolicy": ("app.security.policy", "SecurityPolicy"),
    "AuditLogger": ("app.security.audit", "AuditLogger"),
}


def __getattr__(name: str) -> Any:
    """Resolve public security services without eager cross-package imports."""
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value
