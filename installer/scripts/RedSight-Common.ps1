<#
    RedSight-Common.ps1

    Shared helpers for the RedSight Windows setup pipeline: structured logging,
    resilient downloads, hash verification, archive handling, process execution
    with timeouts, PATH manipulation and reboot-resume registration.

    Dot-sourced by RedSight-Preflight.ps1, Bootstrap-RedSight.ps1 and
    Verify-RedSightSetup.ps1. Contains no top-level side effects other than
    defining functions and $script:RsLog defaults, so it is safe to import from
    tests.
#>

Set-StrictMode -Version Latest

# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------

$script:RsLogPath = $null
$script:RsSummary = [ordered]@{}

function Initialize-RsLog {
    <#
        Creates the log directory and opens a timestamped log file.
        Everything written through Write-RsLog lands both on the console and in
        this file, so a failed unattended install can always be diagnosed.
    #>
    [CmdletBinding()]
    param(
        [string]$Name = 'bootstrap',
        [string]$LogDir
    )

    if (-not $LogDir) { $LogDir = Join-Path (Get-RsLocalAppData) 'RedSight\logs' }
    New-Item -ItemType Directory -Path $LogDir -Force -ErrorAction SilentlyContinue | Out-Null
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $script:RsLogPath = Join-Path $LogDir ("{0}-{1}.log" -f $Name, $stamp)
    # Touch the file so later appends cannot fail on a missing directory.
    Set-Content -LiteralPath $script:RsLogPath -Value '' -Encoding utf8 -ErrorAction SilentlyContinue
    return $script:RsLogPath
}

function Get-RsLogPath { return $script:RsLogPath }

function Write-RsLog {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory, Position = 0)][AllowEmptyString()][string]$Message,
        [ValidateSet('INFO', 'STEP', 'OK', 'WARN', 'FAIL', 'DEBUG')][string]$Level = 'INFO'
    )

    $line = '{0}  {1,-5}  {2}' -f (Get-Date -Format 'yyyy-MM-ddTHH:mm:ss'), $Level, $Message
    if ($script:RsLogPath) {
        # Never let logging break the install.
        try { Add-Content -LiteralPath $script:RsLogPath -Value $line -Encoding utf8 -ErrorAction Stop } catch { }
    }

    $color = switch ($Level) {
        'STEP'  { 'Cyan' }
        'OK'    { 'Green' }
        'WARN'  { 'Yellow' }
        'FAIL'  { 'Red' }
        'DEBUG' { 'DarkGray' }
        default { 'Gray' }
    }
    Write-Host $line -ForegroundColor $color
}

function Set-RsSummary {
    <# Records a key/value pair for the machine-readable setup summary. #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Key,
        [Parameter(Mandatory)][AllowNull()]$Value
    )
    $script:RsSummary[$Key] = $Value
}

function Get-RsSummary { return $script:RsSummary }

function Save-RsSummary {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Path)
    try {
        New-Item -ItemType Directory -Path (Split-Path -Parent $Path) -Force -ErrorAction SilentlyContinue | Out-Null
        ($script:RsSummary | ConvertTo-Json -Depth 6) | Set-Content -LiteralPath $Path -Encoding utf8
        Write-RsLog "Setup summary written to $Path" -Level DEBUG
    } catch {
        Write-RsLog "Could not write setup summary: $($_.Exception.Message)" -Level WARN
    }
}

# --------------------------------------------------------------------------
# Environment probing
# --------------------------------------------------------------------------

function Test-RsAdmin {
    <# True when the current process holds the local Administrators role. #>
    [CmdletBinding()] param()
    # $IsWindows only exists on PowerShell 6+; Windows PowerShell 5.1 is always Windows.
    $onWindows = if ($PSVersionTable.PSEdition -eq 'Desktop') { $true }
                 else { [bool](Get-Variable -Name IsWindows -ValueOnly -ErrorAction SilentlyContinue) }
    if (-not $onWindows) {
        # Non-Windows (test harness) - never elevated.
        return $false
    }
    try {
        $id = [Security.Principal.WindowsIdentity]::GetCurrent()
        $principal = New-Object Security.Principal.WindowsPrincipal($id)
        return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    } catch {
        return $false
    }
}

