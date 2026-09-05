"""
Capability Registry.

Provides runtime feature discovery for the RedSight platform.
Each capability can be checked before attempting to use a feature.
"""

from __future__ import annotations

import json
import urllib.request
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
        from app.acceleration.gpu_telemetry import GpuTelemetry
        from app.config.settings import get_settings

        # GPU capability
        telemetry = GpuTelemetry()
        try:
            gpus = telemetry.get_gpu_status() if telemetry.initialize() else []
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
        finally:
            telemetry.shutdown()

        # LM Studio capability
        try:
            base_url = get_settings().lmstudio.base_url
            request = urllib.request.Request(
                f"{base_url.rstrip('/')}/models",
                headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=3) as response:
                payload = json.load(response)
            model_count = len(payload.get("data", [])) if isinstance(payload, dict) else 0
            if 200 <= response.status < 300:
                self.register(Capability(
                    name="lm_studio",
                    description="LM Studio API is reachable",
                    status=CapabilityStatus.ENABLED,
                    metadata={"model_count": model_count},
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
            retrieval = get_settings().retrieval
            qdrant_url = (
                retrieval.vector_backend_url
                or f"http://{retrieval.vector_backend_host}:{retrieval.vector_backend_port}"
            ).rstrip("/")
            with urllib.request.urlopen(f"{qdrant_url}/readyz", timeout=3) as response:
                if not 200 <= response.status < 300:
                    raise RuntimeError(f"Qdrant returned HTTP {response.status}")
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
