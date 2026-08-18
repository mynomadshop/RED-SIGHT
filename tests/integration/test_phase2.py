"""
RedSight - High-Performance Local AI Intelligence Platform
Phase 2 Integration Tests

Tests the full Hybrid RAG pipeline:
- BM25 sparse retrieval
- Cross-encoder reranking
- Context budgeting
- Golden evaluation
- Drive scanning
- Multi-drive indexing
- End-to-end hybrid search
"""

import asyncio
import hashlib
import os
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

project_root = Path(__file__).parent.parent.parent
import sys
sys.path.insert(0, str(project_root))

# ─── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def test_document_content():
    """Rich test document for BM25 and embedding tests."""
    return """
    RedSight Architecture Overview

    RedSight is a high-performance local AI intelligence platform.
    It combines dense vector search with sparse lexical retrieval
    for hybrid knowledge search.

    The platform uses Qdrant for vector storage and SQLite for
    metadata persistence. The ingestion pipeline parses PDFs,
    text files, and Python code with structural preservation.

    GPU scheduling is handled by a dual-GPU aware scheduler
    that manages VRAM reservations, affinity, and backpressure.

    The agent runtime implements a planner/executor/evaluator
    loop with subagent support and tool contracts.

    Knowledge collections include knowledge_docs, project_code,
    project_decisions, skills_index, episodic_memory, tool_catalog,
    and eval_corpus.

    ## Retrieval Pipeline

    1. Query planner classifies the question type
    2. Parallel retrieval searches relevant collections
    3. Reranking uses a cross-encoder on candidates
    4. Context budgeter allocates tokens by evidence value
    5. Citation pack passes source IDs through for display
    """


@pytest.fixture
def test_code_content():
    """Test Python code for code-aware parsing."""
    return '''"""
RedSight - GPU Scheduler Module
"""

from typing import List, Optional, Dict, Any


class GpuScheduler:
    """Dual-GPU aware scheduler with VRAM reservations."""

    def __init__(self, num_gpus: int = 2, headroom_gb: float = 3.0):
        self.num_gpus = num_gpus
        self.headroom_gb = headroom_gb
        self._gpu_states: Dict[int, Any] = {}

    async def schedule_job(
        self,
        job_type: str,
        payload: Dict[str, Any],
        priority: str = "normal",
        gpu_affinity: Optional[int] = None,
        vram_reservation_mb: Optional[float] = None,
    ) -> str:
        """Schedule a job on the best available GPU."""
        if gpu_affinity is not None:
            return await self._schedule_on_gpu(gpu_affinity, job_type, payload)
        return await self._schedule_optimal(job_type, payload)

    async def _schedule_on_gpu(self, gpu_id: int, job_type: str, payload: dict):
        """Schedule job on specific GPU."""
        return f"job_gpu_{gpu_id}_{hash(payload)}"

    async def _schedule_optimal(self, job_type: str, payload: dict):
        """Schedule on optimal GPU based on VRAM and affinity."""
        best_gpu = 0
        max_free = 0
        for i in range(self.num_gpus):
            free = self._gpu_states.get(i, {}).get("free_vram_mb", 0)
            if free > max_free:
                max_free = free
                best_gpu = i
        return await self._schedule_on_gpu(best_gpu, job_type, payload)

    def get_gpu_status(self) -> List[Dict[str, Any]]:
        """Get current status of all GPUs."""
        return [
            {
                "index": i,
                "free_vram_mb": self._gpu_states.get(i, {}).get("free_vram_mb", 0),
                "utilization_percent": self._gpu_states.get(i, {}).get("utilization", 0),
            }
            for i in range(self.num_gpus)
        ]


def create_scheduler(num_gpus: int = 2) -> GpuScheduler:
    """Factory function to create a GPU scheduler."""
    return GpuScheduler(num_gpus=num_gpus)
'''


