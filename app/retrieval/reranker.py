"""
RedSight - High-Performance Local AI Intelligence Platform
Cross-Encoder Reranker

Re-ranks retrieved candidates using a cross-encoder model for
higher-quality relevance scoring.

Supports:
- Local cross-encoder models (sentence-transformers)
- LM Studio / OpenAI-compatible API fallback
- Simple keyword fallback when no model available
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Default cross-encoder model
DEFAULT_RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


@dataclass
class RerankResult:
    """A single reranked result."""
    doc_id: str
    original_score: float
    rerank_score: float
    content: str
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "original_score": round(self.original_score, 4),
            "rerank_score": round(self.rerank_score, 4),
            "content": self.content,
            "metadata": self.metadata,
        }


class CrossEncoderReranker:
    """
    Cross-encoder reranker for improving retrieval quality.

    Takes a query and a list of candidate documents, then produces
    a joint relevance score for each (query, document) pair.

    Priority:
    1. Local cross-encoder model (sentence-transformers)
    2. LM Studio / OpenAI API
    3. Keyword-based fallback (TF-IDF similarity)
    """

    def __init__(
        self,
        model_name: str = DEFAULT_RERANKER_MODEL,
        lmstudio_url: Optional[str] = None,
        max_batch_size: int = 32,
    ):
        self._model_name = model_name
        self._lmstudio_url = lmstudio_url
        self._max_batch_size = max_batch_size
        self._model = None
        self._backend = None  # "local", "lmstudio", "keyword"

    async def load(self) -> bool:
        """Load the reranker model."""
        # Try 1: Local cross-encoder
        loaded = await self._load_local()
        if loaded:
            return True

        # Try 2: LM Studio API
        if self._lmstudio_url:
            loaded = await self._load_lmstudio()
            if loaded:
                return True

        # Fallback: keyword-based
        logger.info("No cross-encoder model available, using keyword fallback")
        self._backend = "keyword"
        return True  # Keyword fallback always succeeds

    async def _load_local(self) -> bool:
        """Load a local cross-encoder model."""
        try:
            from sentence_transformers import CrossEncoder

            logger.info(f"Loading cross-encoder model: {self._model_name}")
            self._model = CrossEncoder(self._model_name)
            self._backend = "local"
            logger.info(f"Loaded cross-encoder: {self._model_name}")
            return True

        except ImportError:
            logger.info("sentence-transformers not installed, skipping cross-encoder")
            return False
        except Exception as e:
            logger.warning(f"Failed to load cross-encoder: {e}")
            return False

    async def _load_lmstudio(self) -> bool:
        """Load reranker from LM Studio API."""
        try:
            import httpx

            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self._lmstudio_url}/models")
                resp.raise_for_status()

                models_data = resp.json()
                model_list = models_data.get("data", [])

                # Find a model suitable for reranking
                rerank_model = None
                for m in model_list:
                    mid = m.get("id", "")
                    if "rerank" in mid.lower() or "cross" in mid.lower():
                        rerank_model = mid
                        break

                if not rerank_model and model_list:
                    rerank_model = model_list[0].get("id", "")

                if not rerank_model:
                    return False

                self._model = {
                    "client": client,
                    "base_url": self._lmstudio_url,
                    "model_id": rerank_model,
                }
                self._backend = "lmstudio"
                logger.info(f"Using LM Studio reranker: {rerank_model}")
                return True

        except ImportError:
            return False
        except Exception as e:
            logger.warning(f"Failed to connect to LM Studio for reranking: {e}")
            return False

    async def rerank(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        top_k: Optional[int] = None,
    ) -> List[RerankResult]:
        """
        Re-rank candidates by relevance to query.

        Args:
            query: Search query
            candidates: List of {doc_id, score, content, metadata}
            top_k: Optional limit on results

        Returns:
            List of RerankResult sorted by rerank_score descending
        """
        if not candidates:
            return []

        if self._backend == "keyword":
            return self._rerank_keyword(query, candidates, top_k)

        # Batch process
        all_results = []
        for i in range(0, len(candidates), self._max_batch_size):
            batch = candidates[i : i + self._max_batch_size]
            batch_results = await self._rerank_batch(query, batch)
            all_results.extend(batch_results)

        # Sort by rerank score
        all_results.sort(key=lambda r: r.rerank_score, reverse=True)

        if top_k:
            all_results = all_results[:top_k]

        return all_results

    async def _rerank_batch(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
    ) -> List[RerankResult]:
        """Re-rank a batch of candidates."""
        if self._backend == "local":
            return await self._rerank_local(query, candidates)
        elif self._backend == "lmstudio":
            return await self._rerank_lmstudio(query, candidates)
        else:
            return self._rerank_keyword(query, candidates)

    async def _rerank_local(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
    ) -> List[RerankResult]:
        """Re-rank using local cross-encoder."""
        pairs = [(query, c.get("content", "")) for c in candidates]

        try:
            scores = self._model.predict(pairs, show_progress_bar=False)

            if hasattr(scores, "tolist"):
                scores = scores.tolist()
            elif hasattr(scores, "__iter__"):
                scores = list(scores)

            return [
                RerankResult(
                    doc_id=c["doc_id"],
                    original_score=c.get("score", 0),
                    rerank_score=float(scores[i]) if i < len(scores) else 0.0,
                    content=c.get("content", ""),
                    metadata=c.get("metadata", {}),
                )
                for i, c in enumerate(candidates)
            ]

        except Exception as e:
            logger.error(f"Local cross-encoder reranking failed: {e}")
            return self._rerank_keyword(query, candidates)

    async def _rerank_lmstudio(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
    ) -> List[RerankResult]:
        """Re-rank using LM Studio API."""
        import httpx

        client = self._model["client"]
        base_url = self._model["base_url"]
        model_id = self._model["model_id"]

        all_results = []
        for i in range(0, len(candidates), self._max_batch_size):
            batch = candidates[i : i + self._max_batch_size]
            pairs = [{"query": query, "text": c.get("content", "")} for c in batch]

            try:
                resp = await client.post(
                    f"{base_url}/rerank",
                    json={"model": model_id, "query": query, "documents": [c.get("content", "") for c in batch]},
                )
                resp.raise_for_status()
                data = resp.json()

                for j, item in enumerate(data.get("results", [])):
                    idx = i + j
                    if idx < len(candidates):
                        all_results.append(RerankResult(
                            doc_id=candidates[idx]["doc_id"],
                            original_score=candidates[idx].get("score", 0),
                            rerank_score=float(item.get("score", 0)),
                            content=candidates[idx].get("content", ""),
                            metadata=candidates[idx].get("metadata", {}),
                        ))

            except Exception as e:
                logger.warning(f"LM Studio reranking batch failed: {e}")

        return all_results

    def _rerank_keyword(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        top_k: Optional[int] = None,
    ) -> List[RerankResult]:
        """
        Keyword-based reranking fallback.

        Uses Jaccard similarity between query tokens and document tokens.
        """
        from app.retrieval.sparse_retrieval import tokenize

        query_tokens = set(tokenize(query))
        if not query_tokens:
            return candidates[:top_k] if top_k else candidates

        results = []
        for c in candidates:
            doc_tokens = set(tokenize(c.get("content", "")))
            if not doc_tokens:
                continue

            # Jaccard similarity
            intersection = query_tokens & doc_tokens
            union = query_tokens | doc_tokens
            jaccard = len(intersection) / len(union) if union else 0

            # Boost for exact phrase match
            content = c.get("content", "")
            query_lower = query.lower()
            exact_match = 1.0 if query_lower in content else 0.0

            # Combined score
            combined = jaccard * 0.7 + exact_match * 0.3

            results.append(RerankResult(
                doc_id=c["doc_id"],
                original_score=c.get("score", 0),
                rerank_score=combined,
                content=c.get("content", ""),
                metadata=c.get("metadata", {}),
            ))

        results.sort(key=lambda r: r.rerank_score, reverse=True)
        return results[:top_k] if top_k else results

    def get_info(self) -> Dict[str, Any]:
        """Get reranker information."""
        return {
            "loaded": self._model is not None,
            "backend": self._backend,
            "model_name": self._model_name,
        }
