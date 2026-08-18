$ErrorActionPreference = "Stop"

$Root = "C:\Users\walim\RedSight"
$DockerDesktopExe = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
$Hotfix = Join-Path $Root "REDSIGHT-UI-HOTFIX-RESTART.ps1"

Set-Location $Root

Write-Host ""
Write-Host "================================================================="
Write-Host " DOCKER DESKTOP + REDSIGHT RECOVERY + UI HOTFIX"
Write-Host "================================================================="
Write-Host ""

function Test-DockerEngine {

    $ErrorActionPreference = "Continue"

    $Result =
        docker info `
            --format "{{.ServerVersion}}" `
            2>$null

    $ExitCode =
        $LASTEXITCODE

    $ErrorActionPreference = "Stop"

    if (
        $ExitCode -eq 0 -and
        "$Result".Trim()
    ) {
        return $true
    }

    return $false
}

function Wait-DockerEngine {

    param([int]$Attempts = 60)

    for ($i = 1; $i -le $Attempts; $i++) {

        if (Test-DockerEngine) {

            Write-Host ""
            Write-Host "Docker Linux engine: ONLINE"
            return $true
        }

        Write-Host "Waiting for Docker engine... $i/$Attempts"

        Start-Sleep -Seconds 2
    }

    return $false
}

# =================================================================
# 1. CURRENT DOCKER STATUS
# =================================================================

Write-Host "=== Docker Desktop status ==="

$ErrorActionPreference = "Continue"

docker desktop status

$ErrorActionPreference = "Stop"

Write-Host ""

# =================================================================
# 2. START DOCKER DESKTOP
# =================================================================

if (-not (Test-DockerEngine)) {

    Write-Host "Docker engine is offline."
    Write-Host "Starting Docker Desktop..."
    Write-Host ""

    $ErrorActionPreference = "Continue"

    docker desktop start --detach

    $DesktopCliExit =
        $LASTEXITCODE

    $ErrorActionPreference = "Stop"

    # Fallback to executable if Desktop CLI start did not work.
    if (-not (Test-DockerEngine)) {

        if (Test-Path $DockerDesktopExe) {

            Write-Host "Starting Docker Desktop executable..."

            Start-Process `
                -FilePath $DockerDesktopExe `
                -ErrorAction SilentlyContinue
        }
    }

    $Ready =
        Wait-DockerEngine -Attempts 60
}
else {

    $Ready = $true
}

# =================================================================
# 3. IF WSL ENGINE IS STUCK, CLEANLY RESTART WSL + DESKTOP
# =================================================================

if (-not $Ready) {

    Write-Host ""
    Write-Host "Docker Desktop did not recover on first start."
    Write-Host "Restarting the WSL virtualization layer..."
    Write-Host ""

    $ErrorActionPreference = "Continue"

    docker desktop stop

    Start-Sleep -Seconds 2

    wsl.exe --shutdown

    Start-Sleep -Seconds 2

    docker desktop start --detach

    $ErrorActionPreference = "Stop"

    if (Test-Path $DockerDesktopExe) {

        Start-Process `
            -FilePath $DockerDesktopExe `
            -ErrorAction SilentlyContinue
    }

    $Ready =
        Wait-DockerEngine -Attempts 60
}

# =================================================================
# 4. HARD FAILURE DIAGNOSTICS
# =================================================================

if (-not $Ready) {

    Write-Host ""
    Write-Host "================================================================="
    Write-Host " DOCKER DESKTOP STILL OFFLINE"
    Write-Host "================================================================="
    Write-Host ""

    $ErrorActionPreference = "Continue"

    Write-Host "=== Docker Desktop ==="
    docker desktop status

    Write-Host ""
    Write-Host "=== WSL ==="
    wsl.exe --version

    Write-Host ""
    wsl.exe -l -v

    Write-Host ""
    Write-Host "=== Docker contexts ==="
    docker context ls

    $ErrorActionPreference = "Stop"

    throw "Docker Desktop Linux engine could not be recovered."
}

# =================================================================
# 5. ENSURE desktop-linux CONTEXT WHEN AVAILABLE
# =================================================================

Write-Host ""
Write-Host "=== Docker contexts ==="

$ErrorActionPreference = "Continue"

$Contexts =
    docker context ls `
        --format "{{.Name}}" `
        2>$null

$ErrorActionPreference = "Stop"

$Contexts |
    ForEach-Object {
        Write-Host $_
    }

if ($Contexts -contains "desktop-linux") {

    $ErrorActionPreference = "Continue"

    docker context use desktop-linux

    $ContextExit =
        $LASTEXITCODE

    $ErrorActionPreference = "Stop"

    if ($ContextExit -eq 0) {
        Write-Host "Using Docker context: desktop-linux"
    }
}

Write-Host ""

# =================================================================
# 6. VERIFY DOCKER ENGINE
# =================================================================