function Test-RsOnline {
    <#
        Cheap reachability probe. Used to decide between wheelhouse-only and
        online installs, never to hard-fail: a false negative just means we try
        the network anyway and report a real error if it fails.
    #>
    [CmdletBinding()]
    param([string[]]$Hosts = @('pypi.org', 'files.pythonhosted.org'), [int]$TimeoutSeconds = 8)

    foreach ($h in $Hosts) {
        try {
            $req = [System.Net.HttpWebRequest]::Create("https://$h/")
            $req.Method = 'HEAD'
            $req.Timeout = $TimeoutSeconds * 1000
            $resp = $req.GetResponse()
            $resp.Dispose()
            return $true
        } catch {
            # A protocol-level error still proves we reached the host.
            if ($_.Exception.Response) { return $true }
        }
    }
    return $false
}

function Get-RsSystemDir {
    <#
        %WINDIR% with fallbacks. Windows always sets it, but a stripped
        environment (a service account, a test harness, a non-Windows host) may
        not, and Join-Path throws on a null path - which used to abort setup
        before it could report anything useful.
    #>
    [CmdletBinding()] param()
    if ($env:WINDIR)     { return $env:WINDIR }
    if ($env:SystemRoot) { return $env:SystemRoot }
    return 'C:\Windows'
}

function Get-RsSystem32 {
    <#
        Full path to a System32 executable, e.g. Get-RsSystem32 'dism.exe'.
        Built with [IO.Path]::Combine rather than Join-Path: Join-Path resolves
        the path through the PowerShell provider stack and fails on a drive the
        current host does not have, which is exactly what happens when these
        scripts are exercised off Windows.
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Leaf)
    return [System.IO.Path]::Combine((Get-RsSystemDir), 'System32', $Leaf)
}

function Get-RsPowerShellExe {
    <# Windows PowerShell 5.1, which is what the installer invokes scripts with. #>
    [CmdletBinding()] param()
    return [System.IO.Path]::Combine([string[]]@(
        (Get-RsSystemDir), 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe'))
}

function Get-RsLocalAppData {
    <# %LOCALAPPDATA% with a temp-dir fallback. #>
    [CmdletBinding()] param()
    if ($env:LOCALAPPDATA) { return $env:LOCALAPPDATA }
    if ($env:APPDATA)      { return $env:APPDATA }
    return ([System.IO.Path]::GetTempPath())
}

function Get-RsCommand {
    <# Resolves an executable on PATH, returning $null instead of throwing. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Name)
    return (Get-Command $Name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1)
}

# --------------------------------------------------------------------------
# Process execution
# --------------------------------------------------------------------------

function Invoke-RsProcess {
    <#
        Runs an executable, streams stdout/stderr into the log, and enforces a
        timeout so an unattended install can never hang forever on a child
        process that is waiting for input.

        Returns a PSCustomObject with ExitCode / TimedOut / StdOut / StdErr.
        Does not throw on a non-zero exit code - callers decide what is fatal.

        -HeartbeatSeconds logs a line at that interval while the child runs.
        Output cannot be read until the pipes close, so a long step is silent
        without it and looks like a hang.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [string[]]$Arguments = @(),
        [string]$WorkingDirectory,
        [int]$TimeoutSeconds = 1800,
        [int]$HeartbeatSeconds = 0,
        [switch]$Quiet
    )

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $FilePath
    # ArgumentList keeps quoting correct on PS7; fall back to a joined string on PS5.
    if ($psi.PSObject.Properties.Name -contains 'ArgumentList') {
        foreach ($a in $Arguments) { $psi.ArgumentList.Add($a) }
    } else {
        $psi.Arguments = ($Arguments | ForEach-Object {
            if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ }
        }) -join ' '
    }
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    if ($WorkingDirectory) { $psi.WorkingDirectory = $WorkingDirectory }

    $shown = if ($Arguments.Count) { "$FilePath $($Arguments -join ' ')" } else { $FilePath }
    if (-not $Quiet) { Write-RsLog "exec: $shown" -Level DEBUG }

    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi

    try {
        try {
            [void]$proc.Start()
        } catch {
            # A missing, corrupt or non-executable target must not blow up the
            # caller: report it like any other failed command so probes such as
            # Get-RsPythonVersion can simply treat it as unusable.
            Write-RsLog "could not start process: $shown :: $($_.Exception.Message)" -Level DEBUG
            return [pscustomobject]@{
                ExitCode = -1
                TimedOut = $false
                StdOut   = ''
                StdErr   = $_.Exception.Message
                Command  = $shown
            }
        }

        # Drain both pipes with .NET async reads rather than PowerShell events:
        # Register-ObjectEvent handlers only run when the engine pumps its event
        # queue, which it does not do while the pipeline is blocked in
        # WaitForExit - so event-based capture silently loses output. Task-based
        # reads run on the thread pool and also prevent a full-pipe deadlock.
        $outTask = $proc.StandardOutput.ReadToEndAsync()
        $errTask = $proc.StandardError.ReadToEndAsync()

        if ($HeartbeatSeconds -gt 0) {
            # Output is only readable once the pipes close, so a step like
            # "docker compose build" would otherwise print nothing for twenty
            # minutes and read as hung. A heartbeat says it is still working.
            $waited = 0
            $timedOut = $false
            while (-not $proc.WaitForExit($HeartbeatSeconds * 1000)) {
                $waited += $HeartbeatSeconds
                if ($waited -ge $TimeoutSeconds) { $timedOut = $true; break }
                Write-RsLog ("    still running after {0:n0}s (timeout {1:n0}s)" -f $waited, $TimeoutSeconds) -Level INFO
            }
        } else {
            $timedOut = -not $proc.WaitForExit($TimeoutSeconds * 1000)
        }
        if ($timedOut) {
            Write-RsLog "TIMEOUT after ${TimeoutSeconds}s: $shown" -Level WARN
            # Kill the whole tree where supported: installers spawn children.
            try { $proc.Kill($true) } catch { try { $proc.Kill() } catch { } }
            try { [void]$proc.WaitForExit(15000) } catch { }
        }

        # Once the process is gone the pipes close and both tasks complete.
        $out = ''
        $err = ''
        try { if ($outTask.Wait(15000)) { $out = $outTask.Result } } catch { }
        try { if ($errTask.Wait(15000)) { $err = $errTask.Result } } catch { }
        if ($null -eq $out) { $out = '' }
        if ($null -eq $err) { $err = '' }

        $exit = if ($timedOut) { -1 } else { $proc.ExitCode }

        if (-not $Quiet) {
            foreach ($stream in @($out, $err)) {
                foreach ($l in ($stream -split "`r?`n")) {
                    if ($l.Trim()) { Write-RsLog "    | $l" -Level DEBUG }
                }
            }
        }

        return [pscustomobject]@{
            ExitCode = $exit
            TimedOut = $timedOut
            StdOut   = $out
            StdErr   = $err
            Command  = $shown
        }
    } finally {
        $proc.Dispose()
    }
}

