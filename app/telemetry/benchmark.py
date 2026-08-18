"""
RedSight - High-Performance Local AI Intelligence Platform
Benchmark Manager

Records and compares benchmark results for evidence-based routing.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.interfaces import BenchmarkResult

logger = logging.getLogger(__name__)


class BenchmarkManager:
    """
    Benchmark Manager - Records and compares benchmark results.
    
    Stores performance by model + quantization + backend + GPU placement
    so future routing is evidence-based.
    """
    
    def __init__(self, benchmark_path: str = "./data/benchmarks"):
        self.benchmark_path = Path(benchmark_path)
        self.benchmark_path.mkdir(parents=True, exist_ok=True)
        self._results: List[BenchmarkResult] = []
        self._load_results()
    
    def _load_results(self) -> None:
        """Load benchmark results from disk."""
        result_file = self.benchmark_path / "results.json"
        if result_file.exists():
            try:
                with open(result_file, "r") as f:
                    data = json.load(f)
                    self._results = [
                        BenchmarkResult(**r) for r in data
                    ]
                logger.info(f"Loaded {len(self._results)} benchmark results")
            except Exception as e:
                logger.warning(f"Failed to load benchmarks: {e}")
    
    async def record(self, result: BenchmarkResult) -> None:
        """Record a benchmark result."""
        self._results.append(result)
        self._save_results()
        logger.info(
            f"Benchmark recorded: {result.profile_name} - "
            f"TTFT={result.ttft_ms:.0f}ms, "
            f"{result.tokens_per_second:.1f} tok/s"
        )
    
    async def get_results(self, profile_name: Optional[str] = None,
                         model_id: Optional[str] = None,
                         success: Optional[bool] = None,
                         limit: int = 50) -> List[BenchmarkResult]:
        """
        Get benchmark results with optional filters.
        
        Returns matching results sorted by timestamp (newest first).
        """
        results = self._results
        
        if profile_name:
            results = [r for r in results if r.profile_name == profile_name]
        
        if model_id:
            results = [r for r in results if r.model_id == model_id]
        
        if success is not None:
            results = [r for r in results if r.success == success]
        
        # Sort by timestamp (using total_latency_ms as proxy)
        results.sort(key=lambda r: r.total_latency_ms, reverse=True)
        
        return results[:limit]
    
    async def get_best_result(self, profile_name: str,
                             model_id: Optional[str] = None) -> Optional[BenchmarkResult]:
        """Get the best benchmark result for a profile."""
        results = await self.get_results(
            profile_name=profile_name,
            model_id=model_id,
            success=True,
        )
        
        if not results:
            return None
        
        # Sort by tokens/second (higher is better)
        results.sort(key=lambda r: r.tokens_per_second, reverse=True)
        return results[0]
    
    async def get_average_by_model(self, model_id: str) -> Dict[str, float]:
        """Get average metrics by model."""
        results = await self.get_results(model_id=model_id, success=True)
        
        if not results:
            return {}
        
        return {
            "avg_ttft_ms": sum(r.ttft_ms for r in results) / len(results),
            "avg_tokens_per_second": sum(r.tokens_per_second for r in results) / len(results),
            "avg_total_latency_ms": sum(r.total_latency_ms for r in results) / len(results),
            "avg_vram_peak_mb": sum(r.vram_peak_mb for r in results) / len(results),
            "count": len(results),
        }
    
    def _save_results(self) -> None:
        """Save benchmark results to disk."""
        result_file = self.benchmark_path / "results.json"
        try:
            with open(result_file, "w") as f:
                json.dump([r.to_dict() for r in self._results], f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save benchmarks: {e}")
    
    async def clear(self) -> None:
        """Clear all benchmark results."""
        self._results.clear()
        self._save_results()
        logger.info("Benchmark results cleared")
