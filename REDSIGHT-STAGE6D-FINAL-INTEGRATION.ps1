$ErrorActionPreference = "Stop"

$Root       = "C:\Users\walim\RedSight"
$Compose    = Join-Path $Root "docker-compose.yml"
$Override   = Join-Path $Root "docker-compose.override.yml"
$Settings   = Join-Path $Root "app\config\settings.py"
$UI         = Join-Path $Root "app\ui\command_center.py"

$Stamp      = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot = Join-Path $Root ".repair-backups\stage6d-$Stamp"
$UiVenv     = Join-Path $Root ".venv-ui"

$Utf8 = New-Object System.Text.UTF8Encoding($false)

Set-Location $Root

New-Item `
    -ItemType Directory `
    -Path $BackupRoot `
    -Force |
    Out-Null

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

    $Name =
        $Path.Substring(
            $script:Root.Length
        ).TrimStart("\") `
        -replace '[\\/:*?"<>|]', '__'

    Copy-Item `
        -LiteralPath $Path `
        -Destination (Join-Path $script:BackupRoot $Name) `
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
        throw "Could not locate the redsight service in docker-compose.override.yml."
    }

    for ($i = $Start + 1; $i -lt $Lines.Count; $i++) {

        if ($Lines[$i] -match '^\s{2}[A-Za-z0-9_.-]+:\s*$') {
            $End = $i - 1
            break
        }
    }

    return @($Start,$End)
}

function Set-RedsightEnv {
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

    $Start = [int]$Bounds[0]
    $End   = [int]$Bounds[1]

    $EnvironmentIndex = -1

    for ($i = $Start + 1; $i -le $End; $i++) {

        if ($Lines[$i] -match '^\s{4}environment:\s*$') {
            $EnvironmentIndex = $i
            break
        }
    }

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

    $EnvironmentEnd = $End

    for (
        $i = $EnvironmentIndex + 1;
        $i -le $End;
        $i++
    ) {

        if ($Lines[$i].Trim().Length -eq 0) {
            continue
        }

        if ($Lines[$i] -match '^\s{4}\S') {

            $EnvironmentEnd = $i - 1
            break
        }
    }

    for (
        $i = $EnvironmentIndex + 1;
        $i -le $EnvironmentEnd;
        $i++
    ) {

        if ($Lines[$i] -match '^\s{6}-\s*') {

            throw `
                "Compose override uses list-style environment entries. Stopping rather than rewrite it automatically."
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

