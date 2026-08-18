"""
RedSight - High-Performance Local AI Intelligence Platform
Indexer

Manages indexing jobs, chunk embedding, and vector store operations.

Full ingestion pipeline (blueprint §4):
1. Detect and fingerprint — hash the source, identify type, skip unchanged
2. Parse structurally — preserve headings, code symbols, page numbers
3. Normalize — clean boilerplate, split by semantic boundaries
4. Enrich — generate summaries, entities, project tags
5. Embed + sparse-index — dense embeddings + lexical representation
6. Quality gate — reject empty/low-information chunks
7. Commit index version — record parser/embedding versions for rollback
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.ingestion.parser import DocumentParser, DocumentChunk
from app.retrieval.qdrant_client import QdrantClientWrapper
from app.retrieval.metadata_db import MetadataDB

logger = logging.getLogger(__name__)


@dataclass
class IndexJob:
    """An indexing job."""
    job_id: str
    source_path: str
    collection: str
    project: str
    status: str = "pending"  # pending, processing, complete, failed
    chunks_created: int = 0
    error: Optional[str] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    index_version: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "source_path": self.source_path,
            "collection": self.collection,
            "project": self.project,
            "status": self.status,
            "chunks_created": self.chunks_created,
            "error": self.error,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "index_version": self.index_version,
        }


class Indexer:
    """
    Indexer — Manages indexing jobs and vector store operations.

    Connects the full ingestion pipeline to Qdrant for vector storage
    and SQLite for metadata persistence.
    """

    def __init__(
        self,
        qdrant: Optional[QdrantClientWrapper] = None,
        metadata_db: Optional[MetadataDB] = None,
        embedding_model: Optional[Any] = None,
        bm25_index: Optional[Any] = None,
        chunk_size: int = 512,
        chunk_overlap: int = 64,
    ):
        self._qdrant = qdrant
        self._metadata = metadata_db
        self._embedding_model = embedding_model
        self._bm25_index = bm25_index
        self._parser = DocumentParser(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        self._jobs: Dict[str, IndexJob] = {}
        self._index_version_counter = 0

    # ── Job Management ──────────────────────────────────────────

    async def create_job(
        self,
        source_path: str,
        collection: str,
        project: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Create a new indexing job. Returns job_id."""
        job_id = str(uuid.uuid4())[:8]

        job = IndexJob(
            job_id=job_id,
            source_path=source_path,
            collection=collection,
            project=project,
            metadata=metadata or {},
        )
        self._jobs[job_id] = job
        logger.info(f"Index job created: {job_id} for {source_path}")
        return job_id

    async def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get job details."""
        job = self._jobs.get(job_id)
        return job.to_dict() if job else None

    async def list_jobs(
        self,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List indexing jobs."""
        jobs = list(self._jobs.values())
        if status:
            jobs = [j for j in jobs if j.status == status]
        jobs.sort(key=lambda j: j.started_at or 0, reverse=True)
        return [j.to_dict() for j in jobs[:limit]]

    # ── Main Pipeline ───────────────────────────────────────────

    async def process_job(self, job_id: str) -> Dict[str, Any]:
        """
        Process an indexing job — full ingestion pipeline.

        Executes all 7 steps from the blueprint:
        1. Detect and fingerprint
        2. Parse structurally
        3. Normalize
        4. Enrich
        5. Embed + sparse-index
        6. Quality gate
        7. Commit index version
        """
        job = self._jobs.get(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        if job.status != "pending":
            raise ValueError(f"Job {job_id} is not pending (status={job.status})")

        job.status = "processing"
        job.started_at = time.time()

        try:
            # ── Step 1: Detect and fingerprint ────────────────────
            logger.info(f"Step 1: Fingerprinting {job.source_path}")
            file_hash = await self._parser.get_file_hash(job.source_path)

            # Check if file changed since last indexed
            if self._metadata:
                changed = await self._metadata.check_hash_changed(
                    job.source_path, file_hash
                )
                if not changed:
                    logger.info(f"File unchanged: {job.source_path} — skipping")
                    job.status = "complete"
                    job.completed_at = time.time()
                    job.chunks_created = 0
                    return job.to_dict()

            # Register source in metadata DB
            source_file_id = None
            if self._metadata:
                source_file_id = await self._metadata.get_or_create_source(
                    job.source_path, job.project, file_hash
                )

            # ── Step 2: Parse structurally ────────────────────────
            logger.info(f"Step 2: Parsing {job.source_path}")
            chunks = await self._parser.parse(
                job.source_path, job.project, job.metadata
            )

            if not chunks:
                logger.warning(f"No chunks extracted from {job.source_path}")
                job.status = "complete"
                job.completed_at = time.time()
                return job.to_dict()

            # ── Step 3: Normalize ─────────────────────────────────
            logger.info(f"Step 3: Normalizing {len(chunks)} chunks")
            normalized = []
            for chunk in chunks:
                # Clean whitespace, strip boilerplate
                content = chunk.content.strip()
                if len(content) > 10:  # Skip very short chunks
                    chunk.content = content
                    normalized.append(chunk)

            logger.info(f"Normalized: {len(normalized)} chunks (from {len(chunks)})")
            chunks = normalized

            # ── Step 4: Enrich ────────────────────────────────────
            logger.info(f"Step 4: Enriching {len(chunks)} chunks")
            self._enrich_chunks(chunks, job)

            # ── Step 5: Embed + sparse-index ──────────────────────
            logger.info(f"Step 5: Embedding {len(chunks)} chunks")
            embedded_chunks = await self._embed_chunks(chunks)

            if not embedded_chunks:
                raise ValueError("Failed to generate embeddings for any chunks")

            # ── Step 5b: Index into BM25 (sparse) ─────────────────
            if self._bm25_index:
                for ec in embedded_chunks:
                    self._bm25_index.add_document(
                        doc_id=ec.chunk.chunk_id,
                        content=ec.chunk.content,
                        title=ec.chunk.heading or ec.chunk.source_path,
                        heading=ec.chunk.heading,
                        metadata={
                            "source_path": ec.chunk.source_path,
                            "project": ec.chunk.project,
                            "collection": job.collection,
                            "page_number": ec.chunk.page_number,
                            "file_hash": file_hash,
                        },
                    )
                logger.info(f"Indexed {len(embedded_chunks)} chunks into BM25")

            # ── Step 6: Quality gate ──────────────────────────────
            logger.info(f"Step 6: Quality gate")
            valid_chunks = []
            for ec in embedded_chunks:
                # Reject empty content
                if not ec.chunk.content.strip():
                    logger.warning(f"Skipping empty chunk: {ec.chunk.chunk_id}")
                    continue
                # Reject chunks with zero-dimension embeddings
                if not ec.vector or len(ec.vector) == 0:
                    logger.warning(f"Skipping zero-vector chunk: {ec.chunk.chunk_id}")
                    continue
                valid_chunks.append(ec)

            logger.info(f"Quality gate: {len(valid_chunks)}/{len(embedded_chunks)} chunks pass")
            if not valid_chunks:
                raise ValueError("No chunks passed quality gate")

            # ── Step 7: Commit to Qdrant + SQLite ─────────────────
            logger.info(f"Step 7: Committing {len(valid_chunks)} chunks")

            # Upsert to Qdrant
            if self._qdrant:
                qdrant_points = []
                for ec in valid_chunks:
                    qdrant_points.append({
                        "id": ec.chunk.chunk_id,
                        "vector": ec.vector,
                        "payload": {
                            "chunk_id": ec.chunk.chunk_id,
                            "content": ec.chunk.content,
                            "source_path": ec.chunk.source_path,
                            "project": ec.chunk.project,
                            "collection": job.collection,
                            "page_number": ec.chunk.page_number,
                            "heading": ec.chunk.heading,
                            "chunk_index": ec.chunk.chunk_index,
                            "file_hash": file_hash,
                            "embedding_version": ec.embedding_version,
                            "parser_version": ec.parser_version,
                            "access_scope": "internal",
                        },
                    })

                await self._qdrant.upsert_points(job.collection, qdrant_points)
                logger.info(f"Upserted {len(qdrant_points)} points to Qdrant '{job.collection}'")

            # Persist to SQLite metadata
            if self._metadata:
                for ec in valid_chunks:
                    await self._metadata.upsert_chunk(
                        chunk_id=ec.chunk.chunk_id,
                        source_file_id=source_file_id or 0,
                        collection=job.collection,
                        content=ec.chunk.content,
                        page_number=ec.chunk.page_number,
                        heading=ec.chunk.heading,
                        chunk_index=ec.chunk.chunk_index,
                        embedding_version=ec.embedding_version,
                        parser_version=ec.parser_version,
                    )

            # Create index version record
            if self._metadata:
                self._index_version_counter += 1
                await self._metadata.create_index_version(
                    collection=job.collection,
                    parser_version="1.0.0",
                    embedding_model=ec.embedding_model if hasattr(ec, 'embedding_model') else "unknown",
                    embedding_version=ec.embedding_version,
                    points_count=len(valid_chunks),
                )
                job.index_version = self._index_version_counter

            # Update job
            job.status = "complete"
            job.chunks_created = len(valid_chunks)
            job.completed_at = time.time()

            elapsed = job.completed_at - job.started_at
            logger.info(
                f"Job {job_id} complete: {len(valid_chunks)} chunks in {elapsed:.1f}s"
            )

        except Exception as e:
            job.status = "failed"
            job.error = str(e)
            job.completed_at = time.time()
            logger.error(f"Job {job_id} failed: {e}", exc_info=True)

        return job.to_dict()

    # ── Re-indexing ─────────────────────────────────────────────

    async def reindex_collection(
        self,
        collection: str,
        project: Optional[str] = None,
    ) -> List[str]:
        """
        Re-index an entire collection.

        Deletes existing Qdrant points and re-indexes all sources
        in the collection. Returns list of job_ids.
        """
        if not self._metadata:
            raise RuntimeError("Metadata DB required for re-indexing")

        # Get all source files for this collection
        stats = await self._metadata.get_collection_stats(collection)
        logger.info(f"Re-indexing collection '{collection}'")

        # Delete existing Qdrant data
        if self._qdrant:
            await self._qdrant.delete_collection(collection)
            await self._qdrant.create_collection(collection)

        # Delete SQLite chunks
        await self._metadata.delete_chunks_for_collection(collection)

        # TODO: Scan project directories for files to re-index
        # For now, return empty list — real implementation would
        # walk project directories and create jobs for each file

        logger.info(f"Collection '{collection}' cleared for re-index")
        return []

    # ── Helpers ─────────────────────────────────────────────────

    def _enrich_chunks(
        self,
        chunks: List[DocumentChunk],
        job: IndexJob,
    ) -> None:
        """Enrich chunks with metadata."""
        for chunk in chunks:
            # Add collection to metadata
            chunk.metadata["collection"] = job.collection
            chunk.metadata["project"] = job.project
            chunk.metadata["indexed_at"] = time.time()

    async def _embed_chunks(
        self,
        chunks: List[DocumentChunk],
    ) -> List["EmbeddedChunk"]:
        """Generate embeddings for a list of chunks."""
        if not self._embedding_model:
            raise ValueError("No embedding model configured")

        texts = [c.content for c in chunks]
        embedding_version = "unknown"
        embedding_model_name = "unknown"

        try:
            # Try sentence-transformers interface
            if hasattr(self._embedding_model, "encode"):
                import numpy as np

                embeddings = self._embedding_model.encode(
                    texts,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                )
                if isinstance(embeddings, np.ndarray):
                    embeddings = embeddings.tolist()
                elif hasattr(embeddings, "tolist"):
                    embeddings = embeddings.tolist()
                else:
                    embeddings = [list(e) for e in embeddings]

                embedding_version = getattr(
                    self._embedding_model, "sentence_transformers_version", "st"
                )
                embedding_model_name = getattr(
                    self._embedding_model, "name_or_path", "sentence-transformers"
                )

            # Try OpenAI/LM Studio interface
            elif hasattr(self._embedding_model, "embed"):
                result = self._embedding_model.embed(texts)
                if result:
                    embeddings = result
                else:
                    raise ValueError("Embedding model returned empty result")

                embedding_version = "openai_api"
                embedding_model_name = getattr(
                    self._embedding_model, "model", "openai-embeddings"
                )

            else:
                raise ValueError(
                    f"Unknown embedding model interface: {type(self._embedding_model)}"
                )

            if len(embeddings) != len(chunks):
                raise ValueError(
                    f"Embedding count mismatch: {len(embeddings)} vs {len(chunks)} chunks"
                )

            return [
                EmbeddedChunk(
                    chunk=chunk,
                    vector=vec,
                    embedding_model=embedding_model_name,
                    embedding_version=embedding_version,
                    parser_version="1.0.0",
                )
                for chunk, vec in zip(chunks, embeddings)
            ]

        except Exception as e:
            logger.error(f"Embedding failed: {e}")
            raise

    # ── Batch Index ─────────────────────────────────────────────

    async def index_files(
        self,
        file_paths: List[str],
        collection: str,
        project: str,
    ) -> List[Dict[str, Any]]:
        """
        Index multiple files in sequence.

        Returns list of job results.
        """
        results = []
        for path in file_paths:
            job_id = await self.create_job(path, collection, project)
            result = await self.process_job(job_id)
            results.append(result)
            logger.info(f"Indexed {path}: {result['status']} ({result['chunks_created']} chunks)")

        return results


# ─── Data Classes ─────────────────────────────────────────────────


@dataclass
class EmbeddedChunk:
    """A chunk with its embedding."""
    chunk: DocumentChunk
    vector: List[float]
    embedding_model: str
    embedding_version: str
    parser_version: str


@dataclass
class IndexConfig:
    """Configuration for indexing."""
    chunk_size: int = 512
    chunk_overlap: int = 64
    collection: str = "default"
    project: str = "default"
    embedding_model: Optional[str] = None
    enable_bm25: bool = True
    enable_hybrid: bool = True


@dataclass
class IndexResult:
    """Result of an indexing operation."""
    job_id: str
    status: str
    chunks_created: int
    chunks_skipped: int = 0
    error: Optional[str] = None
    elapsed_seconds: float = 0.0


@dataclass
class IndexStats:
    """Statistics about an index."""
    total_chunks: int = 0
    total_sources: int = 0
    collections: Dict[str, int] = field(default_factory=dict)
    last_indexed: Optional[float] = None


class TextIndex:
    """Simple text index for keyword search (BM25 wrapper)."""
    
    def __init__(self):
        self._docs: Dict[str, Dict[str, Any]] = {}
    
    def add_document(self, doc_id: str, content: str, **kwargs) -> None:
        self._docs[doc_id] = {"content": content, **kwargs}
    
    def remove_document(self, doc_id: str) -> bool:
        return self._docs.pop(doc_id, None) is not None
    
    def search(self, query: str, top_k: int = 10) -> List[Dict[str, Any]]:
        results = []
        query_terms = query.lower().split()
        for doc_id, doc in self._docs.items():
            score = sum(1 for term in query_terms if term in doc["content"].lower())
            if score > 0:
                results.append({"id": doc_id, "score": score, "doc": doc})
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]
    
    def stats(self) -> Dict[str, Any]:
        return {"total_docs": len(self._docs)}


class VectorIndex:
    """Simple vector index for dense search."""
    
    def __init__(self, dimension: int = 384):
        self._vectors: Dict[str, List[float]] = {}
        self._payloads: Dict[str, Dict[str, Any]] = {}
        self._dimension = dimension
    
    def add_vector(self, vector_id: str, vector: List[float], payload: Optional[Dict[str, Any]] = None) -> None:
        self._vectors[vector_id] = vector
        self._payloads[vector_id] = payload or {}
    
    def search(self, query_vector: List[float], top_k: int = 10) -> List[Dict[str, Any]]:
        import math
        results = []
        for vid, vec in self._vectors.items():
            if len(vec) != self._dimension:
                continue
            dot = sum(a * b for a, b in zip(vec, query_vector))
            norm_a = math.sqrt(sum(a * a for a in vec))
            norm_b = math.sqrt(sum(b * b for b in query_vector))
            if norm_a > 0 and norm_b > 0:
                score = dot / (norm_a * norm_b)
                results.append({"id": vid, "score": score, "payload": self._payloads.get(vid, {})})
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]
    
    def stats(self) -> Dict[str, Any]:
        return {"total_vectors": len(self._vectors), "dimension": self._dimension}
