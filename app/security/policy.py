"""
RedSight - High-Performance Local AI Intelligence Platform
Security Policy

Defines file scopes, command policy, network scopes, and safety boundaries.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.security.permissions import (
    DEFAULT_FILE_DENY_PATTERNS,
    _command_is_allowed,
    _domain_matches,
    _normalize_host,
    _path_is_allowed,
)

logger = logging.getLogger(__name__)


@dataclass
class SecurityPolicy:
    """
    Security Policy - Defines safety boundaries for agent execution.
    
    Controls:
    - File scopes (read/write roots per agent/skill)
    - Command policy (allowlisted executables, timeouts)
    - Network scopes (per-provider/domain rules)
    - Destructive actions (require confirmation)
    - Prompt-injection defense
    """
    
    # File scopes
    file_read_roots: List[str] = field(default_factory=list)
    file_write_roots: List[str] = field(default_factory=list)
    file_deny_patterns: List[str] = field(
        default_factory=lambda: list(DEFAULT_FILE_DENY_PATTERNS)
    )
    
    # Command policy
    command_allowlist: List[str] = field(default_factory=lambda: [
        "python",
        "pip",
        "git",
        "ls",
        "cat",
        "grep",
    ])
    command_timeout_seconds: int = 60
    sanitize_environment: bool = True
    
    # Network scopes
    network_allow_domains: List[str] = field(default_factory=lambda: [
        "127.0.0.1",
        "localhost",
    ])
    network_deny_domains: List[str] = field(default_factory=list)
    block_outbound: bool = False
    
    # Destructive actions
    require_confirmation_destructive: bool = True
    allowed_destructive_actions: List[str] = field(default_factory=lambda: [
        "delete",
        "overwrite",
        "send",
        "publish",
    ])
    
    # Prompt injection defense
    treat_retrieved_as_untrusted: bool = True
    tool_permissions_from_policy: bool = True
    
    def is_file_read_allowed(self, path: str) -> bool:
        """Check if a file path is allowed for reading."""
        return _path_is_allowed(path, self.file_read_roots, self.file_deny_patterns)
    
    def is_file_write_allowed(self, path: str) -> bool:
        """Check if a file path is allowed for writing."""
        return _path_is_allowed(path, self.file_write_roots, self.file_deny_patterns)
    
    def is_command_allowed(self, command: str) -> bool:
        """Check if a command is allowed."""
        return _command_is_allowed(command, self.command_allowlist)
    
    def is_network_allowed(self, domain: str) -> bool:
        """Check if a network domain is allowed."""
        if self.block_outbound:
            return False
        host = _normalize_host(domain)
        if not host:
            return False
        if self.network_deny_domains and any(
            _domain_matches(host, denied) for denied in self.network_deny_domains
        ):
            return False
        if self.network_allow_domains:
            return any(_domain_matches(host, allowed) for allowed in self.network_allow_domains)
        return True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert policy to dictionary."""
        return {
            "file_read_roots": self.file_read_roots,
            "file_write_roots": self.file_write_roots,
            "file_deny_patterns": self.file_deny_patterns,
            "command_allowlist": self.command_allowlist,
            "command_timeout_seconds": self.command_timeout_seconds,
            "sanitize_environment": self.sanitize_environment,
            "network_allow_domains": self.network_allow_domains,
            "network_deny_domains": self.network_deny_domains,
            "block_outbound": self.block_outbound,
            "require_confirmation_destructive": self.require_confirmation_destructive,
            "allowed_destructive_actions": self.allowed_destructive_actions,
            "treat_retrieved_as_untrusted": self.treat_retrieved_as_untrusted,
            "tool_permissions_from_policy": self.tool_permissions_from_policy,
        }