function Get-HttpCode {
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

Write-Host ""
Write-Host "===================================================================="
Write-Host " REDSIGHT STAGE-6D"
Write-Host " LM CONFIG + CHAT E2E + QTASYNCIO COMMAND CENTER"
Write-Host "===================================================================="
Write-Host ""

foreach ($Required in @(
    $Compose,
    $Override,
    $Settings,
    $UI
)) {

    if (-not (Test-Path $Required)) {
        throw "Required file missing: $Required"
    }
}

Backup-One $Override
Backup-One $Settings
Backup-One $UI

Write-Host "Backup:"
Write-Host $BackupRoot
Write-Host ""

# =====================================================================
# 1. VERIFY WE DO NOT REGRESS THE WORKING BASELINE
# =====================================================================

Write-Host "===================================================================="
Write-Host " 1. BASELINE"
Write-Host "===================================================================="

$BackendCode =
    Get-HttpCode `
        "http://127.0.0.1:8000/api/v1/health"

Write-Host "RedSight API health: $BackendCode"

if ($BackendCode -ne "200") {
    throw "RedSight backend is not healthy. Stage-6D will not modify it."
}

$ErrorActionPreference = "Continue"

$GpuList =
    docker exec `
        redsight `
        nvidia-smi -L `
        2>&1

$GpuListExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

$GpuList |
    ForEach-Object {
        Write-Host $_
    }

if ($GpuListExit -ne 0) {
    throw "Live RedSight GPU access regressed."
}

if (($GpuList | Out-String) -notmatch 'GPU 1:') {
    throw "Live RedSight container no longer exposes two GPUs."
}

Write-Host ""
Write-Host "Dual-GPU baseline: PASS"
Write-Host ""

# =====================================================================
# 2. CREATE REAL SETTINGS PROBE
#
# Important difference from Stage-6C:
# docker exec uses -w /app so `import app` works.
# =====================================================================

Write-Host "===================================================================="
Write-Host " 2. DISCOVERING THE ACTUAL LM STUDIO SETTING"
Write-Host "===================================================================="

$Probe =
    Join-Path $BackupRoot `
        "lm_settings_probe.py"

$ProbeLines = @(
    'import os'
    'import sys'
    ''
    'sys.path.insert(0, "/app")'
    ''
    'import app.server as server'
    ''
    'settings = getattr(server, "settings", None)'
    ''
    'if settings is None:'
    '    print("ERROR|server.settings missing")'
    '    raise SystemExit(2)'
    ''
    'Root = type(settings)'
    'root_config = getattr(settings, "model_config", {}) or {}'
    ''
    'root_prefix = str(root_config.get("env_prefix", "") or "")'
    'root_delimiter = str(root_config.get("env_nested_delimiter", "__") or "__")'
    ''
    'print("ROOT|" + root_prefix + "|" + root_delimiter)'
    ''
    'def aliases(field):'
    '    result = []'
    ''
    '    for attr in ("validation_alias", "alias"):'
    '        value = getattr(field, attr, None)'
    ''
    '        if isinstance(value, str):'
    '            result.append(value)'
    ''
    '        choices = getattr(value, "choices", None)'
    '        if choices:'
    '            for choice in choices:'
    '                if isinstance(choice, str):'
    '                    result.append(choice)'
    ''
    '    return list(dict.fromkeys(result))'
    ''
    'def get_path(obj, path):'
    '    cur = obj'
    '    for part in path.split("."):'
    '        cur = getattr(cur, part)'
    '    return cur'
    ''
    'targets = []'
    ''
    'def walk(obj, path=""):'
    '    fields = getattr(obj.__class__, "model_fields", None)'
    ''
    '    if not fields:'
    '        return'
    ''
    '    for name, field in fields.items():'
    '        try:'
    '            value = getattr(obj, name)'
    '        except Exception:'
    '            continue'
    ''
    '        child = path + "." + name if path else name'
    ''
    '        nested = getattr(value.__class__, "model_fields", None)'
    '        if nested:'
    '            walk(value, child)'
    '            continue'
    ''
    '        text = str(value)'
    ''
    '        if ("127.0.0.1:1234" in text or "localhost:1234" in text):'
    '            targets.append((child, text, field))'
    '            print("TARGET|" + child + "|" + text)'
    ''
    'walk(settings)'
    ''
    'if not targets:'
    '    print("NO_BAD_LM_TARGET")'
    '    raise SystemExit(0)'
    ''
    'for path, old_value, field in targets:'
    '    new_value = old_value.replace("127.0.0.1", "host.docker.internal").replace("localhost", "host.docker.internal")'
    ''
    '    parts = [p.upper() for p in path.split(".")]'
    ''
    '    candidates = []'
    '    candidates.extend(aliases(field))'
    ''
    '    if root_delimiter:'
    '        candidates.append(root_prefix + root_delimiter.join(parts))'
    ''
    '    candidates.append(root_prefix + "_".join(parts))'
    '    candidates.extend(['
    '        "LM_STUDIO_URL",'
    '        "LM_STUDIO_BASE_URL",'
    '        "LMSTUDIO_URL",'
    '        "LMSTUDIO_BASE_URL",'
    '    ])'
    ''
    '    candidates = [c for c in dict.fromkeys(candidates) if c]'
    ''
    '    print("NEWVALUE|" + path + "|" + new_value)'
    ''
    '    working = None'
    ''
    '    for candidate in candidates:'
    '        previous = os.environ.get(candidate)'
    '        existed = candidate in os.environ'
    ''
    '        os.environ[candidate] = new_value'
    ''
    '        try:'
    '            test_settings = Root()'
    '            test_value = str(get_path(test_settings, path))'
    '        except Exception:'
    '            test_value = ""'
    ''
    '        if existed:'
    '            os.environ[candidate] = previous'
    '        else:'
    '            os.environ.pop(candidate, None)'
    ''
    '        if test_value == new_value:'
    '            working = candidate'
    '            print("WORKING_ENV|" + path + "|" + candidate + "|" + new_value)'
    '            break'
    ''
    '    if working is None:'
    '        print("NO_WORKING_ENV|" + path + "|" + new_value)'
)

[System.IO.File]::WriteAllLines(
    $Probe,
    $ProbeLines,
    $Utf8
)

$ErrorActionPreference = "Continue"

docker cp `
    $Probe `
    redsight:/tmp/lm_settings_probe.py

$CopyExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

if ($CopyExit -ne 0) {
    throw "Could not copy LM settings probe."
}

$ErrorActionPreference = "Continue"

$ProbeOutput =
    docker exec `
        -w /app `
        redsight `
        python /tmp/lm_settings_probe.py `
        2>&1

$ProbeExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

$ProbeOutput |
    ForEach-Object {
        Write-Host $_
    }

$ProbeOutput |
    Out-String |
    Set-Content (
        Join-Path $BackupRoot `
            "lm-settings-probe.txt"
    )

