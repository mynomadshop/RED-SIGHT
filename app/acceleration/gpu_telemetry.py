"""
RedSight - High-Performance Local AI Intelligence Platform
GPU Telemetry via NVML

Enumerates GPUs, monitors VRAM, utilization, temperature, and processes.
Provides real-time GPU status for the scheduler and UI.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

try:
    import pynvml
    NVML_AVAILABLE = True
except ImportError:
    NVML_AVAILABLE = False
    pynvml = None  # type: ignore

from app.config.settings import get_settings
from app.core.interfaces import GpuInfo

logger = logging.getLogger(__name__)


class GpuTelemetry:
    """
    GPU telemetry collector using NVIDIA NVML.
    
    Monitors all NVIDIA GPUs on the system, providing real-time
    VRAM, utilization, temperature, and power data.
    """
    
    def __init__(self, poll_interval: Optional[float] = None):
        settings = get_settings()
        self.poll_interval = poll_interval or settings.acceleration.nvml_poll_interval_seconds
        self._gpus: Dict[int, GpuInfo] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_update: float = 0.0
        self._initialized = False
    
    def initialize(self) -> bool:
        """
        Initialize NVML and enumerate GPUs.
        
        Returns True if initialization succeeded.
        """
        if not NVML_AVAILABLE:
            logger.warning("pynvml not available — GPU telemetry disabled")
            return False
        
        try:
            pynvml.nvmlInit()
            self._initialized = True
            self._enumerate_gpus()
            logger.info(f"NVML initialized, {pynvml.nvmlDeviceGetCount()} GPU(s) detected")
            return True
        except Exception as e:
            logger.error(f"NVML initialization failed: {e}")
            return False
    
    def _enumerate_gpus(self) -> None:
        """Enumerate all GPUs and create GpuInfo objects."""
        if not self._initialized:
            return
        
        device_count = pynvml.nvmlDeviceGetCount()
        for i in range(device_count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            name = pynvml.nvmlDeviceGetName(handle)
            if isinstance(name, bytes):
                name = name.decode("utf-8")
            
            mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            
            self._gpus[i] = GpuInfo(
                index=i,
                name=name,
                total_vram_mb=mem_info.total / (1024 * 1024),
                free_vram_mb=mem_info.free / (1024 * 1024),
                used_vram_mb=mem_info.used / (1024 * 1024),
                utilization_percent=0.0,
                temperature_c=0.0,
                process_count=0,
                power_draw_w=0.0,
            )
    
    def update(self) -> Dict[int, GpuInfo]:
        """
        Update GPU telemetry data.
        
        Returns dict of GPU index -> GpuInfo.
        """
        if not self._initialized:
            return {}
        
        now = time.time()
        if now - self._last_update < self.poll_interval:
            return self._gpus
        
        self._last_update = now
        
        for gpu_idx, gpu in self._gpus.items():
            try:
                handle = pynvml.nvmlDeviceGetHandleByIndex(gpu_idx)
                
                # Memory info
                mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                gpu.free_vram_mb = mem_info.free / (1024 * 1024)
                gpu.used_vram_mb = mem_info.used / (1024 * 1024)
                
                # Utilization
                util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                gpu.utilization_percent = float(util.gpu)
                
                # Temperature
                try:
                    gpu.temperature_c = float(pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU))
                except Exception:
                    pass
                
                # Power draw
                try:
                    power = pynvml.nvmlDeviceGetPowerUsage(handle)
                    gpu.power_draw_w = power / 1000.0  # Convert mW to W
                except Exception:
                    pass
                
                # Process count
                try:
                    processes = pynvml.nvmlDeviceGetComputeRunningProcesses(handle)
                    gpu.process_count = len(processes)
                except Exception:
                    pass
                    
            except Exception as e:
                logger.warning(f"Failed to update GPU {gpu_idx}: {e}")
        
        return self._gpus
    
    def get_gpu_status(self) -> List[GpuInfo]:
        """Get current status of all GPUs."""
        self.update()
        return list(self._gpus.values())
    
    def get_gpu_by_index(self, index: int) -> Optional[GpuInfo]:
        """Get GPU info by index."""
        self.update()
        return self._gpus.get(index)
    
    def get_total_free_vram(self) -> float:
        """Get total free VRAM across all GPUs in MB."""
        self.update()
        return sum(g.free_vram_mb for g in self._gpus.values())
    
    def get_total_used_vram(self) -> float:
        """Get total used VRAM across all GPUs in MB."""
        self.update()
        return sum(g.used_vram_mb for g in self._gpus.values())
    
    def get_best_gpu_for_model(
        self,
        required_vram_mb: float,
        prefer_loaded: bool = True,
    ) -> Optional[int]:
        """
        Find the best GPU for a model based on VRAM availability.
        
        Returns GPU index or None if no suitable GPU found.
        """
        self.update()
        
        candidates = []
        for gpu in self._gpus.values():
            free = gpu.free_vram_mb - (get_settings().routing.vram_headroom_gb_per_gpu * 1024)
            if free >= required_vram_mb:
                candidates.append((gpu.index, free))
        
        if not candidates:
            return None
        
        # Sort by free VRAM (descending)
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[0][0]
    
    def get_gpu_summary(self) -> List[Dict[str, Any]]:
        """Get a summary of all GPU status for UI display."""
        self.update()
        return [gpu.to_dict() for gpu in self._gpus.values()]
    
    def start_polling(self) -> None:
        """Start background GPU telemetry polling."""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        logger.info("GPU telemetry polling started")
    
    def _poll_loop(self) -> None:
        """Background polling loop."""
        while self._running:
            try:
                self.update()
            except Exception as e:
                logger.error(f"GPU telemetry poll error: {e}")
            time.sleep(self.poll_interval)
    
    def stop_polling(self) -> None:
        """Stop background GPU telemetry polling."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("GPU telemetry polling stopped")
    
    def shutdown(self) -> None:
        """Clean shutdown of NVML."""
        self.stop_polling()
        if self._initialized and NVML_AVAILABLE:
            try:
                pynvml.nvmlShutdown()
            except Exception as e:
                logger.warning(f"Error shutting down NVML: {e}")
            self._initialized = False
