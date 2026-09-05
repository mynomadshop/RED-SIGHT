"""
RedSight - High-Performance Local AI Intelligence Platform
Core interfaces and abstract base classes

Defines the stable contracts that all platform components implement.
If these interfaces are clean, the rest of the platform can evolve
aggressively without becoming a rewrite.
"""

from __future__ import annotations

import abc
import enum
import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    Any,
    AsyncIterator,
    Dict,
    List,
    Optional,
    Protocol,
    Sequence,
    Tuple,
    runtime_checkable,
)


# ─── Enums ───────────────────────────────────────────────────────────

class TrustLevel(enum.IntEnum):
    """Trust levels for memory and knowledge items."""
    RAW = 0           # Unverified source chunk or observation
    PARSED = 1        # Structurally valid and provenance attached
    VALIDATED = 2     # Deduplicated, policy-checked, supported by source/test
    PROMOTED = 3      # Approved as reusable memory or production skill
    GOLDEN = 4        # Part of curated benchmark, policy, or critical operating procedure


class JobStatus(enum.StrEnum):
    """Status of a scheduled job."""
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    OOM = "oom"
    PREEMPTED = "preempted"


class Capability(enum.StrEnum):
    """Model capability categories for routing."""
    REASONING = "reasoning"
    FAST_CHAT = "fast_chat"
    CODING = "coding"
    VISION = "vision"
    EMBEDDING = "embedding"
    RERANKER = "reranker"
    VOICE = "voice"


class RoutingMode(enum.StrEnum):
    """Platform operating modes."""
    LOCAL_ONLY = "local_only"
    LOCAL_PREFERRED = "local_preferred"
    CLOUD_ALLOWED = "cloud_allowed"


class PermissionLevel(enum.StrEnum):
    """Permission levels for tools and skills."""
    READ_ONLY = "read_only"
    READ_WRITE = "read_write"
    WRITE_ONLY = "write_only"
    DESTRUCTIVE = "destructive"  # delete, overwrite, send, publish, trade


class AuditAction(enum.StrEnum):
    """Types of audit events."""
    TOOL_CALL = "tool_call"
    SKILL_EXECUTION = "skill_execution"
    MODEL_SELECTION = "model_selection"
    PERMISSION_CHECK = "permission_check"
    MEMORY_STORE = "memory_store"
    MEMORY_PROMOTE = "memory_promote"
    CONFIG_CHANGE = "config_change"
    SECURITY_VIOLATION = "security_violation"
    JOB_START = "job_start"
    JOB_COMPLETE = "job_complete"
    JOB_FAIL = "job_fail"


# ─── Data Classes ────────────────────────────────────────────────────

@dataclass
class SourceReference:
    """Provenance information for a retrieved chunk."""
    source_path: str
    project: str
    timestamp: float
    checksum: str
    parser_version: str
    embedding_version: str
    access_scope: str
    page_number: Optional[int] = None
    offset_start: Optional[int] = None
    offset_end: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_path": self.source_path,
            "project": self.project,
            "timestamp": self.timestamp,
            "checksum": self.checksum,
            "parser_version": self.parser_version,
            "embedding_version": self.embedding_version,
            "access_scope": self.access_scope,
            "page_number": self.page_number,
            "offset_start": self.offset_start,
            "offset_end": self.offset_end,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SourceReference:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class CitationPack:
    """Source IDs and offsets passed through for UI citation display."""
    references: List[SourceReference]
    chunk_ids: List[str]
    relevance_scores: List[float]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "references": [r.to_dict() for r in self.references],
            "chunk_ids": self.chunk_ids,
            "relevance_scores": self.relevance_scores,
        }


@dataclass
class ModelInfo:
    """Metadata about a loaded or available model."""
    model_id: str
    name: str
    capabilities: List[Capability]
    context_size: int
    is_loaded: bool
    total_vram_mb: float = 0.0
    gpu_affinity: Optional[int] = None
    vram_usage_mb: float = 0.0
    loaded_at: Optional[float] = None
    backend: str = "lmstudio"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "name": self.name,
            "capabilities": [c.value for c in self.capabilities],
            "context_size": self.context_size,
            "is_loaded": self.is_loaded,
            "total_vram_mb": round(self.total_vram_mb, 1),
            "gpu_affinity": self.gpu_affinity,
            "vram_usage_mb": self.vram_usage_mb,
            "loaded_at": self.loaded_at,
            "backend": self.backend,
        }


