"""
RedSight - High-Performance Local AI Intelligence Platform
Typed configuration and capability registry

All behavioral settings go here — never in agent code or prompts.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, List, Optional
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# ─── Configuration Models ───────────────────────────────────────────

class PlatformConfig(BaseModel):
    """Platform-wide settings."""
    mode: str = Field(
        default="local_preferred",
        description="Operating mode: local_only | local_preferred | cloud_allowed",
    )
    data_root: str = Field(
        default="./data",
        description="Root directory for all data (sources, vectors, metadata)",
    )
    platform_name: str = Field(
        default="RedSight",
        description="Platform name for UI display and audit trails",
    )
    version: str = Field(
        default="11.6.0",
        description="Platform version",
    )
    
    @field_validator("mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        valid = {"local_only", "local_preferred", "cloud_allowed"}
        if v not in valid:
            raise ValueError(f"mode must be one of {valid}, got '{v}'")
        return v


class LmStudioConfig(BaseModel):
    """LM Studio provider configuration."""
    base_url: str = Field(
        default="http://127.0.0.1:1234/v1",
        description="LM Studio OpenAI-compatible API endpoint",
    )
    timeout_seconds: int = Field(
        default=180,
        gt=0,
        le=3600,
        description="Request timeout in seconds",
    )
    max_retries: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Number of retry attempts on transient failures",
    )
    retry_delay_seconds: float = Field(
        default=2.0,
        ge=0,
        le=60,
        description="Delay between retries (exponential backoff)",
    )
    model_id: Optional[str] = Field(
        default=None,
        description="Default model to use (None = auto-select)",
    )
    embedding_model_id: Optional[str] = Field(
        default=None,
        description="LM Studio embedding model (None = discover a loaded embedding model)",
    )

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        return _validated_http_url(value, "LM Studio base URL")


class RoutingConfig(BaseModel):
    """Model routing policy configuration."""
    interactive_priority: str = Field(
        default="high",
        description="Priority for interactive chat: low | normal | high | critical",
    )
    cloud_fallback: bool = Field(
        default=False,
        description="Allow cloud fallback when local models fail",
    )
    vram_headroom_gb_per_gpu: float = Field(
        default=3.0,
        description="VRAM headroom to reserve per GPU (GB)",
    )
    max_concurrent_jobs: int = Field(
        default=4,
        description="Maximum concurrent jobs across all GPUs",
    )
    preemption_enabled: bool = Field(
        default=True,
        description="Allow preemption of lower-priority jobs for interactive chat",
    )
    oom_recovery_enabled: bool = Field(
        default=True,
        description="Automatically retry with reduced resources on OOM",
    )


class RetrievalConfig(BaseModel):
    """Retrieval and RAG configuration."""
    vector_backend: str = Field(
        default="qdrant",
        description="Vector search backend: qdrant | chroma | faiss",
    )
    vector_backend_url: Optional[str] = Field(
        default=None,
        description="Optional complete Qdrant URL; takes precedence over host and port",
    )
    vector_backend_host: str = Field(
        default="127.0.0.1",
        description="Qdrant host when a complete URL is not configured",
    )
    vector_backend_port: int = Field(
        default=6333,
        ge=1,
        le=65535,
        description="Qdrant REST port",
    )
    vector_backend_embedded: bool = Field(
        default=False,
        description="Run the persistent Qdrant store in-process",
    )
    vector_backend_path: Optional[str] = Field(
        default=None,
        description="Persistent embedded-Qdrant path (defaults below the platform data root)",
    )
    enable_embeddings: bool = Field(
        default=False,
        description="Load an embedding model during server startup",
    )

    @field_validator("vector_backend_url")
    @classmethod
    def validate_vector_backend_url(cls, value: Optional[str]) -> Optional[str]:
        return _validated_http_url(value, "Qdrant URL") if value else None
    hybrid_search: bool = Field(
        default=True,
        description="Enable hybrid (dense + sparse) retrieval",
    )
    rerank: bool = Field(
        default=True,
        description="Enable reranking of candidate results",
    )
    top_candidates: int = Field(
        default=40,
        description="Number of initial candidates to retrieve",
    )
    final_context_chunks: int = Field(
        default=8,
        description="Number of final chunks after reranking",
    )
    embedding_model: str = Field(
        default="sentence-transformers/all-MiniLM-L6-v2",
        description="Default embedding model",
    )
    reranker_model: str = Field(
        default="cross-encoder/ms-marco-MiniLM-L-6-v2",
        description="Default reranker model",
    )
    chunk_size: int = Field(
        default=512,
        description="Target chunk size in tokens",
    )
    chunk_overlap: int = Field(
        default=64,
        description="Overlap between chunks in tokens",
    )


class AgentsConfig(BaseModel):
    """Agent runtime configuration."""
    default_permission_profile: str = Field(
        default="safe",
        description="Default permission profile: safe | moderate | unrestricted",
    )
    skill_auto_promotion: bool = Field(
        default=False,
        description="Allow automatic promotion of skills from experience",
    )
    destructive_actions_require_confirmation: bool = Field(
        default=True,
        description="Require explicit confirmation for destructive actions",
    )
    max_agent_steps: int = Field(
        default=50,
        description="Maximum steps per agent execution",
    )
    subagent_timeout_seconds: int = Field(
        default=300,
        description="Timeout for subagent execution",
    )


class AccelerationConfig(BaseModel):
    """GPU acceleration configuration."""
    scheduler: str = Field(
        default="dual_gpu_aware",
        description="Scheduler type: single_gpu | dual_gpu_aware | multi_gpu",
    )
    triton_enabled: bool = Field(
        default=True,
        description="Enable Triton kernels for hot paths",
    )
    tensorrt_backend: str = Field(
        default="optional",
        description="TensorRT backend: disabled | optional | required",
    )
    benchmark_gate_required: bool = Field(
        default=True,
        description="Require benchmark validation before enabling new backends",
    )
    nvml_poll_interval_seconds: float = Field(
        default=5.0,
        description="Interval for GPU telemetry polling",
    )
    cuda_graph_enabled: bool = Field(
        default=False,
        description="Enable CUDA graphs for stable repeated workloads",
    )


class SecurityConfig(BaseModel):
    """Security and permissions configuration."""
    local_only_mode: bool = Field(
        default=False,
        description="Block all outbound network requests",
    )
    secret_storage: str = Field(
        default="dpapi",
        description="Secret storage backend: dpapi | keyring | file",
    )
    audit_enabled: bool = Field(
        default=True,
        description="Enable audit trail logging",
    )
    audit_log_path: str = Field(
        default="./data/audit.log",
        description="Path to audit log file",
    )
    redact_sensitive_paths: bool = Field(
        default=True,
        description="Block sensitive local paths from external providers",
    )
    sensitive_path_patterns: List[str] = Field(
        default=[
            "*/.env",
            "*/secrets/*",
            "*/credentials/*",
            "*/.ssh/*",
            "*/.aws/*",
        ],
        description="Glob patterns for sensitive paths to redact",
    )


class TelemetryConfig(BaseModel):
    """Telemetry and observability configuration."""
    enabled: bool = Field(
        default=True,
        description="Enable telemetry collection",
    )
    metrics_path: str = Field(
        default="./data/metrics",
        description="Directory for metrics storage",
    )
    traces_enabled: bool = Field(
        default=False,
        description="Enable OpenTelemetry tracing",
    )
    benchmark_storage: str = Field(
        default="./data/benchmarks",
        description="Directory for benchmark results",
    )
    log_level: str = Field(
        default="INFO",
        description="Logging level: DEBUG | INFO | WARNING | ERROR | CRITICAL",
    )
    log_format: str = Field(
        default="json",
        description="Log format: json | text",
    )


# ─── Settings (combines all configs) ────────────────────────────────

class Settings(BaseSettings):
    """
    Top-level settings object.
    
    Loaded from environment variables and .env file.
    All behavioral settings are here — never hardcoded in agent code.
    """
    model_config = SettingsConfigDict(
        env_prefix="RED_SIGHT_",
        env_file=".env",
        env_file_encoding="utf-8",
        # Without this, the nested sections below are reachable only by passing
        # whole JSON objects (RED_SIGHT_LMSTUDIO='{"base_url": ...}'), and the
        # per-field names the installer exports - RED_SIGHT_LMSTUDIO__BASE_URL,
        # RED_SIGHT_PLATFORM__DATA_ROOT - are silently ignored.
        env_nested_delimiter="__",
        extra="ignore",
    )
    
    # Platform
    platform: PlatformConfig = Field(default_factory=PlatformConfig)
    
    # LM Studio
    lmstudio: LmStudioConfig = Field(default_factory=LmStudioConfig)
    
    # Routing
    routing: RoutingConfig = Field(default_factory=RoutingConfig)
    
    # Retrieval
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    
    # Agents
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    
    # Acceleration
    acceleration: AccelerationConfig = Field(default_factory=AccelerationConfig)
    
    # Security
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    
    # Telemetry
    telemetry: TelemetryConfig = Field(default_factory=TelemetryConfig)

    @model_validator(mode="before")
    @classmethod
    def apply_legacy_environment_aliases(cls, data: Any) -> Any:
        """Map established launcher variables into the typed nested settings.

        Current configuration uses ``RED_SIGHT_<SECTION>__<FIELD>`` names.  The
        Windows installer and earlier launchers also emit a small set of flat
        variables, so accepting both forms keeps upgraded installations working.
        Explicit constructor values and canonical nested variables always win.
        """
        values = dict(data or {})
        aliases = (
            ("RED_SIGHT_MODE", "platform", "mode"),
            ("RED_SIGHT_DATA_ROOT", "platform", "data_root"),
            ("LM_STUDIO_BASE_URL", "lmstudio", "base_url"),
            ("LM_STUDIO_URL", "lmstudio", "base_url"),
            ("LM_STUDIO_TIMEOUT", "lmstudio", "timeout_seconds"),
            ("LM_STUDIO_MODEL", "lmstudio", "model_id"),
            ("LM_STUDIO_EMBEDDING_MODEL", "lmstudio", "embedding_model_id"),
            ("VECTOR_BACKEND_URL", "retrieval", "vector_backend_url"),
            ("QDRANT_URL", "retrieval", "vector_backend_url"),
            ("VECTOR_BACKEND_HOST", "retrieval", "vector_backend_host"),
            ("VECTOR_BACKEND_PORT", "retrieval", "vector_backend_port"),
            ("VECTOR_BACKEND_EMBEDDED", "retrieval", "vector_backend_embedded"),
            ("VECTOR_BACKEND_PATH", "retrieval", "vector_backend_path"),
            ("ENABLE_EMBEDDINGS", "retrieval", "enable_embeddings"),
            ("EMBEDDING_MODEL", "retrieval", "embedding_model"),
            ("GPU_VRAM_HEADROOM_GB", "routing", "vram_headroom_gb_per_gpu"),
            ("LOG_LEVEL", "telemetry", "log_level"),
        )

        for env_name, section_name, field_name in aliases:
            raw_value = os.getenv(env_name)
            if raw_value is None:
                continue
            existing = values.get(section_name)
            if isinstance(existing, BaseModel):
                # An explicitly supplied typed section is authoritative.
                continue
            section = dict(existing or {})
            section.setdefault(field_name, raw_value)
            values[section_name] = section

        return values
    
    @property
    def data_root_path(self) -> Path:
        """Resolved data root path."""
        return Path(self.platform.data_root).resolve()
    
    @property
    def is_local_only(self) -> bool:
        """Check if platform is in local-only mode."""
        return self.platform.mode == "local_only" or self.security.local_only_mode
    
    @property
    def is_cloud_allowed(self) -> bool:
        """Check if cloud APIs are permitted."""
        return self.platform.mode == "cloud_allowed" and self.routing.cloud_fallback
    
    def model_dump_safe(self) -> dict:
        """
        Dump settings without sensitive values.
        
        Used for audit trail and diagnostics — never expose API keys or secrets.
        """
        data = self.model_dump()
        # Redact secret-related fields
        data["security"]["secret_storage"] = "[REDACTED]"
        return data


# ─── Singleton Settings ─────────────────────────────────────────────

_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get or create the global settings singleton."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Reset settings singleton (useful for testing)."""
    global _settings
    _settings = None


def _validated_http_url(value: str, label: str) -> str:
    """Accept only credential-free HTTP(S) service URLs."""
    candidate = str(value).strip().rstrip("/")
    parsed = urlsplit(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"{label} must be an http:// or https:// URL with a hostname")
    if parsed.username or parsed.password:
        raise ValueError(f"{label} must not contain embedded credentials")
    return candidate
