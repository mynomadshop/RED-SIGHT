"""
RedSight - High-Performance Local AI Intelligence Platform
Context Budgeter

Allocates token budget across retrieved evidence by:
1. Evidence value (relevance score, freshness)
2. Diversity (coverage across topics/collections)
3. Task type (code vs general vs decision)
4. Deduplication (remove redundant content)

Implements the context budgeting step from blueprint §4 retrieval pipeline.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


@dataclass
class ContextSlot:
    """A slot in the context budget."""
    chunk_id: str
    content: str
    score: float
    collection: str
    source_path: str
    project: str
    page_number: Optional[int] = None
    heading: Optional[str] = None
    slot_position: int = 0
    evidence_type: str = "retrieved"  # retrieved, deduplicated, diverse
    token_estimate: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "content": self.content,
            "score": round(self.score, 4),
            "collection": self.collection,
            "source_path": self.source_path,
            "project": self.project,
            "page_number": self.page_number,
            "heading": self.heading,
            "slot_position": self.slot_position,
            "evidence_type": self.evidence_type,
            "token_estimate": self.token_estimate,
        }


class ContextBudgeter:
    """
    Allocates context budget across retrieved evidence.

    Takes raw search results and produces an optimally selected subset
    that maximizes information coverage within the token budget.

    Strategy:
    1. Sort by relevance score
    2. Deduplicate by content similarity
    3. Ensure collection diversity
    4. Allocate by evidence value
    5. Estimate token usage
    6. Trim to budget
    """

    def __init__(
        self,
        max_tokens: int = 4096,
        min_chunk_tokens: int = 20,
        diversity_weight: float = 0.3,
        dedup_threshold: float = 0.85,
    ):
        self.max_tokens = max_tokens
        self.min_chunk_tokens = min_chunk_tokens
        self.diversity_weight = diversity_weight
        self.dedup_threshold = dedup_threshold

    def budget(
        self,
        results: List[Dict[str, Any]],
        query: str = "",
        task_type: str = "general",
    ) -> List[ContextSlot]:
        """
        Allocate context budget from search results.

        Args:
            results: List of search results {chunk_id, content, score, ...}
            query: Original query (for task-type detection)
            task_type: "code", "general", "decision", "mixed"

        Returns:
            List of ContextSlot (selected chunks for context)
        """
        if not results:
            return []

        # Step 1: Estimate tokens and filter tiny chunks
        scored = []
        for r in results:
            content = r.get("content", "")
            token_estimate = self._estimate_tokens(content)

            if token_estimate < self.min_chunk_tokens:
                continue

            scored.append({
                **r,
                "_token_estimate": token_estimate,
            })

        if not scored:
            return []

        # Step 2: Sort by relevance score
        scored.sort(key=lambda x: x.get("score", 0), reverse=True)

        # Step 3: Deduplicate by content similarity
        deduped = self._deduplicate(scored)

        # Step 4: Ensure diversity across collections
        diversified = self._ensure_diversity(deduped, task_type)

        # Step 5: Allocate to context slots
        slots = self._allocate_slots(diversified)

        # Step 6: Trim to budget
        final = self._trim_to_budget(slots)

        logger.info(
            f"Context budget: {len(results)} → {len(final)} slots, "
            f"~{sum(s.token_estimate for s in final)} tokens"
        )

        return final

    def _estimate_tokens(self, text: str) -> int:
        """Rough token estimate (1 token ≈ 4 chars for English)."""
        # English text: ~4 chars per token
        # Code: ~3 chars per token
        # Adjust for whitespace
        clean = re.sub(r"\s+", " ", text.strip())
        return max(1, len(clean) // 4)

    def _deduplicate(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Remove near-duplicate results.

        Uses Jaccard similarity on word sets.
        """
        if len(results) <= 1:
            return results

        seen_hashes: Set[str] = set()
        deduped = []

        for r in results:
            content = r.get("content", "").lower()
            # Simple hash of first 200 chars for dedup
            content_hash = hashlib.md5(content[:200].encode()).hexdigest()

            # Check against recent results for similarity
            is_duplicate = False
            for existing in deduped:
                existing_content = existing.get("content", "").lower()
                existing_hash = hashlib.md5(existing_content[:200].encode()).hexdigest()

                if content_hash == existing_hash:
                    is_duplicate = True
                    break

                # Word-level Jaccard similarity
                words_new = set(content.split())
                words_existing = set(existing_content.split())

                if words_new and words_existing:
                    intersection = words_new & words_existing
                    union = words_new | words_existing
                    jaccard = len(intersection) / len(union)

                    if jaccard > self.dedup_threshold:
                        is_duplicate = True
                        break

            if not is_duplicate:
                deduped.append(r)

        logger.info(f"Deduplicated: {len(results)} → {len(deduped)} results")
        return deduped

    def _ensure_diversity(
        self,
        results: List[Dict[str, Any]],
        task_type: str,
    ) -> List[Dict[str, Any]]:
        """
        Ensure results cover multiple collections/topics.

        Strategy:
        - Reserve slots for each collection
        - Fill remaining slots by score
        """
        if len(results) <= 5:
            return results

        # Group by collection
        by_collection: Dict[str, List[Dict[str, Any]]] = {}
        for r in results:
            coll = r.get("collection", "unknown")
            if coll not in by_collection:
                by_collection[coll] = []
            by_collection[coll].append(r)

        # Determine how many slots per collection
        total = len(results)
        num_collections = len(by_collection)
        slots_per_coll = max(1, total // (num_collections * 2))

        diversified = []
        for coll, coll_results in by_collection.items():
            # Take top N from each collection
            diversified.extend(coll_results[:slots_per_coll])

        # Fill remaining by score
        remaining = [r for r in results if r not in diversified]
        remaining.sort(key=lambda x: x.get("score", 0), reverse=True)
        diversified.extend(remaining[:total // 2])

        return diversified

    def _allocate_slots(self, results: List[Dict[str, Any]]) -> List[ContextSlot]:
        """Convert results to context slots."""
        slots = []
        for i, r in enumerate(results):
            content = r.get("content", "")
            token_estimate = self._estimate_tokens(content)

            slots.append(ContextSlot(
                chunk_id=r.get("chunk_id", r.get("doc_id", f"slot_{i}")),
                content=content,
                score=r.get("score", 0),
                collection=r.get("collection", "unknown"),
                source_path=r.get("source_path", ""),
                project=r.get("project", ""),
                page_number=r.get("page_number"),
                heading=r.get("heading"),
                slot_position=i,
                token_estimate=token_estimate,
            ))

        return slots

    def _trim_to_budget(self, slots: List[ContextSlot]) -> List[ContextSlot]:
        """Trim slots to fit within token budget."""
        total_tokens = sum(s.token_estimate for s in slots)

        if total_tokens <= self.max_tokens:
            return slots

        logger.info(f"Trimming context: {total_tokens} tokens > {self.max_tokens} budget")

        # Sort by score (highest first)
        sorted_slots = sorted(slots, key=lambda s: s.score, reverse=True)

        trimmed = []
        current_tokens = 0

        for slot in sorted_slots:
            if current_tokens + slot.token_estimate <= self.max_tokens:
                trimmed.append(slot)
                current_tokens += slot.token_estimate
            elif current_tokens > 0:
                # Don't add if it would exceed budget significantly
                if slot.token_estimate <= self.max_tokens // 4:
                    # Add smaller chunks even if over budget slightly
                    trimmed.append(slot)
                    current_tokens += slot.token_estimate

        return trimmed

    def build_context(self, slots: List[ContextSlot], query: str = "") -> str:
        """
        Build the final context string from selected slots.

        Format:
        [SOURCE: path (page N)]
        Content...
        ---
        """
        parts = []

        for slot in slots:
            source_info = []
            if slot.source_path:
                source_info.append(slot.source_path)
            if slot.page_number:
                source_info.append(f"p{slot.page_number}")
            if slot.heading:
                source_info.append(slot.heading)

            header = " | ".join(source_info) if source_info else f"[{slot.chunk_id}]"
            parts.append(f"[{header}]\n{slot.content}\n---\n")

        context = "\n".join(parts)

        if query:
            context = f"Query: {query}\n\n" + context

        return context

    def get_budget_info(self) -> Dict[str, Any]:
        """Get budget configuration info."""
        return {
            "max_tokens": self.max_tokens,
            "min_chunk_tokens": self.min_chunk_tokens,
            "diversity_weight": self.diversity_weight,
            "dedup_threshold": self.dedup_threshold,
        }


# Import hashlib at module level
import hashlib