@dataclass
class GpuInfo:
    """GPU telemetry data."""
    index: int
    name: str
    total_vram_mb: float
    free_vram_mb: float
    used_vram_mb: float
    utilization_percent: float
    temperature_c: float
    process_count: int
    power_draw_w: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "name": self.name,
            "total_vram_mb": round(self.total_vram_mb, 1),
            "free_vram_mb": round(self.free_vram_mb, 1),
            "used_vram_mb": round(self.used_vram_mb, 1),
            "utilization_percent": round(self.utilization_percent, 1),
            "temperature_c": round(self.temperature_c, 1),
            "process_count": self.process_count,
            "power_draw_w": round(self.power_draw_w, 1),
        }


@dataclass
class AuditEvent:
    """Immutable-ish audit record."""
    event_id: str
    action: AuditAction
    timestamp: float
    actor: str  # agent_id, skill_id, or "user"
    details: Dict[str, Any]
    permissions_used: List[str] = field(default_factory=list)
    result: str = "success"
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "action": self.action.value,
            "timestamp": self.timestamp,
            "actor": self.actor,
            "details": self.details,
            "permissions_used": self.permissions_used,
            "result": self.result,
            "error": self.error,
        }


@dataclass
class BenchmarkResult:
    """Performance benchmark result."""
    profile_name: str
    model_id: str
    backend: str
    ttft_ms: float  # Time to first token
    tokens_per_second: float
    total_latency_ms: float
    vram_peak_mb: float
    cpu_percent: float
    success: bool
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "profile_name": self.profile_name,
            "model_id": self.model_id,
            "backend": self.backend,
            "ttft_ms": round(self.ttft_ms, 2),
            "tokens_per_second": round(self.tokens_per_second, 2),
            "total_latency_ms": round(self.total_latency_ms, 2),
            "vram_peak_mb": round(self.vram_peak_mb, 1),
            "cpu_percent": round(self.cpu_percent, 1),
            "success": self.success,
            "error": self.error,
        }


# ─── Interfaces (Protocols) ─────────────────────────────────────────