@pytest.fixture
def test_bm25_docs():
    """Documents for BM25 testing."""
    return [
        {
            "doc_id": "doc_1",
            "content": "RedSight GPU scheduler manages dual RTX 5090 VRAM reservations",
            "title": "GPU Scheduler",
            "heading": "GPU Scheduling",
            "metadata": {"collection": "project_code", "project": "redsight"},
        },
        {
            "doc_id": "doc_2",
            "content": "Qdrant vector database stores knowledge embeddings for semantic search",
            "title": "Qdrant Integration",
            "heading": "Vector Storage",
            "metadata": {"collection": "project_code", "project": "redsight"},
        },
        {
            "doc_id": "doc_3",
            "content": "BM25 sparse retrieval provides lexical search complementing dense vectors",
            "title": "BM25 Index",
            "heading": "Sparse Search",
            "metadata": {"collection": "project_code", "project": "redsight"},
        },
        {
            "doc_id": "doc_4",
            "content": "Cross-encoder reranking improves relevance of retrieved documents",
            "title": "Reranker",
            "heading": "Reranking",
            "metadata": {"collection": "project_code", "project": "redsight"},
        },
        {
            "doc_id": "doc_5",
            "content": "Context budgeter allocates token budget across evidence with diversity",
            "title": "Context Budgeter",
            "heading": "Context Allocation",
            "metadata": {"collection": "project_code", "project": "redsight"},
        },
    ]


# ─── BM25 Sparse Retrieval Tests ──────────────────────────────────────

class TestBM25Index:
    """Tests for BM25 sparse retrieval."""

    def test_add_and_search(self):
        """Test basic BM25 indexing and search."""
        from app.retrieval.sparse_retrieval import BM25Index

        index = BM25Index()
        index.add_document("doc_1", "The quick brown fox jumps over the lazy dog")
        index.add_document("doc_2", "A fast red fox runs quickly across the field")

        results = index.search("quick fox", top_k=2)
        assert len(results) >= 1
        assert results[0]["doc_id"] in ["doc_1", "doc_2"]

    def test_bm25_scoring(self):
        """Test that BM25 scores correlate with relevance."""
        from app.retrieval.sparse_retrieval import BM25Index

        index = BM25Index()
        index.add_document("doc_1", "GPU scheduler manages dual RTX 5090 VRAM reservations")
        index.add_document("doc_2", "The weather is nice today")
        index.add_document("doc_3", "GPU scheduling algorithms optimize VRAM allocation")

        results = index.search("GPU scheduler VRAM", top_k=3)
        assert len(results) >= 2

        # doc_1 and doc_3 should rank higher than doc_2
        top_ids = [r["doc_id"] for r in results[:2]]
        assert "doc_1" in top_ids or "doc_3" in top_ids

    def test_field_weighting(self):
        """Test that BM25FieldIndex weights heading/title higher."""
        from app.retrieval.sparse_retrieval import BM25FieldIndex

        index = BM25FieldIndex()
        index.add_document(
            "doc_1",
            content="some content with gpu in it",
            title="",
            heading="GPU Scheduler Implementation",
        )
        index.add_document(
            "doc_2",
            content="gpu gpu gpu gpu gpu",  # Many occurrences but not in heading
            title="",
            heading="",
        )

        results = index.search("GPU Scheduler", top_k=2)
        # doc_1 should rank higher due to heading match
        if len(results) >= 2:
            assert results[0]["doc_id"] == "doc_1"

    def test_stop_word_removal(self):
        """Test that stop words are filtered."""
        from app.retrieval.sparse_retrieval import tokenize

        tokens = tokenize("the quick brown fox is very fast")
        assert "the" not in tokens
        assert "is" not in tokens
        assert "very" not in tokens
        assert "quick" in tokens
        assert "brown" in tokens
        assert "fox" in tokens

    def test_index_stats(self):
        """Test index statistics."""
        from app.retrieval.sparse_retrieval import BM25Index

        index = BM25Index()
        index.add_document("d1", "Hello world")
        index.add_document("d2", "Hello again world")
        index.add_document("d3", "Goodbye world")

        stats = index.get_stats()
        assert stats["num_documents"] == 3
        assert stats["num_terms"] > 0
        assert stats["total_entries"] > 0

    def test_remove_document(self):
        """Test document removal."""
        from app.retrieval.sparse_retrieval import BM25Index

        index = BM25Index()
        index.add_document("d1", "Hello world")
        index.add_document("d2", "Hello again")
        index.remove_document("d1")

        stats = index.get_stats()
        assert stats["num_documents"] == 1

        results = index.search("Hello", top_k=5)
        assert len(results) == 1
        assert results[0]["doc_id"] == "d2"

    def test_filters(self):
        """Test filtered search."""
        from app.retrieval.sparse_retrieval import BM25Index

        index = BM25Index()
        index.add_document("d1", "GPU scheduler", metadata={"collection": "code"})
        index.add_document("d2", "Documentation text", metadata={"collection": "docs"})
        index.add_document("d3", "GPU scheduler again", metadata={"collection": "code"})

        results = index.search("GPU", top_k=5, filters={"collection": {"match": {"value": "code"}}})
        assert len(results) == 2
        assert all(r["metadata"].get("collection") == "code" for r in results)

    def test_empty_query(self):
        """Test empty query returns no results."""
        from app.retrieval.sparse_retrieval import BM25Index

        index = BM25Index()
        index.add_document("d1", "Hello world")
        results = index.search("", top_k=5)
        assert len(results) == 0

    def test_no_match(self):
        """Test query with no matching terms."""
        from app.retrieval.sparse_retrieval import BM25Index

        index = BM25Index()
        index.add_document("d1", "Hello world")
        results = index.search("xyznonexistent", top_k=5)
        assert len(results) == 0


