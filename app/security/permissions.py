"""
RedSight - High-Performance Local AI Intelligence Platform
Permission System

Enforces read-only, read-write, network, and destructive permissions
with audit logging and policy-based access control.
"""

from __future__ import annotations

import logging
import os
import shlex
import time
import uuid
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlsplit

from app.core.interfaces import AuditAction, AuditEvent

logger = logging.getLogger(__name__)

DEFAULT_FILE_DENY_PATTERNS = (
    "*/.env",
    "*/.env.*",
    "*/secrets",
    "*/secrets/*",
    "*/secrets.*",
    "*/credentials",
    "*/credentials/*",
    "*/credentials.*",
    "*/.ssh",
    "*/.ssh/*",
    "*/.aws",
    "*/.aws/*",
    "*/.git-credentials",
    "*/.netrc",
    "*/.npmrc",
    "*/.pypirc",
    "*/id_rsa*",
    "*/id_ed25519*",
)


class PermissionLevel:
    """Permission levels for tools and skills."""
    READ_ONLY = "read_only"
    READ_WRITE = "read_write"
    WRITE_ONLY = "write_only"
    DESTRUCTIVE = "destructive"


class PermissionPolicy:
    """
    Permission Policy - Defines who can do what.

    Supports:
    - Role-based permissions (user, admin, agent, guest)
    - File scope restrictions (read roots, write roots, deny patterns)
    - Network scope restrictions (allow/deny domains)
    - Command policy (allowlist, timeouts)
    - Destructive action protection (confirmation required)
    """

    def __init__(self):
        self._roles: Dict[str, Set[str]] = {}
        self._file_read_roots: List[str] = []
        self._file_write_roots: List[str] = []
        self._file_deny_patterns: List[str] = list(DEFAULT_FILE_DENY_PATTERNS)
        self._command_allowlist: List[str] = [
            "python", "pip", "git", "ls", "cat", "grep", "find", "head", "tail",
        ]
        self._network_allow_domains: List[str] = ["127.0.0.1", "localhost"]
        self._network_deny_domains: List[str] = []
        self._block_outbound: bool = False
        self._require_confirmation_destructive: bool = True
        self._allowed_destructive_actions: List[str] = [
            "delete", "overwrite", "send", "publish", "trade",
        ]

    def add_role(self, role: str, permissions: List[str]) -> None:
        """Add a role with its permissions."""
        self._roles[role] = set(permissions)
        logger.info(f"Role registered: {role} ({len(permissions)} permissions)")

    def has_permission(self, role: str, permission: str) -> bool:
        """Check if a role has a specific permission."""
        role_perms = self._roles.get(role, set())
        return permission in role_perms

    def get_role_permissions(self, role: str) -> Set[str]:
        """Get all permissions for a role."""
        return self._roles.get(role, set()).copy()

    def is_file_read_allowed(self, path: str) -> bool:
        """Check if a file path is allowed for reading."""
        return _path_is_allowed(path, self._file_read_roots, self._file_deny_patterns)

    def is_file_write_allowed(self, path: str) -> bool:
        """Check if a file path is allowed for writing."""
        return _path_is_allowed(path, self._file_write_roots, self._file_deny_patterns)

    def is_command_allowed(self, command: str) -> bool:
        """Check if a command is allowed."""
        return _command_is_allowed(command, self._command_allowlist)

    def is_network_allowed(self, domain: str) -> bool:
        """Check if a network domain is allowed."""
        if self._block_outbound:
            return False
        host = _normalize_host(domain)
        if not host:
            return False
        if self._network_deny_domains and any(
            _domain_matches(host, denied) for denied in self._network_deny_domains
        ):
            return False
        if self._network_allow_domains:
            return any(_domain_matches(host, allowed) for allowed in self._network_allow_domains)
        return True

    def requires_confirmation(self, action: str) -> bool:
        """Check if an action requires confirmation."""
        if not self._require_confirmation_destructive:
            return False
        return action in self._allowed_destructive_actions

    def set_file_read_roots(self, roots: List[str]) -> None:
        """Set allowed file read roots."""
        self._file_read_roots = roots

    def set_file_write_roots(self, roots: List[str]) -> None:
        """Set allowed file write roots."""
        self._file_write_roots = roots

    def set_command_allowlist(self, commands: List[str]) -> None:
        """Set allowed commands."""
        self._command_allowlist = commands

    def set_network_allow_domains(self, domains: List[str]) -> None:
        """Set allowed network domains."""
        self._network_allow_domains = domains

    def set_block_outbound(self, block: bool) -> None:
        """Block all outbound network."""
        self._block_outbound = block

    def to_dict(self) -> Dict[str, Any]:
        """Convert policy to dictionary."""
        return {
            "roles": {k: list(v) for k, v in self._roles.items()},
            "file_read_roots": self._file_read_roots,
            "file_write_roots": self._file_write_roots,
            "file_deny_patterns": self._file_deny_patterns,
            "command_allowlist": self._command_allowlist,
            "network_allow_domains": self._network_allow_domains,
            "network_deny_domains": self._network_deny_domains,
            "block_outbound": self._block_outbound,
            "require_confirmation_destructive": self._require_confirmation_destructive,
            "allowed_destructive_actions": self._allowed_destructive_actions,
        }


