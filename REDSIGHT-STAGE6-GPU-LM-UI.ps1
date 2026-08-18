$ErrorActionPreference = "Stop"

$Root       = "C:\Users\walim\RedSight"
$Compose    = Join-Path $Root "docker-compose.yml"
$Override   = Join-Path $Root "docker-compose.override.yml"
$Server     = Join-Path $Root "app\server.py"
$UI         = Join-Path $Root "app\ui\command_center.py"

$Stamp      = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot = Join-Path $Root ".repair-backups\stage6-$Stamp"
$UiVenv     = Join-Path $Root ".venv-ui"

$Utf8 = New-Object System.Text.UTF8Encoding($false)

function Save-Utf8 {
    param(
        [string]$Path,
        [string]$Text
    )

    [System.IO.File]::WriteAllText(
        $Path,
        $Text,
        $script:Utf8
    )
}

function Backup-One {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        return
    }

    $Relative =
        $Path.Substring($script:Root.Length).TrimStart("\")

    $Safe =
        $Relative -replace '[\\/:*?"<>|]', '__'

    Copy-Item `
        -LiteralPath $Path `
        -Destination (Join-Path $script:BackupRoot $Safe) `
        -Force
}

function Get-RedsightBounds {
    param(
        [System.Collections.Generic.List[string]]$Lines
    )

    $Start = -1
    $End   = $Lines.Count - 1

    for ($i = 0; $i -lt $Lines.Count; $i++) {

        if ($Lines[$i] -match '^\s{2}redsight:\s*$') {

            $Start = $i
            break
        }
    }

    if ($Start -lt 0) {
        throw "Could not find services -> redsight in docker-compose.override.yml"
    }

    for ($i = $Start + 1; $i -lt $Lines.Count; $i++) {

        if (
            $Lines[$i] -match
            '^\s{2}[A-Za-z0-9_.-]+:\s*$'
        ) {

            $End = $i - 1
            break
        }
    }

    return @($Start, $End)
}

function Ensure-RedsightScalar {
    param(
        [string]$Key,
        [string]$Value
    )

    $Lines =
        [System.Collections.Generic.List[string]]::new()

    foreach (
        $Line in
        [System.IO.File]::ReadAllLines($script:Override)
    ) {
        [void]$Lines.Add($Line)
    }

    $Bounds =
        Get-RedsightBounds $Lines

    $Start =
        [int]$Bounds[0]

    $End =
        [int]$Bounds[1]

    $Pattern =
        '^\s{4}' +
        [regex]::Escape($Key) +
        '\s*:'

    $Found = -1

    for ($i = $Start + 1; $i -le $End; $i++) {

        if ($Lines[$i] -match $Pattern) {

            $Found = $i
            break
        }
    }

    if ($Found -ge 0) {

        $Lines[$Found] =
            "    ${Key}: $Value"
    }

    if ($Found -lt 0) {

        $Lines.Insert(
            $Start + 1,
            "    ${Key}: $Value"
        )
    }

    [System.IO.File]::WriteAllLines(
        $script:Override,
        $Lines,
        $script:Utf8
    )
}

function Ensure-RedsightEnv {
    param(
        [string]$Name,
        [string]$Value
    )

    $Lines =
        [System.Collections.Generic.List[string]]::new()

    foreach (
        $Line in
        [System.IO.File]::ReadAllLines($script:Override)
    ) {
        [void]$Lines.Add($Line)
    }

    $Bounds =
        Get-RedsightBounds $Lines

    $Start =
        [int]$Bounds[0]

    $End =
        [int]$Bounds[1]

    $EnvIndex = -1

    for ($i = $Start + 1; $i -le $End; $i++) {

        if ($Lines[$i] -match '^\s{4}environment:\s*$') {

            $EnvIndex = $i
            break
        }
    }

    if ($EnvIndex -lt 0) {

        $Lines.Insert(
            $Start + 1,
            "    environment:"
        )

        $Lines.Insert(
            $Start + 2,
            "      ${Name}: `"$Value`""
        )

        [System.IO.File]::WriteAllLines(
            $script:Override,
            $Lines,
            $script:Utf8
        )

        return
    }

    $EnvEnd = $End

    for ($i = $EnvIndex + 1; $i -le $End; $i++) {

        if (
            $Lines[$i].Trim().Length -gt 0 -and
            $Lines[$i] -match '^\s{4}\S'
        ) {

            $EnvEnd = $i - 1
            break
        }
    }

    $MapStyle = $true

    for ($i = $EnvIndex + 1; $i -le $EnvEnd; $i++) {

        if ($Lines[$i] -match '^\s{6}-\s*') {

            $MapStyle = $false
            break
        }
    }

    if (-not $MapStyle) {

        throw `
            "docker-compose.override.yml uses list-style environment entries. Stage-6 intentionally stopped rather than rewrite its structure."
    }

    $Pattern =
        '^\s{6}' +
        [regex]::Escape($Name) +
        '\s*:'

    $Found = -1

    for ($i = $EnvIndex + 1; $i -le $EnvEnd; $i++) {

        if ($Lines[$i] -match $Pattern) {

            $Found = $i
            break
        }
    }

    if ($Found -ge 0) {

        $Lines[$Found] =
            "      ${Name}: `"$Value`""
    }

    if ($Found -lt 0) {

        $Lines.Insert(
            $EnvIndex + 1,
            "      ${Name}: `"$Value`""
        )
    }

    [System.IO.File]::WriteAllLines(
        $script:Override,
        $Lines,
        $script:Utf8
    )
}

function Test-HostUrl {
    param([string]$Url)

    try {

        $Response =
            Invoke-WebRequest `
                -UseBasicParsing `
                -Uri $Url `
                -TimeoutSec 6

        return (
            $Response.StatusCode -ge 200 -and
            $Response.StatusCode -lt 300
        )
    }
    catch {

        return $false
    }
}

