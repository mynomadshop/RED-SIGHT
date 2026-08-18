"""
RedSight - High-Performance Local AI Intelligence Platform
Metrics Collector

Collects and stores performance metrics for inference, hardware,
RAG, agents, skills, and reliability.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class MetricsCollector:
    """
    Metrics Collector - Collects performance metrics.
    
    Tracks:
    - Inference: TTFT, tokens/second, completion latency
    - Hardware: GPU utilization, VRAM peak, CPU/RAM use
    - RAG: Recall@k, MRR/nDCG, reranker lift
    - Agents: Task success rate, tool-call success
    - Skills: Invocation count, success rate, latency
    - Reliability: Crash-free runs, OOM rate
    - Cloud: Tokens, cost, rate-limit errors
    """
    
    def __init__(self, metrics_path: str = "./data/metrics"):
        self.metrics_path = Path(metrics_path)
        self.metrics_path.mkdir(parents=True, exist_ok=True)
        self._metrics: Dict[str, List[Dict[str, Any]]] = {}
    
    async def record(self, category: str, metric_name: str,
                    value: float, tags: Optional[Dict[str, str]] = None,
                    timestamp: Optional[float] = None) -> None:
        """
        Record a metric.
        
        Args:
            category: Metric category (inference, hardware, rag, agents, skills, reliability, cloud)
            metric_name: Metric name (e.g., "ttft_ms", "tokens_per_second")
            value: Metric value
            tags: Optional tags for filtering (e.g., {"model": "gpt-4"})
            timestamp: Optional timestamp
        """
        timestamp = timestamp or time.time()
        
        entry = {
            "category": category,
            "metric_name": metric_name,
            "value": value,
            "tags": tags or {},
            "timestamp": timestamp,
        }
        
        if category not in self._metrics:
            self._metrics[category] = []
        
        self._metrics[category].append(entry)
        
        # Keep only last 10000 entries per category
        if len(self._metrics[category]) > 10000:
            self._metrics[category] = self._metrics[category][-10000:]
    
    async def get_metrics(self, category: str, metric_name: Optional[str] = None,
                         start_time: Optional[float] = None,
                         end_time: Optional[float] = None,
                         limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get metrics with optional filters.
        
        Returns matching metrics sorted by timestamp (newest first).
        """
        if category not in self._metrics:
            return []
        
        metrics = self._metrics[category]
        
        if metric_name:
            metrics = [m for m in metrics if m["metric_name"] == metric_name]
        
        if start_time:
            metrics = [m for m in metrics if m["timestamp"] >= start_time]
        
        if end_time:
            metrics = [m for m in metrics if m["timestamp"] <= end_time]
        
        # Sort by timestamp descending
        metrics.sort(key=lambda m: m["timestamp"], reverse=True)
        
        return metrics[:limit]
    
    async def get_average(self, category: str, metric_name: str,
                         start_time: Optional[float] = None,
                         end_time: Optional[float] = None) -> Optional[float]:
        """Get the average value for a metric."""
        metrics = await self.get_metrics(
            category=category,
            metric_name=metric_name,
            start_time=start_time,
            end_time=end_time,
            limit=10000,
        )
        
        if not metrics:
            return None
        
        return sum(m["value"] for m in metrics) / len(metrics)
    
    async def get_summary(self) -> Dict[str, Any]:
        """Get a summary of all metrics."""
        summary = {}
        for category, metrics in self._metrics.items():
            if metrics:
                summary[category] = {
                    "count": len(metrics),
                    "latest_timestamp": max(m["timestamp"] for m in metrics),
                    "metrics": list(set(m["metric_name"] for m in metrics)),
                }
        return summary
    
    async def export(self, format: str = "json") -> str:
        """Export all metrics."""
        if format == "json":
            return json.dumps(self._metrics, indent=2, default=str)
        else:
            raise ValueError(f"Unsupported export format: {format}")
