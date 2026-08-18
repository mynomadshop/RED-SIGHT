"""
RedSight - High-Performance Local AI Intelligence Platform
Acceleration Package

Provides GPU acceleration and management:
- GPU telemetry and monitoring
- GPU scheduling and resource allocation
- CUDA/PyTorch optimization
"""

from app.acceleration.gpu_telemetry import GpuTelemetry
from app.acceleration.gpu_scheduler import JobSchedulerImpl, ScheduledJob

GPUScheduler = JobSchedulerImpl  # Alias for backward compatibility
GPUAllocation = ScheduledJob  # Alias

__all__ = [
    "GpuTelemetry",
    "GPUScheduler",
    "GPUAllocation",
    "JobSchedulerImpl",
    "ScheduledJob",
]