Set-Location $Root

New-Item `
    -ItemType Directory `
    -Path $BackupRoot `
    -Force |
    Out-Null

Write-Host ""
Write-Host "===================================================================="
Write-Host " REDSIGHT STAGE-6"
Write-Host " DUAL RTX 5090 + NVML + LM STUDIO + COMMAND CENTER"
Write-Host "===================================================================="
Write-Host ""

# ====================================================================
# PRECHECK
# ====================================================================

foreach ($Required in @(
    $Compose,
    $Override,
    $Server,
    $UI
)) {

    if (-not (Test-Path $Required)) {
        throw "Required file missing: $Required"
    }
}

Backup-One $Override
Backup-One $Server
Backup-One $UI

Write-Host "Backup:"
Write-Host $BackupRoot
Write-Host ""

# ====================================================================
# VERIFY CURRENT BACKEND
# ====================================================================

Write-Host "=== Current RedSight backend ==="

$ErrorActionPreference = "Continue"

$HealthJson =
    curl.exe `
        -fsS `
        http://127.0.0.1:8000/api/v1/health `
        2>&1

$HealthExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

if ($HealthExit -ne 0) {

    throw `
        "RedSight backend is no longer healthy. Stage-6 will not modify the stable baseline."
}

Write-Host $HealthJson
Write-Host ""

# ====================================================================
# COMPOSE VERSION
# ====================================================================

$ComposeVersionText =
    (docker compose version --short).Trim()

$ComposeVersionClean =
    ($ComposeVersionText -replace '^v','').Split('-')[0]

try {

    $ComposeVersion =
        [version]$ComposeVersionClean
}
catch {

    throw "Unable to parse Docker Compose version: $ComposeVersionText"
}

Write-Host "Docker Compose: $ComposeVersion"
Write-Host ""

if (
    $ComposeVersion -lt
    [version]"2.30.0"
) {

    throw `
        "Stage-6 uses the modern 'gpus: all' Compose property and requires Docker Compose 2.30+."
}

# ====================================================================
# 1. WINDOWS GPU ENUMERATION
# ====================================================================

Write-Host "===================================================================="
Write-Host " 1. WINDOWS GPU CHECK"
Write-Host "===================================================================="

$ErrorActionPreference = "Continue"

nvidia-smi -L

$HostSmiExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

if ($HostSmiExit -ne 0) {

    throw "Windows nvidia-smi failed."
}

Write-Host ""

# ====================================================================
# 2. DIRECT DOCKER GPU + NVML PROBE
#
# IMPORTANT:
# No Compose modification happens until this passes.
# ====================================================================

Write-Host "===================================================================="
Write-Host " 2. DIRECT DOCKER GPU + NVML PROBE"
Write-Host "===================================================================="

$GpuProbeCode =
    'import torch; ' +
    'print("CUDA_AVAILABLE="+str(torch.cuda.is_available())); ' +
    'print("CUDA_GPU_COUNT="+str(torch.cuda.device_count())); ' +
    '[print("CUDA_GPU_"+str(i)+"="+torch.cuda.get_device_name(i)) for i in range(torch.cuda.device_count())]; ' +
    'assert torch.cuda.is_available(), "CUDA unavailable"; ' +
    'assert torch.cuda.device_count() >= 2, "Less than two CUDA GPUs"; ' +
    'import pynvml; ' +
    'pynvml.nvmlInit(); ' +
    'n=pynvml.nvmlDeviceGetCount(); ' +
    'print("NVML_GPU_COUNT="+str(n)); ' +
    '[print("NVML_GPU_"+str(i)+"="+pynvml.nvmlDeviceGetName(pynvml.nvmlDeviceGetHandleByIndex(i)).decode() if isinstance(pynvml.nvmlDeviceGetName(pynvml.nvmlDeviceGetHandleByIndex(i)),bytes) else pynvml.nvmlDeviceGetName(pynvml.nvmlDeviceGetHandleByIndex(i))) for i in range(n)]; ' +
    'assert n >= 2, "NVML sees less than two GPUs"; ' +
    'pynvml.nvmlShutdown(); ' +
    'print("DIRECT_GPU_NVML=PASS")'

$ErrorActionPreference = "Continue"