Write-Host ""

# =====================================================================
# 3. PERSIST A PROVEN ENV VARIABLE
# =====================================================================

$WorkingEnvCount = 0

foreach ($Line in $ProbeOutput) {

    $Text = "$Line"

    if (
        $Text -notmatch
        '^WORKING_ENV\|([^|]+)\|([^|]+)\|(.*)$'
    ) {
        continue
    }

    $ConfigPath =
        $Matches[1]

    $EnvName =
        $Matches[2]

    $Value =
        $Matches[3]

    Write-Host "PROVEN RedSight environment override:"
    Write-Host "  setting = $ConfigPath"
    Write-Host "  env     = $EnvName"
    Write-Host "  value   = $Value"
    Write-Host ""

    Set-RedsightEnv `
        -Name $EnvName `
        -Value $Value

    $WorkingEnvCount++
}

# =====================================================================
# 4. SOURCE FALLBACK ONLY IF PYDANTIC HAS NO USABLE ENV OVERRIDE
# =====================================================================

$SourceModified = $false

if ($WorkingEnvCount -eq 0) {

    Write-Host "No proven Pydantic environment override was discovered."
    Write-Host "Using targeted Docker-backend default repair."
    Write-Host ""

    $SettingsText =
        [System.IO.File]::ReadAllText(
            $Settings
        )

    $OldUrl =
        "http://127.0.0.1:1234/v1"

    $NewUrl =
        "http://host.docker.internal:1234/v1"

    $UrlCount =
        ([regex]::Matches(
            $SettingsText,
            [regex]::Escape($OldUrl)
        )).Count

    Write-Host "127.0.0.1 LM Studio defaults found: $UrlCount"

    if ($UrlCount -eq 0) {

        throw `
            "No environment override worked, and the known LM Studio default is no longer present."
    }

    if ($UrlCount -gt 1) {

        throw `
            "Multiple LM Studio default URLs were found. Automatic source modification stopped."
    }

    $SettingsText =
        $SettingsText.Replace(
            $OldUrl,
            $NewUrl
        )

    Save-Utf8 `
        -Path $Settings `
        -Text $SettingsText

    $SourceModified =
        $true

    Write-Host ""
    Write-Host "Changed Docker backend default:"
    Write-Host "  $OldUrl"
    Write-Host "     ->"
    Write-Host "  $NewUrl"
    Write-Host ""
}

# =====================================================================
# 5. VALIDATE COMPOSE
# =====================================================================

Write-Host "===================================================================="
Write-Host " 3. VALIDATING CONFIGURATION"
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
    throw "Docker Compose validation failed."
}

Write-Host "Compose: PASS"
Write-Host ""

# =====================================================================
# 6. REBUILD ONLY IF settings.py CHANGED
# =====================================================================

