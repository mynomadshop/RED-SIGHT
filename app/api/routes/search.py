"""
RedSight - High-Performance Local AI Intelligence Platform
Search API Routes - Hybrid RAG (Phase 2)

Knowledge search with:
- Dense vector search (Qdrant)
- Sparse BM25 lexical search
- Cross-encoder reranking
- Context budgeting
- Citation pack with provenance
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

from app.retrieval.hybrid_search import HybridSearchEngine, SearchResult, CitationPack
from app.retrieval.sparse_retrieval import BM25Index
from app.retrieval.reranker import CrossEncoderReranker
from app.retrieval.context_budgeter import ContextBudgeter

logger = logging.getLogger(__name__)

router = APIRouter()

# Global instances
_search_engine: Optional[HybridSearchEngine] = None
_bm25_index: Optional[BM25Index] = None
_reranker: Optional[CrossEncoderReranker] = None
_budgeter: Optional[ContextBudgeter] = None


def set_search_engine(engine: HybridSearchEngine):
    global _search_engine
    _search_engine = engine


def set_bm25_index(index: BM25Index):
    global _bm25_index
    _bm25_index = index


def set_reranker(reranker: CrossEncoderReranker):
    global _reranker
    _reranker = reranker


def set_budgeter(budgeter: ContextBudgeter):
    global _budgeter
    _budgeter = budgeter


@router.post("/search")
async def search_knowledge(request: Dict[str, Any]) -> Dict[str, Any]:
    """
    Hybrid search across knowledge collections.

    Combines dense vector search + sparse BM25 + optional reranking.

    Request body:
    - query: str (required)
    - collections: list[str] (optional)
    - top_k: int (default 40)
    - hybrid: bool (default True) — use BM25 + dense
    - rerank: bool (default True) — apply cross-encoder reranking
    - budget_tokens: int (default 4096) — context budget limit
    """
    if not _search_engine:
        raise HTTPException(
            status_code=503,
            detail="Search engine not initialized. Server not started?",
        )

    query = request.get("query", "")
    collections = request.get("collections")
    top_k = request.get("top_k", 40)
    hybrid = request.get("hybrid", True)
    rerank = request.get("rerank", True)
    budget_tokens = request.get("budget_tokens", 4096)

    if not query.strip():
        raise HTTPException(status_code=400, detail="No query provided")

    # ── Step 1: Dense vector search ──────────────────────────────
    query_vector = await _search_engine._embed_query(query)
    if not query_vector:
        raise HTTPException(
            status_code=503,
            detail="Embedding model not available. Cannot perform search.",
        )

    collection_weights = _search_engine._search_collection
    search_collections = collections or await _search_engine.list_collections()

    all_dense_results = []
    for coll in search_collections:
        try:
            coll_results = await _search_engine._search_collection(
                query_vector, coll, top_k=top_k, filters=None
            )
            all_dense_results.extend(coll_results)
        except Exception as e:
            logger.warning(f"Collection '{coll}' search failed: {e}")

    # ── Step 2: Sparse BM25 search (if hybrid) ───────────────────
    if hybrid and _bm25_index:
        try:
            bm25_results = _bm25_index.search(query, top_k=top_k * 2)
            # Merge with dense results
            dense_ids = {r.chunk_id for r in all_dense_results}
            for bm25_r in bm25_results:
                if bm25_r["doc_id"] not in dense_ids:
                    all_dense_results.append(SearchResult(
                        chunk_id=bm25_r["doc_id"],
                        content=bm25_r["content"],
                        collection=bm25_r.get("metadata", {}).get("collection", "unknown"),
                        source_path=bm25_r.get("metadata", {}).get("source_path", ""),
                        project=bm25_r.get("metadata", {}).get("project", ""),
                        score=bm25_r["score"],
                    ))
        except Exception as e:
            logger.warning(f"BM25 search failed: {e}")

    # ── Step 3: Reranking ────────────────────────────────────────
    candidates = [r.to_dict() for r in all_dense_results]
    if rerank and _reranker and len(candidates) > 5:
        try:
            reranked = await _reranker.rerank(query, candidates, top_k=20)
            final_results = [SearchResult(
                chunk_id=r.doc_id,
                content=r.content,
                collection=r.metadata.get("collection", "unknown"),
                source_path=r.metadata.get("source_path", ""),
                project=r.metadata.get("project", ""),
                score=r.rerank_score,
            ) for r in reranked]
        except Exception as e:
            logger.warning(f"Reranking failed: {e}")
            final_results = all_dense_results[:top_k]
    else:
        final_results = all_dense_results[:top_k]

    # ── Step 4: Context budgeting ────────────────────────────────
    if _budgeter:
        budgeted = _budgeter.budget(final_results, query=query, task_type="general")
        final_results = [SearchResult(
            chunk_id=s.chunk_id,
            content=s.content,
            collection=s.collection,
            source_path=s.source_path,
            project=s.project,
            score=s.score,
            page_number=s.page_number,
            heading=s.heading,
        ) for s in budgeted]

    # ── Step 5: Build citation pack ──────────────────────────────
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

    return {
        "query": query,
        "results": [r.to_dict() for r in final_results],
        "count": len(final_results),
        "collections": search_collections,
        "citation_pack": citation.to_dict(),
        "hybrid": hybrid,
        "reranked": rerank,
        "budget_tokens": budget_tokens,
    }


@router.get("/collections")
async def list_collections() -> Dict[str, Any]:
    """List all available knowledge collections."""
    if not _search_engine:
        return {"collections": [], "count": 0, "message": "Search engine not initialized"}

    try:
        collections = await _search_engine.list_collections()
        return {"collections": collections, "count": len(collections)}
    except Exception as e:
        logger.error(f"Failed to list collections: {e}")
        return {"collections": [], "count": 0, "error": str(e)}


@router.get("/collections/{collection}/stats")
async def get_collection_stats(collection: str) -> Dict[str, Any]:
    """Get statistics for a specific collection."""
    if not _search_engine:
        return {"error": "Search engine not initialized"}

    try:
        stats = await _search_engine.get_collection_stats(collection)
        return stats
    except Exception as e:
        logger.error(f"Failed to get collection stats: {e}")
        return {"collection": collection, "error": str(e)}


@router.get("/bm25/stats")
async def get_bm25_stats() -> Dict[str, Any]:
    """Get BM25 index statistics."""
    if not _bm25_index:
        return {"error": "BM25 index not initialized"}

    return _bm25_index.get_stats()


@router.get("/chunks/{chunk_id}")
async def get_chunk(chunk_id: str) -> Dict[str, Any]:
    """Retrieve a specific chunk by ID."""
    if not _search_engine:
        raise HTTPException(status_code=503, detail="Search engine not initialized")

    try:
        result = await _search_engine.search_by_id(chunk_id)
        if result:
            return result.to_dict()
        return {"error": f"Chunk not found: {chunk_id}"}
    except Exception as e:
        logger.error(f"Failed to get chunk: {e}")
        raise HTTPException(status_code=500, detail=str(e))
