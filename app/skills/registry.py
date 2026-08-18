"""
RedSight - High-Performance Local AI Intelligence Platform
Skill Registry

Indexes skill descriptions for discovery but keeps executable code
versioned and testable. Controls which version executes and under
what permissions.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from app.skills.manifest import SkillManifest

logger = logging.getLogger(__name__)


class SkillRegistry:
    """
    Skill Registry - Manages skill manifests and execution.
    
    Semantic indexing helps choose a skill; the registry controls
    the actual code and permissions.
    """
    
    def __init__(self):
        self._skills: Dict[str, SkillManifest] = {}
        self._semantic_index: Dict[str, List[str]] = {}  # keyword -> skill_ids
    
    async def register(self, manifest: SkillManifest) -> str:
        """
        Register a skill.
        
        Returns skill_id.
        """
        # Validate manifest
        is_valid, errors = manifest.validate()
        if not is_valid:
            raise ValueError(f"Invalid skill manifest: {', '.join(errors)}")
        
        self._skills[manifest.skill_id] = manifest
        self._index_semantic(manifest)
        
        logger.info(f"Skill registered: {manifest.skill_id} ({manifest.name})")
        return manifest.skill_id
    
    async def unregister(self, skill_id: str) -> bool:
        """Unregister a skill."""
        if skill_id not in self._skills:
            return False
        
        manifest = self._skills.pop(skill_id)
        self._unindex_semantic(manifest)
        
        logger.info(f"Skill unregistered: {skill_id}")
        return True
    
    async def get(self, skill_id: str) -> Optional[SkillManifest]:
        """Get a skill by ID."""
        return self._skills.get(skill_id)
    
    async def list_all(self) -> List[SkillManifest]:
        """List all registered skills."""
        return list(self._skills.values())
    
    async def search(self, query: str, limit: int = 10) -> List[SkillManifest]:
        """
        Search skills by semantic similarity.
        
        Simple keyword-based search (replace with vector search in Phase 2).
        """
        query_lower = query.lower()
        results = []
        
        for manifest in self._skills.values():
            # Search in name, description, and trigger prompts
            text = f"{manifest.name} {manifest.description} {' '.join(manifest.trigger_prompts)}"
            if any(term in text.lower() for term in query_lower.split()):
                results.append(manifest)
        
        return results[:limit]
    
    async def execute(self, skill_id: str, inputs: Dict[str, Any],
                     permissions: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Execute a skill with given inputs.
        
        Checks permissions and executes the skill's entry point.
        """
        manifest = self._skills.get(skill_id)
        if not manifest:
            raise ValueError(f"Skill {skill_id} not found")
        
        # Check permissions
        if permissions:
            required = manifest.allowed_tools
            if not all(p in permissions for p in required):
                raise PermissionError(
                    f"Insufficient permissions for skill {skill_id}. "
                    f"Required: {required}, Have: {permissions}"
                )
        
        # TODO: Actually execute the skill
        # For now, return placeholder
        return {
            "skill_id": skill_id,
            "status": "simulated",
            "inputs": inputs,
            "output": {"result": "Skill execution simulated"},
        }
    
    async def validate_skill(self, skill_id: str) -> tuple[bool, List[str]]:
        """Validate a skill's manifest and tests."""
        manifest = self._skills.get(skill_id)
        if not manifest:
            return False, [f"Skill {skill_id} not found"]
        
        # Validate manifest
        is_valid, errors = manifest.validate()
        if not is_valid:
            return False, errors
        
        # TODO: Run tests
        # For now, return valid
        return True, []
    
    def _index_semantic(self, manifest: SkillManifest) -> None:
        """Add skill to semantic index."""
        keywords = self._extract_keywords(manifest)
        for keyword in keywords:
            if keyword not in self._semantic_index:
                self._semantic_index[keyword] = []
            if manifest.skill_id not in self._semantic_index[keyword]:
                self._semantic_index[keyword].append(manifest.skill_id)
    
    def _unindex_semantic(self, manifest: SkillManifest) -> None:
        """Remove skill from semantic index."""
        keywords = self._extract_keywords(manifest)
        for keyword in keywords:
            if keyword in self._semantic_index:
                self._semantic_index[keyword] = [
                    sid for sid in self._semantic_index[keyword]
                    if sid != manifest.skill_id
                ]
                if not self._semantic_index[keyword]:
                    del self._semantic_index[keyword]
    
    def _extract_keywords(self, manifest: SkillManifest) -> List[str]:
        """Extract keywords from a skill manifest."""
        keywords = []
        
        # From name and description
        text = f"{manifest.name} {manifest.description}".lower()
        keywords.extend(text.split())
        
        # From trigger prompts
        for prompt in manifest.trigger_prompts:
            keywords.extend(prompt.lower().split())
        
        # From supported intents
        keywords.extend(manifest.supported_intents)
        
        # Deduplicate and filter
        keywords = list(set(kw for kw in keywords if len(kw) > 2))
        return keywords
    
    async def get_skill_stats(self) -> Dict[str, Any]:
        """Get statistics about the skill registry."""
        return {
            "total_skills": len(self._skills),
            "indexed_keywords": len(self._semantic_index),
            "skills_by_owner": {},  # Would aggregate by owner
        }