function Invoke-RsRetry {
    <#
        Retries a scriptblock with exponential backoff. Used for every network
        operation so a transient DNS/TLS hiccup does not fail the whole install.
        The scriptblock must throw to signal failure.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][scriptblock]$Action,
        [string]$Description = 'operation',
        [int]$MaxAttempts = 4,
        [int]$InitialDelaySeconds = 2
    )

    $delay = $InitialDelaySeconds
    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        try {
            $out = & $Action
            # Emitting $null here would pollute the caller's return value.
            if ($null -ne $out) { return $out }
            return
        } catch {
            $msg = $_.Exception.Message
            if ($attempt -eq $MaxAttempts) {
                Write-RsLog "$Description failed after $MaxAttempts attempts: $msg" -Level FAIL
                throw
            }
            Write-RsLog "$Description failed (attempt $attempt/$MaxAttempts): $msg - retrying in ${delay}s" -Level WARN
            Start-Sleep -Seconds $delay
            $delay = $delay * 2
        }
    }
}

# --------------------------------------------------------------------------
# Downloads
# --------------------------------------------------------------------------

function Get-RsFileHashSafe {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Path, [string]$Algorithm = 'SHA256')
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    return (Get-FileHash -LiteralPath $Path -Algorithm $Algorithm).Hash.ToLowerInvariant()
}