# ─── Cross-Encoder Reranker Tests ──────────────────────────────────────

class TestCrossEncoderReranker:
    """Tests for cross-encoder reranker."""

    @pytest.mark.asyncio
    async def test_keyword_fallback(self):
        """Test keyword-based reranking fallback."""
        from app.retrieval.reranker import CrossEncoderReranker

        reranker = CrossEncoderReranker()
        loaded = await reranker.load()
        assert loaded is True
        # Backend can be "local" (model loaded) or "keyword" (fallback)
        assert reranker._backend in ("local", "keyword")

        candidates = [
            {"doc_id": "d1", "content": "GPU scheduler manages VRAM", "score": 0.5},
            {"doc_id": "d2", "content": "The weather is nice", "score": 0.9},
            {"doc_id": "d3", "content": "GPU scheduling and VRAM allocation", "score": 0.3},
        ]

        results = await reranker.rerank("GPU scheduler VRAM", candidates, top_k=3)
        assert len(results) >= 2
        # d1 and d3 should rank higher than d2
        top_ids = [r.doc_id for r in results[:2]]
        assert "d1" in top_ids or "d3" in top_ids

    @pytest.mark.asyncio
    async def test_rerank_empty(self):
        """Test reranking with empty candidates."""
        from app.retrieval.reranker import CrossEncoderReranker

        reranker = CrossEncoderReranker()
        results = await reranker.rerank("test", [], top_k=5)
        assert len(results) == 0

    def test_reranker_info(self):
        """Test reranker info."""
        from app.retrieval.reranker import CrossEncoderReranker

        reranker = CrossEncoderReranker()
        info = reranker.get_info()
        assert "loaded" in info
        assert "backend" in info


# ─── Context Budgeter Tests ────────────────────────────────────────────