if ($SourceModified) {

    Write-Host "=== Rebuilding RedSight because settings.py changed ==="

    $ErrorActionPreference = "Continue"

    docker compose `
        -f $Compose `
        -f $Override `
        build redsight

    $BuildExit =
        $LASTEXITCODE

    $ErrorActionPreference = "Stop"

    if ($BuildExit -ne 0) {
        throw "RedSight rebuild failed."
    }

    Write-Host ""
}

# =====================================================================
# 7. RECREATE REDSIGHT ONLY
# =====================================================================

Write-Host "===================================================================="
Write-Host " 4. RECREATING REDSIGHT"
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
# 8. WAIT FOR HEALTHY
# =====================================================================

for ($i = 1; $i -le 40; $i++) {

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
# 9. VERIFY BOTH GPUS STILL EXIST AFTER RECREATE
# =====================================================================

Write-Host "=== GPU regression check ==="

$ErrorActionPreference = "Continue"

$GpuAfter =
    docker exec `
        redsight `
        nvidia-smi -L `
        2>&1

$GpuAfterExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

$GpuAfter |
    ForEach-Object {
        Write-Host $_
    }

if ($GpuAfterExit -ne 0) {
    throw "GPU access was lost after RedSight recreation."
}

if (($GpuAfter | Out-String) -notmatch 'GPU 1:') {
    throw "Only one GPU is visible after recreation."
}

Write-Host ""
Write-Host "Both RTX 5090s still visible: YES"
Write-Host ""

# =====================================================================
# 10. DIRECT LIVE LM STUDIO TEST AGAIN
# =====================================================================

Write-Host "=== Live container -> LM Studio ==="

$ErrorActionPreference = "Continue"

$LmDirect =
    docker exec `
        redsight `
        curl `
        -fsS `
        --max-time 8 `
        http://host.docker.internal:1234/v1/models `
        2>&1

$LmDirectExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

Write-Host "LM Studio direct exit: $LmDirectExit"

if ($LmDirectExit -ne 0) {
    throw "Live RedSight container lost LM Studio connectivity."
}

Write-Host "LM Studio direct connectivity: PASS"
Write-Host ""

# =====================================================================
# 11. CHECK FRESH REDSIGHT LOG
# =====================================================================

$RuntimeLog =
    Join-Path $BackupRoot `
        "redsight-after-lm-fix.log"

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

$NvmlFailed =
    $RuntimeText.Contains(
        "NVML initialization failed"
    )

$LmFailed =
    $RuntimeText.Contains(
        "LM Studio health check failed"
    )

Write-Host "===================================================================="
Write-Host " 5. REDSIGHT STARTUP RESULTS"
Write-Host "===================================================================="

Write-Host "Application startup complete : $StartupOK"
Write-Host "NVML initialization failed   : $NvmlFailed"
Write-Host "LM Studio health check failed: $LmFailed"
Write-Host ""

if (-not $StartupOK) {

    Get-Content `
        $RuntimeLog `
        -Tail 140

    throw "RedSight no longer completes startup."
}

if ($NvmlFailed) {
    throw "NVML works directly but RedSight still reports NVML failure."
}

if ($LmFailed) {

    Write-Host "LM direct connectivity is good, but RedSight's own LM health still fails."
    Write-Host ""
    Write-Host "Relevant source:"
    Write-Host ""

    Get-Content `
        (Join-Path $Root "app\models\lmstudio.py") |
        Select-String `
            -Pattern `
            "health",
            "base_url",
            "models",
            "1234" `
            -Context 3,3

    throw `
        "LM Studio application configuration still requires one additional source-level repair. Diagnostic shown above."
}

Write-Host "REDSIGHT LM STUDIO HEALTH: PASS"
Write-Host ""

# =====================================================================
# 12. REDSIGHT CHAT PROBE
# =====================================================================

Write-Host "===================================================================="
Write-Host " 6. REDSIGHT -> LM STUDIO CHAT E2E"
Write-Host "===================================================================="

