<#
    RedSight-Hardware.ps1

    Machine capability scan. Answers the questions that decide what RedSight
    should install on this particular computer:

      * Is there an NVIDIA GPU worth installing CUDA wheels for?
      * Is this a laptop?
      * Can this machine actually run WSL2 and Docker, or is hardware
        virtualization switched off in the firmware?
      * Is there enough RAM and disk?

    Deliberately STANDALONE - no dot-sourcing, no dependencies on the other
    RedSight scripts - because the Inno Setup wizard extracts and runs it on its
    own, before anything has been installed.

        powershell -ExecutionPolicy Bypass -File RedSight-Hardware.ps1 -Json
        powershell -ExecutionPolicy Bypass -File RedSight-Hardware.ps1 -OutFile hw.json

    Exit code is always 0: an inconclusive scan must never block setup, it just
    produces a conservative profile.
#>

[CmdletBinding()]
param(
    [switch]$Json,
    [string]$OutFile,
    [string]$IniFile,
    [switch]$Quiet
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Continue'

function Write-Probe {
    param([string]$Message)
    if (-not $Quiet) { Write-Host $Message -ForegroundColor DarkGray }
}

function Get-Cim {
    <# CIM with a WMI fallback; never throws. #>
    param([Parameter(Mandatory)][string]$Class)
    try {
        return @(Get-CimInstance -ClassName $Class -ErrorAction Stop)
    } catch {
        try { return @(Get-WmiObject -Class $Class -ErrorAction Stop) } catch { return @() }
    }
}

function Get-Prop {
    <# Property access that tolerates a missing property under StrictMode. #>
    param($Object, [string]$Name, $Default = $null)
    if ($null -eq $Object) { return $Default }
    $p = $Object.PSObject.Properties[$Name]
    if (-not $p) { return $Default }
    if ($null -eq $p.Value) { return $Default }
    return $p.Value
}

# ==========================================================================
# Operating system
# ==========================================================================

$os = Get-Cim -Class 'Win32_OperatingSystem' | Select-Object -First 1
$osCaption = [string](Get-Prop $os 'Caption' 'unknown')
$osBuildRaw = [string](Get-Prop $os 'BuildNumber' '0')
$osBuild = 0
[void][int]::TryParse($osBuildRaw, [ref]$osBuild)
$osArch = [string](Get-Prop $os 'OSArchitecture' '')

# ==========================================================================
# CPU / RAM
# ==========================================================================

$cpus = Get-Cim -Class 'Win32_Processor'
$cpu = $cpus | Select-Object -First 1
$cpuName = ([string](Get-Prop $cpu 'Name' 'unknown')).Trim()
$cpuCores = 0
foreach ($c in $cpus) { $cpuCores += [int](Get-Prop $c 'NumberOfCores' 0) }
$cpuThreads = 0
foreach ($c in $cpus) { $cpuThreads += [int](Get-Prop $c 'NumberOfLogicalProcessors' 0) }

$cs = Get-Cim -Class 'Win32_ComputerSystem' | Select-Object -First 1
$ramBytes = [double](Get-Prop $cs 'TotalPhysicalMemory' 0)
$ramGB = [math]::Round($ramBytes / 1GB, 1)

# ==========================================================================
# Chassis: laptop or desktop
# ==========================================================================

# DMI chassis types that mean "portable". 30/31/32 are tablet/convertible/
# detachable, which for our purposes behave like laptops.
$portableChassis = @(8, 9, 10, 11, 12, 14, 18, 21, 30, 31, 32)
$chassisTypes = @()
foreach ($enc in (Get-Cim -Class 'Win32_SystemEnclosure')) {
    foreach ($t in @(Get-Prop $enc 'ChassisTypes' @())) { $chassisTypes += [int]$t }
}
$batteries = @(Get-Cim -Class 'Win32_Battery')
# @() around the pipeline: a Where-Object that matches nothing returns $null,
# and .Count on $null throws under Set-StrictMode.
$portableMatches = @($chassisTypes | Where-Object { $portableChassis -contains $_ })
$isLaptop = [bool]($portableMatches.Count -gt 0 -or $batteries.Count -gt 0)

# ==========================================================================
# GPU / CUDA
# ==========================================================================

$gpus = New-Object System.Collections.Generic.List[object]
foreach ($v in (Get-Cim -Class 'Win32_VideoController')) {
    $name = ([string](Get-Prop $v 'Name' '')).Trim()
    if (-not $name) { continue }
    # AdapterRAM is a uint32 and saturates at 4 GB, so it is only a hint.
    $adapterRam = [double](Get-Prop $v 'AdapterRAM' 0)
    $gpus.Add([pscustomobject]@{
        Name          = $name
        DriverVersion = [string](Get-Prop $v 'DriverVersion' '')
        AdapterRamGB  = if ($adapterRam -gt 0) { [math]::Round($adapterRam / 1GB, 1) } else { 0 }
        Vendor        = if ($name -match 'NVIDIA') { 'NVIDIA' }
                        elseif ($name -match 'AMD|Radeon') { 'AMD' }
                        elseif ($name -match 'Intel') { 'Intel' }
                        else { 'Other' }
    })
}

# nvidia-smi is authoritative when it exists: a video controller named NVIDIA
# with no working driver cannot run CUDA.
$nvidiaSmi = $null
$smiCandidates = New-Object System.Collections.Generic.List[string]
$smiCandidates.Add('nvidia-smi')
$sysFolder = [Environment]::GetFolderPath('System')
if ($sysFolder) { $smiCandidates.Add([System.IO.Path]::Combine($sysFolder, 'nvidia-smi.exe')) }
$smiCandidates.Add('C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe')
foreach ($candidate in $smiCandidates) {
    if (-not $candidate) { continue }
    $resolved = $null
    if ($candidate -notmatch '[\\/]') {
        $cmd = Get-Command $candidate -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($cmd) { $resolved = $cmd.Source }
    } elseif ([System.IO.File]::Exists($candidate)) {
        $resolved = $candidate
    }
    if ($resolved) { $nvidiaSmi = $resolved; break }
}

$nvidiaGpus = New-Object System.Collections.Generic.List[object]
$driverVersion = ''
$cudaVersion = ''
if ($nvidiaSmi) {
    Write-Probe "probing $nvidiaSmi"
    try {
        $q = & $nvidiaSmi --query-gpu=name,memory.total,driver_version --format=csv,noheader,nounits 2>$null
        foreach ($line in @($q)) {
            if (-not $line -or -not $line.Trim()) { continue }
            $parts = $line -split ','
            if ($parts.Count -lt 3) { continue }
            $vram = 0
            [void][int]::TryParse($parts[1].Trim(), [ref]$vram)
            $nvidiaGpus.Add([pscustomobject]@{
                Name    = $parts[0].Trim()
                VramGB  = [math]::Round($vram / 1024, 1)
                Driver  = $parts[2].Trim()
            })
            $driverVersion = $parts[2].Trim()
        }
        # "CUDA Version: 12.4" appears in the nvidia-smi banner.
        $banner = & $nvidiaSmi 2>$null | Out-String
        $m = [regex]::Match($banner, 'CUDA Version:\s*([0-9]+\.[0-9]+)')
        if ($m.Success) { $cudaVersion = $m.Groups[1].Value }
    } catch {
        Write-Probe "nvidia-smi probe failed: $($_.Exception.Message)"
    }
}

$hasNvidiaHardware = [bool](@($gpus | Where-Object { $_.Vendor -eq 'NVIDIA' }).Count -gt 0)
# CUDA is only worth installing when a driver actually answers.
$cudaCapable = [bool]($nvidiaGpus.Count -gt 0)
$maxVramGB = 0.0
foreach ($g in $nvidiaGpus) { if ($g.VramGB -gt $maxVramGB) { $maxVramGB = $g.VramGB } }

# ==========================================================================
# Virtualization / WSL2 capability
#
# This is the check whose absence made earlier builds fail: setup would enable
# the WSL2 Windows features and install Docker on machines whose firmware has
# virtualization switched off, leaving a half-configured system that could
# never start the engine.
# ==========================================================================

# HypervisorPresent is true when something (Hyper-V, WSL2, a VM) is already
# running a hypervisor. Critically, when it is true the CPU is itself
# virtualized and Win32_Processor.VirtualizationFirmwareEnabled reports FALSE
# even though virtualization plainly works - so the two must be OR'd, never
# read in isolation.
$hypervisorPresent = [bool](Get-Prop $cs 'HypervisorPresent' $false)
$firmwareVirt = $false
$slat = $false
foreach ($c in $cpus) {
    if ([bool](Get-Prop $c 'VirtualizationFirmwareEnabled' $false)) { $firmwareVirt = $true }
    if ([bool](Get-Prop $c 'SecondLevelAddressTranslationExtensions' $false)) { $slat = $true }
}
$virtualizationAvailable = [bool]($hypervisorPresent -or $firmwareVirt)

# Windows feature state (may need elevation; absence is not proof of anything).
function Get-FeatureState {
    param([Parameter(Mandatory)][string]$Name)
    try {
        $f = Get-WindowsOptionalFeature -Online -FeatureName $Name -ErrorAction Stop
        return ($f.State -eq 'Enabled')
    } catch {
        return $null
    }
}
$featureWsl = Get-FeatureState -Name 'Microsoft-Windows-Subsystem-Linux'
$featureVmp = Get-FeatureState -Name 'VirtualMachinePlatform'

$wslExe = Get-Command 'wsl' -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
$wslKernel = $false
if ($wslExe) {
    try {
        $status = (& $wslExe.Source --status 2>&1 | Out-String) -replace "`0", ''
        $wslKernel = ($LASTEXITCODE -eq 0 -and $status.Trim().Length -gt 0)
    } catch { }
}

# WSL2 needs Windows 10 2004 (build 19041) or newer AND working virtualization.
$buildOk = ($osBuild -ge 19041)
$wsl2Capable = [bool]($buildOk -and $virtualizationAvailable)

$wsl2Blocker = ''
if (-not $buildOk) {
    $wsl2Blocker = "Windows build $osBuild is older than 19041 (Windows 10 version 2004), which WSL2 requires."
} elseif (-not $virtualizationAvailable) {
    $wsl2Blocker = 'Hardware virtualization is not available. It is switched off in this computer''s firmware (BIOS/UEFI), so WSL2 and Docker Desktop cannot run.'
}

# ==========================================================================
# Disk
# ==========================================================================

$systemDrive = if ($env:SystemDrive) { $env:SystemDrive } else { 'C:' }
$freeGB = 0.0
$totalGB = 0.0
try {
    $disk = Get-Cim -Class 'Win32_LogicalDisk' | Where-Object { $_.DeviceID -eq $systemDrive } | Select-Object -First 1
    if ($disk) {
        $freeGB = [math]::Round([double](Get-Prop $disk 'FreeSpace' 0) / 1GB, 1)
        $totalGB = [math]::Round([double](Get-Prop $disk 'Size' 0) / 1GB, 1)
    }
} catch { }

# ==========================================================================
# Recommendation
# ==========================================================================

# The profile decides which Python wheels get downloaded. Installing multi-
# gigabyte CUDA builds of torch/onnxruntime on a machine with no usable NVIDIA
# driver is pure waste, so anything without a working driver gets 'api'.
$recommendedProfile = if ($cudaCapable -and $maxVramGB -ge 4) { 'cuda' } else { 'api' }

$recommendedRuntime = if ($wsl2Capable) { 'container' } else { 'native' }

$warnings = New-Object System.Collections.Generic.List[string]
if (-not $virtualizationAvailable) {
    $warnings.Add('Hardware virtualization is disabled in firmware; Docker Desktop and WSL2 will be skipped and RedSight will run in native mode.')
}
if ($hasNvidiaHardware -and -not $cudaCapable) {
    $warnings.Add('An NVIDIA GPU is present but nvidia-smi did not respond, so the driver is missing or too old. CUDA packages will not be installed - update the NVIDIA driver and re-run setup to enable GPU acceleration.')
}
if ($ramGB -gt 0 -and $ramGB -lt 8) {
    $warnings.Add("Only $ramGB GB of RAM detected; RedSight will run but local inference will be slow.")
}
if ($freeGB -gt 0 -and $freeGB -lt 8) {
    $warnings.Add("Only $freeGB GB free on $systemDrive; setup needs roughly 8 GB.")
}

$hw = [ordered]@{
    scannedAt   = (Get-Date -Format 'o')
    os          = [ordered]@{
        caption = $osCaption
        build   = $osBuild
        arch    = $osArch
    }
    cpu         = [ordered]@{
        name    = $cpuName
        cores   = $cpuCores
        threads = $cpuThreads
    }
    memoryGB    = $ramGB
    disk        = [ordered]@{
        drive   = $systemDrive
        freeGB  = $freeGB
        totalGB = $totalGB
    }
    chassis     = [ordered]@{
        isLaptop     = $isLaptop
        chassisTypes = $chassisTypes
        hasBattery   = ($batteries.Count -gt 0)
    }
    gpu         = [ordered]@{
        adapters          = $gpus.ToArray()
        nvidia            = $nvidiaGpus.ToArray()
        hasNvidiaHardware = $hasNvidiaHardware
        cudaCapable       = $cudaCapable
        maxVramGB         = $maxVramGB
        driverVersion     = $driverVersion
        cudaVersion       = $cudaVersion
        nvidiaSmi         = $nvidiaSmi
    }
    virtualization = [ordered]@{
        available          = $virtualizationAvailable
        hypervisorPresent  = $hypervisorPresent
        firmwareEnabled    = $firmwareVirt
        slat               = $slat
        wsl2Capable        = $wsl2Capable
        wsl2Blocker        = $wsl2Blocker
        featureWsl         = $featureWsl
        featureVmp         = $featureVmp
        wslKernel          = $wslKernel
    }
    recommend   = [ordered]@{
        setupProfile = $recommendedProfile
        runtimeMode  = $recommendedRuntime
    }
    warnings    = $warnings.ToArray()
}

if ($OutFile) {
    try {
        $dir = Split-Path -Parent $OutFile
        if ($dir) { New-Item -ItemType Directory -Path $dir -Force -ErrorAction SilentlyContinue | Out-Null }
        ($hw | ConvertTo-Json -Depth 8) | Set-Content -LiteralPath $OutFile -Encoding utf8
        Write-Probe "hardware profile written to $OutFile"
    } catch {
        Write-Probe "could not write $OutFile : $($_.Exception.Message)"
    }
}

if ($IniFile) {
    # Inno Setup reads INI natively with GetIniString, which is far more robust
    # than parsing JSON in Pascal script.
    try {
        $dir = Split-Path -Parent $IniFile
        if ($dir) { New-Item -ItemType Directory -Path $dir -Force -ErrorAction SilentlyContinue | Out-Null }
        $gpuName = ''
        if ($nvidiaGpus.Count -gt 0) { $gpuName = $nvidiaGpus[0].Name }
        elseif ($gpus.Count -gt 0) { $gpuName = $gpus[0].Name }

        function ConvertTo-IniBool { param($Value) ; if ($Value) { '1' } else { '0' } }

        $lines = New-Object System.Collections.Generic.List[string]
        $lines.Add('[hardware]')
        $lines.Add("osCaption=$osCaption")
        $lines.Add("osBuild=$osBuild")
        $lines.Add("cpuName=$cpuName")
        $lines.Add("cpuCores=$cpuCores")
        $lines.Add("memoryGB=$ramGB")
        $lines.Add("diskFreeGB=$freeGB")
        $lines.Add("isLaptop=$(ConvertTo-IniBool $isLaptop)")
        $lines.Add("gpuName=$gpuName")
        $lines.Add("hasNvidiaHardware=$(ConvertTo-IniBool $hasNvidiaHardware)")
        $lines.Add("cudaCapable=$(ConvertTo-IniBool $cudaCapable)")
        $lines.Add("maxVramGB=$maxVramGB")
        $lines.Add("cudaVersion=$cudaVersion")
        $lines.Add("driverVersion=$driverVersion")
        $lines.Add("virtAvailable=$(ConvertTo-IniBool $virtualizationAvailable)")
        $lines.Add("wsl2Capable=$(ConvertTo-IniBool $wsl2Capable)")
        # INI values are single-line; collapse any newlines out of the blocker.
        $lines.Add("wsl2Blocker=$(($wsl2Blocker -replace '\s+', ' ').Trim())")
        $lines.Add("recommendProfile=$recommendedProfile")
        $lines.Add("recommendRuntime=$recommendedRuntime")
        $lines.Add("warningCount=$($warnings.Count)")
        for ($i = 0; $i -lt $warnings.Count; $i++) {
            $lines.Add("warning$($i + 1)=$(($warnings[$i] -replace '\s+', ' ').Trim())")
        }
        Set-Content -LiteralPath $IniFile -Value $lines.ToArray() -Encoding utf8
        Write-Probe "hardware INI written to $IniFile"
    } catch {
        Write-Probe "could not write $IniFile : $($_.Exception.Message)"
    }
}

if ($Json) {
    $hw | ConvertTo-Json -Depth 8
} elseif (-not $Quiet) {
    Write-Host ''
    Write-Host 'RedSight hardware scan' -ForegroundColor Cyan
    Write-Host ('-' * 60)
    Write-Host ("  OS              : {0} (build {1})" -f $osCaption, $osBuild)
    Write-Host ("  CPU             : {0} ({1} cores / {2} threads)" -f $cpuName, $cpuCores, $cpuThreads)
    Write-Host ("  Memory          : {0} GB" -f $ramGB)
    Write-Host ("  Disk free       : {0} GB on {1}" -f $freeGB, $systemDrive)
    Write-Host ("  Form factor     : {0}" -f $(if ($isLaptop) { 'laptop / portable' } else { 'desktop' }))
    foreach ($g in $gpus) { Write-Host ("  GPU             : {0} [{1}]" -f $g.Name, $g.Vendor) }
    Write-Host ("  CUDA capable    : {0}{1}" -f $cudaCapable, $(if ($cudaVersion) { " (CUDA $cudaVersion, driver $driverVersion)" } else { '' }))
    Write-Host ("  Virtualization  : {0} (hypervisor={1} firmware={2})" -f $virtualizationAvailable, $hypervisorPresent, $firmwareVirt)
    Write-Host ("  WSL2 capable    : {0}" -f $wsl2Capable)
    if ($wsl2Blocker) { Write-Host ("                    {0}" -f $wsl2Blocker) -ForegroundColor Yellow }
    Write-Host ("  Recommended     : {0} profile, {1} runtime" -f $recommendedProfile, $recommendedRuntime) -ForegroundColor Green
    foreach ($w in $warnings) { Write-Host ("  ! {0}" -f $w) -ForegroundColor Yellow }
    Write-Host ('-' * 60)
}

exit 0