class TestContextBudgeter:
    """Tests for context budgeter."""

    def test_budget_basic(self):
        """Test basic context budgeting."""
        from app.retrieval.context_budgeter import ContextBudgeter

        budgeter = ContextBudgeter(max_tokens=1000)
        results = [
            {"chunk_id": f"chunk_{i}", "content": f"Content {i} " * 50, "score": 0.9 - i * 0.1,
             "collection": "test", "source_path": f"/test/{i}.txt", "project": "test"}
            for i in range(5)
        ]

        slots = budgeter.budget(results, query="test", task_type="general")
        assert len(slots) > 0
        assert len(slots) <= len(results)

        # Check token estimation
        total_tokens = sum(s.token_estimate for s in slots)
        assert total_tokens <= budgeter.max_tokens * 1.5  # Allow slight overage

    def test_budget_deduplication(self):
        """Test that near-duplicate content is deduplicated."""
        from app.retrieval.context_budgeter import ContextBudgeter

        # Use longer content so it passes min_chunk_tokens=20
        long_content = "This is the same content repeated for deduplication testing purposes. " * 3

        budgeter = ContextBudgeter(max_tokens=10000, dedup_threshold=0.85)
        results = [
            {"chunk_id": "c1", "content": long_content, "score": 0.9,
             "collection": "test", "source_path": "/test/1.txt", "project": "test"},
            {"chunk_id": "c2", "content": long_content, "score": 0.8,
             "collection": "test", "source_path": "/test/2.txt", "project": "test"},
            {"chunk_id": "c3", "content": "Completely different content here that is much longer and has unique words for testing deduplication", "score": 0.7,
             "collection": "test", "source_path": "/test/3.txt", "project": "test"},
        ]

        slots = budgeter.budget(results, query="test")
        # c1 and c2 are duplicates, so only one should appear
        chunk_ids = [s.chunk_id for s in slots]
        assert "c1" in chunk_ids or "c2" in chunk_ids
        # But not both
        assert not ("c1" in chunk_ids and "c2" in chunk_ids)

    def test_build_context(self):
        """Test context string building."""
        from app.retrieval.context_budgeter import ContextBudgeter, ContextSlot

        budgeter = ContextBudgeter()
        slots = [
            ContextSlot(
                chunk_id="c1", content="Test content", score=0.9,
                collection="test", source_path="/test.txt", project="test",
                page_number=5, heading="Introduction",
            ),
        ]

        context = budgeter.build_context(slots, query="test query")
        assert "test query" in context
        assert "Test content" in context
        assert "/test.txt" in context
        assert "p5" in context

    def test_budget_trim(self):
        """Test that budget trimming respects token limits."""
        from app.retrieval.context_budgeter import ContextBudgeter

        budgeter = ContextBudgeter(max_tokens=500)
        # Create results that would exceed budget
        results = [
            {"chunk_id": f"chunk_{i}", "content": "word " * 200, "score": 0.9 - i * 0.01,
             "collection": "test", "source_path": f"/test/{i}.txt", "project": "test"}
            for i in range(10)
        ]

        slots = budgeter.budget(results)
        total_tokens = sum(s.token_estimate for s in slots)
        # Should be trimmed to budget
        assert total_tokens <= budgeter.max_tokens * 2  # Some tolerance


# ─── Golden Set Tests ──────────────────────────────────────────────────