$ChatProbe =
    Join-Path $BackupRoot `
        "redsight_chat_probe.py"

$ChatProbeLines = @(
    'import json'
    'import httpx'
    'import sys'
    ''
    'base = "http://127.0.0.1:8000"'
    'text = "Reply with exactly REDSIGHT_E2E_OK"'
    ''
    'def resolve_schema(openapi, schema):'
    '    seen = set()'
    ''
    '    while isinstance(schema, dict) and "$ref" in schema:'
    '        ref = schema["$ref"]'
    '        if ref in seen:'
    '            break'
    '        seen.add(ref)'
    ''
    '        cur = openapi'
    '        for part in ref.lstrip("#/").split("/"):'
    '            cur = cur[part]'
    '        schema = cur'
    ''
    '    return schema'
    ''
    'def send(mode, payload):'
    '    try:'
    '        r = httpx.post('
    '            base + "/api/v1/chat",'
    '            json=payload,'
    '            timeout=120.0,'
    '        )'
    '    except Exception as exc:'
    '        print("ATTEMPT|" + mode + "|EXCEPTION|" + repr(exc))'
    '        return False'
    ''
    '    print("ATTEMPT|" + mode + "|" + str(r.status_code))'
    '    print(r.text[:5000])'
    ''
    '    if r.status_code >= 200 and r.status_code < 300:'
    '        print("CHAT_MODE=" + mode)'
    '        print("CHAT_E2E=PASS")'
    '        return True'
    ''
    '    return False'
    ''
    '# First try exactly what the current Command Center uses.'
    'if send("message", {"message": text}):'
    '    raise SystemExit(0)'
    ''
    '# If that fails, inspect RedSight OpenAPI rather than guessing.'
    'openapi = httpx.get(base + "/openapi.json", timeout=10.0).json()'
    'operation = openapi["paths"]["/api/v1/chat"]["post"]'
    ''
    'content = operation.get("requestBody", {}).get("content", {})'
    'schema = content.get("application/json", {}).get("schema", {})'
    'schema = resolve_schema(openapi, schema)'
    ''
    'print("CHAT_SCHEMA=" + json.dumps(schema, indent=2)[:12000])'
    ''
    'properties = schema.get("properties", {})'
    'required = schema.get("required", [])'
    ''
    'model_id = None'
    ''
    'try:'
    '    lm = httpx.get('
    '        "http://host.docker.internal:1234/v1/models",'
    '        timeout=10.0,'
    '    ).json()'
    '    entries = lm.get("data", [])'
    '    if entries:'
    '        model_id = entries[0].get("id")'
    'except Exception:'
    '    pass'
    ''
    'modes = ["messages", "prompt", "query", "input", "content", "text"]'
    ''
    'for mode in modes:'
    '    if mode not in properties:'
    '        continue'
    ''
    '    payload = {}'
    ''
    '    for name in required:'
    '        spec = resolve_schema(openapi, properties.get(name, {}))'
    '        typ = spec.get("type")'
    ''
    '        if name == "model" and model_id:'
    '            payload[name] = model_id'
    '        elif name in ("message", "prompt", "query", "input", "content", "text"):'
    '            payload[name] = text'
    '        elif name == "messages":'
    '            payload[name] = [{"role": "user", "content": text}]'
    '        elif name in ("session_id", "conversation_id", "thread_id"):'
    '            payload[name] = "stage6d-test"'
    '        elif typ == "string":'
    '            payload[name] = "stage6d-test"'
    '        elif typ == "boolean":'
    '            payload[name] = False'
    '        elif typ == "integer":'
    '            payload[name] = 1'
    '        elif typ == "number":'
    '            payload[name] = 0'
    '        elif typ == "array":'
    '            payload[name] = []'
    '        elif typ == "object":'
    '            payload[name] = {}'
    ''
    '    if mode == "messages":'
    '        payload[mode] = [{"role": "user", "content": text}]'
    '    else:'
    '        payload[mode] = text'
    ''
    '    if "model" in properties and "model" not in payload and model_id:'
    '        if "model" in required:'
    '            payload["model"] = model_id'
    ''
    '    if send(mode, payload):'
    '        raise SystemExit(0)'
    ''
    'print("CHAT_E2E=FAIL")'
    'raise SystemExit(1)'
)

[System.IO.File]::WriteAllLines(
    $ChatProbe,
    $ChatProbeLines,
    $Utf8
)

$ErrorActionPreference = "Continue"

docker cp `
    $ChatProbe `
    redsight:/tmp/redsight_chat_probe.py

$ChatCopyExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

if ($ChatCopyExit -ne 0) {
    throw "Could not copy chat probe."
}

$ErrorActionPreference = "Continue"

$ChatOutput =
    docker exec `
        -w /app `
        redsight `
        python /tmp/redsight_chat_probe.py `
        2>&1

$ChatExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

$ChatOutput |
    ForEach-Object {
        Write-Host $_
    }

$ChatOutput |
    Out-String |
    Set-Content (
        Join-Path $BackupRoot `
            "redsight-chat-e2e.txt"
    )