@runtime_checkable
class ModelProvider(Protocol):
    """
    Interface for model providers (LM Studio, OpenAI, Google, etc.).
    
    All external providers must implement this interface so that
    agent logic never leaks provider-specific details.
    """
    
    async def health_check(self) -> bool:
        """Check if the provider is reachable and healthy."""
        ...
    
    async def list_models(self) -> List[ModelInfo]:
        """List available models and their capabilities."""
        ...
    
    async def chat(
        self,
        messages: List[Dict[str, str]],
        model_id: Optional[str] = None,
        stream: bool = False,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> AsyncIterator[str] | str:
        """
        Send a chat completion request.
        
        Returns an async iterator if stream=True, otherwise a string.
        """
        ...
    
    async def embed(
        self,
        texts: List[str],
        model_id: Optional[str] = None,
        **kwargs: Any,
    ) -> List[List[float]]:
        """Generate embeddings for a list of texts."""
        ...
    
    async def rerank(
        self,
        query: str,
        documents: List[str],
        model_id: Optional[str] = None,
        **kwargs: Any,
    ) -> List[float]:
        """Rerank documents by relevance to the query."""
        ...
    
    async def get_capability(self, capability: Capability) -> Optional[ModelInfo]:
        """Get the best model for a given capability."""
        ...


@runtime_checkable
class Retriever(Protocol):
    """
    Interface for the retrieval and memory subsystem.
    
    Handles hybrid search (dense + sparse), reranking, context
    budgeting, and citation pack assembly.
    """
    
    async def search(
        self,
        query: str,
        collections: Optional[List[str]] = None,
        top_k: int = 40,
        filters: Optional[Dict[str, Any]] = None,
        hybrid: bool = True,
        rerank: bool = True,
    ) -> Tuple[List[Dict[str, Any]], CitationPack]:
        """
        Search across knowledge collections.
        
        Returns (documents, citation_pack) where documents are the
        retrieved chunks and citation_pack contains provenance info.
        """
        ...
    
    async def search_by_id(self, chunk_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a specific chunk by ID."""
        ...
    
    async def get_collection_stats(self, collection: str) -> Dict[str, Any]:
        """Get statistics for a collection."""
        ...
    
    async def list_collections(self) -> List[str]:
        """List all available collections."""
        ...
    
    async def ingest(
        self,
        source_path: str,
        collection: str,
        project: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        """
        Ingest a source file into a collection.
        
        Returns list of chunk IDs created.
        """
        ...
    
    async def delete_collection(self, collection: str) -> bool:
        """Delete an entire collection."""
        ...


@runtime_checkable
class Skill(Protocol):
    """
    Interface for skills — reusable, versioned, permissioned procedures.
    
    Skills are discovered semantically but executed through a governed
    registry that controls version, permissions, and sandboxing.
    """
    
    @property
    def skill_id(self) -> str:
        """Unique identifier for this skill."""
        ...
    
    @property
    def name(self) -> str:
        """Human-readable name."""
        ...
    
    @property
    def description(self) -> str:
        """Semantic description for discovery."""
        ...
    
    @property
    def version(self) -> str:
        """Semantic version (e.g., '1.0.0')."""
        ...
    
    @property
    def trigger_model(self) -> Dict[str, Any]:
        """Example prompts, supported intents, confidence threshold."""
        ...
    
    @property
    def interface(self) -> Dict[str, Any]:
        """Typed inputs/outputs using Pydantic/JSON Schema."""
        ...
    
    @property
    def execution(self) -> Dict[str, Any]:
        """Python entry point, timeout, resource class, allowed tools, GPU need."""
        ...
    
    @property
    def permissions(self) -> List[str]:
        """Filesystem scopes, network scopes, secret scopes, write/delete capability."""
        ...
    
    @property
    def quality(self) -> Dict[str, Any]:
        """Tests, success rate, last validation time, known limitations."""
        ...
    
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the skill with given inputs.
        
        Returns structured output. Must respect permissions and sandboxing.
        """
        ...
    
    async def validate(self) -> bool:
        """Run validation tests on the skill."""
        ...


@runtime_checkable
class Tool(Protocol):
    """
    Interface for tools — typed contracts with permission checks.
    
    Tools are the atomic operations an agent can perform. Each tool
    has a name, schema, permissions, and execution logic.
    """
    
    @property
    def name(self) -> str:
        """Tool name (e.g., 'read_file', 'search_code')."""
        ...
    
    @property
    def description(self) -> str:
        """Tool description for agent selection."""
        ...
    
    @property
    def schema(self) -> Dict[str, Any]:
        """JSON Schema for tool parameters."""
        ...
    
    @property
    def permissions(self) -> List[str]:
        """Required permissions to execute this tool."""
        ...
    
    async def execute(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the tool with given parameters.
        
        Must check permissions before execution.
        Returns structured result.
        """
        ...
    
    async def validate_params(self, params: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Validate parameters against schema. Returns (is_valid, error_message)."""
        ...


@runtime_checkable
class MemoryStore(Protocol):
    """
    Interface for the memory subsystem.
    
    Uses distinct memory classes with different retention and trust rules
    so temporary context doesn't silently become permanent truth.
    """
    
    async def store_working(
        self,
        key: str,
        value: Any,
        ttl_seconds: Optional[int] = None,
    ) -> None:
        """Store working memory (short-lived, not auto-persisted)."""
        ...
    
    async def get_working(self, key: str) -> Optional[Any]:
        """Retrieve working memory."""
        ...
    
    async def store_episodic(
        self,
        task_id: str,
        decision: str,
        outcome: str,
        user_approved: bool = False,
    ) -> str:
        """Store episodic memory (completed task decisions and outcomes)."""
        ...
    
    async def store_semantic(
        self,
        fact: str,
        source_provenance: str,
        project: Optional[str] = None,
        trust_level: TrustLevel = TrustLevel.PARSED,
    ) -> str:
        """Store semantic memory (stable facts with provenance)."""
        ...
    
    async def store_procedural(
        self,
        skill_id: str,
        version: str,
        workflow: Dict[str, Any],
        trust_level: TrustLevel = TrustLevel.VALIDATED,
    ) -> str:
        """Store procedural memory (skills, workflows, tool recipes)."""
        ...
    
    async def query_episodic(
        self,
        query: str,
        project: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Query episodic memory by semantic similarity."""
        ...
    
    async def query_semantic(
        self,
        query: str,
        trust_min: TrustLevel = TrustLevel.PARSED,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Query semantic memory by semantic similarity."""
        ...
    
    async def promote_memory(
        self,
        memory_id: str,
        from_level: TrustLevel,
        to_level: TrustLevel,
        validator: str,
    ) -> bool:
        """Promote a memory item to a higher trust level."""
        ...
    
    async def get_memory_stats(self) -> Dict[str, Any]:
        """Get statistics about memory stores."""
        ...


@runtime_checkable
class JobScheduler(Protocol):
    """
    Interface for the job scheduler.
    
    Manages VRAM reservations, GPU affinity, backpressure,
    preemption, OOM recovery, and benchmark profiles.
    """
    
    async def submit_job(
        self,
        job_type: str,
        payload: Dict[str, Any],
        priority: str = "normal",
        gpu_affinity: Optional[int] = None,
        vram_reservation_mb: Optional[float] = None,
        timeout_seconds: Optional[int] = None,
    ) -> str:
        """
        Submit a job to the scheduler.
        
        Returns job_id. Jobs are queued if resources are insufficient.
        """
        ...
    
    async def cancel_job(self, job_id: str) -> bool:
        """Cancel a running or queued job."""
        ...
    
    async def get_job_status(self, job_id: str) -> Dict[str, Any]:
        """Get the current status and details of a job."""
        ...
    
    async def list_jobs(
        self,
        status: Optional[JobStatus] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List jobs with optional status filter."""
        ...
    
    async def get_gpu_status(self) -> List[GpuInfo]:
        """Get current status of all GPUs."""
        ...
    
    async def get_queue_depth(self) -> int:
        """Get the current queue depth."""
        ...
    
    async def run_benchmark(
        self,
        profile_name: str,
        model_id: str,
        backend: str,
        test_cases: List[Dict[str, Any]],
    ) -> BenchmarkResult:
        """Run a benchmark and return results."""
        ...
    
    async def record_benchmark(self, result: BenchmarkResult) -> None:
        """Record a benchmark result for future routing decisions."""
        ...


@runtime_checkable
class AuditSink(Protocol):
    """
    Interface for the audit trail.
    
    Maintains immutable-ish run records with who/what/when,
    tool inputs, outputs, permissions, and result status.
    """
    
    async def record(
        self,
        event: AuditEvent,
    ) -> None:
        """Record an audit event."""
        ...
    
    async def query(
        self,
        actor: Optional[str] = None,
        action: Optional[AuditAction] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        limit: int = 100,
    ) -> List[AuditEvent]:
        """Query audit events with filters."""
        ...
    
    async def export(
        self,
        format: str = "json",
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
    ) -> str:
        """Export audit trail in specified format."""
        ...
    
    async def get_recent_violations(self, limit: int = 20) -> List[AuditEvent]:
        """Get recent security violations."""
        ...


# ─── Base Implementations ───────────────────────────────────────────

class BaseMemoryStore:
    """
    Base class for MemoryStore implementations.
    
    Provides common patterns for working memory (TTL-based),
    episodic memory (task-linked), and semantic memory (provenance-tracked).
    """
    
    def __init__(self):
        self._working_memory: Dict[str, Tuple[Any, float]] = {}  # key -> (value, expiry)
        self._episodic: List[Dict[str, Any]] = []
        self._semantic: List[Dict[str, Any]] = []
        self._procedural: List[Dict[str, Any]] = []
        self._trust_levels: Dict[str, TrustLevel] = {}
    
    def _now(self) -> float:
        return time.time()
    
    def _check_ttl(self, key: str) -> bool:
        """Check if a working memory entry has expired."""
        if key not in self._working_memory:
            return False
        value, expiry = self._working_memory[key]
        if expiry and self._now() > expiry:
            del self._working_memory[key]
            return True
        return False
    
    async def store_working(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        expiry = self._now() + ttl_seconds if ttl_seconds else None
        self._working_memory[key] = (value, expiry)
    
    async def get_working(self, key: str) -> Optional[Any]:
        if self._check_ttl(key):
            return None
        value, _ = self._working_memory.get(key, (None, None))
        return value
    
    async def store_episodic(self, task_id: str, decision: str, outcome: str, user_approved: bool = False) -> str:
        memory_id = f"ep_{task_id}_{int(self._now())}"
        entry = {
            "memory_id": memory_id,
            "task_id": task_id,
            "decision": decision,
            "outcome": outcome,
            "user_approved": user_approved,
            "timestamp": self._now(),
            "trust_level": TrustLevel.VALIDATED if user_approved else TrustLevel.PARSED,
        }
        self._episodic.append(entry)
        self._trust_levels[memory_id] = entry["trust_level"]
        return memory_id
    
    async def store_semantic(self, fact: str, source_provenance: str, project: Optional[str] = None, trust_level: TrustLevel = TrustLevel.PARSED) -> str:
        memory_id = f"sm_{hashlib.md5(fact.encode()).hexdigest()[:12]}"
        entry = {
            "memory_id": memory_id,
            "fact": fact,
            "source_provenance": source_provenance,
            "project": project,
            "timestamp": self._now(),
            "trust_level": trust_level,
        }
        self._semantic.append(entry)
        self._trust_levels[memory_id] = trust_level
        return memory_id
    
    async def store_procedural(self, skill_id: str, version: str, workflow: Dict[str, Any], trust_level: TrustLevel = TrustLevel.VALIDATED) -> str:
        memory_id = f"pm_{skill_id}_{version.replace('.', '_')}"
        entry = {
            "memory_id": memory_id,
            "skill_id": skill_id,
            "version": version,
            "workflow": workflow,
            "timestamp": self._now(),
            "trust_level": trust_level,
        }
        self._procedural.append(entry)
        self._trust_levels[memory_id] = trust_level
        return memory_id
    
    async def query_episodic(self, query: str, project: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
        """Simple keyword-based query (replace with vector search in production)."""
        query_lower = query.lower()
        results = []
        for entry in self._episodic:
            if project and entry.get("project") != project:
                continue
            if any(term in entry.get("decision", "").lower() or term in entry.get("outcome", "").lower() for term in query_lower.split()):
                results.append(entry)
        return results[:limit]
    
    async def query_semantic(self, query: str, trust_min: TrustLevel = TrustLevel.PARSED, limit: int = 10) -> List[Dict[str, Any]]:
        """Simple keyword-based query (replace with vector search in production)."""
        query_lower = query.lower()
        results = []
        for entry in self._semantic:
            if entry.get("trust_level", TrustLevel.RAW) < trust_min:
                continue
            if any(term in entry.get("fact", "").lower() for term in query_lower.split()):
                results.append(entry)
        return results[:limit]
    
    async def promote_memory(self, memory_id: str, from_level: TrustLevel, to_level: TrustLevel, validator: str) -> bool:
        if from_level >= to_level:
            return False
        # Update trust level
        for entry_list in [self._episodic, self._semantic, self._procedural]:
            for entry in entry_list:
                if entry.get("memory_id") == memory_id:
                    entry["trust_level"] = to_level
                    entry["promoted_by"] = validator
                    entry["promoted_at"] = self._now()
                    self._trust_levels[memory_id] = to_level
                    return True
        return False
    
    async def get_memory_stats(self) -> Dict[str, Any]:
        return {
            "working_entries": len(self._working_memory),
            "episodic_count": len(self._episodic),
            "semantic_count": len(self._semantic),
            "procedural_count": len(self._procedural),
            "trust_distribution": {
                level.name: sum(1 for v in self._trust_levels.values() if v == level)
                for level in TrustLevel
            },
        }
