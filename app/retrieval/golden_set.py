"""
RedSight - High-Performance Local AI Intelligence Platform
Golden Evaluation Set

Curated queries with expected results for measuring retrieval quality.
Used for:
- Regression testing
- Benchmarking model/index changes
- Measuring recall@k, MRR, nDCG

Blueprint §13: "Use your real workflows. Build 30-100 representative tasks."
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class GoldenQuery:
    """A single golden evaluation query."""
    query_id: str
    query_text: str
    category: str  # code, docs, decisions, skills, general
    expected_chunk_ids: List[str] = field(default_factory=list)
    expected_source_paths: List[str] = field(default_factory=list)
    expected_collections: List[str] = field(default_factory=list)
    difficulty: str = "easy"  # easy, medium, hard
    description: str = ""
    task_type: str = "general"  # code, general, decision, mixed

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query_id": self.query_id,
            "query_text": self.query_text,
            "category": self.category,
            "expected_chunk_ids": self.expected_chunk_ids,
            "expected_source_paths": self.expected_source_paths,
            "expected_collections": self.expected_collections,
            "difficulty": self.difficulty,
            "description": self.description,
            "task_type": self.task_type,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GoldenQuery":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class EvaluationResult:
    """Result of evaluating a golden query."""
    query_id: str
    query_text: str
    retrieved_chunk_ids: List[str] = field(default_factory=list)
    retrieved_source_paths: List[str] = field(default_factory=list)
    recall_at_1: float = 0.0
    recall_at_5: float = 0.0
    recall_at_10: float = 0.0
    recall_at_20: float = 0.0
    mrr: float = 0.0  # Mean Reciprocal Rank
    ndcg_at_5: float = 0.0
    ndcg_at_10: float = 0.0
    hit: bool = False  # Any expected result in top 20
    precision_at_5: float = 0.0
    precision_at_10: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query_id": self.query_id,
            "query_text": self.query_text,
            "retrieved_chunk_ids": self.retrieved_chunk_ids,
            "retrieved_source_paths": self.retrieved_source_paths,
            "recall_at_1": round(self.recall_at_1, 4),
            "recall_at_5": round(self.recall_at_5, 4),
            "recall_at_10": round(self.recall_at_10, 4),
            "recall_at_20": round(self.recall_at_20, 4),
            "mrr": round(self.mrr, 4),
            "ndcg_at_5": round(self.ndcg_at_5, 4),
            "ndcg_at_10": round(self.ndcg_at_10, 4),
            "hit": self.hit,
            "precision_at_5": round(self.precision_at_5, 4),
            "precision_at_10": round(self.precision_at_10, 4),
        }


class GoldenSet:
    """
    Golden evaluation set for RAG quality measurement.

    Manages a curated set of queries with expected results,
    runs evaluations, and tracks metrics over time.
    """

    def __init__(self, data_dir: str = "./data/evals"):
        self._data_dir = data_dir
        self._queries: Dict[str, GoldenQuery] = {}
        self._results: Dict[str, EvaluationResult] = {}

    def add_query(self, query: GoldenQuery) -> None:
        """Add a golden query."""
        self._queries[query.query_id] = query
        logger.info(f"Added golden query: {query.query_id} — {query.query_text[:50]}...")

    def remove_query(self, query_id: str) -> bool:
        """Remove a golden query."""
        if query_id in self._queries:
            del self._queries[query_id]
            return True
        return False

    def get_query(self, query_id: str) -> Optional[GoldenQuery]:
        """Get a golden query by ID."""
        return self._queries.get(query_id)

    def list_queries(self) -> List[GoldenQuery]:
        """List all golden queries."""
        return list(self._queries.values())

    def get_by_category(self, category: str) -> List[GoldenQuery]:
        """Get queries by category."""
        return [q for q in self._queries.values() if q.category == category]

    def get_by_difficulty(self, difficulty: str) -> List[GoldenQuery]:
        """Get queries by difficulty."""
        return [q for q in self._queries.values() if q.difficulty == difficulty]

    def load_from_file(self, filepath: str) -> int:
        """Load golden queries from a JSON file."""
        path = Path(filepath)
        if not path.exists():
            logger.warning(f"Golden set file not found: {filepath}")
            return 0

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            count = 0
            for item in data:
                if isinstance(item, dict) and "query_id" in item:
                    query = GoldenQuery.from_dict(item)
                    self._queries[query.query_id] = query
                    count += 1

            logger.info(f"Loaded {count} golden queries from {filepath}")
            return count

        except Exception as e:
            logger.error(f"Failed to load golden set: {e}")
            return 0

    def save_to_file(self, filepath: Optional[str] = None) -> str:
        """Save golden queries to a JSON file."""
        if not filepath:
            filepath = os.path.join(self._data_dir, "golden_queries.json")

        Path(filepath).parent.mkdir(parents=True, exist_ok=True)

        data = [q.to_dict() for q in self._queries.values()]
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        logger.info(f"Saved {len(data)} golden queries to {filepath}")
        return filepath

    async def evaluate_query(
        self,
        query: GoldenQuery,
        retrieved_chunk_ids: List[str],
        retrieved_source_paths: Optional[List[str]] = None,
    ) -> EvaluationResult:
        """
        Evaluate retrieval results against a golden query.

        Computes recall@k, MRR, nDCG, precision@k.
        """
        result = EvaluationResult(
            query_id=query.query_id,
            query_text=query.query_text,
            retrieved_chunk_ids=retrieved_chunk_ids,
            retrieved_source_paths=retrieved_source_paths or [],
        )

        expected_ids = set(query.expected_chunk_ids)
        retrieved_ids = set(retrieved_chunk_ids)

        if not expected_ids:
            # No expected results — just report hits
            result.hit = len(retrieved_ids) > 0
            return result

        # Recall@k
        for k in [1, 5, 10, 20]:
            retrieved_at_k = retrieved_ids if k >= len(retrieved_chunk_ids) else set(retrieved_chunk_ids[:k])
            hits = len(expected_ids & retrieved_at_k)
            result.__setattr__(f"recall_at_{k}", hits / len(expected_ids))

        # Hit@20
        result.hit = bool(expected_ids & retrieved_ids)

        # Precision@k
        for k in [5, 10]:
            retrieved_at_k = retrieved_ids if k >= len(retrieved_chunk_ids) else set(retrieved_chunk_ids[:k])
            hits = len(expected_ids & retrieved_at_k)
            result.__setattr__(f"precision_at_{k}", hits / k)

        # MRR (Mean Reciprocal Rank)
        for rank, chunk_id in enumerate(retrieved_chunk_ids, 1):
            if chunk_id in expected_ids:
                result.mrr = 1.0 / rank
                break

        # nDCG@k
        for k in [5, 10]:
            result.__setattr__(f"ndcg_at_{k}", self._compute_ndcg(retrieved_chunk_ids, expected_ids, k))

        self._results[query.query_id] = result
        return result

    def _compute_ndcg(
        self,
        retrieved: List[str],
        relevant: Set[str],
        k: int,
    ) -> float:
        """Compute Normalized Discounted Cumulative Gain."""
        retrieved_at_k = retrieved[:k]

        # DCG
        dcg = 0.0
        for i, chunk_id in enumerate(retrieved_at_k):
            if chunk_id in relevant:
                dcg += 1.0 / math.log2(i + 2)  # i+2 because log2(1) = 0

        # IDCG (ideal DCG)
        num_relevant = min(len(relevant), k)
        idcg = sum(1.0 / math.log2(i + 2) for i in range(num_relevant))

        return dcg / idcg if idcg > 0 else 0.0

    async def evaluate_all(
        self,
        search_fn,
    ) -> Dict[str, EvaluationResult]:
        """
        Evaluate all golden queries against a search function.

        Args:
            search_fn: Async function(query, top_k) -> (results, citation)

        Returns:
            Dict of query_id -> EvaluationResult
        """
        results = {}

        for query_id, query in self._queries.items():
            try:
                retrieved, _ = await search_fn(query.query_text, top_k=20)

                chunk_ids = [r.get("chunk_id", "") for r in retrieved]
                source_paths = [r.get("source_path", "") for r in retrieved]

                result = await self.evaluate_query(query, chunk_ids, source_paths)
                results[query_id] = result

            except Exception as e:
                logger.error(f"Evaluation failed for {query_id}: {e}")
                results[query_id] = EvaluationResult(
                    query_id=query_id,
                    query_text=query.query_text,
                )

        return results

    def get_summary(self) -> Dict[str, Any]:
        """Get evaluation summary statistics."""
        if not self._results:
            return {"error": "No results available. Run evaluate_all() first."}

        total = len(self._results)
        hits = sum(1 for r in self._results.values() if r.hit)

        avg_recall_1 = sum(r.recall_at_1 for r in self._results.values()) / total
        avg_recall_5 = sum(r.recall_at_5 for r in self._results.values()) / total
        avg_mrr = sum(r.mrr for r in self._results.values()) / total
        avg_ndcg_5 = sum(r.ndcg_at_5 for r in self._results.values()) / total

        return {
            "total_queries": total,
            "total_results": len(self._results),
            "hits": hits,
            "hit_rate": round(hits / total, 4),
            "avg_recall_at_1": round(avg_recall_1, 4),
            "avg_recall_at_5": round(avg_recall_5, 4),
            "avg_mrr": round(avg_mrr, 4),
            "avg_ndcg_at_5": round(avg_ndcg_5, 4),
            "by_category": self._summary_by_category(),
        }

    def _summary_by_category(self) -> Dict[str, Any]:
        """Get summary statistics by category."""
        by_cat: Dict[str, List[EvaluationResult]] = {}
        for r in self._results.values():
            # Find query category
            query = self._queries.get(r.query_id)
            cat = query.category if query else "unknown"
            if cat not in by_cat:
                by_cat[cat] = []
            by_cat[cat].append(r)

        summary = {}
        for cat, results in by_cat.items():
            total = len(results)
            hits = sum(1 for r in results if r.hit)
            summary[cat] = {
                "count": total,
                "hits": hits,
                "hit_rate": round(hits / total, 4) if total > 0 else 0,
                "avg_recall_at_5": round(
                    sum(r.recall_at_5 for r in results) / total, 4
                ) if total > 0 else 0,
            }

        return summary

    def save_results(self, filepath: Optional[str] = None) -> str:
        """Save evaluation results to JSON."""
        if not filepath:
            filepath = os.path.join(self._data_dir, "evaluation_results.json")

        Path(filepath).parent.mkdir(parents=True, exist_ok=True)

        data = {
            "summary": self.get_summary(),
            "results": {qid: r.to_dict() for qid, r in self._results.items()},
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        logger.info(f"Saved evaluation results to {filepath}")
        return filepath


# Import math at module level
import math