function Save-RsDownload {
    <#
        Downloads $Uri to $Destination with retries, resumable temp file and
        optional SHA256 verification. If the destination already exists and
        matches the expected hash, the download is skipped entirely - this is
        what makes re-running the bootstrap cheap.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Uri,
        [Parameter(Mandatory)][string]$Destination,
        [string]$Sha256,
        [int]$TimeoutSeconds = 1800,
        [string]$Description
    )

    if (-not $Description) { $Description = Split-Path -Leaf $Destination }

    if (Test-Path -LiteralPath $Destination) {
        if (-not $Sha256) {
            Write-RsLog "$Description already present (no hash to verify) - reusing" -Level OK
            return $Destination
        }
        $have = Get-RsFileHashSafe -Path $Destination
        if ($have -eq $Sha256.ToLowerInvariant()) {
            Write-RsLog "$Description already present and hash-verified - reusing" -Level OK
            return $Destination
        }
        Write-RsLog "$Description present but hash mismatch - re-downloading" -Level WARN
        Remove-Item -LiteralPath $Destination -Force -ErrorAction SilentlyContinue
    }

    New-Item -ItemType Directory -Path (Split-Path -Parent $Destination) -Force -ErrorAction SilentlyContinue | Out-Null
    $tmp = "$Destination.part"

    Invoke-RsRetry -Description "download $Description" -Action {
        if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue }
        Write-RsLog "Downloading $Description from $Uri" -Level STEP

        # TLS 1.2+ must be explicit on stock Windows PowerShell 5.1.
        try {
            [Net.ServicePointManager]::SecurityProtocol =
                [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls13
        } catch {
            try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch { }
        }

        $ProgressPreference = 'SilentlyContinue'   # Invoke-WebRequest is ~10x slower with it
        Invoke-WebRequest -Uri $Uri -OutFile $tmp -UseBasicParsing -TimeoutSec $TimeoutSeconds -MaximumRedirection 10

        if (-not (Test-Path -LiteralPath $tmp)) { throw 'download produced no file' }
        $len = (Get-Item -LiteralPath $tmp).Length
        if ($len -le 0) { throw 'download produced an empty file' }

        if ($Sha256) {
            $actual = (Get-FileHash -LiteralPath $tmp -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($actual -ne $Sha256.ToLowerInvariant()) {
                throw "SHA256 mismatch: expected $Sha256, got $actual"
            }
            Write-RsLog "    hash verified ($Sha256)" -Level OK
        }

        Move-Item -LiteralPath $tmp -Destination $Destination -Force
        Write-RsLog "    saved $Description ($([math]::Round($len / 1MB, 1)) MB)" -Level OK
    }

    return $Destination
}

function Expand-RsArchive {
    <#
        Expands a .zip (or NuGet .nupkg, which is a zip) into a directory.
        Uses System.IO.Compression directly: Expand-Archive is unavailable on
        some minimal PowerShell 5.1 installs and much slower on large payloads.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Destination,
        [switch]$Force
    )

    if ((Test-Path -LiteralPath $Destination) -and $Force) {
        Remove-Item -LiteralPath $Destination -Recurse -Force -ErrorAction SilentlyContinue
    }
    New-Item -ItemType Directory -Path $Destination -Force -ErrorAction SilentlyContinue | Out-Null

    Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction SilentlyContinue
    $full = (Resolve-Path -LiteralPath $Path).Path
    $destFull = (Resolve-Path -LiteralPath $Destination).Path

    $zip = [System.IO.Compression.ZipFile]::OpenRead($full)
    try {
        foreach ($entry in $zip.Entries) {
            # Skip directory entries.
            if (-not $entry.Name) { continue }

            $target = Join-Path $destFull $entry.FullName
            # Guard against path traversal in a hostile archive.
            $resolved = [System.IO.Path]::GetFullPath($target)
            if (-not $resolved.StartsWith($destFull, [StringComparison]::OrdinalIgnoreCase)) {
                Write-RsLog "skipping archive entry outside destination: $($entry.FullName)" -Level WARN
                continue
            }
            New-Item -ItemType Directory -Path (Split-Path -Parent $resolved) -Force -ErrorAction SilentlyContinue | Out-Null
            [System.IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $resolved, $true)
        }
    } finally {
        $zip.Dispose()
    }
    return $Destination
}

# --------------------------------------------------------------------------
# PATH handling
# --------------------------------------------------------------------------

