"""
RedSight - High-Performance Local AI Intelligence Platform
Skill Manifest

Defines the structure of a skill with identity, triggers, interface,
execution, permissions, quality, and knowledge links.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class SkillManifest:
    """
    Skill Manifest - Defines a skill's structure and metadata.
    
    Fields:
    - Identity: skill_id, name, semantic description, version, owner/source project
    - Trigger model: Example prompts, supported intents, required context, confidence threshold
    - Interface: Typed inputs/outputs using Pydantic/JSON Schema
    - Execution: Python entry point, timeout, resource class, allowed tools, GPU need
    - Permissions: Filesystem scopes, network scopes, secret scopes, write/delete capability
    - Quality: Tests, success rate, last validation time, known limitations
    - Knowledge links: Related project artifacts, docs, examples and prior successful trajectories
    """
    
    # Identity
    skill_id: str
    name: str
    description: str
    version: str = "1.0.0"
    owner: str = "system"
    source_project: Optional[str] = None
    
    # Trigger model
    trigger_prompts: List[str] = field(default_factory=list)
    supported_intents: List[str] = field(default_factory=list)
    required_context: List[str] = field(default_factory=list)
    confidence_threshold: float = 0.7
    
    # Interface
    input_schema: Dict[str, Any] = field(default_factory=dict)
    output_schema: Dict[str, Any] = field(default_factory=dict)
    
    # Execution
    entry_point: str = ""
    timeout_seconds: int = 300
    resource_class: str = "normal"  # low, normal, high, critical
    allowed_tools: List[str] = field(default_factory=list)
    needs_gpu: bool = False
    
    # Permissions
    filesystem_scopes: List[str] = field(default_factory=list)
    network_scopes: List[str] = field(default_factory=list)
    secret_scopes: List[str] = field(default_factory=list)
    write_capability: bool = False
    delete_capability: bool = False
    
    # Quality
    test_paths: List[str] = field(default_factory=list)
    success_rate: float = 0.0
    last_validated: Optional[float] = None
    known_limitations: List[str] = field(default_factory=list)
    
    # Knowledge links
    related_artifacts: List[str] = field(default_factory=list)
    related_docs: List[str] = field(default_factory=list)
    example_outputs: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert manifest to dictionary."""
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "owner": self.owner,
            "source_project": self.source_project,
            "trigger_prompts": self.trigger_prompts,
            "supported_intents": self.supported_intents,
            "required_context": self.required_context,
            "confidence_threshold": self.confidence_threshold,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "entry_point": self.entry_point,
            "timeout_seconds": self.timeout_seconds,
            "resource_class": self.resource_class,
            "allowed_tools": self.allowed_tools,
            "needs_gpu": self.needs_gpu,
            "filesystem_scopes": self.filesystem_scopes,
            "network_scopes": self.network_scopes,
            "secret_scopes": self.secret_scopes,
            "write_capability": self.write_capability,
            "delete_capability": self.delete_capability,
            "test_paths": self.test_paths,
            "success_rate": self.success_rate,
            "last_validated": self.last_validated,
            "known_limitations": self.known_limitations,
            "related_artifacts": self.related_artifacts,
            "related_docs": self.related_docs,
            "example_outputs": self.example_outputs,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SkillManifest":
        """Create a manifest from a dictionary."""
        return cls(
            skill_id=data.get("skill_id", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            version=data.get("version", "1.0.0"),
            owner=data.get("owner", "system"),
            source_project=data.get("source_project"),
            trigger_prompts=data.get("trigger_prompts", []),
            supported_intents=data.get("supported_intents", []),
            required_context=data.get("required_context", []),
            confidence_threshold=data.get("confidence_threshold", 0.7),
            input_schema=data.get("input_schema", {}),
            output_schema=data.get("output_schema", {}),
            entry_point=data.get("entry_point", ""),
            timeout_seconds=data.get("timeout_seconds", 300),
            resource_class=data.get("resource_class", "normal"),
            allowed_tools=data.get("allowed_tools", []),
            needs_gpu=data.get("needs_gpu", False),
            filesystem_scopes=data.get("filesystem_scopes", []),
            network_scopes=data.get("network_scopes", []),
            secret_scopes=data.get("secret_scopes", []),
            write_capability=data.get("write_capability", False),
            delete_capability=data.get("delete_capability", False),
            test_paths=data.get("test_paths", []),
            success_rate=data.get("success_rate", 0.0),
            last_validated=data.get("last_validated"),
            known_limitations=data.get("known_limitations", []),
            related_artifacts=data.get("related_artifacts", []),
            related_docs=data.get("related_docs", []),
            example_outputs=data.get("example_outputs", []),
        )
    
    @classmethod
    def from_file(cls, path: str) -> "SkillManifest":
        """Load a manifest from a JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)
    
    def to_file(self, path: str) -> None:
        """Save manifest to a JSON file."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)
    
    def validate(self) -> tuple[bool, List[str]]:
        """
        Validate the manifest.
        
        Returns (is_valid, list_of_errors).
        """
        errors = []
        
        if not self.skill_id:
            errors.append("skill_id is required")
        
        if not self.name:
            errors.append("name is required")
        
        if not self.description:
            errors.append("description is required")
        
        if not self.version:
            errors.append("version is required")
        
        if not self.entry_point:
            errors.append("entry_point is required")
        
        if self.confidence_threshold < 0 or self.confidence_threshold > 1:
            errors.append("confidence_threshold must be between 0 and 1")
        
        if self.timeout_seconds <= 0:
            errors.append("timeout_seconds must be positive")
        
        return (len(errors) == 0, errors)