Write-Host ""

if ($ChatExit -ne 0) {

    throw `
        "RedSight chat E2E still fails. Exact API response and schema were saved in redsight-chat-e2e.txt."
}

$ChatMode =
    "message"

foreach ($Line in $ChatOutput) {

    if ("$Line" -match '^CHAT_MODE=(.+)$') {

        $ChatMode =
            $Matches[1].Trim()

        break
    }
}

Write-Host "Working RedSight chat payload mode: $ChatMode"
Write-Host ""

# =====================================================================
# 13. IF API SCHEMA DIFFERS, UPDATE COMMAND CENTER PAYLOAD
# =====================================================================

if ($ChatMode -ne "message") {

    Write-Host "Updating Command Center request body to match working API schema."

    $UiText =
        [System.IO.File]::ReadAllText(
            $UI
        )

    $Old =
        'json={"message": message},'

    if (-not $UiText.Contains($Old)) {

        throw `
            "Command Center request body has changed and cannot be patched automatically."
    }

    $New = $null

    if ($ChatMode -eq "messages") {

        $New =
            'json={"messages": [{"role": "user", "content": message}]},'
    }

    if ($ChatMode -in @(
        "prompt",
        "query",
        "input",
        "content",
        "text"
    )) {

        $New =
            'json={"' +
            $ChatMode +
            '": message},'
    }

    if (-not $New) {
        throw "Unsupported automatically discovered UI chat mode: $ChatMode"
    }

    $UiText =
        $UiText.Replace(
            $Old,
            $New
        )

    Save-Utf8 `
        -Path $UI `
        -Text $UiText

    Write-Host "Command Center chat payload updated."
    Write-Host ""
}

# =====================================================================
# 14. AST VALIDATE COMMAND CENTER
# =====================================================================

$UiValidator =
    Join-Path $BackupRoot `
        "validate_ui.py"

$UiValidatorLines = @(
    'import ast'
    'import pathlib'
    ''
    'path = pathlib.Path("/source/app/ui/command_center.py")'
    'text = path.read_text(encoding="utf-8-sig")'
    'ast.parse(text, filename=str(path))'
    'print("COMMAND_CENTER_AST=OK")'
)

[System.IO.File]::WriteAllLines(
    $UiValidator,
    $UiValidatorLines,
    $Utf8
)

$ErrorActionPreference = "Continue"

$UiAst =
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

$UiAst |
    ForEach-Object {
        Write-Host $_
    }

if ($UiAstExit -ne 0) {
    throw "Command Center syntax validation failed."
}

Write-Host ""

# =====================================================================
# 15. CREATE / REUSE ISOLATED WINDOWS UI ENVIRONMENT
# =====================================================================

Write-Host "===================================================================="
Write-Host " 7. WINDOWS PYSIDE COMMAND CENTER"
Write-Host "===================================================================="

$BaseExe =
    $null

$BaseArgs =
    @()

$PyCommand =
    Get-Command py `
        -ErrorAction SilentlyContinue

if ($PyCommand) {

    $ErrorActionPreference = "Continue"

    & py -3.12 --version `
        2>$null

    $Python312Exit =
        $LASTEXITCODE

    $ErrorActionPreference = "Stop"

    if ($Python312Exit -eq 0) {

        $BaseExe =
            "py"

        $BaseArgs =
            @("-3.12")
    }
}

if (-not $BaseExe) {

    $PythonCommand =
        Get-Command python `
            -ErrorAction SilentlyContinue

    if ($PythonCommand) {

        $BaseExe =
            $PythonCommand.Source
    }
}

if (-not $BaseExe) {
    throw "No Windows Python installation was found."
}