function Add-RsPathEntry {
    <#
        Adds a directory to the machine (or user) PATH if absent, and to the
        current process PATH so the rest of this run can see it without a
        restart. Machine scope needs elevation; falls back to user scope.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Directory,
        [ValidateSet('Machine', 'User')][string]$Scope = 'Machine'
    )

    if (-not (Test-Path -LiteralPath $Directory)) {
        Write-RsLog "not adding missing directory to PATH: $Directory" -Level WARN
        return $false
    }
    $normalized = (Resolve-Path -LiteralPath $Directory).Path.TrimEnd('\')

    if ($Scope -eq 'Machine' -and -not (Test-RsAdmin)) {
        Write-RsLog 'not elevated - adding to user PATH instead of machine PATH' -Level WARN
        $Scope = 'User'
    }

    $target = [EnvironmentVariableTarget]::$Scope
    $current = [Environment]::GetEnvironmentVariable('Path', $target)
    if (-not $current) { $current = '' }

    $parts = $current -split ';' | Where-Object { $_ -and $_.Trim() }
    $already = $parts | Where-Object { $_.TrimEnd('\') -ieq $normalized }
    if (-not $already) {
        $new = (@($parts) + $normalized) -join ';'
        [Environment]::SetEnvironmentVariable('Path', $new, $target)
        Write-RsLog "added to $Scope PATH: $normalized" -Level OK
    } else {
        Write-RsLog "$Scope PATH already contains $normalized" -Level DEBUG
    }

    # Make it effective for the remainder of this process.
    $procParts = ($env:Path -split ';') | Where-Object { $_ -and $_.Trim() }
    if (-not ($procParts | Where-Object { $_.TrimEnd('\') -ieq $normalized })) {
        $env:Path = "$env:Path;$normalized"
    }
    return $true
}

function Update-RsProcessPath {
    <# Re-reads machine+user PATH into the current process, e.g. after an installer ran. #>
    [CmdletBinding()] param()
    try {
        $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
        $user = [Environment]::GetEnvironmentVariable('Path', 'User')
        $env:Path = (@($machine, $user) | Where-Object { $_ }) -join ';'
        Write-RsLog 'refreshed process PATH from machine + user environment' -Level DEBUG
    } catch {
        Write-RsLog "could not refresh PATH: $($_.Exception.Message)" -Level WARN
    }
}

# --------------------------------------------------------------------------
# Reboot-resume
# --------------------------------------------------------------------------

function Register-RsResumeAfterReboot {
    <#
        Enabling the WSL2 / VirtualMachinePlatform Windows features can require
        a restart before Docker Desktop will run. Rather than silently leaving a
        half-configured machine, register a RunOnce entry that resumes the
        bootstrap for the next interactive logon.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$ProjectRoot,
        [string]$ExtraArguments = ''
    )

    $script = Join-Path $ProjectRoot 'scripts\windows\Bootstrap-RedSight.ps1'
    if (-not (Test-Path -LiteralPath $script)) {
        Write-RsLog "cannot register resume: $script not found" -Level WARN
        return $false
    }

    $cmd = '"{0}" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "{1}" -Resume {2}' -f `
        (Get-RsPowerShellExe), $script, $ExtraArguments

    try {
        $key = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce'
        if (-not (Test-RsAdmin)) { $key = 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce' }
        New-Item -Path $key -Force -ErrorAction SilentlyContinue | Out-Null
        Set-ItemProperty -Path $key -Name 'RedSightSetupResume' -Value $cmd -Force
        Write-RsLog "registered post-reboot resume under $key" -Level OK
        return $true
    } catch {
        Write-RsLog "could not register post-reboot resume: $($_.Exception.Message)" -Level WARN
        return $false
    }
}

function Unregister-RsResumeAfterReboot {
    [CmdletBinding()] param()
    foreach ($key in @('HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce',
                       'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce')) {
        try {
            if (Test-Path $key) {
                Remove-ItemProperty -Path $key -Name 'RedSightSetupResume' -ErrorAction SilentlyContinue
            }
        } catch { }
    }
}

# --------------------------------------------------------------------------
# Version helpers
# --------------------------------------------------------------------------

function ConvertTo-RsVersion {
    <#
        Parses the first dotted numeric run out of arbitrary tool output
        ("Python 3.12.10", "Docker version 27.4.0, build ...", "v22.11.0").
        Returns $null when nothing version-like is present.
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][AllowEmptyString()][AllowNull()][string]$Text)

    if (-not $Text) { return $null }
    $m = [regex]::Match($Text, '(\d+)\.(\d+)(?:\.(\d+))?(?:\.(\d+))?')
    if (-not $m.Success) { return $null }
    $parts = @($m.Groups[1].Value, $m.Groups[2].Value)
    if ($m.Groups[3].Success) { $parts += $m.Groups[3].Value }
    if ($m.Groups[4].Success) { $parts += $m.Groups[4].Value }
    try { return [version]($parts -join '.') } catch { return $null }
}

function Test-RsVersionInRange {
    <# Inclusive lower bound, exclusive upper bound - the usual "3.12 <= v < 3.14". #>
    [CmdletBinding()]
    param(
        [AllowNull()][version]$Version,
        [Parameter(Mandatory)][version]$Minimum,
        [AllowNull()][version]$ExclusiveMaximum
    )
    if (-not $Version) { return $false }
    if ($Version -lt $Minimum) { return $false }
    if ($ExclusiveMaximum -and $Version -ge $ExclusiveMaximum) { return $false }
    return $true
}
