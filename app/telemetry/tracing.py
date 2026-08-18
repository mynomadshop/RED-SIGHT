"""
RedSight - High-Performance Local AI Intelligence Platform
Trace Collector

Collects distributed traces for debugging and observability.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class TraceCollector:
    """
    Trace Collector - Collects execution traces.
    
    Tracks request flows through the system for debugging
    and observability.
    """
    
    def __init__(self):
        self._traces: Dict[str, Dict[str, Any]] = {}
    
    async def start_trace(self, trace_id: str, operation: str,
                         metadata: Optional[Dict[str, Any]] = None) -> None:
        """Start a new trace."""
        self._traces[trace_id] = {
            "trace_id": trace_id,
            "operation": operation,
            "start_time": time.time(),
            "end_time": None,
            "metadata": metadata or {},
            "spans": [],
            "status": "running",
        }
    
    async def add_span(self, trace_id: str, span_name: str,
                      metadata: Optional[Dict[str, Any]] = None) -> str:
        """Add a span to a trace."""
        trace = self._traces.get(trace_id)
        if not trace:
            raise ValueError(f"Trace {trace_id} not found")
        
        span_id = f"{trace_id}_span_{len(trace['spans'])}"
        span = {
            "span_id": span_id,
            "name": span_name,
            "start_time": time.time(),
            "end_time": None,
            "metadata": metadata or {},
        }
        
        trace["spans"].append(span)
        return span_id
    
    async def end_span(self, trace_id: str, span_id: str,
                      status: str = "success",
                      metadata: Optional[Dict[str, Any]] = None) -> None:
        """End a span."""
        trace = self._traces.get(trace_id)
        if not trace:
            return
        
        for span in trace["spans"]:
            if span["span_id"] == span_id:
                span["end_time"] = time.time()
                span["status"] = status
                if metadata:
                    span["metadata"].update(metadata)
                break
    
    async def end_trace(self, trace_id: str, status: str = "success",
                       metadata: Optional[Dict[str, Any]] = None) -> None:
        """End a trace."""
        trace = self._traces.get(trace_id)
        if not trace:
            return
        
        trace["end_time"] = time.time()
        trace["status"] = status
        if metadata:
            trace["metadata"].update(metadata)
    
    async def get_trace(self, trace_id: str) -> Optional[Dict[str, Any]]:
        """Get a trace by ID."""
        return self._traces.get(trace_id)
    
    async def list_traces(self, operation: Optional[str] = None,
                         status: Optional[str] = None,
                         limit: int = 50) -> List[Dict[str, Any]]:
        """List traces with optional filters."""
        traces = list(self._traces.values())
        
        if operation:
            traces = [t for t in traces if t["operation"] == operation]
        
        if status:
            traces = [t for t in traces if t["status"] == status]
        
        # Sort by start time descending
        traces.sort(key=lambda t: t["start_time"], reverse=True)
        
        return traces[:limit]
    
    async def cleanup_old_traces(self, max_age_seconds: int = 3600) -> int:
        """Remove traces older than max_age_seconds."""
        now = time.time()
        to_remove = [
            tid for tid, trace in self._traces.items()
            if now - trace["start_time"] > max_age_seconds
        ]
        
        for tid in to_remove:
            del self._traces[tid]
        
        return len(to_remove)