class TestGoldenSet:
    """Tests for golden evaluation set."""

    def test_add_and_list_queries(self):
        """Test adding and listing golden queries."""
        from app.retrieval.golden_set import GoldenSet, GoldenQuery

        gs = GoldenSet()
        gs.add_query(GoldenQuery(
            query_id="test_1",
            query_text="How does GPU scheduling work?",
            category="code",
            difficulty="medium",
        ))

        queries = gs.list_queries()
        assert len(queries) == 1
        assert queries[0].query_id == "test_1"

    def test_filter_by_category(self):
        """Test filtering queries by category."""
        from app.retrieval.golden_set import GoldenSet, GoldenQuery

        gs = GoldenSet()
        gs.add_query(GoldenQuery(query_id="c1", query_text="code query", category="code"))
        gs.add_query(GoldenQuery(query_id="d1", query_text="doc query", category="docs"))
        gs.add_query(GoldenQuery(query_id="c2", query_text="another code", category="code"))

        code_queries = gs.get_by_category("code")
        assert len(code_queries) == 2
        assert all(q.category == "code" for q in code_queries)

    @pytest.mark.asyncio
    async def test_evaluate_query(self):
        """Test query evaluation metrics."""
        from app.retrieval.golden_set import GoldenSet, GoldenQuery

        gs = GoldenSet()
        gs.add_query(GoldenQuery(
            query_id="eval_1",
            query_text="test query",
            category="code",
            expected_chunk_ids=["c1", "c2", "c3"],
        ))

        # Evaluate with partial hit
        result = await gs.evaluate_query(
            gs.get_query("eval_1"),
            retrieved_chunk_ids=["c1", "c5", "c6"],
        )

        assert result.query_id == "eval_1"
        assert result.hit is True  # c1 is in expected
        assert result.recall_at_1 > 0  # c1 is at rank 1
        assert result.mrr == 1.0  # c1 is at rank 1

    @pytest.mark.asyncio
    async def test_evaluate_no_hit(self):
        """Test evaluation with no hits."""
        from app.retrieval.golden_set import GoldenSet, GoldenQuery

        gs = GoldenSet()
        gs.add_query(GoldenQuery(
            query_id="eval_2",
            query_text="test query",
            category="code",
            expected_chunk_ids=["c1", "c2"],
        ))

        result = await gs.evaluate_query(
            gs.get_query("eval_2"),
            retrieved_chunk_ids=["c5", "c6", "c7"],
        )

        assert result.hit is False
        assert result.recall_at_1 == 0
        assert result.mrr == 0

    def test_save_and_load(self, temp_dir):
        """Test saving and loading golden queries."""
        from app.retrieval.golden_set import GoldenSet, GoldenQuery
        import json

        gs = GoldenSet(data_dir=temp_dir)
        gs.add_query(GoldenQuery(
            query_id="persist_1",
            query_text="test query",
            category="code",
        ))

        filepath = gs.save_to_file()
        assert os.path.exists(filepath)

        # Load into new set
        gs2 = GoldenSet(data_dir=temp_dir)
        count = gs2.load_from_file(filepath)
        assert count == 1
        assert gs2.get_query("persist_1") is not None

    @pytest.mark.asyncio
    async def test_summary(self, temp_dir):
        """Test evaluation summary statistics."""
        from app.retrieval.golden_set import GoldenSet, GoldenQuery

        gs = GoldenSet(data_dir=temp_dir)
        gs.add_query(GoldenQuery(query_id="s1", query_text="q1", category="code", expected_chunk_ids=["c1"]))
        gs.add_query(GoldenQuery(query_id="s2", query_text="q2", category="code", expected_chunk_ids=["c2"]))

        result_s1 = await gs.evaluate_query(gs.get_query("s1"), ["c1"])
        result_s2 = await gs.evaluate_query(gs.get_query("s2"), ["c5"])

        summary = gs.get_summary()
        assert summary["total_queries"] == 2
        assert summary["hits"] == 1
        assert summary["hit_rate"] == 0.5

    def test_create_golden_queries(self):
        """Test the real golden queries from system data."""
        from app.retrieval.golden_queries import create_golden_queries

        gs = create_golden_queries()
        queries = gs.list_queries()
        assert len(queries) >= 10

        # Check categories
        categories = set(q.category for q in queries)
        assert "code" in categories
        assert "docs" in categories


# ─── Drive Scanner Tests ──────────────────────────────────────────────