$GpuProbe =
    docker run `
        --rm `
        --gpus all `
        redsight-redsight `
        python -c $GpuProbeCode `
        2>&1

$GpuProbeExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

$GpuProbe |
    ForEach-Object {
        Write-Host $_
    }

Write-Host ""

$GpuProbe |
    Out-String |
    Set-Content (
        Join-Path $BackupRoot "gpu-direct-probe.txt"
    )

if ($GpuProbeExit -ne 0) {

    Write-Host "Direct Docker GPU passthrough failed."
    Write-Host ""
    Write-Host "=== WSL diagnostics ==="

    $ErrorActionPreference = "Continue"

    wsl.exe --version
    docker info

    $ErrorActionPreference = "Stop"

    throw `
        "GPU passthrough must work with docker run --gpus all before RedSight Compose is modified."
}

# ====================================================================
# 3. PERSIST ALL GPUS IN COMPOSE
# ====================================================================

Write-Host "===================================================================="
Write-Host " 3. ENABLING BOTH GPUS FOR REDSIGHT"
Write-Host "===================================================================="

Ensure-RedsightScalar `
    -Key "gpus" `
    -Value "all"

Write-Host "docker-compose.override.yml:"
Write-Host "  redsight -> gpus: all"
Write-Host ""

# ====================================================================
# 4. LM STUDIO HOST API
# ====================================================================

Write-Host "===================================================================="
Write-Host " 4. LM STUDIO API CHECK"
Write-Host "===================================================================="

$LmHostOK =
    Test-HostUrl `
        "http://127.0.0.1:1234/v1/models"

Write-Host "Windows /v1/models: $LmHostOK"

$LmContainerCode =
    'import httpx,sys; ' +
    'u="http://host.docker.internal:1234/v1/models"; ' +
    'r=httpx.get(u,timeout=6); ' +
    'print("HTTP_STATUS="+str(r.status_code)); ' +
    'print(r.text[:2500]); ' +
    'sys.exit(0 if r.status_code==200 else 1)'

$ErrorActionPreference = "Continue"

$LmContainerProbe =
    docker run `
        --rm `
        --add-host host.docker.internal:host-gateway `
        redsight-redsight `
        python -c $LmContainerCode `
        2>&1

$LmContainerExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "Docker -> LM Studio:"
$LmContainerProbe |
    ForEach-Object {
        Write-Host $_
    }

$LmContainerOK =
    ($LmContainerExit -eq 0)

Write-Host ""
Write-Host "Docker /v1/models: $LmContainerOK"
Write-Host ""

# ====================================================================
# 5. START/REBIND LM STUDIO IF NECESSARY
# ====================================================================

if (
    (-not $LmHostOK) -or
    (-not $LmContainerOK)
) {

    $Lms =
        Get-Command lms `
            -ErrorAction SilentlyContinue

    if (-not $Lms) {

        throw `
            "LM Studio API is not reachable and the 'lms' CLI was not found. Start LM Studio Developer Server on port 1234 with network access enabled, then rerun Stage-6."
    }

    Write-Host "LM Studio needs its server restarted for Docker access."
    Write-Host ""
    Write-Host "NOTE: binding to 0.0.0.0 makes LM Studio reachable beyond loopback."
    Write-Host "CORS is NOT being enabled."
    Write-Host ""

    $ErrorActionPreference = "Continue"

    & lms server stop

    Start-Sleep -Seconds 2

    & lms server start `
        --port 1234 `
        --bind 0.0.0.0

    $LmsStartExit =
        $LASTEXITCODE

    $ErrorActionPreference = "Stop"

    if ($LmsStartExit -ne 0) {

        throw "LM Studio server could not be started."
    }

    Start-Sleep -Seconds 3

    $LmHostOK =
        Test-HostUrl `
            "http://127.0.0.1:1234/v1/models"

    $ErrorActionPreference = "Continue"

    $LmContainerProbe =
        docker run `
            --rm `
            --add-host host.docker.internal:host-gateway `
            redsight-redsight `
            python -c $LmContainerCode `
            2>&1

    $LmContainerExit =
        $LASTEXITCODE

    $ErrorActionPreference = "Stop"

    $LmContainerOK =
        ($LmContainerExit -eq 0)

    Write-Host "After LM Studio restart:"
    Write-Host "  Windows = $LmHostOK"
    Write-Host "  Docker  = $LmContainerOK"
    Write-Host ""

    if (
        (-not $LmHostOK) -or
        (-not $LmContainerOK)
    ) {

        throw "LM Studio still cannot be reached from Docker."
    }
}

# ====================================================================
# 6. COMMON LM STUDIO ENVIRONMENT
# ====================================================================

Ensure-RedsightEnv `
    -Name "LM_STUDIO_URL" `
    -Value "http://host.docker.internal:1234"

Ensure-RedsightEnv `
    -Name "LM_STUDIO_BASE_URL" `
    -Value "http://host.docker.internal:1234"

Write-Host "Common LM Studio Docker variables set."
Write-Host ""

