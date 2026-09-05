"""
RedSight - High-Performance Local AI Intelligence Platform
Qdrant Client Wrapper

Manages Qdrant connection, collection lifecycle, vector operations,
and hybrid search with dense + sparse vectors.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Known collections per blueprint §4
KNOWLEDGE_COLLECTIONS = [
    "knowledge_docs",
    "project_code",
    "project_decisions",
    "skills_index",
    "episodic_memory",
    "tool_catalog",
    "eval_corpus",
]

# Default vector dimension for sentence-transformers all-MiniLM-L6-v2
DEFAULT_VECTOR_SIZE = 384


class QdrantConfig:
    """Configuration for Qdrant connection and behavior."""
    def __init__(
        self,
        url: Optional[str] = None,
        api_key: Optional[str] = None,
        host: str = "127.0.0.1",
        port: int = 6333,
        embedded: bool = False,
        vector_size: int = DEFAULT_VECTOR_SIZE,
        embedded_path: Optional[str] = None,
    ):
        self.url = url
        self.api_key = api_key
        self.host = host
        self.port = port
        self.embedded = embedded
        self.vector_size = vector_size
        self.embedded_path = embedded_path or "./data/qdrant_db"


class QdrantClientWrapper:
    """
    Qdrant client wrapper with collection management and hybrid search.

    Supports:
    - Local Qdrant instance (http://127.0.0.1:6333)
    - Embedded Qdrant mode (no separate process)
    - Dense vector search with optional sparse vectors
    - Payload filtering by metadata
    - Collection lifecycle (create, list, delete, stats)
    """

    def __init__(
        self,
        url: Optional[str] = None,
        api_key: Optional[str] = None,
        host: str = "127.0.0.1",
        port: int = 6333,
        embedded: bool = False,
        vector_size: int = DEFAULT_VECTOR_SIZE,
        embedded_path: Optional[str] = None,
    ):
        self._client = None
        self._url = url
        self._api_key = api_key
        self._host = host
        self._port = port
        self._embedded = embedded
        self._vector_size = vector_size
        self._embedded_path = embedded_path or "./data/qdrant_db"
        self._collections: set[str] = set()

    # ── Connection ──────────────────────────────────────────────

    async def connect(self) -> bool:
        """Connect to Qdrant (remote or embedded mode)."""
        try:
            from qdrant_client import QdrantClient, models

            if self._embedded:
                # Embedded mode — runs in-process, no server needed
                self._client = QdrantClient(
                    path=self._embedded_path,
                )
                logger.info("Qdrant connected in EMBEDDED mode (local DB)")
            else:
                if self._url:
                    # qdrant-client rejects URL and host supplied together.
                    connect_kwargs: Dict[str, Any] = {"url": self._url}
                else:
                    connect_kwargs = {"host": self._host, "port": self._port}
                if self._api_key:
                    connect_kwargs["api_key"] = self._api_key

                self._client = QdrantClient(**connect_kwargs)
                # Verify connectivity
                collections = self._client.get_collections().collections
                self._collections = {c.name for c in collections}
                logger.info(
                    f"Qdrant connected at {self._host}:{self._port} "
                    f"({len(self._collections)} collections)"
                )

            return True

        except ImportError:
            logger.error("qdrant-client not installed. Run: pip install qdrant-client")
            return False
        except Exception as e:
            logger.error(f"Qdrant connection failed: {e}")
            # Fallback to embedded mode
            if not self._embedded:
                logger.info("Falling back to embedded Qdrant mode...")
                return await self._connect_embedded()
            return False

    async def _connect_embedded(self) -> bool:
        """Fallback to embedded Qdrant."""
        try:
            from qdrant_client import QdrantClient, models

            self._client = QdrantClient(
                path=self._embedded_path,
            )
            collections = self._client.get_collections().collections
            self._collections = {c.name for c in collections}
            logger.info("Qdrant connected in EMBEDDED fallback mode")
            return True
        except Exception as e:
            logger.error(f"Embedded Qdrant fallback failed: {e}")
            return False

    @property
    def is_connected(self) -> bool:
        return self._client is not None

    # ── Collection Lifecycle ────────────────────────────────────

    async def create_collection(
        self,
        name: str,
        vector_size: Optional[int] = None,
        distance: str = "COSINE",
    ) -> bool:
        """Create a Qdrant collection with dense vector config."""
        if not self._client:
            raise RuntimeError("Not connected to Qdrant")

        from qdrant_client import models

        try:
            self._client.create_collection(
                collection_name=name,
                vectors_config=models.VectorParams(
                    size=vector_size or self._vector_size,
                    distance=getattr(models.Distance, distance.upper(), models.Distance.COSINE),
                ),
                # Enable sparse vectors for hybrid search
                sparse_vectors_config={
                    "sparse_text": models.SparseVectorParams(
                        index=models.SparseIndexParams(
                            on_disk=False,
                        )
                    )
                }
                if self._vector_size == DEFAULT_VECTOR_SIZE  # Only for MiniLM dimension
                else None,
            )
            self._collections.add(name)
            logger.info(f"Collection '{name}' created")
            return True
        except Exception as e:
            if "already exists" in str(e).lower():
                logger.info(f"Collection '{name}' already exists")
                self._collections.add(name)
                return True
            logger.error(f"Failed to create collection '{name}': {e}")
            return False

    async def ensure_collections(self) -> List[str]:
        """Ensure all known knowledge collections exist. Returns created list."""
        created = []
        for coll in KNOWLEDGE_COLLECTIONS:
            if await self.create_collection(coll):
                created.append(coll)
        return created

    async def delete_collection(self, name: str) -> bool:
        """Delete a collection and all its data."""
        if not self._client:
            return False
        try:
            self._client.delete_collection(collection_name=name)
            self._collections.discard(name)
            logger.info(f"Collection '{name}' deleted")
            return True
        except Exception as e:
            logger.error(f"Failed to delete collection '{name}': {e}")
            return False

    async def list_collections(self) -> List[str]:
        """List all collection names."""
        if not self._client:
            return []
        try:
            collections = self._client.get_collections().collections
            self._collections = {c.name for c in collections}
            return list(self._collections)
        except Exception:
            return list(self._collections)

    async def get_collection_stats(self, name: str) -> Dict[str, Any]:
        """Get collection statistics."""
        if not self._client:
            return {"error": "Not connected"}
        try:
            info = self._client.get_collection(collection_name=name)
            result = {
                "collection": name,
                "points_count": info.points_count,
            }
            # Embedded Qdrant may not have all attributes
            if hasattr(info, "vectors_count"):
                result["vectors_count"] = info.vectors_count
            if hasattr(info, "indexed_vectors_count"):
                result["indexed_vectors_count"] = info.indexed_vectors_count
            if hasattr(info, "status"):
                result["status"] = info.status
            if hasattr(info, "optimizer_status"):
                result["optimizer_status"] = info.optimizer_status
            return result
        except Exception as e:
            return {"collection": name, "error": str(e)}

    # ── Write Operations ────────────────────────────────────────

    async def upsert_points(
        self,
        collection: str,
        points: List[Dict[str, Any]],
    ) -> bool:
        """
        Upsert points into a collection.

        Each point dict must have:
        - id: unique identifier
        - vector: list of floats (dense embedding)
        - payload: dict with metadata
        """
        if not self._client:
            raise RuntimeError("Not connected to Qdrant")

        from qdrant_client import models

        q_points = []
        for p in points:
            q_points.append(
                models.PointStruct(
                    id=p["id"],
                    vector=p["vector"],
                    payload=p.get("payload", {}),
                )
            )

        try:
            self._client.upsert(
                collection_name=collection,
                points=q_points,
            )
            logger.info(f"Upserted {len(q_points)} points to '{collection}'")
            return True
        except Exception as e:
            logger.error(f"Upsert failed for '{collection}': {e}")
            return False

    # ── Search Operations ───────────────────────────────────────

    async def search(
        self,
        query_vector: List[float],
        collection: str,
        top_k: int = 20,
        filters: Optional[Dict[str, Any]] = None,
        score_threshold: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """
        Dense vector search with optional payload filtering.

        Returns list of {id, score, payload} dicts.
        """
        if not self._client:
            raise RuntimeError("Not connected to Qdrant")

        from qdrant_client import models

        q_filter = None
        if filters:
            q_filter = self._build_qdrant_filter(filters)

        search_params = models.SearchParams(
            hnsw_ef=128,
            exact=False,
        )

        try:
            # Embedded Qdrant uses query_points, remote uses search
            if self._embedded:
                from qdrant_client import models as qmodels

                query_result = self._client.query_points(
                    collection_name=collection,
                    query=query_vector,
                    query_filter=q_filter,
                    limit=top_k,
                )
                results = query_result.points
            else:
                results = self._client.search(
                    collection_name=collection,
                    query_vector=query_vector,
                    query_filter=q_filter,
                    limit=top_k,
                    score_threshold=score_threshold,
                    search_params=search_params,
                )
            return [
                {
                    "id": r.id,
                    "score": r.score,
                    "payload": r.payload,
                }
                for r in results
            ]
        except Exception as e:
            logger.error(f"Search failed for '{collection}': {e}")
            return []

    async def search_by_id(self, collection: str, point_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a single point by ID."""
        if not self._client:
            return None
        try:
            results = self._client.retrieve(
                collection_name=collection,
                ids=[point_id],
                with_payload=True,
            )
            if results:
                r = results[0]
                return {
                    "id": r.id,
                    "vector": r.vector,
                    "payload": r.payload,
                }
            return None
        except Exception as e:
            logger.error(f"Retrieve failed for '{collection}' id={point_id}: {e}")
            return None

    async def get_all_point_ids(self, collection: str, limit: int = 1000) -> List[str]:
        """Get all point IDs in a collection (for iteration)."""
        if not self._client:
            return []
        try:
            ids = []
            offset = None
            while True:
                results, offset = self._client.scroll(
                    collection_name=collection,
                    limit=limit,
                    offset=offset,
                    with_payload=False,
                    with_vectors=False,
                )
                if not results:
                    break
                ids.extend(r.id for r in results)
                if offset is None:
                    break
            return ids
        except Exception as e:
            logger.error(f"Scroll failed for '{collection}': {e}")
            return []

    # ── Hybrid Search (Dense + Sparse) ──────────────────────────

    async def hybrid_search(
        self,
        query_vector: List[float],
        sparse_query: Dict[str, Any],
        collection: str,
        top_k: int = 40,
        alpha: float = 0.5,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Hybrid search combining dense vector + sparse lexical results.

        alpha: weight for dense results (1-alpha for sparse).
        Uses RRF (Reciprocal Rank Fusion) to merge results.
        """
        if not self._client:
            raise RuntimeError("Not connected to Qdrant")

        from qdrant_client import models

        q_filter = None
        if filters:
            q_filter = self._build_qdrant_filter(filters)

        try:
            # Dense search
            dense_results = self._client.search(
                collection_name=collection,
                query_vector=query_vector,
                query_filter=q_filter,
                limit=top_k,
                search_params=models.SearchParams(hnsw_ef=128),
            )

            # Sparse search
            sparse_results = self._client.search(
                collection_name=collection,
                query_vector=(
                    "sparse_text",
                    models.SparseVector(
                        indices=sparse_query.get("indices", []),
                        values=sparse_query.get("values", []),
                    ),
                ),
                query_filter=q_filter,
                limit=top_k,
                search_params=models.SearchParams(hnsw_ef=128),
            )

            # RRF fusion
            fused = self._rrf_fusion(dense_results, sparse_results, alpha=alpha, k=top_k)
            return fused

        except Exception as e:
            logger.error(f"Hybrid search failed for '{collection}': {e}")
            # Fallback to dense-only
            return await self.search(query_vector, collection, top_k, filters)

    # ── Helpers ─────────────────────────────────────────────────

    def _build_qdrant_filter(self, conditions: Dict[str, Any]) -> Any:
        """Convert simple dict filters to Qdrant Filter."""
        from qdrant_client import models

        must_clauses = []
        for key, value in conditions.items():
            if isinstance(value, dict):
                # Support match, range, range operators
                if "match" in value:
                    must_clauses.append(
                        models.FieldCondition(
                            key=key,
                            match=models.MatchValue(value=value["match"]["value"]),
                        )
                    )
                elif "range" in value:
                    r = value["range"]
                    must_clauses.append(
                        models.FieldCondition(
                            key=key,
                            range=models.Range(
                                gte=r.get("gte"),
                                lte=r.get("lte"),
                                gt=r.get("gt"),
                                lt=r.get("lt"),
                            ),
                        )
                    )
                elif "values" in value:
                    must_clauses.append(
                        models.FieldCondition(
                            key=key,
                            match=models.MatchAny(any=value["values"]),
                        )
                    )
            else:
                # Simple equality match
                must_clauses.append(
                    models.FieldCondition(
                        key=key,
                        match=models.MatchValue(value=value),
                    )
                )

        if not must_clauses:
            return None
        return models.Filter(must=must_clauses)

    @staticmethod
    def _rrf_fusion(
        dense_results: List,
        sparse_results: List,
        alpha: float = 0.5,
        k: int = 60,
    ) -> List[Dict[str, Any]]:
        """Reciprocal Rank Fusion to merge dense + sparse results."""
        rrf_scores: Dict[str, Tuple[float, float, list]] = {}

        for rank, point in enumerate(dense_results):
            pid = point.id
            dense_score = point.score
            rrf_scores[pid] = (
                dense_score,
                0.0,
                [p for p in dense_results],
            )

        for rank, point in enumerate(sparse_results):
            pid = point.id
            sparse_score = point.score
            if pid in rrf_scores:
                old_dense, _, dense_list = rrf_scores[pid]
                rrf_scores[pid] = (old_dense, sparse_score, dense_list)
            else:
                rrf_scores[pid] = (0.0, sparse_score, [point])

        # Compute RRF score and merge
        fused = []
        for pid, (dense_s, sparse_s, points_list) in rrf_scores.items():
            rrf_score = alpha * (1 / (k + 1)) + (1 - alpha) * (1 / (k + 1))
            # Weight by actual scores
            max_score = max(dense_s, sparse_s, 0.001)
            payload = points_list[0].payload if points_list else {}
            fused.append(
                {
                    "id": pid,
                    "score": max_score,
                    "dense_score": dense_s,
                    "sparse_score": sparse_s,
                    "rrf_score": rrf_score,
                    "payload": payload,
                }
            )

        fused.sort(key=lambda x: x["score"], reverse=True)
        return fused

    async def close(self):
        """Close the Qdrant connection."""
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
            # On Windows, embedded Qdrant may hold SQLite locks briefly after close()
            # Add a small delay to ensure file handles are released before temp_dir cleanup
            import asyncio
            try:
                await asyncio.sleep(0.1)
            except Exception:
                pass
            logger.info("Qdrant connection closed")