Write-Host "=== Docker engine ==="

$ErrorActionPreference = "Continue"

docker info `
    --format "Server={{.ServerVersion}} OS={{.OperatingSystem}} CPUs={{.NCPU}} Memory={{.MemTotal}}"

$InfoExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

if ($InfoExit -ne 0) {
    throw "Docker engine became unavailable again."
}

Write-Host ""

# =================================================================
# 7. RESTORE REDSIGHT STACK
# =================================================================

Write-Host "================================================================="
Write-Host " STARTING REDSIGHT STACK"
Write-Host "================================================================="

$ErrorActionPreference = "Continue"

docker compose up -d

$ComposeExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

if ($ComposeExit -ne 0) {

    Write-Host ""
    docker compose ps
    Write-Host ""
    docker compose logs --tail 100

    throw "RedSight Compose startup failed."
}

Write-Host ""

# =================================================================
# 8. WAIT FOR REDSIGHT API
# =================================================================

$RedSightReady =
    $false

for ($i = 1; $i -le 45; $i++) {

    $ErrorActionPreference = "Continue"

    $Code =
        curl.exe `
            -s `
            -o NUL `
            -w "%{http_code}" `
            --max-time 4 `
            http://127.0.0.1:8000/api/v1/health `
            2>$null

    $ErrorActionPreference = "Stop"

    Write-Host "RedSight health: $Code"

    if ($Code -eq "200") {

        $RedSightReady =
            $true

        break
    }

    Start-Sleep -Seconds 2
}

if (-not $RedSightReady) {

    Write-Host ""
    Write-Host "=== REDSIGHT LOG ==="

    docker logs `
        --tail 180 `
        redsight

    throw "RedSight did not become healthy."
}

Write-Host ""
Write-Host "RedSight backend: HEALTHY"
Write-Host ""

# =================================================================
# 9. VERIFY QDRANT
# =================================================================

Write-Host "=== Qdrant ==="

$ErrorActionPreference = "Continue"

$Qdrant =
    curl.exe `
        -fsS `
        http://127.0.0.1:6333/readyz `
        2>&1

$QdrantExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

Write-Host $Qdrant

if ($QdrantExit -ne 0) {
    throw "Qdrant health check failed."
}

Write-Host ""

# =================================================================
# 10. VERIFY LM STUDIO
# =================================================================

Write-Host "=== LM Studio ==="

$ErrorActionPreference = "Continue"

$LmCode =
    curl.exe `
        -s `
        -o NUL `
        -w "%{http_code}" `
        --max-time 5 `
        http://127.0.0.1:1234/v1/models `
        2>$null

$ErrorActionPreference = "Stop"

Write-Host "LM Studio HTTP: $LmCode"

if ($LmCode -ne "200") {
    throw "LM Studio is not reachable on port 1234."
}

Write-Host ""

# =================================================================
# 11. VERIFY BOTH GPUS AGAIN
# =================================================================

Write-Host "=== Dual RTX GPU passthrough ==="

$ErrorActionPreference = "Continue"

$GpuOutput =
    docker exec `
        redsight `
        nvidia-smi -L `
        2>&1

$GpuExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

$GpuOutput |
    ForEach-Object {
        Write-Host $_
    }

if ($GpuExit -ne 0) {
    throw "GPU passthrough failed after Docker recovery."
}

if (($GpuOutput | Out-String) -notmatch "GPU 1:") {
    throw "Both GPUs are not visible after Docker recovery."
}

Write-Host ""
Write-Host "Dual GPU passthrough: PASS"
Write-Host ""

# =================================================================
# 12. RUN EXISTING FUNCTIONAL UI HOTFIX
#
# Previous invocation stopped BEFORE this code could execute.
# Now Docker + RedSight are healthy, rerun it.
# =================================================================

if (-not (Test-Path $Hotfix)) {

    throw "UI hotfix script is missing: $Hotfix"
}

Write-Host "================================================================="
Write-Host " APPLYING COMMAND CENTER FUNCTIONAL FIX + RESTART"
Write-Host "================================================================="
Write-Host ""

powershell.exe `
    -NoProfile `
    -ExecutionPolicy Bypass `
    -File $Hotfix

$HotfixExit =
    $LASTEXITCODE

if ($HotfixExit -ne 0) {

    throw "UI hotfix/restart script failed."
}

Write-Host ""
Write-Host "================================================================="
Write-Host " RECOVERY COMPLETE"
Write-Host "================================================================="
Write-Host ""

docker compose ps

Write-Host ""
Write-Host "Docker Desktop : ONLINE"
Write-Host "RedSight       : ONLINE"
Write-Host "Qdrant         : ONLINE"
Write-Host "LM Studio      : ONLINE"
Write-Host "Dual RTX GPUs  : ONLINE"
Write-Host "UI hotfix      : APPLIED"
Write-Host "Command Center : RESTARTED"
Write-Host ""
