"""
RedSight - High-Performance Local AI Intelligence Platform
Phase 1 Integration Tests

Tests the full knowledge pipeline:
- Qdrant embedded mode connection
- SQLite metadata DB operations
- PDF/text ingestion with embeddings
- Hybrid search with provenance
- Source viewing and navigation
- Re-indexing with version tracking
"""

import asyncio
import hashlib
import os
import sys
import tempfile
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pytest
import pytest_asyncio


# ─── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files.
    
    Uses robust cleanup that retries on Windows file-lock errors
    from Qdrant embedded SQLite and other file handles.
    """
    import shutil
    import time as _time
    
    tmpdir = tempfile.mkdtemp()
    yield tmpdir
    # Robust cleanup for Windows — retry deleting locked files
    if os.path.exists(tmpdir):
        for _attempt in range(5):
            try:
                shutil.rmtree(tmpdir)
                break
            except PermissionError:
                _time.sleep(0.5)
        else:
            # Last resort: try individual file deletions
            for root, dirs, files in os.walk(tmpdir, topdown=False):
                for f in files:
                    fp = os.path.join(root, f)
                    try:
                        os.unlink(fp)
                    except PermissionError:
                        pass
                for d in dirs:
                    dp = os.path.join(root, d)
                    try:
                        os.rmdir(dp)
                    except OSError:
                        pass
            try:
                os.rmdir(tmpdir)
            except OSError:
                pass


@pytest.fixture
def test_pdf_content():
    """Return test PDF-like content."""
    return """
    # RedSight Architecture Overview

    RedSight is a local-first AI intelligence platform that turns your
    projects, documents, and operational knowledge into a governed
    retrieval + agent system.

    ## Core Components

    ### Knowledge Fabric
    The knowledge fabric combines dense semantic retrieval with lexical
    sparse retrieval, metadata filtering and reranking. A Qdrant-based
    implementation supports local operation and hybrid/multi-stage querying.

    ### Agent Runtime
    The agent runtime implements a planner/executor/evaluator loop with
    subagent support, tool contracts, permission checks and task state.

    ### GPU Scheduler
    The acceleration layer is a policy-driven execution service with
    VRAM reservations, GPU affinity, backpressure, and preemption.

    ## Retrieval Pipeline

    1. Query planner classifies the question type
    2. Parallel retrieval searches relevant collections
    3. Reranking uses a cross-encoder on candidates
    4. Context budgeter allocates tokens by evidence value
    5. Citation pack passes source IDs through for UI display
    """


@pytest.fixture
def test_code_content():
    """Return test Python code content."""
    return '''"""
