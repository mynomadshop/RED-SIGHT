"""
RedSight - High-Performance Local AI Intelligence Platform
Hybrid Search Engine

Combines dense vector search (Qdrant) with metadata filtering from
SQLite metadata. Implements the retrieval pipeline from blueprint §4:

1. Query planner — classify question type
2. Parallel retrieval — search relevant collections
3. Reranking — cross-encoder on candidate set
4. Context budgeter — allocate tokens by evidence value
5. Citation pack — provenance for UI display
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from app.retrieval.qdrant_client import QdrantClientWrapper
from app.retrieval.metadata_db import MetadataDB

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """A single search result with provenance."""
    chunk_id: str
    content: str
    collection: str
    source_path: str
    project: str
    page_number: Optional[int] = None
    heading: Optional[str] = None
    score: float = 0.0
    offset_start: Optional[int] = None
    offset_end: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "content": self.content,
            "collection": self.collection,
            "source_path": self.source_path,
            "project": self.project,
            "page_number": self.page_number,
            "heading": self.heading,
            "score": round(self.score, 4),
            "offset_start": self.offset_start,
            "offset_end": self.offset_end,
        }


@dataclass
class CitationPack:
    """Provenance information for retrieved results."""
    references: List[Dict[str, Any]] = field(default_factory=list)
    chunk_ids: List[str] = field(default_factory=list)
    relevance_scores: List[float] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "references": self.references,
            "chunk_ids": self.chunk_ids,
            "relevance_scores": [round(s, 4) for s in self.relevance_scores],
        }


class QueryClassifier:
    """Classify queries to determine which collections to search."""

    # Keywords mapped to collections
    COLLECTION_KEYWORDS = {
        "project_code": ["function", "class", "method", "api", "endpoint", "schema",
                         "code", "import", "def ", "async def", "class ", "TODO", "FIXME"],
        "project_decisions": ["decision", "why", "rationale", "tradeoff", "alternatives",
                              "rejected", "chosen", "architecture decision"],
        "skills_index": ["skill", "procedure", "workflow", "recipe", "how to", "steps"],
        "knowledge_docs": ["document", "report", "manual", "specification", "policy"],
        "episodic_memory": ["task", "session", "outcome", "completed", "previous work"],
        "tool_catalog": ["tool", "api", "endpoint", "integration", "webhook"],
        "eval_corpus": ["test", "benchmark", "evaluation", "golden", "expected"],
    }

    @classmethod
    def classify(cls, query: str) -> Dict[str, float]:
        """
        Classify query and return collection weights.

        Returns dict of {collection: weight} sorted by relevance.
        """
        query_lower = query.lower()
        weights: Dict[str, float] = {}

        for collection, keywords in cls.COLLECTION_KEYWORDS.items():
            score = 0.0
            for kw in keywords:
                if kw in query_lower:
                    score += 1.0
            if score > 0:
                weights[collection] = score

        # Default: search all if no specific keywords match
        if not weights:
            weights = {c: 1.0 for c in ["knowledge_docs", "project_code", "project_decisions"]}

        return weights


class HybridSearchEngine:
    """
    Hybrid search engine combining Qdrant vector search with SQLite metadata.

    Implements the full retrieval pipeline:
    - Query classification
    - Parallel collection search
    - Reranking (optional cross-encoder)
    - Context budgeting
    - Citation pack assembly
    """

    def __init__(
        self,
        qdrant: QdrantClientWrapper,
        metadata_db: MetadataDB,
        embedding_model: Optional[Any] = None,
        reranker_model: Optional[Any] = None,
    ):
        self._qdrant = qdrant
        self._metadata = metadata_db
        self._embedding_model = embedding_model
        self._reranker_model = reranker_model

    async def search(
        self,
        query: str,
        collections: Optional[List[str]] = None,
        top_k: int = 40,
        filters: Optional[Dict[str, Any]] = None,
        hybrid: bool = True,
        rerank: bool = True,
    ) -> Tuple[List[SearchResult], CitationPack]:
        """
        Main search entry point.

        Returns (results, citation_pack).
        """
        if not query.strip():
            return [], CitationPack()

        # Step 1: Query classification
        collection_weights = QueryClassifier.classify(query)
        search_collections = collections or list(collection_weights.keys())

        # Step 2: Generate query embedding
        query_vector = await self._embed_query(query)
        if not query_vector:
            logger.warning("Failed to generate query embedding")
            return [], CitationPack()

        # Step 3: Parallel search across collections
        all_results: Dict[str, SearchResult] = {}
        search_start = time.time()

        for coll in search_collections:
            try:
                coll_results = await self._search_collection(
                    query_vector, coll, top_k=top_k, filters=filters
                )
                for r in coll_results:
                    all_results[r.chunk_id] = r
            except Exception as e:
                logger.warning(f"Collection '{coll}' search failed: {e}")

        search_time = time.time() - search_start
        logger.info(f"Search completed in {search_time:.2f}s across {len(search_collections)} collections, {len(all_results)} results")

        # Step 4: Reranking
        results_list = list(all_results.values())
        if rerank and self._reranker_model and len(results_list) > 5:
            results_list = await self._rerank_results(query, results_list, top_k=20)

        # Step 5: Context budgeting
        final_results = self._context_budget(results_list, top_k=top_k)

        # Step 6: Build citation pack
        citation = CitationPack(
            chunk_ids=[r.chunk_id for r in final_results],
            relevance_scores=[r.score for r in final_results],
            references=[
                {
                    "source_path": r.source_path,
                    "project": r.project,
                    "collection": r.collection,
                    "page_number": r.page_number,
                    "heading": r.heading,
                    "score": r.score,
                }
                for r in final_results
            ],
        )

        return final_results, citation

    async def _embed_query(self, query: str) -> Optional[List[float]]:
        """Generate embedding for a query string."""
        if not self._embedding_model:
            logger.warning("No embedding model configured")
            return None
        try:
            if hasattr(self._embedding_model, "encode"):
                # sentence-transformers style
                import numpy as np
                embedding = self._embedding_model.encode(query, normalize_embeddings=True)
                if isinstance(embedding, np.ndarray):
                    return embedding.tolist()
                return embedding.tolist() if hasattr(embedding, 'tolist') else list(embedding)
            elif hasattr(self._embedding_model, "embed"):
                # OpenAI/LM Studio style
                result = self._embedding_model.embed([query])
                return result[0] if result else None
            else:
                logger.warning("Unknown embedding model interface")
                return None
        except Exception as e:
            logger.error(f"Embedding failed: {e}")
            return None

    async def _search_collection(
        self,
        query_vector: List[float],
        collection: str,
        top_k: int = 20,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        """Search a single collection in Qdrant."""
        results = await self._qdrant.search(
            query_vector=query_vector,
            collection=collection,
            top_k=top_k,
            filters=filters,
        )

        search_results = []
        for r in results:
            payload = r.get("payload", {})
            search_results.append(SearchResult(
                chunk_id=payload.get("chunk_id", r["id"]),
                content=payload.get("content", ""),
                collection=collection,
                source_path=payload.get("source_path", ""),
                project=payload.get("project", ""),
                page_number=payload.get("page_number"),
                heading=payload.get("heading"),
                score=r.get("score", 0.0),
                offset_start=payload.get("offset_start"),
                offset_end=payload.get("offset_end"),
            ))

        return search_results

    async def _rerank_results(
        self,
        query: str,
        results: List[SearchResult],
        top_k: int = 20,
    ) -> List[SearchResult]:
        """Rerank results using cross-encoder/reranker model."""
        if not self._reranker_model:
            return results

        try:
            # Prepare documents for reranking
            documents = [r.content for r in results]

            # Call reranker (assuming cross-encoder interface)
            if hasattr(self._reranker_model, "encode"):
                scores = self._reranker_model.encode(
                    [[query, doc] for doc in documents],
                    convert_to_numpy=True,
                )
                if hasattr(scores, 'tolist'):
                    scores = scores.tolist()

                # Attach scores and sort
                for r, s in zip(results, scores):
                    r.score = float(s)

            results.sort(key=lambda x: x.score, reverse=True)
            logger.info(f"Reranked {len(results)} results, top score: {results[0].score:.4f}")
            return results[:top_k]

        except Exception as e:
            logger.warning(f"Reranking failed, using original scores: {e}")
            return results

    def _context_budget(
        self,
        results: List[SearchResult],
        top_k: int = 8,
    ) -> List[SearchResult]:
        """
        Allocate context budget by evidence value, diversity, and task type.

        Uses a simple heuristic:
        - Top-k by score
        - Deduplicate by source
        - Ensure diversity across collections
        """
        if len(results) <= top_k:
            return results

        # Deduplicate by source_path (keep highest score per source)
        seen_sources: Dict[str, SearchResult] = {}
        for r in results:
            if r.source_path not in seen_sources or r.score > seen_sources[r.source_path].score:
                seen_sources[r.source_path] = r

        # Ensure collection diversity
        collection_counts: Dict[str, int] = {}
        final = []
        for r in results:
            if len(final) >= top_k:
                break
            coll = r.collection
            max_per_coll = max(1, top_k // len(collection_counts) if collection_counts else top_k)
            if collection_counts.get(coll, 0) < max_per_coll:
                final.append(r)
                collection_counts[coll] = collection_counts.get(coll, 0) + 1

        return final[:top_k]

    async def search_by_id(self, chunk_id: str) -> Optional[SearchResult]:
        """Retrieve a specific chunk by ID from metadata DB."""
        chunk_data = await self._metadata.get_chunk_by_id(chunk_id)
        if not chunk_data:
            return None

        # Get source file info
        # We'd need to query the source file, but for now return chunk data
        return SearchResult(
            chunk_id=chunk_data["chunk_id"],
            content=chunk_data["content"],
            collection=chunk_data["collection"],
            source_path="",  # Would need source lookup
            project="",
            page_number=chunk_data.get("page_number"),
            heading=chunk_data.get("heading"),
            offset_start=chunk_data.get("offset_start"),
            offset_end=chunk_data.get("offset_end"),
        )

    async def get_collection_stats(self, collection: str) -> Dict[str, Any]:
        """Get combined stats from Qdrant and SQLite."""
        qdrant_stats = await self._qdrant.get_collection_stats(collection)
        sqlite_stats = await self._metadata.get_collection_stats(collection)

        return {
            **qdrant_stats,
            "sqlite_chunks": sqlite_stats.get("total_chunks", 0),
            "versions": sqlite_stats.get("versions", []),
        }

    async def list_collections(self) -> List[str]:
        """List all available collections."""
        return await self._qdrant.list_collections()
