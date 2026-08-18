$ErrorActionPreference = "Stop"

# =====================================================================
# PATHS
# =====================================================================

$Root       = "C:\Users\walim\RedSight"
$Compose    = Join-Path $Root "docker-compose.yml"
$Override   = Join-Path $Root "docker-compose.override.yml"
$UI         = Join-Path $Root "app\ui\command_center.py"

$Stamp      = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot = Join-Path $Root ".repair-backups\stage6c-$Stamp"
$UiVenv     = Join-Path $Root ".venv-ui"

$Utf8 = New-Object System.Text.UTF8Encoding($false)

New-Item `
    -ItemType Directory `
    -Path $BackupRoot `
    -Force |
    Out-Null

Set-Location $Root

# =====================================================================
# HELPERS
# =====================================================================

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
        $Path.Substring(
            $script:Root.Length
        ).TrimStart("\")

    $Safe =
        $Relative -replace '[\\/:*?"<>|]', '__'

    Copy-Item `
        -LiteralPath $Path `
        -Destination (Join-Path $script:BackupRoot $Safe) `
        -Force
}

function Get-RedsightBlock {

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
        throw "Could not find the redsight service in docker-compose.override.yml"
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

    return @(
        $Start,
        $End
    )
}

function Set-RedsightScalar {

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
        Get-RedsightBlock $Lines

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

function Set-RedsightEnvironment {

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
        Get-RedsightBlock $Lines

    $Start =
        [int]$Bounds[0]

    $End =
        [int]$Bounds[1]

    $EnvironmentIndex = -1

    for ($i = $Start + 1; $i -le $End; $i++) {

        if (
            $Lines[$i] -match
            '^\s{4}environment:\s*$'
        ) {

            $EnvironmentIndex = $i
            break
        }
    }

    # -------------------------------------------------------------
    # Add environment mapping if none exists.
    # -------------------------------------------------------------

    if ($EnvironmentIndex -lt 0) {

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

    # -------------------------------------------------------------
    # Find end of environment mapping.
    # -------------------------------------------------------------

    $EnvironmentEnd =
        $End

    for (
        $i = $EnvironmentIndex + 1;
        $i -le $End;
        $i++
    ) {

        if ($Lines[$i].Trim().Length -eq 0) {
            continue
        }

        if (
            $Lines[$i] -match
            '^\s{4}\S'
        ) {

            $EnvironmentEnd =
                $i - 1

            break
        }
    }

    # -------------------------------------------------------------
    # Refuse list-style environment syntax.
    # -------------------------------------------------------------

    for (
        $i = $EnvironmentIndex + 1;
        $i -le $EnvironmentEnd;
        $i++
    ) {

        if (
            $Lines[$i] -match
            '^\s{6}-\s*'
        ) {

            throw `
                "The override uses list-style environment variables. Stage-6C stopped rather than rewrite the structure."
        }
    }

    $Pattern =
        '^\s{6}' +
        [regex]::Escape($Name) +
        '\s*:'

    $Found = -1

    for (
        $i = $EnvironmentIndex + 1;
        $i -le $EnvironmentEnd;
        $i++
    ) {

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
            $EnvironmentIndex + 1,
            "      ${Name}: `"$Value`""
        )
    }

    [System.IO.File]::WriteAllLines(
        $script:Override,
        $Lines,
        $script:Utf8
    )
}

function Host-HttpCode {

    param([string]$Url)

    $ErrorActionPreference = "Continue"

    $Code =
        curl.exe `
            -s `
            -o NUL `
            -w "%{http_code}" `
            --max-time 8 `
            $Url `
            2>$null

    $Exit =
        $LASTEXITCODE

    $ErrorActionPreference = "Stop"

    if ($Exit -ne 0) {
        return "000"
    }

    return "$Code"
}

# =====================================================================
# HEADER
# =====================================================================

Write-Host ""
Write-Host "===================================================================="
Write-Host " REDSIGHT STAGE-6C"
Write-Host " DUAL RTX 5090 + NVML + LM STUDIO + COMMAND CENTER"
Write-Host "===================================================================="
Write-Host ""

# =====================================================================
# BACKUPS
# =====================================================================

foreach ($Required in @(
    $Compose,
    $Override,
    $UI
)) {

    if (-not (Test-Path $Required)) {
        throw "Required file missing: $Required"
    }
}

Backup-One $Override
Backup-One $UI

Write-Host "Backup:"
Write-Host $BackupRoot
Write-Host ""

# =====================================================================
# VERIFY HEALTHY BASELINE
# =====================================================================

Write-Host "=== Existing RedSight backend ==="

$BackendCode =
    Host-HttpCode `
        "http://127.0.0.1:8000/api/v1/health"

Write-Host "HTTP: $BackendCode"

if ($BackendCode -ne "200") {

    throw `
        "RedSight baseline is no longer healthy. Stage-6C will not alter the working backend."
}

Write-Host ""

# =====================================================================
# WINDOWS GPUS
# =====================================================================

Write-Host "===================================================================="
Write-Host " 1. WINDOWS GPU CHECK"
Write-Host "===================================================================="

$ErrorActionPreference = "Continue"

nvidia-smi -L

$WindowsGpuExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

if ($WindowsGpuExit -ne 0) {
    throw "Windows nvidia-smi failed."
}

Write-Host ""

# =====================================================================
# CREATE GPU PROBE AS A REAL FILE
#
# NO python -c
# NO PowerShell native quote corruption
# =====================================================================

$GpuProbe =
    Join-Path $BackupRoot "gpu_probe.py"

$GpuProbeLines = @(
    'import ctypes.util'
    'import sys'
    'import torch'
    ''
    'print("CUDA_AVAILABLE=" + str(torch.cuda.is_available()))'
    'print("CUDA_GPU_COUNT=" + str(torch.cuda.device_count()))'
    ''
    'for i in range(torch.cuda.device_count()):'
    '    print("CUDA_GPU_" + str(i) + "=" + torch.cuda.get_device_name(i))'
    ''
    'if not torch.cuda.is_available():'
    '    raise RuntimeError("CUDA is unavailable inside container")'
    ''
    'if torch.cuda.device_count() < 2:'
    '    raise RuntimeError("Docker sees fewer than two CUDA GPUs")'
    ''
    'print("NVML_LIBRARY=" + str(ctypes.util.find_library("nvidia-ml")))'
    ''
    'import pynvml'
    'pynvml.nvmlInit()'
    ''
    'count = pynvml.nvmlDeviceGetCount()'
    'print("NVML_GPU_COUNT=" + str(count))'
    ''
    'for i in range(count):'
    '    handle = pynvml.nvmlDeviceGetHandleByIndex(i)'
    '    name = pynvml.nvmlDeviceGetName(handle)'
    '    if isinstance(name, bytes):'
    '        name = name.decode("utf-8", errors="replace")'
    '    print("NVML_GPU_" + str(i) + "=" + str(name))'
    ''
    'pynvml.nvmlShutdown()'
    ''
    'if count < 2:'
    '    raise RuntimeError("NVML sees fewer than two GPUs")'
    ''
    'print("GPU_NVML_PROBE=PASS")'
)

[System.IO.File]::WriteAllLines(
    $GpuProbe,
    $GpuProbeLines,
    $Utf8
)

Write-Host "===================================================================="
Write-Host " 2. DIRECT DOCKER GPU + NVML CHECK"
Write-Host "===================================================================="

Write-Host ""
Write-Host "--- nvidia-smi through Docker ---"

$ErrorActionPreference = "Continue"

docker run `
    --rm `
    --gpus all `
    -e NVIDIA_DRIVER_CAPABILITIES=compute,utility `
    redsight-redsight `
    nvidia-smi -L

$DockerSmiExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "docker nvidia-smi exit: $DockerSmiExit"
Write-Host ""

Write-Host "--- PyTorch + NVML probe ---"

$ErrorActionPreference = "Continue"

$GpuOutput =
    docker run `
        --rm `
        --gpus all `
        -e NVIDIA_DRIVER_CAPABILITIES=compute,utility `
        -v "${BackupRoot}:/diag:ro" `
        redsight-redsight `
        python /diag/gpu_probe.py `
        2>&1

$GpuExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

$GpuOutput |
    ForEach-Object {
        Write-Host $_
    }

$GpuOutput |
    Out-String |
    Set-Content (
        Join-Path $BackupRoot "gpu-direct.txt"
    )

Write-Host ""

if ($GpuExit -ne 0) {

    Write-Host "===================================================================="
    Write-Host " REAL GPU PASSTHROUGH FAILURE"
    Write-Host "===================================================================="
    Write-Host ""

    Write-Host "The quoting problem is now eliminated."
    Write-Host "The failure above is therefore the genuine CUDA/NVML result."
    Write-Host ""

    Write-Host "WSL:"
    $ErrorActionPreference = "Continue"
    wsl.exe --version
    Write-Host ""
    docker info
    $ErrorActionPreference = "Stop"

    throw `
        "Direct Docker CUDA/NVML probe failed. Compose was NOT modified."
}

Write-Host ""
Write-Host "DIRECT DUAL-GPU + NVML PROBE: PASS"
Write-Host ""

# =====================================================================
# ENABLE GPUS PERSISTENTLY FOR REDSIGHT
# =====================================================================

Write-Host "===================================================================="
Write-Host " 3. PERSISTING BOTH GPUS INTO REDSIGHT COMPOSE"
Write-Host "===================================================================="

Set-RedsightScalar `
    -Key "gpus" `
    -Value "all"

Set-RedsightEnvironment `
    -Name "NVIDIA_VISIBLE_DEVICES" `
    -Value "all"

Set-RedsightEnvironment `
    -Name "NVIDIA_DRIVER_CAPABILITIES" `
    -Value "compute,utility"

Write-Host "Added/verified:"
Write-Host "  gpus: all"
Write-Host "  NVIDIA_VISIBLE_DEVICES=all"
Write-Host "  NVIDIA_DRIVER_CAPABILITIES=compute,utility"
Write-Host ""

# =====================================================================
# LM STUDIO — HOST
# =====================================================================

Write-Host "===================================================================="
Write-Host " 4. LM STUDIO CONNECTIVITY"
Write-Host "===================================================================="

$LmHostCode =
    Host-HttpCode `
        "http://127.0.0.1:1234/v1/models"

Write-Host "Windows -> LM Studio /v1/models: $LmHostCode"

# If LM Studio server is not running, safely try local-only startup.
if ($LmHostCode -ne "200") {

    $Lms =
        Get-Command lms `
            -ErrorAction SilentlyContinue

    if ($Lms) {

        Write-Host ""
        Write-Host "Attempting to start LM Studio server on localhost:1234..."

        $ErrorActionPreference = "Continue"

        & lms server start `
            --port 1234

        $ErrorActionPreference = "Stop"

        Start-Sleep -Seconds 3

        $LmHostCode =
            Host-HttpCode `
                "http://127.0.0.1:1234/v1/models"

        Write-Host "After start: $LmHostCode"
    }
}

Write-Host ""

# =====================================================================
# LM STUDIO — DOCKER
# =====================================================================

$LmDockerFile =
    Join-Path $BackupRoot "lm-models.json"

$ErrorActionPreference = "Continue"

$LmDockerOutput =
    docker run `
        --rm `
        --add-host host.docker.internal:host-gateway `
        redsight-redsight `
        curl `
        -fsS `
        --max-time 8 `
        http://host.docker.internal:1234/v1/models `
        2>&1

$LmDockerExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

$LmDockerOutput |
    Out-String |
    Set-Content $LmDockerFile

Write-Host "Docker -> LM Studio exit code: $LmDockerExit"

if ($LmDockerExit -eq 0) {

    Write-Host "Docker -> LM Studio /v1/models: PASS"
}

if ($LmDockerExit -ne 0) {

    Write-Warning `
        "Windows can access LM Studio, but Docker cannot."

    Write-Host ""
    Write-Host "LM Studio may currently be bound only to 127.0.0.1."
    Write-Host ""
    Write-Host "For security, Stage-6C will NOT silently expose LM Studio to your LAN."
    Write-Host ""
    Write-Host "If this occurs, the official LM Studio command is:"
    Write-Host ""
    Write-Host "  lms server stop"
    Write-Host "  lms server start --port 1234 --bind 0.0.0.0"
    Write-Host ""
}

Write-Host ""

# =====================================================================
# DISCOVER ACTUAL LM STUDIO ENVIRONMENT REFERENCES IN SOURCE
# =====================================================================

Write-Host "===================================================================="
Write-Host " 5. DISCOVERING REDSIGHT LM STUDIO CONFIG"
Write-Host "===================================================================="

$LmSourceProbe =
    Join-Path $BackupRoot "lm_source_probe.py"

$LmSourceProbeLines = @(
    'import ast'
    'import pathlib'
    ''
    'root = pathlib.Path("/source/app")'
    ''
    'def call_name(node):'
    '    if isinstance(node, ast.Attribute):'
    '        parts = []'
    '        cur = node'
    '        while isinstance(cur, ast.Attribute):'
    '            parts.append(cur.attr)'
    '            cur = cur.value'
    '        if isinstance(cur, ast.Name):'
    '            parts.append(cur.id)'
    '        return ".".join(reversed(parts))'
    '    if isinstance(node, ast.Name):'
    '        return node.id'
    '    return ""'
    ''
    'for path in sorted(root.rglob("*.py")):'
    '    try:'
    '        text = path.read_text(encoding="utf-8-sig")'
    '    except Exception:'
    '        continue'
    ''
    '    lowered = text.lower()'
    '    if not any(x in lowered for x in ("lm studio", "lm_studio", "lmstudio", ":1234")):'
    '        continue'
    ''
    '    rel = path.relative_to(root.parent)'
    ''
    '    if "LM Studio health check failed" in text:'
    '        print("HEALTHFILE|" + str(rel))'
    ''
    '    try:'
    '        tree = ast.parse(text, filename=str(path))'
    '    except SyntaxError:'
    '        continue'
    ''
    '    for node in ast.walk(tree):'
    '        if isinstance(node, ast.Constant) and isinstance(node.value, str):'
    '            if ":1234" in node.value:'
    '                print("URL|" + str(rel) + "|" + str(getattr(node, "lineno", 0)) + "|" + node.value)'
    ''
    '        if isinstance(node, ast.Call):'
    '            name = call_name(node.func)'
    '            if name not in ("os.getenv", "os.environ.get"):'
    '                continue'
    ''
    '            if not node.args:'
    '                continue'
    ''
    '            first = node.args[0]'
    '            if not isinstance(first, ast.Constant) or not isinstance(first.value, str):'
    '                continue'
    ''
    '            envname = first.value'
    '            default = ""'
    ''
    '            if len(node.args) > 1:'
    '                second = node.args[1]'
    '                if isinstance(second, ast.Constant) and isinstance(second.value, str):'
    '                    default = second.value'
    ''
    '            print("ENVREF|" + envname + "|" + default + "|" + str(rel) + "|" + str(getattr(node, "lineno", 0)))'
)

[System.IO.File]::WriteAllLines(
    $LmSourceProbe,
    $LmSourceProbeLines,
    $Utf8
)

$ErrorActionPreference = "Continue"

$LmSourceOutput =
    docker run `
        --rm `
        -v "${Root}:/source:ro" `
        -v "${BackupRoot}:/diag:ro" `
        redsight-redsight `
        python /diag/lm_source_probe.py `
        2>&1

$LmSourceExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

$LmSourceOutput |
    Out-String |
    Set-Content (
        Join-Path $BackupRoot "lm-source-discovery.txt"
    )

$LmSourceOutput |
    ForEach-Object {
        Write-Host $_
    }

Write-Host ""

# =====================================================================
# APPLY ENV VARIABLES EXPLICITLY REFERENCED BY LM CODE
# =====================================================================

$ActualLmEnvNames = @()

foreach ($OutputLine in $LmSourceOutput) {

    $Text =
        "$OutputLine"

    if (
        $Text -notmatch
        '^ENVREF\|([^|]+)\|([^|]*)\|([^|]+)\|(\d+)$'
    ) {
        continue
    }

    $Name =
        $Matches[1]

    $Default =
        $Matches[2]

    $Value = $null

    if (
        $Default -match
        'https?://(localhost|127\.0\.0\.1):1234'
    ) {

        $Value =
            $Default.Replace(
                "localhost",
                "host.docker.internal"
            ).Replace(
                "127.0.0.1",
                "host.docker.internal"
            )
    }

    if (
        -not $Value -and
        $Name -match 'LM.*(URL|BASE|ENDPOINT)'
    ) {

        $Value =
            "http://host.docker.internal:1234"
    }

    if (
        -not $Value -and
        $Name -match 'LM.*HOST'
    ) {

        $Value =
            "host.docker.internal"
    }

    if (
        -not $Value -and
        $Name -match 'LM.*PORT'
    ) {

        $Value =
            "1234"
    }

    if ($Value) {

        Set-RedsightEnvironment `
            -Name $Name `
            -Value $Value

        if ($Name -notin $ActualLmEnvNames) {
            $ActualLmEnvNames += $Name
        }

        Write-Host "Configured:"
        Write-Host "  $Name=$Value"
    }
}

# Common variables are retained as compatibility fallbacks.
Set-RedsightEnvironment `
    -Name "LM_STUDIO_URL" `
    -Value "http://host.docker.internal:1234"

Set-RedsightEnvironment `
    -Name "LM_STUDIO_BASE_URL" `
    -Value "http://host.docker.internal:1234"

Write-Host ""

# =====================================================================
# INSPECT EFFECTIVE Pydantic SETTINGS
# =====================================================================

$SettingsProbe =
    Join-Path $BackupRoot "lm_settings_probe.py"

$SettingsProbeLines = @(
    'import app.server as server'
    ''
    'settings = getattr(server, "settings", None)'
    ''
    'if settings is None:'
    '    print("NO_SERVER_SETTINGS")'
    '    raise SystemExit(0)'
    ''
    'config = getattr(settings, "model_config", {}) or {}'
    'prefix = str(config.get("env_prefix", "") or "")'
    'delimiter = str(config.get("env_nested_delimiter", "__") or "__")'
    ''
    'print("ROOTCFG|" + prefix + "|" + delimiter)'
    ''
    'seen = set()'
    ''
    'def walk(obj, path=""):'
    '    ident = id(obj)'
    '    if ident in seen:'
    '        return'
    ''
    '    if hasattr(obj, "model_fields"):'
    '        seen.add(ident)'
    '        fields = getattr(obj.__class__, "model_fields", {})'
    '        for name in fields:'
    '            try:'
    '                value = getattr(obj, name)'
    '            except Exception:'
    '                continue'
    '            child = path + "." + name if path else name'
    '            walk(value, child)'
    '        return'
    ''
    '    if isinstance(obj, dict):'
    '        seen.add(ident)'
    '        for key, value in obj.items():'
    '            child = path + "." + str(key) if path else str(key)'
    '            walk(value, child)'
    '        return'
    ''
    '    if isinstance(obj, (list, tuple, set)):'
    '        return'
    ''
    '    text = str(obj)'
    '    lowpath = path.lower()'
    ''
    '    if any(x in lowpath for x in ("lm", "studio", "llm")) or ":1234" in text:'
    '        print("SETTING|" + path + "|" + text)'
)

[System.IO.File]::WriteAllLines(
    $SettingsProbe,
    $SettingsProbeLines,
    $Utf8
)

# Copy into current healthy service.
$ErrorActionPreference = "Continue"

docker cp `
    $SettingsProbe `
    redsight:/tmp/lm_settings_probe.py

$CopySettingsExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

if ($CopySettingsExit -eq 0) {

    $ErrorActionPreference = "Continue"

    $SettingsBefore =
        docker exec `
            redsight `
            python /tmp/lm_settings_probe.py `
            2>&1

    $ErrorActionPreference = "Stop"

    $SettingsBefore |
        Out-String |
        Set-Content (
            Join-Path $BackupRoot "lm-settings-before.txt"
        )

    Write-Host "Current LM-related settings:"
    $SettingsBefore |
        ForEach-Object {
            Write-Host $_
        }

    Write-Host ""

    # -------------------------------------------------------------
    # Derive Pydantic nested environment names from effective paths.
    # -------------------------------------------------------------

    $Prefix =
        ""

    $Delimiter =
        "__"

    foreach ($Line in $SettingsBefore) {

        $Text =
            "$Line"

        if (
            $Text -match
            '^ROOTCFG\|([^|]*)\|([^|]*)$'
        ) {

            $Prefix =
                $Matches[1]

            if ($Matches[2]) {
                $Delimiter = $Matches[2]
            }
        }
    }

    foreach ($Line in $SettingsBefore) {

        $Text =
            "$Line"

        if (
            $Text -notmatch
            '^SETTING\|([^|]+)\|(.*)$'
        ) {
            continue
        }

        $Path =
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
            $Path.Split(".") |
            ForEach-Object {
                $_.ToUpperInvariant()
            }

        $DerivedName =
            (
                $Prefix +
                ($Parts -join $Delimiter)
            ).ToUpperInvariant()

        if ($DerivedName) {

            Set-RedsightEnvironment `
                -Name $DerivedName `
                -Value $NewValue

            Write-Host "Derived from Pydantic settings:"
            Write-Host "  path  = $Path"
            Write-Host "  env   = $DerivedName"
            Write-Host "  value = $NewValue"
            Write-Host ""
        }
    }
}

# =====================================================================
# VALIDATE COMPOSE BEFORE RECREATE
# =====================================================================

Write-Host "===================================================================="
Write-Host " 6. COMPOSE VALIDATION"
Write-Host "===================================================================="

$ResolvedCompose =
    Join-Path $BackupRoot "compose-resolved.yml"

$ErrorActionPreference = "Continue"

docker compose `
    -f $Compose `
    -f $Override `
    config `
    1> $ResolvedCompose

$ComposeExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

if ($ComposeExit -ne 0) {

    throw "Docker Compose validation failed."
}

Write-Host "Compose: PASS"
Write-Host ""

# =====================================================================
# RECREATE ONLY REDSIGHT
# =====================================================================

Write-Host "===================================================================="
Write-Host " 7. RECREATING REDSIGHT WITH GPU + LM CONFIG"
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

# =====================================================================
# WAIT FOR HEALTH
# =====================================================================

for ($i = 1; $i -le 35; $i++) {

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

# =====================================================================
# VERIFY DUAL GPUS INSIDE ACTUAL REDSIGHT SERVICE
# =====================================================================

Write-Host "===================================================================="
Write-Host " 8. GPU + NVML INSIDE REDSIGHT SERVICE"
Write-Host "===================================================================="

$ErrorActionPreference = "Continue"

docker cp `
    $GpuProbe `
    redsight:/tmp/gpu_probe.py

$GpuCopyExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

if ($GpuCopyExit -ne 0) {
    throw "Could not copy GPU probe into RedSight."
}

$ErrorActionPreference = "Continue"

$ServiceGpu =
    docker exec `
        redsight `
        python /tmp/gpu_probe.py `
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
        Join-Path $BackupRoot "gpu-service.txt"
    )

Write-Host ""

if ($ServiceGpuExit -ne 0) {

    throw `
        "Direct GPU probe passed, but the actual RedSight Compose service cannot see both GPUs/NVML."
}

# =====================================================================
# LM STUDIO FROM ACTUAL REDSIGHT SERVICE
# =====================================================================

Write-Host "===================================================================="
Write-Host " 9. LIVE REDSIGHT -> LM STUDIO"
Write-Host "===================================================================="

$ErrorActionPreference = "Continue"

$LiveLmModels =
    docker exec `
        redsight `
        curl `
        -fsS `
        --max-time 8 `
        http://host.docker.internal:1234/v1/models `
        2>&1

$LiveLmExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

Write-Host "Live RedSight -> LM Studio exit: $LiveLmExit"

$LiveLmModels |
    Out-String |
    Set-Content (
        Join-Path $BackupRoot "lm-live-models.json"
    )

if ($LiveLmExit -eq 0) {

    Write-Host "Live container /v1/models: PASS"
}

Write-Host ""

# =====================================================================
# LM STUDIO INFERENCE PROBE AS REAL PYTHON FILE
# =====================================================================

$LmInferenceProbe =
    Join-Path $BackupRoot "lm_inference_probe.py"

$LmInferenceLines = @(
    'import httpx'
    'import sys'
    ''
    'base = "http://host.docker.internal:1234"'
    ''
    'r = httpx.get(base + "/v1/models", timeout=10.0)'
    'print("MODELS_STATUS=" + str(r.status_code))'
    'r.raise_for_status()'
    ''
    'data = r.json()'
    'models = data.get("data", [])'
    ''
    'if not models:'
    '    raise RuntimeError("LM Studio reports no models")'
    ''
    'model = models[0].get("id")'
    ''
    'if not model:'
    '    raise RuntimeError("Could not obtain model id from /v1/models")'
    ''
    'print("MODEL=" + model)'
    ''
    'payload = {'
    '    "model": model,'
    '    "messages": ['
    '        {'
    '            "role": "user",'
    '            "content": "Reply with exactly LM_STUDIO_E2E_OK",'
    '        }'
    '    ],'
    '    "temperature": 0,'
    '}'
    ''
    'r = httpx.post('
    '    base + "/v1/chat/completions",'
    '    json=payload,'
    '    timeout=120.0,'
    ')'
    ''
    'print("CHAT_STATUS=" + str(r.status_code))'
    'print(r.text[:4000])'
    'r.raise_for_status()'
    ''
    'print("LM_STUDIO_INFERENCE=PASS")'
)

[System.IO.File]::WriteAllLines(
    $LmInferenceProbe,
    $LmInferenceLines,
    $Utf8
)

$ErrorActionPreference = "Continue"

docker cp `
    $LmInferenceProbe `
    redsight:/tmp/lm_inference_probe.py

$ErrorActionPreference = "Stop"

$ErrorActionPreference = "Continue"

$LmInferenceOutput =
    docker exec `
        redsight `
        python /tmp/lm_inference_probe.py `
        2>&1

$LmInferenceExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

$LmInferenceOutput |
    ForEach-Object {
        Write-Host $_
    }

$LmInferenceOutput |
    Out-String |
    Set-Content (
        Join-Path $BackupRoot "lm-inference.txt"
    )

Write-Host ""

# =====================================================================
# CHECK REDSIGHT LOG WARNINGS
# =====================================================================

$RuntimeLog =
    Join-Path $BackupRoot "redsight-runtime.log"

$LogCommand =
    'docker logs --tail 600 redsight > "' +
    $RuntimeLog +
    '" 2>&1'

cmd.exe /d /c $LogCommand

$RuntimeText =
    [System.IO.File]::ReadAllText(
        $RuntimeLog
    )

$StartupOK =
    $RuntimeText.Contains(
        "Application startup complete"
    )

$NvmlFailure =
    $RuntimeText.Contains(
        "NVML initialization failed"
    )

$LmHealthFailure =
    $RuntimeText.Contains(
        "LM Studio health check failed"
    )

Write-Host "===================================================================="
Write-Host " 10. REDSIGHT RUNTIME RESULTS"
Write-Host "===================================================================="

Write-Host "Application startup complete : $StartupOK"
Write-Host "NVML initialization failed   : $NvmlFailure"
Write-Host "LM Studio health check failed: $LmHealthFailure"
Write-Host ""

# =====================================================================
# REDSIGHT -> LM STUDIO END-TO-END CHAT
# =====================================================================

Write-Host "===================================================================="
Write-Host " 11. REDSIGHT CHAT END-TO-END"
Write-Host "===================================================================="

$RedSightChatOK =
    $false

$Body =
    @{
        message = "Reply with exactly REDSIGHT_E2E_OK"
    } |
    ConvertTo-Json -Compress

try {

    $ChatResult =
        Invoke-RestMethod `
            -Uri "http://127.0.0.1:8000/api/v1/chat" `
            -Method Post `
            -ContentType "application/json" `
            -Body $Body `
            -TimeoutSec 120

    Write-Host (
        $ChatResult |
        ConvertTo-Json `
            -Depth 10
    )

    $RedSightChatOK =
        $true
}
catch {

    Write-Warning "RedSight chat API failed:"
    Write-Warning $_.Exception.Message
}

Write-Host ""
Write-Host "RedSight -> LM Studio chat: $RedSightChatOK"
Write-Host ""

# =====================================================================
# COMMAND CENTER UI EVENT LOOP REPAIR
# =====================================================================

Write-Host "===================================================================="
Write-Host " 12. COMMAND CENTER ASYNCIO + QT REPAIR"
Write-Host "===================================================================="

$UiText =
    [System.IO.File]::ReadAllText($UI)

# -------------------------------------------------------------
# Keep the existing asyncio.create_task() call.
#
# The issue was the absence of a running asyncio-compatible Qt loop.
# -------------------------------------------------------------

if (
    $UiText -notmatch
    'PySide6\.QtAsyncio'
) {

    $FirstPySide =
        [regex]::Match(
            $UiText,
            '(?m)^from\s+PySide6'
        )

    if (-not $FirstPySide.Success) {

        throw `
            "Could not find a PySide6 import in command_center.py."
    }

    $Position =
        $FirstPySide.Index

    $UiText =
        $UiText.Insert(
            $Position,
            "import PySide6.QtAsyncio as QtAsyncio`r`n"
        )
}

$AlreadyQtAsync =
    $UiText -match
    'QtAsyncio\.run\s*\('

if (-not $AlreadyQtAsync) {

    $ExitExec =
        [regex]::Matches(
            $UiText,
            '(?m)^(\s*)sys\.exit\(app\.exec\(\)\)\s*$'
        ).Count

    $ReturnExec =
        [regex]::Matches(
            $UiText,
            '(?m)^(\s*)return\s+app\.exec\(\)\s*$'
        ).Count

    $PlainExec =
        [regex]::Matches(
            $UiText,
            '(?m)^(\s*)app\.exec\(\)\s*$'
        ).Count

    if ($ExitExec -gt 0) {

        $UiText =
            [regex]::Replace(
                $UiText,
                '(?m)^(\s*)sys\.exit\(app\.exec\(\)\)\s*$',
                '$1QtAsyncio.run(handle_sigint=True)'
            )
    }
    elseif ($ReturnExec -gt 0) {

        $UiText =
            [regex]::Replace(
                $UiText,
                '(?m)^(\s*)return\s+app\.exec\(\)\s*$',
                '$1QtAsyncio.run(handle_sigint=True)' +
                "`r`n" +
                '$1return 0'
            )
    }
    elseif ($PlainExec -gt 0) {

        $UiText =
            [regex]::Replace(
                $UiText,
                '(?m)^(\s*)app\.exec\(\)\s*$',
                '$1QtAsyncio.run(handle_sigint=True)'
            )
    }
    else {

        throw `
            "Could not identify the existing Qt app.exec() call. UI source was not saved."
    }
}

Save-Utf8 `
    -Path $UI `
    -Text $UiText

Write-Host "QtAsyncio event-loop integration applied."
Write-Host ""

# =====================================================================
# AST VALIDATE UI USING CONTAINER
# =====================================================================

$UiValidate =
    Join-Path $BackupRoot "validate_ui.py"

$UiValidateLines = @(
    'import ast'
    'import pathlib'
    ''
    'p = pathlib.Path("/source/app/ui/command_center.py")'
    'text = p.read_text(encoding="utf-8-sig")'
    'ast.parse(text, filename=str(p))'
    'print("COMMAND_CENTER_AST=OK")'
)

[System.IO.File]::WriteAllLines(
    $UiValidate,
    $UiValidateLines,
    $Utf8
)

$ErrorActionPreference = "Continue"

$UiAstOutput =
    docker run `
        --rm `
        -v "${Root}:/source:ro" `
        -v "${BackupRoot}:/diag:ro" `
        redsight-redsight `
        python /diag/validate_ui.py `
        2>&1

$UiAstExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

$UiAstOutput |
    ForEach-Object {
        Write-Host $_
    }

if ($UiAstExit -ne 0) {
    throw "Command Center syntax validation failed."
}

Write-Host ""

# =====================================================================
# WINDOWS PYTHON FOR UI
# =====================================================================

Write-Host "===================================================================="
Write-Host " 13. WINDOWS PYSIDE UI ENVIRONMENT"
Write-Host "===================================================================="

$BaseExe =
    $null

$BaseArgs =
    @()

$Py =
    Get-Command py `
        -ErrorAction SilentlyContinue

if ($Py) {

    $ErrorActionPreference = "Continue"

    & py -3.12 --version `
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

    $Python =
        Get-Command python `
            -ErrorAction SilentlyContinue

    if ($Python) {

        $BaseExe =
            $Python.Source
    }
}

if (-not $BaseExe) {

    throw `
        "Windows Python was not found. Native PySide UI cannot be launched."
}

if (-not (Test-Path $UiVenv)) {

    Write-Host "Creating isolated UI venv..."

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
    throw ".venv-ui Python executable is missing."
}

Write-Host "UI Python:"
Write-Host $UiPython
Write-Host ""

# =====================================================================
# INSTALL NATIVE UI-ONLY DEPENDENCIES
# =====================================================================

& $UiPython `
    -m pip `
    install `
    --upgrade `
    pip

if ($LASTEXITCODE -ne 0) {
    throw "pip upgrade failed."
}

& $UiPython `
    -m pip `
    install `
    "PySide6>=6.8" `
    httpx `
    psutil `
    structlog `
    pydantic `
    pydantic-settings `
    PyYAML `
    markdown `
    pygments

if ($LASTEXITCODE -ne 0) {
    throw "Native UI dependency installation failed."
}

Write-Host ""

# =====================================================================
# VERIFY QtAsyncio
# =====================================================================

$QtProbe =
    Join-Path $BackupRoot "qt_probe.py"

$QtProbeLines = @(
    'import PySide6'
    'import PySide6.QtAsyncio as QtAsyncio'
    'print("PYSIDE_VERSION=" + PySide6.__version__)'
    'print("QTASYNCIO=OK")'
)

[System.IO.File]::WriteAllLines(
    $QtProbe,
    $QtProbeLines,
    $Utf8
)

& $UiPython `
    $QtProbe

if ($LASTEXITCODE -ne 0) {
    throw "PySide6.QtAsyncio could not be imported."
}

Write-Host ""

# =====================================================================
# IMPORT COMMAND CENTER
# =====================================================================

$UiImportProbe =
    Join-Path $BackupRoot "ui_import_probe.py"

$EscapedRoot =
    $Root.Replace(
        "\",
        "\\"
    )

$UiImportLines = @(
    'import sys'
    "sys.path.insert(0, r`"$Root`")"
    'import app.ui.command_center'
    'print("COMMAND_CENTER_IMPORT=OK")'
)

[System.IO.File]::WriteAllLines(
    $UiImportProbe,
    $UiImportLines,
    $Utf8
)

$ErrorActionPreference = "Continue"

$UiImport =
    & $UiPython `
        $UiImportProbe `
        2>&1

$UiImportExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

$UiImport |
    ForEach-Object {
        Write-Host $_
    }

$UiImport |
    Out-String |
    Set-Content (
        Join-Path $BackupRoot "ui-import.txt"
    )

if ($UiImportExit -ne 0) {

    throw `
        "Command Center import failed. The exact missing Windows dependency is shown above and saved in ui-import.txt."
}

Write-Host ""

# =====================================================================
# CREATE REUSABLE LAUNCHER
# =====================================================================

$Launcher =
    Join-Path $Root `
        "LAUNCH-REDSIGHT-COMMAND-CENTER.ps1"

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

# =====================================================================
# LAUNCH UI
# =====================================================================

Write-Host "===================================================================="
Write-Host " 14. LAUNCHING REDSIGHT COMMAND CENTER"
Write-Host "===================================================================="

$UiStdout =
    Join-Path $BackupRoot `
        "command-center.stdout.log"

$UiStderr =
    Join-Path $BackupRoot `
        "command-center.stderr.log"

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

Start-Sleep -Seconds 5

$UiProcess.Refresh()

if ($UiProcess.HasExited) {

    Write-Host ""
    Write-Host "The Command Center exited immediately."
    Write-Host ""

    if (Test-Path $UiStderr) {

        Write-Host "=== UI STDERR ==="

        Get-Content `
            $UiStderr `
            -Tail 120
    }

    throw `
        "Command Center launch failed. Full stderr was preserved."
}

Write-Host "COMMAND_CENTER_LAUNCHED=YES"
Write-Host "PID=$($UiProcess.Id)"
Write-Host ""

# =====================================================================
# FINAL STATUS
# =====================================================================

Write-Host "===================================================================="
Write-Host " FINAL REDSIGHT STATUS"
Write-Host "===================================================================="

$ErrorActionPreference = "Continue"

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

$ErrorActionPreference = "Stop"

Write-Host ""

$FinalHealth =
    Host-HttpCode `
        "http://127.0.0.1:8000/api/v1/health"

Write-Host "API health HTTP       : $FinalHealth"
Write-Host "GPU service probe     : $ServiceGpuExit"
Write-Host "LM models probe       : $LiveLmExit"
Write-Host "LM inference probe    : $LmInferenceExit"
Write-Host "RedSight chat E2E     : $RedSightChatOK"
Write-Host "NVML warning present  : $NvmlFailure"
Write-Host "LM warning present    : $LmHealthFailure"
Write-Host "Command Center PID    : $($UiProcess.Id)"
Write-Host ""

Write-Host "===================================================================="

if (
    $FinalHealth -eq "200" -and
    $ServiceGpuExit -eq 0 -and
    (-not $NvmlFailure) -and
    $UiProcess.Id
) {

    Write-Host " REDSIGHT GPU + BACKEND + COMMAND CENTER: OPERATIONAL"
}

Write-Host "===================================================================="
Write-Host ""

Write-Host "Diagnostics:"
Write-Host $BackupRoot
Write-Host ""

Write-Host "Reusable Command Center launcher:"
Write-Host $Launcher
Write-Host ""

Write-Host "Qdrant volumes/data were NOT deleted or reset."
Write-Host ""
