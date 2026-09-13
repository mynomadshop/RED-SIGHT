<# Verify actual CPU-to-CUDA package replacement on Windows; no GPU is required. #>
[CmdletBinding()]
param([Parameter(Mandatory)][string]$PythonExe, [Parameter(Mandatory)][string]$VenvPath)

$ErrorActionPreference = 'Stop'
$root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
. (Join-Path $root 'installer\scripts\RedSight-Common.ps1')
. (Join-Path $root 'installer\scripts\RedSight-Preflight.ps1')
. (Join-Path $root 'installer\scripts\RedSight-Provision.ps1')

$cpu = Get-RsDependencyPlan -SetupProfile 'api'
$python = Initialize-RsVenv -PythonExe $PythonExe -VenvPath $VenvPath -PreInstalls $cpu.PreInstalls
& $python -c "import torch,onnxruntime; assert torch.version.cuda is None; print('CPU_RUNTIME=PASS')"
if ($LASTEXITCODE -ne 0) { throw 'The CPU profile did not install correctly' }

$hardware = [pscustomobject]@{ gpu = [pscustomobject]@{
    cudaCapable = $true; maxVramGB = 32.0; hasNvidiaHardware = $true
    maxComputeCap = '12.0'; cudaVersion = '13.3'
} }
$cuda = Get-RsDependencyPlan -SetupProfile 'cuda' -Hardware $hardware
$python = Initialize-RsVenv -PythonExe $PythonExe -VenvPath $VenvPath -PreInstalls $cuda.PreInstalls -Packages @('onnx>=1.17,<2')
$code = @'
import importlib.metadata as metadata
import torch
import onnxruntime as ort
assert torch.version.cuda == '13.0', torch.__version__
assert 'CUDAExecutionProvider' in ort.get_available_providers()
installed = {dist.metadata['Name'].lower() for dist in metadata.distributions()}
assert 'onnxruntime-gpu' in installed and 'onnxruntime' not in installed
print('CUDA_PACKAGES=PASS', torch.__version__, ort.__version__)
print('GPU_EXECUTION=NOT_TESTED (hosted runner has no NVIDIA GPU)')
'@
& $python -c $code
if ($LASTEXITCODE -ne 0) { throw 'The CUDA profile did not replace the CPU packages cleanly' }
& $python -m pip check
if ($LASTEXITCODE -ne 0) { throw 'The CUDA environment has dependency conflicts' }