# ====================================================================
# 7. DISCOVER REDSIGHT'S ACTUAL LM CONFIGURATION
# ====================================================================

Write-Host "===================================================================="
Write-Host " 5. DISCOVERING REDSIGHT LM STUDIO CONFIG VARIABLE"
Write-Host "===================================================================="

$SettingsProbe =
    Join-Path $BackupRoot "probe_settings.py"

$SettingsProbeLines = @(
    'import sys'
    'sys.path.insert(0, "/source")'
    'import app.config.settings as mod'
    ''
    'obj = None'
    ''
    'getter = getattr(mod, "get_settings", None)'
    'if callable(getter):'
    '    try:'
    '        obj = getter()'
    '    except Exception as exc:'
    '        print("GET_SETTINGS_ERROR=" + repr(exc))'
    ''
    'if obj is None:'
    '    candidate = getattr(mod, "settings", None)'
    '    if candidate is not None:'
    '        obj = candidate'
    ''
    'if obj is None:'
    '    cls = getattr(mod, "Settings", None)'
    '    if cls is not None:'
    '        try:'
    '            obj = cls()'
    '        except Exception as exc:'
    '            print("SETTINGS_CLASS_ERROR=" + repr(exc))'
    ''
    'if obj is None:'
    '    print("NO_SETTINGS_OBJECT")'
    '    raise SystemExit(0)'
    ''
    'config = getattr(obj, "model_config", {}) or {}'
    'print("ENV_PREFIX=" + str(config.get("env_prefix", "")))'
    'print("ENV_NESTED_DELIMITER=" + str(config.get("env_nested_delimiter", "__") or "__"))'
    ''
    'if hasattr(obj, "model_dump"):'
    '    data = obj.model_dump()'
    'elif hasattr(obj, "dict"):'
    '    data = obj.dict()'
    'else:'
    '    data = {}'
    ''
    'def walk(value, path=""):'
    '    if isinstance(value, dict):'
    '        for key, child in value.items():'
    '            p = f"{path}.{key}" if path else str(key)'
    '            walk(child, p)'
    '        return'
    '    if isinstance(value, (list, tuple)):'
    '        return'
    '    text = str(value)'
    '    keytext = path.lower()'
    '    if ("lm" in keytext or "studio" in keytext or ":1234" in text):'
    '        print("CFG|" + path + "|" + text)'
    ''
    'walk(data)'
)

[System.IO.File]::WriteAllLines(
    $SettingsProbe,
    $SettingsProbeLines,
    $Utf8
)