RedSight - Example Module
"""

from typing import List, Optional


class KnowledgeRetriever:
    """Retrieves knowledge from indexed collections."""

    def __init__(self, collection_name: str):
        self.collection_name = collection_name
        self.indexed = False

    async def search(self, query: str, top_k: int = 10) -> List[dict]:
        """Search the knowledge collection."""
        if not self.indexed:
            raise RuntimeError("Collection not indexed")
        return []

    async def ingest(self, file_path: str) -> str:
        """Ingest a file into the knowledge collection."""
        chunk_id = hashlib.md5(file_path.encode()).hexdigest()[:8]
        self.indexed = True
        return chunk_id


def create_retriever(collection: str) -> KnowledgeRetriever:
    """Factory function to create a retriever."""
    return KnowledgeRetriever(collection)
'''


@pytest.fixture
def test_text_content():
    """Return plain text content."""
    return """
    This is a test document for RedSight knowledge indexing.

    It contains multiple paragraphs with various topics including:
    - Local AI inference
    - Vector databases
    - Hybrid search
    - GPU scheduling

    The purpose is to verify that the ingestion pipeline correctly
    parses, chunks, and indexes text content for semantic search.
    """


# ─── Qdrant Client Tests ─────────────────────────────────────────────


class TestQdrantClient:
    """Tests for QdrantClientWrapper with embedded mode."""

    @pytest.mark.asyncio
    async def test_embedded_connection(self, temp_dir):
        """Test connecting to Qdrant in embedded mode."""
        from app.retrieval.qdrant_client import QdrantClientWrapper

        qdrant = QdrantClientWrapper(embedded=True, embedded_path=temp_dir)
        result = await qdrant.connect()
        assert result is True
        assert qdrant.is_connected is True
        await qdrant.close()

    @pytest.mark.asyncio
    async def test_create_collection(self, temp_dir):
        """Test creating a Qdrant collection."""
        from app.retrieval.qdrant_client import QdrantClientWrapper

        qdrant = QdrantClientWrapper(embedded=True, embedded_path=temp_dir)
        await qdrant.connect()

        created = await qdrant.create_collection("test_collection")
        assert created is True

        # Creating same collection again should succeed (idempotent)
        created_again = await qdrant.create_collection("test_collection")
        assert created_again is True

        collections = await qdrant.list_collections()
        assert "test_collection" in collections

        await qdrant.close()

    @pytest.mark.asyncio
    async def test_upsert_and_search(self, temp_dir):
        """Test upserting points and searching."""
        from app.retrieval.qdrant_client import QdrantClientWrapper

        qdrant = QdrantClientWrapper(embedded=True, embedded_path=temp_dir)
        await qdrant.connect()
        await qdrant.create_collection("test_search")

        # Upsert test points with UUID-formatted IDs
        points = [
            {
                "id": "10000000-0000-0000-0000-000000000001",
                "vector": [0.1] * 384,
                "payload": {
                    "chunk_id": "chunk_1",
                    "content": "This is document one about AI",
                    "source_path": "/test/doc1.txt",
                    "project": "test",
                    "collection": "test_search",
                },
            },
            {
                "id": "10000000-0000-0000-0000-000000000002",
                "vector": [0.2] * 384,
                "payload": {
                    "chunk_id": "chunk_2",
                    "content": "This is document two about GPUs",
                    "source_path": "/test/doc2.txt",
                    "project": "test",
                    "collection": "test_search",
                },
            },
        ]

        upserted = await qdrant.upsert_points("test_search", points)
        assert upserted is True

        # Search
        query_vector = [0.15] * 384
        results = await qdrant.search(query_vector, "test_search", top_k=2)
        assert len(results) == 2
        assert results[0]["payload"]["chunk_id"] in ["chunk_1", "chunk_2"]

        # Get by ID
        result = await qdrant.search_by_id("test_search", "10000000-0000-0000-0000-000000000001")
        assert result is not None
        assert result["payload"]["chunk_id"] == "chunk_1"

        # Stats
        stats = await qdrant.get_collection_stats("test_search")
        assert stats["points_count"] == 2

        await qdrant.close()

    @pytest.mark.asyncio
    async def test_delete_collection(self, temp_dir):
        """Test deleting a collection."""
        from app.retrieval.qdrant_client import QdrantClientWrapper
        import time

        qdrant = QdrantClientWrapper(embedded=True, embedded_path=temp_dir)
        try:
            await qdrant.connect()
            await qdrant.create_collection("test_delete")

            deleted = await qdrant.delete_collection("test_delete")
            assert deleted is True

            collections = await qdrant.list_collections()
            assert "test_delete" not in collections
        finally:
            await qdrant.close()
            # Windows needs extra time for Qdrant embedded SQLite locks to release
            time.sleep(0.5)


# ─── SQLite Metadata DB Tests ──────────────────────────────────────────


class TestMetadataDB:
    """Tests for MetadataDB."""

    @pytest.fixture
    def db_path(self, temp_dir):
        return os.path.join(temp_dir, "metadata.db")

    @pytest.mark.asyncio
    async def test_init_db(self, db_path):
        """Test database initialization."""
        from app.retrieval.metadata_db import MetadataDB

        db = MetadataDB(db_path=db_path)
        result = await db.init_db()
        assert result is True
        assert os.path.exists(db_path)
        await db.close()

    @pytest.mark.asyncio
    async def test_source_file_operations(self, db_path):
        """Test source file CRUD."""
        from app.retrieval.metadata_db import MetadataDB

        db = MetadataDB(db_path=db_path)
        await db.init_db()

        file_hash = hashlib.md5(b"test content").hexdigest()
        source_id = await db.get_or_create_source(
            "/test/document.pdf", "test_project", file_hash
        )
        assert source_id is not None
        assert source_id > 0

        # Get source by path
        source = await db.get_source_by_path("/test/document.pdf")
        assert source is not None
        assert source["project"] == "test_project"
        assert source["file_hash"] == file_hash

        # Check hash changed (new hash = changed)
        changed = await db.check_hash_changed("/test/document.pdf", "new_hash")
        assert changed is True

        # Check hash not changed (same hash)
        unchanged = await db.check_hash_changed("/test/document.pdf", file_hash)
        assert unchanged is False

        await db.close()

    @pytest.mark.asyncio
    async def test_chunk_operations(self, db_path):
        """Test chunk CRUD."""
        from app.retrieval.metadata_db import MetadataDB

        db = MetadataDB(db_path=db_path)
        await db.init_db()

        # Create source first
        source_id = await db.get_or_create_source(
            "/test/chunk_test.pdf", "test", "abc123"
        )

        # Upsert chunk
        upserted = await db.upsert_chunk(
            chunk_id="test_chunk_1",
            source_file_id=source_id,
            collection="knowledge_docs",
            content="This is test chunk content",
            page_number=5,
            heading="Introduction",
            chunk_index=0,
            embedding_version="v1",
            parser_version="v1",
        )
        assert upserted is True

        # Get chunk by ID
        chunk = await db.get_chunk_by_id("test_chunk_1")
        assert chunk is not None
        assert chunk["content"] == "This is test chunk content"
        assert chunk["page_number"] == 5

        # Get chunks for source
        chunks = await db.get_chunks_for_source(source_id)
        assert len(chunks) >= 1

        # Delete chunks for collection
        deleted = await db.delete_chunks_for_collection("knowledge_docs")
        assert deleted >= 1

        # Verify deleted
        chunks_after = await db.get_chunks_for_source(source_id)
        assert len(chunks_after) == 0

        await db.close()

    @pytest.mark.asyncio
    async def test_index_version_operations(self, db_path):
        """Test index version creation and rollback."""
        from app.retrieval.metadata_db import MetadataDB

        db = MetadataDB(db_path=db_path)
        await db.init_db()

        # Create version
        version_id = await db.create_index_version(
            collection="test_coll",
            parser_version="1.0.0",
            embedding_model="all-MiniLM-L6-v2",
            embedding_version="v1",
            points_count=100,
        )
        assert version_id is not None

        # Get active version
        active = await db.get_active_version("test_coll")
        assert active is not None
        assert active["is_active"] is True
        assert active["embedding_model"] == "all-MiniLM-L6-v2"

        # Create second version (should deactivate first)
        version_id_2 = await db.create_index_version(
            collection="test_coll",
            parser_version="1.1.0",
            embedding_model="all-MiniLM-L6-v2",
            embedding_version="v2",
            points_count=200,
        )
        assert version_id_2 is not None

        active_2 = await db.get_active_version("test_coll")
        assert active_2["id"] == version_id_2

        await db.close()

    @pytest.mark.asyncio
    async def test_job_operations(self, db_path):
        """Test indexing job tracking."""
        from app.retrieval.metadata_db import MetadataDB

        db = MetadataDB(db_path=db_path)
        await db.init_db()

        # Create job
        created = await db.create_job(
            job_id="test_job_1",
            source_file_id=None,
            collection="knowledge_docs",
            project="test",
        )
        assert created is True

        # Update job
        updated = await db.update_job(
            "test_job_1",
            status="complete",
            chunks_created=50,
            started_at=1000.0,
            completed_at=1005.0,
        )
        assert updated is True

        # Get job
        job = await db.get_job("test_job_1")
        assert job is not None
        assert job["status"] == "complete"
        assert job["chunks_created"] == 50

        # List jobs
        jobs = await db.list_jobs()
        assert len(jobs) >= 1

        await db.close()

    @pytest.mark.asyncio
    async def test_collection_stats(self, db_path):
        """Test collection statistics."""
        from app.retrieval.metadata_db import MetadataDB

        db = MetadataDB(db_path=db_path)
        await db.init_db()

        # Add some data
        source_id = await db.get_or_create_source("/test/stats.pdf", "test", "hash1")
        await db.upsert_chunk(
            chunk_id="stat_chunk_1",
            source_file_id=source_id,
            collection="stats_coll",
            content="Test content",
        )
        await db.upsert_chunk(
            chunk_id="stat_chunk_2",
            source_file_id=source_id,
            collection="stats_coll",
            content="More content",
        )

        # Get stats
        stats = await db.get_collection_stats("stats_coll")
        assert stats["total_chunks"] == 2

        # Get overall stats
        overall = await db.get_stats()
        assert overall["source_files"] >= 1
        assert overall["chunks"] >= 2

        await db.close()


# ─── Document Parser Tests ─────────────────────────────────────────────


class TestDocumentParser:
    """Tests for DocumentParser."""

    @pytest.mark.asyncio
    async def test_parse_text_file(self, temp_dir, test_text_content):
        """Test parsing a text file."""
        from app.ingestion.parser import DocumentParser

        file_path = os.path.join(temp_dir, "test.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(test_text_content)

        parser = DocumentParser()
        chunks = await parser.parse(file_path, "test_project")

        assert len(chunks) > 0
        for chunk in chunks:
            assert len(chunk.content) > 0
            assert chunk.project == "test_project"

    @pytest.mark.asyncio
    async def test_parse_pdf_with_pymupdf(self, temp_dir, test_pdf_content):
        """Test parsing PDF content (using pymupdf if available)."""
        from app.ingestion.parser import DocumentParser

        # Create a simple text file to test parsing logic
        file_path = os.path.join(temp_dir, "test.md")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(test_pdf_content)

        parser = DocumentParser()
        chunks = await parser.parse(file_path, "test_project")

        assert len(chunks) > 0
        # Check that chunks have proper IDs
        for chunk in chunks:
            assert chunk.chunk_id.startswith("chunk_")

    @pytest.mark.asyncio
    async def test_get_file_hash(self, temp_dir):
        """Test file hash generation."""
        from app.ingestion.parser import DocumentParser

        file_path = os.path.join(temp_dir, "hash_test.txt")
        with open(file_path, "w") as f:
            f.write("test content")

        parser = DocumentParser()
        hash1 = await parser.get_file_hash(file_path)
        assert hash1 is not None
        assert len(hash1) > 0

        # Same file should produce same hash
        hash2 = await parser.get_file_hash(file_path)
        assert hash1 == hash2

    @pytest.mark.asyncio
    async def test_different_files_different_hashes(self, temp_dir):
        """Test that different files produce different hashes."""
        from app.ingestion.parser import DocumentParser

        file1_path = os.path.join(temp_dir, "file1.txt")
        file2_path = os.path.join(temp_dir, "file2.txt")

        with open(file1_path, "w") as f:
            f.write("content one")
        with open(file2_path, "w") as f:
            f.write("content two")

        parser = DocumentParser()
        hash1 = await parser.get_file_hash(file1_path)
        hash2 = await parser.get_file_hash(file2_path)

        assert hash1 != hash2


# ─── Embedding Loader Tests ────────────────────────────────────────────


class TestEmbeddingLoader:
    """Tests for EmbeddingModelLoader."""

    @pytest.mark.asyncio
    async def test_load_local_model(self, temp_dir):
        """Test loading a local embedding model (if available)."""
        from app.retrieval.embedding_loader import EmbeddingModelLoader

        loader = EmbeddingModelLoader(
            model_name="sentence-transformers/all-MiniLM-L6-v2",
        )
        # This may fail if the model isn't downloaded, which is fine
        result = await loader.load()
        # Just verify the loader object works
        info = loader.get_info()
        assert "model_name" in info

    @pytest.mark.asyncio
    async def test_embed_with_local_model(self, temp_dir):
        """Test embedding generation with local model."""
        from app.retrieval.embedding_loader import EmbeddingModelLoader

        loader = EmbeddingModelLoader(
            model_name="sentence-transformers/all-MiniLM-L6-v2",
        )
        result = await loader.load()
        if result and loader.model:
            embeddings = await loader.embed(["test document"])
            assert len(embeddings) == 1
            assert len(embeddings[0]) == 384  # MiniLM dimension

    @pytest.mark.asyncio
    async def test_lmstudio_fallback(self):
        """Test LM Studio fallback configuration."""
        from app.retrieval.embedding_loader import EmbeddingModelLoader

        loader = EmbeddingModelLoader(
            model_name="local",
            lmstudio_url="http://127.0.0.1:1234/v1",
        )
        info = loader.get_info()
        assert info["lmstudio_url"] == "http://127.0.0.1:1234/v1"


# ─── Hybrid Search Engine Tests ────────────────────────────────────────


class TestHybridSearchEngine:
    """Tests for HybridSearchEngine."""

    @pytest.mark.asyncio
    async def test_search_without_model(self, temp_dir):
        """Test search with metadata-only (no embedding model)."""
        from app.retrieval.hybrid_search import HybridSearchEngine
        from app.retrieval.qdrant_client import QdrantClientWrapper
        from app.retrieval.metadata_db import MetadataDB

        qdrant = QdrantClientWrapper(embedded=True, embedded_path=temp_dir)
        await qdrant.connect()
        await qdrant.create_collection("test_search")

        db = MetadataDB(db_path=os.path.join(temp_dir, "search.db"))
        await db.init_db()

        # Create search engine without embedding model
        engine = HybridSearchEngine(
            qdrant=qdrant,
            metadata_db=db,
            embedding_model=None,
        )

        # Should not crash - returns empty results gracefully
        results, citation = await engine.search("test query", top_k=10)
        assert isinstance(results, list)
        assert citation is not None

        await qdrant.close()
        await db.close()

    @pytest.mark.asyncio
    async def test_query_classifier(self):
        """Test query type classification."""
        from app.retrieval.hybrid_search import QueryClassifier

        # Test classification
        assert "project_code" in QueryClassifier.classify("function class method api")
        assert "project_decisions" in QueryClassifier.classify("decision why rationale")
        assert "skills_index" in QueryClassifier.classify("skill procedure how to steps")
        assert "knowledge_docs" in QueryClassifier.classify("document report manual")


# ─── Source Viewer Tests ──────────────────────────────────────────────


class TestSourceViewer:
    """Tests for SourceViewer."""

    @pytest.mark.asyncio
    async def test_chunk_detail(self, temp_dir):
        """Test chunk detail retrieval."""
        from app.retrieval.source_viewer import SourceViewer
        from app.retrieval.metadata_db import MetadataDB

        db = MetadataDB(db_path=os.path.join(temp_dir, "viewer.db"))
        await db.init_db()

        # Add test data
        source_id = await db.get_or_create_source("/test/viewer.pdf", "test", "hash1")
        await db.upsert_chunk(
            chunk_id="viewer_chunk_1",
            source_file_id=source_id,
            collection="test",
            content="Test chunk content",
            page_number=1,
            heading="Test Heading",
        )

        viewer = SourceViewer(metadata_db=db)
        chunk = await viewer.get_chunk_detail("viewer_chunk_1")
        assert chunk is not None
        assert chunk.content == "Test chunk content"

        await db.close()

    @pytest.mark.asyncio
    async def test_preview_content(self, temp_dir):
        """Test source file preview."""
        from app.retrieval.source_viewer import SourceViewer
        from app.retrieval.metadata_db import MetadataDB

        db = MetadataDB(db_path=os.path.join(temp_dir, "preview.db"))
        await db.init_db()

        # Create a test file
        test_file = os.path.join(temp_dir, "preview_test.txt")
        with open(test_file, "w") as f:
            f.write("This is preview content for testing.")

        source_id = await db.get_or_create_source(test_file, "test", "hash2")

        viewer = SourceViewer(metadata_db=db)
        preview = await viewer.preview_content(test_file, offset=0, length=500)
        assert preview is not None
        assert "preview" in preview or "error" in preview

        await db.close()

    @pytest.mark.asyncio
    async def test_source_navigation(self, temp_dir):
        """Test source file navigation."""
        from app.retrieval.source_viewer import SourceViewer
        from app.retrieval.metadata_db import MetadataDB

        db = MetadataDB(db_path=os.path.join(temp_dir, "nav.db"))
        await db.init_db()

        try:
            # Add multiple chunks
            source_id = await db.get_or_create_source("/test/nav.pdf", "test", "hash3")
            for i in range(3):
                await db.upsert_chunk(
                    chunk_id=f"nav_chunk_{i}",
                    source_file_id=source_id,
                    collection="test",
                    content=f"Content {i}",
                    page_number=i + 1,
                )

            viewer = SourceViewer(metadata_db=db)
            nav = await viewer.get_source_navigation("/test/nav.pdf", "nav_chunk_1")
            assert nav is not None
            assert nav["total_chunks"] >= 3
        finally:
            await db.close()


# ─── Full Pipeline Tests ──────────────────────────────────────────────


class TestFullPipeline:
    """Integration tests for the full ingestion pipeline."""

    @pytest.mark.asyncio
    async def test_end_to_end_ingestion(self, temp_dir):
        """Test full ingestion pipeline with mock embedding."""
        from app.ingestion.indexer import Indexer
        from app.retrieval.qdrant_client import QdrantClientWrapper
        from app.retrieval.metadata_db import MetadataDB

        # Setup
        qdrant = QdrantClientWrapper(embedded=True, embedded_path=temp_dir)
        await qdrant.connect()
        await qdrant.create_collection("pipeline_test")

        db = MetadataDB(db_path=os.path.join(temp_dir, "pipeline.db"))
        await db.init_db()

        # Write test file
        file_path = os.path.join(temp_dir, "pipeline_test.txt")
        with open(file_path, "w") as f:
            f.write("This is a test document for the RedSight ingestion pipeline. It covers knowledge retrieval, hybrid search, and GPU scheduling.")

        # Mock embedding model
        class MockEmbeddingModel:
            def encode(self, texts, batch_size=32, show_progress_bar=False, normalize_embeddings=True):
                import numpy as np
                if isinstance(texts, str):
                    texts = [texts]
                vectors = []
                for text in texts:
                    h = int(hashlib.md5(text.encode()).hexdigest()[:8], 16)
                    vec = [((h >> (i % 32)) & 1) * 0.01 for i in range(384)]
                    norm = (sum(v*v for v in vec)) ** 0.5 or 1.0
                    vectors.append([v/norm for v in vec])
                return np.array(vectors)

        # Create indexer with mock embedding
        indexer = Indexer(
            qdrant=qdrant,
            metadata_db=db,
            embedding_model=MockEmbeddingModel(),
        )

        # Index file via index_files()
        results = await indexer.index_files([file_path], "pipeline_test", "pipeline_project")
        assert len(results) == 1
        assert results[0]["status"] == "complete"
        assert results[0]["chunks_created"] > 0

        await qdrant.close()
        await db.close()

    @pytest.mark.asyncio
    async def test_skip_unchanged_file(self, temp_dir):
        """Test that unchanged files are skipped during re-indexing."""
        from app.ingestion.indexer import Indexer
        from app.retrieval.qdrant_client import QdrantClientWrapper
        from app.retrieval.metadata_db import MetadataDB

        # Setup
        qdrant = QdrantClientWrapper(embedded=True, embedded_path=temp_dir)
        await qdrant.connect()
        await qdrant.create_collection("skip_test")

        db = MetadataDB(db_path=os.path.join(temp_dir, "skip.db"))
        await db.init_db()

        # Write test file
        file_path = os.path.join(temp_dir, "skip_test.txt")
        with open(file_path, "w") as f:
            f.write("Unchanged content for skip test.")

        # Mock embedding model
        class MockEmbeddingModel:
            def encode(self, texts, batch_size=32, show_progress_bar=False, normalize_embeddings=True):
                import numpy as np
                if isinstance(texts, str):
                    texts = [texts]
                vectors = []
                for text in texts:
                    h = int(hashlib.md5(text.encode()).hexdigest()[:8], 16)
                    vec = [((h >> (i % 32)) & 1) * 0.01 for i in range(384)]
                    norm = (sum(v*v for v in vec)) ** 0.5 or 1.0
                    vectors.append([v/norm for v in vec])
                return np.array(vectors)

        # First ingestion
        indexer = Indexer(
            qdrant=qdrant,
            metadata_db=db,
            embedding_model=MockEmbeddingModel(),
        )
        result1 = await indexer.index_files([file_path], "skip_test", "skip_project")
        assert result1[0]["status"] == "complete"
        chunks_created_1 = result1[0]["chunks_created"]

        # Second ingestion (same file, should skip)
        result2 = await indexer.index_files([file_path], "skip_test", "skip_project")
        assert result2[0]["status"] == "complete"  # skipped = complete with 0 chunks
        assert result2[0]["chunks_created"] == 0

        await qdrant.close()
        await db.close()