if (-not (Test-Path $UiVenv)) {

    Write-Host "Creating isolated UI Python environment..."

    & $BaseExe `
        @BaseArgs `
        -m venv `
        $UiVenv

    if ($LASTEXITCODE -ne 0) {
        throw "Could not create .venv-ui."
    }
}

$UiPython =
    Join-Path $UiVenv `
        "Scripts\python.exe"

if (-not (Test-Path $UiPython)) {
    throw ".venv-ui Python executable is missing."
}

Write-Host "UI Python:"
Write-Host $UiPython
Write-Host ""

# =====================================================================
# 16. INSTALL UI DEPENDENCIES
# =====================================================================

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
    "PySide6>=6.8,<7" `
    httpx `
    psutil `
    structlog `
    pydantic `
    pydantic-settings `
    PyYAML `
    markdown `
    pygments `
    rich

if ($LASTEXITCODE -ne 0) {
    throw "UI dependencies could not be installed."
}

Write-Host ""

# =====================================================================
# 17. VERIFY PYSIDE + QTASYNCIO
# =====================================================================

$QtProbe =
    Join-Path $BackupRoot `
        "qt_probe.py"

$QtProbeLines = @(
    'import PySide6'
    'import PySide6.QtAsyncio as QtAsyncio'
    ''
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
    throw "PySide6.QtAsyncio is unavailable."
}

Write-Host ""

# =====================================================================
# 18. VERIFY COMMAND CENTER IMPORT ON WINDOWS
# =====================================================================

$ImportProbe =
    Join-Path $BackupRoot `
        "command_center_import.py"

$ImportLines = @(
    'import sys'
    'sys.path.insert(0, r"C:\Users\walim\RedSight")'
    'import app.ui.command_center as cc'
    'print("COMMAND_CENTER_IMPORT=OK")'
    'print("WINDOW_CLASS=" + str(hasattr(cc, "CommandCenterMainWindow")))'
)

[System.IO.File]::WriteAllLines(
    $ImportProbe,
    $ImportLines,
    $Utf8
)

$ErrorActionPreference = "Continue"

$ImportOutput =
    & $UiPython `
        $ImportProbe `
        2>&1

$ImportExit =
    $LASTEXITCODE

$ErrorActionPreference = "Stop"

$ImportOutput |
    ForEach-Object {
        Write-Host $_
    }

$ImportOutput |
    Out-String |
    Set-Content (
        Join-Path $BackupRoot `
            "command-center-import.txt"
    )

if ($ImportExit -ne 0) {
    throw "Command Center Windows import failed. Exact error is shown above."
}

if (($ImportOutput | Out-String) -notmatch 'WINDOW_CLASS=True') {
    throw "CommandCenterMainWindow class could not be found."
}

Write-Host ""

# =====================================================================
# 19. CREATE QTASYNCIO LAUNCH WRAPPER
#
# We intentionally DO NOT modify command_center.main().
#
# This wrapper:
# - creates QApplication
# - constructs CommandCenterMainWindow
# - forces correct RedSight API address
# - starts Qt + asyncio using QtAsyncio.run()
#
# Therefore asyncio.create_task() in _send_to_api() receives
# a real running asyncio event loop.
# =====================================================================

$UiLauncherPy =
    Join-Path $Root `
        "launch_redsight_command_center.py"

$UiLauncherLines = @(
    'import os'
    'import sys'
    ''
    'ROOT = r"C:\Users\walim\RedSight"'
    ''
    'if ROOT not in sys.path:'
    '    sys.path.insert(0, ROOT)'
    ''
    'os.environ["REDSIGHT_API_URL"] = "http://127.0.0.1:8000"'
    'os.environ["REDSIGHT_API_BASE_URL"] = "http://127.0.0.1:8000"'
    'os.environ["API_BASE_URL"] = "http://127.0.0.1:8000"'
    ''
    'from PySide6.QtWidgets import QApplication'
    'import PySide6.QtAsyncio as QtAsyncio'
    ''
    'from app.ui.command_center import CommandCenterMainWindow'
    ''
    'app = QApplication.instance()'
    ''
    'if app is None:'
    '    app = QApplication(sys.argv)'
    ''
    'window = CommandCenterMainWindow()'
    ''
    'if hasattr(window, "_api_base_url"):'
    '    window._api_base_url = "http://127.0.0.1:8000"'
    ''
    'window.show()'
    ''
    'print("COMMAND_CENTER_WINDOW_SHOWN=YES", flush=True)'
    ''
    '# Run the Qt event loop through QtAsyncio so callbacks can'
    '# safely call asyncio.create_task(...).'
    'QtAsyncio.run(handle_sigint=True)'
)

[System.IO.File]::WriteAllLines(
    $UiLauncherPy,
    $UiLauncherLines,
    $Utf8
)

Write-Host "QtAsyncio launcher created:"
Write-Host $UiLauncherPy
Write-Host ""

# =====================================================================
# 20. CREATE REUSABLE POWERSHELL LAUNCHER
# =====================================================================

$UiLauncherPs =
    Join-Path $Root `
        "LAUNCH-REDSIGHT-COMMAND-CENTER.ps1"