$SettingsProbeRelative =
    $SettingsProbe.Substring(
        $Root.Length
    ).Replace("\","/")

$ErrorActionPreference = "Continue"

$SettingsOutput =
    docker compose `
        -f $Compose `
        -f $Override `
        run `
        --rm `
        --no-deps `
        -v "${Root}:/source:ro" `
        -e PYTHONPATH=/source `
        redsight `
        python "/source$SettingsProbeRelative" `
        2>&1

$SettingsProbeExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

$SettingsOutput |
    ForEach-Object {
        Write-Host $_
    }

$SettingsOutput |
    Out-String |
    Set-Content (
        Join-Path $BackupRoot "settings-lmstudio.txt"
    )

Write-Host ""

$Prefix = ""

$Delimiter = "__"

foreach ($Line in $SettingsOutput) {

    $Text =
        "$Line"

    if ($Text -match '^ENV_PREFIX=(.*)$') {
        $Prefix = $Matches[1]
    }

    if ($Text -match '^ENV_NESTED_DELIMITER=(.*)$') {

        if ($Matches[1]) {
            $Delimiter = $Matches[1]
        }
    }
}

$DerivedVars = @()

foreach ($Line in $SettingsOutput) {

    $Text =
        "$Line"

    if (
        $Text -notmatch
        '^CFG\|([^|]+)\|(.*)$'
    ) {
        continue
    }

    $ConfigPath =
        $Matches[1]

    $CurrentValue =
        $Matches[2]

    if (
        $CurrentValue -notmatch
        'https?://(localhost|127\.0\.0\.1):1234'
    ) {
        continue
    }

    $NewValue =
        $CurrentValue.Replace(
            "localhost",
            "host.docker.internal"
        ).Replace(
            "127.0.0.1",
            "host.docker.internal"
        )

    $Parts =
        $ConfigPath.Split(".") |
        ForEach-Object {
            $_.ToUpperInvariant()
        }

    $EnvName =
        (
            $Prefix +
            ($Parts -join $Delimiter)
        ).ToUpperInvariant()

    if (
        $EnvName -and
        $EnvName -notin $DerivedVars
    ) {

        Write-Host "Derived RedSight setting:"
        Write-Host "  config = $ConfigPath"
        Write-Host "  env    = $EnvName"
        Write-Host "  value  = $NewValue"
        Write-Host ""

        Ensure-RedsightEnv `
            -Name $EnvName `
            -Value $NewValue

        $DerivedVars += $EnvName
    }
}

# ====================================================================
# 8. SHOW LM STUDIO SOURCE REFERENCES
# ====================================================================

$LmSourceMatches =
    Get-ChildItem `
        (Join-Path $Root "app") `
        -Recurse `
        -File `
        -Filter "*.py" |
    Select-String `
        -Pattern `
        "LM Studio health check failed",
        "LM_STUDIO",
        "lm_studio",
        "localhost:1234",
        "127.0.0.1:1234" `
        -ErrorAction SilentlyContinue

$LmSourceMatches |
    Select-Object -First 100 |
    Out-String |
    Set-Content (
        Join-Path $BackupRoot "lmstudio-source-references.txt"
    )

Write-Host "LM Studio source references saved."
Write-Host ""

# ====================================================================
# 9. VALIDATE COMPOSE
# ====================================================================

Write-Host "===================================================================="
Write-Host " 6. COMPOSE VALIDATION"
Write-Host "===================================================================="

$ErrorActionPreference = "Continue"

docker compose `
    -f $Compose `
    -f $Override `
    config `
    1> (Join-Path $BackupRoot "compose-resolved.yml")

$ComposeExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

if ($ComposeExit -ne 0) {

    throw "Compose validation failed."
}

Write-Host "Compose: PASS"
Write-Host ""

# ====================================================================
# 10. RECREATE REDSIGHT WITH GPU + LM SETTINGS
# ====================================================================

Write-Host "===================================================================="
Write-Host " 7. RECREATING REDSIGHT WITH BOTH GPUS"
Write-Host "===================================================================="

$ErrorActionPreference = "Continue"

docker compose `
    -f $Compose `
    -f $Override `
    up -d `
    --force-recreate `
    redsight

$StartExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

if ($StartExit -ne 0) {
    throw "RedSight recreate failed."
}

Write-Host ""

# ====================================================================
# 11. WAIT FOR APPLICATION HEALTH
# ====================================================================

for ($i = 1; $i -le 30; $i++) {

    $ErrorActionPreference = "Continue"

    $State =
        docker inspect redsight `
        --format "{{.State.Status}}" `
        2>$null

    $Health =
        docker inspect redsight `
        --format "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}" `
        2>$null

    $Restarts =
        docker inspect redsight `
        --format "{{.RestartCount}}" `
        2>$null

    $ErrorActionPreference = "Stop"

    Write-Host (
        "state=$State health=$Health restarts=$Restarts"
    )

    if (
        $State -eq "running" -and
        $Health -eq "healthy"
    ) {
        break
    }

    Start-Sleep -Seconds 2
}

Write-Host ""

# ====================================================================
# 12. GPU TEST INSIDE REAL REDSIGHT SERVICE
# ====================================================================

Write-Host "===================================================================="
Write-Host " 8. REDSIGHT SERVICE GPU + NVML CHECK"
Write-Host "===================================================================="

$ErrorActionPreference = "Continue"

$ServiceGpu =
    docker exec `
        redsight `
        python -c $GpuProbeCode `
        2>&1

$ServiceGpuExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

$ServiceGpu |
    ForEach-Object {
        Write-Host $_
    }

$ServiceGpu |
    Out-String |
    Set-Content (
        Join-Path $BackupRoot "gpu-redsight-service.txt"
    )

Write-Host ""

if ($ServiceGpuExit -ne 0) {

    throw `
        "Direct --gpus all worked, but the RedSight Compose service still cannot see both GPUs."
}

# ====================================================================
# 13. LM STUDIO FROM REAL REDSIGHT SERVICE
# ====================================================================

Write-Host "===================================================================="
Write-Host " 9. REDSIGHT CONTAINER -> LM STUDIO /v1/models"
Write-Host "===================================================================="

$ErrorActionPreference = "Continue"

$LmInside =
    docker exec `
        redsight `
        python -c $LmContainerCode `
        2>&1

$LmInsideExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

$LmInside |
    ForEach-Object {
        Write-Host $_
    }

Write-Host ""

if ($LmInsideExit -ne 0) {

    throw "The live RedSight service cannot reach LM Studio."
}

# ====================================================================
# 14. DIRECT LM STUDIO INFERENCE
# ====================================================================

Write-Host "===================================================================="
Write-Host " 10. DIRECT LM STUDIO INFERENCE TEST"
Write-Host "===================================================================="

$LmInferenceCode =
    'import httpx,json; ' +
    'base="http://host.docker.internal:1234"; ' +
    'r=httpx.get(base+"/api/v1/models",timeout=10); ' +
    'r.raise_for_status(); ' +
    'items=r.json().get("models",[]); ' +
    'llms=[m for m in items if m.get("type")=="llm"]; ' +
    'assert llms, "No LLM is available in LM Studio"; ' +
    'm=llms[0]; ' +
    'model=m.get("key") or m.get("id") or m.get("model"); ' +
    'print("TEST_MODEL="+str(model)); ' +
    'payload={"model":model,"messages":[{"role":"user","content":"Reply with exactly LM_STUDIO_E2E_OK"}],"temperature":0}; ' +
    'x=httpx.post(base+"/v1/chat/completions",json=payload,timeout=120); ' +
    'print("CHAT_STATUS="+str(x.status_code)); ' +
    'print(x.text[:4000]); ' +
    'x.raise_for_status(); ' +
    'print("LM_STUDIO_INFERENCE=PASS")'

$ErrorActionPreference = "Continue"

$LmInference =
    docker exec `
        redsight `
        python -c $LmInferenceCode `
        2>&1

$LmInferenceExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

$LmInference |
    ForEach-Object {
        Write-Host $_
    }

$LmInference |
    Out-String |
    Set-Content (
        Join-Path $BackupRoot "lmstudio-inference.txt"
    )

Write-Host ""

if ($LmInferenceExit -ne 0) {

    Write-Warning `
        "LM Studio network access works but direct inference failed. Check whether an LLM is downloaded/available and whether LM Studio authentication is enabled."
}

# ====================================================================
# 15. CHECK REDSIGHT STARTUP LOG FOR OLD WARNINGS
# ====================================================================

$RuntimeLog =
    Join-Path $BackupRoot "redsight-after-gpu-lm.log"

$LogCommand =
    'docker logs --tail 500 redsight > "' +
    $RuntimeLog +
    '" 2>&1'

cmd.exe /d /c $LogCommand

$RuntimeText =
    [System.IO.File]::ReadAllText(
        $RuntimeLog
    )

$NvmlFailed =
    $RuntimeText.Contains(
        "NVML initialization failed"
    )

$LmHealthFailed =
    $RuntimeText.Contains(
        "LM Studio health check failed"
    )

$StartupOK =
    $RuntimeText.Contains(
        "Application startup complete"
    )

Write-Host "=== Runtime warning state ==="
Write-Host "Application startup complete : $StartupOK"
Write-Host "NVML initialization failed   : $NvmlFailed"
Write-Host "LM Studio health check failed: $LmHealthFailed"
Write-Host ""

# ====================================================================
# 16. REDSIGHT -> LM STUDIO END-TO-END CHAT
# ====================================================================

Write-Host "===================================================================="
Write-Host " 11. REDSIGHT -> LM STUDIO END-TO-END CHAT"
Write-Host "===================================================================="

$ChatBody =
    @{
        message = "Reply with exactly REDSIGHT_E2E_OK"
    } |
    ConvertTo-Json -Compress

$RedSightChatOK =
    $false

try {

    $ChatResponse =
        Invoke-RestMethod `
            -Uri "http://127.0.0.1:8000/api/v1/chat" `
            -Method Post `
            -ContentType "application/json" `
            -Body $ChatBody `
            -TimeoutSec 120

    Write-Host (
        $ChatResponse |
        ConvertTo-Json `
            -Depth 10
    )

    $RedSightChatOK =
        $true
}
catch {

    Write-Warning "RedSight chat request failed:"
    Write-Warning $_.Exception.Message
}

Write-Host ""
Write-Host "RedSight chat E2E: $RedSightChatOK"
Write-Host ""

# ====================================================================
# 17. REPAIR COMMAND CENTER ASYNCIO INTEGRATION
# ====================================================================

Write-Host "===================================================================="
Write-Host " 12. COMMAND CENTER QT + ASYNCIO REPAIR"
Write-Host "===================================================================="

$UiText =
    [System.IO.File]::ReadAllText($UI)

# Replace raw create_task with the QtAsyncio-friendly scheduling form.
$UiText =
    $UiText.Replace(
        'asyncio.create_task(self._send_to_api(message))',
        'asyncio.ensure_future(self._send_to_api(message))'
    )

# Add QtAsyncio import if absent.
if (
    $UiText -notmatch
    'PySide6\.QtAsyncio'
) {

    $ImportPattern =
        '(?m)^(from\s+PySide6\.)'

    if (
        $UiText -notmatch
        $ImportPattern
    ) {

        throw `
            "Could not find a PySide6 import in command_center.py."
    }

    $UiText =
        [regex]::Replace(
            $UiText,
            $ImportPattern,
            "import PySide6.QtAsyncio as QtAsyncio`r`n`$1",
            1
        )
}

# Replace the traditional Qt event loop with QtAsyncio.
$ExitCount =
    (
        [regex]::Matches(
            $UiText,
            '(?m)^\s*sys\.exit\(app\.exec\(\)\)\s*$'
        )
    ).Count

$PlainCount =
    (
        [regex]::Matches(
            $UiText,
            '(?m)^\s*app\.exec\(\)\s*$'
        )
    ).Count

$ReturnCount =
    (
        [regex]::Matches(
            $UiText,
            '(?m)^\s*return\s+app\.exec\(\)\s*$'
        )
    ).Count

if ($ExitCount -gt 0) {

    $UiText =
        [regex]::Replace(
            $UiText,
            '(?m)^(\s*)sys\.exit\(app\.exec\(\)\)\s*$',
            '$1QtAsyncio.run(handle_sigint=True)'
        )
}