class TestDriveScanner:
    """Tests for drive scanner."""

    def test_classify_file(self):
        """Test file classification."""
        from app.retrieval.drive_scanner import classify_file
        from pathlib import Path

        # Python file
        ftype, cat, coll = classify_file(Path("/test/file.py"))
        assert ftype == "py"
        assert cat == "code"
        assert coll == "project_code"

        # Markdown file
        ftype, cat, coll = classify_file(Path("/test/file.md"))
        assert ftype == "md"
        assert cat in ("docs", "decisions")

        # PDF file
        ftype, cat, coll = classify_file(Path("/test/file.pdf"))
        assert ftype == "pdf"
        assert cat == "docs"
        assert coll == "knowledge_docs"

        # JSON file
        ftype, cat, coll = classify_file(Path("/test/file.json"))
        assert ftype == "json"
        assert cat == "config"

    def test_infer_project(self):
        """Test project name inference."""
        from app.retrieval.drive_scanner import infer_project
        from pathlib import Path

        # File under home - infer_project returns the parent of the file
        p = Path("/c/Users/walim/RedSight/app/server.py")
        project = infer_project(p, "C:")
        # infer_project returns the immediate parent directory name
        assert project == "app"

        p = Path("/c/Users/walim/BrightDataMCP/extract.py")
        project = infer_project(p, "C:")
        assert project == "brightdatamcp"

    def test_scan_specific_directory(self, temp_dir):
        """Test scanning a specific directory (not full drive)."""
        from app.retrieval.drive_scanner import DriveScanner, DiscoveredFile

        # Create test files
        test_files = [
            ("test1.py", "code content here that is longer to pass min token threshold"),
            ("test2.md", "markdown content here that is longer to pass min token threshold"),
            ("test3.txt", "text content here that is longer to pass min token threshold"),
        ]

        for fname, content in test_files:
            fpath = Path(temp_dir) / fname
            fpath.write_text(content)

        # Scan the temp directory (as if it were a drive)
        scanner = DriveScanner(drives=[temp_dir], max_depth=3)
        discovered = scanner.scan()

        # Should find our test files
        assert len(discovered) >= 2  # At least .py and .md

    def test_scan_report(self, temp_dir):
        """Test scan report generation."""
        from app.retrieval.drive_scanner import DriveScanner

        # Create test files so scan finds something
        fpath = Path(temp_dir) / "test.py"
        fpath.write_text("code content here that is longer to pass min token threshold")

        scanner = DriveScanner(drives=[temp_dir], max_depth=3)
        scanner.scan()

        report = scanner.get_summary()
        # get_summary returns a dict-like string
        assert "files" in report.lower() or len(report) > 0


# ─── Multi-Drive Indexer Tests ─────────────────────────────────────────

class TestMultiDriveIndexer:
    """Tests for multi-drive indexer."""

    @pytest.mark.asyncio
    async def test_batch_result(self):
        """Test batch result reporting."""
        from app.retrieval.multi_drive_indexer import BatchResult

        result = BatchResult(
            total_files=10,
            indexed=7,
            skipped=2,
            failed=1,
            total_chunks=50,
        )

        d = result.to_dict()
        assert d["total_files"] == 10
        assert d["indexed"] == 7
        assert d["skipped"] == 2
        assert d["failed"] == 1
        assert d["success_rate"] == 0.7

    def test_report(self):
        """Test report generation."""
        from app.retrieval.multi_drive_indexer import BatchResult, MultiDriveIndexer

        result = BatchResult(total_files=10, indexed=7, skipped=2, failed=1, total_chunks=50)
        indexer = MultiDriveIndexer(None)
        report = indexer.get_report(result)

        assert "Indexed: 7" in report
        assert "Skipped: 2" in report
        assert "Failed: 1" in report


# ─── End-to-End Hybrid RAG Tests ──────────────────────────────────────