class PermissionChecker:
    """
    Permission Checker - Validates permissions before tool/skill execution.

    Checks:
    - Role-based permissions
    - File scope restrictions
    - Network scope restrictions
    - Destructive action confirmation
    - Tool-specific permissions
    """

    def __init__(self, policy: PermissionPolicy, audit_logger=None):
        self._policy = policy
        self._audit = audit_logger

    async def _record(
        self,
        *,
        actor: str,
        details: Dict[str, Any],
        result: str,
    ) -> None:
        """Write a typed permission event to the shared audit sink."""
        if not self._audit:
            return
        await self._audit.record(
            AuditEvent(
                event_id=f"permission_{time.time_ns()}_{uuid.uuid4().hex[:8]}",
                action=AuditAction.PERMISSION_CHECK,
                timestamp=time.time(),
                actor=actor,
                details=details,
                result=result,
            )
        )

    async def check_tool_permission(
        self,
        role: str,
        tool_name: str,
        tool_permissions: List[str],
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Check if a role can execute a tool.

        Returns {"allowed": bool, "reason": str, "details": dict}
        """
        # Check role permissions
        for perm in tool_permissions:
            if not self._policy.has_permission(role, perm):
                await self._record(
                    actor=role,
                    details={"tool": tool_name, "required": perm, "have": "none"},
                    result="denied",
                )
                return {
                    "allowed": False,
                    "reason": f"Role '{role}' lacks permission '{perm}'",
                    "tool": tool_name,
                }

        # Check every referenced file scope. Copy/move operations must validate
        # the source as a read and the destination as a write independently.
        source = str(params.get("source") or "")
        destination = str(params.get("destination") or "")
        path = str(params.get("path") or "")
        if source and not self._policy.is_file_read_allowed(source):
            await self._record(
                actor=role,
                details={"tool": tool_name, "path": source, "action": "read"},
                result="denied",
            )
            return {
                "allowed": False,
                "reason": f"Read not allowed for path: {source}",
                "tool": tool_name,
            }
        if destination and not self._policy.is_file_write_allowed(destination):
            await self._record(
                actor=role,
                details={"tool": tool_name, "path": destination, "action": "write"},
                result="denied",
            )
            return {
                "allowed": False,
                "reason": f"Write not allowed for path: {destination}",
                "tool": tool_name,
            }
        if path:
            is_write = bool(
                {"read_write", "write_only", "destructive"}.intersection(tool_permissions)
                or any(key in params for key in ("content", "data"))
            )
            allowed = (
                self._policy.is_file_write_allowed(path)
                if is_write
                else self._policy.is_file_read_allowed(path)
            )
            if not allowed:
                action = "write" if is_write else "read"
                await self._record(
                    actor=role,
                    details={"tool": tool_name, "path": path, "action": action},
                    result="denied",
                )
                return {
                    "allowed": False,
                    "reason": f"{action.title()} not allowed for path: {path}",
                    "tool": tool_name,
                }

        command = str(params.get("command") or "")
        if command and not self._policy.is_command_allowed(command):
            await self._record(
                actor=role,
                details={"tool": tool_name, "command": command},
                result="denied",
            )
            return {
                "allowed": False,
                "reason": "Command is not permitted by the execution allowlist",
                "tool": tool_name,
            }

        # Check destructive action confirmation
        is_destructive = "destructive" in tool_permissions
        if self._policy.requires_confirmation(tool_name) or (is_destructive and self._policy._require_confirmation_destructive):
            if not params.get("_confirmed"):
                return {
                    "allowed": False,
                    "reason": f"Action '{tool_name}' requires confirmation. Set _confirmed=True.",
                    "tool": tool_name,
                    "requires_confirmation": True,
                }

        # All checks passed
        await self._record(
            actor=role,
            details={"tool": tool_name, "role": role, "permissions": tool_permissions},
            result="allowed",
        )

        return {
            "allowed": True,
            "reason": "All permission checks passed",
            "tool": tool_name,
        }

    async def check_command_permission(
        self,
        role: str,
        command: str,
    ) -> Dict[str, Any]:
        """Check if a command is allowed for a role."""
        if not self._policy.is_command_allowed(command):
            await self._record(
                actor=role,
                details={"command": command, "allowed_commands": self._policy._command_allowlist},
                result="denied",
            )
            return {
                "allowed": False,
                "reason": f"Command '{command}' not in allowlist",
            }
        return {"allowed": True, "reason": "Command allowed"}

    async def check_network_permission(
        self,
        role: str,
        domain: str,
    ) -> Dict[str, Any]:
        """Check if a network domain is allowed."""
        if not self._policy.is_network_allowed(domain):
            await self._record(
                actor=role,
                details={"domain": domain, "allowed": self._policy._network_allow_domains},
                result="denied",
            )
            return {
                "allowed": False,
                "reason": f"Network access to '{domain}' denied",
            }
        return {"allowed": True, "reason": "Network access allowed"}

    def get_policy(self) -> Dict[str, Any]:
        """Get current policy configuration."""
        return self._policy.to_dict()


def _path_is_allowed(path: str, roots: List[str], deny_patterns: List[str]) -> bool:
    """Apply deny globs and root boundaries to a normalized filesystem path."""
    try:
        target = Path(path).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return False

    candidates = {
        str(path).replace("\\", "/").casefold(),
        target.as_posix().casefold(),
    }
    for pattern in deny_patterns:
        normalized_pattern = str(pattern).replace("\\", "/").casefold()
        if any(fnmatchcase(candidate, normalized_pattern) for candidate in candidates):
            return False

    if not roots:
        return True

    for root in roots:
        try:
            allowed_root = Path(root).expanduser().resolve(strict=False)
            if target == allowed_root or allowed_root in target.parents:
                return True
        except (OSError, RuntimeError, ValueError):
            continue
    return False


def _command_is_allowed(command: str, allowlist: List[str]) -> bool:
    """Check the parsed executable name against a case-insensitive allowlist."""
    if not allowlist:
        return True
    try:
        if os.name == "nt":
            stripped = command.strip()
            if stripped.startswith('"') and '"' in stripped[1:]:
                executable = stripped[1:stripped.index('"', 1)]
            else:
                executable = stripped.split(maxsplit=1)[0] if stripped else ""
            argv = [executable] if executable else []
        else:
            argv = shlex.split(command)
    except ValueError:
        return False
    if not argv:
        return False
    command_name = Path(argv[0]).stem.casefold()
    return command_name in {item.casefold() for item in allowlist}


def _normalize_host(value: str) -> str:
    """Extract a case-insensitive hostname from a hostname or URL value."""
    candidate = str(value).strip()
    if not candidate:
        return ""
    parsed = urlsplit(candidate if "://" in candidate else f"//{candidate}")
    return (parsed.hostname or "").rstrip(".").casefold()


def _domain_matches(host: str, rule: str) -> bool:
    """Match an exact host or a true subdomain, never a string prefix."""
    allowed = _normalize_host(rule)
    return bool(allowed and (host == allowed or host.endswith(f".{allowed}")))
