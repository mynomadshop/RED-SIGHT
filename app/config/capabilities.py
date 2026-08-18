"""
Capability Registry.

Provides runtime feature discovery for the RedSight platform.
Each capability can be checked before attempting to use a feature.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class CapabilityStatus(Enum):
    """Status of a capability."""
    ENABLED = "enabled"
    DISABLED = "disabled"
    PARTIAL = "partial"  # partially available (e.g., GPU exists but VRAM low)
    MISSING = "missing"


@dataclass(frozen=True)
class Capability:
    """A single capability descriptor."""
    name: str
    description: str
    status: CapabilityStatus = CapabilityStatus.DISABLED
    requires: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @property
    def is_available(self) -> bool:
        return self.status in (CapabilityStatus.ENABLED, CapabilityStatus.PARTIAL)


class CapabilityRegistry:
    """Registry of all platform capabilities.

    Capabilities are discovered at startup by probing the environment
    (GPU availability, model connectivity, etc.).
    """

    def __init__(self) -> None:
        self._capabilities: dict[str, Capability] = {}

    def register(self, capability: Capability) -> None:
        """Register a capability."""
        self._capabilities[capability.name] = capability

    def get(self, name: str) -> Optional[Capability]:
        """Get a capability by name."""
        return self._capabilities.get(name)

    def check(self, name: str) -> bool:
        """Check if a capability is available."""
        cap = self._capabilities.get(name)
        return cap.is_available if cap else False

    def check_all(self, names: list[str]) -> bool:
        """Check if all specified capabilities are available."""
        return all(self.check(n) for n in names)

    def list_enabled(self) -> list[Capability]:
        """List all enabled capabilities."""
        return [c for c in self._capabilities.values() if c.is_available]

    def discover(self) -> dict[str, Capability]:
        """Discover capabilities from the environment.

        Probes GPU, LM Studio, Qdrant, and other subsystems.
        """
        from app.acceleration.gpu import GpuScheduler
        from app.models.lm_studio import LmStudioProvider
        from app.retrieval.vector import VectorStore

        # GPU capability
        try:
            scheduler = GpuScheduler()
            gpus = scheduler.discover_gpus()
            if gpus:
                self.register(Capability(
                    name="gpu",
                    description=f"Multi-GPU available: {len(gpus)} device(s)",
                    status=CapabilityStatus.ENABLED,
                    metadata={"count": len(gpus), "gpus": [g.name for g in gpus]},
                ))
            else:
                self.register(Capability(
                    name="gpu",
                    description="No GPU detected",
                    status=CapabilityStatus.MISSING,
                ))
        except Exception:
            self.register(Capability(
                name="gpu",
                description="GPU detection failed",
                status=CapabilityStatus.MISSING,
            ))

        # LM Studio capability
        try:
            provider = LmStudioProvider()
            health = provider.health_check()
            if health.get("status") == "healthy":
                self.register(Capability(
                    name="lm_studio",
                    description="LM Studio API is reachable",
                    status=CapabilityStatus.ENABLED,
                    metadata={"model_count": health.get("model_count", 0)},
                ))
            else:
                self.register(Capability(
                    name="lm_studio",
                    description="LM Studio API is not reachable",
                    status=CapabilityStatus.DISABLED,
                ))
        except Exception:
            self.register(Capability(
                name="lm_studio",
                description="LM Studio connection failed",
                status=CapabilityStatus.DISABLED,
            ))

        # Vector store capability
        try:
            store = VectorStore()
            store.initialize()
            self.register(Capability(
                name="vector_store",
                description="Qdrant vector store is available",
                status=CapabilityStatus.ENABLED,
            ))
        except Exception:
            self.register(Capability(
                name="vector_store",
                description="Vector store initialization failed",
                status=CapabilityStatus.PARTIAL,
            ))

        return self._capabilities
