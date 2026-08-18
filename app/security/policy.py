"""
RedSight - High-Performance Local AI Intelligence Platform
Security Policy

Defines file scopes, command policy, network scopes, and safety boundaries.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

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
    file_deny_patterns: List[str] = field(default_factory=lambda: [
        "*/.env",
        "*/secrets/*",
        "*/credentials/*",
        "*/.ssh/*",
        "*/.aws/*",
    ])
    
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
        # Check deny patterns first
        for pattern in self.file_deny_patterns:
            if self._matches_pattern(path, pattern):
                return False
        
        # Check read roots
        if not self.file_read_roots:
            return True  # No restrictions
        
        return any(path.startswith(root) for root in self.file_read_roots)
    
    def is_file_write_allowed(self, path: str) -> bool:
        """Check if a file path is allowed for writing."""
        # Check deny patterns first
        for pattern in self.file_deny_patterns:
            if self._matches_pattern(path, pattern):
                return False
        
        # Check write roots
        if not self.file_write_roots:
            return True  # No restrictions
        
        return any(path.startswith(root) for root in self.file_write_roots)
    
    def is_command_allowed(self, command: str) -> bool:
        """Check if a command is allowed."""
        if not self.command_allowlist:
            return True  # No restrictions
        
        command_name = command.split()[0] if command else ""
        return command_name in self.command_allowlist
    
    def is_network_allowed(self, domain: str) -> bool:
        """Check if a network domain is allowed."""
        if self.block_outbound:
            return False
        
        # Check allowlist
        if self.network_allow_domains:
            return any(domain.startswith(allowed) for allowed in self.network_allow_domains)
        
        # Check denylist
        if self.network_deny_domains:
            return not any(domain.startswith(denied) for denied in self.network_deny_domains)
        
        return True  # Default allow
    
    def _matches_pattern(self, path: str, pattern: str) -> bool:
        """Simple pattern matching for file paths."""
        if "*" in pattern:
            # Simple glob matching
            import fnmatch
            return fnmatch.fnmatch(path, pattern)
        return path == pattern
    
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
