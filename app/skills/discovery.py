"""
RedSight - High-Performance Local AI Intelligence Platform
Semantic Skill Discovery

Uses embedding models to find relevant skills by natural language query.
Falls back to keyword search if no embedding model is available.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from app.skills.manifest import SkillManifest

logger = logging.getLogger(__name__)


class SemanticSkillDiscovery:
    """
    Semantic Skill Discovery - Find skills by natural language query.

    Uses embedding similarity when available, falls back to keyword
    matching. Maintains a local index of skill descriptions.
    """

    def __init__(self):
        self._skills: Dict[str, SkillManifest] = {}
        self._embeddings: Dict[str, List[float]] = {}
        self._embedding_model = None

    def set_embedding_model(self, model) -> None:
        """Set the embedding model for semantic search."""
        self._embedding_model = model
        logger.info("Semantic skill discovery: embedding model set")

    def register_skill(self, manifest: SkillManifest) -> None:
        """Register a skill for discovery."""
        self._skills[manifest.skill_id] = manifest
        self._index_skill(manifest)
        logger.info(f"Skill indexed for discovery: {manifest.skill_id}")

    def unregister_skill(self, skill_id: str) -> None:
        """Remove a skill from discovery."""
        if skill_id in self._skills:
            del self._skills[skill_id]
            self._embeddings.pop(skill_id, None)

    def list_all(self) -> List[SkillManifest]:
        """List all registered skills."""
        return list(self._skills.values())

    def search(self, query: str, limit: int = 10) -> List[Tuple[SkillManifest, float]]:
        """
        Search for relevant skills by query.

        Returns list of (skill, score) tuples, sorted by relevance.
        Uses semantic search if embedding model is available,
        otherwise falls back to keyword matching.
        """
        if self._embedding_model and self._embeddings:
            return self._semantic_search(query, limit)
        else:
            return self._keyword_search(query, limit)

    def _keyword_search(self, query: str, limit: int = 10) -> List[Tuple[SkillManifest, float]]:
        """Keyword-based fallback search."""
        query_lower = query.lower()
        query_terms = set(query_lower.split())
        results = []

        for manifest in self._skills.values():
            text = f"{manifest.name} {manifest.description} {' '.join(manifest.trigger_prompts)}".lower()
            score = sum(1 for term in query_terms if term in text)
            if score > 0:
                results.append((manifest, score))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:limit]

    def _semantic_search(self, query: str, limit: int = 10) -> List[Tuple[SkillManifest, float]]:
        """Semantic search using embeddings."""
        import asyncio
        import numpy as np

        try:
            query_embedding = asyncio.run(self._embedding_model.embed([query]))[0]
        except Exception as e:
            logger.warning(f"Embedding failed, falling back to keyword search: {e}")
            return self._keyword_search(query, limit)

        results = []
        query_vec = np.array(query_embedding, dtype=np.float32)

        for skill_id, skill_emb in self._embeddings.items():
            skill_vec = np.array(skill_emb, dtype=np.float32)
            # Cosine similarity
            norm_q = np.linalg.norm(query_vec)
            norm_s = np.linalg.norm(skill_vec)
            if norm_q > 0 and norm_s > 0:
                similarity = float(np.dot(query_vec, skill_vec) / (norm_q * norm_s))
                results.append((self._skills[skill_id], similarity))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:limit]

    def _index_skill(self, manifest: SkillManifest) -> None:
        """Index a skill for semantic search."""
        # Build description text for embedding
        desc = f"{manifest.name}: {manifest.description}"
        if manifest.trigger_prompts:
            desc += " " + " ".join(manifest.trigger_prompts)

        if self._embedding_model:
            import asyncio
            try:
                embedding = asyncio.run(self._embedding_model.embed([desc]))[0]
                self._embeddings[manifest.skill_id] = embedding
            except Exception as e:
                logger.warning(f"Failed to embed skill {manifest.skill_id}: {e}")
        else:
            # Store description for keyword search
            self._embeddings[manifest.skill_id] = []

    def get_skill(self, skill_id: str) -> Optional[SkillManifest]:
        """Get a skill by ID."""
        return self._skills.get(skill_id)

    def get_stats(self) -> Dict[str, Any]:
        """Get discovery statistics."""
        return {
            "total_skills": len(self._skills),
            "skills_with_embeddings": sum(
                1 for emb in self._embeddings.values() if emb
            ),
            "has_embedding_model": self._embedding_model is not None,
        }