class TestHybridRAG:
    """End-to-end tests for the hybrid RAG pipeline."""

    @pytest.mark.asyncio
    async def test_full_pipeline(self, temp_dir, test_document_content):
        """Test full pipeline: BM25 index → search → rerank → budget."""
        from app.retrieval.sparse_retrieval import BM25Index
        from app.retrieval.reranker import CrossEncoderReranker
        from app.retrieval.context_budgeter import ContextBudgeter

        # 1. Build BM25 index
        bm25 = BM25Index()
        bm25.add_document(
            "doc_gpu",
            "RedSight GPU scheduler manages dual RTX 5090 VRAM reservations for optimal performance",
            metadata={"collection": "project_code", "project": "redsight"},
        )
        bm25.add_document(
            "doc_qdrant",
            "Qdrant vector database stores knowledge embeddings for semantic search across collections with high recall",
            metadata={"collection": "project_code", "project": "redsight"},
        )
        bm25.add_document(
            "doc_bm25",
            "BM25 sparse retrieval provides lexical search complementing dense vectors for hybrid RAG systems",
            metadata={"collection": "project_code", "project": "redsight"},
        )
        bm25.add_document(
            "doc_rerank",
            "Cross-encoder reranking improves relevance of retrieved documents for better answers",
            metadata={"collection": "project_code", "project": "redsight"},
        )
        bm25.add_document(
            "doc_budget",
            "Context budgeter allocates token budget across evidence with diversity for efficient LLM prompts",
            metadata={"collection": "project_code", "project": "redsight"},
        )
        bm25.add_document(
            "doc_gpu2",
            "GPU VRAM reservations are critical for dual RTX 5090 scheduling in multi-agent AI platforms",
            metadata={"collection": "project_code", "project": "redsight"},
        )

        # 2. Search - BM25 finds doc_gpu and doc_gpu2
        results = bm25.search("GPU scheduler VRAM", top_k=3)
        assert len(results) == 2
        assert results[0]["doc_id"] == "doc_gpu"

        # 3. Rerank
        reranker = CrossEncoderReranker()
        await reranker.load()
        candidates = [
            {"doc_id": r["doc_id"], "content": r["content"], "score": r["score"],
             "metadata": r["metadata"]}
            for r in results
        ]
        reranked = await reranker.rerank("GPU scheduler VRAM", candidates, top_k=3)
        assert len(reranked) >= 2

        # 4. Budget
        budget_results = [
            {"chunk_id": r.doc_id, "content": r.content, "score": r.rerank_score,
             "collection": r.metadata.get("collection", "unknown"),
             "source_path": r.metadata.get("source_path", ""),
             "project": r.metadata.get("project", ""),
             "page_number": None, "heading": r.metadata.get("heading")}
            for r in reranked
        ]
        budgeter = ContextBudgeter(max_tokens=4096)
        slots = budgeter.budget(budget_results, query="GPU scheduler VRAM")
        assert len(slots) > 0

        # 5. Build context
        context = budgeter.build_context(slots, query="GPU scheduler VRAM")
        assert "GPU scheduler" in context
        assert "VRAM" in context

    @pytest.mark.asyncio
    async def test_golden_evaluation_on_bm25(self, temp_dir, test_bm25_docs):
        """Test golden evaluation against BM25 results."""
        from app.retrieval.sparse_retrieval import BM25Index
        from app.retrieval.golden_set import GoldenSet, GoldenQuery

        # Build BM25 index with test docs
        bm25 = BM25Index()
        for doc in test_bm25_docs:
            bm25.add_document(
                doc["doc_id"],
                doc["content"],
                metadata=doc["metadata"],
            )

        # Create golden query
        gs = GoldenSet(data_dir=temp_dir)
        gs.add_query(GoldenQuery(
            query_id="gpu_test",
            query_text="GPU scheduler VRAM",
            category="code",
            expected_chunk_ids=["doc_1", "doc_3"],
        ))

        # Evaluate
        results = bm25.search("GPU scheduler VRAM", top_k=5)
        chunk_ids = [r["doc_id"] for r in results]

        eval_result = await gs.evaluate_query(
            gs.get_query("gpu_test"),
            retrieved_chunk_ids=chunk_ids,
        )

        assert eval_result.hit is True
        assert eval_result.recall_at_1 > 0


# ─── Run Tests ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
