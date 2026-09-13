---
name: cuda-readiness
description: Check that every installed NVIDIA GPU can execute PyTorch kernels in the RedSight environment.
---

# Cuda Readiness

Example request: Verify both GPUs are usable by RedSight and explain any CUDA mismatch.

Use system.powershell with the installed RedSight health checker or its Test-RsTorchCuda helper after locating the installation. Require the reported per-device allocation result; nvidia-smi visibility or torch.cuda.is_available alone is insufficient. Compare all devices, not only GPU 0. Distinguish CUDA package/runtime compatibility from LM Studio model loading. If repair is required, use the matching setup profile and verify again. Do not promise that two GPUs automatically split every model or double performance.