if ($ReturnCount -gt 0) {

    $UiText =
        [regex]::Replace(
            $UiText,
            '(?m)^(\s*)return\s+app\.exec\(\)\s*$',
            '$1QtAsyncio.run(handle_sigint=True)' +
            "`r`n" +
            '$1return 0'
        )
}

if (
    $ExitCount -eq 0 -and
    $ReturnCount -eq 0 -and
    $PlainCount -gt 0
) {

    $UiText =
        [regex]::Replace(
            $UiText,
            '(?m)^(\s*)app\.exec\(\)\s*$',
            '$1QtAsyncio.run(handle_sigint=True)'
        )
}

Save-Utf8 `
    -Path $UI `
    -Text $UiText

Write-Host "Command Center event-loop patch applied."
Write-Host ""

# ====================================================================
# 18. AST VALIDATE UI
# ====================================================================

$UiRelative =
    $UI.Substring(
        $Root.Length
    ).Replace("\","/")

$ErrorActionPreference = "Continue"

$UiAst =
    docker run `
        --rm `
        -v "${Root}:/source:ro" `
        redsight-redsight `
        python -c "import ast,pathlib; p=pathlib.Path('/source$UiRelative'); ast.parse(p.read_text(encoding='utf-8-sig'),filename=str(p)); print('COMMAND_CENTER_AST=OK')" `
        2>&1

$UiAstExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

$UiAst |
    ForEach-Object {
        Write-Host $_
    }

if ($UiAstExit -ne 0) {

    throw "Command Center AST validation failed."
}

Write-Host ""

# ====================================================================
# 19. CREATE ISOLATED WINDOWS UI PYTHON ENVIRONMENT
# ====================================================================

Write-Host "===================================================================="
Write-Host " 13. WINDOWS COMMAND CENTER ENVIRONMENT"
Write-Host "===================================================================="

$BaseExe  = $null
$BaseArgs = @()

$PyLauncher =
    Get-Command py `
        -ErrorAction SilentlyContinue

if ($PyLauncher) {

    $ErrorActionPreference = "Continue"

    & py -3.12 -c "import sys; print(sys.executable)" `
        1> (Join-Path $BackupRoot "host-python.txt") `
        2>$null

    $Py312Exit =
        $LASTEXITCODE

    $ErrorActionPreference = "Stop"

    if ($Py312Exit -eq 0) {

        $BaseExe =
            "py"

        $BaseArgs =
            @("-3.12")
    }
}

if (-not $BaseExe) {

    $PythonCmd =
        Get-Command python `
            -ErrorAction SilentlyContinue

    if ($PythonCmd) {

        $BaseExe =
            $PythonCmd.Source

        $BaseArgs =
            @()
    }
}

if (-not $BaseExe) {

    throw `
        "No Windows Python installation was found for the native Command Center."
}

if (-not (Test-Path $UiVenv)) {

    Write-Host "Creating:"
    Write-Host $UiVenv

    & $BaseExe `
        @BaseArgs `
        -m venv `
        $UiVenv

    if ($LASTEXITCODE -ne 0) {
        throw "Could not create .venv-ui"
    }
}

$UiPython =
    Join-Path $UiVenv "Scripts\python.exe"

if (-not (Test-Path $UiPython)) {
    throw "UI venv Python not found."
}

# Match PySide/httpx versions to the Docker project environment.

$ContainerVersions =
    @(
        docker run `
            --rm `
            redsight-redsight `
            python -c "import PySide6,httpx; print(PySide6.__version__); print(httpx.__version__)"
    )

$PySideVersion =
    "$($ContainerVersions[0])".Trim()

$HttpxVersion =
    "$($ContainerVersions[1])".Trim()

Write-Host "PySide6 version: $PySideVersion"
Write-Host "httpx version  : $HttpxVersion"
Write-Host ""

& $UiPython `
    -m pip `
    install `
    --upgrade `
    pip

if ($LASTEXITCODE -ne 0) {
    throw "UI pip upgrade failed."
}

& $UiPython `
    -m pip `
    install `
    "PySide6==$PySideVersion" `
    "httpx==$HttpxVersion" `
    psutil `
    structlog `
    pydantic `
    pydantic-settings `
    PyYAML `
    markdown `
    pygments

if ($LASTEXITCODE -ne 0) {

    throw "UI dependency installation failed."
}

# ====================================================================
# 20. VERIFY QtAsyncio + UI IMPORT
# ====================================================================

Write-Host ""
Write-Host "=== Native PySide verification ==="

& $UiPython `
    -c "import PySide6; import PySide6.QtAsyncio as QtAsyncio; print('PYSIDE='+PySide6.__version__); print('QTASYNCIO=OK')"

if ($LASTEXITCODE -ne 0) {
    throw "PySide6.QtAsyncio verification failed."
}

$UiImportCode =
    "import sys;" +
    "sys.path.insert(0,r'$Root');" +
    "import app.ui.command_center;" +
    "print('COMMAND_CENTER_IMPORT=OK')"

$ErrorActionPreference = "Continue"

$UiImportOutput =
    & $UiPython `
        -c $UiImportCode `
        2>&1

$UiImportExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

$UiImportOutput |
    ForEach-Object {
        Write-Host $_
    }

if ($UiImportExit -ne 0) {

    $UiImportOutput |
        Out-String |
        Set-Content (
            Join-Path $BackupRoot "ui-import-error.txt"
        )

    throw `
        "Command Center still has a Windows-side import dependency problem. See ui-import-error.txt in the Stage-6 diagnostics directory."
}

Write-Host ""

# ====================================================================
# 21. CREATE REUSABLE UI LAUNCHER
# ====================================================================

$Launcher =
    Join-Path $Root "LAUNCH-REDSIGHT-COMMAND-CENTER.ps1"

$LauncherLines = @(
    '$ErrorActionPreference = "Stop"'
    '$Root = "C:\Users\walim\RedSight"'
    '$Python = Join-Path $Root ".venv-ui\Scripts\python.exe"'
    '$env:REDSIGHT_API_URL = "http://127.0.0.1:8000"'
    '$env:REDSIGHT_API_BASE_URL = "http://127.0.0.1:8000"'
    '$env:API_BASE_URL = "http://127.0.0.1:8000"'
    'Set-Location $Root'
    '& $Python -m app.ui.command_center'
)

[System.IO.File]::WriteAllLines(
    $Launcher,
    $LauncherLines,
    $Utf8
)

Write-Host "Reusable launcher:"
Write-Host $Launcher
Write-Host ""

# ====================================================================
# 22. LAUNCH COMMAND CENTER
# ====================================================================

Write-Host "===================================================================="
Write-Host " 14. LAUNCHING REDSIGHT COMMAND CENTER"
Write-Host "===================================================================="

$UiStdout =
    Join-Path $BackupRoot "command-center.stdout.log"

$UiStderr =
    Join-Path $BackupRoot "command-center.stderr.log"

$env:REDSIGHT_API_URL =
    "http://127.0.0.1:8000"

$env:REDSIGHT_API_BASE_URL =
    "http://127.0.0.1:8000"

$env:API_BASE_URL =
    "http://127.0.0.1:8000"

$UiProcess =
    Start-Process `
        -FilePath $UiPython `
        -ArgumentList @(
            "-m",
            "app.ui.command_center"
        ) `
        -WorkingDirectory $Root `
        -RedirectStandardOutput $UiStdout `
        -RedirectStandardError $UiStderr `
        -PassThru

Start-Sleep -Seconds 4

$UiProcess.Refresh()

if ($UiProcess.HasExited) {

    Write-Host ""
    Write-Host "Command Center exited during launch."
    Write-Host ""

    if (Test-Path $UiStderr) {

        Get-Content `
            $UiStderr `
            -Tail 100
    }

    throw `
        "Command Center launch failed. Full stderr was preserved."
}

Write-Host "COMMAND_CENTER_LAUNCHED=YES"
Write-Host "PID=$($UiProcess.Id)"
Write-Host ""

# ====================================================================
# 23. FINAL STATUS
# ====================================================================

Write-Host "===================================================================="
Write-Host " FINAL REDSIGHT STATUS"
Write-Host "===================================================================="

docker compose `
    -f $Compose `
    -f $Override `
    ps

Write-Host ""

docker inspect redsight `
    --format "redsight status={{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} restarts={{.RestartCount}}"

Write-Host ""

docker inspect redsight-qdrant `
    --format "qdrant status={{.State.Status}} health={{.State.Health.Status}}"

Write-Host ""

Write-Host "=== GPU inside RedSight ==="

docker exec redsight `
    python -c "import torch; print('CUDA='+str(torch.cuda.is_available())); print('GPU_COUNT='+str(torch.cuda.device_count())); [print(str(i)+'='+torch.cuda.get_device_name(i)) for i in range(torch.cuda.device_count())]"

Write-Host ""

Write-Host "=== API health ==="

curl.exe `
    -fsS `
    http://127.0.0.1:8000/api/v1/health

Write-Host ""
Write-Host ""

Write-Host "===================================================================="
Write-Host " STAGE-6 COMPLETE"
Write-Host "===================================================================="
Write-Host ""

Write-Host "Expected final state:"
Write-Host "  RedSight backend       : healthy"
Write-Host "  Qdrant                 : healthy"
Write-Host "  Docker CUDA GPU count  : 2"
Write-Host "  Docker NVML GPU count  : 2"
Write-Host "  LM Studio /v1/models   : reachable"
Write-Host "  LM Studio inference    : tested"
Write-Host "  RedSight chat E2E      : $RedSightChatOK"
Write-Host "  Command Center         : running PID $($UiProcess.Id)"
Write-Host ""

Write-Host "Diagnostics:"
Write-Host $BackupRoot
Write-Host ""

Write-Host "Command Center stderr:"
Write-Host $UiStderr
Write-Host ""

Write-Host "Reusable UI launcher:"
Write-Host $Launcher
Write-Host ""

Write-Host "Qdrant data and volumes were NOT deleted or reset."
Write-Host ""