$UiLauncherPsLines = @(
    '$ErrorActionPreference = "Stop"'
    '$Root = "C:\Users\walim\RedSight"'
    '$Python = Join-Path $Root ".venv-ui\Scripts\python.exe"'
    '$Launcher = Join-Path $Root "launch_redsight_command_center.py"'
    'Set-Location $Root'
    '& $Python $Launcher'
)

[System.IO.File]::WriteAllLines(
    $UiLauncherPs,
    $UiLauncherPsLines,
    $Utf8
)

# =====================================================================
# 21. LAUNCH THE UI
# =====================================================================

Write-Host "===================================================================="
Write-Host " 8. LAUNCHING REDSIGHT COMMAND CENTER"
Write-Host "===================================================================="

$UiStdout =
    Join-Path $BackupRoot `
        "command-center.stdout.log"

$UiStderr =
    Join-Path $BackupRoot `
        "command-center.stderr.log"

$UiProcess =
    Start-Process `
        -FilePath $UiPython `
        -ArgumentList @(
            $UiLauncherPy
        ) `
        -WorkingDirectory $Root `
        -RedirectStandardOutput $UiStdout `
        -RedirectStandardError $UiStderr `
        -PassThru

Start-Sleep -Seconds 5

$UiProcess.Refresh()

if ($UiProcess.HasExited) {

    Write-Host ""
    Write-Host "Command Center exited during startup."
    Write-Host ""

    if (Test-Path $UiStdout) {

        Write-Host "=== STDOUT ==="

        Get-Content `
            $UiStdout `
            -Tail 100
    }

    if (Test-Path $UiStderr) {

        Write-Host ""
        Write-Host "=== STDERR ==="

        Get-Content `
            $UiStderr `
            -Tail 140
    }

    throw "Command Center launch failed."
}

Write-Host "COMMAND_CENTER_LAUNCHED=YES"
Write-Host "PID=$($UiProcess.Id)"
Write-Host ""

# =====================================================================
# 22. FINAL STATUS
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

Write-Host ""

docker exec `
    redsight `
    nvidia-smi -L

$ErrorActionPreference = "Stop"

Write-Host ""

$FinalHealth =
    Get-HttpCode `
        "http://127.0.0.1:8000/api/v1/health"

Write-Host "API health                : $FinalHealth"
Write-Host "Application startup       : $StartupOK"
Write-Host "NVML failure present      : $NvmlFailed"
Write-Host "LM health failure present : $LmFailed"
Write-Host "RedSight chat mode        : $ChatMode"
Write-Host "RedSight chat E2E         : PASS"
Write-Host "Command Center PID        : $($UiProcess.Id)"
Write-Host ""

Write-Host "===================================================================="
Write-Host " STAGE-6D COMPLETE"
Write-Host "===================================================================="
Write-Host ""

Write-Host "Reusable Command Center launcher:"
Write-Host $UiLauncherPs
Write-Host ""

Write-Host "Diagnostics:"
Write-Host $BackupRoot
Write-Host ""

Write-Host "Command Center stderr:"
Write-Host $UiStderr
Write-Host ""

Write-Host "Qdrant data and volumes were NOT modified or deleted."
Write-Host ""
